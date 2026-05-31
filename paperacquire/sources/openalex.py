from __future__ import annotations

import urllib.parse

from ..models import GraphNode, SearchResult
from ..normalize import extract_arxiv_id, strip_version
from .arxiv import canonical_abs_url, canonical_pdf_url
from ..http import request_json


OPENALEX_API = "https://api.openalex.org"


def search_papers(query: str, limit: int = 10) -> list[SearchResult]:
    params = urllib.parse.urlencode({"search": query, "per_page": max(1, min(limit, 50))})
    data = request_json(f"{OPENALEX_API}/works?{params}")
    results = data.get("results", []) if isinstance(data, dict) else []
    papers: list[SearchResult] = []
    for work in results:
        paper = _parse_work(work)
        if paper:
            papers.append(paper)
    return papers


def fetch_work(identifier: str) -> GraphNode | None:
    work = _resolve_work(identifier)
    if not work:
        return None
    return _work_to_node(work)


def fetch_references(identifier: str, limit: int = 25) -> list[GraphNode]:
    work = _resolve_work(identifier)
    if not work:
        return []
    references = []
    for ref in (work.get("referenced_works") or [])[:limit]:
        ref_work = request_json(f"{OPENALEX_API}/works/{ref.rsplit('/', 1)[-1]}")
        node = _work_to_node(ref_work)
        if node:
            references.append(node)
    return references


def fetch_citations(identifier: str, limit: int = 25) -> list[GraphNode]:
    work = _resolve_work(identifier)
    if not work:
        return []
    openalex_id = (work.get("id", "") or "").replace("https://openalex.org/", "")
    params = urllib.parse.urlencode({"filter": f"cites:{openalex_id}", "per_page": max(1, min(limit, 50))})
    data = request_json(f"{OPENALEX_API}/works?{params}")
    items = data.get("results", []) if isinstance(data, dict) else []
    citations: list[GraphNode] = []
    for item in items:
        node = _work_to_node(item)
        if node:
            citations.append(node)
    return citations


def _parse_work(work: dict) -> SearchResult | None:
    title = (work or {}).get("title", "")
    if not title:
        return None

    authors: list[str] = []
    for authorship in work.get("authorships", []):
        author = authorship.get("author", {}) or {}
        name = author.get("display_name", "")
        if name:
            authors.append(name)

    primary_location = work.get("primary_location", {}) or {}
    source = primary_location.get("source", {}) or {}
    venue = source.get("display_name", "")
    landing_page_url = primary_location.get("landing_page_url", "") or ""

    openalex_id = (work.get("id", "") or "").replace("https://openalex.org/", "")
    doi = work.get("doi", "") or ""
    if doi.startswith("https://doi.org/"):
        doi = doi[16:]

    arxiv_id = _extract_arxiv_id_from_work(work)
    paper_id = strip_version(arxiv_id) if arxiv_id else ""

    pdf_url = ((work.get("open_access", {}) or {}).get("oa_url", "") or "")
    if not pdf_url and paper_id:
        pdf_url = canonical_pdf_url(paper_id)

    canonical_url = landing_page_url or (canonical_abs_url(paper_id) if paper_id else work.get("id", "") or "")

    abstract = _reconstruct_abstract(work.get("abstract_inverted_index", {}) or {})

    return SearchResult(
        title=title,
        source="openalex",
        sources=["openalex"],
        paper_id=paper_id,
        identifiers={
            "arxiv_id": paper_id,
            "doi": doi,
            "openalex_id": openalex_id,
        },
        authors=authors,
        abstract=abstract[:1000],
        year=work.get("publication_year"),
        venue=venue,
        citation_count=work.get("cited_by_count"),
        canonical_url=canonical_url,
        landing_page_url=landing_page_url or canonical_url,
        pdf_url=pdf_url,
    )


def _extract_arxiv_id_from_work(work: dict) -> str:
    ids = work.get("ids", {}) or {}
    for key, value in ids.items():
        if not isinstance(value, str):
            continue
        if key.lower() == "arxiv":
            arxiv_id = extract_arxiv_id(value)
            if arxiv_id:
                return arxiv_id
    for loc in work.get("locations", []):
        for key in ("landing_page_url", "pdf_url"):
            value = loc.get(key, "") or ""
            if "arxiv.org" not in value:
                continue
            arxiv_id = extract_arxiv_id(value)
            if arxiv_id:
                return arxiv_id
    return ""


def _resolve_work(identifier: str) -> dict | None:
    if identifier.startswith("W"):
        return request_json(f"{OPENALEX_API}/works/{identifier}")
    if identifier.startswith("https://openalex.org/W"):
        return request_json(f"{OPENALEX_API}/works/{identifier.rsplit('/', 1)[-1]}")
    if identifier.startswith("10."):
        data = request_json(f"{OPENALEX_API}/works?{urllib.parse.urlencode({'filter': f'doi:{identifier}', 'per_page': 1})}")
        return (data.get("results") or [None])[0] if isinstance(data, dict) else None
    arxiv_id = strip_version(extract_arxiv_id(identifier) or "")
    if arxiv_id:
        data = request_json(f"{OPENALEX_API}/works?{urllib.parse.urlencode({'search': arxiv_id, 'per_page': 5})}")
        results = data.get("results", []) if isinstance(data, dict) else []
        for item in results:
            if strip_version(_extract_arxiv_id_from_work(item) or "") == arxiv_id:
                return item
        return None
    data = request_json(f"{OPENALEX_API}/works?{urllib.parse.urlencode({'search': identifier, 'per_page': 1})}")
    return (data.get("results") or [None])[0] if isinstance(data, dict) else None



def _work_to_node(work: dict) -> GraphNode | None:
    paper = _parse_work(work)
    if not paper:
        return None
    identifiers = dict(paper.identifiers)
    return GraphNode(
        key=_node_key(paper.paper_id, identifiers),
        title=paper.title,
        paper_id=paper.paper_id,
        identifiers=identifiers,
        authors=paper.authors,
        year=paper.year,
        venue=paper.venue,
        citation_count=paper.citation_count,
        canonical_url=paper.canonical_url,
        pdf_url=paper.pdf_url,
        sources=["openalex"],
    )



def _node_key(paper_id: str, identifiers: dict[str, str]) -> str:
    return paper_id or identifiers.get("doi") or identifiers.get("openalex_id") or ""



def _reconstruct_abstract(abstract_inv: dict) -> str:
    if not abstract_inv:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in abstract_inv.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(word for _, word in word_positions)
