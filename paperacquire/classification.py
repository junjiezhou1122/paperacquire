from __future__ import annotations

import re
from typing import Iterable


CATEGORY_AXES = ("domain", "task", "method")
CATEGORY_PRIORITY = ("domain", "task", "method")

TOPIC_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(medical|medicine|clinical|health|healthcare|biomedical)\b", re.I), "domain", "medical"),
    (re.compile(r"\b(radiology|radiologic)\b", re.I), "domain", "medical/radiology"),
    (re.compile(r"\b(ct|chest ct|computed tomography)\b", re.I), "domain", "medical/chest-ct"),
    (re.compile(r"\b(x-ray|xray|chest x-ray|cxr)\b", re.I), "domain", "medical/chest-xray"),
    (re.compile(r"\b(multimodal|vision-language|vision language|vlm|v-l)\b", re.I), "domain", "multimodal"),
    (re.compile(r"\b(report generation|radiology report|reporting)\b", re.I), "task", "report-generation"),
    (re.compile(r"\b(grounded|grounding)\b", re.I), "task", "grounding"),
    (re.compile(r"\b(retrieval|rag)\b", re.I), "task", "retrieval"),
    (re.compile(r"\b(evaluation|benchmark|verification)\b", re.I), "task", "evaluation"),
    (re.compile(r"\b(reasoning)\b", re.I), "method", "reasoning"),
    (re.compile(r"\b(agent|agents|agentic)\b", re.I), "method", "agent"),
    (re.compile(r"\b(tool use|tool-use|tools|function calling)\b", re.I), "method", "tool-use"),
    (re.compile(r"\b(transfer learning)\b", re.I), "method", "transfer-learning"),
    (re.compile(r"\b(transformer|llm|large language model|foundation model)\b", re.I), "method", "foundation-model"),
]


def build_classification(*, source_topics: Iterable[str] | None = None, title: str = "", overview_markdown: str = "") -> dict:
    raw_topics = [topic.strip() for topic in (source_topics or []) if topic and topic.strip()]
    tags = _dedupe(_slugify(topic) for topic in raw_topics)
    category: dict[str, list[str]] = {axis: [] for axis in CATEGORY_AXES}

    topic_text = "\n".join(raw_topics)
    fallback_text = "\n".join(part for part in (title, _trim_text(overview_markdown, 4000)) if part)

    _apply_rules(topic_text, category, tags)
    if not any(category.values()):
        _apply_rules(fallback_text, category, tags)

    category = {axis: values for axis, values in category.items() if values}
    primary_category = _primary_category(category)
    return {
        "source_topics": raw_topics,
        "tags": tags,
        "category": category,
        "primary_category": primary_category,
    }


def _apply_rules(text: str, category: dict[str, list[str]], tags: list[str]) -> None:
    if not text:
        return
    for pattern, axis, value in TOPIC_RULES:
        if pattern.search(text):
            category[axis] = _dedupe(category.get(axis, []) + [value])
            tags[:] = _dedupe(tags + [value])


def _primary_category(category: dict[str, list[str]]) -> str:
    for axis in CATEGORY_PRIORITY:
        values = category.get(axis, [])
        if values:
            return f"{axis}/{values[0]}"
    return ""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _trim_text(value: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", value or "").strip()
    return compact[:limit]


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
