"""Exact lifecycle tests with controlled producers, never a live Codex/Herdr task."""
import base64
from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"
SPEC = importlib.util.spec_from_file_location("horch_exact_tests", SCRIPT)
h = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h)
c = h.completion
PRODUCER = Path(__file__).parent / "fixtures/codex_history.py"


class ExactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scenario = self.root / "scenario.json"
        self.scenario.write_text("{}")
        env = {"XDG_STATE_HOME": str(self.root / "ordinary"), "HERDR_ENV": "1",
               "HORCH_EXACT_STORE": str(self.root / "exact"),
               "HORCH_TEST_SCENARIO": str(self.scenario)}
        self.environment = patch.dict(os.environ, env)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        h.require_exact_store()
        self.directory = h.tasks_root() / "t-aabbcc"
        self.directory.mkdir(parents=True, mode=0o700)
        self.binary = self.root / "codex"
        self.binary.symlink_to("/usr/bin/true")
        self.context = {"executable": sys.executable, "sha256": c.executable_digest(sys.executable),
                        "argv": [str(PRODUCER)], "cwd": str(self.root),
                        "environment_sha256": c.environment_digest()}
        self.contract = {"mode": c.MODE, "schema": 1, "task_id": "t-aabbcc", "nonce": "a" * 32,
                         "expected_inputs": ["exclusive pointer with nonce " + "a" * 32],
                         "original_argv_sha256": c.digest([]), "reader": self.context}
        self.contract["digest"] = c.digest(self.contract)
        self.task = {"task_id": "t-aabbcc", "nonce": "a" * 32, "worker": "solo",
                     "agent": "horch-aabbcc", "pane_id": "w1:p2", "workspace_id": "w1",
                     "result_path": str(self.directory / "result.json"),
                     "created_at": "2020-01-01T00:00:00Z", "completion": self.contract}
        h.write_json(self.directory / "task.json", self.task)
        state = h.default_state()
        state["exact"] = {"kind": "active", "dispatch_intent": True, "task_digest": c.digest(self.task)}
        h.write_json(self.directory / "state.json", state)
        self.frozen = {"contract": self.contract, "directory": str(self.directory), "notifier": []}
        self.result = {"task_id": "t-aabbcc", "nonce": "a" * 32, "status": "completed",
                       "summary": "original snapshot", "files": ["report.md"], "question": None}
        self.info = h.make_info("t-aabbcc")
        self.config = {"max_active_workers": 4, "notify_after_minutes": 180,
                       "roles": {}, "workers": {"solo": {"harness": "codex", "model": "test",
                       "provider": None, "effort": None, "args": ["-c", 'notify=["/usr/bin/true"]']}}}

    def scenario_value(self, **values):
        self.scenario.write_text(json.dumps(values))

    def event(self, **overrides):
        value = {"type": "agent-turn-complete", "input-messages": self.contract["expected_inputs"],
                 "thread-id": "thread", "turn-id": "turn"}
        value.update(overrides)
        return json.dumps(value)

    def callback(self, **overrides):
        c.accept_notify(self.frozen, self.event(**overrides))

    def publish_result(self, **overrides):
        h.write_json(self.directory / "result.json", {**self.result, **overrides})

    def poll(self, seconds=2):
        h.poll_exact(self.info, time.monotonic() + seconds)
        return h.wait_line(self.info)

    def qualify_inputs(self):
        self.callback()
        self.publish_result()

    def proof(self):
        candidate = c.binding(self.directory, self.contract)
        return {"contract_digest": self.contract["digest"], "binding_digest": c.digest(candidate),
                "thread_id": "thread", "turn_id": "turn", "status": "completed",
                "response_sha256": c.digest("fixture")}

    def test_positive_proof_commits_snapshot_and_all_readers_replay_it(self):
        self.qualify_inputs()
        with patch.object(h, "close_pane", return_value="closed") as close:
            line = self.poll()
            self.assertEqual((line["state"], line["summary"], line["closed"]),
                             ("done", "original snapshot", True))
            close.assert_called_once_with("w1:p2")
        self.publish_result(summary="later changed bytes", status="failed")
        recovered = h.make_info("t-aabbcc")
        self.assertEqual(h.wait_line(recovered)["summary"], "original snapshot")
        self.assertEqual(h.wait_line(recovered)["result"]["status"], "completed")
        with patch.object(h, "load_config", return_value=self.config), redirect_stdout(io.StringIO()) as out:
            h.main(["stats"])
        row = json.loads(out.getvalue())["workers"]["solo"]
        self.assertEqual(row["result_statuses"], {"completed": 1})
        self.assertEqual(row["duration_samples"][0]["endpoint_source"], "first_done_at")

    def test_early_result_and_foreign_callback_never_query_or_deliver(self):
        self.publish_result()
        for values in ({"thread-id": "foreign", "input-messages": ["another pointer"]},
                       {"input-messages": self.contract["expected_inputs"] + ["extra"]},
                       {"type": "other"}):
            self.callback(**values)
        self.assertFalse((self.directory / "completion.json").exists())
        with patch.object(c, "observe") as observe, patch.object(h, "close_pane") as close:
            line = self.poll()
        observe.assert_not_called()
        close.assert_not_called()
        self.assertIsNone(line["summary"])
        self.assertIn("unverified", line["message"])

    def test_duplicate_callback_and_unchanged_poll_are_noops(self):
        self.callback()
        path = self.directory / "completion.json"
        initial = path.stat().st_mtime_ns
        self.callback()
        self.assertEqual(path.stat().st_mtime_ns, initial)
        self.scenario_value(pages=[{"data": []}])
        self.poll()
        with patch.object(h, "write_json", wraps=h.write_json) as write:
            self.poll()
        write.assert_not_called()

    def test_conflicting_matching_identity_is_permanent(self):
        self.qualify_inputs()
        self.callback(**{"thread-id": "other"})
        self.callback()
        with patch.object(c, "observe") as observe, patch.object(h, "close_pane") as close:
            line = self.poll()
        self.assertIsNone(line["summary"])
        self.assertIn("binding_conflict", line["message"])
        observe.assert_not_called()
        close.assert_not_called()

    def test_late_conflict_keeps_snapshot_and_reports_association_limit(self):
        self.qualify_inputs()
        with patch.object(h, "close_pane", return_value="closed"):
            self.poll()
            self.callback(**{"turn-id": "different"})
            line = self.poll()
        self.assertEqual(line["summary"], "original snapshot")
        self.assertIn("assumption violated", line["message"])

    def test_native_nonpositive_and_malformed_responses_remain_retryable(self):
        self.qualify_inputs()
        scenarios = [{"pages": [{"data": [{"id": "turn", "status": status}]}]}
                     for status in ("inProgress", "interrupted", "failed", "unknown", None)]
        scenarios += [{"pages": [{"data": []}]}, {"malformed": True}, {"error": True},
                      {"eof": True}, {"request": True}, {"id_offset": 1}, {"flood": True},
                      {"pages": [{"data": [{"id": "turn", "status": "completed", "error": {}}]}]},
                      {"pages": [{"data": [{"id": "turn", "status": "completed"}] * 2}]}]
        with patch.object(h, "close_pane") as close:
            for scenario in scenarios:
                with self.subTest(scenario=scenario):
                    self.scenario_value(**scenario)
                    self.assertIsNone(self.poll()["summary"])
                    self.assertTrue(h.observable(self.info))
            close.assert_not_called()
        self.scenario_value()
        with patch.object(h, "close_pane", return_value="closed"):
            self.assertEqual(self.poll()["state"], "done")

    def test_history_queries_exact_bound_thread_with_bounded_pagination(self):
        self.qualify_inputs()
        requests = self.root / "requests.jsonl"
        self.scenario_value(requests=str(requests), pages=[
            {"data": [{"id": "foreign", "status": "completed"}], "nextCursor": "next"},
            {"data": [{"id": "turn", "status": "completed", "error": None}]}])
        with patch.object(h, "close_pane", return_value="closed"):
            self.assertEqual(self.poll()["state"], "done")
        records = [json.loads(line) for line in requests.read_text().splitlines()]
        self.assertEqual([r["method"] for r in records],
                         ["initialize", "initialized", "thread/turns/list", "thread/turns/list"])
        for request in records[2:]:
            self.assertEqual(request["params"]["threadId"], "thread")
            self.assertEqual(request["params"]["itemsView"], "notLoaded")
        self.assertEqual(records[-1]["params"]["cursor"], "next")

    def test_repeated_cursor_and_page_cap_do_not_authorize(self):
        self.qualify_inputs()
        for pages in ([{"data": [], "nextCursor": "same"}] * 4,
                      [{"data": [], "nextCursor": str(n)} for n in range(4)]):
            self.scenario_value(pages=pages)
            with patch.object(h, "close_pane") as close:
                self.assertIsNone(self.poll()["summary"])
                close.assert_not_called()

    def test_zero_budget_performs_no_rpc_and_no_cleanup(self):
        self.qualify_inputs()
        with patch.object(c, "observe") as observe, patch.object(h, "close_pane") as close:
            self.poll(seconds=0)
        observe.assert_not_called()
        close.assert_not_called()

    def test_wrong_nonce_malformed_symlink_or_oversized_result_is_withheld(self):
        self.callback()
        for result in ({**self.result, "nonce": "old"}, {"status": "completed"},
                       {**self.result, "summary": "x" * (256 * 1024)}):
            h.write_json(self.directory / "result.json", result)
            with patch.object(h, "close_pane") as close:
                self.assertIsNone(self.poll()["summary"])
                close.assert_not_called()
        target = self.root / "other-result"
        target.write_text(json.dumps(self.result))
        (self.directory / "result.json").unlink()
        (self.directory / "result.json").symlink_to(target)
        with patch.object(h, "close_pane") as close:
            self.assertIsNone(self.poll()["summary"])
            close.assert_not_called()

    def test_failed_or_blocked_worker_result_is_deliverable_after_completed_engine(self):
        self.callback()
        self.publish_result(status="blocked", question="Need an answer")
        with patch.object(h, "close_pane", return_value="closed"):
            line = self.poll()
        self.assertEqual(line["state"], "done")
        self.assertEqual(line["question"], "Need an answer")

    def test_close_during_query_persists_cancellation_before_rpc(self):
        self.qualify_inputs()
        querying, release = threading.Event(), threading.Event()
        proof = self.proof()
        errors = []
        def observe(*_):
            querying.set()
            self.assertTrue(release.wait(3))
            return proof
        def run_poll():
            try:
                self.poll()
            except Exception as error:
                errors.append(error)
        def pane_close(_):
            control = h.read_json(self.directory / "state.json")["exact"]
            self.assertEqual(control["kind"], "cancel_requested")
            release.set()
            return "closed"
        with patch.object(c, "observe", side_effect=observe), \
                patch.object(h, "close_pane", side_effect=pane_close) as close:
            waiter = threading.Thread(target=run_poll)
            waiter.start()
            self.assertTrue(querying.wait(3))
            h.exact_cleanup(h.make_info("t-aabbcc"), explicit=True)
            waiter.join(3)
            self.assertFalse(waiter.is_alive())
            close.assert_called_once()
        self.assertFalse(errors)
        line = h.wait_line(h.make_info("t-aabbcc"))
        self.assertTrue(line["closed"])
        self.assertIsNone(line["summary"])

    def test_failed_close_retains_cancellation_and_blocks_future_delivery(self):
        self.qualify_inputs()
        with patch.object(h, "close_pane", side_effect=h.HerdrError("PRIVATE")):
            h.exact_cleanup(self.info, explicit=True)
        self.assertEqual(h.read_json(self.directory / "state.json")["exact"]["kind"], "cancel_requested")
        self.assertIsNone(h.read_json(self.directory / "state.json")["settled_at"])
        self.assertIsNone(h.read_json(self.directory / "state.json")["first_done_at"])
        with patch.object(c, "observe") as observe, patch.object(h, "close_pane") as close:
            self.assertIsNone(self.poll()["summary"])
        observe.assert_not_called()
        close.assert_not_called()
        with patch.object(h, "close_pane", return_value="closed"):
            h.exact_cleanup(h.make_info("t-aabbcc"), explicit=True)
        self.assertTrue(h.wait_line(h.make_info("t-aabbcc"))["closed"])

    def test_failed_delivery_commit_cannot_output_or_close_and_recovery_never_resends(self):
        self.qualify_inputs()
        original = h.write_json
        def fail_commit(path, value):
            if value.get("exact", {}).get("kind") == "delivered":
                raise OSError("injected commit failure")
            original(path, value)
        with patch.object(h, "write_json", side_effect=fail_commit), patch.object(h, "close_pane") as close:
            with self.assertRaises(OSError):
                self.poll()
            close.assert_not_called()
        self.assertIsNone(h.wait_line(h.make_info("t-aabbcc"))["summary"])
        self.info = h.make_info("t-aabbcc")
        with patch.object(h, "herdr", side_effect=AssertionError("must never replay")), \
                patch.object(h, "close_pane", return_value="closed"):
            self.assertEqual(self.poll()["state"], "done")

    def test_failed_cancel_commit_never_calls_pane_rpc(self):
        with patch.object(h, "write_json", side_effect=OSError("failure")), \
                patch.object(h, "close_pane") as close:
            with self.assertRaises(OSError):
                h.exact_cleanup(self.info, explicit=True)
            close.assert_not_called()
        self.assertEqual(h.read_json(self.directory / "state.json")["exact"]["kind"], "active")

    def test_recover_committed_delivery_retries_only_cleanup(self):
        self.qualify_inputs()
        with patch.object(h, "exact_cleanup", side_effect=RuntimeError("observer death after commit")):
            with self.assertRaises(RuntimeError):
                self.poll()
        self.publish_result(summary="must not replace delivered bytes")
        self.info = h.make_info("t-aabbcc")
        with patch.object(c, "observe") as observe, \
                patch.object(h, "close_pane", return_value="closed") as close:
            line = self.poll()
        observe.assert_not_called()
        close.assert_called_once()
        self.assertEqual(line["summary"], "original snapshot")

    def test_corrupt_committed_snapshot_never_falls_back_to_mutable_worker_file(self):
        self.qualify_inputs()
        with patch.object(h, "close_pane", return_value="closed"):
            self.poll()
        state = h.read_json(self.directory / "state.json")
        state["exact"]["result_bytes"] = base64.b64encode(b"{}").decode()
        h.write_json(self.directory / "state.json", state)
        with self.assertRaises(c.Unverified):
            h.make_info("t-aabbcc")

    def test_fresh_cancellation_and_identity_or_candidate_change_during_query(self):
        self.qualify_inputs()
        proof = self.proof()
        def conflicting(*_):
            self.callback(**{"thread-id": "other"})
            return proof
        with patch.object(c, "observe", side_effect=conflicting), patch.object(h, "close_pane") as close:
            self.assertIsNone(self.poll()["summary"])
            close.assert_not_called()

    def test_unknown_contract_and_corrupt_control_fail_closed(self):
        task = copy.deepcopy(self.task)
        task["completion"]["mode"] = "future"
        h.write_json(self.directory / "task.json", task)
        with self.assertRaises(h.TaskInvalidError):
            h.make_info("t-aabbcc")
        h.write_json(self.directory / "task.json", self.task)
        h.write_json(self.directory / "state.json", {"state": "done"})
        with self.assertRaises(c.Unverified):
            h.make_info("t-aabbcc")

    def test_simultaneous_observers_commit_one_delivery_and_cleanup_once(self):
        self.qualify_inputs()
        barrier = threading.Barrier(2)
        proof = self.proof()
        errors = []
        def observe(*_):
            barrier.wait(timeout=3)
            return proof
        def wait():
            try:
                h.poll_exact(h.make_info("t-aabbcc"), time.monotonic() + 3)
            except Exception as error:
                errors.append(error)
        with patch.object(c, "observe", side_effect=observe), \
                patch.object(h, "close_pane", return_value="closed") as close:
            threads = [threading.Thread(target=wait) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(4)
                self.assertFalse(thread.is_alive())
            close.assert_called_once()
        self.assertFalse(errors)
        self.assertEqual(h.wait_line(h.make_info("t-aabbcc"))["state"], "done")

    def test_launch_identity_change_withholds_previously_observed_proof(self):
        self.qualify_inputs()
        proof = self.proof()
        def changed(*_):
            h.write_json(self.directory / "task.json", {**self.task, "pane_id": "other"})
            return proof
        with patch.object(c, "observe", side_effect=changed), patch.object(h, "close_pane") as close:
            self.assertIsNone(self.poll()["summary"])
            close.assert_not_called()

    def test_old_nonce_callback_and_unrecorded_dispatch_cannot_bind_delivery(self):
        frozen = copy.deepcopy(self.frozen)
        frozen["contract"]["nonce"] = "b" * 32
        frozen["contract"].pop("digest")
        frozen["contract"]["digest"] = c.digest(frozen["contract"])
        with self.assertRaises(c.Unverified):
            c.accept_notify(frozen, self.event())
        self.assertFalse((self.directory / "completion.json").exists())
        self.qualify_inputs()
        state = h.read_json(self.directory / "state.json")
        state["exact"]["dispatch_intent"] = False
        h.write_json(self.directory / "state.json", state)
        with patch.object(c, "observe") as observe:
            self.assertIsNone(self.poll()["summary"])
        observe.assert_not_called()

    def test_direct_scripts_and_empty_notifier_are_not_production_launches(self):
        script = self.root / "fake/codex"
        script.parent.mkdir()
        script.write_text("#!/bin/sh\nexit 0\n")
        for argv, binary in ((["-c", 'notify=["/usr/bin/true"]'], script),
                             (["-c", "notify=[]"], self.binary)):
            with self.assertRaises(c.Unverified):
                c.prepare(argv, self.directory, "t-aabbcc", "a" * 32, "pointer", self.root,
                          executable=str(binary))

    def test_reader_context_change_and_wrong_attempt_receipt_are_unverified(self):
        self.qualify_inputs()
        with patch.object(c, "environment_digest", return_value="changed"):
            self.assertIsNone(self.poll()["summary"])
        receipt = h.read_json(self.directory / "completion.json")
        receipt["nonce"] = "b" * 32
        h.write_json(self.directory / "completion.json", receipt)
        with patch.object(c, "observe") as observe:
            self.assertIsNone(self.poll()["summary"])
        observe.assert_not_called()

    def test_unacknowledged_dispatch_is_still_ordinary_wait_eligible(self):
        state = h.read_json(self.directory / "state.json")
        state["state"] = "not_started"
        h.write_json(self.directory / "state.json", state)
        self.qualify_inputs()
        with patch.object(h, "load_config", return_value=self.config), \
                patch.object(h, "close_pane", return_value="closed"), redirect_stdout(io.StringIO()) as out:
            h.main(["wait", "--max-seconds", "2"])
        self.assertEqual(json.loads(out.getvalue())["summary"], "original snapshot")

    def test_legacy_null_sequence_keeps_original_completion_contract(self):
        task = {k: v for k, v in self.task.items() if k != "completion"}
        h.write_json(self.directory / "task.json", task)
        state = h.default_state()
        state["baseline_seq"] = None
        state["saw_working"] = True
        h.write_json(self.directory / "state.json", state)
        self.publish_result()
        info = h.make_info("t-aabbcc")
        with patch.object(h, "agent_index", return_value={task["agent"]: {
                "agent_status": "idle", "completion_seq": None}}), \
                patch.object(c, "observe") as observe, patch.object(h, "close_pane", return_value="closed"):
            h.poll_round([info], {"t-aabbcc": "running"}, self.config)
        self.assertEqual(h.wait_line(info)["state"], "done")
        observe.assert_not_called()

    def test_store_requires_new_private_separate_selection_and_quotas_are_independent(self):
        with patch.dict(os.environ, {"HORCH_EXACT_STORE": ""}):
            with self.assertRaises(c.Unverified):
                h.require_exact_store()
            self.assertEqual(h.task_capacity("w1")[0], 0)
        self.assertEqual(h.task_capacity("w1")[0], 1)
        ordinary = h.ordinary_tasks_root()
        with patch.dict(os.environ, {"HORCH_EXACT_STORE": str(ordinary)}):
            with self.assertRaises(c.Unverified):
                h.require_exact_store()
        used = self.root / "used"
        used.mkdir(mode=0o700)
        (used / "unrelated").write_text("preserve")
        with patch.dict(os.environ, {"HORCH_EXACT_STORE": str(used)}):
            with self.assertRaises(c.Unverified):
                h.require_exact_store()
        self.assertEqual((used / "unrelated").read_text(), "preserve")

    def test_supported_notifier_slot_is_replaced_in_place_without_other_argv_changes(self):
        original = ["-m", "m", "-c", 'model_reasoning_effort="high"', "--profile", "p",
                    "--add-dir", str(self.directory), "-c", 'notify=["notify-tool", "a b", "$()`"]',
                    "--sandbox", "workspace-write", "--no-alt-screen"]
        argv, contract = c.prepare(original, self.directory, "t-aabbcc", "a" * 32,
                                   "pointer", self.root, executable=str(self.binary))
        self.assertEqual(argv[:9], original[:9])
        self.assertEqual(argv[10:], original[10:])
        wrapper = __import__("tomllib").loads(argv[9])["notify"]
        frozen = c.decode(wrapper[-1])
        self.assertEqual(frozen["notifier"], ["notify-tool", "a b", "$()`"])
        self.assertEqual(contract["reader"]["argv"], ["-c", 'model_reasoning_effort="high"', "--profile", "p"])
        self.assertEqual(original[9], 'notify=["notify-tool", "a b", "$()`"]')

    def test_unsupported_or_ambiguous_notify_is_rejected_before_pane_creation(self):
        unsupported = [[], ["-c", "notify=[]", "-c", "notify=[]"], ["--config=notify=[]"],
                       ["-cnotify=[]"], ["-c", '"notify"=[]'], ["-c", "notify.x=[]"],
                       ["-c", "notify=oops"], ["-c", 'notify=[""]'], ["-c", "notify=1"],
                       ["resume", "-c", "notify=[]"], ["-c", "notify=[]", "prompt"],
                       ["-c", "notify=[]", "--unknown"], ["-c", "notify=[]", "-c", 'profile="x"']]
        with patch.object(h, "require_caller_context", return_value={"workspace_id": "w1", "tab_id": "t"}), \
                patch.object(h, "place_pane") as pane, patch.object(h, "herdr") as herdr:
            for argv in unsupported:
                with self.subTest(argv=argv):
                    config = copy.deepcopy(self.config)
                    config["workers"]["solo"]["args"] = argv
                    with self.assertRaises(c.Unverified):
                        h.start_task(config, "solo", "brief", self.root, completion_mode=c.MODE)
            pane.assert_not_called()
            herdr.assert_not_called()

    def test_notifier_receives_identical_raw_foreign_malformed_and_failed_receipt(self):
        output = self.root / "notified.jsonl"
        target = self.root / "notifier.py"
        target.write_text("import json,os,sys\nfrom pathlib import Path\n"
                          "with open(sys.argv[1], 'a') as out:\n"
                          " out.write(json.dumps([sys.argv[2:],os.getcwd(),os.environ.get('HORCH_FORWARD_TEST')])+'\\n')\n"
                          "sys.exit(23)\n")
        frozen = {**self.frozen, "notifier": [sys.executable, str(target), str(output), "literal $()`"]}
        duplicate_mtime = None
        for index, raw in enumerate((self.event(**{"input-messages": ["foreign"]}), "not JSON",
                                     self.event(), self.event(), self.event())):
            if index == 4:
                (self.directory / "completion.json").unlink()
                (self.directory / "completion.json").mkdir()
            with patch.dict(os.environ, {"HORCH_FORWARD_TEST": "inherited"}):
                proc = subprocess.run([sys.executable, str(Path(c.__file__)), "notify", c.encode(frozen), raw],
                                      cwd=self.root, capture_output=True, text=True, timeout=3)
            self.assertEqual(proc.returncode, 23)
            self.assertEqual((proc.stdout, proc.stderr), ("", ""))
            if index == 2:
                duplicate_mtime = (self.directory / "completion.json").stat().st_mtime_ns
            if index == 3:
                self.assertEqual((self.directory / "completion.json").stat().st_mtime_ns, duplicate_mtime)
        rows = [json.loads(row) for row in output.read_text().splitlines()]
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-1], [["literal $()`", self.event()], str(self.root), "inherited"])

    def test_timeout_is_bounded_and_does_not_settle_or_close(self):
        self.qualify_inputs()
        self.scenario_value(hang=True)
        began = time.monotonic()
        with patch.object(h, "close_pane") as close:
            line = self.poll(seconds=0.15)
            close.assert_not_called()
        self.assertLess(time.monotonic() - began, 2)
        self.assertIn("native_timeout", line["message"])
        self.assertTrue(h.observable(self.info))

    def test_observer_sigkill_kills_owned_reader_group_and_recovers_without_replay(self):
        self.qualify_inputs()
        pids_path = self.root / "pids.json"
        self.scenario_value(hang=True, pids=str(pids_path))
        driver = self.root / "observer.py"
        driver.write_text("import importlib.util,time\n"
                          f"spec=importlib.util.spec_from_file_location('horch', {str(SCRIPT)!r})\n"
                          "h=importlib.util.module_from_spec(spec); spec.loader.exec_module(h)\n"
                          "h.poll_exact(h.make_info('t-aabbcc'),time.monotonic()+20)\n")
        observer = subprocess.Popen([sys.executable, str(driver)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: observer.poll() is None and observer.kill())
        deadline = time.monotonic() + 3
        while not pids_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(pids_path.exists())
        pids = json.loads(pids_path.read_text())
        observer.kill()
        observer.communicate(timeout=2)
        def alive(pid):
            try:
                return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
            except FileNotFoundError:
                return False
        deadline = time.monotonic() + 2
        while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(any(alive(pid) for pid in pids), "owned reader/initializer survived observer death")
        self.scenario_value()
        self.info = h.make_info("t-aabbcc")
        with patch.object(h, "herdr", side_effect=AssertionError("no replay")), \
                patch.object(h, "close_pane", return_value="closed"):
            self.assertEqual(self.poll()["summary"], "original snapshot")

    def test_actual_launch_callback_wait_and_check_snapshot_callers(self):
        submitted = []
        original_prepare = c.prepare
        def controlled_prepare(argv, directory, task_id, nonce, pointer, cwd):
            argv, contract = original_prepare(argv, directory, task_id, nonce, pointer, cwd,
                                              executable=str(self.binary))
            # Controlled producer, explicitly not installed-Codex qualification.
            contract["reader"] = self.context
            contract.pop("digest")
            contract["digest"] = c.digest(contract)
            frozen = {"contract": contract, "directory": str(directory), "notifier": []}
            slot = next(i for i, value in enumerate(argv) if value.startswith("notify="))
            wrapper = [sys.executable, str(Path(c.__file__)), "notify", c.encode(frozen)]
            argv[slot] = "notify=" + json.dumps(wrapper)
            return argv, contract
        def herdr(*args, **kwargs):
            if args[:2] == ("agent", "start"):
                return {"result": {"type": "agent_started"}}
            if args[:2] == ("agent", "read"):
                return "\n› \n"
            if args[:2] == ("agent", "prompt"):
                submitted.append(args[3])
                task_id = args[2].replace("horch-", "t-")
                directory = h.task_dir(task_id)
                task = h.load_task(directory, task_id)
                state = h.read_json(directory / "state.json")
                self.assertTrue(state["exact"]["dispatch_intent"])
                self.assertEqual(task["completion"]["expected_inputs"], [args[3]])
                result = {**self.result, "task_id": task_id, "nonce": task["nonce"]}
                h.write_json(directory / "result.json", result)
                frozen = {"contract": task["completion"], "directory": str(directory), "notifier": []}
                event = {"type": "agent-turn-complete", "thread-id": "thread", "turn-id": "turn",
                         "input-messages": [args[3]]}
                proc = subprocess.run([sys.executable, str(Path(c.__file__)), "notify", c.encode(frozen),
                                       json.dumps(event)], capture_output=True, timeout=3)
                self.assertEqual(proc.returncode, 0)
                return {"result": {"agent": {"agent_status": "idle", "completion_seq": None}}}
            self.fail(f"unexpected Herdr command {args[:2]}")
        with patch.object(c, "prepare", side_effect=controlled_prepare), \
                patch.object(h, "require_caller_context", return_value={"workspace_id": "w1", "tab_id": "t"}), \
                patch.object(h, "place_pane", return_value=("w1:p3", "w1:t2")), \
                patch.object(h, "agent_index", return_value={}), patch.object(h, "herdr", side_effect=herdr), \
                patch.object(h, "load_config", return_value=self.config), \
                patch.object(h, "close_pane", return_value="closed"):
            run = h.start_task(self.config, "solo", "one brief", self.root, completion_mode=c.MODE)
            self.assertEqual(run["state"], "running")
            with redirect_stdout(io.StringIO()) as out:
                h.main(["wait", run["task_id"], "--max-seconds", "3"])
            self.assertEqual(json.loads(out.getvalue())["summary"], "original snapshot")
            # cmd_check must use the committed snapshot even if cleanup mutates
            # the worker's original result after the delivery commit.
            real_cleanup = h.exact_cleanup
            def mutate(info, **kwargs):
                answer = real_cleanup(info, **kwargs)
                (info["dir"] / "result.json").write_text("broken after delivery")
                return answer
            with patch.object(h, "exact_cleanup", side_effect=mutate), redirect_stdout(io.StringIO()) as out:
                h.main(["check", "solo", "--completion", c.MODE, "--max-seconds", "3"])
            self.assertTrue(json.loads(out.getvalue())["ok"])
        self.assertEqual(len(submitted), 2)
        self.assertNotEqual(submitted[0], submitted[1])


if __name__ == "__main__":
    unittest.main()
