from __future__ import annotations

import re
import urllib.parse

from ..http import request_json
from ..models import SearchResult


CROSSREF_API = "https://api.crossref.org/works"


def search_papers(query: str, limit: int = 10) -> list[SearchResult]:
    params = urllib.parse.urlencode({"query": query, "rows": max(1, min(limit, 50))})
    data = request_json(f"{CROSSREF_API}?{params}")
    items = ((data.get("message", {}) or {}).get("items", [])) if isinstance(data, dict) else []
    results: list[SearchResult] = []
    for item in items:
        paper = _item_to_result(item)
        if paper:
            results.append(paper)
    return results


def _item_to_result(item: dict) -> SearchResult | None:
    title = item.get("title", [""])[0] if item.get("title") else ""
    if not title:
        return None

    authors = []
    for author in item.get("author", []):
        given = author.get("given", "")
        family = author.get("family", "")
        name = " ".join(part for part in [given, family] if part).strip()
        if name:
            authors.append(name)

    year = _extract_year(item)
    venue = item.get("container-title", [""])[0] if item.get("container-title") else ""
    doi = item.get("DOI", "") or ""
    abstract = re.sub(r"<[^>]+>", "", item.get("abstract", "") or "")
    landing_page_url = item.get("URL", "") or (f"https://doi.org/{doi}" if doi else "")

    return SearchResult(
        title=title,
        source="crossref",
        sources=["crossref"],
        identifiers={"doi": doi},
        authors=authors,
        abstract=abstract,
        year=year,
        venue=venue,
        citation_count=item.get("is-referenced-by-count"),
        canonical_url=landing_page_url,
        landing_page_url=landing_page_url,
    )


def _extract_year(item: dict) -> int | None:
    for field in ["published-print", "published-online", "created"]:
        if item.get(field):
            parts = item[field].get("date-parts", [[]])
            if parts and parts[0]:
                return int(parts[0][0])
    return None
