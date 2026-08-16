"""Keppi MCP server — exposes graph analysis tools via the Model Context Protocol."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import networkx as nx
from mcp.server.fastmcp import FastMCP

from keppi.parser.config import Config, load_config

mcp = FastMCP(
    "keppi",
    instructions=(
        "Keppi gives you graph-aware and semantic access to a knowledge vault. "
        "SEARCH STRATEGY: "
        "(1) Call get_embed_status() once to check if semantic search is ready. "
        "(2) Use semantic_search() as your first search — it finds notes by meaning, not exact keywords. "
        "Pass subfolder='<name>' to scope the search to a specific directory. "
        "One call replaces 2-3 keyword attempts. "
        "(3) Fall back to keyword_search only if semantic returns no strong results (distance > 0.5). "
        "Use context_pack to build a token-budgeted reading set for deep research. "
        "Use blast_radius to trace structural impact of a concept change. "
        "Use detect_gaps to find blind spots between idea clusters."
    ),
)

# Lazy-loaded state: {vault_path: (graph, conn, config)}
_state: dict[str, tuple[nx.DiGraph, sqlite3.Connection, Config]] = {}


def _load(vault_path: str = ".") -> tuple[nx.DiGraph, sqlite3.Connection, Config]:
    """Load and cache graph + db connection for the given vault path."""
    import hashlib
    import os

    if vault_path == "." and "KEPPI_VAULT" in os.environ:
        vault_path = os.environ["KEPPI_VAULT"]

    key = str(Path(vault_path).resolve())
    if key in _state:
        return _state[key]

    config = load_config(Path(key))
    config.vault.path = key
    vault_root = config.vault_root()
    vault_hash = hashlib.sha256(str(vault_root).encode()).hexdigest()[:12]
    db_path = config.db_path(vault_hash)

    if not db_path.exists():
        raise FileNotFoundError(
            f"No graph found at {db_path}. Run: keppi build {vault_path}"
        )

    from keppi.graph.storage import load_graph, open_db

    conn = open_db(db_path)
    graph = load_graph(conn)
    _state[key] = (graph, conn, config)
    return graph, conn, config


def _real_nodes(graph: nx.DiGraph) -> set[str]:
    return {n for n in graph.nodes if not str(n).startswith("__broken__")}


# ---------------------------------------------------------------------------
# Graph overview
# ---------------------------------------------------------------------------


@mcp.tool()
def get_graph_stats(vault_path: str = ".") -> dict[str, Any]:
    """Return overall graph statistics: node/edge counts, density, orphans."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    real = _real_nodes(graph)
    subgraph = graph.subgraph(real)

    edge_types: dict[str, int] = {}
    for _, _, d in subgraph.edges(data=True):
        t = d.get("type", "unknown")
        edge_types[t] = edge_types.get(t, 0) + 1

    orphans = sum(
        1
        for n in real
        if not any(d in real for _, d in graph.out_edges(n))
        and not any(s in real for s, _ in graph.in_edges(n))
    )

    n = subgraph.number_of_nodes()
    e = subgraph.number_of_edges()
    density = (e / (n * (n - 1))) if n > 1 else 0.0

    return {
        "node_count": n,
        "edge_count": e,
        "orphan_count": orphans,
        "density": round(density, 6),
        "edge_types": edge_types,
    }


