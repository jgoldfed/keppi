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
    """Return top N nodes by betweenness centrality (boundary spanners)."""
    real_nodes = {n for n in graph.nodes if not str(n).startswith("__broken__")}
    subgraph = graph.subgraph(real_nodes).to_undirected()

    if subgraph.number_of_nodes() < 3:
        return []

    centrality = nx.betweenness_centrality(subgraph, normalized=True)
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
