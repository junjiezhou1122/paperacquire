import json
import os
import urllib.parse
from dataclasses import dataclass

from ..http import NotFoundError, request_json, request_text
from ..models import SearchResult
from ..normalize import extract_arxiv_id, strip_version


API_BASE_URL = "https://api.alphaxiv.org"
WEB_BASE_URL = "https://www.alphaxiv.org"


@dataclass
class AlphaXivFetchResult:
    title: str = ""
    authors: list[str] | None = None
    published: str = ""
    overview_markdown: str | None = None
    abs_markdown: str | None = None
    canonical_url: str = ""
    topics: list[str] | None = None


def _read_zshrc(key: str) -> str | None:
    zshrc = os.path.expanduser("~/.zshrc")
    if not os.path.exists(zshrc):
        return None
    with open(zshrc, encoding="utf-8") as handle:
        for line in handle:
            if key in line and "=" in line and not line.strip().startswith("#"):
                value = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    return None


def _resolve_token() -> str | None:
    return os.environ.get("ALPHAXIV_TOKEN") or _read_zshrc("ALPHAXIV_TOKEN")


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    token = _resolve_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra:
        headers.update(extra)
    return headers


def _get_json(path: str) -> dict | list | None:
    return request_json(API_BASE_URL + path, headers=_headers())


def resolve_ids(id_or_arxiv: str) -> tuple[str, str]:
    data = _get_json(f"/papers/v3/{id_or_arxiv}")
    if not data:
        return id_or_arxiv, id_or_arxiv
    paper = data.get("data", data) if isinstance(data, dict) else data
    return paper.get("versionId", id_or_arxiv), paper.get("groupId", id_or_arxiv)


def fetch_overview_markdown(paper_id_input: str) -> str | None:
    try:
        return request_text(f"{WEB_BASE_URL}/overview/{paper_id_input}.md")
    except NotFoundError:
        return None


def fetch_abs_markdown(paper_id_input: str) -> str | None:
    try:
        return request_text(f"{WEB_BASE_URL}/abs/{paper_id_input}.md")
    except NotFoundError:
        return None


def fetch_metadata(arxiv_id: str) -> dict:
    try:
        data = _get_json(f"/v2/papers/{arxiv_id}/metadata")
    except Exception:
        return {}
    if not data:
        return {}
    return data.get("data", data) if isinstance(data, dict) else {}


def fetch_paper(arxiv_id: str) -> AlphaXivFetchResult:
    metadata = fetch_metadata(arxiv_id)
    paper_version = metadata.get("paper_version", {})
    paper_group = metadata.get("paper_group", {})
    authors_data = metadata.get("authors", [])
    authors = [author.get("full_name", "") for author in authors_data if author.get("full_name")]
    overview_markdown = fetch_overview_markdown(arxiv_id)
    abs_markdown = fetch_abs_markdown(arxiv_id)

    return AlphaXivFetchResult(
        title=paper_version.get("title", ""),
        authors=authors,
        published=paper_version.get("publication_date", ""),
        overview_markdown=overview_markdown,
        abs_markdown=abs_markdown,
        canonical_url=f"https://arxiv.org/abs/{arxiv_id}",
        topics=paper_group.get("topics", []),
    )


def search_papers(query: str, limit: int = 10) -> list[SearchResult]:
    try:
        encoded_query = urllib.parse.quote_plus(query)
        data = _get_json(f"/search/v2/paper/fast?q={encoded_query}&includePrivate=false")
    except Exception:
        return []
    items = data if isinstance(data, list) else data.get("papers", []) if isinstance(data, dict) else []
    return _items_to_results(items[:limit])


def fetch_feed_papers(limit: int = 20, *, sort: str = "trending", interval: str = "7d") -> list[SearchResult]:
    try:
        data = _get_json(f"/papers/v3/feed?pageNum=1&pageSize={max(1, limit)}&sort={sort}&interval={interval}")
    except Exception:
        return []
    items = data.get("papers", data) if isinstance(data, dict) else data if isinstance(data, list) else []
    return _items_to_results(items[:limit])


def fetch_top_papers(limit: int = 20) -> list[SearchResult]:
    try:
        data = _get_json(f"/retrieve/v1/top-papers?limit={max(1, limit)}&skip=0")
    except Exception:
        return []
    items = data if isinstance(data, list) else (data.get("data") or data.get("papers") or []) if isinstance(data, dict) else []
    return _items_to_results(items[:limit])


def _items_to_results(items: list[dict]) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in items:
        result = _item_to_result(item)
        if result is not None:
            results.append(result)
    return results


def _item_to_result(item: dict) -> SearchResult | None:
    raw_id = item.get("paperId", "") or item.get("arxivId", "") or item.get("link", "") or item.get("id", "") or ""
    paper_id = strip_version(extract_arxiv_id(raw_id) or raw_id)
    if not paper_id:
        return None
    title = item.get("title", "") or item.get("name", "") or paper_id
    return SearchResult(
        title=title,
        source="alphaxiv",
        sources=["alphaxiv"],
        paper_id=paper_id,
        identifiers={"arxiv_id": paper_id},
        canonical_url=f"https://alphaxiv.org/abs/{paper_id}",
        landing_page_url=f"https://alphaxiv.org/abs/{paper_id}",
        pdf_url=f"https://arxiv.org/pdf/{paper_id}.pdf",
    )