@mcp.tool()
def query_node(note: str, vault_path: str = ".") -> dict[str, Any]:
    """Get full details for a note: metadata, outbound and inbound edges."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.blast_radius import find_node_by_title

    node = find_node_by_title(graph, note, case_sensitive=config.links.case_sensitive)
    if node is None:
        return {"error": f"Note not found: {note!r}"}

    nd = dict(graph.nodes[node])
    try:
        nd["tags"] = json.loads(nd.get("tags", "[]"))
    except (json.JSONDecodeError, TypeError):
        nd["tags"] = []

    real = _real_nodes(graph)
    outbound = [
        {"target": d, "title": graph.nodes.get(d, {}).get("title", d), "type": data.get("type"), "weight": data.get("weight")}
        for _, d, data in graph.out_edges(node, data=True)
        if d in real
    ]
    inbound = [
        {"source": s, "title": graph.nodes.get(s, {}).get("title", s), "type": data.get("type"), "weight": data.get("weight")}
        for s, _, data in graph.in_edges(node, data=True)
        if s in real
    ]

    return {
        "path": node,
        "title": nd.get("title", node),
        "tags": nd.get("tags", []),
        "type": nd.get("type", ""),
        "updated": nd.get("updated", ""),
        "word_count": nd.get("word_count", 0),
        "outbound_edges": outbound,
        "inbound_edges": inbound,
    }


# ---------------------------------------------------------------------------
# Traversal & paths
# ---------------------------------------------------------------------------


@mcp.tool()
def blast_radius(
    note: str,
    depth: int = 2,
    threshold: float = 0.3,
    direction: str = "both",
    vault_path: str = ".",
) -> dict[str, Any]:
    """BFS impact analysis: which notes are affected if this one changes?"""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.blast_radius import compute_blast_radius, find_node_by_title

    node = find_node_by_title(graph, note, case_sensitive=config.links.case_sensitive)
    if node is None:
        return {"error": f"Note not found: {note!r}"}

    results = compute_blast_radius(graph, node, depth=depth, threshold=threshold, direction=direction)
    return {
        "count": len(results),
        "seed": node,
        "results": [
            {"path": r.path, "title": r.title, "relevance": r.relevance, "distance": r.distance, "edge_types": r.edge_types}
            for r in results
        ],
    }


@mcp.tool()
def traverse_graph(note: str, depth: int = 2, vault_path: str = ".") -> dict[str, Any]:
    """Expand the graph from a note to depth N, collecting all reachable nodes."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from collections import deque

    from keppi.analysis.blast_radius import find_node_by_title

    node = find_node_by_title(graph, note, case_sensitive=config.links.case_sensitive)
    if node is None:
        return {"error": f"Note not found: {note!r}"}

    real = _real_nodes(graph)
    # Structural-only traversal — tag_overlap creates false paths
    structural_types = {"wikilink", "related_to", "embed", "semantic_similarity"}
    visited: dict[str, int] = {node: 0}
    queue: deque[tuple[str, int]] = deque([(node, 0)])

    while queue:
        current, dist = queue.popleft()
        if dist >= depth:
            continue
        for _, dst, data in graph.out_edges(current, data=True):
            if dst in real and dst not in visited and data.get("type") in structural_types:
                visited[dst] = dist + 1
                queue.append((dst, dist + 1))
        for src, _, data in graph.in_edges(current, data=True):
            if src in real and src not in visited and data.get("type") in structural_types:
                visited[src] = dist + 1
                queue.append((src, dist + 1))

    nodes = [
        {"path": n, "title": graph.nodes[n].get("title", n), "distance": d}
        for n, d in visited.items()
        if n != node
    ]
    nodes.sort(key=lambda x: (x["distance"], x["title"]))

    return {"node_count": len(nodes), "seed": node, "nodes": nodes}


