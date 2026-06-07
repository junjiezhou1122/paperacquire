"""Workspace management for paper-acquire.

Workspaces layer a lightweight reference/sharing/progress tracking layer on top of
the shared acquisition library.  Each workspace is a named working context (e.g. one paper
you are writing) that tracks:

- which papers it references (``papers.tsv``)
- the claim→papers position map (``position.json``)           e.g. "C6-evolution ← Live-Evo, MemEvolve"
- per-paper reading state (``reading-state.json``)          e.g. "unread / read / cited / rejected"
- per-paper notes directory (``notes/``)

The actual paper metadata (titles, abstracts, venue, citations) lives in the shared
library (``library/index.json``).  A workspace never duplicates that data; it only
stores IDs and references.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_WORKSPACES = Path.home() / ".paperacquire" / "workspaces"
ACTIVE_WORKSPACE_FILE = Path.home() / ".paperacquire" / "active_workspace"


@dataclass
class WorkspaceMeta:
    name: str
    title: str = ""
    tag_schema: list[str] = field(default_factory=list)
    created_at: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "tag_schema": self.tag_schema,
            "created_at": self.created_at,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkspaceMeta":
        return cls(
            name=d.get("name", ""),
            title=d.get("title", ""),
            tag_schema=list(d.get("tag_schema") or []),
            created_at=d.get("created_at", ""),
            description=d.get("description", ""),
        )


@dataclass
class WorkspaceData:
    meta: WorkspaceMeta
    papers: list[str] = field(default_factory=list)  # paper_ids
    position: dict[str, list[str]] = field(default_factory=dict)  # claim → [paper_ids]
    reading_state: dict[str, str] = field(default_factory=dict)  # paper_id → state

    @classmethod
    def from_meta(cls, meta: WorkspaceMeta) -> "WorkspaceData":
        return cls(meta=meta)


def _workspace_dir(name: str, root: Path | None = None) -> Path:
    return (root or DEFAULT_WORKSPACES) / name


def _meta_path(name: str, root: Path | None = None) -> Path:
    return _workspace_dir(name, root) / "workspace.yaml"


def _papers_path(name: str, root: Path | None = None) -> Path:
    return _workspace_dir(name, root) / "papers.tsv"


def _position_path(name: str, root: Path | None = None) -> Path:
    return _workspace_dir(name, root) / "position.json"


def _reading_state_path(name: str, root: Path | None = None) -> Path:
    return _workspace_dir(name, root) / "reading-state.json"


def _notes_dir(name: str, root: Path | None = None) -> Path:
    return _workspace_dir(name, root) / "notes"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# WorkspaceManager — all public operations
# ---------------------------------------------------------------------------

class WorkspaceManager:
    """Create, inspect, and mutate workspaces.  All operations are file-based and
    atomic (write-to-temp + rename).  Never mutate shared library data."""

    def __init__(self, workspaces_root: Path | None = None):
        self._workspaces_root = workspaces_root or DEFAULT_WORKSPACES

    # -- creation --

    def create(self, name: str, title: str = "", tag_schema: list[str] | None = None, description: str = "") -> WorkspaceData:
        """Create a new named workspace, fail if it already exists."""
        if not name:
            raise ValueError("workspace name cannot be empty")
        d = _workspace_dir(name, self._workspaces_root)
        if d.exists():
            raise FileExistsError(f"workspace already exists: {name}")

        d.mkdir(parents=True, exist_ok=True)
        (_notes_dir(name, self._workspaces_root)).mkdir(parents=True)

        meta = WorkspaceMeta(
            name=name,
            title=title or name,
            tag_schema=list(tag_schema) if tag_schema else [],
            created_at=_now_iso(),
            description=description,
        )
        _write_meta(meta, self._workspaces_root)
        data = WorkspaceData(meta=meta)
        _write_papers(name, [], self._workspaces_root)
        _write_position(name, {}, self._workspaces_root)
        _write_reading_state(name, {}, self._workspaces_root)
        return data

    # -- listing --

    def list(self) -> list[WorkspaceMeta]:
        """List all workspaces (names only, lightweight)."""
        if not self._workspaces_root.exists():
            return []
        metas: list[WorkspaceMeta] = []
        for d in sorted(self._workspaces_root.iterdir()):
            if d.is_dir() and (d / "workspace.yaml").exists():
                try:
                    meta = _read_meta(d.name, self._workspaces_root)
                    if meta:
                        metas.append(meta)
                except Exception:
                    pass
        return metas

    def get(self, name: str) -> WorkspaceData | None:
        """Load full workspace data. Returns None if not found."""
        if not _workspace_dir(name, self._workspaces_root).exists():
            return None
        meta = _read_meta(name, self._workspaces_root)
        if not meta:
            return None
        papers = _read_papers(name, self._workspaces_root)
        position = _read_position(name, self._workspaces_root)
        reading_state = _read_reading_state(name, self._workspaces_root)
        return WorkspaceData(
            meta=meta,
            papers=papers,
            position=position,
            reading_state=reading_state,
        )

    # -- active workspace --

    def get_active(self) -> WorkspaceData | None:
        """Return the currently active workspace, or None."""
        active = get_active_workspace_name()
        if not active:
            return None
        return self.get(active)

    def set_active(self, name: str) -> None:
        """Set the active workspace (switch working context)."""
        if not _workspace_dir(name, self._workspaces_root).exists():
            raise FileNotFoundError(f"no such workspace: {name}")
        ACTIVE_WORKSPACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTIVE_WORKSPACE_FILE.write_text(name, encoding="utf-8")

    def unset_active(self) -> None:
        """Clear the active workspace."""
        if ACTIVE_WORKSPACE_FILE.exists():
            ACTIVE_WORKSPACE_FILE.unlink()

    # -- paper references --

    def add_papers(self, name: str, paper_ids: list[str]) -> WorkspaceData:
        """Add paper IDs to workspace.  Deduplicates.  Returns updated data."""
        data = self.get(name)
        if not data:
            raise FileNotFoundError(f"workspace not found: {name}")
        existing = set(data.papers)
        for pid in paper_ids:
            pid = pid.strip()
            if pid and pid not in existing:
                data.papers.append(pid)
                existing.add(pid)
                if pid not in data.reading_state:
                    data.reading_state[pid] = "unread"
        _write_papers(name, data.papers, self._workspaces_root)
        _write_reading_state(name, data.reading_state, self._workspaces_root)
        return data

    def remove_papers(self, name: str, paper_ids: list[str]) -> WorkspaceData:
        """Remove paper IDs from workspace.  Returns updated data."""
        data = self.get(name)
        if not data:
            raise FileNotFoundError(f"no such workspace: {name}")
        remove_set = {p.strip() for p in paper_ids}
        data.papers = [p for p in data.papers if p not in remove_set]
        for pid in remove_set:
            data.reading_state.pop(pid, None)
        _write_papers(name, data.papers, self._workspaces_root)
        _write_reading_state(name, data.reading_state, self._workspaces_root)
        return data

    def papers_with_state(self, name: str, state_filter: str | None = None) -> list[tuple[str, str]]:
        """Return (paper_id, reading_state) pairs, optionally filtered by state."""
        data = self.get(name)
        if not data:
            return []
        if not state_filter:
            return [(pid, data.reading_state.get(pid, "unread")) for pid in data.papers]
        return [
            (pid, st) for pid, st in data.reading_state.items()
            if st == state_filter and pid in data.papers
        ]

    # -- reading state --

    def set_state(self, name: str, paper_id: str, state: str) -> WorkspaceData:
        """Set the reading state for one paper."""
        data = self.get(name)
        if not data:
            raise FileNotFoundError(f"no such workspace: {name}")
        if paper_id not in data.papers:
            raise ValueError(f"paper {paper_id} not in workspace {name}")
        data.reading_state[paper_id] = state
        _write_reading_state(name, data.reading_state, self._workspaces_root)
        return data

    # -- position map --

    def set_position(self, name: str, claim: str, paper_ids: list[str]) -> WorkspaceData:
        """Assign which papers support/contradict a claim (e.g. "C6-evolution")."""
        data = self.get(name)
        if not data:
            raise FileNotFoundError(f"no such workspace: {name}")
        data.position[claim] = paper_ids
        _write_position(name, data.position, self._workspaces_root)
        return data

    def remove_position(self, name: str, claim: str) -> WorkspaceData:
        data = self.get(name)
        if not data:
            raise FileNotFoundError(f"no such workspace: {name}")
        data.position.pop(claim, None)
        _write_position(name, data.position, self._workspaces_root)
        return data

    # -- notes --

    def note_path(self, name: str, paper_id: str) -> Path:
        """Return the path to a paper's note file (create dir if needed)."""
        nd = _notes_dir(name, self._workspaces_root)
        nd.mkdir(parents=True, exist_ok=True)
        safe_pid = paper_id.replace("/", "_")
        return nd / f"{safe_pid}.md"

    def read_note(self, name: str, paper_id: str) -> str:
        p = self.note_path(name, paper_id)
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8")

    def write_note(self, name: str, paper_id: str, content: str) -> Path:
        p = self.note_path(name, paper_id)
        p.write_text(content, encoding="utf-8")
        return p

    # -- delete --

    def delete(self, name: str) -> None:
        """Delete a workspace and all its files."""
        d = _workspace_dir(name, self._workspaces_root)
        if d.exists():
            shutil.rmtree(d)
        if get_active_workspace_name() == name:
            self.unset_active()


