from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .backfill import build_backfill_records, infer_title_from_abs, infer_title_from_overview
from .bibliography import extract_reference_candidates_for_paper, resolve_reference_candidates_for_paper
from .graph import expand_graph
from .index import get_record, list_records, set_collection, set_tags, upsert_record, verify_index
from .models import PaperRecord
from .normalize import normalize_input, strip_version
from .paths import DEFAULT_GLOBAL_HOME, abs_path_for, ensure_storage_dirs, home_root, overview_path_for, resolve_stored_path, to_repo_relative
from .preview import build_preview_page
from .search import search_papers as search_for_papers
from .sources.alphaxiv import (
    AlphaXivFetchResult,
    fetch_feed_papers as fetch_alphaxiv_feed_papers,
    fetch_metadata,
    fetch_paper as fetch_alphaxiv_paper,
    fetch_top_papers as fetch_alphaxiv_top_papers,
)
from .sources.arxiv import get_arxiv_info
from .sources.huggingface import HuggingFaceFetchResult, fetch_daily_papers as fetch_huggingface_daily_papers, fetch_paper as fetch_huggingface_paper
from .sources.openalex import fetch_work as fetch_openalex_work
from .sources.dblp import search_papers_by_venue as search_dblp_venue
from .sources.openreview_adaptive import search_papers_by_venue as search_openreview_venue


HF_ENRICH_FIELDS = (
    "ai_summary",
    "ai_keywords",
    "github_repo",
    "github_stars",
    "organization",
    "upvotes",
    "comments",
)
from .sources.semantic_scholar import fetch_paper as fetch_semantic_paper


FEED_PROVIDERS = {
    "alphaxiv": lambda limit: fetch_alphaxiv_feed_papers(limit=limit, sort="trending", interval="7d") + fetch_alphaxiv_top_papers(limit=limit),
    "huggingface": lambda limit: fetch_huggingface_daily_papers(limit=limit),
}


def _write_text(path: Path, content: str | None) -> Path | None:
    if not content:
        return None
    path.write_text(content, encoding="utf-8")
    return path


def _safe_fetch(fetcher, *args):
    try:
        return fetcher(*args)
    except Exception:
        return None


def _build_paper_record(input_value: str) -> PaperRecord:
    ensure_storage_dirs()
    normalized = normalize_input(input_value)
    paper_id = _resolve_paper_id_for_acquire(normalized)
    if not paper_id:
        raise ValueError(f"Acquire expects an arXiv-backed paper input, got: {input_value}")

    existing = get_record(paper_id) or {}
    fetch_input = normalized.paper_id_input or paper_id
    alphaxiv_result = _safe_fetch(fetch_alphaxiv_paper, fetch_input)
    hf_result = _safe_fetch(fetch_huggingface_paper, fetch_input)
    arxiv_info = get_arxiv_info(paper_id)

    if alphaxiv_result is None:
        alphaxiv_result = AlphaXivFetchResult()
    if hf_result is None:
        hf_result = HuggingFaceFetchResult()

    overview_written = _write_text(overview_path_for(paper_id), alphaxiv_result.overview_markdown)
    abs_content = alphaxiv_result.abs_markdown or hf_result.markdown
    abs_written = _write_text(abs_path_for(paper_id), abs_content)

    overview_rel = to_repo_relative(overview_written) or existing.get("overview_path")
    abs_rel = to_repo_relative(abs_written) or existing.get("abs_path")

    title = alphaxiv_result.title or hf_result.title or existing.get("title", "")
    if not title and overview_rel:
        title = infer_title_from_overview(resolve_stored_path(overview_rel))
    if not title and abs_rel:
        title = infer_title_from_abs(resolve_stored_path(abs_rel))

    sources = []
    if alphaxiv_result.title or alphaxiv_result.overview_markdown or alphaxiv_result.abs_markdown:
        sources.append("alphaxiv")
    if hf_result.title or hf_result.markdown:
        sources.append("huggingface")
    if normalized.source_hint == "arxiv":
        sources.append("arxiv")
    if not sources:
        sources.append(normalized.source_hint)

    status = {
        "overview": "present" if overview_rel else "missing",
        "abs": "present" if abs_rel else "missing",
    }
    if hf_result.markdown and not abs_rel:
        status["hf_markdown"] = "available"

    identifiers = dict(existing.get("identifiers", {}))
    identifiers.update({
        "arxiv_id": paper_id,
        "doi": normalized.doi or identifiers.get("doi", ""),
        "openalex_id": normalized.openalex_id or identifiers.get("openalex_id", ""),
        "semantic_scholar_id": normalized.semantic_scholar_id or identifiers.get("semantic_scholar_id", ""),
    })
    return PaperRecord(
        paper_id=paper_id,
        title=title,
        source=sources[0],
        sources=sources,
        source_input=normalized.source_input,
        canonical_url=alphaxiv_result.canonical_url or hf_result.canonical_url or arxiv_info.canonical_url,
        overview_path=overview_rel,
        abs_path=abs_rel,
        authors=alphaxiv_result.authors or hf_result.authors or existing.get("authors", []),
        published=alphaxiv_result.published or hf_result.published or existing.get("published", ""),
        status=status,
        identifiers=identifiers,
        pdf_url=existing.get("pdf_url") or arxiv_info.pdf_url,
        landing_page_url=hf_result.canonical_url or arxiv_info.canonical_url,
        source_topics=[topic.strip() for topic in (alphaxiv_result.topics or []) if topic and topic.strip()],
        ai_summary=hf_result.ai_summary or existing.get("ai_summary", ""),
        ai_keywords=hf_result.ai_keywords or existing.get("ai_keywords", []),
        github_repo=hf_result.github_repo or existing.get("github_repo", ""),
        github_stars=hf_result.github_stars if hf_result.github_stars is not None else existing.get("github_stars"),
        organization=hf_result.organization or existing.get("organization", ""),
        upvotes=hf_result.upvotes if hf_result.upvotes is not None else existing.get("upvotes"),
        comments=hf_result.comments if hf_result.comments is not None else existing.get("comments"),
    )


