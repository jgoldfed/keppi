"""Gap detection: find idea clusters with no (or weak) cross-community bridges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import networkx as nx

if TYPE_CHECKING:
    from keppi.analysis.communities import Community


@dataclass
class Gap:
    community_a_id: int
    community_b_id: int
    community_a_tags: list[str]
    community_b_tags: list[str]
    shared_tags: list[str]
    bridge_edge_count: int
    description: str


def detect_gaps(
    graph: nx.DiGraph,
    communities: list["Community"],
    *,
    max_bridge_edges: int = 2,
    min_shared_tags: int = 1,
) -> list[Gap]:
    """
    Find pairs of communities with shared tags but few or no connecting edges.
    These are structural blind spots — related ideas that don't cross-reference.
    """
    # Build a node→community map
    node_to_community: dict[str, int] = {}
    for comm in communities:
        for node in comm.nodes:
            node_to_community[node] = comm.id

    # Count cross-community edges
    bridge_counts: dict[tuple[int, int], int] = {}
    for src, dst in graph.edges():
        if src.startswith("__broken__") or dst.startswith("__broken__"):
            continue
        c_src = node_to_community.get(src)
        c_dst = node_to_community.get(dst)
        if c_src is None or c_dst is None or c_src == c_dst:
            continue
        key = (min(c_src, c_dst), max(c_src, c_dst))
        bridge_counts[key] = bridge_counts.get(key, 0) + 1

    # Find sparse pairs that share tags
    comm_by_id = {c.id: c for c in communities}
    gaps = []
    ids = [c.id for c in communities]

    for i, id_a in enumerate(ids):
        for id_b in ids[i + 1 :]:
            key = (min(id_a, id_b), max(id_a, id_b))
            bridges = bridge_counts.get(key, 0)
            if bridges > max_bridge_edges:
                continue

            ca = comm_by_id[id_a]
            cb = comm_by_id[id_b]
            shared = [t for t in ca.top_tags if t in cb.top_tags]
            if len(shared) < min_shared_tags:
                continue

            desc = (
                f"Community {id_a} ({', '.join(ca.top_tags[:3])}) and "
                f"Community {id_b} ({', '.join(cb.top_tags[:3])}) "
                f"share tags [{', '.join(shared[:3])}] but have only {bridges} connecting edges."
            )
            gaps.append(
                Gap(
                    community_a_id=id_a,
                    community_b_id=id_b,
                    community_a_tags=ca.top_tags,
                    community_b_tags=cb.top_tags,
                    shared_tags=shared,
                    bridge_edge_count=bridges,
                    description=desc,
                )
            )

    gaps.sort(key=lambda g: (g.bridge_edge_count, -len(g.shared_tags)))
    return gaps
