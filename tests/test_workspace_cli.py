import argparse
import contextlib
import io
import json
import types
import unittest
from unittest.mock import patch

from paperacquire import workspace_cli


class DummyWorkspaceManager:
    def __init__(self):
        self.data = types.SimpleNamespace(
            papers=["p1", "p2"],
            reading_state={"p1": "read", "p2": "unread"},
        )
        self.added = []
        self.state_updates = []
        self.papers_with_state_calls = []

    def get(self, name):
        return self.data

    def papers_with_state(self, name, state_filter=None):
        self.papers_with_state_calls.append((name, state_filter))
        pairs = [("p1", "read"), ("p2", "unread")]
        if state_filter:
            return [(pid, state) for pid, state in pairs if state == state_filter]
        return pairs

    def add_papers(self, name, paper_ids):
        self.added.append((name, paper_ids))
        return self.data

    def set_state(self, name, paper_id, state):
        self.state_updates.append((name, paper_id, state))
        return self.data


class WorkspaceCliTests(unittest.TestCase):
    def test_workspace_papers_uses_manager_papers_with_state(self):
        wm = DummyWorkspaceManager()
        args = argparse.Namespace(state="", tag="")

        with (
            patch.object(workspace_cli, "_wm", return_value=wm),
            patch.object(workspace_cli, "get_active_workspace_name", return_value="w1"),
            patch.object(workspace_cli, "list_records", return_value=[
                {"paper_id": "p1", "title": "Paper 1", "year": 2025},
                {"paper_id": "p2", "title": "Paper 2", "year": 2026},
            ]),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            workspace_cli.cmd_workspace_papers(args)

        self.assertEqual(wm.papers_with_state_calls, [("w1", None)])
        rows = json.loads(stdout.getvalue())
        self.assertEqual([row["paper_id"] for row in rows], ["p1", "p2"])
        self.assertEqual(rows[0]["state"], "read")

    def test_workspace_state_filter_uses_manager_papers_with_state(self):
        wm = DummyWorkspaceManager()
        args = argparse.Namespace(paper_id="", new_state="", state_filter="read")

        with (
            patch.object(workspace_cli, "_wm", return_value=wm),
            patch.object(workspace_cli, "get_active_workspace_name", return_value="w1"),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            workspace_cli.cmd_workspace_state(args)

        self.assertEqual(wm.papers_with_state_calls, [("w1", "read")])
        rows = json.loads(stdout.getvalue())
        self.assertEqual(rows, [{"paper_id": "p1", "state": "read"}])

    def test_workspace_acquire_persists_missing_records(self):
        wm = DummyWorkspaceManager()
        args = argparse.Namespace(papers=["p3"], no_fetch=False)

        with (
            patch.object(workspace_cli, "_wm", return_value=wm),
            patch.object(workspace_cli, "get_active_workspace_name", return_value="w1"),
            patch.object(workspace_cli, "get_record", return_value=None),
            patch("paperacquire.cli.acquire", return_value={"paper_id": "p3", "title": "Paper 3"}) as acquire,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            workspace_cli.cmd_workspace_acquire(args)

        acquire.assert_called_once_with("p3")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["records"], [{"paper_id": "p3", "title": "Paper 3", "source": "fetched"}])


if __name__ == "__main__":
    unittest.main()
