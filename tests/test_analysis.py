"""Tests for blast radius, search, and graph queries."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from keppi.analysis.blast_radius import compute_blast_radius, find_node_by_title
from keppi.graph.builder import GraphBuilder
from keppi.graph.storage import open_db, save_graph, load_graph
from keppi.parser.config import Config
from keppi.parser.markdown import parse_note, collect_markdown_files
from keppi.search.keyword import keyword_search

VAULT = Path(__file__).parent / "fixtures" / "demo_vault"


def _build_and_persist():
    config = Config()
    config.vault.path = str(VAULT)
    builder = GraphBuilder(config)
    files = collect_markdown_files(VAULT, [".md"], [".obsidian", ".git", "templates"], [])
    notes = []
    for f in files:
        note = parse_note(f, VAULT)
        builder.add_note(note)
        notes.append(note)
    for note in notes:
        builder.add_edges(note)
    builder.compute_tag_edges()

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = Path(tmp.name)
    tmp.close()
    conn = open_db(db_path)
    save_graph(conn, builder.graph, str(VAULT))
    return conn, builder.graph, db_path


class TestBlastRadius:
    def setup_method(self):
        self.conn, self.graph, self.db_path = _build_and_persist()

    def teardown_method(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_blast_radius_returns_results(self):
        results = compute_blast_radius(self.graph, "concepts/Medallion Architecture.md")
        assert len(results) > 0

    def test_blast_radius_excludes_seed(self):
        seed = "concepts/Medallion Architecture.md"
        results = compute_blast_radius(self.graph, seed)
        paths = [r.path for r in results]
        assert seed not in paths

    def test_blast_radius_relevance_sorted(self):
        results = compute_blast_radius(self.graph, "concepts/Medallion Architecture.md", depth=2)
        for i in range(len(results) - 1):
            assert results[i].relevance >= results[i + 1].relevance

    def test_blast_radius_depth_limits(self):
        results_d1 = compute_blast_radius(self.graph, "concepts/Medallion Architecture.md", depth=1)
        results_d2 = compute_blast_radius(self.graph, "concepts/Medallion Architecture.md", depth=2)
        assert len(results_d2) >= len(results_d1)

    def test_blast_radius_threshold(self):
        results_lo = compute_blast_radius(
            self.graph, "concepts/Medallion Architecture.md", threshold=0.1
        )
        results_hi = compute_blast_radius(
            self.graph, "concepts/Medallion Architecture.md", threshold=0.9
        )
        assert len(results_lo) >= len(results_hi)

    def test_blast_radius_nonexistent_returns_empty(self):
        results = compute_blast_radius(self.graph, "nonexistent/path.md")
        assert results == []


class TestFindNode:
    def setup_method(self):
        self.conn, self.graph, self.db_path = _build_and_persist()

    def teardown_method(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_find_by_exact_title(self):
        node = find_node_by_title(self.graph, "Medallion Architecture")
        assert node == "concepts/Medallion Architecture.md"

    def test_find_case_insensitive(self):
        node = find_node_by_title(self.graph, "medallion architecture", case_sensitive=False)
        assert node is not None

    def test_find_by_stem(self):
        node = find_node_by_title(self.graph, "Snowflake")
        assert node is not None

    def test_find_nonexistent_returns_none(self):
        node = find_node_by_title(self.graph, "Definitely Does Not Exist")
        assert node is None


class TestKeywordSearch:
    def setup_method(self):
        self.conn, self.graph, self.db_path = _build_and_persist()

    def teardown_method(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_search_by_title(self):
        results = keyword_search(self.conn, "Snowflake")
        titles = [r.title for r in results]
        assert "Snowflake" in titles

    def test_search_by_tag(self):
        results = keyword_search(self.conn, "data-engineering")
        assert len(results) > 0

    def test_search_returns_scored_results(self):
        results = keyword_search(self.conn, "snowflake")
        for r in results:
            assert r.score > 0

    def test_search_empty_query(self):
        results = keyword_search(self.conn, "")
        assert results == []

    def test_search_no_results(self):
        results = keyword_search(self.conn, "xyzzy_definitely_not_in_any_note_12345")
        assert results == []

    def test_search_limit(self):
        results = keyword_search(self.conn, "wiki", limit=3)
        assert len(results) <= 3