def _persist_paper_record(record: PaperRecord) -> dict:
    return upsert_record(record)


def acquire(input_value: str) -> dict:
    return _persist_paper_record(_build_paper_record(input_value))


def _resolve_paper_id_for_acquire(normalized) -> str:
    if normalized.input_kind == "paper" and normalized.paper_id:
        return normalized.paper_id
    if normalized.input_kind != "external_id":
        return ""

    candidates = [
        _resolved_paper_id_from_node(_safe_fetch(fetch_openalex_work, normalized.openalex_id)) if normalized.openalex_id else "",
        _resolved_paper_id_from_node(_safe_fetch(fetch_openalex_work, normalized.doi)) if normalized.doi else "",
        _resolved_paper_id_from_node(_safe_fetch(fetch_semantic_paper, normalized.semantic_scholar_id)) if normalized.semantic_scholar_id else "",
        _resolved_paper_id_from_node(_safe_fetch(fetch_semantic_paper, normalized.doi)) if normalized.doi else "",
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return ""


def _resolved_paper_id_from_node(node) -> str:
    if node is None:
        return ""
    paper_id = getattr(node, "paper_id", "") or ""
    identifiers = getattr(node, "identifiers", {}) or {}
    return strip_version(paper_id or identifiers.get("arxiv_id", "") or "")


def _failed_reference_result(position: int, match: dict, exc: Exception) -> dict:
    return {
        "position": position,
        "resolved_paper_id": match.get("resolved_paper_id"),
        "matched_title": match.get("matched_title") or match.get("title_guess"),
        "error": str(exc),
    }


def _acquired_reference_result(record: dict, match: dict) -> dict:
    return {
        "resolved_paper_id": record.get("paper_id"),
        "title": record.get("title") or match.get("matched_title") or match.get("title_guess"),
        "overview_path": record.get("overview_path"),
        "abs_path": record.get("abs_path"),
    }


def _sorted_reference_results(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda item: item["position"])


def cmd_acquire(args: argparse.Namespace) -> None:
    record = acquire(args.input)
    print(json.dumps(record, ensure_ascii=False, indent=2))


def cmd_backfill(args: argparse.Namespace) -> None:
    ensure_storage_dirs()
    records = build_backfill_records()
    for record in records:
        upsert_record(record)
    print(json.dumps({"backfilled": len(records)}, ensure_ascii=False))


def _filter_records(records: list[dict], *, source_topic: str = "", tag: str = "", collection: str = "") -> list[dict]:
    filtered = list(records)
    if source_topic:
        filtered = [
            record
            for record in filtered
            if source_topic in [item.strip() for item in (record.get("source_topics", []) or []) if item and item.strip()]
        ]
    if tag:
        wanted = [t.strip() for t in tag.split(",") if t.strip()]
        filtered = [
            record
            for record in filtered
            if all(
                w in [item.strip() for item in (record.get("tags", []) or []) if item and item.strip()]
                for w in wanted
            )
        ]
    if collection:
        filtered = [record for record in filtered if (record.get("collection", "") or "").strip() == collection.strip()]
    return filtered


def _refresh_record_metadata(record: dict) -> dict:
    paper_id = record.get("paper_id", "")
    if not paper_id:
        return record
    metadata = fetch_metadata(paper_id)
    paper_version = metadata.get("paper_version", {})
    authors_data = metadata.get("authors", [])
    authors = [author.get("full_name", "") for author in authors_data if author.get("full_name")]
    refreshed = PaperRecord(
        paper_id=paper_id,
        title=paper_version.get("title", "") or record.get("title", ""),
        source=record.get("source", ""),
        sources=record.get("sources", []),
        source_input=record.get("source_input", paper_id),
        canonical_url=record.get("canonical_url", "") or f"https://arxiv.org/abs/{paper_id}",
        overview_path=record.get("overview_path"),
        abs_path=record.get("abs_path"),
        authors=authors or record.get("authors", []),
        published=paper_version.get("publication_date", "") or record.get("published", ""),
        status=record.get("status", {}),
        identifiers=record.get("identifiers", {}),
        venue=record.get("venue", ""),
        year=record.get("year"),
        citation_count=record.get("citation_count"),
        pdf_url=record.get("pdf_url", ""),
        landing_page_url=record.get("landing_page_url", ""),
        graph_status=record.get("graph_status", {}),
        source_topics=[topic.strip() for topic in ((metadata.get("paper_group", {}) or {}).get("topics", []) or []) if topic and topic.strip()],
    )
    return upsert_record(refreshed)


def cmd_list(args: argparse.Namespace) -> None:
    records = _filter_records(
        list_records(),
        source_topic=args.source_topic,
        tag=getattr(args, "tag", "") or "",
        collection=getattr(args, "collection", "") or "",
    )
    print(json.dumps(records, ensure_ascii=False, indent=2))


def cmd_show(args: argparse.Namespace) -> None:
    record = get_record(args.paper_id)
    if record is None:
        raise SystemExit(f"Paper not found: {args.paper_id}")
    print(json.dumps(record, ensure_ascii=False, indent=2))


def cmd_tag(args: argparse.Namespace) -> None:
    add = [t.strip() for t in (args.add or "").split(",") if t.strip()]
    remove = [t.strip() for t in (args.remove or "").split(",") if t.strip()]
    if not add and not remove:
        raise SystemExit("Nothing to do: pass --add and/or --remove")
    updated = set_tags(args.paper_id, add=add, remove=remove)
    if updated is None:
        raise SystemExit(f"Paper not found: {args.paper_id}")
    print(json.dumps({"paper_id": args.paper_id, "tags": updated.get("tags", [])}, ensure_ascii=False, indent=2))


def cmd_untag(args: argparse.Namespace) -> None:
    remove = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    if not remove:
        raise SystemExit("Nothing to remove: pass comma-separated tags")
    updated = set_tags(args.paper_id, remove=remove)
    if updated is None:
        raise SystemExit(f"Paper not found: {args.paper_id}")
    print(json.dumps({"paper_id": args.paper_id, "tags": updated.get("tags", [])}, ensure_ascii=False, indent=2))


def cmd_collection(args: argparse.Namespace) -> None:
    updated = set_collection(args.paper_id, args.name)
    if updated is None:
        raise SystemExit(f"Paper not found: {args.paper_id}")
    print(json.dumps({"paper_id": args.paper_id, "collection": updated.get("collection", "")}, ensure_ascii=False, indent=2))


def cmd_where(args: argparse.Namespace) -> None:
    from .paths import abs_dir, graph_path, index_path, overview_dir, papers_root

    home = home_root()
    env = os.environ.get("PAPER_ACQUIRE_HOME", "")
    if env.strip():
        source = "env:PAPER_ACQUIRE_HOME"
    elif home == DEFAULT_GLOBAL_HOME:
        source = "default:~/.paperacquire"
    else:
        source = "marker:.paperacquire(.toml)"
    idx = index_path()
    paper_count = 0
    if idx.exists():
        try:
            paper_count = len(json.loads(idx.read_text(encoding="utf-8")).get("papers", []))
        except (ValueError, OSError):
            paper_count = 0
    print(json.dumps({
        "home": str(home),
        "source": source,
        "cwd": str(Path.cwd()),
        "library": str(papers_root()),
        "index": str(idx),
        "graph": str(graph_path()),
        "overview_dir": str(overview_dir()),
        "abs_dir": str(abs_dir()),
        "index_exists": idx.exists(),
        "paper_count": paper_count,
    }, ensure_ascii=False, indent=2))


def cmd_reclassify(args: argparse.Namespace) -> None:
    refreshed_records = []
    for record in list_records():
        refreshed_records.append(_refresh_record_metadata(record))
    print(json.dumps({"refreshed": len(refreshed_records)}, ensure_ascii=False))


def _has_value(value) -> bool:
    return value not in (None, "", [], {})


def _hf_enrichment_updates(record: dict, hf_result: HuggingFaceFetchResult, *, force: bool) -> dict:
    candidate_values = {
        "ai_summary": hf_result.ai_summary,
        "ai_keywords": hf_result.ai_keywords or [],
        "github_repo": hf_result.github_repo,
        "github_stars": hf_result.github_stars,
        "organization": hf_result.organization,
        "upvotes": hf_result.upvotes,
        "comments": hf_result.comments,
    }
    updates: dict = {}
    for field, value in candidate_values.items():
        if not _has_value(value):
            continue
        if force or not _has_value(record.get(field)):
            updates[field] = value
    return updates


def _enrich_record_with_huggingface(record: dict, *, force: bool) -> tuple[dict | None, str]:
    paper_id = record.get("paper_id", "")
    if not paper_id:
        return None, "skipped"
    hf_result = _safe_fetch(fetch_huggingface_paper, paper_id)
    if hf_result is None:
        return None, "failed"
    updates = _hf_enrichment_updates(record, hf_result, force=force)
    if not updates:
        return None, "skipped"
    enriched = PaperRecord(
        paper_id=paper_id,
        title=record.get("title", ""),
        source=record.get("source", ""),
        sources=record.get("sources", []),
        source_input=record.get("source_input", paper_id),
        canonical_url=record.get("canonical_url", ""),
        overview_path=record.get("overview_path"),
        abs_path=record.get("abs_path"),
        authors=record.get("authors", []),
        published=record.get("published", ""),
        status=record.get("status", {}),
        identifiers=record.get("identifiers", {}),
        venue=record.get("venue", ""),
        year=record.get("year"),
        citation_count=record.get("citation_count"),
        pdf_url=record.get("pdf_url", ""),
        landing_page_url=record.get("landing_page_url", ""),
        graph_status=record.get("graph_status", {}),
        source_topics=record.get("source_topics", []),
        ai_summary=updates.get("ai_summary", ""),
        ai_keywords=updates.get("ai_keywords", []),
        github_repo=updates.get("github_repo", ""),
        github_stars=updates.get("github_stars"),
        organization=updates.get("organization", ""),
        upvotes=updates.get("upvotes"),
        comments=updates.get("comments"),
    )
    return upsert_record(enriched), "enriched"


def cmd_enrich_hf(args: argparse.Namespace) -> None:
    scanned = 0
    enriched = 0
    skipped = 0
    failed = 0
    changed_papers: list[str] = []
    failed_papers: list[str] = []
    for record in list_records():
        scanned += 1
        updated_record, status = _enrich_record_with_huggingface(record, force=args.force)
        if status == "enriched":
            enriched += 1
            if updated_record and updated_record.get("paper_id"):
                changed_papers.append(updated_record["paper_id"])
        elif status == "failed":
            failed += 1
            if record.get("paper_id"):
                failed_papers.append(record["paper_id"])
        else:
            skipped += 1
    print(json.dumps({
        "scanned": scanned,
        "enriched": enriched,
        "skipped": skipped,
        "failed": failed,
        "force": args.force,
        "changed_papers": changed_papers,
        "failed_papers": failed_papers,
    }, ensure_ascii=False, indent=2))


def cmd_verify(args: argparse.Namespace) -> None:
    issues = verify_index()
    print(json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False, indent=2))
    if issues:
        raise SystemExit(1)


