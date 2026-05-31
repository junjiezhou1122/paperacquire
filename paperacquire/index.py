import json
import os
import tempfile
from pathlib import Path

from .models import PaperRecord, merge_record
from .paths import index_path, resolve_stored_path


EMPTY_INDEX = {"version": 1, "papers": []}


def load_index() -> dict:
    path = index_path()
    if not path.exists():
        return dict(EMPTY_INDEX)
    index_data = json.loads(path.read_text(encoding="utf-8"))
    index_data["papers"] = [_normalize_record(paper) for paper in index_data.get("papers", [])]
    return index_data


def save_index(index_data: dict) -> None:
    papers = sorted((_normalize_record(paper) for paper in index_data.get("papers", [])), key=lambda paper: paper["paper_id"])
    payload = {"version": 1, "papers": papers}
    _atomic_write_text(index_path(), json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def upsert_record(record: PaperRecord) -> dict:
    index_data = load_index()
    papers = index_data.get("papers", [])
    existing_idx = next((i for i, paper in enumerate(papers) if paper.get("paper_id") == record.paper_id), None)
    existing = papers[existing_idx] if existing_idx is not None else None
    merged = merge_record(existing, record)
    if existing_idx is None:
        papers.append(merged)
    else:
        papers[existing_idx] = merged
    index_data["papers"] = papers
    save_index(index_data)
    return merged


def get_record(paper_id: str) -> dict | None:
    for paper in load_index().get("papers", []):
        if paper.get("paper_id") == paper_id:
            return paper
    return None


def list_records() -> list[dict]:
    return load_index().get("papers", [])


def update_record_fields(paper_id: str, fields: dict) -> dict | None:
    """Patch arbitrary fields on an existing record in place.

    Returns the updated record, or ``None`` if no record matches ``paper_id``.
    Unlike :func:`upsert_record`, this does not run merge semantics; it directly
    overwrites the named keys, which is what tag/collection edits want.
    """
    index_data = load_index()
    papers = index_data.get("papers", [])
    for idx, paper in enumerate(papers):
        if paper.get("paper_id") == paper_id:
            updated = dict(paper)
            updated.update(fields)
            papers[idx] = updated
            index_data["papers"] = papers
            save_index(index_data)
            return updated
    return None


def set_tags(paper_id: str, *, add: list[str] | None = None, remove: list[str] | None = None) -> dict | None:
    """Add and/or remove tags on a record, preserving order and de-duplicating."""
    record = get_record(paper_id)
    if record is None:
        return None
    current = [t.strip() for t in (record.get("tags", []) or []) if t and t.strip()]
    remove_set = {t.strip() for t in (remove or []) if t and t.strip()}
    if remove_set:
        current = [t for t in current if t not in remove_set]
    for tag in (add or []):
        tag = tag.strip()
        if tag and tag not in current:
            current.append(tag)
    return update_record_fields(paper_id, {"tags": current})


def set_collection(paper_id: str, collection: str) -> dict | None:
    return update_record_fields(paper_id, {"collection": (collection or "").strip()})


def verify_index(repo_root: Path | None = None) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for paper in list_records():
        paper_id = paper.get("paper_id", "")
        if not paper_id:
            issues.append("record missing paper_id")
            continue
        if paper_id in seen:
            issues.append(f"duplicate paper_id: {paper_id}")
        seen.add(paper_id)
        if not paper.get("title"):
            issues.append(f"missing title: {paper_id}")
        for field in ("overview_path", "abs_path"):
            rel = paper.get(field)
            resolved = resolve_stored_path(rel)
            if rel and (resolved is None or not resolved.exists()):
                issues.append(f"missing file for {paper_id}: {rel}")

        if _is_effectively_empty(paper):
            issues.append(f"no usable local artifacts or metadata: {paper_id}")
    return issues


def _is_effectively_empty(paper: dict) -> bool:
    if paper.get("overview_path") or paper.get("abs_path"):
        return False
    if paper.get("authors") or paper.get("venue") or paper.get("published"):
        return False
    if paper.get("pdf_url") or paper.get("canonical_url") or paper.get("landing_page_url"):
        return False
    if any(value for value in paper.get("identifiers", {}).values()):
        return False
    graph_status = paper.get("graph_status", {})
    if any(value in {"fetched", "present", "available"} for value in graph_status.values()):
        return False
    return True


def _normalize_record(paper: dict) -> dict:
    normalized = dict(paper)
    normalized["organization"] = _normalize_organization_value(normalized.get("organization"))
    return normalized


def _normalize_organization_value(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("fullname", "name", "title"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        return ""
    return ""


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)
