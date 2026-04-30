"""Temporal drift: notes that are stale but connected to recently-updated notes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

import networkx as nx


@dataclass
class DriftResult:
    path: str
    title: str
    last_updated: str
    days_stale: int
    connected_recent: list[str]
    reason: str


def _parse_date(raw: str) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return date.fromisoformat(raw) if fmt == "%Y-%m-%d" else None
        except ValueError:
            pass
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def detect_drift(
    graph: nx.DiGraph,
    *,
    stale_days: int = 30,
    recent_days: int = 14,
    top_n: int = 30,
) -> list[DriftResult]:
    """
    Find notes that haven't been updated in `stale_days` but are connected
    to notes updated within `recent_days`.
    """
    today = date.today()
    stale_cutoff = today - timedelta(days=stale_days)
    recent_cutoff = today - timedelta(days=recent_days)

    real_nodes = {n for n in graph.nodes if not str(n).startswith("__broken__")}

    # Classify nodes
    stale: set[str] = set()
    recent: set[str] = set()

    for node in real_nodes:
        nd = graph.nodes[node]
        raw = nd.get("updated", "")
        d = _parse_date(raw)
        if d is None:
            stale.add(node)
        elif d <= stale_cutoff:
            stale.add(node)
        elif d >= recent_cutoff:
            recent.add(node)

    results = []
    for node in stale:
        nd = graph.nodes[node]
        # Find connected recent nodes (both directions)
        connected = []
        for _, dst in graph.out_edges(node):
            if dst in recent:
                connected.append(graph.nodes[dst].get("title", dst))
        for src, _ in graph.in_edges(node):
            if src in recent:
                t = graph.nodes[src].get("title", src)
                if t not in connected:
                    connected.append(t)

        if not connected:
            continue

        raw_date = nd.get("updated", "")
        d = _parse_date(raw_date)
        days_stale = (today - d).days if d else stale_days + 1

        results.append(
            DriftResult(
                path=node,
                title=nd.get("title", node),
                last_updated=raw_date or "unknown",
                days_stale=days_stale,
                connected_recent=connected[:5],
                reason=f"Not updated in {days_stale}d but connected to: {', '.join(connected[:3])}",
            )
        )

    results.sort(key=lambda r: -r.days_stale)
    return results[:top_n]
