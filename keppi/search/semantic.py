"""Semantic search using sqlite-vec virtual table.

NOTE: vec_embeddings.path joins to nodes.path. This assumes the existing
schema where nodes.path is the primary key. If the nodes schema changes
to a surrogate ID, this JOIN must be updated.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass
class SemanticResult:
    path: str
    title: str
    distance: float
    match_context: str


def embed_and_store(
    conn: sqlite3.Connection,
    path: str,
    text: str,
    provider,
) -> None:
    """Generate embedding and upsert into vec_embeddings. Raises on failure.

    Validates that the returned vector dimension matches config.embed.dimension
    before insert — sqlite-vec's binding error is unhelpful, this surfaces a
    clear cause.
    """
    from keppi.search.providers import serialize_vector
    vec = provider.embed(text)
    expected = provider.config.embed.dimension
    if len(vec) != expected:
        raise RuntimeError(
            f"Embedding dimension mismatch: provider returned {len(vec)} "
            f"but config.embed.dimension is {expected}. "
            f"Update keppi.toml or change the model."
        )
    conn.execute(
        "INSERT OR REPLACE INTO vec_embeddings (path, embedding) VALUES (?, ?)",
        (path, serialize_vector(vec)),
    )
    conn.commit()


def semantic_search(
    conn: sqlite3.Connection,
    query: str,
    provider,
    *,
    limit: int = 10,
    path_prefix: Optional[str] = None,
) -> list[SemanticResult]:
    """
    KNN semantic search. Returns [] gracefully if vec_embeddings does not exist
    or any provider failure occurs. path_prefix restricts results to notes whose
    path starts with this string.
    """
    from keppi.search.providers import serialize_vector

    try:
        query_vec = provider.embed(query)
        query_bytes = serialize_vector(query_vec)

        if path_prefix:
            rows = conn.execute(
                """
                SELECT v.path, n.title, v.distance
                FROM vec_embeddings v
                JOIN nodes n ON v.path = n.path
                WHERE v.embedding MATCH ? AND k = ?
                  AND n.path LIKE ?
                ORDER BY v.distance
                """,
                (query_bytes, limit, path_prefix + "%"),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT v.path, n.title, v.distance
                FROM vec_embeddings v
                JOIN nodes n ON v.path = n.path
                WHERE v.embedding MATCH ? AND k = ?
                ORDER BY v.distance
                """,
                (query_bytes, limit),
            ).fetchall()

        return [
            SemanticResult(
                path=r["path"],
                title=r["title"] or r["path"],
                distance=r["distance"],
                match_context=(
                    "strong match" if r["distance"] < 0.3 else
                    "moderate match" if r["distance"] < 0.5 else
                    "weak match"
                ),
            )
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []  # vec_embeddings table doesn't exist yet
    except Exception:
        return []  # any provider failure — degrade gracefully