@mcp.tool()
def find_path(source: str, target: str, vault_path: str = ".") -> dict[str, Any]:
    """Find the shortest path between two notes."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.blast_radius import find_node_by_title

    src_node = find_node_by_title(graph, source, case_sensitive=config.links.case_sensitive)
    dst_node = find_node_by_title(graph, target, case_sensitive=config.links.case_sensitive)

    if src_node is None:
        return {"error": f"Note not found: {source!r}"}
    if dst_node is None:
        return {"error": f"Note not found: {target!r}"}

    try:
        # Structural-only path by default — tag_overlap creates false bridges
        structural_types = {"wikilink", "related_to", "embed", "semantic_similarity"}
        structural = nx.Graph()
        structural.add_nodes_from(_real_nodes(graph))
        for u, v, d in graph.edges(data=True):
            if d.get("type") in structural_types:
                structural.add_edge(u, v)
        path_nodes = nx.shortest_path(structural, src_node, dst_node)
    except nx.NetworkXNoPath:
        return {"error": f"No path between {source!r} and {target!r}"}
    except nx.NodeNotFound:
        return {"error": "One or both nodes not in graph"}

    return {
        "hops": len(path_nodes) - 1,
        "path": [graph.nodes[n].get("title", n) for n in path_nodes],
        "path_nodes": path_nodes,
    }


# ---------------------------------------------------------------------------
# Context & search
# ---------------------------------------------------------------------------


@mcp.tool()
def context_pack(topic: str, token_budget: int = 4000, depth: int = 2, vault_path: str = ".") -> dict[str, Any]:
    """Build a minimal token-budgeted reading set for a topic."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.context_pack import build_context_pack

    pack = build_context_pack(graph, conn, topic, token_budget=token_budget, depth=depth)
    return {
        "entry_count": len(pack.entries),
        "seed_note": pack.seed_note,
        "estimated_tokens": pack.total_tokens,
        "token_budget": pack.token_budget,
        "entries": [
            {
                "path": e.path,
                "title": e.title,
                "relevance": e.relevance,
                "estimated_tokens": e.estimated_tokens,
                "tags": e.tags,
            }
            for e in pack.entries
        ],
    }


@mcp.tool()
def semantic_search(
    query: str,
    limit: int = 10,
    subfolder: str = "",
    vault_path: str = ".",
) -> dict[str, Any]:
    """
    Find notes semantically similar to a natural language query.

    USE THIS BEFORE keyword_search. It understands meaning and synonyms —
    one call replaces 2-3 trial-and-error keyword searches.

    subfolder: restrict to any specific subdirectory (e.g. "wiki", "projects/active").
    Leave empty to search the full vault.

    Distance interpretation:
    - < 0.3 (strong): high confidence match — read this note first
    - 0.3–0.5 (moderate): likely relevant — worth reading
    - > 0.5 (weak): loosely related — proceed to keyword_search instead

    Returns {"error": "embeddings_not_built"} with instructions if keppi embed
    has not been run yet. Check get_embed_status() if unsure.
    """
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    # Check embeddings exist
    try:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM vec_embeddings"
        ).fetchone()["c"]
        if count == 0:
            return {
                "error": "embeddings_not_built",
                "message": f"No embeddings found. Run: keppi embed {vault_path}",
                "hint": "After keppi embed completes, semantic_search will work.",
            }
    except Exception:
        return {
            "error": "embeddings_not_built",
            "message": f"Embeddings table not found. Run: keppi embed {vault_path}",
        }

    from keppi.search.providers import get_provider
    from keppi.search.semantic import semantic_search as _search

    search_subfolder = subfolder or config.vault.wiki_subfolder or None

    try:
        provider = get_provider(config)
        results = _search(conn, query, provider, limit=limit, subfolder=search_subfolder)
    except Exception as e:
        return {"error": f"Semantic search failed: {e}"}

    result_list = [
        {
            "path": r.path,
            "title": r.title,
            "distance": round(r.distance, 4),
            "match_strength": r.match_context,
        }
        for r in results
    ]

    return {
        "count": len(results),
        "query": query,
        "scope": search_subfolder or "full vault",
        "results": result_list,
    }


