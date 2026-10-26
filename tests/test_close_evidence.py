"""Pane cleanup preserves the failure that caused a task to stop."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"
SPEC = importlib.util.spec_from_file_location("horch_close", SCRIPT)
horch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(horch)


class CloseEvidenceTests(unittest.TestCase):
    def close(self, state):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "herdr-orchestrator/tasks/t-123abc"
            directory.mkdir(parents=True)
            task = {"task_id": "t-123abc", "nonce": "nonce", "worker": "solo",
                    "agent": "horch-123abc", "pane_id": "w1:p2",
                    "result_path": str(directory / "result.json"),
                    "created_at": "2020-01-01T00:00:00Z"}
            (directory / "task.json").write_text(json.dumps(task))
            (directory / "state.json").write_text(json.dumps(state))
            output = io.StringIO()
            with patch.dict(os.environ, {"XDG_STATE_HOME": temporary, "HERDR_ENV": "1"}), \
                    patch.object(horch, "close_pane", return_value="closed") as close, \
                    redirect_stdout(output):
                horch.main(["close", "t-123abc"])
            close.assert_called_once_with("w1:p2")
            self.assertTrue(json.loads(output.getvalue())["closed"])
            self.assertEqual(json.loads((directory / "task.json").read_text()), task)
            return json.loads((directory / "state.json").read_text())

    def test_closing_a_failed_task_preserves_failure_and_settlement(self):
        for name in sorted(horch.SETTLED_STATES - {"done"}):
            with self.subTest(state=name):
                state = {"state": name, "closed": False,
                         "problem": "account/read failed: workspace routing discovery timed out",
                         "settled_at": "2020-01-01T00:00:15Z"}
                closed = self.close(state)
                self.assertTrue(closed["closed"])
                for key in ("state", "problem", "settled_at"):
                    self.assertEqual(closed[key], state[key])

    def test_successful_cleanup_clears_a_delivered_tasks_cleanup_error(self):
        state = {"state": "done", "closed": False,
                 "problem": "pane cleanup failed; retry with horch close",
                 "first_done_at": "2020-01-01T00:00:15Z"}
        closed = self.close(state)
        self.assertTrue(closed["closed"])
        self.assertEqual(closed["state"], "done")
        self.assertEqual(closed["first_done_at"], state["first_done_at"])
        self.assertIsNone(closed["problem"])


if __name__ == "__main__":
    unittest.main()
