from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from .normalize import extract_arxiv_id, extract_doi, strip_version

DEFAULT_BASE_URL = "https://api.openai.com"
DEFAULT_MODEL = "gpt-4.1-mini"
SYSTEM_PROMPT = (
    "You parse bibliography blocks from research papers. "
    "Return strict JSON only with no markdown fences or commentary. "
    "Split the block into exactly one reference per entry. "
    "Extract only information explicitly present in the text. "
    "Do not guess arXiv IDs, DOIs, or paper matches. "
    "If the title boundary is uncertain, prefer a shorter title span that excludes venue text."
)
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})(?:[a-d])?\b")



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



def _resolve_api_key() -> str | None:
    return (
        os.environ.get("PAPER_ACQUISITION_REFERENCE_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or _read_zshrc("PAPER_ACQUISITION_REFERENCE_LLM_API_KEY")
        or _read_zshrc("OPENAI_API_KEY")
    )



def _resolve_base_url() -> str:
    return (
        os.environ.get("PAPER_ACQUISITION_REFERENCE_LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or _read_zshrc("PAPER_ACQUISITION_REFERENCE_LLM_BASE_URL")
        or _read_zshrc("OPENAI_BASE_URL")
        or DEFAULT_BASE_URL
    )



def _resolve_api_url() -> str:
    base_url = _resolve_base_url().strip().rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/chat/completions"
    return f"{base_url}/v1/chat/completions"



def _resolve_model() -> str:
    return (
        os.environ.get("PAPER_ACQUISITION_REFERENCE_LLM_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or _read_zshrc("PAPER_ACQUISITION_REFERENCE_LLM_MODEL")
        or _read_zshrc("OPENAI_MODEL")
        or DEFAULT_MODEL
    )



def parse_reference_block(reference_block: str, paper_id: str = "", style: str = "author_year") -> list[dict] | None:
    if style != "author_year" or not reference_block.strip():
        return None

    api_key = _resolve_api_key()
    if not api_key:
        return None

    return _parse_reference_block_once(reference_block, api_key, paper_id, style)



def _parse_reference_block_once(reference_block: str, api_key: str, paper_id: str, style: str) -> list[dict] | None:
    payload = {
        "model": _resolve_model(),
        "temperature": 0,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(reference_block, paper_id, style)},
        ],
    }
    text = _request_openai_compatible_text(payload, api_key)
    if not text:
        return None

    data = _extract_json_payload(text)
    if data is None:
        return None
    return _normalize_entries(data, style)



def _build_user_prompt(reference_block: str, paper_id: str, style: str) -> str:
    return f'''Return a JSON object with this shape:
{{
  "style": "{style}",
  "entries": [
    {{
      "index": 1,
      "raw_text": "full text of exactly one reference entry",
      "title_guess": "title only, without venue text when possible",
      "year": 2025,
      "arxiv_id": "",
      "doi": "",
      "confidence": 0.0,
      "notes": []
    }}
  ]
}}

Rules:
- Preserve bibliography order.
- `raw_text` must contain exactly one reference entry.
- Split adjacent references instead of merging them.
- Only set `arxiv_id` or `doi` when explicitly present in the reference text.
- Use null for `year` when it is missing.
- `confidence` should reflect parsing confidence only.
- `notes` should be a short list of flags like `boundary_uncertain` or `title_truncated` when needed.
- Do not use outside knowledge and do not resolve papers.

Paper id: {paper_id or "unknown"}
Bibliography style: {style}
Reference block:
<references>
{reference_block}
</references>
'''



def _request_openai_compatible_text(payload: dict[str, Any], api_key: str) -> str | None:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        _resolve_api_url(),
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    choices = body.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
    return _extract_message_text(message)



def _extract_message_text(message: Any) -> str | None:
    if not isinstance(message, dict):
        return None
    content = message.get("content", "")
    if isinstance(content, str):
        text = content.strip()
        return text or None
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text", "")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    joined = "\n".join(parts).strip()
    return joined or None



def _extract_json_payload(text: str) -> Any | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()

    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = cleaned.find(start_char)
        end = cleaned.rfind(end_char)
        if start == -1 or end == -1 or end < start:
            continue
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            continue
    return None



def _normalize_entries(data: Any, style: str) -> list[dict] | None:
    entries = data.get("entries") if isinstance(data, dict) else data if isinstance(data, list) else None
    if not isinstance(entries, list):
        return None

    normalized: list[dict] = []
    for index, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            continue
        raw_text = _clean_text(item.get("raw_text", "") or "")
        if not raw_text:
            continue
        normalized.append(
            {
                "index": _coerce_index(item.get("index"), index),
                "style": style,
                "raw_text": raw_text,
                "title_guess": _clean_text(item.get("title_guess", "") or ""),
                "year": _coerce_year(item.get("year")) or _extract_year(raw_text),
                "arxiv_id": strip_version(extract_arxiv_id(raw_text) or ""),
                "doi": extract_doi(raw_text) or "",
                "parser": "llm",
                "parse_confidence": _coerce_confidence(item.get("confidence")),
                "parse_notes": _coerce_notes(item.get("notes")),
            }
        )
    return normalized or None



def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).strip(" .\"“”")



def _coerce_index(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback



def _coerce_year(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 1900 <= parsed <= 2100 else None



def _coerce_confidence(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return 0.0
    if parsed > 1:
        return 1.0
    return parsed



def _coerce_notes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]



def _find_year_match(text: str):
    for match in YEAR_RE.finditer(text):
        start = match.start()
        end = match.end()
        prev_char = text[start - 1] if start > 0 else ""
        next_char = text[end] if end < len(text) else ""
        if prev_char in {"-", "/"} or next_char in {"-", "/"}:
            continue
        return match
    return None



def _extract_year(text: str) -> int | None:
    match = _find_year_match(text)
    return int(match.group(1)) if match else None
