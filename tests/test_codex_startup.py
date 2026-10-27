"""Submission-boundary checks with faithful Herdr and Codex startup fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills/herdr-orchestrator/scripts/horch.py"
SPEC = importlib.util.spec_from_file_location("horch", SCRIPT)
horch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(horch)

TRUST_SCREEN = """
  Folder access
  /workspace/project

  Trust this folder?

› 1. Trust and continue
  2. Quit

  enter continue · esc quit
"""
EDITOR = "╭────────────────────────────╮\n│ Codex                      │\n╰────────────────────────────╯\n\n› Ask a question\n\n  ? for shortcuts\n"


class CodexStartupTests(unittest.TestCase):
    def launch(self, screens, *, harness="codex", read_error=None, start_seconds=0,
               read_seconds=0, session=None):
        self.clock = 100.0
        self.commands = []
        self.submitted = []
        self.screens = list(screens)

        def response(argv, **kwargs):
            self.commands.append(argv)
            command = argv[1:3]
            if command == ["agent", "start"]:
                self.clock += start_seconds
                doc = {"result": {"type": "agent_started", "agent": {
                    "agent_status": "idle", "interactive_ready": True,
                    "state_change_seq": 10, "agent_session": session}}}
            elif command == ["agent", "read"]:
                self.assertEqual(argv, ["herdr", "agent", "read", "horch-abcdef", "--source", "visible"])
                self.assertLessEqual(kwargs["timeout"], 90)
                self.clock += read_seconds
                if isinstance(read_error, Exception):
                    raise read_error
                if read_error:
                    return subprocess.CompletedProcess(argv, 1, "", json.dumps({
                        "error": {"code": read_error, "message": "snapshot unavailable"}}))
                screen = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
                return subprocess.CompletedProcess(argv, 0, screen, "")
            elif command == ["agent", "get"]:
                doc = {"result": {"agent": {"agent_status": "idle", "agent_session": {
                    "agent": "pi", "source": "herdr:pi", "value": "fixture-session"}}}}
            elif command == ["agent", "prompt"]:
                self.submitted.append(argv)
                doc = {"result": {"agent": {"agent_status": "working"}}}
            elif command == ["notification", "show"]:
                doc = {"result": {}}
            else:
                self.fail(f"unexpected external command {argv!r}")
            return subprocess.CompletedProcess(argv, 0, json.dumps(doc), "")

        def sleep(seconds):
            self.clock += seconds

        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {"XDG_STATE_HOME": temporary}), \
                patch.object(horch, "require_caller_context", return_value={"workspace_id": "w1", "tab_id": "w1:t1"}), \
                patch.object(horch, "task_capacity", return_value=(0, [])), \
                patch.object(horch, "place_pane", return_value=("w1:p2", "w1:t2")), \
                patch.object(horch, "agent_index", return_value={"horch-abcdef": {"state_change_seq": 10}}), \
                patch.object(horch.secrets, "token_hex", side_effect=["abcdef", "nonce"]), \
                patch.object(horch.time, "monotonic", side_effect=lambda: self.clock), \
                patch.object(horch.time, "sleep", side_effect=sleep), \
                patch.object(horch.subprocess, "run", side_effect=response):
            config = {"max_active_workers": 4, "workers": {"worker": {
                "harness": harness, "model": "fixture-model", "provider": None,
                "effort": None, "args": []}}}
            result = horch._start_task_locked(config, "worker", "Do not delegate.", Path(temporary), False, "w1:p1")
            directory = Path(temporary) / "herdr-orchestrator/tasks" / result["task_id"]
            self.state = json.loads((directory / "state.json").read_text())
            self.assertFalse((directory / "result.json").exists())
            return result

    def assert_withheld(self, result):
        self.assertEqual(self.submitted, [], "startup UI must never receive text or Enter")
        self.assertEqual(result["state"], "start_failed")
        self.assertIsNone(self.state["baseline_seq"])
        self.assertFalse(self.state["closed"])
        self.assertFalse(self.state["saw_working"])
        self.assertFalse(any(c[1:3] in (["pane", "close"], ["agent", "send-keys"],
                                     ["pane", "send-keys"], ["pane", "send-text"])
                             for c in self.commands))

    def test_idle_interactive_ready_trust_dialog_receives_no_prompt(self):
        self.assert_withheld(self.launch([TRUST_SCREEN]))

    def test_numbered_picker_detection_does_not_depend_on_english_labels(self):
        screen = "Acceso\n\n  › 1. Confiar y continuar\n    2. Salir\n"
        self.assert_withheld(self.launch([screen]))
        self.assertNotIn("untrusted", self.state["problem"].lower())

    def test_session_hook_does_not_allow_a_prompt_to_a_visible_picker(self):
        session = {"agent": "codex", "source": "herdr:codex", "value": "another-thread"}
        self.assert_withheld(self.launch([TRUST_SCREEN], session=session))

    def test_second_option_selected_receives_no_prompt(self):
        self.assert_withheld(self.launch(["  1. Continue\n› 2. Exit\n"]))

    def test_picker_blocks_even_with_a_composer_visible_behind_it(self):
        self.assert_withheld(self.launch([EDITOR + TRUST_SCREEN]))

    def test_normal_trusted_start_submits_exactly_once(self):
        result = self.launch([EDITOR])
        self.assertEqual(result["state"], "running")
        self.assertEqual(len(self.submitted), 1)
        self.assertIn("Read", self.submitted[0][4])
        self.assertEqual(self.state["baseline_seq"], 10)

    def test_empty_composer_is_ready_without_an_english_placeholder(self):
        self.assertEqual(self.launch(["\n  › \n\n"])["state"], "running")
        self.assertEqual(len(self.submitted), 1)

    def test_trust_words_in_ordinary_output_do_not_claim_a_dialog(self):
        screen = "Previous output mentions Folder access and Trust this folder?\n" + EDITOR
        self.assertEqual(self.launch([screen])["state"], "running")
        self.assertEqual(len(self.submitted), 1)

    def test_waits_for_the_editor_within_the_existing_start_budget(self):
        self.assertEqual(self.launch(["Loading", "", EDITOR])["state"], "running")
        self.assertEqual(len(self.submitted), 1)
        self.assertGreater(self.clock, 100)
        self.assertLess(self.clock, 190)

    def test_missing_editor_exhausts_budget_without_input(self):
        self.assert_withheld(self.launch(["Loading"]))
        self.assertEqual(self.clock, 190)

    def test_expired_start_budget_withholds_input(self):
        self.assert_withheld(self.launch([EDITOR], start_seconds=90))
        self.assertFalse(any(c[1:3] == ["agent", "read"] for c in self.commands))

    def test_read_returning_after_the_deadline_does_not_allow_input(self):
        self.assert_withheld(self.launch([EDITOR], start_seconds=89, read_seconds=2))

    def test_snapshot_failure_withholds_input(self):
        self.assert_withheld(self.launch([EDITOR], read_error="transport_error"))
        self.assertIn("transport_error", self.state["problem"])

    def test_snapshot_timeout_withholds_input(self):
        self.assert_withheld(self.launch([EDITOR], read_error=subprocess.TimeoutExpired("herdr", 1)))

    def test_missing_cli_during_snapshot_withholds_input(self):
        self.assert_withheld(self.launch([EDITOR], read_error=FileNotFoundError("herdr")))

    def test_pi_and_claude_startup_keep_their_existing_contract(self):
        for harness in ("pi", "claude"):
            with self.subTest(harness=harness):
                self.assertEqual(self.launch([TRUST_SCREEN], harness=harness)["state"], "running")
                self.assertEqual(len(self.submitted), 1)
                self.assertFalse(any(c[1:3] == ["agent", "read"] for c in self.commands))


if __name__ == "__main__":
    unittest.main()
