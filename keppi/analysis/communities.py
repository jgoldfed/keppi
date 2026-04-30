"""Community detection using Louvain algorithm."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import networkx as nx


@dataclass
class Community:
    id: int
    nodes: list[str]
    size: int
    top_tags: list[str] = field(default_factory=list)
    top_types: list[str] = field(default_factory=list)
    representative: str = ""  # highest-degree node in community


def detect_communities(
    graph: nx.DiGraph,
    *,
    min_size: int = 2,
    resolution: float = 1.0,
) -> list[Community]:
    """
    Run Louvain community detection on the undirected projection of the graph.
    Returns communities sorted by size (largest first).
    """
    try:
        from networkx.algorithms.community import louvain_communities
    except ImportError:
        raise ImportError("networkx >= 3.0 required for louvain_communities")

    real_nodes = {n for n in graph.nodes if not str(n).startswith("__broken__")}
    subgraph = graph.subgraph(real_nodes)
    undirected = subgraph.to_undirected()

    if undirected.number_of_nodes() == 0:
        return []

    partitions = louvain_communities(undirected, resolution=resolution, seed=42)

    communities = []
    for idx, node_set in enumerate(partitions):
        nodes = list(node_set)
        if len(nodes) < min_size:
            continue

        tags_counter: dict[str, int] = {}
        types_counter: dict[str, int] = {}
        best_node = ""
        best_degree = -1

        for node in nodes:
            nd = graph.nodes.get(node, {})
            try:
                tags = json.loads(nd.get("tags", "[]"))
            except (json.JSONDecodeError, TypeError):
                tags = []
            for t in tags:
                tags_counter[t] = tags_counter.get(t, 0) + 1
            ntype = nd.get("type", "")
            if ntype:
                types_counter[ntype] = types_counter.get(ntype, 0) + 1
            deg = graph.degree(node)
            if deg > best_degree:
                best_degree = deg
                best_node = node

        top_tags = [t for t, _ in sorted(tags_counter.items(), key=lambda x: -x[1])[:5]]
        top_types = [t for t, _ in sorted(types_counter.items(), key=lambda x: -x[1])[:3]]

        communities.append(
            Community(
                id=idx,
                nodes=nodes,
                size=len(nodes),
                top_tags=top_tags,
                top_types=top_types,
                representative=best_node,
            )
        )

    communities.sort(key=lambda c: -c.size)
    return communities
