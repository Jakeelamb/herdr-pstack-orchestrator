"""Publication death and stale-save controls with real processes and flock."""
from contextlib import contextmanager, redirect_stdout
import fcntl
import importlib.util
import io
import json
import multiprocessing
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"
SPEC = importlib.util.spec_from_file_location("horch_publication", SCRIPT)
horch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(horch)
CTX = multiprocessing.get_context("fork")
CONFIG = {"max_active_workers": 1, "notify_after_minutes": 180, "workers": {
    name: {"harness": "codex", "model": "fixture", "effort": None, "args": []}
    for name in ("first", "second")}}
CONFIG["roles"] = {}
CALLER = {"workspace_id": "fixture", "tab_id": "fixture:controller"}


def record(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


@contextmanager
def isolated_store(name):
    retained = os.environ.get("HORCH_TEST_EVIDENCE_DIR")
    if retained:
        root = Path(retained) / name
        root.mkdir(parents=True, exist_ok=False)
        yield root
    else:
        with tempfile.TemporaryDirectory() as temporary:
            yield Path(temporary)


@contextmanager
def startup_boundary(root, failure=None, checkpoint=None, cleanup_oserror=False):
    calls = []
    counts = {}
    original = horch.write_json

    def write(path, value):
        counts[path.name] = counts.get(path.name, 0) + 1
        target = failure.split("_")[0] + ".json" if failure else None
        if path.name == target and (failure.endswith("always") or counts[path.name] == 1):
            raise OSError("injected " + failure)
        original(path, value)
        if checkpoint and path.name == "task.json" and (not failure or counts.get("state.json", 0)):
            checkpoint.send("published")
            checkpoint.recv()

    def external(*args, **kwargs):
        calls.append(list(args))
        record(root / "calls.json", calls)
        if args[:2] == ("agent", "start"):
            return {"result": {"type": "agent_started"}}
        if args[:2] == ("agent", "read"):
            return "\n› \n"
        if args[:2] == ("agent", "prompt"):
            return {"result": {"agent": {"agent_status": "working"}}}
        raise AssertionError("unexpected external boundary " + repr(args))

    def cleanup(pane_id):
        calls.append(["cleanup", pane_id])
        record(root / "calls.json", calls)
        if cleanup_oserror:
            raise OSError("injected cleanup OS error")
        if not failure or not failure.endswith("_cleanup"):
            raise horch.HerdrError("injected cleanup transport error")
        return "closed"

    record(root / "calls.json", calls)
    with patch.object(horch, "tasks_root", return_value=root), \
            patch.object(horch, "require_caller_context", return_value=CALLER), \
            patch.object(horch, "place_pane", return_value=("fixture:pane", "fixture:worker")), \
            patch.object(horch.secrets, "token_hex", side_effect=["abcdef", "fixture-nonce"]), \
            patch.object(horch, "agent_index", return_value={"horch-abcdef": {"state_change_seq": 10}}), \
            patch.object(horch, "write_json", side_effect=write), \
            patch.object(horch, "close_pane", side_effect=cleanup), \
            patch.object(horch, "herdr", side_effect=external), \
            patch.object(horch, "notify"):
        yield


def publication_child(root, failure, connection):
    if failure == "postcommit":
        with startup_boundary(root, checkpoint=connection), postcommit_fault(root):
            horch.start_task(CONFIG, "first", "Fixture only. Do not delegate.", root)
        return
    with startup_boundary(root, failure, connection):
        horch.start_task(CONFIG, "first", "Fixture only. Do not delegate.", root)


@contextmanager
def postcommit_fault(root, boundary="unlink", damaged=None):
    """Commit real state, fail after commit, then fail diagnostic replacement."""
    replace, unlink, flock, read_text = os.replace, os.unlink, fcntl.flock, Path.read_text
    publication_error = OSError("injected postcommit " + boundary)
    state_replacements, identity_replacements = 0, 0
    events = []
    failed = False

    def replace_file(source, target):
        nonlocal state_replacements, identity_replacements
        target = Path(target)
        if target.parent.name == "t-abcdef" and target.name == "state.json":
            state_replacements += 1
            if state_replacements > (2 if boundary == "diagnostic_unlink" else 1):
                if damaged == "missing":
                    unlink(target)
                elif damaged is not None and damaged != "unreadable":
                    target.write_bytes(damaged)
                events.append("diagnostic replace failed")
                raise OSError("injected diagnostic replace failure")
        if target.parent.name == "t-abcdef" and target.name == "task.json":
            identity_replacements += 1
            if boundary in ("diagnostic_unlink", "identity") and identity_replacements == 1:
                raise publication_error
        replace(source, target)
        events.append("replaced " + target.name)

    def unlink_file(path, *args, **kwargs):
        nonlocal failed
        expected = 2 if boundary == "diagnostic_unlink" else 1
        if (boundary in ("unlink", "diagnostic_unlink") and not failed
                and Path(path).name.startswith(".state.json.")
                and state_replacements == expected):
            failed = True
            events.append("postcommit unlink failed")
            raise publication_error
        return unlink(path, *args, **kwargs)

    def lock_file(stream, operation):
        nonlocal failed
        result = flock(stream, operation)
        if (boundary == "unlock" and not failed and operation == fcntl.LOCK_UN
                and Path(stream.name).name == ".state.lock"):
            failed = True
            events.append("postcommit unlock failed")
            raise publication_error
        return result

    def read_file(path, *args, **kwargs):
        if (damaged == "unreadable" and state_replacements > 1
                and path == root / "t-abcdef/state.json"):
            raise OSError("injected state read failure")
        return read_text(path, *args, **kwargs)

    try:
        with patch.object(os, "replace", side_effect=replace_file), \
                patch.object(os, "unlink", side_effect=unlink_file), \
                patch.object(fcntl, "flock", side_effect=lock_file), \
                patch.object(Path, "read_text", read_file):
            yield publication_error, events
    finally:
        record(root / "faults.json", {"events": events, "state_replacements": state_replacements,
               "identity_replacements": identity_replacements})


def stale_save_child(directory, connection):
    stale = horch.load_state(directory)
    stale.update(state="done", settled_at="2020-01-01T00:00:20Z",
                 first_done_at="2020-01-01T00:00:25Z")
    connection.send("loaded")
    connection.recv()
    original = horch.task_state_lock

    @contextmanager
    def lock(path):
        with (path / ".state.lock").open("a") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                connection.send("contended")
            else:
                fcntl.flock(probe, fcntl.LOCK_UN)
                raise AssertionError("parent must hold the actual state lock")
        with original(path):
            yield

    with patch.object(horch, "task_state_lock", side_effect=lock):
        horch.save_state(directory, stale)
    connection.send("saved")
    connection.recv()


class PublicationTests(unittest.TestCase):
    def child(self, target, *args):
        parent, child = CTX.Pipe()
        process = CTX.Process(target=target, args=(*args, child))
        process.start()
        child.close()

        def cleanup():
            if process.is_alive():
                process.kill()
            process.join(10)
            parent.close()
        self.addCleanup(cleanup)
        return process, parent

    def receive(self, connection, expected):
        self.assertTrue(connection.poll(10), "child did not reach " + expected)
        self.assertEqual(connection.recv(), expected)

    def assert_lock(self, path, busy):
        with path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.assertTrue(busy, str(path) + " unexpectedly busy")
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)
                self.assertFalse(busy, str(path) + " was not held by starter")

    def publication_death(self, failure):
        with isolated_store(self._testMethodName) as root:
            process, connection = self.child(publication_child, root, failure)
            self.receive(connection, "published")
            directory = root / "t-abcdef"
            self.assert_lock(root / ".start.lock", busy=True)
            self.assert_lock(directory / ".state.lock", busy=False)
            process.kill()
            process.join(10)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, -signal.SIGKILL)
            self.assert_lock(root / ".start.lock", busy=False)
            state = horch.read_json(directory / "state.json")
            calls = horch.read_json(root / "calls.json")
            with patch.object(horch, "tasks_root", return_value=root):
                count = horch.active_task_count("fixture")
            record(root / "observation.json", {"exit_code": process.exitcode,
                   "state": state, "calls": calls, "reservations": count,
                   "startup_lock_busy_before_death": True, "startup_lock_released": True})
            self.assertEqual(count, 1)
            self.assertEqual(horch.load_task(directory, "t-abcdef")["pane_id"], "fixture:pane")
            self.assertEqual(calls, [["cleanup", "fixture:pane"]] if failure else [])
            self.assertIsNotNone(state, "visible task must have initialized state after SIGKILL")
            self.assertFalse(state["closed"])
            self.assertIsNone(state["first_done_at"])
            self.assertFalse((directory / "result.json").exists())
            if failure and failure != "postcommit":
                self.assertEqual(state["state"], "start_failed")
                self.assertIn("cleanup transport error", state["problem"])
                self.assertIsNotNone(state["settled_at"])
            else:
                self.assertEqual(state, horch.default_state())

    def test_normal_publication_survives_sigkill(self):
        self.publication_death(None)

    def test_rollback_publication_survives_sigkill(self):
        self.publication_death("state_once")

    def test_postcommit_recovery_publication_survives_sigkill(self):
        self.publication_death("postcommit")

    def test_closed_timestamps_survive_contended_stale_save_and_sigkill(self):
        cases = (
            ("running", None, None),
            ("not_started", None, None),
            ("not_started", "2020-01-01T00:00:10Z", None),
            ("done", "2020-01-01T00:00:10Z", "2020-01-01T00:00:12Z"),
            ("done", None, None),
        )
        for number, (name, settled, delivered) in enumerate(cases):
            with self.subTest(state=name, settled_at=settled, first_done_at=delivered), \
                    isolated_store(self._testMethodName + str(number)) as root:
                directory = root / "t-abcdef"
                directory.mkdir()
                task = {"task_id": "t-abcdef", "nonce": "fixture", "worker": "first",
                        "agent": "horch-abcdef", "pane_id": "fixture:pane", "workspace_id": "fixture",
                        "result_path": str(directory / "result.json"), "created_at": "2020-01-01T00:00:00Z"}
                state = dict(horch.default_state(), state=name, problem="retained failure" if name == "not_started" else None,
                             settled_at=settled, first_done_at=delivered)
                horch.write_json(directory / "task.json", task)
                horch.write_json(directory / "state.json", state)
                process, connection = self.child(stale_save_child, directory)
                self.receive(connection, "loaded")
                output = io.StringIO()
                with patch.object(horch, "tasks_root", return_value=root), \
                        patch.object(horch, "require_herdr_env"), \
                        patch.object(horch, "close_pane", return_value="closed") as close, redirect_stdout(output):
                    horch.cmd_close(type("Args", (), {"task_id": "t-abcdef"})())
                close.assert_called_once_with("fixture:pane")
                closed = horch.read_json(directory / "state.json")
                with horch.task_state_lock(directory):
                    connection.send("save")
                    self.receive(connection, "contended")
                    self.assertEqual(horch.read_json(directory / "state.json"), closed)
                self.receive(connection, "saved")
                process.kill()
                process.join(10)
                self.assertEqual(process.exitcode, -signal.SIGKILL)
                self.assert_lock(directory / ".state.lock", busy=False)
                stored = horch.read_json(directory / "state.json")
                record(root / "observation.json", {"before_stale_save": closed, "after_stale_save": stored,
                       "exit_code": process.exitcode, "actual_state_lock_contended": True,
                       "close_output": json.loads(output.getvalue())})
                self.assertEqual(stored, closed)
                self.assertTrue(stored["closed"])
                self.assertEqual(stored["settled_at"], settled)
                self.assertEqual(stored["first_done_at"], delivered)

    def test_publication_failures_retain_reservation_when_storage_recovers(self):
        for failure in ("state_once", "task_once"):
            with self.subTest(failure=failure), isolated_store(self._testMethodName + failure) as root:
                with startup_boundary(root, failure), self.assertRaisesRegex(OSError, "injected " + failure):
                    horch.start_task(CONFIG, "first", "Fixture only", root)
                state = horch.read_json(root / "t-abcdef/state.json")
                with patch.object(horch, "tasks_root", return_value=root):
                    self.assertEqual(horch.active_task_count("fixture"), 1)
                self.assertEqual(state["state"], "start_failed")
                self.assertIsNotNone(state["settled_at"])
                self.assertIsNone(state["first_done_at"])
                self.assertIn("cleanup transport error", state["problem"])
                self.assertEqual(horch.read_json(root / "calls.json"), [["cleanup", "fixture:pane"]])

    def test_confirmed_unused_pane_cleanup_removes_unpublished_task(self):
        for failure in ("state_cleanup", "task_cleanup"):
            with self.subTest(failure=failure), isolated_store(self._testMethodName + failure) as root:
                with startup_boundary(root, failure), self.assertRaisesRegex(OSError, "injected " + failure):
                    horch.start_task(CONFIG, "first", "Fixture only", root)
                self.assertFalse((root / "t-abcdef").exists())
                with patch.object(horch, "tasks_root", return_value=root):
                    self.assertEqual(horch.active_task_count("fixture"), 0)
                self.assertEqual(horch.read_json(root / "calls.json"), [["cleanup", "fixture:pane"]])

    def test_initialized_state_reserves_capacity_when_failure_diagnostic_cannot_save(self):
        for cleanup_oserror in (False, True):
            with self.subTest(cleanup_oserror=cleanup_oserror), \
                    isolated_store(self._testMethodName + str(cleanup_oserror)) as root:
                original = horch.write_json
                writes = []
                publication_error = OSError("injected transient identity failure")

                def write(path, value):
                    writes.append(path.name)
                    if path.parent.name == "t-abcdef":
                        if path.name == "task.json" and writes.count("task.json") == 1:
                            raise publication_error
                        if path.name == "state.json" and writes.count("state.json") > 1:
                            raise OSError("injected failure diagnostic storage error")
                    original(path, value)

                warning, output = io.StringIO(), io.StringIO()
                with startup_boundary(root, cleanup_oserror=cleanup_oserror), \
                        patch.object(horch, "write_json", side_effect=write), \
                        patch.object(horch.secrets, "token_hex", side_effect=["abcdef", "nonce1", "123abc", "nonce2"]), \
                        patch.object(horch, "place_pane", side_effect=[("fixture:pane", "fixture:worker"),
                                                                     ("fixture:pane2", "fixture:worker")]) as place, \
                        patch.object(horch, "agent_index", return_value={"horch-123abc": {"state_change_seq": 10}}), \
                        patch("sys.stderr", warning):
                    with self.assertRaises(OSError) as raised:
                        horch.start_task(CONFIG, "first", "Fixture only", root)
                    state = horch.read_json(root / "t-abcdef/state.json")
                    count = horch.active_task_count("fixture")
                    with redirect_stdout(output):
                        try:
                            second = horch.start_task(CONFIG, "second", "Fixture only", root)
                        except SystemExit as exc:
                            second = {"exit_code": exc.code, **json.loads(output.getvalue())}
                    calls = horch.read_json(root / "calls.json")
                    record(root / "observation.json", {"state": state, "reservations": count,
                           "second_launch": second, "panes_placed": place.call_count,
                           "writes": writes, "calls": calls, "warning": warning.getvalue()})
                    self.assertIs(raised.exception, publication_error)
                    self.assertEqual(second.get("error"), "worker_limit")
                    self.assertEqual(second["exit_code"], 1)
                    self.assertEqual(place.call_count, 1)
                self.assertEqual(count, 1)
                self.assertEqual(state, horch.default_state())
                self.assertEqual(writes.count("task.json"), 2)
                self.assertEqual(calls, [["cleanup", "fixture:pane"]])
                self.assertIn("cannot save failure diagnostic for task t-abcdef", warning.getvalue())
                self.assertIn("injected failure diagnostic storage error", warning.getvalue())
                self.assertIn("cleanup OS error" if cleanup_oserror else "cleanup transport error", warning.getvalue())
                self.assertNotIn("cannot preserve task", warning.getvalue())

    def test_postcommit_errors_retain_visible_reservation_when_diagnostic_fails(self):
        for boundary in ("unlink", "unlock", "diagnostic_unlink"):
            for cleanup_oserror in (False, True):
                with self.subTest(boundary=boundary, cleanup_oserror=cleanup_oserror), \
                        isolated_store(self._testMethodName + boundary + str(cleanup_oserror)) as root:
                    warning, listing, stats, launch = (io.StringIO() for _ in range(4))
                    with startup_boundary(root, cleanup_oserror=cleanup_oserror), \
                            postcommit_fault(root, boundary) as (original, events), \
                            patch("sys.stderr", warning), \
                            patch.object(horch, "require_herdr_env"), \
                            patch.object(horch, "load_config", return_value=CONFIG), \
                            patch.object(horch.secrets, "token_hex", side_effect=["abcdef", "nonce1", "123abc", "nonce2"]), \
                            patch.object(horch, "place_pane", return_value=("fixture:pane", "fixture:worker")) as place:
                        with self.assertRaises(OSError) as raised:
                            horch.start_task(CONFIG, "first", "Fixture only", root)
                        state = horch.read_json(root / "t-abcdef/state.json")
                        count = horch.active_task_count("fixture")
                        with redirect_stdout(listing):
                            horch.main(["list", "--workspace", "fixture"])
                        with redirect_stdout(stats):
                            horch.main(["stats", "--workspace", "fixture"])
                        with redirect_stdout(launch):
                            try:
                                second = horch.start_task(CONFIG, "second", "Fixture only", root)
                            except SystemExit as exc:
                                second = {"exit_code": exc.code, **json.loads(launch.getvalue())}
                        rows = [json.loads(line) for line in listing.getvalue().splitlines()]
                        statistics = json.loads(stats.getvalue())
                        record(root / "observation.json", {"state": state, "reservations": count,
                               "list": rows, "stats": statistics, "second_launch": second,
                               "warning": warning.getvalue(), "events": events})
                        self.assertIs(raised.exception, original)
                        self.assertEqual(count, 1)
                        self.assertEqual([row["task_id"] for row in rows], ["t-abcdef"])
                        self.assertEqual(statistics["task_count"], 1)
                        self.assertEqual(second.get("error"), "worker_limit")
                        self.assertEqual(second["exit_code"], 1)
                        self.assertEqual(place.call_count, 1)
                    if boundary == "diagnostic_unlink":
                        self.assertEqual(state["state"], "start_failed")
                        self.assertIsNotNone(state["settled_at"])
                    else:
                        self.assertEqual(state, horch.default_state())
                    self.assertEqual(horch.read_json(root / "calls.json"), [["cleanup", "fixture:pane"]])
                    self.assertIn("cannot save failure diagnostic", warning.getvalue())
                    self.assertIn("cleanup OS error" if cleanup_oserror else "cleanup transport error", warning.getvalue())
                    self.assertNotIn("cannot preserve task", warning.getvalue())

    def test_postcommit_recovery_rejects_missing_corrupt_or_incomplete_state(self):
        invalid = ["missing", "unreadable", b"{", b"[]", b"null", b"\xff", b'{}', b'{"state":"running"}']
        for key, value in (("closed", "false"), ("saw_working", 0), ("state", []),
                           ("state", "custom"), ("long_notified", None),
                           ("baseline_seq", True), ("baseline_seq", -1), ("problem", []),
                           ("settled_at", "yesterday"), ("first_done_at", "2020-01-01"),
                           ("first_done_at", 0)):
            invalid.append(json.dumps(dict(horch.default_state(), **{key: value})).encode())
        for index, damaged in enumerate(invalid):
            with self.subTest(damaged=damaged), isolated_store(self._testMethodName + str(index)) as root:
                warning = io.StringIO()
                with startup_boundary(root), postcommit_fault(root, boundary="identity", damaged=damaged) as (original, _), \
                        patch("sys.stderr", warning), self.assertRaises(OSError) as raised:
                    horch.start_task(CONFIG, "first", "Fixture only", root)
                self.assertIs(raised.exception, original)
                self.assertFalse((root / "t-abcdef/task.json").exists())
                self.assertIn("cannot preserve task", warning.getvalue())
                self.assertIn("cannot save failure diagnostic", warning.getvalue())
                record(root / "observation.json", {"warning": warning.getvalue(), "identity_published": False})

    def test_failed_diagnostic_and_identity_retry_report_both_storage_errors(self):
        with isolated_store(self._testMethodName) as root:
            original = horch.write_json
            task_writes, state_writes = 0, 0
            publication_error = OSError("injected original identity failure")

            def write(path, value):
                nonlocal task_writes, state_writes
                if path.name == "task.json":
                    task_writes += 1
                    if task_writes == 1:
                        raise publication_error
                    raise OSError("injected identity retry failure")
                if path.name == "state.json":
                    state_writes += 1
                    if state_writes > 1:
                        raise OSError("injected failure diagnostic storage error")
                original(path, value)

            warning = io.StringIO()
            with startup_boundary(root), patch.object(horch, "write_json", side_effect=write), \
                    patch("sys.stderr", warning), self.assertRaises(OSError) as raised:
                horch.start_task(CONFIG, "first", "Fixture only", root)
            self.assertIs(raised.exception, publication_error)
            self.assertEqual(task_writes, 2)
            self.assertEqual(horch.read_json(root / "t-abcdef/state.json"), horch.default_state())
            self.assertFalse((root / "t-abcdef/task.json").exists())
            with patch.object(horch, "tasks_root", return_value=root):
                self.assertEqual(horch.active_task_count("fixture"), 0)
            self.assertIn("cannot save failure diagnostic", warning.getvalue())
            self.assertIn("injected failure diagnostic storage error", warning.getvalue())
            self.assertIn("injected cleanup transport error", warning.getvalue())
            self.assertIn("cannot preserve task t-abcdef for pane fixture:pane", warning.getvalue())
            self.assertIn("injected identity retry failure", warning.getvalue())
            self.assertEqual(horch.read_json(root / "calls.json"), [["cleanup", "fixture:pane"]])
            record(root / "observation.json", {"warning": warning.getvalue(), "identity_attempts": task_writes,
                   "reservations": 0, "limit": "identity storage remained unavailable"})

    def test_cleanup_oserror_retains_reservation_and_original_publication_error(self):
        with isolated_store(self._testMethodName) as root:
            with startup_boundary(root, "state_once", cleanup_oserror=True), \
                    self.assertRaisesRegex(OSError, "injected state_once"):
                horch.start_task(CONFIG, "first", "Fixture only", root)
            state = horch.read_json(root / "t-abcdef/state.json")
            self.assertEqual(state["state"], "start_failed")
            self.assertIn("cleanup OS error", state["problem"])
            with patch.object(horch, "tasks_root", return_value=root):
                self.assertEqual(horch.active_task_count("fixture"), 1)
            self.assertEqual(horch.read_json(root / "calls.json"), [["cleanup", "fixture:pane"]])

    def test_existing_identity_keeps_reservation_when_failure_state_cannot_save(self):
        with isolated_store(self._testMethodName) as root:
            with startup_boundary(root):
                original = horch.write_json
                published = False

                def write(path, value):
                    nonlocal published
                    if path.name == "state.json" and published:
                        raise OSError("injected failure-state storage error")
                    original(path, value)
                    if path.name == "task.json":
                        published = True
                        raise OSError("injected error after identity replacement")

                warning = io.StringIO()
                with patch.object(horch, "write_json", side_effect=write), patch("sys.stderr", warning), \
                        self.assertRaisesRegex(OSError, "injected error after identity replacement"):
                    horch.start_task(CONFIG, "first", "Fixture only", root)
                self.assertEqual(horch.active_task_count("fixture"), 1)
            self.assertEqual(horch.read_json(root / "t-abcdef/state.json"), horch.default_state())
            self.assertIn("cannot save failure diagnostic for task t-abcdef", warning.getvalue())
            record(root / "observation.json", {"warning": warning.getvalue(), "reservations": 1,
                   "limit": "initialized state survived but failure-state update could not persist"})

    def test_repeated_storage_failure_reports_unpreserved_reservation(self):
        for failure in ("state_always", "task_always"):
            with self.subTest(failure=failure), isolated_store(self._testMethodName + failure) as root:
                warning = io.StringIO()
                with startup_boundary(root, failure), patch("sys.stderr", warning), \
                        self.assertRaisesRegex(OSError, "injected " + failure):
                    horch.start_task(CONFIG, "first", "Fixture only", root)
                with patch.object(horch, "tasks_root", return_value=root):
                    count = horch.active_task_count("fixture")
                record(root / "observation.json", {"warning": warning.getvalue(), "reservations": count})
                self.assertIn("cannot preserve task t-abcdef for pane fixture:pane", warning.getvalue())
                self.assertIn("injected " + failure, warning.getvalue())
                self.assertTrue((root / "t-abcdef/brief.md").is_file())
                self.assertEqual(count, 0)
                self.assertFalse((root / "t-abcdef/task.json").exists())
                self.assertEqual(horch.read_json(root / "calls.json"), [["cleanup", "fixture:pane"]])

    def test_healthy_start_retains_baseline_and_single_prompt(self):
        with isolated_store(self._testMethodName) as root:
            with startup_boundary(root):
                run = horch.start_task(CONFIG, "first", "Fixture only", root)
            state = horch.load_state(root / run["task_id"])
            self.assertEqual(state["state"], "running")
            self.assertEqual(state["baseline_seq"], 10)
            self.assertTrue(state["saw_working"])
            self.assertIsNone(state["settled_at"])
            self.assertIsNone(state["first_done_at"])
            calls = horch.read_json(root / "calls.json")
            self.assertEqual([call[:2] for call in calls if call[:2] != ["agent", "read"]],
                             [["agent", "start"], ["agent", "prompt"]])

    def test_unclosed_delivery_precedes_stale_running_save(self):
        with isolated_store(self._testMethodName) as root:
            state = dict(horch.default_state(), state="done", settled_at="2020-01-01T00:00:10Z",
                         first_done_at="2020-01-01T00:00:12Z")
            horch.write_json(root / "state.json", state)
            horch.save_state(root, horch.default_state())
            self.assertEqual(horch.load_state(root), state)

    def test_check_starts_pending_worker_after_null_sequence_delivery(self):
        with isolated_store(self._testMethodName) as root:
            calls, starts, polls, snapshots = [], [], {}, []

            def place(*args):
                self.assertEqual(horch.active_task_count("fixture"), 0)
                return "fixture:pane", "fixture:worker"

            def external(*args, **kwargs):
                calls.append(list(args))
                if args[:2] == ("agent", "start"):
                    starts.append(args[2])
                    return {"result": {"type": "agent_started"}}
                if args[:2] == ("agent", "read"):
                    return "\n› \n"
                if args[:2] == ("agent", "prompt"):
                    task_id = "t-" + args[2].removeprefix("horch-")
                    directory = root / task_id
                    task = horch.load_task(directory, task_id)
                    horch.write_json(directory / "result.json", {
                        "task_id": task_id, "nonce": task["nonce"], "status": "completed",
                        "summary": "early fixture result", "files": ["report.md"], "question": None})
                    polls[args[2]] = iter((
                        {"agent_status": "unknown"},
                        {"agent_status": "idle", "completion_seq": 10},
                        {"agent_status": "working"},
                        {"agent_status": "idle", "completion_seq": None}))
                    return {"result": {"agent": {"agent_status": "working"}}}
                raise AssertionError("unexpected boundary " + repr(args))

            def index():
                agent = starts[-1]
                if agent not in polls:
                    return {agent: {"state_change_seq": 10}}
                entry = next(polls[agent])
                info = horch.make_info("t-" + agent.removeprefix("horch-"))
                line = horch.wait_line(info)
                snapshots.append({"agent": agent, "observation": entry, "line_before_poll": line})
                self.assertIsNone(line["summary"])
                self.assertEqual(line["files"], [])
                return {agent: entry}

            output = io.StringIO()
            with patch.object(horch, "tasks_root", return_value=root), \
                    patch.object(horch, "require_herdr_env"), \
                    patch.object(horch, "require_caller_context", return_value=CALLER), \
                    patch.object(horch, "load_config", return_value=CONFIG), \
                    patch.object(horch, "place_pane", side_effect=place), \
                    patch.object(horch.secrets, "token_hex", side_effect=["abcdef", "nonce1", "123abc", "nonce2"]), \
                    patch.object(horch, "herdr", side_effect=external), \
                    patch.object(horch, "agent_index", side_effect=index), \
                    patch.object(horch, "close_pane", return_value="closed") as close, \
                    patch.object(horch.time, "sleep"), patch.object(horch, "notify"), redirect_stdout(output):
                horch.main(["check", "first", "second", "--cwd", str(root), "--max-seconds", "10"])
                count = horch.active_task_count("fixture")
            lines = [json.loads(line) for line in output.getvalue().splitlines()]
            record(root / "observation.json", {"calls": calls, "polls": snapshots, "output": lines,
                   "reservations_after_delivery": count})
            self.assertEqual([line["worker"] for line in lines], ["first", "second"])
            self.assertTrue(all(line["ok"] and line["state"] == "done" for line in lines))
            self.assertEqual(close.call_count, 2)
            self.assertEqual(len(snapshots), 8)
            self.assertEqual(sum(call[:2] == ["agent", "prompt"] for call in calls), 2)
            self.assertEqual(sum(call[:2] == ["agent", "start"] for call in calls), 2)
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
