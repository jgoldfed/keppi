"""Context pack: minimal token-budgeted reading set for a topic."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

import networkx as nx

from keppi.analysis.blast_radius import compute_blast_radius, find_node_by_title
from keppi.search.keyword import keyword_search

WORDS_PER_TOKEN = 0.75  # rough approximation: 1 token ≈ 0.75 words


@dataclass
class ContextEntry:
    path: str
    title: str
    relevance: float
    word_count: int
    estimated_tokens: int
    excerpt: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class ContextPack:
    topic: str
    entries: list[ContextEntry]
    total_tokens: int
    token_budget: int
    seed_note: str = ""


def build_context_pack(
    graph: nx.DiGraph,
    conn: sqlite3.Connection,
    topic: str,
    *,
    token_budget: int = 4000,
    depth: int = 2,
    case_sensitive: bool = False,
) -> ContextPack:
    """
    Build a minimal reading set for a topic within a token budget.

    Strategy:
    1. Find seed note(s) via keyword search
    2. Expand via blast_radius from seed
    3. Rank by: relevance × centrality × recency
    4. Fill budget greedily from top-ranked notes
    """
    # Step 1: find seed
    seed_node = find_node_by_title(graph, topic, case_sensitive=case_sensitive)
    if seed_node is None:
        search_results = keyword_search(conn, topic, limit=3)
        if search_results:
            seed_node = search_results[0].path

    if seed_node is None:
        return ContextPack(topic=topic, entries=[], total_tokens=0, token_budget=token_budget)

    # Step 2: blast radius gives us ranked neighbours
    blast = compute_blast_radius(graph, seed_node, depth=depth, threshold=0.1)

    # Build candidate pool: seed + blast radius
    candidates: list[tuple[str, float]] = [(seed_node, 1.0)]
    for r in blast:
        candidates.append((r.path, r.relevance))

    # Step 3: compute degree for centrality bonus
    real_nodes = {n for n in graph.nodes if not str(n).startswith("__broken__")}
    subgraph = graph.subgraph(real_nodes)
    max_degree = max((subgraph.degree(n) for n in real_nodes), default=1)

    # Step 4: fill budget
    entries: list[ContextEntry] = []
    tokens_used = 0

    for node_path, relevance in candidates:
        if tokens_used >= token_budget:
            break
        if node_path not in real_nodes:
            continue
        nd = graph.nodes.get(node_path, {})
        word_count = nd.get("word_count", 0)
        if isinstance(word_count, str):
            try:
                word_count = int(word_count)
            except ValueError:
                word_count = 0

        est_tokens = max(1, int(word_count / WORDS_PER_TOKEN))

        # Centrality bonus (0–1)
        deg = subgraph.degree(node_path)
        centrality_bonus = deg / max_degree if max_degree > 0 else 0

        adjusted_relevance = relevance * (1 + centrality_bonus * 0.2)

        try:
            tags = json.loads(nd.get("tags", "[]"))
        except (json.JSONDecodeError, TypeError):
            tags = []

        entries.append(
            ContextEntry(
                path=node_path,
                title=nd.get("title", node_path),
                relevance=round(adjusted_relevance, 4),
                word_count=word_count,
                estimated_tokens=est_tokens,
                tags=tags,
            )
        )
        tokens_used += est_tokens

    entries.sort(key=lambda e: -e.relevance)

    return ContextPack(
        topic=topic,
        entries=entries,
        total_tokens=tokens_used,
        token_budget=token_budget,
        seed_note=graph.nodes.get(seed_node, {}).get("title", seed_node),
    )
