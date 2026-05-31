from __future__ import annotations

import urllib.parse

from ..http import request_json
from ..models import GraphNode
from ..normalize import extract_arxiv_id, strip_version
from .arxiv import canonical_abs_url, canonical_pdf_url


API_BASE = "https://api.semanticscholar.org/graph/v1"
DEFAULT_FIELDS = "paperId,title,authors,year,venue,citationCount,externalIds,url,openAccessPdf"


def fetch_paper(identifier: str) -> GraphNode | None:
    data = _request_paper(identifier, DEFAULT_FIELDS)
    if not isinstance(data, dict):
        return None
    return _paper_to_node(data, source="semantic_scholar")


def fetch_references(identifier: str, limit: int = 25) -> list[GraphNode]:
    fields = f"references.{DEFAULT_FIELDS}"
    data = _request_paper(identifier, fields)
    refs = data.get("references", []) if isinstance(data, dict) else []
    nodes: list[GraphNode] = []
    for item in refs[:limit]:
        paper = item.get("citedPaper", {}) or item.get("paper", {}) or {}
        node = _paper_to_node(paper, source="semantic_scholar")
        if node:
            nodes.append(node)
    return nodes


def fetch_citations(identifier: str, limit: int = 25) -> list[GraphNode]:
    params = urllib.parse.urlencode({"fields": DEFAULT_FIELDS, "limit": max(1, min(limit, 100))})
    data = request_json(f"{API_BASE}/paper/{urllib.parse.quote(identifier, safe='')}/citations?{params}")
    items = data.get("data", []) if isinstance(data, dict) else []
    nodes: list[GraphNode] = []
    for item in items:
        paper = item.get("citingPaper", {}) or item.get("paper", {}) or {}
        node = _paper_to_node(paper, source="semantic_scholar")
        if node:
            nodes.append(node)
    return nodes


def _request_paper(identifier: str, fields: str) -> dict:
    params = urllib.parse.urlencode({"fields": fields})
    return request_json(f"{API_BASE}/paper/{urllib.parse.quote(identifier, safe='')}?{params}")


def _paper_to_node(paper: dict, source: str) -> GraphNode | None:
    title = paper.get("title", "") or ""
    if not title:
        return None
    external_ids = paper.get("externalIds", {}) or {}
    arxiv_raw = external_ids.get("ArXiv", "") or extract_arxiv_id(paper.get("url", "") or "") or ""
    paper_id = strip_version(arxiv_raw) if arxiv_raw else ""
    identifiers = {
        "arxiv_id": paper_id,
        "doi": external_ids.get("DOI", "") or "",
        "semantic_scholar_id": paper.get("paperId", "") or "",
    }
    canonical_url = paper.get("url", "") or (canonical_abs_url(paper_id) if paper_id else "")
    pdf_url = ((paper.get("openAccessPdf", {}) or {}).get("url", "") or "")
    if not pdf_url and paper_id:
        pdf_url = canonical_pdf_url(paper_id)

    return GraphNode(
        key=_node_key(paper_id, identifiers),
        title=title,
        paper_id=paper_id,
        identifiers=identifiers,
        authors=[author.get("name", "") for author in paper.get("authors", []) if author.get("name")],
        year=paper.get("year"),
        venue=paper.get("venue", "") or "",
        citation_count=paper.get("citationCount"),
        canonical_url=canonical_url,
        pdf_url=pdf_url,
        sources=[source],
    )


def _node_key(paper_id: str, identifiers: dict[str, str]) -> str:
    return paper_id or identifiers.get("doi") or identifiers.get("semantic_scholar_id") or identifiers.get("arxiv_id") or ""
