"""Workspace-scoped listing reads recorded metadata without controlling workers."""
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
SPEC = importlib.util.spec_from_file_location("horch_list", SCRIPT)
horch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(horch)


class WorkspaceListTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        config = self.root / "config/herdr-orchestrator/workers.toml"
        config.parent.mkdir(parents=True)
        config.write_text('[workers.solo]\nharness = "codex"\nmodel = "test-model"\n')
        self.tasks = self.root / "state/herdr-orchestrator/tasks"

    def task(self, task_id, workspace="w1", created="2020-01-01T00:00:00Z",
             state="running", closed=False):
        directory = self.tasks / task_id
        directory.mkdir(parents=True)
        task = {
            "task_id": task_id, "nonce": task_id + "-nonce", "worker": "solo",
            "agent": "horch-" + task_id[2:], "pane_id": "recorded-pane",
            "result_path": str(directory / "result.json"), "created_at": created,
        }
        if workspace is not None:
            task["workspace_id"] = workspace
        (directory / "task.json").write_text(json.dumps(task))
        (directory / "state.json").write_text(json.dumps({"state": state, "closed": closed}))
        return directory, task

    def snapshot(self):
        return {str(path.relative_to(self.root)): (
            path.stat().st_mtime_ns, path.stat().st_mode,
            path.read_bytes() if path.is_file() else None,
        ) for path in [self.root, *self.root.rglob("*")]}

    def invoke(self, *arguments, in_herdr=True):
        before = self.snapshot()
        output = io.StringIO()
        code = 0
        with ExitStack() as stack:
            environment = {
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "XDG_STATE_HOME": str(self.root / "state"),
            }
            if in_herdr:
                environment["HERDR_ENV"] = "1"
            stack.enter_context(patch.dict(os.environ, environment, clear=True))
            forbidden = []
            for owner, name in (
                (horch, "herdr"), (horch, "require_caller_context"),
                (horch, "workspace_panes"), (horch, "notify"),
                (horch, "task_store_lock"), (horch, "task_state_lock"),
                (horch, "write_json"), (horch.subprocess, "run"),
                (horch.subprocess, "Popen"), (horch.fcntl, "flock"),
            ):
                forbidden.append(stack.enter_context(patch.object(
                    owner, name, side_effect=AssertionError("listing called " + name))))
            with redirect_stdout(output):
                try:
                    horch.main(list(arguments))
                except SystemExit as exc:
                    code = exc.code
            for call in forbidden:
                call.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        return code, [json.loads(line) for line in output.getvalue().splitlines()]

    def listing(self, *arguments):
        code, rows = self.invoke("list", *arguments)
        self.assertEqual(code, 0)
        return rows

    def test_default_all_and_scoped_rows_keep_schema_and_order(self):
        expected = []
        for task_id, workspace, created, state, closed in (
            ("t-000004", "w1", "2020-01-02T00:00:00Z", "done", True),
            ("t-000003", "w2", "2020-01-01T00:00:00Z", "blocked", False),
            ("t-000002", "w1", "2020-01-01T00:00:00Z", "running", False),
            ("t-000001", None, "2020-01-01T00:00:00Z", "done", True),
        ):
            self.task(task_id, workspace, created, state, closed)
            expected.append({
                "task_id": task_id, "worker": "solo", "agent": "horch-" + task_id[2:],
                "pane_id": "recorded-pane", "workspace_id": workspace, "state": state,
                "closed": closed, "created_at": created,
            })
        expected.sort(key=lambda row: (row["created_at"], row["task_id"]))
        self.assertEqual(self.listing(), expected)
        for workspace in ("w1", "w2", "unknown", "w"):
            with self.subTest(workspace=workspace):
                self.assertEqual(self.listing("--workspace", workspace),
                                 [row for row in expected if row["workspace_id"] == workspace])

    def test_scoped_malformed_records_use_known_raw_workspace(self):
        known_other = []
        unknown = []
        for index, workspace in enumerate(("w2", "w2", "w2", "w1", None,
                                            "", " \t", 3, [], None), start=1):
            task_id = f"t-{index:06x}"
            directory, task = self.task(task_id, workspace)
            if index == 1:
                task["task_id"] = "t-ffffff"
            elif index == 2:
                task["created_at"] = "invalid"
            else:
                del task["worker"]
            if index == 10:
                task["workspace_id"] = None
            (directory / "task.json").write_text(json.dumps(task))
            (known_other if index <= 3 else unknown).append(task_id)
        for index, content in enumerate((b"{", b"[]", b"null", b"\xff"), start=11):
            task_id = f"t-{index:06x}"
            directory, _ = self.task(task_id)
            (directory / "task.json").write_bytes(content)
            unknown.append(task_id)
        self.task("t-00000f", None)  # Valid legacy records have no scoped match.
        self.task("t-000010", "w1")

        scoped = self.listing("--workspace", "w1")
        self.assertEqual([row["task_id"] for row in scoped], unknown + ["t-000010"])
        for row in scoped[:-1]:
            self.assertEqual(row["state"], "task_invalid")
            self.assertEqual(row["error"], "task_invalid")
            self.assertEqual(set(row), {"task_id", "state", "error", "message"})
        whole = self.listing()
        self.assertEqual([row["task_id"] for row in whole],
                         known_other + unknown + ["t-00000f", "t-000010"])

    def test_state_fallbacks_remain_unchanged(self):
        for index, content in enumerate((None, "{", "[]", '{"state": "custom"}'), start=1):
            directory, _ = self.task(f"t-{index:06x}")
            state_path = directory / "state.json"
            if content is None:
                state_path.unlink()
            else:
                state_path.write_text(content)
        rows = self.listing()
        self.assertEqual([row["state"] for row in rows], ["running"] * 3 + ["custom"])
        self.assertEqual(self.listing("--workspace", "w1"), rows)

    def test_empty_store_is_not_created(self):
        self.assertEqual(self.listing(), [])
        self.assertEqual(self.listing("--workspace", "w1"), [])
        self.assertFalse((self.root / "state").exists())

    def test_blank_workspace_rejection_matches_stats(self):
        self.task("t-000001")
        for workspace in ("", " ", "\t\n"):
            with self.subTest(workspace=workspace):
                code, rows = self.invoke("list", "--workspace", workspace)
                stats_code, stats_rows = self.invoke("stats", "--workspace", workspace)
                self.assertEqual(code, 1)
                self.assertEqual(stats_code, code)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["error"], "invalid_arguments")
                self.assertEqual(set(rows[0]), {"error", "message"})
                self.assertEqual(len(stats_rows), 1)
                self.assertEqual(stats_rows[0]["error"], rows[0]["error"])
                self.assertEqual(set(stats_rows[0]), set(rows[0]))

    def test_herdr_environment_requirement_is_preserved(self):
        for arguments in ((), ("--workspace", "w1")):
            with self.subTest(arguments=arguments):
                code, rows = self.invoke("list", *arguments, in_herdr=False)
                self.assertEqual(code, 1)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["error"], "not_in_herdr")


if __name__ == "__main__":
    unittest.main()
