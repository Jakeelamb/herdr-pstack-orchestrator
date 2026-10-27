"""Poll persistence retains lifecycle changes and avoids unchanged replacements."""
from argparse import Namespace
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timezone
import fcntl
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"
SPEC = importlib.util.spec_from_file_location("horch_poll", SCRIPT)
horch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(horch)


class PollPersistenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "state.json"
        self.task = {
            "task_id": "t-123abc", "nonce": "nonce", "worker": "solo",
            "agent": "horch-123abc", "pane_id": "w1:p2",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "result_path": str(self.directory / "result.json"),
        }
        self.info = {"task_id": self.task["task_id"], "task": self.task,
                     "dir": self.directory}
        self.config = {"notify_after_minutes": 180}
        self.previous = {}
        self.agent = {"agent_status": "working"}
        self.store(saw_working=True, baseline_seq=10)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(
            horch, "agent_index", side_effect=lambda: {self.task["agent"]: self.agent}))
        self.notice = self.stack.enter_context(patch.object(horch, "notify"))
        self.close = self.stack.enter_context(patch.object(horch, "close_pane", return_value="closed"))
        self.stack.enter_context(patch.object(
            horch, "herdr", side_effect=AssertionError("unexpected live Herdr call")))
        self.replace = horch.os.replace
        self.replacements = self.stack.enter_context(patch.object(
            horch.os, "replace", wraps=self.replace))

    def store(self, **fields):
        state = horch.default_state()
        state.update(fields)
        self.path.write_text(json.dumps(state))
        return state

    def poll(self):
        return horch.poll_round([self.info], self.previous, self.config)

    def result(self):
        value = {"task_id": self.task["task_id"], "nonce": self.task["nonce"],
                 "status": "completed", "summary": "Controlled result", "files": [],
                 "question": None}
        (self.directory / "result.json").write_text(json.dumps(value))

    def assert_lock_held(self):
        with (self.directory / ".state.lock").open("a") as lock:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_unchanged_polls_preserve_file_and_report_initial_state(self):
        before = self.path.read_bytes()
        initial_stat = self.path.stat()
        for round_number in range(10):
            self.assertEqual(self.poll(), (round_number == 0, True))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_ino, initial_stat.st_ino)
        self.assertEqual(self.path.stat().st_mtime_ns, initial_stat.st_mtime_ns)
        self.replacements.assert_not_called()
        self.notice.assert_not_called()
        self.close.assert_not_called()

    def test_working_observation_persists_without_a_reported_state_change(self):
        self.store(baseline_seq=10)
        self.previous[self.task["task_id"]] = "running"
        self.assertEqual(self.poll(), (False, True))
        self.assertTrue(horch.load_state(self.directory)["saw_working"])
        self.assertEqual(self.replacements.call_count, 1)
        self.poll()
        self.assertEqual(self.replacements.call_count, 1)

    def test_boolean_observation_replaces_a_legacy_numeric_value(self):
        self.store(saw_working=1)
        self.poll()
        self.assertIs(json.loads(self.path.read_text())["saw_working"], True)
        self.assertEqual(self.replacements.call_count, 1)

    def test_running_problem_is_cleared_without_a_reported_state_change(self):
        self.store(saw_working=True, problem="stale observation")
        self.previous[self.task["task_id"]] = "running"
        self.assertEqual(self.poll(), (False, True))
        self.assertIsNone(horch.load_state(self.directory)["problem"])
        self.assertEqual(self.replacements.call_count, 1)
        self.poll()
        self.assertEqual(self.replacements.call_count, 1)

    def test_normalization_repairs_missing_corrupt_and_legacy_files_once(self):
        variants = [None, b"{broken", b"\xff", b"null", b"[]", b"7",
                    b"{}", b'{"saw_working": true}',
                    json.dumps({**horch.default_state(), "unknown": "legacy"}).encode()]
        for raw in variants:
            with self.subTest(raw=raw):
                self.path.unlink(missing_ok=True)
                if raw is not None:
                    self.path.write_bytes(raw)
                self.replacements.reset_mock()
                self.poll()
                self.assertEqual(json.loads(self.path.read_text()),
                                 {**horch.default_state(), "saw_working": True})
                self.assertEqual(self.replacements.call_count, 1)
                self.poll()
                self.assertEqual(self.replacements.call_count, 1)

    def test_missing_file_is_created_even_when_evaluation_does_not_change_defaults(self):
        self.path.unlink()
        self.agent = {"agent_status": "idle"}
        self.poll()
        self.assertEqual(json.loads(self.path.read_text()), horch.default_state())
        self.assertEqual(self.replacements.call_count, 1)
        self.poll()
        self.assertEqual(self.replacements.call_count, 1)

    def test_equivalent_key_order_and_format_do_not_require_replacement(self):
        state = horch.load_state(self.directory)
        self.path.write_text(json.dumps(dict(reversed(list(state.items()))), indent=4))
        before = self.path.read_bytes()
        self.poll()
        self.assertEqual(self.path.read_bytes(), before)
        self.replacements.assert_not_called()

    def test_notification_flag_persists_once_across_a_restart(self):
        self.task["created_at"] = "2020-01-01T00:00:00Z"
        self.assertEqual(self.poll(), (True, True))
        self.assertEqual(self.info["reported"], "long_running")
        self.assertTrue(horch.load_state(self.directory)["long_notified"])
        self.assertEqual(self.replacements.call_count, 1)
        self.notice.assert_called_once()
        self.info = {"task_id": self.task["task_id"], "task": self.task, "dir": self.directory}
        self.previous = {}
        self.poll()
        self.assertEqual(self.info["reported"], "running")
        self.assertEqual(self.replacements.call_count, 1)
        self.notice.assert_called_once()

    def test_problem_and_settlement_persist_then_recheck_recovers(self):
        self.agent = {"agent_status": "blocked"}
        self.poll()
        blocked = horch.load_state(self.directory)
        self.assertEqual(blocked["state"], "blocked")
        self.assertIn("waiting at a dialog", blocked["problem"])
        self.assertIsNotNone(blocked["settled_at"])
        self.assertIsNone(blocked["first_done_at"])
        self.assertEqual(self.replacements.call_count, 1)
        self.agent = {"agent_status": "working"}
        self.poll()
        self.assertEqual(horch.load_state(self.directory), blocked)
        self.info["recheck"] = True
        self.poll()
        recovered = horch.load_state(self.directory)
        self.assertEqual(recovered["state"], "running")
        self.assertIsNone(recovered["problem"])
        self.assertEqual(recovered["settled_at"], blocked["settled_at"])
        self.assertEqual(self.replacements.call_count, 2)
        self.poll()
        self.assertEqual(self.replacements.call_count, 2)

    def test_early_result_is_withheld_then_delivery_and_closure_persist(self):
        self.result()
        self.poll()
        line = horch.wait_line(self.info)
        self.assertEqual(line["state"], "running")
        self.assertIsNone(line["summary"])
        self.replacements.assert_not_called()
        self.agent = {"agent_status": "idle", "completion_seq": 11}
        self.poll()
        done = horch.load_state(self.directory)
        self.assertEqual(done["state"], "done")
        self.assertTrue(done["closed"])
        self.assertIsNotNone(done["settled_at"])
        self.assertIsNotNone(done["first_done_at"])
        self.assertEqual(self.replacements.call_count, 2)
        self.assertEqual(horch.wait_line(self.info)["summary"], "Controlled result")
        self.info = {"task_id": self.task["task_id"], "task": self.task,
                     "dir": self.directory, "recheck": True}
        self.poll()
        self.assertEqual(horch.load_state(self.directory), done)
        self.assertEqual(self.replacements.call_count, 2)
        self.close.assert_called_once()

    def test_idle_without_fresh_completion_does_not_deliver_after_restart(self):
        self.store(baseline_seq=10)
        self.result()
        self.agent = {"agent_status": "idle", "completion_seq": 10}
        self.poll()
        self.assertEqual(horch.load_state(self.directory)["state"], "running")
        self.replacements.assert_not_called()
        self.agent["completion_seq"] = 11
        self.poll()
        self.assertTrue(horch.load_state(self.directory)["closed"])
        self.close.assert_called_once()

    def test_missing_and_invalid_results_retain_distinct_failures(self):
        for contents, expected in ((None, "result_missing"), ("{}", "result_invalid")):
            with self.subTest(expected=expected):
                self.store(baseline_seq=10)
                result_path = self.directory / "result.json"
                result_path.unlink(missing_ok=True)
                if contents is not None:
                    result_path.write_text(contents)
                self.agent = {"agent_status": "idle", "completion_seq": 11}
                self.poll()
                state = horch.load_state(self.directory)
                self.assertEqual(state["state"], expected)
                self.assertIsNotNone(state["problem"])
                self.assertIsNotNone(state["settled_at"])
                self.assertFalse(state["closed"])
        self.close.assert_not_called()

    def test_cleanup_failure_is_retained_until_explicit_close(self):
        self.result()
        self.agent = {"agent_status": "idle", "completion_seq": 11}
        self.close.side_effect = horch.HerdrError("controlled cleanup failure")
        self.poll()
        failed = horch.load_state(self.directory)
        self.assertEqual(failed["state"], "done")
        self.assertFalse(failed["closed"])
        self.assertIn("controlled cleanup failure", failed["problem"])
        self.assertEqual(self.replacements.call_count, 2)
        self.poll()
        self.assertEqual(horch.load_state(self.directory), failed)
        self.close.side_effect = None
        with patch.object(horch, "task_dir", return_value=self.directory), \
                patch.object(horch, "load_task", return_value=self.task), \
                patch.object(horch, "require_herdr_env"), redirect_stdout(io.StringIO()):
            horch.cmd_close(Namespace(task_id=self.task["task_id"]))
        closed = horch.load_state(self.directory)
        self.assertTrue(closed["closed"])
        self.assertIsNone(closed["problem"])
        self.assertEqual(closed["settled_at"], failed["settled_at"])
        self.assertEqual(closed["first_done_at"], failed["first_done_at"])
        self.poll()
        self.assertEqual(self.replacements.call_count, 3)

    def test_unavailable_agent_index_leaves_state_untouched(self):
        before = self.path.read_bytes()
        with patch.object(horch, "agent_index", return_value=None):
            self.assertEqual(self.poll(), (False, False))
        self.assertEqual(self.path.read_bytes(), before)
        self.replacements.assert_not_called()

    def test_evaluation_and_changed_write_hold_the_state_lock(self):
        self.store()
        evaluate = horch.evaluate_task

        def evaluate_locked(*arguments):
            self.assert_lock_held()
            return evaluate(*arguments)

        def replace_locked(*arguments):
            self.assert_lock_held()
            return self.replace(*arguments)

        with patch.object(horch, "evaluate_task", side_effect=evaluate_locked):
            self.replacements.side_effect = replace_locked
            self.poll()
            self.poll()
        self.assertEqual(self.replacements.call_count, 1)

    def test_poll_reloads_closure_written_after_agent_snapshot(self):
        observed = threading.Event()
        closed = threading.Event()
        errors = []

        def index():
            observed.set()
            if not closed.wait(5):
                raise AssertionError("concurrent close did not finish")
            return {self.task["agent"]: self.agent}

        def poll_thread():
            try:
                self.poll()
            except BaseException as error:
                errors.append(error)

        with patch.object(horch, "agent_index", side_effect=index):
            thread = threading.Thread(target=poll_thread)
            thread.start()
            try:
                self.assertTrue(observed.wait(5))
                with patch.object(horch, "task_dir", return_value=self.directory), \
                        patch.object(horch, "load_task", return_value=self.task), \
                        patch.object(horch, "require_herdr_env"), redirect_stdout(io.StringIO()):
                    horch.cmd_close(Namespace(task_id=self.task["task_id"]))
            finally:
                closed.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(horch.load_state(self.directory)["closed"])
        self.assertEqual(self.replacements.call_count, 1)

    def test_cleanup_rereads_a_concurrent_confirmed_close(self):
        self.result()
        self.agent = {"agent_status": "idle", "completion_seq": 11}

        def close_during_cleanup(pane):
            with horch.task_state_lock(self.directory):
                state = horch.load_state(self.directory)
                state["closed"] = True
                horch.write_json(self.path, state)
            raise horch.HerdrError("stale cleanup failure after concurrent close")

        self.close.side_effect = close_during_cleanup
        self.poll()
        state = horch.load_state(self.directory)
        self.assertEqual(state["state"], "done")
        self.assertTrue(state["closed"])
        self.assertIsNone(state["problem"])
        self.assertEqual(self.replacements.call_count, 2)
        self.notice.assert_not_called()

    def test_stale_startup_save_preserves_polled_progress_and_closure(self):
        stale = horch.default_state()
        stale["baseline_seq"] = 10
        self.task["created_at"] = "2020-01-01T00:00:00Z"
        self.poll()
        self.result()
        self.agent = {"agent_status": "idle", "completion_seq": 11}
        self.poll()
        done = horch.load_state(self.directory)
        horch.save_state(self.directory, stale)
        self.assertEqual(horch.load_state(self.directory), done)
        self.assertEqual(stale, done)
        self.assertTrue(done["saw_working"])
        self.assertTrue(done["long_notified"])


if __name__ == "__main__":
    unittest.main()
