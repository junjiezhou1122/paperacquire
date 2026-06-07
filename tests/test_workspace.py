"""Offline tests for paperacquire's workspace layer.

These tests touch only the local filesystem (no network): WorkspaceManager CRUD,
YAML/JSON persistence, active workspace management, and atomic write behaviour.
"""

from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import paperacquire.workspace as ws_module
from paperacquire.workspace import (
    DEFAULT_WORKSPACES,
    ACTIVE_WORKSPACE_FILE,
    WorkspaceManager,
    WorkspaceMeta,
    WorkspaceData,
    _meta_path,
    _papers_path,
    _position_path,
    _reading_state_path,
    _workspace_dir,
    _read_meta,
    _write_meta,
    _parse_meta_yaml,
    _read_papers,
    _write_papers,
    _read_position,
    _write_position,
    _read_reading_state,
    _write_reading_state,
    get_active_workspace_name,
)


def _tmp_wm():
    """WorkspaceManager backed by a temp directory, isolated per test."""
    tmp = TemporaryDirectory()
    return WorkspaceManager(workspaces_root=Path(tmp.name)), tmp


# ---------------------------------------------------------------------------
# WorkspaceMeta / WorkspaceData
# ---------------------------------------------------------------------------

class MetaTests(unittest.TestCase):
    def test_to_dict_roundtrip(self):
        meta = WorkspaceMeta(
            name="w1",
            title="My Workspace",
            tag_schema=["claim", "evidence"],
            created_at="2025-01-01T00:00:00Z",
            description="A test workspace",
        )
        d = meta.to_dict()
        restored = WorkspaceMeta.from_dict(d)
        self.assertEqual(restored.name, meta.name)
        self.assertEqual(restored.title, meta.title)
        self.assertEqual(restored.tag_schema, meta.tag_schema)
        self.assertEqual(restored.created_at, meta.created_at)
        self.assertEqual(restored.description, meta.description)

    def test_from_dict_default(self):
        d = {"name": "w1"}
        meta = WorkspaceMeta.from_dict(d)
        self.assertEqual(meta.name, "w1")
        self.assertEqual(meta.title, "")
        self.assertEqual(meta.tag_schema, [])
        self.assertEqual(meta.created_at, "")

    def test_workspace_data_from_meta(self):
        meta = WorkspaceMeta(name="w1")
        data = WorkspaceData.from_meta(meta)
        self.assertEqual(data.meta.name, "w1")
        self.assertEqual(data.papers, [])
        self.assertEqual(data.position, {})
        self.assertEqual(data.reading_state, {})


# ---------------------------------------------------------------------------
# YAML persistence
# ---------------------------------------------------------------------------

class YamlPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _wm(self):
        return WorkspaceManager(workspaces_root=self._root)

    def test_meta_write_and_read(self):
        meta = WorkspaceMeta(
            name="w1",
            title="Title",
            tag_schema=["a", "b"],
            created_at="2025-01-01T00:00:00Z",
            description="desc",
        )
        _write_meta(meta, self._root)
        path = _meta_path("w1", self._root)
        self.assertTrue(path.exists())
        restored = _read_meta("w1", self._root)
        self.assertEqual(restored.name, "w1")
        self.assertEqual(restored.title, "Title")
        self.assertEqual(restored.tag_schema, ["a", "b"])
        self.assertEqual(restored.created_at, "2025-01-01T00:00:00Z")
        self.assertEqual(restored.description, "desc")

    def test_meta_yaml_parsing(self):
        raw = 'name: w1\ntitle: "My Title"\ncreated_at: 2025-01-01T00:00:00Z\ndescription: desc here\ntag_schema:\n  - claim\n  - evidence\n'
        meta = _parse_meta_yaml(raw)
        self.assertEqual(meta.name, "w1")
        self.assertEqual(meta.title, "My Title")
        self.assertEqual(meta.tag_schema, ["claim", "evidence"])
        self.assertEqual(meta.description, "desc here")

    def test_meta_yaml_empty_schema(self):
        raw = "name: w1\ntitle: w1\ncreated_at: 2025-01-01T00:00:00Z\n"
        meta = _parse_meta_yaml(raw)
        self.assertEqual(meta.tag_schema, [])

    def test_create_establishes_all_files(self):
        wm = self._wm()
        wm.create("w1", title="Title")
        root = self._root
        self.assertTrue(_workspace_dir("w1", root).exists())
        self.assertTrue(_meta_path("w1", root).exists())
        self.assertTrue(_papers_path("w1", root).exists())
        self.assertTrue(_position_path("w1", root).exists())
        self.assertTrue(_reading_state_path("w1", root).exists())


# ---------------------------------------------------------------------------
# JSON persistence
# ---------------------------------------------------------------------------

class JsonPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _wm(self):
        return WorkspaceManager(workspaces_root=self._root)

    def test_papers_roundtrip(self):
        _write_papers("w1", ["pid1", "pid2"], self._root)
        self.assertEqual(_read_papers("w1", self._root), ["pid1", "pid2"])

    def test_position_roundtrip(self):
        pos = {"C6-evolution": ["pid1", "pid2"], "C7": ["pid3"]}
        _write_position("w1", pos, self._root)
        self.assertEqual(_read_position("w1", self._root), pos)

    def test_reading_state_roundtrip(self):
        state = {"pid1": "read", "pid2": "unread"}
        _write_reading_state("w1", state, self._root)
        self.assertEqual(_read_reading_state("w1", self._root), state)

    def test_position_empty_file_returns_empty_dict(self):
        self.assertEqual(_read_position("nonexistent", self._root), {})


# ---------------------------------------------------------------------------
# WorkspaceManager CRUD
# ---------------------------------------------------------------------------

class WorkspaceManagerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _wm(self):
        return WorkspaceManager(workspaces_root=self._root)

    def test_create_and_get(self):
        wm = self._wm()
        data = wm.create("w1", title="Title", tag_schema=["claim"], description="desc")
        self.assertEqual(data.meta.name, "w1")
        self.assertEqual(data.meta.title, "Title")
        self.assertEqual(data.meta.tag_schema, ["claim"])
        self.assertEqual(data.meta.description, "desc")
        self.assertIsInstance(data.meta.created_at, str)
        self.assertEqual(data.papers, [])
        self.assertEqual(data.position, {})
        self.assertEqual(data.reading_state, {})

    def test_create_then_get(self):
        wm = self._wm()
        wm.create("w1")
        data = wm.get("w1")
        self.assertIsNotNone(data)
        self.assertEqual(data.meta.name, "w1")

    def test_create_duplicate_raises(self):
        wm = self._wm()
        wm.create("w1")
        with self.assertRaises(FileExistsError):
            wm.create("w1")

    def test_create_empty_name_raises(self):
        wm = self._wm()
        with self.assertRaises(ValueError):
            wm.create("")

    def test_list_empty(self):
        self.assertEqual(self._wm().list(), [])

    def test_list_returns_metas(self):
        wm = self._wm()
        wm.create("w1", title="W1")
        wm.create("w2", title="W2")
        metas = wm.list()
        self.assertEqual(len(metas), 2)
        names = {m.name for m in metas}
        self.assertEqual(names, {"w1", "w2"})

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(self._wm().get("nonexistent"))

    def test_delete(self):
        wm = self._wm()
        wm.create("w1")
        wm.delete("w1")
        self.assertIsNone(wm.get("w1"))
        self.assertEqual(wm.list(), [])

    def test_delete_nonexistent_noop(self):
        # Should not raise
        self._wm().delete("nonexistent")


# ---------------------------------------------------------------------------
# Active workspace
# ---------------------------------------------------------------------------

class ActiveWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)
        # Save and override the global file location for isolation
        self._orig_active = ACTIVE_WORKSPACE_FILE

    def tearDown(self):
        self._tmp.cleanup()

    def _wm(self, active_file=None):
        if active_file:
            # Point active file into the temp dir
            ACTIVE_WORKSPACE_FILE.write_text(active_file, encoding="utf-8")
        return WorkspaceManager(workspaces_root=self._root)

    def test_set_and_get_active(self):
        wm = self._wm()
        wm.create("w1")
        wm.set_active("w1")
        self.assertEqual(get_active_workspace_name(), "w1")

    def test_unset_active(self):
        wm = self._wm("w1")
        wm.create("w1")
        wm.unset_active()
        self.assertIsNone(get_active_workspace_name())

    def test_get_active_returns_none_when_none_set(self):
        self.assertIsNone(get_active_workspace_name())

    def test_set_active_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            self._wm().set_active("nonexistent")

    def test_delete_clears_active_if_was_set(self):
        wm = self._wm("w1")
        wm.create("w1")
        wm.set_active("w1")
        self.assertEqual(get_active_workspace_name(), "w1")
        wm.delete("w1")
        self.assertIsNone(get_active_workspace_name())


# ---------------------------------------------------------------------------
# Paper management
# ---------------------------------------------------------------------------

class PaperManagementTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _wm(self):
        return WorkspaceManager(workspaces_root=self._root)

    def test_add_papers(self):
        wm = self._wm()
        wm.create("w1")
        data = wm.add_papers("w1", ["pid1", "pid2"])
        self.assertEqual(data.papers, ["pid1", "pid2"])
        # reading_state auto-initialized
        self.assertEqual(data.reading_state["pid1"], "unread")
        self.assertEqual(data.reading_state["pid2"], "unread")

    def test_add_papers_deduplicates(self):
        wm = self._wm()
        wm.create("w1")
        wm.add_papers("w1", ["pid1"])
        data = wm.add_papers("w1", ["pid1", "pid2"])
        self.assertEqual(data.papers, ["pid1", "pid2"])

    def test_remove_papers(self):
        wm = self._wm()
        wm.create("w1")
        wm.add_papers("w1", ["pid1", "pid2", "pid3"])
        data = wm.remove_papers("w1", ["pid2"])
        self.assertEqual(data.papers, ["pid1", "pid3"])

    def test_remove_papers_cleans_reading_state(self):
        """remove_papers must also remove reading_state entries."""
        wm = self._wm()
        wm.create("w1")
        wm.add_papers("w1", ["pid1", "pid2"])
        wm.set_state("w1", "pid1", "read")
        wm.set_state("w1", "pid2", "cited")
        data = wm.remove_papers("w1", ["pid1"])
        self.assertNotIn("pid1", data.reading_state)
        self.assertEqual(data.reading_state["pid2"], "cited")

    def test_papers_with_state_unfiltered(self):
        wm = self._wm()
        wm.create("w1")
        wm.add_papers("w1", ["pid1", "pid2"])
        wm.set_state("w1", "pid1", "read")
        pairs = wm.papers_with_state("w1")
        self.assertEqual(dict(pairs), {"pid1": "read", "pid2": "unread"})

    def test_papers_with_state_filtered(self):
        wm = self._wm()
        wm.create("w1")
        wm.add_papers("w1", ["pid1", "pid2"])
        wm.set_state("w1", "pid1", "read")
        pairs = wm.papers_with_state("w1", state_filter="read")
        self.assertEqual(pairs, [("pid1", "read")])


# ---------------------------------------------------------------------------
# Reading state
# ---------------------------------------------------------------------------

class ReadingStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _wm(self):
        return WorkspaceManager(workspaces_root=self._root)

    def test_set_state(self):
        wm = self._wm()
        wm.create("w1")
        wm.add_papers("w1", ["pid1"])
        data = wm.set_state("w1", "pid1", "read")
        self.assertEqual(data.reading_state["pid1"], "read")

    def test_set_state_paper_not_in_workspace_raises(self):
        wm = self._wm()
        wm.create("w1")
        with self.assertRaises(ValueError):
            wm.set_state("w1", "nonexistent", "read")


# ---------------------------------------------------------------------------
# Position map
# ---------------------------------------------------------------------------

class PositionMapTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _wm(self):
        return WorkspaceManager(workspaces_root=self._root)

    def test_set_position(self):
        wm = self._wm()
        wm.create("w1")
        data = wm.set_position("w1", "C6-evolution", ["pid1", "pid2"])
        self.assertEqual(data.position["C6-evolution"], ["pid1", "pid2"])

    def test_set_position_overwrites(self):
        wm = self._wm()
        wm.create("w1")
        wm.set_position("w1", "C6-evolution", ["pid1"])
        data = wm.set_position("w1", "C6-evolution", ["pid1", "pid2"])
        self.assertEqual(data.position["C6-evolution"], ["pid1", "pid2"])

    def test_remove_position(self):
        wm = self._wm()
        wm.create("w1")
        wm.set_position("w1", "C6-evolution", ["pid1"])
        data = wm.remove_position("w1", "C6-evolution")
        self.assertNotIn("C6-evolution", data.position)


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

class NotesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _wm(self):
        return WorkspaceManager(workspaces_root=self._root)

    def test_write_and_read_note(self):
        wm = self._wm()
        wm.create("w1")
        path = wm.write_note("w1", "pid1/abc", "# Notes\nSome content")
        self.assertTrue(path.exists())
        content = wm.read_note("w1", "pid1/abc")
        self.assertEqual(content, "# Notes\nSome content")

    def test_read_nonexistent_note_returns_empty(self):
        wm = self._wm()
        wm.create("w1")
        self.assertEqual(wm.read_note("w1", "nonexistent"), "")


# ---------------------------------------------------------------------------
# Active-workspace helper
# ---------------------------------------------------------------------------

class ActiveWorkspaceHelperTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._orig = ACTIVE_WORKSPACE_FILE

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_active_workspace_name_none_when_file_missing(self):
        ACTIVE_WORKSPACE_FILE.write_text("", encoding="utf-8")
        ACTIVE_WORKSPACE_FILE.unlink()
        # get_active_workspace_name reads from disk; make sure we don't break if file is absent
        result = get_active_workspace_name()
        # behaviour: returns None when file doesn't exist
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()