@mcp.tool()
def get_embed_status(vault_path: str = ".") -> dict[str, Any]:
    """
    Check embedding coverage: how many notes have embeddings vs total.
    Call this before semantic_search to verify embeddings are ready.
    Returns ready_for_semantic_search: bool and action_needed guidance.
    """
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    total = conn.execute("SELECT COUNT(*) as c FROM nodes").fetchone()["c"]

    try:
        total_chunks = conn.execute(
            "SELECT COUNT(*) as c FROM vec_embeddings"
        ).fetchone()["c"]
        # Count unique notes by stripping ::N chunk suffix
        embedded = conn.execute(
            "SELECT COUNT(DISTINCT CASE WHEN INSTR(path, '::') > 0 "
            "THEN SUBSTR(path, 1, INSTR(path, '::') - 1) ELSE path END) as c "
            "FROM vec_embeddings"
        ).fetchone()["c"]
        needs_rebuild = conn.execute(
            "SELECT value FROM meta WHERE key='embed_needs_rebuild'"
        ).fetchone()
        stored_dim = conn.execute(
            "SELECT value FROM meta WHERE key='embed_dimension'"
        ).fetchone()
    except Exception:
        total_chunks = 0
        embedded = 0
        needs_rebuild = None
        stored_dim = None

    coverage = round((embedded / total * 100), 1) if total else 0.0

    return {
        "total_notes": total,
        "embedded_notes": embedded,
        "total_chunks": total_chunks,
        "coverage_percent": coverage,
        "needs_rebuild": bool(needs_rebuild and needs_rebuild["value"] == "1"),
        "stored_dimension": int(stored_dim["value"]) if stored_dim else None,
        "configured_provider": config.embed.provider,
        "configured_model": config.embed.model,
        "ready_for_semantic_search": embedded > 0 and coverage >= 80.0,
        "action_needed": (
            f"Run: keppi embed {vault_path}"
            if embedded == 0
            else (
                f"Run: keppi embed {vault_path} "
                f"({total - embedded} notes not yet embedded)"
                if coverage < 100
                else None
            )
        ),
    }


@mcp.tool()
def keyword_search(query: str, limit: int = 20, vault_path: str = ".") -> dict[str, Any]:
    """Search notes by keyword across title, tags, headings, and body."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.search.keyword import keyword_search as _search

    results = _search(conn, query, limit=limit)
    return {
        "count": len(results),
        "results": [
            {"path": r.path, "title": r.title, "score": r.score, "fields": r.match_fields, "context": r.match_context}
            for r in results
        ],
    }


@mcp.tool()
def tag_search(tag: str, vault_path: str = ".") -> dict[str, Any]:
    """Find all notes with a specific tag."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    matches = []
    tag_lower = tag.lower()
    for node, data in graph.nodes(data=True):
        if str(node).startswith("__broken__"):
            continue
        try:
            tags = json.loads(data.get("tags", "[]"))
        except (json.JSONDecodeError, TypeError):
            tags = []
        if any(str(t).lower() == tag_lower for t in tags):
            matches.append({"path": node, "title": data.get("title", node)})

    matches.sort(key=lambda x: x["title"])
    return {"count": len(matches), "tag": tag, "notes": matches}


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@mcp.tool()
def find_hubs(top_n: int = 10, vault_path: str = ".") -> dict[str, Any]:
    """Return top notes by degree centrality (most connections)."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.centrality import find_hubs as _find_hubs

    results = _find_hubs(graph, top_n=top_n)
    return {
        "count": len(results),
        "hubs": [{"path": r.path, "title": r.title, "centrality_score": r.score} for r in results],
    }


@mcp.tool()
def find_orphans(vault_path: str = ".") -> dict[str, Any]:
    """Return notes with zero inbound and zero outbound connections."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.centrality import find_orphans as _find_orphans

    results = _find_orphans(graph)
    return {
        "count": len(results),
        "orphans": [{"path": r.path, "title": r.title} for r in results],
    }


@mcp.tool()
def detect_communities(min_size: int = 2, vault_path: str = ".") -> dict[str, Any]:
    """Detect topical clusters using the Louvain algorithm."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.communities import detect_communities as _detect

    comms = _detect(graph, min_size=min_size)
    return {
        "count": len(comms),
        "communities": [
            {
                "id": c.id,
                "size": c.size,
                "top_tags": c.top_tags,
                "representative": graph.nodes.get(c.representative, {}).get("title", c.representative),
            }
            for c in comms
        ],
    }


@mcp.tool()
def detect_gaps(max_bridge_edges: int = 2, min_shared_tags: int = 1, vault_path: str = ".") -> dict[str, Any]:
    """Find structural gaps: community pairs with shared tags but few bridge edges."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.communities import detect_communities as _detect_comms
    from keppi.analysis.gaps import detect_gaps as _detect_gaps

    comms = _detect_comms(graph, min_size=2)
    gaps = _detect_gaps(graph, comms, max_bridge_edges=max_bridge_edges, min_shared_tags=min_shared_tags)
    return {
        "count": len(gaps),
        "gaps": [
            {
                "community_a": g.community_a_id,
                "community_b": g.community_b_id,
                "shared_tags": g.shared_tags,
                "bridge_edges": g.bridge_edge_count,
                "description": g.description,
            }
            for g in gaps
        ],
    }


