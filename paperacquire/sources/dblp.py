"""DBLP source adapter for paperacquire.

DBLP (https://dblp.org) is the authoritative bibliography for CS conferences.
It is the only major source that reliably tags papers with their venue
(NeurIPS/ICML/ACL/AAAI/EMNLP etc.) in a clean, stable field —
unlike crossref/openalex which often leave venue blank or unparseable.

API docs: https://dblp.org/faq/How+to+use+the+DBLP+API.html
Search endpoint: https://dblp.org/search/publ/api?q=<query>&format=json&h=<limit>
"""

from __future__ import annotations

import urllib.parse

from ..http import NotFoundError, jget, request_json
from ..models import SearchResult
from ..normalize import extract_doi, strip_version

DBLP_BASE = "https://dblp.org"
DBLP_SEARCH_FALLBACKS = [
    "https://dblp.org/search/publ/api",
    "https://dblp.dagstuhl.de/search/publ/api",
    "https://dblp.uni-trier.de/search/publ/api",
]


def search_papers(query: str, limit: int = 10) -> list[SearchResult]:
    """Search DBLP by title/content query and return matching papers.

    DBLP's ``publ`` endpoint returns published items (journal articles,
    conference papers) with accurate venue and year.  Venue values are
    abbreviated venue strings such as "NeurIPS", "ICML", "ACL", "AAAI".
    """
    params = urllib.parse.urlencode({"q": query, "format": "json", "h": min(limit, 200)})
    data = _request_search_json(params)
    if not data:
        return []

    hits = jget(data, "result.hits.hit", [])
    papers: list[SearchResult] = []
    for hit in hits:
        info = (hit.get("info", {}) or {})
        paper = _parse_hit(info)
        if paper:
            papers.append(paper)
    return papers


def search_papers_by_venue(conference: str, year: int, limit: int = 25) -> list[SearchResult]:
    """Search DBLP for papers from a venue/year and keep exact venue/year hits."""
    venue = conference.strip()
    if not venue:
        return []

    # DBLP's public search endpoint is text-oriented, so over-fetch a compact
    # query and then require the structured venue/year fields to match.
    query_limit = max(limit * 5, 50)
    candidates = search_papers(f"{venue} {year}", limit=min(query_limit, 200))
    wanted_venue = _normalize_venue(venue)
    results: list[SearchResult] = []
    seen: set[str] = set()
    for paper in candidates:
        if paper.year != year:
            continue
        if _normalize_venue(paper.venue) != wanted_venue:
            continue
        key = paper.identifiers.get("doi") or paper.canonical_url or paper.title
        if key in seen:
            continue
        seen.add(key)
        results.append(paper)
        if len(results) >= limit:
            break
    return results


def fetch_paper(identifier: str) -> SearchResult | None:
    """Fetch a single DBLP record by DOI or exact title.

    DBLP does not have a direct "get by DOI" endpoint, so we search
    by the DOI (as a query) and take the first exact-match result.
    """
    doi = extract_doi(identifier)
    if doi:
        return _fetch_by_doi(doi)
    return _fetch_by_title(identifier)


def _fetch_by_doi(doi: str) -> SearchResult | None:
    params = urllib.parse.urlencode({"q": f"doi:{doi}", "format": "json", "h": 1})
    data = _request_search_json(params)
    if not data:
        return None
    hits = jget(data, "result.hits.hit", [])
    for hit in hits:
        info = (hit.get("info", {}) or {})
        if _doi_matches(info, doi):
            return _parse_hit(info)
    return None


def _fetch_by_title(title: str) -> SearchResult | None:
    params = urllib.parse.urlencode({"q": title, "format": "json", "h": 1})
    data = _request_search_json(params)
    if not data:
        return None
    hits = jget(data, "result.hits.hit", [])
    if not hits:
        return None
    return _parse_hit(hits[0].get("info", {}) or {})


def _parse_hit(info: dict) -> SearchResult | None:
    title = (info.get("title", "") or "").strip()
    if not title:
        return None

    authors_raw = jget(info, "authors.author", [])
    if isinstance(authors_raw, dict):
        authors_raw = [authors_raw]
    authors = [a.get("text", "") or "" for a in authors_raw if a.get("text", "")]

    year_val = info.get("year", "")
    try:
        year = int(year_val) if year_val else None
    except (ValueError, TypeError):
        year = None

    venue = (info.get("venue", "") or "").strip()
    pages = (info.get("pages", "") or "").strip()
    doi = (info.get("doi", "") or "").strip()
    url = (info.get("url", "") or "").strip()
    volume = (info.get("volume", "") or "").strip()
    number = (info.get("number", "") or "").strip()

    # Build a usable paper_id: prefer DOI-based, fall back to empty
    paper_id = strip_version(doi) if doi else ""

    # DBLP's abstract / abstract Inverted Index lives under
    # "abstract" — it is plain text when present.
    abstract = (info.get("abstract", "") or "").strip()

    return SearchResult(
        title=title,
        source="dblp",
        sources=["dblp"],
        paper_id=paper_id,
        identifiers={
            "doi": doi,
            "dblp_key": info.get("key", "") or "",
        },
        authors=authors,
        abstract=abstract[:2000] if abstract else "",
        year=year,
        venue=venue,
        citation_count=None,  # DBLP does not surface citation counts in search
        canonical_url=url or (f"{DBLP_BASE}/rec/{info.get('key', '')}" if info.get("key") else ""),
        landing_page_url=url,
        pdf_url="",
    )


def _doi_matches(info: dict, doi: str) -> bool:
    info_doi = (info.get("doi", "") or "").strip()
    return info_doi == doi or info_doi == f"10.1007{doi[7:]}" if doi.startswith("10.1007/") else False


def _normalize_venue(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _request_search_json(params: str) -> dict | None:
    for endpoint in DBLP_SEARCH_FALLBACKS:
        try:
            return request_json(f"{endpoint}?{params}")
        except NotFoundError:
            return None
        except Exception:
            continue
    return None
