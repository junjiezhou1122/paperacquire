from __future__ import annotations

import json
from typing import Callable

from .bibliography import resolve_reference_candidates_for_paper, resolved_candidate_to_graph_node
from .index import get_record, upsert_record
from .models import GraphEdge, GraphNode, PaperRecord, now_iso
from .normalize import normalize_input
from .paths import graph_path
from .sources.alphaxiv import fetch_paper as fetch_alphaxiv_paper
from .sources.huggingface import fetch_paper as fetch_huggingface_paper
from .sources.openalex import fetch_citations as fetch_openalex_citations
from .sources.openalex import fetch_references as fetch_openalex_references
from .sources.openalex import fetch_work as fetch_openalex_work
from .sources.semantic_scholar import fetch_citations as fetch_semantic_citations
from .sources.semantic_scholar import fetch_paper as fetch_semantic_paper
from .sources.semantic_scholar import fetch_references as fetch_semantic_references


EMPTY_GRAPH = {"version": 1, "nodes": [], "edges": [], "expansions": []}



def load_graph() -> dict:
    path = graph_path()
    if not path.exists():
        return dict(EMPTY_GRAPH)
    return json.loads(path.read_text(encoding="utf-8"))



def save_graph(graph: dict) -> None:
    payload = {
        "version": 1,
        "nodes": sorted(graph.get("nodes", []), key=lambda item: item["key"]),
        "edges": sorted(graph.get("edges", []), key=lambda item: (item["source_key"], item["edge_type"], item["target_key"])),
        "expansions": graph.get("expansions", []),
    }
    graph_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")



def expand_graph(input_value: str, include_references: bool = True, include_citations: bool = True, limit: int = 25) -> dict:
    normalized = normalize_input(input_value)
    existing = get_record(normalized.paper_id) if normalized.paper_id else None
    seed = _resolve_seed(normalized, existing)
    if seed is None:
        raise ValueError(f"Could not resolve paper for graph expansion: {input_value}")

    graph = load_graph()
    _upsert_node(graph, seed)

    added_references = 0
    added_citations = 0
    providers_used: set[str] = set()

    if include_references:
        for node in _fetch_local_references(seed, limit):
            providers_used.add("local_markdown")
            _upsert_node(graph, node)
            if _upsert_edge(graph, GraphEdge(source_key=seed.key, target_key=node.key, edge_type="reference", providers=["local_markdown"])):
                added_references += 1

        for provider, fetcher in (("openalex", fetch_openalex_references), ("semantic_scholar", fetch_semantic_references)):
            for node in _safe_fetch(fetcher, seed, limit):
                providers_used.add(provider)
                _upsert_node(graph, node)
                if _upsert_edge(graph, GraphEdge(source_key=seed.key, target_key=node.key, edge_type="reference", providers=[provider])):
                    added_references += 1

    if include_citations:
        for provider, fetcher in (("openalex", fetch_openalex_citations), ("semantic_scholar", fetch_semantic_citations)):
            for node in _safe_fetch(fetcher, seed, limit):
                providers_used.add(provider)
                _upsert_node(graph, node)
                if _upsert_edge(graph, GraphEdge(source_key=node.key, target_key=seed.key, edge_type="citation", providers=[provider])):
                    added_citations += 1

    graph.setdefault("expansions", []).append(
        {
            "seed_key": seed.key,
            "paper_id": seed.paper_id,
            "references": include_references,
            "citations": include_citations,
            "providers": sorted(providers_used),
            "limit": limit,
            "expanded_at": now_iso(),
        }
    )
    save_graph(graph)
    _update_index_summary(seed, include_references, include_citations)

    return {
        "seed": seed.to_dict(),
        "references_added": added_references,
        "citations_added": added_citations,
        "providers": sorted(providers_used),
        "graph_path": str(graph_path()),
    }



def _resolve_seed(normalized, existing: dict | None) -> GraphNode | None:
    if existing:
        seed = _seed_from_record(existing)
        enriched = _enrich_seed(seed)
        return _prefer_local_seed(seed, enriched)

    if normalized.paper_id:
        seed = GraphNode(
            key=normalized.paper_id,
            title="",
            paper_id=normalized.paper_id,
            identifiers={
                "arxiv_id": normalized.paper_id,
                "doi": normalized.doi,
                "openalex_id": normalized.openalex_id,
                "semantic_scholar_id": normalized.semantic_scholar_id,
            },
            sources=[],
        )
        enriched = _enrich_seed(seed)
        return enriched or seed

    return None



def _fetch_local_references(seed: GraphNode, limit: int) -> list[GraphNode]:
    if not seed.paper_id:
        return []
    try:
        resolved = resolve_reference_candidates_for_paper(seed.paper_id, limit=limit)
    except Exception:
        return []
    nodes: list[GraphNode] = []
    for candidate in resolved:
        node = resolved_candidate_to_graph_node(candidate)
        if node.key:
            nodes.append(node)
    return nodes


