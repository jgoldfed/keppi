"""Incremental graph update via SHA-256 content hashing."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import networkx as nx

from keppi.graph.builder import GraphBuilder
from keppi.graph.storage import (
    delete_node,
    get_stored_hashes,
    upsert_edges_for_node,
    upsert_node,
)
from keppi.parser.config import Config
from keppi.parser.markdown import ParsedNote, collect_markdown_files, parse_note


def incremental_update(
    conn: sqlite3.Connection,
    graph: nx.DiGraph,
    config: Config,
    *,
    verbose: bool = False,
) -> dict[str, int]:
    """
    Compare current files against stored hashes; re-parse only changed/new files.
    Returns counts: {added, updated, deleted, unchanged}.
    """
    vault_root = config.vault_root()
    stored = get_stored_hashes(conn)

    current_files = collect_markdown_files(
        vault_root,
        config.vault.file_extensions,
        config.vault.exclude_dirs,
        config.vault.exclude_patterns,
    )
    current_paths = {f.relative_to(vault_root).as_posix(): f for f in current_files}

    # Build a temporary builder seeded with existing title/alias maps from the graph
    builder = _seed_builder(graph, config)

    counts = {"added": 0, "updated": 0, "deleted": 0, "unchanged": 0}
    notes_to_process: list[ParsedNote] = []

    for rel_path, filepath in current_paths.items():
        stored_hash = stored.get(rel_path)
        # Quick hash check — read first 8KB for speed
        note = parse_note(
            filepath,
            vault_root,
            type_field=config.frontmatter.type_field,
            subtype_field=config.frontmatter.subtype_field,
            status_field=config.frontmatter.status_field,
            updated_field=config.frontmatter.updated_field,
            tags_field=config.frontmatter.tags_field,
            aliases_field=config.frontmatter.aliases_field,
            related_field=config.frontmatter.related_field,
            case_sensitive=config.links.case_sensitive,
        )

        if stored_hash is None:
            counts["added"] += 1
            notes_to_process.append(note)
        elif note.content_hash != stored_hash:
            counts["updated"] += 1
            notes_to_process.append(note)
        else:
            counts["unchanged"] += 1

    # Delete removed files
    for rel_path in stored:
        if rel_path not in current_paths:
            counts["deleted"] += 1
            graph.remove_node(rel_path) if graph.has_node(rel_path) else None
            delete_node(conn, rel_path)
            # Remove all chunks for deleted note (non-blocking)
            try:
                conn.execute(
                    "DELETE FROM vec_embeddings WHERE path = ? OR path LIKE ?",
                    (rel_path, rel_path + "::%"),
                )
                conn.commit()
            except Exception:
                pass

    # Add new/changed notes to the graph and builder
    for note in notes_to_process:
        builder.add_note(note)
        # Update graph node
        builder.add_note(note)  # idempotent in networkx

    # Re-add edges for changed notes (after all nodes are in the builder)
    for note in notes_to_process:
        builder.add_edges(note)
        node_data = graph.nodes.get(note.path, {})
        node_data.update(builder.graph.nodes.get(note.path, {}))
        upsert_node(conn, note.path, node_data)

        # Auto-embed on note create/update (non-blocking)
        if config.embed.auto_embed:
            try:
                from keppi.graph.builder import _read_note_body, chunk_text
                from keppi.graph.storage import ensure_vec_table
                from keppi.search.providers import get_provider
                from keppi.search.semantic import embed_and_store

                if ensure_vec_table(conn, config.embed.dimension):
                    text = _read_note_body(vault_root, note.path)
                    if not text:
                        text = node_data.get("title", note.path)
                    provider = get_provider(config)
                    # Delete old chunks before re-embedding
                    conn.execute(
                        "DELETE FROM vec_embeddings WHERE path = ? OR path LIKE ?",
                        (note.path, note.path + "::%"),
                    )
                    conn.commit()
                    for ci, chunk in enumerate(chunk_text(text)):
                        try:
                            embed_and_store(conn, f"{note.path}::{ci}", chunk, provider)
                        except Exception:
                            pass
            except Exception as e:
                import logging
                logging.getLogger("keppi.embed").debug(
                    "incremental auto-embed failed for %s: %s", note.path, e
                )
                # never block incremental update

        # Persist outgoing edges
        out_edges = [
            (note.path, dst, data.get("type", "wikilink"), data.get("weight", 1.0))
            for _, dst, data in builder.graph.out_edges(note.path, data=True)
        ]
        upsert_edges_for_node(conn, note.path, out_edges)

    # Merge builder graph back into main graph
    for n, d in builder.graph.nodes(data=True):
        graph.add_node(n, **d)
    for src, dst, d in builder.graph.edges(data=True):
        graph.add_edge(src, dst, **d)

    return counts


def _seed_builder(graph: nx.DiGraph, config: Config) -> GraphBuilder:
    """Create a GraphBuilder pre-seeded with existing node titles from the graph."""
    builder = GraphBuilder(config)
    for node, data in graph.nodes(data=True):
        if str(node).startswith("__broken__"):
            continue
        title = data.get("title", Path(node).stem)
        key = title.lower() if not config.links.case_sensitive else title
        builder._title_to_path[key] = node
        stem = Path(node).stem
        stem_key = stem.lower() if not config.links.case_sensitive else stem
        builder._stem_to_path[stem_key] = node
    return builder