@mcp.tool()
def detect_drift(stale_days: int = 30, recent_days: int = 14, vault_path: str = ".") -> dict[str, Any]:
    """Find stale notes connected to recently-updated ones."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.drift import detect_drift as _detect

    results = _detect(graph, stale_days=stale_days, recent_days=recent_days)
    return {
        "count": len(results),
        "results": [
            {
                "path": r.path,
                "title": r.title,
                "last_updated": r.last_updated,
                "days_stale": r.days_stale,
                "connected_recent": r.connected_recent,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Links & health
# ---------------------------------------------------------------------------


@mcp.tool()
def list_broken_links(vault_path: str = ".") -> dict[str, Any]:
    """Return all broken wikilinks (targets that don't exist in the vault)."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.suggestions import find_broken_links

    broken = find_broken_links(graph)
    return {"count": len(broken), "broken_links": broken}


@mcp.tool()
def suggest_links(note: str = "", top_n: int = 10, min_score: float = 0.3, vault_path: str = ".") -> dict[str, Any]:
    """Suggest missing connections based on tag overlap and shared neighbors."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.blast_radius import find_node_by_title
    from keppi.analysis.suggestions import suggest_links as _suggest

    source_node = None
    if note:
        source_node = find_node_by_title(graph, note, case_sensitive=config.links.case_sensitive)
        if source_node is None:
            return {"error": f"Note not found: {note!r}"}

    results = _suggest(graph, source=source_node, top_n=top_n, min_score=min_score)
    return {
        "count": len(results),
        "suggestions": [
            {
                "source": r.source_title,
                "source_path": r.source_path,
                "target": r.target_title,
                "target_path": r.target_path,
                "score": r.score,
                "reasons": r.reasons,
            }
            for r in results
        ],
    }


@mcp.tool()
def list_stale(days: int = 30, vault_path: str = ".") -> dict[str, Any]:
    """Return notes not modified in N days."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from datetime import date, timedelta

    cutoff = date.today() - timedelta(days=days)
    from keppi.analysis.drift import _parse_date

    stale = []
    for node, data in graph.nodes(data=True):
        if str(node).startswith("__broken__"):
            continue
        raw = data.get("updated", "")
        d = _parse_date(raw)
        if d is None or d <= cutoff:
            stale.append({"path": node, "title": data.get("title", node), "last_updated": raw or "unknown"})

    stale.sort(key=lambda x: x["last_updated"])
    return {"count": len(stale), "notes": stale}


@mcp.tool()
def get_surprising_connections(top_n: int = 10, vault_path: str = ".") -> dict[str, Any]:
    """Find unexpected high-relevance connections between distant notes."""
    try:
        graph, conn, config = _load(vault_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    from keppi.analysis.suggestions import suggest_links as _suggest

    # Surprising = high score but not already linked, filtered to distant pairs
    results = _suggest(graph, source=None, top_n=top_n * 3, min_score=0.5)

    # Build structural-only graph for distance computation
    structural_types = {"wikilink", "related_to", "embed", "semantic_similarity"}
    structural = nx.Graph()
    structural.add_nodes_from(_real_nodes(graph))
    for u, v, d in graph.edges(data=True):
        if d.get("type") in structural_types:
            structural.add_edge(u, v)

    surprising = []
    for r in results:
        try:
            dist = nx.shortest_path_length(structural, r.source_path, r.target_path)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            dist = 99
        if dist >= 3:
            surprising.append({"source": r.source_title, "target": r.target_title, "score": r.score, "distance": dist, "reasons": r.reasons})
        if len(surprising) >= top_n:
            break

    return {"count": len(surprising), "connections": surprising}


if __name__ == "__main__":
    mcp.run()
