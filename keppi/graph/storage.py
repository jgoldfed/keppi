"""SQLite persistence for the keppi graph."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import networkx as nx

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


def open_db(db_path: Path) -> sqlite3.Connection:
    """Open (or create) a SQLite database with WAL mode."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
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
