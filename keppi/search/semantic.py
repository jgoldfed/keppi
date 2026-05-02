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
    KNN semantic search with per-note deduplication. Returns [] gracefully if
    vec_embeddings does not exist or any provider failure occurs.

    Chunk keys have the form "path::N". Multiple chunks from the same note are
    deduplicated by keeping the lowest distance. Old-format keys without ::N
    are handled transparently (treated as the full note path).

    path_prefix restricts results to notes whose path starts with this string.
    """
    from keppi.search.providers import serialize_vector

    try:
        query_vec = provider.embed(query)
        query_bytes = serialize_vector(query_vec)

        # Request more results than needed to compensate for deduplication loss
        raw_rows = conn.execute(
            """
            SELECT v.path, v.distance
            FROM vec_embeddings v
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (query_bytes, limit * 3),
        ).fetchall()

        # Deduplicate by note path (strip ::N suffix), keeping lowest distance
        seen: dict[str, float] = {}
        for row in raw_rows:
            chunk_path = row["path"]
            sep = chunk_path.find("::")
            note_path = chunk_path[:sep] if sep != -1 else chunk_path

            if path_prefix and not note_path.startswith(path_prefix):
                continue

            dist = row["distance"]
            if note_path not in seen or dist < seen[note_path]:
                seen[note_path] = dist

        # Sort by distance, truncate to limit, then fetch titles
        sorted_notes = sorted(seen.items(), key=lambda x: x[1])[:limit]

        results = []
        for note_path, distance in sorted_notes:
            title_row = conn.execute(
                "SELECT title FROM nodes WHERE path = ?", (note_path,)
            ).fetchone()
            title = (title_row["title"] if title_row else None) or note_path
            results.append(SemanticResult(
                path=note_path,
                title=title,
                distance=distance,
                match_context=(
                    "strong match" if distance < 0.3 else
                    "moderate match" if distance < 0.5 else
                    "weak match"
                ),
            ))

        return results

    except sqlite3.OperationalError:
        return []  # vec_embeddings table doesn't exist yet
    except Exception:
        return []  # any provider failure — degrade gracefully
