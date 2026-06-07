"""OpenReview source adapter for paper-acquire.

OpenReview (https://openreview.net) hosts the official paper pages for ICLR and
 NeurIPS.  It is the authoritative source for:
 - Accept/reject decisions and poster/spotlight distinctions
 - Discussion scores and reviewer ratings
 - Camera-ready official PDFs (when public)

API split (handled transparently here):
 - v2 API (2024-): https://api2.openreview.net/notes
   Used for ICLR 2024+, and newer NeurIPS years.
 - v1 API  (older): https://api.openreview.net/notes
   Used for ICLR 2023 and earlier, and older NeurIPS/AAAI/ACL conferences.

The adapter detects which API version to use automatically from the
conference and year, and also provides a best-effort fetch by paper title
or submission number.
"""

from __future__ import annotations

import re
import urllib.parse

from ..http import NotFoundError, jget, request_json
from ..models import SearchResult
from ..normalize import extract_arxiv_id, strip_version

V2_BASE = "https://api2.openreview.net"
V1_BASE = "https://api.openreview.net"

# Map conference names to their OpenReview invitation prefixes and the API version.
CONFERENCE_CONFIG = {
    "ICLR": {"v2_invitation": "ICLR.cc", "v1_invitation": "ICLR.cc", "api": 2},
    "NeurIPS": {"v2_invitation": "NeurIPS.cc", "v1_invitation": "NeurIPS.cc", "api": 2},
    "AAAI": {"v2_invitation": "AAAI.cc", "v1_invitation": "AAAI.cc", "api": 2},
    "ACL": {"v2_invitation": "ACL", "v1_invitation": "ACL.findings", "api": 1},
    "EMNLP": {"v2_invitation": "EMNLP", "v1_invitation": "EMNLP", "api": 1},
}


def _normalize_conference_name(conference: str) -> str:
    raw = conference.strip()
    for known in CONFERENCE_CONFIG:
        if raw.lower() == known.lower():
            return known
    return raw.upper()


def _conference_api_version(conference: str, year: int | None = None) -> int:
    """Decide whether to use OpenReview v1 or v2 API.

    v2 (api2.openreview.net) is the modern API.  It is used for ICLR and
    NeurIPS from 2024 onwards.  Older conferences or 2023 and earlier use
    the legacy v1 API.
    """
    conf = _normalize_conference_name(conference)
    api_version = CONFERENCE_CONFIG.get(conf, {}).get("api", 2)
    if api_version == 1:
        return 1
    if year and year <= 2023:
        return 1
    return 2


def _build_invitation(conference: str, year: int | None, paper_number: str | None) -> str:
    """Build the OpenReview invitation string for a venue.

    For search by venue, the invitation format is usually:
      <venue>.cc/<year>/Conference/-/Submission

    For fetch by paper number, the invitation is embedded in the note ID and
    the full invitation name of the note is returned in the response.
    """
    conf = _normalize_conference_name(conference)
    if conf not in CONFERENCE_CONFIG:
        return ""
    suffix = CONFERENCE_CONFIG[conf].get("v2_invitation", "ICLR.cc")
    year_str = str(year) if year else ""
    if paper_number:
        # When we have a note ID/number we don't need the invitation prefix;
        # the note itself knows its invitation.
        return ""
    return f"{suffix}/{year_str}/Conference/-/Submission" if year_str else suffix


# ---------------------------------------------------------------------------
# Search by venue (most useful for "give me all papers from ICLR 2024")
# ---------------------------------------------------------------------------


def search_papers_by_venue(conference: str, year: int, limit: int = 25) -> list[SearchResult]:
    """Fetch all papers for a specific OpenReview venue (e.g. ICLR 2024).

    This is the primary method for systematically acquiring conference papers.
    """
    api_version = _conference_api_version(conference, year)
    base = V2_BASE if api_version == 2 else V1_BASE
    primary_invitation = _build_invitation(conference, year, None)
    if not primary_invitation:
        return []

    all_notes: list[dict] = []
    cursor = ""
    invitation_candidates = [
        primary_invitation,
        primary_invitation.replace("/-/Submission", "/-/Blind_Submission"),
        primary_invitation.replace("/-/Submission", ""),
    ]

    for invitation in invitation_candidates:
        cursor = ""
        while len(all_notes) < limit:
            params = {
                "invitation": invitation,
                "limit": min(limit, 50),
                "details": "all",
            }
            if cursor:
                params["cursor"] = cursor
            url = f"{base}/notes?{urllib.parse.urlencode(params)}"
            try:
                data = request_json(url)
            except NotFoundError:
                break

            notes = jget(data, "notes", [])
            if not notes:
                break
            all_notes.extend(notes)

            # OpenReview paginates with a 'cursor' field
            cursor = data.get("cursor", "") or ""
            if not cursor:
                break

            if len(all_notes) >= limit:
                break
        if all_notes:
            break

    results: list[SearchResult] = []
    for note in all_notes[:limit]:
        paper = _note_to_result(note)
        if paper:
            results.append(paper)
    return results


# ---------------------------------------------------------------------------
# Search by title / content query
# ---------------------------------------------------------------------------


