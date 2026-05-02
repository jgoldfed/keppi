"""Tests for the graph builder and SQLite persistence."""

from __future__ import annotations

import tempfile
from pathlib import Path

from keppi.graph.builder import GraphBuilder
from keppi.graph.storage import get_stored_hashes, load_graph, open_db, save_graph
from keppi.parser.config import Config
from keppi.parser.markdown import collect_markdown_files, parse_note

VAULT = Path(__file__).parent / "fixtures" / "demo_vault"


def _build_full_graph(vault=VAULT) -> tuple[GraphBuilder, list]:
    config = Config()
    config.vault.path = str(vault)
    builder = GraphBuilder(config)
    files = collect_markdown_files(vault, [".md"], [".obsidian", ".git", "templates"], [])
    notes = []
    for f in files:
        note = parse_note(f, vault)
        builder.add_note(note)
        notes.append(note)
    for note in notes:
        builder.add_edges(note)
    builder.compute_tag_edges()
    return builder, notes


class TestGraphBuilder:
    def test_nodes_created(self):
        builder, notes = _build_full_graph()
        real = [n for n in builder.graph.nodes if not str(n).startswith("__broken__")]
        assert len(real) == len(notes)

    def test_wikilink_edges(self):
        builder, _ = _build_full_graph()
        g = builder.graph
        # Medallion Architecture → Snowflake (wikilink in related_to AND body)
        ma_path = "concepts/Medallion Architecture.md"
        snow_path = "concepts/Snowflake.md"
        assert g.has_edge(ma_path, snow_path)
        edge = g[ma_path][snow_path]
        assert edge["type"] in ("wikilink", "related_to", "embed")

    def test_related_to_bidirectional(self):
        builder, _ = _build_full_graph()
        g = builder.graph
        # related_to is bidirectional
        ma_path = "concepts/Medallion Architecture.md"
        snow_path = "concepts/Snowflake.md"
        assert g.has_edge(ma_path, snow_path)
        assert g.has_edge(snow_path, ma_path)

    def test_embed_higher_weight_than_wikilink(self):
        builder, _ = _build_full_graph()
        g = builder.graph
        embed_path = "embed_note.md"
        snow_path = "concepts/Snowflake.md"
        if g.has_edge(embed_path, snow_path):
            assert g[embed_path][snow_path]["weight"] >= 1.5

    def test_broken_link_recorded(self):
        builder, _ = _build_full_graph()
        broken_nodes = [n for n in builder.graph.nodes if str(n).startswith("__broken__")]
        assert len(broken_nodes) > 0

    def test_tag_overlap_edges(self):
        builder, _ = _build_full_graph()
        # Snowflake and Medallion Architecture share tags → should have tag_overlap edge
        g = builder.graph
        snowflake = "concepts/Snowflake.md"
        medallion = "concepts/Medallion Architecture.md"
        if g.has_node(snowflake) and g.has_node(medallion):
            assert g.has_edge(snowflake, medallion) or g.has_edge(medallion, snowflake)

    def test_orphan_note_has_no_real_edges(self):
        builder, _ = _build_full_graph()
        g = builder.graph
        orphan = "orphan_note.md"
        real_nodes = {n for n in g.nodes if not str(n).startswith("__broken__")}
        out_real = [d for _, d in g.out_edges(orphan) if d in real_nodes]
        in_real = [s for s, _ in g.in_edges(orphan) if s in real_nodes]
        assert not out_real
        assert not in_real


class TestSQLitePersistence:
    def test_save_and_reload(self):
        builder, _ = _build_full_graph()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            conn = open_db(db_path)
            save_graph(conn, builder.graph, str(VAULT))
            conn.close()

            conn2 = open_db(db_path)
            loaded = load_graph(conn2)
            conn2.close()

            real_original = {n for n in builder.graph.nodes if not str(n).startswith("__broken__")}
            real_loaded = {n for n in loaded.nodes if not str(n).startswith("__broken__")}
            assert real_original == real_loaded
        finally:
            db_path.unlink(missing_ok=True)

    def test_content_hashes_stored(self):
        builder, _ = _build_full_graph()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            conn = open_db(db_path)
            save_graph(conn, builder.graph, str(VAULT))
            hashes = get_stored_hashes(conn)
            conn.close()
            assert len(hashes) > 0
            for path, h in hashes.items():
                assert len(h) == 16
        finally:
            db_path.unlink(missing_ok=True)

    def test_node_properties_preserved(self):
        builder, _ = _build_full_graph()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            conn = open_db(db_path)
            save_graph(conn, builder.graph, str(VAULT))
            conn.close()

            conn2 = open_db(db_path)
            loaded = load_graph(conn2)
            conn2.close()

            snowflake = "concepts/Snowflake.md"
            assert loaded.has_node(snowflake)
            nd = loaded.nodes[snowflake]
            assert nd["title"] == "Snowflake"
            assert nd["type"] == "concept"
        finally:
            db_path.unlink(missing_ok=True)
