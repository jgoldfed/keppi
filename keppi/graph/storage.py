"""SQLite persistence for the keppi graph."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import networkx as nx

# Module-level cache for sqlite-vec extension load attempts.
# None = not attempted, True = loaded successfully, False = unavailable.
# Avoids repeatedly attempting to load a shared library that doesn't exist.
_VEC_LOAD_STATE: bool | None = None


def _try_load_vec(conn: sqlite3.Connection) -> bool:
    """Attempt to load sqlite-vec extension. Caches result globally."""
    global _VEC_LOAD_STATE
    if _VEC_LOAD_STATE is False:
        return False
    try:
        conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _VEC_LOAD_STATE = True
        return True
    except Exception:
        _VEC_LOAD_STATE = False
        return False


def ensure_vec_table(conn: sqlite3.Connection, dimension: int) -> bool:
    """
    Create vec_embeddings virtual table with given dimension if it doesn't exist.
    Returns True if table is ready, False if sqlite-vec is not available.

    If stored dimension in meta differs from requested dimension:
    - Set meta['embed_needs_rebuild'] = '1' FIRST (so a crash here is recoverable —
      the next call will see the flag and rebuild)
    - Drop and recreate vec_embeddings with new dimension
    - Print warning to stderr

    Crash recovery: if the process is killed between the DROP and the CREATE,
    the next ensure_vec_table call recreates the table from scratch and
    embed_all_notes sees the rebuild flag and re-embeds everything.
    """
    try:
        stored = conn.execute(
            "SELECT value FROM meta WHERE key='embed_dimension'"
        ).fetchone()

        if stored and int(stored["value"]) != dimension:
            import sys
            print(
                f"[keppi] WARNING: Embedding dimension changed "
                f"({stored['value']} → {dimension}). "
                f"Dropping and rebuilding vec_embeddings table.",
                file=sys.stderr,
            )
            # Set rebuild flag BEFORE drop — crash recovery
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) "
                "VALUES ('embed_needs_rebuild', '1')"
            )
            conn.commit()
            conn.execute("DROP TABLE IF EXISTS vec_embeddings")

        conn.execute(
            f"""CREATE VIRTUAL TABLE IF NOT EXISTS vec_embeddings USING vec0(
                path TEXT PRIMARY KEY,
                embedding float[{dimension}]
            )"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) "
            "VALUES ('embed_dimension', ?)",
            (str(dimension),),
        )
        conn.commit()
        return True
    except Exception:
        return False  # sqlite-vec not installed or vec0 unavailable

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS nodes (
    path        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    type        TEXT DEFAULT '',
    subtype     TEXT DEFAULT '',
    status      TEXT DEFAULT '',
    updated     TEXT DEFAULT '',
    tags        TEXT DEFAULT '[]',
    headings    TEXT DEFAULT '[]',
    word_count  INTEGER DEFAULT 0,
    content_hash TEXT DEFAULT '',
    parse_error TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS edges (
    src         TEXT NOT NULL,
    dst         TEXT NOT NULL,
    type        TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (src, dst, type)
);

CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_nodes_title ON nodes(title);
"""


def open_db(db_path: Path, enable_vec: bool = True) -> sqlite3.Connection:
    """Open (or create) a SQLite database with WAL mode.

    enable_vec=False only prevents the initial extension load attempt for
    this connection. If sqlite-vec was already loaded into another connection
    in the same process, _VEC_LOAD_STATE remains True — vec0 tables remain
    usable globally. This is the correct semantics for a per-connection flag.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    if enable_vec:
        _try_load_vec(conn)  # cached — only attempts shared library load once

    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def save_graph(conn: sqlite3.Connection, graph: nx.DiGraph, vault_root: str) -> None:
    """Write the entire graph to SQLite, replacing existing data."""
    cur = conn.cursor()

    cur.execute("DELETE FROM edges")
    cur.execute("DELETE FROM nodes")

    real_nodes = [(n, d) for n, d in graph.nodes(data=True) if not str(n).startswith("__broken__")]
    cur.executemany(
        """INSERT OR REPLACE INTO nodes
           (path, title, type, subtype, status, updated, tags, headings, word_count, content_hash, parse_error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                n,
                d.get("title", ""),
                d.get("type", ""),
                d.get("subtype", ""),
                d.get("status", ""),
                d.get("updated", ""),
                d.get("tags", "[]"),
                d.get("headings", "[]"),
                d.get("word_count", 0),
                d.get("content_hash", ""),
                d.get("parse_error", ""),
            )
            for n, d in real_nodes
        ],
    )

    edges = []
    for src, dst, data in graph.edges(data=True):
        edges.append((src, dst, data.get("type", "wikilink"), data.get("weight", 1.0)))
    cur.executemany(
        "INSERT OR REPLACE INTO edges (src, dst, type, weight) VALUES (?, ?, ?, ?)",
        edges,
    )

    cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('vault_root', ?)", (vault_root,))

    conn.commit()


def load_graph(conn: sqlite3.Connection) -> nx.DiGraph:
    """Load graph from SQLite into NetworkX."""
    graph = nx.DiGraph()
    cur = conn.cursor()

    for row in cur.execute("SELECT * FROM nodes"):
        graph.add_node(
            row["path"],
            title=row["title"],
            type=row["type"],
            subtype=row["subtype"],
            status=row["status"],
            updated=row["updated"],
            tags=row["tags"],
            headings=row["headings"],
            word_count=row["word_count"],
            content_hash=row["content_hash"],
            parse_error=row["parse_error"],
        )

    for row in cur.execute("SELECT * FROM edges"):
        graph.add_edge(row["src"], row["dst"], type=row["type"], weight=row["weight"])

    return graph


def get_stored_hashes(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {path: content_hash} for all nodes."""
    cur = conn.cursor()
    return {row["path"]: row["content_hash"] for row in cur.execute("SELECT path, content_hash FROM nodes")}


def upsert_node(conn: sqlite3.Connection, node_path: str, data: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO nodes
           (path, title, type, subtype, status, updated, tags, headings, word_count, content_hash, parse_error)
           VALUES (:path, :title, :type, :subtype, :status, :updated, :tags, :headings, :word_count, :content_hash, :parse_error)""",
        {
            "path": node_path,
            "title": data.get("title", ""),
            "type": data.get("type", ""),
            "subtype": data.get("subtype", ""),
            "status": data.get("status", ""),
            "updated": data.get("updated", ""),
            "tags": data.get("tags", "[]"),
            "headings": data.get("headings", "[]"),
            "word_count": data.get("word_count", 0),
            "content_hash": data.get("content_hash", ""),
            "parse_error": data.get("parse_error", ""),
        },
    )
    conn.commit()


def delete_node(conn: sqlite3.Connection, node_path: str) -> None:
    conn.execute("DELETE FROM nodes WHERE path = ?", (node_path,))
    conn.execute("DELETE FROM edges WHERE src = ? OR dst = ?", (node_path, node_path))
    conn.commit()


def upsert_edges_for_node(conn: sqlite3.Connection, node_path: str, edges: list[tuple]) -> None:
    """Replace all outgoing edges for node_path."""
    conn.execute("DELETE FROM edges WHERE src = ?", (node_path,))
    conn.executemany(
        "INSERT OR REPLACE INTO edges (src, dst, type, weight) VALUES (?, ?, ?, ?)",
        edges,
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None
