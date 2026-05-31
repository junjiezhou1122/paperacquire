from __future__ import annotations

import re

from .models import GraphNode
from .normalize import extract_arxiv_id, extract_doi, strip_version
from .paths import abs_path_for
from .reference_llm import parse_reference_block
from .search import search_papers

REFERENCE_HEADER_RE = re.compile(r"^\s*(?:#+\s*)?(?:references|bibliography)\s*$", re.IGNORECASE)
REFERENCE_END_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:[A-Z](?:\.\d+)?\s+)?(?:appendix|supplementary|acknowledg(?:e)?ments?)\b",
    re.IGNORECASE,
)
PAGE_HEADER_RE = re.compile(r"^\s*(?:references|bibliography)\s+\d+\s*$", re.IGNORECASE)
NUMBERED_ENTRY_RE = re.compile(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})\.)\s*(.*)$")
SAME_LINE_YEAR_RE = re.compile(r"^.+?\.\s*((?:19|20)\d{2}[a-z]?)\.\s+")
NEXT_LINE_YEAR_RE = re.compile(r"^\s*((?:19|20)\d{2}[a-d]?)\.\s+")
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})(?:[a-d])?\b")
WORD_RE = re.compile(r"[a-z0-9]+")
VENUE_FRAGMENT_RE = re.compile(
    r"^(?:in\b|proceedings\b|findings\b|arxiv\b|adv\b|advances\b|ieee\b|international\b|european\b|springer\b|technical report\b|conference\b)",
    re.IGNORECASE,
)
YEAR_RANGE_BOUNDARY_CHARS = {"-", "/", "–", "—"}



def load_abs_text(paper_id: str) -> str:
    path = abs_path_for(paper_id)
    if not path.exists():
        raise FileNotFoundError(f"Local abs markdown not found for {paper_id}: {path}")
    return path.read_text(encoding="utf-8")



def load_reference_block(abs_text: str) -> str | None:
    lines = abs_text.splitlines()
    start_idx: int | None = None
    for index, line in enumerate(lines):
        if REFERENCE_HEADER_RE.match(line):
            start_idx = index + 1
            break
    if start_idx is None:
        return None

    block_lines: list[str] = []
    for line in lines[start_idx:]:
        if REFERENCE_END_RE.match(line):
            break
        block_lines.append(line)
    return "\n".join(block_lines).strip() or None



def extract_reference_candidates(abs_text: str, paper_id: str = "") -> list[dict]:
    block = load_reference_block(abs_text)
    if not block:
        return []

    lines = _normalize_reference_lines(block.splitlines())
    if not lines:
        return []

    if _is_numbered_style(lines):
        entries = _split_numbered_entries(lines)
        style = "numbered"
    else:
        style = "author_year"
        llm_candidates = _normalize_llm_candidates(_parse_reference_candidates_with_llm(lines, paper_id=paper_id, style=style), style)
        if llm_candidates:
            return llm_candidates
        entries = _split_author_year_entries(lines)

    rule_candidates = _build_rule_candidates(entries, style)
    if style != "author_year":
        return rule_candidates
    if not _author_year_candidates_look_suspicious(lines, rule_candidates):
        return rule_candidates

    llm_candidates = _normalize_llm_candidates(_parse_reference_candidates_with_llm(lines, paper_id=paper_id, style=style), style)
    if not llm_candidates:
        return rule_candidates
    return _prefer_candidate_set(lines, rule_candidates, llm_candidates)



def extract_reference_candidates_for_paper(paper_id: str) -> list[dict]:
    return extract_reference_candidates(load_abs_text(paper_id), paper_id=paper_id)



