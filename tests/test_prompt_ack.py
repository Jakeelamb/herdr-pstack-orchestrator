"""Task publication and acknowledgement against controlled Herdr responses."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"
SPEC = importlib.util.spec_from_file_location("horch", SCRIPT)
horch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(horch)


class PromptAcknowledgementTests(unittest.TestCase):
    def launch(self, prompt="working", observed="working", elapsed=5):
        self.clock = 100.0
        self.commands = []

        def response(*args, **kwargs):
            self.commands.append(args)
            if args[:2] == ("agent", "start"):
                return {"result": {"type": "agent_started"}}
            value = prompt if args[:2] == ("agent", "prompt") else observed
            if args[:2] == ("agent", "prompt"):
                self.clock += elapsed
            if isinstance(value, dict):
                return value
            if value not in ("working", "blocked"):
                raise horch.HerdrError(value, {"error": {"code": value, "message": value}})
            return {"result": {"agent": {"agent_status": value}}}

        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {"XDG_STATE_HOME": temporary}), \
                patch.object(horch, "require_caller_context", return_value={"workspace_id": "w1", "tab_id": "w1:t1"}), \
                patch.object(horch, "task_capacity", return_value=(0, [])), \
                patch.object(horch, "place_pane", return_value=("w1:p2", "w1:t2")), \
                patch.object(horch, "agent_index", return_value={"horch-abcdef": {"state_change_seq": 10}}), \
                patch.object(horch.secrets, "token_hex", side_effect=["abcdef", "nonce"]), \
                patch.object(horch.time, "monotonic", side_effect=lambda: self.clock), \
                patch.object(horch, "herdr", side_effect=response), \
                patch.object(horch, "notify") as notice:
            config = {"max_active_workers": 4, "workers": {"worker": {
                "harness": "codex", "model": "test-model", "effort": None, "args": []}}}
            result = horch._start_task_locked(config, "worker", "Do not delegate.", Path(temporary), False, "w1:p1")
            directory = Path(temporary) / "herdr-orchestrator/tasks" / result["task_id"]
            self.state = json.loads((directory / "state.json").read_text())
            self.brief = (directory / "brief.md").read_text()
            self.notices = notice.call_args_list
            self.assertEqual(sum(c[:2] == ("agent", "prompt") for c in self.commands), 1)
            self.assertFalse(any(c[:2] == ("pane", "close") for c in self.commands))
            return result["state"]

    def test_acknowledged_prompt_needs_no_extra_observation(self):
        self.assertEqual(self.launch(), "running")
        self.assertFalse(any(c[:2] == ("agent", "wait") for c in self.commands))

    def test_delayed_acknowledgement_observes_same_worker_with_remaining_budget(self):
        self.assertEqual(self.launch(prompt="agent_prompt_stalled"), "running")
        waits = [c for c in self.commands if c[:2] == ("agent", "wait")]
        self.assertEqual(len(waits), 1)
        self.assertEqual(waits[0][-2:], ("--timeout", "10000"))
        self.assertTrue(self.state["saw_working"])
        self.assertFalse(self.notices)

    def test_delayed_dialog_stays_blocked(self):
        self.assertEqual(self.launch(prompt="agent_prompt_stalled", observed="blocked"), "blocked")
        self.assertFalse(self.state["saw_working"])
        self.assertEqual(len(self.notices), 1)

    def test_unconfirmed_prompt_preserves_both_errors(self):
        self.assertEqual(self.launch(prompt="agent_prompt_stalled", observed="timeout"), "not_started")
        self.assertIn("agent_prompt_stalled", self.state["problem"])
        self.assertIn("timeout", self.state["problem"])
        self.assertEqual(len(self.notices), 1)

    def test_rejected_prompt_is_not_observed_or_resent(self):
        self.assertEqual(self.launch(prompt="agent_blocked"), "blocked")
        self.assertFalse(any(c[:2] == ("agent", "wait") for c in self.commands))

    def test_other_errors_are_not_observed_or_resent(self):
        self.assertEqual(self.launch(prompt="transport_error"), "not_started")
        self.assertFalse(any(c[:2] == ("agent", "wait") for c in self.commands))

    def test_exhausted_deadline_adds_no_observation(self):
        self.assertEqual(self.launch(prompt="agent_prompt_stalled", elapsed=16), "not_started")
        self.assertFalse(any(c[:2] == ("agent", "wait") for c in self.commands))

    def test_generated_rules_respect_delegation_limits(self):
        self.launch()
        self.assertIn("Do not delegate.", self.brief)
        self.assertNotIn("You may use your own subagents", self.brief)

    def test_unexpected_acknowledgement_is_not_running(self):
        for reply in ({"result": {"agent": {"agent_status": "idle"}}},
                      {"result": []}, {"result": {"agent": []}}):
            with self.subTest(reply=reply):
                self.assertEqual(self.launch(prompt=reply), "not_started")

    def test_unexpected_passive_reply_is_not_running(self):
        self.assertEqual(self.launch(prompt="agent_prompt_stalled",
            observed={"result": {"agent": {"agent_status": "unknown"}}}), "not_started")
        self.assertIn("agent_prompt_stalled", self.state["problem"])
        self.assertIn("unknown", self.state["problem"])

    def test_passive_dialog_error_stays_blocked(self):
        self.assertEqual(self.launch(prompt="agent_prompt_stalled", observed="agent_blocked"), "blocked")

    def test_short_completed_turn_is_acknowledged_without_delivering_result(self):
        for status in ("idle", "done"):
            with self.subTest(status=status):
                reply = {"result": {"agent": {"agent_status": status, "completion_seq": 11}}}
                self.assertEqual(self.launch(prompt="agent_prompt_stalled", observed=reply), "running")
                self.assertFalse(self.state["saw_working"])

    def test_stale_completion_is_not_acknowledgement(self):
        for status in ("idle", "done"):
            with self.subTest(status=status):
                reply = {"result": {"agent": {"agent_status": status, "completion_seq": 10}}}
                self.assertEqual(self.launch(prompt="agent_prompt_stalled", observed=reply), "not_started")


if __name__ == "__main__":
    unittest.main()
