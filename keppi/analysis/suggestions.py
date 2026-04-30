"""Link suggestions: notes that should probably link to each other."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import networkx as nx


@dataclass
class LinkSuggestion:
    source_path: str
    source_title: str
    target_path: str
    target_title: str
    score: float
    reasons: list[str] = field(default_factory=list)


def suggest_links(
    graph: nx.DiGraph,
    source: str | None = None,
    *,
    top_n: int = 20,
    min_score: float = 0.3,
) -> list[LinkSuggestion]:
    """
    Suggest missing links based on tag overlap and shared neighbours.

    If source is given, returns suggestions for that node.
    If source is None, returns top suggestions across all nodes (slow on large graphs).
    """
    real_nodes = {n for n in graph.nodes if not str(n).startswith("__broken__")}

    if source is not None:
        if source not in real_nodes:
            return []
        candidates = real_nodes - {source}
        return _score_pairs(graph, [(source, c) for c in candidates], top_n, min_score)

    # Global mode: sample pairs that share a tag (most promising candidates)
    tag_index: dict[str, list[str]] = {}
    for node in real_nodes:
        nd = graph.nodes[node]
        try:
            tags = json.loads(nd.get("tags", "[]"))
        except (json.JSONDecodeError, TypeError):
            tags = []
        for t in tags:
            tag_index.setdefault(t, []).append(node)

    pairs: set[tuple[str, str]] = set()
    for tag, nodes in tag_index.items():
        if len(nodes) < 2:
            continue
        for i, a in enumerate(nodes[:50]):  # limit combinatorial explosion
            for b in nodes[i + 1 : 51]:
                if not graph.has_edge(a, b) and not graph.has_edge(b, a):
                    pairs.add((a, b) if a < b else (b, a))

    return _score_pairs(graph, list(pairs), top_n, min_score)


def _score_pairs(
    graph: nx.DiGraph,
    pairs: list[tuple[str, str]],
    top_n: int,
    min_score: float,
) -> list[LinkSuggestion]:
    results = []
    for a, b in pairs:
        if graph.has_edge(a, b) or graph.has_edge(b, a):
            continue

        score = 0.0
        reasons = []

        # Tag Jaccard
        tags_a = set(json.loads(graph.nodes[a].get("tags", "[]") or "[]"))
        tags_b = set(json.loads(graph.nodes[b].get("tags", "[]") or "[]"))
        if tags_a and tags_b:
            j = len(tags_a & tags_b) / len(tags_a | tags_b)
            if j > 0:
                score += j * 2.0
                shared = list(tags_a & tags_b)[:3]
                reasons.append(f"shared tags: {', '.join(shared)}")

        # Shared neighbours
        nbrs_a = set(n for _, n in graph.out_edges(a)) | set(n for n, _ in graph.in_edges(a))
        nbrs_b = set(n for _, n in graph.out_edges(b)) | set(n for n, _ in graph.in_edges(b))
        nbrs_a.discard(b)
        nbrs_b.discard(a)
        shared_nbrs = nbrs_a & nbrs_b
        if shared_nbrs:
            score += min(len(shared_nbrs) * 0.3, 1.0)
            titles = [graph.nodes[n].get("title", n) for n in list(shared_nbrs)[:2]]
            reasons.append(f"shared connections: {', '.join(titles)}")

        if score < min_score:
            continue

        results.append(
            LinkSuggestion(
                source_path=a,
                source_title=graph.nodes[a].get("title", a),
                target_path=b,
                target_title=graph.nodes[b].get("title", b),
                score=round(score, 3),
                reasons=reasons,
            )
        )

    results.sort(key=lambda r: -r.score)
    return results[:top_n]


def find_broken_links(graph: nx.DiGraph) -> list[dict]:
    """Return all broken wikilink edges (target doesn't exist in graph)."""
    broken = []
    for src, dst, data in graph.edges(data=True):
        if data.get("type") == "wikilink_broken":
            target_name = dst.replace("__broken__:", "")
            broken.append(
                {
                    "source_path": src,
                    "source_title": graph.nodes.get(src, {}).get("title", src),
                    "target_name": target_name,
                }
            )
    broken.sort(key=lambda x: x["source_title"])
    return broken
