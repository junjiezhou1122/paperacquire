from dataclasses import dataclass
from datetime import date
import urllib.parse

from ..http import NotFoundError, request_json, request_text
from ..models import SearchResult
from ..normalize import extract_arxiv_id, strip_version
from .arxiv import canonical_abs_url, canonical_pdf_url


BASE_URL = "https://huggingface.co"


@dataclass
class HuggingFaceFetchResult:
    title: str = ""
    authors: list[str] | None = None
    published: str = ""
    markdown: str | None = None
    canonical_url: str = ""
    ai_summary: str = ""
    ai_keywords: list[str] | None = None
    github_repo: str = ""
    github_stars: int | None = None
    organization: str = ""
    upvotes: int | None = None
    comments: int | None = None


def fetch_markdown(paper_id_input: str) -> str | None:
    try:
        return request_text(f"{BASE_URL}/papers/{paper_id_input}.md")
    except NotFoundError:
        return None


def fetch_metadata(paper_id_input: str) -> dict:
    try:
        return request_json(f"{BASE_URL}/api/papers/{paper_id_input}")
    except Exception:
        return {}


def fetch_paper(paper_id_input: str) -> HuggingFaceFetchResult:
    metadata = fetch_metadata(paper_id_input)
    markdown = fetch_markdown(paper_id_input)
    paper = metadata.get("paper", {}) or {}
    authors = [author.get("name", "") for author in metadata.get("authors", []) if author.get("name")]
    published = metadata.get("publishedAt", "") or metadata.get("published", "") or paper.get("publishedAt", "") or ""
    title = metadata.get("title", "") or paper.get("title", "")
    ai_summary = metadata.get("summary", "") or paper.get("summary", "") or metadata.get("ai_summary", "") or ""
    ai_keywords = [keyword.strip() for keyword in (metadata.get("keywords", []) or metadata.get("ai_keywords", []) or []) if isinstance(keyword, str) and keyword.strip()]
    github_repo = metadata.get("github", "") or metadata.get("githubRepo", "") or metadata.get("github_repo", "") or ""
    github_stars = _coerce_int(metadata.get("githubStars") or metadata.get("github_stars"))
    organization = _coerce_organization_name(metadata.get("organization") or metadata.get("publisher"))
    upvotes = _coerce_int(metadata.get("upvotes") or metadata.get("likes"))
    comments = _coerce_int(metadata.get("comments") or metadata.get("commentCount"))
    return HuggingFaceFetchResult(
        title=title,
        authors=authors,
        published=published,
        markdown=markdown,
        canonical_url=f"{BASE_URL}/papers/{paper_id_input}",
        ai_summary=ai_summary,
        ai_keywords=ai_keywords,
        github_repo=github_repo,
        github_stars=github_stars,
        organization=organization,
        upvotes=upvotes,
        comments=comments,
    )


def search_papers(query: str, limit: int = 10) -> list[SearchResult]:
    params = urllib.parse.urlencode({"q": query, "limit": max(1, min(limit, 120))})
    try:
        data = request_json(f"{BASE_URL}/api/papers/search?{params}")
    except Exception:
        return []
    items = data if isinstance(data, list) else data.get("papers", []) if isinstance(data, dict) else []
    return _items_to_results(items)


def fetch_daily_papers(limit: int = 20, *, day: str | None = None, sort: str = "publishedAt") -> list[SearchResult]:
    params = {
        "p": 0,
        "limit": max(1, min(limit, 100)),
        "date": day or date.today().isoformat(),
        "sort": sort,
    }
    try:
        data = request_json(f"{BASE_URL}/api/daily_papers?{urllib.parse.urlencode(params)}")
    except Exception:
        return []
    items = data if isinstance(data, list) else data.get("papers", []) if isinstance(data, dict) else []
    return _items_to_results(items)


def _items_to_results(items: list[dict]) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in items:
        paper = _item_to_result(item)
        if paper:
            results.append(paper)
    return results


def _coerce_organization_name(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        name = value.get("fullname") or value.get("name") or ""
        return name.strip() if isinstance(name, str) else ""
    return ""


def _coerce_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if stripped.isdigit():
            return int(stripped)
    return None


def _item_to_result(item: dict) -> SearchResult | None:
    paper = item.get("paper", {}) or {}
    raw_paper_id = paper.get("id", "") or item.get("id", "") or item.get("paperId", "") or item.get("arxivId", "") or ""
    paper_id = strip_version(extract_arxiv_id(raw_paper_id) or raw_paper_id)
    title = item.get("title", "") or paper.get("title", "")
    if not title or not paper_id:
        return None
    authors = [author.get("name", "") for author in (paper.get("authors", []) or item.get("authors", [])) if author.get("name")]
    summary = item.get("summary", "") or paper.get("summary", "") or item.get("abstract", "") or ""
    published = item.get("publishedAt", "") or paper.get("publishedAt", "") or item.get("published", "") or ""
    year = None
    if published and len(published) >= 4 and published[:4].isdigit():
        year = int(published[:4])
    canonical_url = f"{BASE_URL}/papers/{paper_id}" if paper_id else ""
    return SearchResult(
        title=title,
        source="huggingface",
        sources=["huggingface"],
        paper_id=paper_id,
        identifiers={"arxiv_id": paper_id},
        authors=authors,
        abstract=summary,
        year=year,
        venue="Hugging Face Papers",
        canonical_url=canonical_url or canonical_abs_url(paper_id),
        landing_page_url=canonical_url or canonical_abs_url(paper_id),
        pdf_url=canonical_pdf_url(paper_id),
    )
