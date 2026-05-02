"""Tests for MCP server tools (unit tests via direct function calls)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from keppi.graph.builder import GraphBuilder
from keppi.graph.storage import open_db, save_graph
from keppi.parser.config import Config
from keppi.parser.markdown import collect_markdown_files, parse_note

VAULT = Path(__file__).parent / "fixtures" / "demo_vault"


def _build_graph_and_db():
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
    return conn, builder.graph, config, db_path


class TestMCPTools:
    def setup_method(self):
        self.conn, self.graph, self.config, self.db_path = _build_graph_and_db()
        # Patch _load so MCP tools use our in-memory graph
        self._patch = patch(
            "keppi.mcp.server._load",
            return_value=(self.graph, self.conn, self.config),
        )
        self._patch.start()

    def teardown_method(self):
        self._patch.stop()
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_get_graph_stats(self):
        from keppi.mcp.server import get_graph_stats
        result = get_graph_stats()
        assert result["node_count"] > 0
        assert result["edge_count"] > 0
        assert "edge_types" in result
        assert "orphan_count" in result
        assert result["density"] >= 0

    def test_query_node_found(self):
        from keppi.mcp.server import query_node
        result = query_node("Medallion Architecture")
        assert "error" not in result
        assert result["title"] == "Medallion Architecture"
        assert "outbound_edges" in result
        assert "inbound_edges" in result

    def test_query_node_not_found(self):
        from keppi.mcp.server import query_node
        result = query_node("Definitely Nonexistent Note 99999")
        assert "error" in result

    def test_blast_radius_tool(self):
        from keppi.mcp.server import blast_radius
        result = blast_radius("Medallion Architecture", depth=2, threshold=0.3)
        assert "error" not in result
        assert result["count"] > 0
        assert len(result["results"]) > 0
        for r in result["results"]:
            assert r["relevance"] >= 0.3

    def test_blast_radius_missing_note(self):
        from keppi.mcp.server import blast_radius
        result = blast_radius("Ghost Note That Does Not Exist")
        assert "error" in result

    def test_context_pack_tool(self):
        from keppi.mcp.server import context_pack
        result = context_pack("Snowflake", token_budget=2000)
        assert result["entry_count"] > 0
        assert result["seed_note"] != ""
        assert result["estimated_tokens"] > 0

    def test_traverse_graph_tool(self):
        from keppi.mcp.server import traverse_graph
        result = traverse_graph("Databricks", depth=2)
        assert "error" not in result
        assert result["node_count"] > 0
        for node in result["nodes"]:
            assert node["distance"] <= 2

    def test_find_path_tool(self):
        from keppi.mcp.server import find_path
        result = find_path("Databricks", "Snowflake")
        assert "error" not in result
        assert result["hops"] >= 1
        assert len(result["path"]) >= 2

    def test_find_path_no_path(self):
        from keppi.mcp.server import find_path
        # orphan_note has no connections
        result = find_path("Orphan Note", "Snowflake")
        # Either not found or no path
        assert "error" in result or result.get("hops", 99) >= 1

    def test_find_hubs_tool(self):
        from keppi.mcp.server import find_hubs
        result = find_hubs(top_n=5)
        assert result["count"] > 0
        assert len(result["hubs"]) <= 5
        for hub in result["hubs"]:
            assert hub["centrality_score"] >= 0

    def test_find_orphans_tool(self):
        from keppi.mcp.server import find_orphans
        result = find_orphans()
        assert "count" in result
        assert "orphans" in result

    def test_detect_communities_tool(self):
        from keppi.mcp.server import detect_communities
        result = detect_communities(min_size=2)
        assert result["count"] >= 1
        for c in result["communities"]:
            assert c["size"] >= 2

    def test_detect_gaps_tool(self):
        from keppi.mcp.server import detect_gaps
        result = detect_gaps(max_bridge_edges=10, min_shared_tags=0)
        assert "count" in result
        assert "gaps" in result

    def test_detect_drift_tool(self):
        from keppi.mcp.server import detect_drift
        result = detect_drift(stale_days=1, recent_days=9999)
        assert "count" in result
        assert "results" in result

    def test_keyword_search_tool(self):
        from keppi.mcp.server import keyword_search
        result = keyword_search("snowflake")
        assert result["count"] > 0
        for r in result["results"]:
            assert r["score"] > 0

    def test_keyword_search_no_results(self):
        from keppi.mcp.server import keyword_search
        result = keyword_search("xyzzy_12345_nonexistent")
        assert result["count"] == 0

    def test_tag_search_tool(self):
        from keppi.mcp.server import tag_search
        result = tag_search("data-engineering")
        assert result["count"] > 0

    def test_list_broken_links_tool(self):
        from keppi.mcp.server import list_broken_links
        result = list_broken_links()
        assert result["count"] > 0

    def test_suggest_links_tool(self):
        from keppi.mcp.server import suggest_links
        result = suggest_links(top_n=10)
        assert "count" in result
        assert "suggestions" in result

    def test_list_stale_tool(self):
        from keppi.mcp.server import list_stale
        result = list_stale(days=1)
        assert "count" in result
        assert "notes" in result

    def test_get_surprising_connections_tool(self):
        from keppi.mcp.server import get_surprising_connections
        result = get_surprising_connections(top_n=10)
        assert "count" in result
        assert "connections" in result