def _safe_fetch(fetcher: Callable[[str, int], list[GraphNode]], seed: GraphNode, limit: int) -> list[GraphNode]:
    identifiers = [
        f"ARXIV:{seed.paper_id}" if seed.paper_id else "",
        seed.paper_id,
        seed.identifiers.get("doi", ""),
        seed.identifiers.get("openalex_id", ""),
        seed.identifiers.get("semantic_scholar_id", ""),
        seed.title,
    ]
    seen: set[str] = set()
    for identifier in identifiers:
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        try:
            results = fetcher(identifier, limit)
        except Exception:
            continue
        if results:
            return [node for node in results if node.key]
    return []



def _enrich_seed(seed: GraphNode) -> GraphNode | None:
    enriched: GraphNode | None = None
    for fetcher in (_fetch_openalex_seed, _fetch_semantic_seed):
        try:
            node = fetcher(seed)
        except Exception:
            continue
        if not node or not _titles_compatible(seed.title, node.title):
            continue
        enriched = _merge_seed(enriched or seed, node)
    return enriched



def _fetch_openalex_seed(seed: GraphNode) -> GraphNode | None:
    identifiers = [seed.identifiers.get("openalex_id", ""), seed.identifiers.get("doi", ""), seed.paper_id, seed.title]
    for identifier in identifiers:
        if not identifier:
            continue
        node = fetch_openalex_work(identifier)
        if node:
            return node
    return None



def _fetch_semantic_seed(seed: GraphNode) -> GraphNode | None:
    identifiers = [seed.identifiers.get("semantic_scholar_id", ""), f"ARXIV:{seed.paper_id}" if seed.paper_id else "", seed.identifiers.get("doi", ""), seed.paper_id]
    for identifier in identifiers:
        if not identifier:
            continue
        node = fetch_semantic_paper(identifier)
        if node:
            return node
    return None



def _titles_compatible(base_title: str, enriched_title: str) -> bool:
    if not base_title or not enriched_title:
        return True
    base_tokens = set(_normalize_title(base_title).split())
    enriched_tokens = set(_normalize_title(enriched_title).split())
    if not base_tokens or not enriched_tokens:
        return True
    overlap = len(base_tokens & enriched_tokens)
    return overlap / min(len(base_tokens), len(enriched_tokens)) >= 0.6



def _normalize_title(title: str) -> str:
    return " ".join(part for part in "".join(ch.lower() if ch.isalnum() else " " for ch in title).split())



def _seed_from_record(record: dict) -> GraphNode:
    identifiers = dict(record.get("identifiers", {}))
    identifiers.setdefault("arxiv_id", record.get("paper_id", ""))
    return GraphNode(
        key=record.get("paper_id", ""),
        title=record.get("title", ""),
        paper_id=record.get("paper_id", ""),
        identifiers=identifiers,
        authors=record.get("authors", []),
        year=record.get("year"),
        venue=record.get("venue", ""),
        citation_count=record.get("citation_count"),
        canonical_url=record.get("canonical_url", ""),
        pdf_url=record.get("pdf_url", ""),
        sources=record.get("sources", []),
    )



def _prefer_local_seed(local_seed: GraphNode, enriched: GraphNode | None) -> GraphNode:
    if not enriched:
        return _refresh_local_seed(local_seed)
    return _refresh_local_seed(_merge_seed(local_seed, enriched))



def _refresh_local_seed(seed: GraphNode) -> GraphNode:
    if not seed.paper_id:
        return seed
    refreshed = _fetch_local_text_seed(seed.paper_id)
    if not refreshed:
        return seed
    identifiers = dict(seed.identifiers)
    for key, value in refreshed.identifiers.items():
        if value and not identifiers.get(key):
            identifiers[key] = value
    return GraphNode(
        key=seed.key or refreshed.key,
        title=refreshed.title or seed.title,
        paper_id=seed.paper_id or refreshed.paper_id,
        identifiers=identifiers,
        authors=refreshed.authors or seed.authors,
        year=refreshed.year if refreshed.year is not None else seed.year,
        venue=seed.venue or refreshed.venue,
        citation_count=seed.citation_count if seed.citation_count is not None else refreshed.citation_count,
        canonical_url=refreshed.canonical_url or seed.canonical_url,
        pdf_url=refreshed.pdf_url or seed.pdf_url,
        sources=sorted(set(seed.sources + refreshed.sources)),
    )



