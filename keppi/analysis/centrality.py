"""Hub, bridge, and orphan detection via centrality analysis."""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx


@dataclass
class CentralityResult:
    path: str
    title: str
    score: float


def find_hubs(graph: nx.DiGraph, top_n: int = 20) -> list[CentralityResult]:
    """Return top N nodes by degree centrality (most-connected notes)."""
    real_nodes = {n for n in graph.nodes if not str(n).startswith("__broken__")}
    subgraph = graph.subgraph(real_nodes)

    centrality = nx.degree_centrality(subgraph)
    results = [
        CentralityResult(
            path=node,
            title=graph.nodes[node].get("title", node),
            score=round(score, 6),
        )
        for node, score in centrality.items()
    ]
    results.sort(key=lambda r: -r.score)
    return results[:top_n]


def find_bridges(graph: nx.DiGraph, top_n: int = 20) -> list[CentralityResult]:
    """Return top N nodes by betweenness centrality (boundary spanners).

    Computes betweenness on the STRUCTURAL graph only (wikilinks, related_to,
    embeds) — tag_overlap edges don't represent traversal paths and would
    make betweenness meaningless. Uses sampled betweenness (k=100) for
    speed on large graphs.
    """
    real_nodes = {n for n in graph.nodes if not str(n).startswith("__broken__")}

    # Filter to structural edges only — tag_overlap is not a traversal path
    structural_edges = [
        (u, v)
        for u, v, d in graph.edges(data=True)
        if u in real_nodes
        and v in real_nodes
        and d.get("type") in ("wikilink", "related_to", "embed")
    ]
    subgraph = nx.Graph()
    subgraph.add_nodes_from(real_nodes)
    subgraph.add_edges_from(structural_edges)

    if subgraph.number_of_nodes() < 3 or subgraph.number_of_edges() == 0:
        return []

    # Sample 100 source nodes for approximate betweenness (fast on large graphs)
    k = min(100, subgraph.number_of_nodes())
    centrality = nx.betweenness_centrality(subgraph, k=k, normalized=True)
    results = [
        CentralityResult(
            path=node,
            title=graph.nodes[node].get("title", node),
            score=round(score, 6),
        )
        for node, score in centrality.items()
    ]
    results.sort(key=lambda r: -r.score)
    return results[:top_n]


def find_orphans(graph: nx.DiGraph) -> list[CentralityResult]:
    """Return nodes with zero real inbound AND zero real outbound edges."""
    real_nodes = {n for n in graph.nodes if not str(n).startswith("__broken__")}
    results = []
    for node in real_nodes:
        out_real = [d for _, d in graph.out_edges(node) if d in real_nodes]
        in_real = [s for s, _ in graph.in_edges(node) if s in real_nodes]
        if not out_real and not in_real:
            results.append(
                CentralityResult(
                    path=node,
                    title=graph.nodes[node].get("title", node),
                    score=0.0,
                )
            )
    results.sort(key=lambda r: r.title)
    return results
