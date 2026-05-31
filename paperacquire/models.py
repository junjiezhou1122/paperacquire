from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


EMPTY_VALUES = (None, "", [], {})
PROTECTED_STATUS_VALUES = {"present", "available", "fetched"}
WEAK_STATUS_VALUES = {"missing", "pending", "not_fetched", ""}


@dataclass
class PaperRecord:
    paper_id: str
    title: str = ""
    source: str = ""
    sources: list[str] = field(default_factory=list)
    source_input: str = ""
    canonical_url: str = ""
    overview_path: str | None = None
    abs_path: str | None = None
    authors: list[str] = field(default_factory=list)
    published: str = ""
    acquired_at: str = ""
    updated_at: str = ""
    status: dict[str, str] = field(default_factory=lambda: {"overview": "missing", "abs": "missing"})
    identifiers: dict[str, str] = field(default_factory=dict)
    venue: str = ""
    year: int | None = None
    citation_count: int | None = None
    pdf_url: str = ""
    landing_page_url: str = ""
    graph_status: dict[str, str] = field(default_factory=lambda: {"references_fetched": "missing", "citations_fetched": "missing"})
    source_topics: list[str] = field(default_factory=list)
    ai_summary: str = ""
    ai_keywords: list[str] = field(default_factory=list)
    github_repo: str = ""
    github_stars: int | None = None
    organization: str = ""
    upvotes: int | None = None
    comments: int | None = None
    tags: list[str] = field(default_factory=list)
    collection: str = ""

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "source": self.source,
            "sources": self.sources,
            "source_input": self.source_input,
            "canonical_url": self.canonical_url,
            "overview_path": self.overview_path,
            "abs_path": self.abs_path,
            "authors": self.authors,
            "published": self.published,
            "acquired_at": self.acquired_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "identifiers": self.identifiers,
            "venue": self.venue,
            "year": self.year,
            "citation_count": self.citation_count,
            "pdf_url": self.pdf_url,
            "landing_page_url": self.landing_page_url,
            "graph_status": self.graph_status,
            "source_topics": self.source_topics,
            "ai_summary": self.ai_summary,
            "ai_keywords": self.ai_keywords,
            "github_repo": self.github_repo,
            "github_stars": self.github_stars,
            "organization": self.organization,
            "upvotes": self.upvotes,
            "comments": self.comments,
            "tags": self.tags,
            "collection": self.collection,
        }


@dataclass
class SearchResult:
    title: str
    source: str
    sources: list[str] = field(default_factory=list)
    paper_id: str = ""
    identifiers: dict[str, str] = field(default_factory=dict)
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    year: int | None = None
    venue: str = ""
    citation_count: int | None = None
    canonical_url: str = ""
    landing_page_url: str = ""
    pdf_url: str = ""
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "source": self.source,
            "sources": _dedupe_strings(self.sources or [self.source]),
            "paper_id": self.paper_id,
            "identifiers": self.identifiers,
            "authors": self.authors,
            "abstract": self.abstract,
            "year": self.year,
            "venue": self.venue,
            "citation_count": self.citation_count,
            "canonical_url": self.canonical_url,
            "landing_page_url": self.landing_page_url,
            "pdf_url": self.pdf_url,
            "score": self.score,
        }


@dataclass
class GraphNode:
    key: str
    title: str = ""
    paper_id: str = ""
    identifiers: dict[str, str] = field(default_factory=dict)
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    citation_count: int | None = None
    canonical_url: str = ""
    pdf_url: str = ""
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "paper_id": self.paper_id,
            "identifiers": self.identifiers,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "citation_count": self.citation_count,
            "canonical_url": self.canonical_url,
            "pdf_url": self.pdf_url,
            "sources": _dedupe_strings(self.sources),
        }


@dataclass
class GraphEdge:
    source_key: str
    target_key: str
    edge_type: str
    providers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_key": self.source_key,
            "target_key": self.target_key,
            "edge_type": self.edge_type,
            "providers": _dedupe_strings(self.providers),
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def merge_record(existing: dict | None, incoming: PaperRecord) -> dict:
    incoming_dict = incoming.to_dict()
    if existing is None:
        if not incoming_dict["acquired_at"]:
            incoming_dict["acquired_at"] = now_iso()
        if not incoming_dict["updated_at"]:
            incoming_dict["updated_at"] = incoming_dict["acquired_at"]
        incoming_dict["sources"] = _dedupe_strings(incoming_dict["sources"])
        incoming_dict["status"] = _merge_state_mapping({}, incoming_dict.get("status", {}))
        incoming_dict["graph_status"] = _merge_state_mapping({}, incoming_dict.get("graph_status", {}))
        incoming_dict["identifiers"] = _merge_mapping({}, incoming_dict.get("identifiers", {}))
        incoming_dict["source_topics"] = _dedupe_strings(incoming_dict.get("source_topics", []))
        return incoming_dict

    merged = dict(existing)
    for key, value in incoming_dict.items():
        if key == "sources":
            merged[key] = _dedupe_strings(existing.get(key, []) + value)
            continue
        if key in {"status", "graph_status"}:
            merged[key] = _merge_state_mapping(existing.get(key, {}), value)
            continue
        if key == "identifiers":
            merged[key] = _merge_mapping(existing.get(key, {}), value)
            continue
        if key == "source_topics":
            merged[key] = _dedupe_strings((existing.get(key, []) or []) + value)
            continue
        if key == "tags":
            merged[key] = _dedupe_strings((existing.get(key, []) or []) + value)
            continue
        if value not in EMPTY_VALUES:
            merged[key] = value

    merged.setdefault("status", _merge_state_mapping({}, incoming_dict.get("status", {})))
    merged.setdefault("graph_status", _merge_state_mapping({}, incoming_dict.get("graph_status", {})))
    merged.setdefault("identifiers", _merge_mapping({}, incoming_dict.get("identifiers", {})))
    merged.setdefault("source_topics", _dedupe_strings(incoming_dict.get("source_topics", [])))
    merged.setdefault("acquired_at", existing.get("acquired_at") or incoming_dict.get("acquired_at") or now_iso())
    merged["updated_at"] = now_iso()
    return merged


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _merge_mapping(existing: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if value not in EMPTY_VALUES:
            merged[key] = value
    return merged


def _merge_state_mapping(existing: dict[str, str] | None, incoming: dict[str, str] | None) -> dict[str, str]:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if value in EMPTY_VALUES:
            continue
        existing_value = merged.get(key, "")
        if existing_value in PROTECTED_STATUS_VALUES and value in WEAK_STATUS_VALUES:
            continue
        merged[key] = value
    return merged

