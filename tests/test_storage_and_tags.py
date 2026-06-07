"""Offline tests for paperacquire's project-scoped storage and tagging.

These tests touch only the local filesystem (no network): path resolution,
tag/collection mutation, merge preservation, and filtering.
"""

from __future__ import annotations

import importlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


def _fresh_modules():
    """Reimport path-dependent modules so cwd/env changes are picked up."""
    import paperacquire.paths as paths
    import paperacquire.index as index
    import paperacquire.models as models

    importlib.reload(paths)
    importlib.reload(models)
    importlib.reload(index)
    return paths, index, models


class PathResolutionTests(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.pop("PAPER_ACQUIRE_HOME", None)
        self._cwd = Path.cwd()

    def tearDown(self):
        if self._env is not None:
            os.environ["PAPER_ACQUIRE_HOME"] = self._env
        else:
            os.environ.pop("PAPER_ACQUIRE_HOME", None)
        os.chdir(self._cwd)

    def test_env_override_wins(self):
        with TemporaryDirectory() as tmp:
            os.environ["PAPER_ACQUIRE_HOME"] = tmp
            paths, _, _ = _fresh_modules()
            self.assertEqual(paths.resolve_home(), Path(tmp).resolve())
            self.assertEqual(paths.papers_root(), Path(tmp).resolve() / "library")

    def test_marker_file_discovery(self):
        os.environ.pop("PAPER_ACQUIRE_HOME", None)
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".paperacquire.toml").write_text('home = "papers"\n', encoding="utf-8")
            sub = root / "a" / "b"
            sub.mkdir(parents=True)
            os.chdir(sub)
            paths, _, _ = _fresh_modules()
            self.assertEqual(paths.resolve_home(), root / "papers")

    def test_marker_dir_discovery(self):
        os.environ.pop("PAPER_ACQUIRE_HOME", None)
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            marker_dir = root / ".paperacquire"
            marker_dir.mkdir()
            os.chdir(root)
            paths, _, _ = _fresh_modules()
            self.assertEqual(paths.resolve_home(), marker_dir)


class TaggingTests(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.get("PAPER_ACQUIRE_HOME")
        self._tmp = TemporaryDirectory()
        os.environ["PAPER_ACQUIRE_HOME"] = self._tmp.name
        self.paths, self.index, self.models = _fresh_modules()

    def tearDown(self):
        if self._env is not None:
            os.environ["PAPER_ACQUIRE_HOME"] = self._env
        else:
            os.environ.pop("PAPER_ACQUIRE_HOME", None)
        self._tmp.cleanup()

    def _seed(self, paper_id="2502.12110", title="A-MEM"):
        self.index.upsert_record(self.models.PaperRecord(paper_id=paper_id, title=title))

    def test_add_remove_and_filter(self):
        self._seed()
        self.index.set_tags("2502.12110", add=["C6-evolution", "method", "dup", "dup"])
        rec = self.index.get_record("2502.12110")
        self.assertEqual(rec["tags"], ["C6-evolution", "method", "dup"])

        self.index.set_tags("2502.12110", remove=["method"])
        self.assertEqual(self.index.get_record("2502.12110")["tags"], ["C6-evolution", "dup"])

    def test_collection_roundtrip(self):
        self._seed()
        self.index.set_collection("2502.12110", "memevo-related")
        self.assertEqual(self.index.get_record("2502.12110")["collection"], "memevo-related")

    def test_merge_preserves_tags(self):
        self._seed()
        self.index.set_tags("2502.12110", add=["keep-me"])
        self.index.set_collection("2502.12110", "memevo-related")
        # Re-acquire with a record that carries no tags/collection.
        self.index.upsert_record(self.models.PaperRecord(paper_id="2502.12110", title="A-MEM v2"))
        rec = self.index.get_record("2502.12110")
        self.assertIn("keep-me", rec["tags"])
        self.assertEqual(rec["collection"], "memevo-related")
        self.assertEqual(rec["title"], "A-MEM v2")

    def test_missing_paper_returns_none(self):
        self.assertIsNone(self.index.set_tags("9999.99999", add=["x"]))

    def test_index_isolated_to_home(self):
        self._seed()
        index_file = self.paths.index_path()
        self.assertTrue(index_file.exists())
        self.assertEqual(
            index_file.resolve().parent.parent,
            Path(self._tmp.name).resolve(),
        )


if __name__ == "__main__":
    unittest.main()