def cmd_search(args: argparse.Namespace) -> None:
    requested_sources = [item.strip() for item in args.sources.split(",") if item.strip()] if args.sources else None
    results = search_for_papers(args.query, limit=args.limit, sources=requested_sources)
    print(json.dumps(results, ensure_ascii=False, indent=2))


VENUE_PROVIDERS = {
    "openreview": search_openreview_venue,
    "dblp": search_dblp_venue,
}


def search_venue_papers(conference: str, year: int, *, limit: int = 25, source: str = "all") -> list[dict]:
    requested_sources = list(VENUE_PROVIDERS) if source == "all" else [source]
    candidates: list[dict] = []
    for source_name in requested_sources:
        provider = VENUE_PROVIDERS.get(source_name)
        if provider is None:
            continue
        try:
            results = provider(conference, year, limit=limit)
        except Exception:
            continue
        for result in results:
            item = result.to_dict()
            item["venue_query"] = {"conference": conference, "year": year, "source": source_name}
            candidates.append(item)
    return _dedupe_feed_candidates(candidates)[:limit]


def _record_id_from_candidate(candidate: dict) -> str:
    identifiers = candidate.get("identifiers", {}) or {}
    paper_id = (candidate.get("paper_id") or "").strip()
    if paper_id:
        return paper_id
    for key, prefix in (("doi", "doi"), ("openreview_id", "openreview"), ("dblp_key", "dblp")):
        value = str(identifiers.get(key, "") or "").strip()
        if value:
            return f"{prefix}:{value}"
    title_key = hashlib.sha1(_normalize_title_key(candidate.get("title", "")).encode("utf-8")).hexdigest()[:16]
    return f"title:{title_key}"