def resolve_reference_candidate(candidate: dict, search_limit: int = 8) -> dict | None:
    explicit_arxiv_id = strip_version(candidate.get("arxiv_id", "") or "")
    if explicit_arxiv_id:
        return {
            **candidate,
            "resolved_input": explicit_arxiv_id,
            "resolved_paper_id": explicit_arxiv_id,
            "matched_title": candidate.get("title_guess", "") or explicit_arxiv_id,
            "matched_year": candidate.get("year"),
            "matched_source": "explicit_arxiv_id",
            "match_score": 1.0,
        }

    query = candidate.get("title_guess", "") or candidate.get("raw_text", "")
    if not query:
        return None

    results = search_papers(query, limit=search_limit)
    best_match: dict | None = None
    best_score = 0.0
    candidate_year = candidate.get("year")
    normalized_query = _normalize_title_for_compare(candidate.get("title_guess", "") or query)

    for result in results:
        paper_id = result.get("paper_id", "") or ""
        if not paper_id:
            continue
        result_title = result.get("title", "") or ""
        if not result_title:
            continue
        score = _title_similarity(normalized_query, _normalize_title_for_compare(result_title))
        if score < 0.72:
            continue
        if not _year_compatible(candidate_year, result.get("year"), score):
            continue
        if score > best_score:
            best_match = result
            best_score = score

    if best_match is None:
        return None

    resolved_paper_id = strip_version(best_match.get("paper_id", "") or "")
    if not resolved_paper_id:
        return None

    return {
        **candidate,
        "resolved_input": resolved_paper_id,
        "resolved_paper_id": resolved_paper_id,
        "matched_title": best_match.get("title", "") or candidate.get("title_guess", ""),
        "matched_year": best_match.get("year") or candidate_year,
        "matched_source": best_match.get("source", "search"),
        "match_score": round(best_score, 4),
    }



def resolve_reference_candidates(candidates: list[dict], min_year: int | None = None, limit: int | None = None) -> list[dict]:
    resolved: list[dict] = []
    seen_paper_ids: set[str] = set()
    for candidate in candidates:
        candidate_year = candidate.get("year")
        if min_year is not None and candidate_year is not None and candidate_year < min_year:
            continue
        match = resolve_reference_candidate(candidate)
        if not match:
            continue
        resolved_paper_id = match.get("resolved_paper_id", "") or ""
        if not resolved_paper_id or resolved_paper_id in seen_paper_ids:
            continue
        seen_paper_ids.add(resolved_paper_id)
        resolved.append(match)
        if limit is not None and len(resolved) >= limit:
            break
    return resolved



def resolve_reference_candidates_for_paper(paper_id: str, min_year: int | None = None, limit: int | None = None) -> list[dict]:
    return resolve_reference_candidates(extract_reference_candidates_for_paper(paper_id), min_year=min_year, limit=limit)



def resolved_candidate_to_graph_node(candidate: dict) -> GraphNode:
    paper_id = strip_version(candidate.get("resolved_paper_id", "") or candidate.get("arxiv_id", "") or "")
    identifiers = {"arxiv_id": paper_id} if paper_id else {}
    doi = candidate.get("doi", "") or ""
    if doi:
        identifiers["doi"] = doi

    sources = ["local_markdown"]
    matched_source = candidate.get("matched_source", "") or ""
    if matched_source and matched_source not in {"local_markdown", "search", "explicit_arxiv_id"}:
        sources.append(matched_source)

    return GraphNode(
        key=paper_id,
        title=candidate.get("matched_title", "") or candidate.get("title_guess", "") or paper_id,
        paper_id=paper_id,
        identifiers=identifiers,
        year=candidate.get("matched_year") or candidate.get("year"),
        canonical_url=f"https://arxiv.org/abs/{paper_id}" if paper_id else "",
        pdf_url=f"https://arxiv.org/pdf/{paper_id}.pdf" if paper_id else "",
        sources=sources,
    )



def _normalize_reference_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line.strip())
        if not line or _is_noise_line(line):
            continue
        if merged and merged[-1].endswith("-"):
            merged[-1] = merged[-1][:-1] + line.lstrip()
            continue
        merged.append(line)
    return merged



def _is_noise_line(line: str) -> bool:
    if re.fullmatch(r"\d+(?:/\d+)?", line):
        return True
    if PAGE_HEADER_RE.match(line):
        return True
    return False



def _is_numbered_style(lines: list[str]) -> bool:
    numbered = sum(1 for line in lines[:20] if NUMBERED_ENTRY_RE.match(line))
    return numbered >= 3



def _split_numbered_entries(lines: list[str]) -> list[list[str]]:
    entries: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if NUMBERED_ENTRY_RE.match(line):
            if current:
                entries.append(current)
            current = [line]
            continue
        if current:
            current.append(line)
    if current:
        entries.append(current)
    return entries



def _split_author_year_entries(lines: list[str]) -> list[list[str]]:
    entries: list[list[str]] = []
    index = 0
    while index < len(lines):
        start_entry, consumed = _consume_author_year_start(lines, index)
        if start_entry is None:
            if entries:
                entries[-1].append(lines[index])
            else:
                entries.append([lines[index]])
            index += 1
            continue

        entry = start_entry
        index += consumed
        while index < len(lines):
            next_entry, _ = _consume_author_year_start(lines, index)
            if next_entry is not None:
                break
            entry.append(lines[index])
            index += 1
        entries.append(entry)
    return entries



