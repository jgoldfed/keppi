"""Blast radius: BFS from a seed note, weighted by edge type."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import networkx as nx


@dataclass
class AffectedNote:
    path: str
    title: str
    relevance: float
    distance: int
    edge_types: list[str] = field(default_factory=list)


def compute_blast_radius(
    graph: nx.DiGraph,
    seed: str,
    *,
    depth: int = 2,
    threshold: float = 0.3,
    direction: str = "both",
) -> list[AffectedNote]:
    """
    BFS from seed node, accumulating weighted relevance scores.

    direction: "out" (follow outgoing links), "in" (backlinks only), "both"
    """
    if not graph.has_node(seed):
        return []

    visited: dict[str, AffectedNote] = {}
    queue: deque[tuple[str, float, int, list[str]]] = deque()

    # Bootstrap from seed's neighbours
    queue.append((seed, 1.0, 0, []))

    while queue:
        node, relevance, dist, path_types = queue.popleft()

        if node != seed and node in visited:
            # Only update if we found a higher-relevance path
            if visited[node].relevance >= relevance:
                continue
        if dist > depth:
            continue

        if node != seed:
            visited[node] = AffectedNote(
                path=node,
                title=graph.nodes[node].get("title", node),
                relevance=round(relevance, 4),
                distance=dist,
                edge_types=path_types,
            )

        if dist == depth:
            continue

        neighbours = _get_neighbours(graph, node, direction)
        for nbr, edge_data in neighbours:
            if nbr.startswith("__broken__"):
                continue
            edge_weight = edge_data.get("weight", 1.0)
            new_relevance = relevance * edge_weight
            if new_relevance < threshold:
                continue
            edge_type = edge_data.get("type", "wikilink")
            queue.append((nbr, new_relevance, dist + 1, path_types + [edge_type]))

    results = [note for note in visited.values() if note.relevance >= threshold]
    results.sort(key=lambda n: (-n.relevance, n.distance))
    return results


def _get_neighbours(
    graph: nx.DiGraph, node: str, direction: str
) -> list[tuple[str, dict]]:
    neighbours = []
    if direction in ("out", "both"):
        for _, dst, data in graph.out_edges(node, data=True):
            neighbours.append((dst, data))
    if direction in ("in", "both"):
        for src, _, data in graph.in_edges(node, data=True):
            neighbours.append((src, data))
    return neighbours


def find_node_by_title(graph: nx.DiGraph, query: str, case_sensitive: bool = False) -> str | None:
    """Find a node by exact or case-insensitive title match, then stem match."""
    q = query if case_sensitive else query.lower()
    for node, data in graph.nodes(data=True):
        if node.startswith("__broken__"):
            continue
        title = data.get("title", "")
        cmp = title if case_sensitive else title.lower()
        if cmp == q:
            return node

    # Fallback: match by file stem
    from pathlib import Path
    for node in graph.nodes:
        if node.startswith("__broken__"):
            continue
        stem = Path(node).stem
        cmp = stem if case_sensitive else stem.lower()
        if cmp == q:
            return node

    return None