def _record_from_candidate(candidate: dict, *, source_input: str) -> PaperRecord:
    return PaperRecord(
        paper_id=_record_id_from_candidate(candidate),
        title=candidate.get("title", ""),
        source=candidate.get("source", ""),
        sources=candidate.get("sources", []) or ([candidate.get("source")] if candidate.get("source") else []),
        source_input=source_input,
        canonical_url=candidate.get("canonical_url", ""),
        authors=candidate.get("authors", []),
        identifiers=candidate.get("identifiers", {}) or {},
        venue=candidate.get("venue", ""),
        year=candidate.get("year"),
        citation_count=candidate.get("citation_count"),
        pdf_url=candidate.get("pdf_url", ""),
        landing_page_url=candidate.get("landing_page_url", ""),
    )


def _ingest_search_candidates(candidates: list[dict], *, source_input: str) -> dict:
    ensure_storage_dirs()
    new_papers: list[str] = []
    existing_papers: list[str] = []
    failed: list[dict[str, str]] = []
    for candidate in candidates:
        try:
            record = _record_from_candidate(candidate, source_input=source_input)
            existing = get_record(record.paper_id)
            stored = upsert_record(record)
        except Exception as exc:
            failed.append({"title": candidate.get("title", ""), "error": str(exc)})
            continue
        if existing is None:
            new_papers.append(stored.get("paper_id", record.paper_id))
        else:
            existing_papers.append(stored.get("paper_id", record.paper_id))
    return {
        "scanned": len(candidates),
        "new_papers": sorted(new_papers),
        "existing_papers": sorted(existing_papers),
        "failed": failed,
    }