# ---------------------------------------------------------------------------
# Standalone helpers (used by CLI to avoid instantiating WorkspaceManager when not needed)
# ---------------------------------------------------------------------------

def get_active_workspace_name() -> str | None:
    if not ACTIVE_WORKSPACE_FILE.exists():
        return None
    return ACTIVE_WORKSPACE_FILE.read_text(encoding="utf-8").strip() or None


# ---------------------------------------------------------------------------
# Internal read/write helpers (all use atomic write: temp + rename)
# ---------------------------------------------------------------------------

def _write_meta(meta: WorkspaceMeta, root: Path | None = None) -> None:
    import tempfile

    p = _meta_path(meta.name, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    try:
        tmp.write(_meta_to_yaml(meta))
        tmp.close()
        os.replace(tmp.name, p)
    except Exception:
        os.unlink(tmp.name)
        raise


def _meta_to_yaml(meta: WorkspaceMeta) -> str:
    lines = [
        f"name: {meta.name}",
        f"title: {meta.title or meta.name}",
        f"created_at: {meta.created_at}",
    ]
    if meta.description:
        lines.append(f"description: {meta.description}")
    if meta.tag_schema:
        lines.append("tag_schema:")
        for t in meta.tag_schema:
            lines.append(f"  - {t}")
    return "\n".join(lines) + "\n"


def _read_meta(name: str, root: Path | None = None) -> WorkspaceMeta | None:
    p = _meta_path(name, root)
    if not p.exists():
        return None
    raw = p.read_text(encoding="utf-8")
    return _parse_meta_yaml(raw)


def _parse_meta_yaml(raw: str) -> WorkspaceMeta:
    name = ""
    title = ""
    created_at = ""
    description = ""
    tag_schema: list[str] = []
    in_schema = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            name = stripped[5:].strip().strip('"').strip("'")
        elif stripped.startswith("title:"):
            title = stripped[6:].strip().strip('"').strip("'")
        elif stripped.startswith("created_at:"):
            created_at = stripped[11:].strip()
        elif stripped.startswith("description:"):
            description = stripped[13:].strip().strip('"').strip("'")
        elif stripped.startswith("tag_schema:"):
            in_schema = True
        elif in_schema and stripped.startswith("- "):
            tag_schema.append(stripped[1:].strip())
        elif in_schema and not line.startswith(" "):
            in_schema = False
    return WorkspaceMeta(name=name, title=title or name, tag_schema=tag_schema, created_at=created_at, description=description)


def _write_papers(name: str, papers: list[str], root: Path | None = None) -> None:
    _atomic_write_json(_papers_path(name, root), {"papers": papers})


def _read_papers(name: str, root: Path | None = None) -> list[str]:
    d = _read_json(_papers_path(name, root))
    return list(d.get("papers", [])) if d else []


def _write_position(name: str, position: dict[str, list[str]], root: Path | None = None) -> None:
    _atomic_write_json(_position_path(name, root), position)


def _read_position(name: str, root: Path | None = None) -> dict[str, list[str]]:
    p = _position_path(name, root)
    if not p.exists():
        return {}
    return _read_json(p) or {}


def _write_reading_state(name: str, state: dict[str, str], root: Path | None = None) -> None:
    _atomic_write_json(_reading_state_path(name, root), state)


def _read_reading_state(name: str, root: Path | None = None) -> dict[str, str]:
    p = _reading_state_path(name, root)
    if not p.exists():
        return {}
    return _read_json(p) or {}


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
