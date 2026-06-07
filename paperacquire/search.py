from __future__ import annotations

import re
from datetime import datetime

from .models import SearchResult
from .normalize import strip_version
from .sources.alphaxiv import search_papers as search_alphaxiv
from .sources.crossref import search_papers as search_crossref
from .sources.dblp import search_papers as search_dblp
from .sources.huggingface import search_papers as search_huggingface
from .sources.openalex import search_papers as search_openalex
from .sources.openreview_adaptive import search_papers as search_openreview


PROVIDERS = {
    "alphaxiv": search_alphaxiv,
    "openalex": search_openalex,
    "crossref": search_crossref,
    "dblp": search_dblp,
    "huggingface": search_huggingface,
    "openreview": search_openreview,
}
TOKEN_RE = re.compile(r"[a-z0-9]+")


def search_papers(query: str, limit: int = 20, sources: list[str] | None = None) -> list[dict]:
    requested_sources = [source for source in (sources or list(PROVIDERS)) if source in PROVIDERS]
    provider_limit = max(5, min(max(limit, 5), 20))

    merged: dict[str, SearchResult] = {}
    for source in requested_sources:
        provider = PROVIDERS[source]
        try:
            provider_results = provider(query, provider_limit)
        except Exception:
            continue
        for result in provider_results:
            key = _dedup_key(result)
            existing = merged.get(key)
            if existing is None:
                merged[key] = result
                continue
            merged[key] = _merge_results(existing, result)

    scored = list(merged.values())
    for result in scored:
        result.score = _score_result(result, query)
    scored.sort(key=lambda item: (item.score, item.citation_count or 0, item.year or 0), reverse=True)
    return [result.to_dict() for result in scored[:limit]]



def _dedup_key(result: SearchResult) -> str:
    arxiv_id = strip_version(result.identifiers.get("arxiv_id", "") or result.paper_id or "")
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    doi = (result.identifiers.get("doi", "") or "").lower()
    if doi:
        return f"doi:{doi}"
    return f"title:{_normalize_title(result.title)}"



def _merge_results(existing: SearchResult, incoming: SearchResult) -> SearchResult:
    for field in ("paper_id", "abstract", "venue", "canonical_url", "landing_page_url", "pdf_url"):
        if not getattr(existing, field) and getattr(incoming, field):
            setattr(existing, field, getattr(incoming, field))

    if not existing.title and incoming.title:
        existing.title = incoming.title
    if not existing.authors and incoming.authors:
        existing.authors = incoming.authors
    if existing.year is None and incoming.year is not None:
        existing.year = incoming.year
    if existing.citation_count is None and incoming.citation_count is not None:
        existing.citation_count = incoming.citation_count

    merged_identifiers = dict(existing.identifiers)
    for key, value in incoming.identifiers.items():
        if value and not merged_identifiers.get(key):
            merged_identifiers[key] = value
    existing.identifiers = merged_identifiers
    existing.sources = sorted(set(existing.sources + incoming.sources + [existing.source, incoming.source]))
    return existing



def _score_result(result: SearchResult, query: str) -> float:
    query_tokens = set(_tokenize(query))
    text_tokens = set(_tokenize(f"{result.title} {result.abstract}"))
    overlap = len(query_tokens & text_tokens)
    relevance = overlap / max(len(query_tokens), 1)

    current_year = datetime.now().year
    freshness = 0.0
    if result.year:
        age = max(0, current_year - result.year)
        freshness = max(0.0, 1.0 - (age / 10.0))

    impact = min(result.citation_count or 0, 200) / 200.0
    source_bonus = max(0, len(set(result.sources)) - 1) * 0.15
    return round((relevance * 2.0) + (freshness * 0.5) + (impact * 0.25) + source_bonus, 4)



def _normalize_title(title: str) -> str:
    return " ".join(_tokenize(title))



def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())