def cmd_venue(args: argparse.Namespace) -> None:
    results = search_venue_papers(args.conference, args.year, limit=args.limit, source=args.source)
    if not args.ingest:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    summary = _ingest_search_candidates(results, source_input=f"venue:{args.conference}:{args.year}:{args.source}")
    summary["results"] = results
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _normalize_title_key(title: str) -> str:
    return " ".join(part for part in "".join(char.lower() if char.isalnum() else " " for char in title).split() if part)


def _feed_candidate_key(candidate: dict) -> str:
    paper_id = (candidate.get("paper_id") or "").strip()
    if paper_id:
        return f"arxiv:{paper_id}"
    doi = str((candidate.get("identifiers") or {}).get("doi", "")).strip().lower()
    if doi:
        return f"doi:{doi}"
    return f"title:{_normalize_title_key(candidate.get('title', ''))}"


def _dedupe_feed_candidates(candidates: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for candidate in candidates:
        key = _feed_candidate_key(candidate)
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(candidate)
            continue
        existing_sources = list(existing.get("sources", []) or [])
        incoming_sources = list(candidate.get("sources", []) or [])
        existing["sources"] = sorted(set(existing_sources + incoming_sources + [existing.get("source", ""), candidate.get("source", "")]) - {""})
        if not existing.get("source"):
            existing["source"] = candidate.get("source", "")
        for field in ("paper_id", "title", "canonical_url", "landing_page_url", "pdf_url"):
            if not existing.get(field) and candidate.get(field):
                existing[field] = candidate[field]
        identifiers = dict(existing.get("identifiers", {}) or {})
        identifiers.update({key: value for key, value in (candidate.get("identifiers", {}) or {}).items() if value and not identifiers.get(key)})
        existing["identifiers"] = identifiers
    return list(merged.values())


def _fetch_feed_candidates(limit: int, sources: list[str] | None) -> list[dict]:
    requested_sources = [source for source in (sources or list(FEED_PROVIDERS)) if source in FEED_PROVIDERS]
    candidates: list[dict] = []
    for source in requested_sources:
        for item in FEED_PROVIDERS[source](limit):
            candidates.append(item.to_dict())
    return candidates


def _ingest_feed_candidates(limit: int, sources: list[str] | None) -> dict:
    scanned_candidates = _fetch_feed_candidates(limit, sources)
    candidates = _dedupe_feed_candidates(scanned_candidates)
    new_papers: list[str] = []
    existing_papers: list[str] = []
    failed: list[dict[str, str]] = []
    for candidate in candidates:
        paper_id = candidate.get("paper_id", "")
        if not paper_id:
            failed.append({"title": candidate.get("title", ""), "error": "missing_paper_id"})
            continue
        existing = get_record(paper_id)
        try:
            record = acquire(paper_id)
        except Exception as exc:
            failed.append({"paper_id": paper_id, "title": candidate.get("title", ""), "error": str(exc)})
            continue
        if existing is None:
            new_papers.append(record.get("paper_id", paper_id))
        else:
            existing_papers.append(record.get("paper_id", paper_id))
    preview_path = build_preview_page()
    return {
        "scanned": len(scanned_candidates),
        "deduped_candidates": len(candidates),
        "new_papers": sorted(new_papers),
        "existing_papers": sorted(existing_papers),
        "failed": failed,
        "preview_path": str(preview_path),
    }


def cmd_ingest_feeds(args: argparse.Namespace) -> None:
    requested_sources = [item.strip() for item in args.sources.split(",") if item.strip()] if args.sources else None
    print(json.dumps(_ingest_feed_candidates(args.limit, requested_sources), ensure_ascii=False, indent=2))


def cmd_extract_refs(args: argparse.Namespace) -> None:
    candidates = extract_reference_candidates_for_paper(args.paper_id)
    parser_counts: dict[str, int] = {}
    for candidate in candidates:
        parser = candidate.get("parser", "unknown") or "unknown"
        parser_counts[parser] = parser_counts.get(parser, 0) + 1
    parser_mode = next(iter(parser_counts), "none") if len(parser_counts) == 1 else "mixed"
    print(json.dumps({
        "paper_id": args.paper_id,
        "count": len(candidates),
        "parser_mode": parser_mode,
        "parser_counts": parser_counts,
        "references": candidates,
    }, ensure_ascii=False, indent=2))


def cmd_acquire_refs(args: argparse.Namespace) -> None:
    resolved = resolve_reference_candidates_for_paper(args.paper_id, min_year=args.min_year, limit=args.limit)
    workers = max(1, min(args.workers, len(resolved) or 1))
    prepared: list[dict] = []
    failed: list[dict] = []

    if workers == 1:
        for position, match in enumerate(resolved):
            try:
                prepared.append({
                    "position": position,
                    "match": match,
                    "record": _build_paper_record(match["resolved_input"]),
                })
            except Exception as exc:
                failed.append(_failed_reference_result(position, match, exc))
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_build_paper_record, match["resolved_input"]): (position, match)
                for position, match in enumerate(resolved)
            }
            for future in as_completed(futures):
                position, match = futures[future]
                try:
                    record = future.result()
                except Exception as exc:
                    failed.append(_failed_reference_result(position, match, exc))
                    continue
                prepared.append({
                    "position": position,
                    "match": match,
                    "record": record,
                })

    acquired: list[dict] = []
    for item in _sorted_reference_results(prepared):
        record = _persist_paper_record(item["record"])
        acquired.append(_acquired_reference_result(record, item["match"]))

    preview_path = build_preview_page()
    print(json.dumps({
        "paper_id": args.paper_id,
        "min_year": args.min_year,
        "resolved_count": len(resolved),
        "acquired_count": len(acquired),
        "failed_count": len(failed),
        "workers": workers,
        "acquired": acquired,
        "failed": [
            {
                "resolved_paper_id": item["resolved_paper_id"],
                "matched_title": item["matched_title"],
                "error": item["error"],
            }
            for item in _sorted_reference_results(failed)
        ],
        "preview_path": str(preview_path),
    }, ensure_ascii=False, indent=2))