def _consume_author_year_start(lines: list[str], index: int) -> tuple[list[str] | None, int]:
    line = lines[index]
    if NUMBERED_ENTRY_RE.match(line):
        return [line], 1
    if SAME_LINE_YEAR_RE.match(line):
        return [line], 1
    if not _looks_like_author_line(line):
        return None, 0

    entry = [line]
    cursor = index + 1
    while cursor < len(lines) and _looks_like_author_line(lines[cursor]) and not SAME_LINE_YEAR_RE.match(lines[cursor]):
        entry.append(lines[cursor])
        cursor += 1

    if cursor >= len(lines):
        return None, 0
    if NEXT_LINE_YEAR_RE.match(lines[cursor]) or SAME_LINE_YEAR_RE.match(lines[cursor]):
        entry.append(lines[cursor])
        return entry, cursor - index + 1
    return None, 0



def _join_entry_lines(lines: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(line.strip() for line in lines if line.strip())).strip()



def _build_rule_candidates(entries: list[list[str]], style: str) -> list[dict]:
    candidates: list[dict] = []
    for position, entry_lines in enumerate(entries, start=1):
        raw_text = _join_entry_lines(entry_lines)
        if not raw_text:
            continue
        candidate = _build_candidate(raw_text, position, style)
        if candidate:
            candidate["parser"] = "rule"
            candidates.append(candidate)
    return candidates



def _normalize_llm_candidates(candidates: list[dict] | None, style: str) -> list[dict]:
    if not candidates:
        return []

    normalized: list[dict] = []
    for position, item in enumerate(candidates, start=1):
        raw_text = _join_entry_lines(str(item.get("raw_text", "")).splitlines())
        if not raw_text:
            continue
        candidate = _build_candidate(raw_text, position, style)
        if not candidate:
            continue

        llm_title = _clean_title(item.get("title_guess", "") or "")
        candidate["title_guess"] = _prefer_title_guess(llm_title, candidate.get("title_guess", "") or "")
        if isinstance(item.get("year"), int):
            candidate["year"] = item["year"]
        candidate["arxiv_id"] = strip_version(item.get("arxiv_id", "") or candidate.get("arxiv_id", "") or "")
        candidate["doi"] = item.get("doi", "") or candidate.get("doi", "") or ""
        candidate["parser"] = "llm"
        if item.get("parse_confidence") is not None:
            candidate["parse_confidence"] = item.get("parse_confidence")
        if item.get("parse_notes"):
            candidate["parse_notes"] = item.get("parse_notes")
        normalized.append(candidate)
    return normalized



def _parse_reference_candidates_with_llm(lines: list[str], paper_id: str, style: str) -> list[dict] | None:
    chunks = _chunk_reference_lines_for_llm(lines)
    if not chunks:
        return None

    merged: list[dict] = []
    for chunk in chunks:
        parsed = parse_reference_block("\n".join(chunk), paper_id=paper_id, style=style)
        normalized = _normalize_llm_candidates(parsed, style)
        if not normalized:
            return None
        merged.extend(normalized)
    for index, item in enumerate(merged, start=1):
        item["index"] = index
    return merged



def _chunk_reference_lines_for_llm(lines: list[str], max_lines: int = 80, soft_min_lines: int = 40) -> list[list[str]]:
    if len(lines) <= max_lines:
        return [lines] if lines else []

    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if len(current) >= max_lines or (len(current) >= soft_min_lines and _looks_like_reference_chunk_boundary(line)):
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks



def _looks_like_reference_chunk_boundary(line: str) -> bool:
    lowered = line.lower()
    if not line.endswith('.'):
        return False
    if 'url ' in lowered or 'doi:' in lowered or 'arxiv' in lowered:
        return True
    return bool(YEAR_RE.search(line))



def _prefer_title_guess(primary: str, fallback: str) -> str:
    if not primary:
        return fallback
    if _looks_like_venue_fragment(primary) and fallback:
        return fallback
    if len(WORD_RE.findall(primary)) < 2 and fallback:
        return fallback
    return primary