def _fetch_local_text_seed(paper_id: str) -> GraphNode | None:
    alphaxiv_result = fetch_alphaxiv_paper(paper_id)
    hf_result = fetch_huggingface_paper(paper_id)
    title = alphaxiv_result.title or hf_result.title
    authors = alphaxiv_result.authors or hf_result.authors or []
    published = alphaxiv_result.published or hf_result.published or ""
    year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None
    if not title and not authors and year is None:
        return None
    return GraphNode(
        key=paper_id,
        title=title,
        paper_id=paper_id,
        identifiers={"arxiv_id": paper_id},
        authors=authors,
        year=year,
        canonical_url=f"https://arxiv.org/abs/{paper_id}",
        pdf_url=f"https://arxiv.org/pdf/{paper_id}.pdf",
        sources=[source for source in ["alphaxiv" if title or alphaxiv_result.overview_markdown or alphaxiv_result.abs_markdown else "", "huggingface" if hf_result.title or hf_result.markdown else ""] if source],
    )



def _merge_seed(base: GraphNode, enriched: GraphNode) -> GraphNode:
    identifiers = dict(base.identifiers)
    for key, value in enriched.identifiers.items():
        if value and not identifiers.get(key):
            identifiers[key] = value
    return GraphNode(
        key=base.key or enriched.key,
        title=base.title or enriched.title,
        paper_id=base.paper_id or enriched.paper_id,
        identifiers=identifiers,
        authors=base.authors or enriched.authors,
        year=base.year if base.year is not None else enriched.year,
        venue=base.venue or enriched.venue,
        citation_count=base.citation_count if base.citation_count is not None else enriched.citation_count,
        canonical_url=base.canonical_url or enriched.canonical_url,
        pdf_url=base.pdf_url or enriched.pdf_url,
        sources=sorted(set(base.sources + enriched.sources)),
    )



def _upsert_node(graph: dict, node: GraphNode) -> None:
    nodes = graph.setdefault("nodes", [])
    existing = next((item for item in nodes if item.get("key") == node.key), None)
    if existing is None:
        nodes.append(node.to_dict())
        return
    if node.paper_id and existing.get("paper_id") == node.paper_id:
        existing.update(node.to_dict())
        existing["sources"] = sorted(set(existing.get("sources", []) + node.sources))
        return
    for field in ("title", "paper_id", "year", "venue", "citation_count", "canonical_url", "pdf_url"):
        if not existing.get(field) and getattr(node, field):
            existing[field] = getattr(node, field)
    if not existing.get("authors") and node.authors:
        existing["authors"] = node.authors
    existing_identifiers = dict(existing.get("identifiers", {}))
    for key, value in node.identifiers.items():
        if value and not existing_identifiers.get(key):
            existing_identifiers[key] = value
    existing["identifiers"] = existing_identifiers
    existing["sources"] = sorted(set(existing.get("sources", []) + node.sources))



def _upsert_edge(graph: dict, edge: GraphEdge) -> bool:
    edges = graph.setdefault("edges", [])
    existing = next(
        (
            item
            for item in edges
            if item.get("source_key") == edge.source_key and item.get("target_key") == edge.target_key and item.get("edge_type") == edge.edge_type
        ),
        None,
    )
    if existing is None:
        edges.append(edge.to_dict())
        return True
    existing["providers"] = sorted(set(existing.get("providers", []) + edge.providers))
    return False



def _update_index_summary(seed: GraphNode, include_references: bool, include_citations: bool) -> None:
    if not seed.paper_id:
        return
    existing = get_record(seed.paper_id) or {}
    refreshed_seed = _prefer_local_seed(_seed_from_record(existing) if existing else seed, seed)
    merged_identifiers = dict(existing.get("identifiers", {}))
    merged_identifiers.update({key: value for key, value in refreshed_seed.identifiers.items() if value})
    record = PaperRecord(
        paper_id=seed.paper_id,
        title=refreshed_seed.title or existing.get("title", ""),
        source=existing.get("source", "graph"),
        sources=sorted(set((existing.get("sources", []) or []) + refreshed_seed.sources)),
        source_input=existing.get("source_input", seed.paper_id),
        canonical_url=existing.get("canonical_url") or refreshed_seed.canonical_url,
        overview_path=existing.get("overview_path"),
        abs_path=existing.get("abs_path"),
        authors=refreshed_seed.authors or existing.get("authors", []),
        published=existing.get("published", ""),
        status=existing.get("status", {}),
        identifiers=merged_identifiers,
        venue=refreshed_seed.venue or existing.get("venue", ""),
        year=refreshed_seed.year if refreshed_seed.year is not None else existing.get("year"),
        citation_count=refreshed_seed.citation_count if refreshed_seed.citation_count is not None else existing.get("citation_count"),
        pdf_url=existing.get("pdf_url") or refreshed_seed.pdf_url,
        landing_page_url=existing.get("landing_page_url") or refreshed_seed.canonical_url,
        graph_status={
            "references_fetched": "fetched" if include_references else existing.get("graph_status", {}).get("references_fetched", "missing"),
            "citations_fetched": "fetched" if include_citations else existing.get("graph_status", {}).get("citations_fetched", "missing"),
        },
        source_topics=existing.get("source_topics", []),
    )
    upsert_record(record)