def _run_graph_expand(input_value: str, include_references: bool, include_citations: bool, limit: int) -> dict:
    return expand_graph(input_value, include_references=include_references, include_citations=include_citations, limit=limit)


def cmd_references(args: argparse.Namespace) -> None:
    print(json.dumps(_run_graph_expand(args.input, include_references=True, include_citations=False, limit=args.limit), ensure_ascii=False, indent=2))


def cmd_citations(args: argparse.Namespace) -> None:
    print(json.dumps(_run_graph_expand(args.input, include_references=False, include_citations=True, limit=args.limit), ensure_ascii=False, indent=2))


def cmd_expand(args: argparse.Namespace) -> None:
    print(json.dumps(_run_graph_expand(args.input, include_references=True, include_citations=True, limit=args.limit), ensure_ascii=False, indent=2))


def cmd_preview_build(args: argparse.Namespace) -> None:
    output_path = build_preview_page()
    print(json.dumps({"preview_path": str(output_path)}, ensure_ascii=False, indent=2))


def cmd_pdf_link(args: argparse.Namespace) -> None:
    normalized = normalize_input(args.input)
    paper_id = normalized.paper_id
    if paper_id:
        existing = get_record(paper_id)
        pdf_url = (existing or {}).get("pdf_url") or get_arxiv_info(paper_id).pdf_url
    else:
        existing = None
        pdf_url = ""
    print(json.dumps({
        "paper_id": paper_id,
        "pdf_url": pdf_url,
        "known": bool(existing),
    }, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="paperacquire research paper library CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    acquire_parser = sub.add_parser("acquire", help="Acquire a paper and update the index")
    acquire_parser.add_argument("input", help="arXiv ID or supported paper URL")
    acquire_parser.set_defaults(func=cmd_acquire)

    backfill_parser = sub.add_parser("backfill", help="Backfill index from existing local artifacts")
    backfill_parser.set_defaults(func=cmd_backfill)

    list_parser = sub.add_parser("list", help="List indexed papers")
    list_parser.add_argument("--source-topic", default="")
    list_parser.add_argument("--tag", default="", help="Filter by tag(s); comma-separated means AND")
    list_parser.add_argument("--collection", default="", help="Filter by collection name")
    list_parser.set_defaults(func=cmd_list)

    show_parser = sub.add_parser("show", help="Show one indexed paper")
    show_parser.add_argument("paper_id")
    show_parser.set_defaults(func=cmd_show)

    tag_parser = sub.add_parser("tag", help="Add and/or remove tags on a paper")
    tag_parser.add_argument("paper_id")
    tag_parser.add_argument("--add", default="", help="Comma-separated tags to add")
    tag_parser.add_argument("--remove", default="", help="Comma-separated tags to remove")
    tag_parser.set_defaults(func=cmd_tag)

    untag_parser = sub.add_parser("untag", help="Remove tags from a paper")
    untag_parser.add_argument("paper_id")
    untag_parser.add_argument("tags", help="Comma-separated tags to remove")
    untag_parser.set_defaults(func=cmd_untag)

    collection_parser = sub.add_parser("collection", help="Set the collection for a paper")
    collection_parser.add_argument("paper_id")
    collection_parser.add_argument("name", help="Collection name (empty string clears it)")
    collection_parser.set_defaults(func=cmd_collection)

    where_parser = sub.add_parser("where", help="Show the active library home and paths")
    where_parser.set_defaults(func=cmd_where)

    reclassify_parser = sub.add_parser("reclassify", help="Refresh AlphaXiv metadata for indexed papers")
    reclassify_parser.set_defaults(func=cmd_reclassify)

    verify_parser = sub.add_parser("verify", help="Verify paper index and file consistency")
    verify_parser.set_defaults(func=cmd_verify)

    enrich_hf_parser = sub.add_parser("enrich-hf", help="Backfill Hugging Face enrichment for indexed papers")
    enrich_hf_parser.add_argument("--force", action="store_true", help="Overwrite existing Hugging Face enrichment fields")
    enrich_hf_parser.set_defaults(func=cmd_enrich_hf)

    search_parser = sub.add_parser("search", help="Search papers across supported sources")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.add_argument("--sources", help="Comma-separated subset: alphaxiv,openalex,crossref,dblp,huggingface,openreview")
    search_parser.set_defaults(func=cmd_search)

    venue_parser = sub.add_parser("venue", help="Search papers from a conference/year")
    venue_parser.add_argument("conference", help="Conference acronym, e.g. ICLR, NeurIPS, ACL")
    venue_parser.add_argument("year", type=int)
    venue_parser.add_argument("--limit", type=int, default=25)
    venue_parser.add_argument("--source", choices=["all", "openreview", "dblp"], default="all")
    venue_parser.add_argument("--ingest", action="store_true", help="Store returned metadata records in the local index")
    venue_parser.set_defaults(func=cmd_venue)

    ingest_feeds_parser = sub.add_parser("ingest-feeds", help="Ingest papers from supported high-signal feeds")
    ingest_feeds_parser.add_argument("--limit", type=int, default=20)
    ingest_feeds_parser.add_argument("--sources", help="Comma-separated subset: alphaxiv,huggingface")
    ingest_feeds_parser.set_defaults(func=cmd_ingest_feeds)

    extract_refs_parser = sub.add_parser("extract-refs", help="Extract references from a local paper markdown bibliography")
    extract_refs_parser.add_argument("paper_id")
    extract_refs_parser.set_defaults(func=cmd_extract_refs)

    acquire_refs_parser = sub.add_parser("acquire-refs", help="Acquire resolved references from a local paper bibliography")
    acquire_refs_parser.add_argument("paper_id")
    acquire_refs_parser.add_argument("--min-year", type=int)
    acquire_refs_parser.add_argument("--limit", type=int)
    acquire_refs_parser.add_argument("--workers", type=int, default=4)
    acquire_refs_parser.set_defaults(func=cmd_acquire_refs)

    references_parser = sub.add_parser("references", help="Fetch references for one paper")
    references_parser.add_argument("input")
    references_parser.add_argument("--limit", type=int, default=25)
    references_parser.set_defaults(func=cmd_references)

    citations_parser = sub.add_parser("citations", help="Fetch citations for one paper")
    citations_parser.add_argument("input")
    citations_parser.add_argument("--limit", type=int, default=25)
    citations_parser.set_defaults(func=cmd_citations)

    expand_parser = sub.add_parser("expand", help="Fetch references and citations for one paper")
    expand_parser.add_argument("input")
    expand_parser.add_argument("--limit", type=int, default=25)
    expand_parser.set_defaults(func=cmd_expand)

    preview_parser = sub.add_parser("preview-build", help="Build static HTML preview page")
    preview_parser.set_defaults(func=cmd_preview_build)

    pdf_parser = sub.add_parser("pdf-link", help="Show preview PDF link for a paper")
    pdf_parser.add_argument("input")
    pdf_parser.set_defaults(func=cmd_pdf_link)

    # Workspace commands
    from . import workspace_cli as _wc
    _wc.build_workspace_parser(sub)   # "pa workspace <sub>"
    # "pa ws <sub>" = alias for "pa workspace <sub>"
    _ws_sp = sub.add_parser("ws", help="Alias for 'pa workspace <subcommand>'").add_subparsers()
    _wc.build_workspace_parser(_ws_sp, skip_top_level=True)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
