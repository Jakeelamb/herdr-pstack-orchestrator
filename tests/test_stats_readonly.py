"""Observer statistics read stored outcomes without controlling workers."""
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"
SPEC = importlib.util.spec_from_file_location("horch_stats", SCRIPT)
horch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(horch)


class ReadOnlyStatsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "config/herdr-orchestrator/workers.toml"
        self.config.parent.mkdir(parents=True)
        self.config.write_text('[workers.solo]\nharness = "codex"\nmodel = "test-model"\n')
        self.tasks = self.root / "state/herdr-orchestrator/tasks"

    def task(self, task_id, workspace, state, status):
        directory = self.tasks / task_id
        directory.mkdir(parents=True)
        task = {
            "task_id": task_id, "nonce": task_id + "-nonce", "worker": "solo",
            "agent": "horch-" + task_id[2:], "pane_id": workspace + ":p1",
            "workspace_id": workspace, "result_path": str(directory / "result.json"),
            "created_at": "2020-01-01T00:00:00Z",
        }
        values = {
            "task.json": task,
            "state.json": {"state": state, "closed": state == "done",
                           "first_done_at": "2020-01-01T00:10:00Z" if state == "done" else None},
            "result.json": {"task_id": task_id, "nonce": task["nonce"], "status": status,
                            "summary": "Stored fixture outcome", "files": [],
                            "question": "Need a decision?" if status == "blocked" else None},
        }
        for name, value in values.items():
            (directory / name).write_text(json.dumps(value))

    def snapshot(self):
        return {str(path.relative_to(self.root)): (
            path.stat().st_mtime_ns, path.stat().st_mode,
            path.read_bytes() if path.is_file() else None,
        ) for path in [self.root, *self.root.rglob("*")]}

    def observe(self, *arguments):
        before = self.snapshot()
        output = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "XDG_STATE_HOME": str(self.root / "state"),
            }, clear=True))
            forbidden = []
            for owner, name in (
                (horch, "herdr"), (horch, "notify"), (horch, "task_store_lock"),
                (horch, "task_state_lock"), (horch.subprocess, "run"),
                (horch.subprocess, "Popen"), (horch.fcntl, "flock"),
            ):
                forbidden.append(stack.enter_context(patch.object(
                    owner, name, side_effect=AssertionError("observer called " + name))))
            with redirect_stdout(output):
                horch.main(["stats", *arguments])
            for call in forbidden:
                call.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        return json.loads(output.getvalue())

    def test_observation_preserves_running_and_delivered_outcomes(self):
        self.task("t-000001", "w1", "done", "completed")
        self.task("t-000002", "w1", "done", "blocked")
        self.task("t-000003", "w1", "running", "completed")
        self.task("t-000004", "w2", "done", "failed")

        scoped = self.observe("--workspace", "w1")
        worker = scoped["workers"]["solo"]
        self.assertEqual(scoped["task_count"], 3)
        self.assertEqual(worker["states"], {"done": 2, "running": 1})
        self.assertEqual(worker["result_statuses"], {"completed": 1, "blocked": 1})
        self.assertEqual(worker["unclosed_running"], 1)
        self.assertEqual(worker["duration_minutes"]["sample_size"], 2)
        whole = self.observe()
        self.assertEqual(whole["task_count"], 4)
        self.assertEqual(whole["workers"]["solo"]["result_statuses"],
                         {"completed": 1, "blocked": 1, "failed": 1})

    def test_observation_does_not_create_an_absent_task_store(self):
        report = self.observe()
        self.assertEqual(report["task_count"], 0)
        self.assertEqual(report["configured_unused_workers"], ["solo"])
        self.assertFalse((self.root / "state").exists())


if __name__ == "__main__":
    unittest.main()
