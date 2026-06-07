"""Workspace CLI commands for paperacquire.

Exposes the workspace layer as ``pa workspace`` and ``pa ws`` subcommands.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .workspace import (
    DEFAULT_WORKSPACES,
    WorkspaceManager,
    get_active_workspace_name,
)
from .paths import home_root
from .index import get_record, list_records


ACTIVE_FILE_MARKER = "active workspace"


def _wm() -> WorkspaceManager:
    return WorkspaceManager()


# ---------------------------------------------------------------------------
# workspace new
# ---------------------------------------------------------------------------

def cmd_workspace_new(args: argparse.Namespace) -> None:
    tag_schema = [t.strip() for t in (args.tag_schema or "").split(",") if t.strip()]
    data = _wm().create(args.name, title=args.title, tag_schema=tag_schema, description=args.description or "")
    print(json.dumps({"created": args.name, "path": str(home_root() / ".workspaces" / args.name), **data.meta.to_dict()}, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# workspace list
# ---------------------------------------------------------------------------

def cmd_workspace_list(args: argparse.Namespace) -> None:
    workspaces = _wm().list()
    if not workspaces:
        print(json.dumps([], indent=2))
        return
    active = get_active_workspace_name() or ""
    out = []
    for w in workspaces:
        marker = " [active]" if w.name == active else ""
        out.append({**w.to_dict(), "papers_count": _paper_count(w.name), "marker": marker})
    print(json.dumps(out, ensure_ascii=False, indent=2))


def _paper_count(name: str) -> int:
    import paperacquire.workspace as ws
    data = _wm().get(name)
    return len(data.papers) if data else 0


# ---------------------------------------------------------------------------
# workspace use / unset
# ---------------------------------------------------------------------------

def cmd_workspace_use(args: argparse.Namespace) -> None:
    _wm().set_active(args.name)
    print(json.dumps({"active": args.name, "source": ACTIVE_FILE_MARKER}, indent=2))


def cmd_workspace_unset(args: argparse.Namespace) -> None:
    _wm().unset_active()
    print(json.dumps({"active": None}, indent=2))


# ---------------------------------------------------------------------------
# workspace status
# ---------------------------------------------------------------------------

def cmd_workspace_status(args: argparse.Namespace) -> None:
    active = get_active_workspace_name()
    if not active:
        print(json.dumps({"active": None, "workspaces": [w.name for w in _wm().list()]}, indent=2))
        return
    data = _wm().get(active)
    if not data:
        print(json.dumps({"active": None}, indent=2))
        return
    state_summary: dict[str, int] = {}
    for pid, st in data.reading_state.items():
        state_summary[st] = state_summary.get(st, 0) + 1
    print(json.dumps({
        "active": active,
        "papers_count": len(data.papers),
        "state_summary": state_summary,
        "claims": list(data.position.keys()),
    }, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# workspace papers (list the papers in the active workspace)
# ---------------------------------------------------------------------------

def cmd_workspace_papers(args: argparse.Namespace) -> None:
    active = _require_active()
    wm = _wm()
    data = wm.get(active)
    if not data:
        raise SystemExit(f"workspace not found: {active}")
    state_filter = getattr(args, "state", None) or None
    tag_filter = getattr(args, "tag", None) or ""

    # Build (paper_id → record) lookup from shared library
    records = {r["paper_id"]: r for r in list_records()}

    pairs = wm.papers_with_state(active, state_filter=state_filter)
    out = []
    for pid, state in pairs:
        rec = records.get(pid, {})
        if tag_filter:
            rec_tags = rec.get("tags", []) or []
            if tag_filter not in rec_tags:
                continue
        out.append({
            "paper_id": pid,
            "title": rec.get("title", ""),
            "venue": rec.get("venue", ""),
            "year": rec.get("year"),
            "state": state,
            "tags": rec.get("tags", []),
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# workspace acquire (add papers to workspace from library or web)
# ---------------------------------------------------------------------------

def cmd_workspace_acquire(args: argparse.Namespace) -> None:
    active = _require_active()
    pids = [p.strip() for p in args.papers if p.strip()]
    if not pids:
        raise SystemExit("no paper IDs provided")
    data = _wm().add_papers(active, pids)
    if getattr(args, "no_fetch", False):
        print(json.dumps({
            "workspace": active,
            "papers_added": pids,
            "records": [],
            "papers_count": len(data.papers),
            "fetch": "skipped",
        }, indent=2, ensure_ascii=False))
        return

    # Try to upsert from index; fetch and persist missing records.
    from .cli import acquire
    upserted = []
    for pid in pids:
        existing = get_record(pid)
        if existing:
            upserted.append({"paper_id": pid, "title": existing.get("title", ""), "source": "library"})
        else:
            try:
                rec = acquire(pid)
                upserted.append({"paper_id": pid, "title": rec.get("title", ""), "source": "fetched"})
            except Exception as e:
                upserted.append({"paper_id": pid, "error": str(e)[:80]})
    print(json.dumps({"workspace": active, "papers_added": pids, "records": upserted, "papers_count": len(data.papers)}, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# workspace position (claim → papers mapping)
# ---------------------------------------------------------------------------

def cmd_workspace_position(args: argparse.Namespace) -> None:
    active = _require_active()
    if args.claim and args.papers is not None:
        paper_list = [p.strip() for p in args.papers.split(",") if p.strip()]
        data = _wm().set_position(active, args.claim, paper_list)
        print(json.dumps({"workspace": active, "claim": args.claim, "papers": paper_list}))
    elif args.remove_claim:
        _wm().remove_position(active, args.remove_claim)
        print(json.dumps({"workspace": active, "removed_claim": args.remove_claim}))
    else:
        data = _wm().get(active)
        if not data:
            raise SystemExit(f"workspace not found: {active}")
        print(json.dumps(data.position, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# workspace state
# ---------------------------------------------------------------------------

def cmd_workspace_state(args: argparse.Namespace) -> None:
    active = _require_active()
    wm = _wm()
    if args.paper_id and args.new_state:
        wm.set_state(active, args.paper_id, args.new_state)
        print(json.dumps({"workspace": active, "paper_id": args.paper_id, "state": args.new_state}))
    else:
        active2 = get_active_workspace_name() or ""
        data = wm.get(active2)
        if not data:
            print(json.dumps({}, indent=2))
            return
        state_filter = args.state_filter
        pairs = wm.papers_with_state(active2, state_filter=state_filter)
        print(json.dumps([{"paper_id": pid, "state": st} for pid, st in pairs], indent=2))


# ---------------------------------------------------------------------------
# workspace note
# ---------------------------------------------------------------------------

def cmd_workspace_note(args: argparse.Namespace) -> None:
    active = _require_active()
    if args.write is not None:
        path = _wm().write_note(active, args.paper_id, args.write)
        print(json.dumps({"workspace": active, "paper_id": args.paper_id, "path": str(path)}))
    else:
        content = _wm().read_note(active, args.paper_id)
        sys.stdout.write(content)


# ---------------------------------------------------------------------------
# workspace delete
# ---------------------------------------------------------------------------

def cmd_workspace_delete(args: argparse.Namespace) -> None:
    _wm().delete(args.name)
    print(json.dumps({"deleted": args.name}))


# ---------------------------------------------------------------------------
# workspace tag-schema
# ---------------------------------------------------------------------------

def cmd_workspace_tag_schema(args: argparse.Namespace) -> None:
    active = _require_active()
    if args.schema_set is not None:
        schema = [t.strip() for t in args.schema_set.split(",") if t.strip()]
        data = _wm().get(active)
        if not data:
            raise SystemExit(f"workspace not found: {active}")
        data.meta.tag_schema = schema
        from .workspace import _write_meta
        _write_meta(data.meta)
        print(json.dumps({"workspace": active, "tag_schema": schema}))
    else:
        data = _wm().get(active)
        if not data:
            raise SystemExit(f"workspace not found: {active}")
        print(json.dumps({"workspace": active, "tag_schema": data.meta.tag_schema}, indent=2))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _require_active() -> str:
    active = get_active_workspace_name()
    if not active:
        raise SystemExit("no active workspace — run 'pa workspace use <name>' first")
    return active


# ---------------------------------------------------------------------------
# Argument parsers (called from cli.py build_parser)
# ---------------------------------------------------------------------------

def build_workspace_parser(sub, skip_top_level: bool = False) -> None:
    """Build workspace subcommands.

    When skip_top_level is False (default), adds a "workspace" parent parser first.
    When skip_top_level is True, sub is already the result of add_subparsers() on
    a "ws" parent parser — skip creating another "workspace" layer.
    """
    if skip_top_level:
        ws_sp = sub
    else:
        ws_parser = sub.add_parser("workspace", help="Manage paper workspaces")
        ws_sp = ws_parser.add_subparsers(dest="workspace_cmd", required=True)

    new_p = ws_sp.add_parser("new", help="Create a workspace")
    new_p.add_argument("name")
    new_p.add_argument("--title", default="")
    new_p.add_argument("--tag-schema", dest="tag_schema", default="")
    new_p.add_argument("--description", dest="description", default="")
    new_p.set_defaults(func=cmd_workspace_new)

    list_p = ws_sp.add_parser("list", help="List workspaces")
    list_p.set_defaults(func=cmd_workspace_list)

    use_p = ws_sp.add_parser("use", help="Set active workspace")
    use_p.add_argument("name", help="Workspace name")
    use_p.set_defaults(func=cmd_workspace_use)

    unset_p = ws_sp.add_parser("unset", help="Clear active workspace")
    unset_p.set_defaults(func=cmd_workspace_unset)

    status_p = ws_sp.add_parser("status", help="Show workspace status")
    status_p.set_defaults(func=cmd_workspace_status)

    papers_p = ws_sp.add_parser("papers", help="List papers in active workspace")
    papers_p.add_argument("--state", default="", help="Filter by state (unread/read/cited/rejected)")
    papers_p.add_argument("--tag", default="", help="Filter by tag (AND)")
    papers_p.set_defaults(func=cmd_workspace_papers)

    acquire_p = ws_sp.add_parser("acquire", help="Add papers to active workspace")
    acquire_p.add_argument("papers", nargs="+", help="Paper IDs (arXiv IDs)")
    acquire_p.add_argument("--no-fetch", action="store_true", help="Only add IDs to the workspace; skip shared-library metadata acquisition")
    acquire_p.set_defaults(func=cmd_workspace_acquire)

    pos_p = ws_sp.add_parser("position", help="Manage claim→papers position map")
    pos_p.add_argument("--claim", default="", help="Claim key, e.g. C6-evolution")
    pos_p.add_argument("--papers", default=None, help="Comma-separated paper IDs")
    pos_p.add_argument("--remove", dest="remove_claim", default=None)
    pos_p.set_defaults(func=cmd_workspace_position)

    state_p = ws_sp.add_parser("state", help="Set or list reading states")
    state_p.add_argument("--paper-id", dest="paper_id", default="")
    state_p.add_argument("--new-state", dest="new_state", default="", help="new-state read / cited / rejected")
    state_p.add_argument("--filter", dest="state_filter", default="")
    state_p.set_defaults(func=cmd_workspace_state)

    note_p = ws_sp.add_parser("note", help="Read or write a paper note")
    note_p.add_argument("paper_id")
    note_p.add_argument("--write", default=None)
    note_p.set_defaults(func=cmd_workspace_note)

    delete_p = ws_sp.add_parser("delete", help="Delete a workspace")
    delete_p.add_argument("name")
    delete_p.set_defaults(func=cmd_workspace_delete)

    schema_p = ws_sp.add_parser("tag-schema", help="Show or update the tag schema")
    schema_p.add_argument("--set", dest="schema_set", default=None, help="Comma-separated tag names to set")
    schema_p.set_defaults(func=cmd_workspace_tag_schema)