def search_papers(query: str, limit: int = 10) -> list[SearchResult]:
    """Search OpenReview by title or content.

    This searches all venues simultaneously using OpenReview's full-text index.
    Use :func:`search_papers_by_venue` for systematic per-venue acquisition.
    """
    params = urllib.parse.urlencode({
        "query": query,
        "limit": min(limit, 50),
        "details": "all",
    })
    # v2 API has a /notes endpoint that supports query=
    try:
        data = request_json(f"{V2_BASE}/notes?{params}")
    except NotFoundError:
        return []
    notes = jget(data, "notes", [])
    results: list[SearchResult] = []
    for note in notes[:limit]:
        paper = _note_to_result(note)
        if paper:
            results.append(paper)
    return results


# ---------------------------------------------------------------------------
# Fetch by paper ID / number
# ---------------------------------------------------------------------------


def fetch_paper(identifier: str) -> SearchResult | None:
    """Fetch a single OpenReview paper by its note ID or number.

    OpenReview note IDs are opaque strings (e.g. "FnKFwg...").
    Paper numbers are numeric (e.g. "12345").
    The API accepts both as the ``note`` parameter.
    """
    params = urllib.parse.urlencode({"id": identifier, "details": "all"})
    # Try v2 first (modern), fall back to v1
    for base in [V2_BASE, V1_BASE]:
        try:
            data = request_json(f"{base}/note?{params}")
        except NotFoundError:
            continue
        note = data.get("note") or data
        if note:
            return _note_to_result(note)
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _note_to_result(note: dict) -> SearchResult | None:
    """Convert an OpenReview note dict into a SearchResult."""
    content = note.get("content", {}) or {}

    # Title
    title = _str_field(content, "title") or note.get("title", "") or ""
    if not title:
        return None

    # Authors
    authors_raw = _field_value(content, "authors")
    if isinstance(authors_raw, dict):
        authors = [str(v.get("value", "") or "") for v in authors_raw.values() if isinstance(v, dict)]
    elif isinstance(authors_raw, list):
        authors = [str(v.get("value", "") or str(v)) if isinstance(v, dict) else str(v) for v in authors_raw]
    elif isinstance(authors_raw, str):
        authors = [authors_raw]
    else:
        authors = []

    # Abstract
    abstract = _str_field(content, "abstract") or ""

    # Year — prefer the venue year, fall back to cdate year
    year_raw = _field_value(content, "year")
    try:
        year = int(year_raw) if year_raw else None
    except (ValueError, TypeError):
        year = None

    # Venue
    venue = _str_field(content, "venue") or ""
    if year is None:
        year = _extract_year(f"{venue} {note.get('domain', '')}")

    # Decision / rating
    decision = _str_field(content, "decision") or ""
    tcscore = content.get("tcwells score", {})
    if isinstance(tcscore, dict):
        tcscore = tcscore.get("value", "") or ""

    # OpenReview note ID (opaque string)
    or_id = note.get("id", "") or ""

    # Canonical URL
    or_forum = note.get("forum", "") or ""
    canonical_url = f"https://openreview.net/forum?id={or_forum}" if or_forum else ""

    # PDF — OpenReview serves PDF as a separate content field or by forum hash
    pdf_url = ""
    pdf_field = content.get("pdf")
    if isinstance(pdf_field, dict):
        pdf_url = pdf_field.get("value", "") or ""
    elif pdf_field and str(pdf_field).startswith("http"):
        pdf_url = str(pdf_field)
    if pdf_url.startswith("/"):
        pdf_url = f"https://openreview.net{pdf_url}"
    if not pdf_url and or_forum:
        pdf_url = f"https://openreview.net/pdf?id={or_forum}"

    # arXiv ID (if the authors submitted to both)
    arxiv_id = ""
    for field in ("arXiv ID", "arxiv_id", "paper_id"):
        raw = _str_field(content, field)
        if raw:
            arxiv_id = strip_version(extract_arxiv_id(raw) or "")
            if arxiv_id:
                break

    # Number (numeric, stable per venue/year)
    number = str(note.get("number", "") or "").strip()
    if not number:
        number = str(note.get("id", "") or "")[:8]  # fallback to short ID

    return SearchResult(
        title=title,
        source="openreview",
        sources=["openreview"],
        paper_id=arxiv_id,
        identifiers={
            "openreview_id": or_id,
            "openreview_number": number,
            "arxiv_id": arxiv_id,
        },
        authors=authors,
        abstract=abstract[:2000] if abstract else "",
        year=year,
        venue=venue,
        citation_count=None,
        canonical_url=canonical_url,
        landing_page_url=canonical_url,
        pdf_url=pdf_url,
    )


def _str_field(content: dict, key: str) -> str:
    """Extract a string field from OpenReview's nested content dict.

    OpenReview content fields are typed: a plain string comes back as-is,
    but a field with metadata (author,數值) comes back as ``{"value": "..."}``.
    """
    val = _field_value(content, key)
    if isinstance(val, list):
        return ", ".join(str(item) for item in val if item)
    return str(val) if val else ""


def _field_value(content: dict, key: str):
    val = content.get(key, "")
    if isinstance(val, dict):
        return val.get("value", "") or ""
    return val


def _extract_year(text: str) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", text or "")
    if not match:
        return None
    return int(match.group(0))