def _prefer_candidate_set(lines: list[str], rule_candidates: list[dict], llm_candidates: list[dict]) -> list[dict]:
    if len(llm_candidates) < max(3, len(rule_candidates) // 2):
        return rule_candidates

    rule_penalty = _reference_candidate_penalty(lines, rule_candidates)
    llm_penalty = _reference_candidate_penalty(lines, llm_candidates)
    if llm_penalty < rule_penalty:
        return llm_candidates
    if llm_penalty == rule_penalty and len(llm_candidates) > len(rule_candidates):
        return llm_candidates
    return rule_candidates



def _author_year_candidates_look_suspicious(lines: list[str], candidates: list[dict]) -> bool:
    penalty = _reference_candidate_penalty(lines, candidates)
    threshold = max(4, len(candidates) // 4 + 2)
    return penalty >= threshold



def _reference_candidate_penalty(lines: list[str], candidates: list[dict]) -> int:
    if not candidates:
        return 10

    penalty = 0
    if len(lines) >= 18 and len(candidates) <= 4:
        penalty += 6

    average_lines_per_candidate = len(lines) / max(len(candidates), 1)
    if average_lines_per_candidate > 4.5:
        penalty += 2
    elif average_lines_per_candidate > 3.8:
        penalty += 1

    for candidate in candidates:
        penalty += _candidate_penalty(candidate)
    return penalty



def _candidate_penalty(candidate: dict) -> int:
    raw_text = candidate.get("raw_text", "") or ""
    title_guess = candidate.get("title_guess", "") or ""
    title_words = len(WORD_RE.findall(title_guess))
    raw_words = len(WORD_RE.findall(raw_text))
    lowered_title = title_guess.lower()
    lowered_raw = raw_text.lower()

    penalty = 0
    if _count_year_matches(raw_text) >= 2:
        penalty += 2
    if not title_guess:
        penalty += 2
    elif title_words < 3:
        penalty += 1
    if _looks_like_venue_fragment(title_guess):
        penalty += 2
    if any(fragment in lowered_title for fragment in ("proceedings", "findings", "springer", "technical report", "pages ")):
        penalty += 1
    if raw_words > 55:
        penalty += 2
    elif raw_words > 40:
        penalty += 1
    if lowered_raw.count(" arxiv:") >= 2 or lowered_raw.count(" arxiv preprint") >= 2:
        penalty += 2
    return penalty



def _count_year_matches(text: str) -> int:
    return len(_valid_year_matches(text))



def _build_candidate(raw_text: str, index: int, style: str) -> dict | None:
    year = _extract_year(raw_text)
    arxiv_id = strip_version(extract_arxiv_id(raw_text) or "")
    doi = extract_doi(raw_text) or ""
    title_guess = _extract_title(raw_text, style)
    if not raw_text:
        return None
    return {
        "index": index,
        "style": style,
        "raw_text": raw_text,
        "title_guess": title_guess,
        "year": year,
        "arxiv_id": arxiv_id,
        "doi": doi,
    }



def _find_year_match(text: str):
    matches = _valid_year_matches(text)
    if not matches:
        return None
    return max(matches, key=lambda item: _year_match_score(text, item))



def _extract_year(text: str) -> int | None:
    match = _find_year_match(text)
    return int(match.group(1)) if match else None



def _extract_title(text: str, style: str) -> str:
    stripped = NUMBERED_ENTRY_RE.sub(lambda match: match.group(3) or "", text).strip()
    if style == "numbered":
        return _extract_numbered_title(stripped)

    year_match = _find_year_match(stripped)
    if not year_match:
        return ""
    after_year = stripped[year_match.end():].lstrip(" .)")
    title = after_year.split(". ", 1)[0].strip().strip(".")
    return _clean_title(title)



def _extract_numbered_title(text: str) -> str:
    candidate_text = _strip_numbered_author_prefix(text)
    candidate_text = candidate_text.split(". arXiv preprint", 1)[0].strip().strip(".")
    parts = _split_reference_segments(candidate_text)
    if not parts:
        return ""

    for part in parts:
        if _looks_like_metadata_fragment(part):
            break
        if _looks_like_author_fragment(part):
            continue
        if len(WORD_RE.findall(part)) >= 3:
            return part

    fallback_candidates = [
        part for part in parts if not _looks_like_author_fragment(part) and not _looks_like_metadata_fragment(part)
    ]
    if fallback_candidates:
        return max(fallback_candidates, key=lambda item: (len(WORD_RE.findall(item)), len(item)))
    return _clean_title(parts[0])



def _looks_like_author_line(line: str) -> bool:
    if not line or ":" in line:
        return False
    if _find_year_match(line):
        return False
    if _looks_like_venue_fragment(line):
        return False
    lowered = line.lower()
    if "et al" in lowered or lowered.endswith(" others"):
        return True
    if "," in line and (" and " in lowered or "&" in line or line.count(",") >= 2):
        return True
    tokens = WORD_RE.findall(lowered)
    if not tokens:
        return False
    uppercase_words = [word for word in line.split() if word[:1].isupper()]
    return len(tokens) <= 12 and len(uppercase_words) >= max(2, len(tokens) // 2)



def _looks_like_author_fragment(part: str) -> bool:
    lowered = part.lower()
    tokens = WORD_RE.findall(lowered)
    if not tokens:
        return False
    if "et al" in lowered or lowered.endswith(" others"):
        return True
    if "&" in part and "," in part and ":" not in part:
        return True
    if part.count(",") >= 2 and ":" not in part:
        return True
    if len(tokens) <= 2:
        return True
    return False



def _looks_like_venue_fragment(part: str) -> bool:
    return bool(VENUE_FRAGMENT_RE.match(part))



def _looks_like_metadata_fragment(part: str) -> bool:
    lowered = part.lower()
    if _looks_like_venue_fragment(part):
        return True
    if lowered.startswith("doi:") or lowered.startswith("https://") or lowered.startswith("http://"):
        return True
    if lowered.startswith("arxiv preprint"):
        return True
    if " pp. " in f" {lowered} " or " vol. " in f" {lowered} ":
        return True
    if re.search(r"\b\d+\(\d+\)", part):
        return True
    if re.search(r"\b\d+\s*,\s*\d+\b", part):
        return True
    if re.search(r"\b\d+[–—-]\d+\b", part):
        return True
    if YEAR_RE.search(part) and re.search(r"\b\d+\b", part):
        return True
    return False



def _clean_title(title: str) -> str:
    title = title.replace("..", ".")
    title = re.sub(r"\s+", " ", title).strip(" .\"“”")
    return title



def _strip_numbered_author_prefix(text: str) -> str:
    if ": " in text:
        prefix, suffix = text.split(": ", 1)
        if _looks_like_author_fragment(prefix) or _looks_like_author_line(prefix):
            return suffix.strip()

    author_split = re.search(r"\.\s+(?=[A-Z0-9][^.]{2,})", text)
    if author_split:
        prefix = text[:author_split.start()].strip()
        if _looks_like_author_fragment(prefix) or _looks_like_author_line(prefix):
            return text[author_split.end():].strip()
    return text.strip()



def _split_reference_segments(text: str) -> list[str]:
    return [_clean_title(part) for part in re.split(r"\.\s+(?=[A-Z0-9])", text) if part.strip()]



def _valid_year_matches(text: str) -> list[re.Match[str]]:
    return [match for match in YEAR_RE.finditer(text) if not _is_suppressed_year_match(text, match)]



def _is_suppressed_year_match(text: str, match: re.Match[str]) -> bool:
    start = match.start()
    end = match.end()
    prev_char = text[start - 1] if start > 0 else ""
    next_char = text[end] if end < len(text) else ""
    if prev_char in YEAR_RANGE_BOUNDARY_CHARS or next_char in YEAR_RANGE_BOUNDARY_CHARS:
        return True
    if next_char == "." and re.match(r"\.\d{4,5}\b", text[end:]):
        return True
    return False



def _year_match_score(text: str, match: re.Match[str]) -> tuple[int, int]:
    start = match.start()
    end = match.end()
    prev_char = text[start - 1] if start > 0 else ""
    next_char = text[end] if end < len(text) else ""
    score = 0
    if prev_char == "(" and next_char == ")":
        score += 6
    elif next_char == ")":
        score += 4
    elif prev_char == "(":
        score += 3
    if end >= len(text) * 0.6:
        score += 2
    if not text[end:].strip(" .,)"):
        score += 3
    return (score, start)



def _normalize_title_for_compare(title: str) -> str:
    title = re.sub(r"^\[[0-9]{4}\.[0-9]{4,5}\]\s*", "", title)
    title = re.sub(r"\s+-\s+arxiv$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip()
    return title.lower()



def _title_similarity(left: str, right: str) -> float:
    left_tokens = set(WORD_RE.findall(left))
    right_tokens = set(WORD_RE.findall(right))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    if not overlap:
        return 0.0
    precision = overlap / len(right_tokens)
    recall = overlap / len(left_tokens)
    return (2 * precision * recall) / (precision + recall)



def _year_compatible(candidate_year: int | None, result_year: int | None, score: float) -> bool:
    if candidate_year is None or result_year is None:
        return True
    delta = abs(candidate_year - result_year)
    if delta <= 1:
        return True
    if delta <= 3 and score >= 0.9:
        return True
    return False
