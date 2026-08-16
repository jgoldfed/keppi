"""Compute semantic_similarity edges from embeddings using cosine similarity.

This is the meaningful replacement for tag_overlap edges. Instead of
"these notes share a tag," it computes "these notes are about similar things"
using the embedding vectors already stored for semantic search.

Algorithm:
1. Load all note-level embeddings (average chunks for multi-chunk notes)
2. Normalize vectors, compute cosine similarity via dot product
3. For each note, find top-K most similar notes above a threshold
4. Add semantic_similarity edges to the graph

Complexity: O(N²) for the full similarity matrix, but using numpy dot product
on 768-dim vectors this is fast — ~2K notes × 768 dims = ~3M floats, dot product
is a single matrix multiply.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np


def compute_semantic_edges(
    conn: sqlite3.Connection,
    graph,
    *,
    min_similarity: float = 0.65,
    max_edges_per_node: int = 15,
    weight: float = 0.8,
) -> dict[str, int]:
    """
    Add semantic_similarity edges to graph based on embedding cosine similarity.

    Args:
        conn: SQLite connection with vec_embeddings table
        graph: NetworkX DiGraph to add edges to
        min_similarity: minimum cosine similarity to create an edge (0-1)
        max_edges_per_node: cap edges per node to prevent hub explosion
        weight: base weight for semantic_similarity edges

    Returns:
        {"edges_added": N, "notes_compared": N, "pairs_above_threshold": N}
    """
    # Load note-level embeddings: average chunks for multi-chunk notes
    rows = conn.execute(
        "SELECT path, embedding FROM vec_embeddings"
    ).fetchall()

    if not rows:
        return {"edges_added": 0, "notes_compared": 0, "pairs_above_threshold": 0}

    # Aggregate chunk embeddings into note-level vectors (mean of chunks)
    import struct
    note_vectors: dict[str, list[np.ndarray]] = {}
    for row in rows:
        chunk_path = row["path"]
        sep = chunk_path.find("::")
        note_path = chunk_path[:sep] if sep != -1 else chunk_path

        # Deserialize float32 vector
        raw = row["embedding"]
        dim = len(raw) // 4
        vec = np.frombuffer(raw, dtype=np.float32, count=dim)
        note_vectors.setdefault(note_path, []).append(vec)

    # Average chunks per note, build matrix
    note_paths = list(note_vectors.keys())
    n = len(note_paths)
    if n < 2:
        return {"edges_added": 0, "notes_compared": n, "pairs_above_threshold": 0}

    # Build index: note_path -> position in matrix
    path_to_idx = {p: i for i, p in enumerate(note_paths)}

    # Get dimension from first vector
    dim = len(note_vectors[note_paths[0]][0])
    matrix = np.zeros((n, dim), dtype=np.float32)

    for i, path in enumerate(note_paths):
        chunks = note_vectors[path]
        matrix[i] = np.mean(chunks, axis=0)

    # Normalize rows to unit vectors for cosine similarity
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1  # avoid division by zero
    normalized = matrix / norms

    # Compute cosine similarity: dot product of normalized vectors
    # This is a single matrix multiply — fast even for 2K+ notes
    sim_matrix = normalized @ normalized.T  # (N, N) cosine similarity matrix

    # Extract candidate pairs above threshold
    # Use upper triangle to avoid self-pairs and duplicates
    upper_indices = np.triu_indices(n, k=1)
    similarities = sim_matrix[upper_indices]

    # Filter by threshold
    above_mask = similarities >= min_similarity
    pair_indices_i = upper_indices[0][above_mask]
    pair_indices_j = upper_indices[1][above_mask]
    pair_sims = similarities[above_mask]

    pairs_above = len(pair_sims)

    # Build adjacency for per-node capping
    adj: dict[int, list[tuple[int, float]]] = {}
    for i, j, sim in zip(pair_indices_i, pair_indices_j, pair_sims):
        adj.setdefault(int(i), []).append((int(j), float(sim)))
        adj.setdefault(int(j), []).append((int(i), float(sim)))

    # Cap per node: keep top N strongest
    kept_pairs: set[frozenset] = set()
    for node_idx, neighbors in adj.items():
        neighbors.sort(key=lambda x: -x[1])
        for neighbor_idx, sim in neighbors[:max_edges_per_node]:
            kept_pairs.add(frozenset((node_idx, neighbor_idx)))

    # Add edges to graph
    edges_added = 0
    real_nodes = {n for n in graph.nodes if not str(n).startswith("__broken__")}

    for i, j, sim in zip(pair_indices_i, pair_indices_j, pair_sims):
        if frozenset((int(i), int(j))) not in kept_pairs:
            continue
        path_a = note_paths[int(i)]
        path_b = note_paths[int(j)]
        if path_a not in real_nodes or path_b not in real_nodes:
            continue
        edge_weight = weight * sim
        # Add bidirectional edges
        if graph.has_edge(path_a, path_b):
            existing = graph[path_a][path_b]
            if existing.get("weight", 0) < edge_weight:
                graph[path_a][path_b]["type"] = "semantic_similarity"
                graph[path_a][path_b]["weight"] = edge_weight
        else:
            graph.add_edge(path_a, path_b, type="semantic_similarity", weight=edge_weight)
        if graph.has_edge(path_b, path_a):
            existing = graph[path_b][path_a]
            if existing.get("weight", 0) < edge_weight:
                graph[path_b][path_a]["type"] = "semantic_similarity"
                graph[path_b][path_a]["weight"] = edge_weight
        else:
            graph.add_edge(path_b, path_a, type="semantic_similarity", weight=edge_weight)
        edges_added += 1

    return {
        "edges_added": edges_added,
        "notes_compared": n,
        "pairs_above_threshold": pairs_above,
    }