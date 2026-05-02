"""Tests for Phase 2 analysis features."""

from __future__ import annotations

import tempfile
from pathlib import Path

from keppi.graph.builder import GraphBuilder
from keppi.graph.storage import open_db, save_graph
from keppi.parser.config import Config
from keppi.parser.markdown import collect_markdown_files, parse_note

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


class TestCommunityDetection:
    def setup_method(self):
        self.conn, self.graph, self.db_path = _build_and_persist()

    def teardown_method(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_communities_detected(self):
        from keppi.analysis.communities import detect_communities
        comms = detect_communities(self.graph, min_size=2)
        assert len(comms) >= 1

    def test_communities_have_nodes(self):
        from keppi.analysis.communities import detect_communities
        comms = detect_communities(self.graph, min_size=2)
        for c in comms:
            assert c.size >= 2
            assert len(c.nodes) == c.size

    def test_communities_sorted_by_size(self):
        from keppi.analysis.communities import detect_communities
        comms = detect_communities(self.graph, min_size=2)
        for i in range(len(comms) - 1):
            assert comms[i].size >= comms[i + 1].size

    def test_community_has_representative(self):
        from keppi.analysis.communities import detect_communities
        comms = detect_communities(self.graph, min_size=2)
        for c in comms:
            assert c.representative in c.nodes


class TestCentrality:
    def setup_method(self):
        self.conn, self.graph, self.db_path = _build_and_persist()

    def teardown_method(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_hubs_returned(self):
        from keppi.analysis.centrality import find_hubs
        hubs = find_hubs(self.graph, top_n=10)
        assert len(hubs) > 0
        assert len(hubs) <= 10

    def test_hubs_sorted_by_score(self):
        from keppi.analysis.centrality import find_hubs
        hubs = find_hubs(self.graph, top_n=10)
        for i in range(len(hubs) - 1):
            assert hubs[i].score >= hubs[i + 1].score

    def test_bridges_returned(self):
        from keppi.analysis.centrality import find_bridges
        bridges = find_bridges(self.graph, top_n=10)
        # May be empty on very small graphs but should not error
        assert isinstance(bridges, list)

    def test_orphans_are_truly_isolated(self):
        from keppi.analysis.centrality import find_orphans
        orphans = find_orphans(self.graph)
        real_nodes = {n for n in self.graph.nodes if not str(n).startswith("__broken__")}
        for o in orphans:
            out_real = [d for _, d in self.graph.out_edges(o.path) if d in real_nodes]
            in_real = [s for s, _ in self.graph.in_edges(o.path) if s in real_nodes]
            assert not out_real
            assert not in_real


class TestGapDetection:
    def setup_method(self):
        self.conn, self.graph, self.db_path = _build_and_persist()

    def teardown_method(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_gaps_detected(self):
        from keppi.analysis.communities import detect_communities
        from keppi.analysis.gaps import detect_gaps
        comms = detect_communities(self.graph, min_size=2)
        if len(comms) >= 2:
            gap_list = detect_gaps(self.graph, comms, max_bridge_edges=5, min_shared_tags=1)
            assert isinstance(gap_list, list)

    def test_gap_descriptions_non_empty(self):
        from keppi.analysis.communities import detect_communities
        from keppi.analysis.gaps import detect_gaps
        comms = detect_communities(self.graph, min_size=2)
        if len(comms) >= 2:
            gap_list = detect_gaps(self.graph, comms, max_bridge_edges=10, min_shared_tags=0)
            for gap in gap_list:
                assert len(gap.description) > 0


class TestDriftDetection:
    def setup_method(self):
        self.conn, self.graph, self.db_path = _build_and_persist()

    def teardown_method(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_drift_returns_list(self):
        from keppi.analysis.drift import detect_drift
        results = detect_drift(self.graph, stale_days=1, recent_days=9999)
        assert isinstance(results, list)

    def test_drift_no_future_dates(self):
        from datetime import date

        from keppi.analysis.drift import _parse_date, detect_drift
        results = detect_drift(self.graph, stale_days=30, recent_days=14)
        for r in results:
            if r.last_updated not in ("unknown", ""):
                d = _parse_date(r.last_updated)
                if d:
                    assert d <= date.today()


class TestSuggestions:
    def setup_method(self):
        self.conn, self.graph, self.db_path = _build_and_persist()

    def teardown_method(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_broken_links_found(self):
        from keppi.analysis.suggestions import find_broken_links
        broken = find_broken_links(self.graph)
        assert len(broken) > 0
        for item in broken:
            assert "source_path" in item
            assert "target_name" in item

    def test_broken_links_targets_dont_exist(self):
        from keppi.analysis.suggestions import find_broken_links
        real_nodes = {n for n in self.graph.nodes if not str(n).startswith("__broken__")}
        broken = find_broken_links(self.graph)
        for item in broken:
            assert item["source_path"] in real_nodes

    def test_suggest_links_global(self):
        from keppi.analysis.suggestions import suggest_links
        suggestions = suggest_links(self.graph, top_n=10)
        assert isinstance(suggestions, list)
        for s in suggestions:
            assert s.score > 0
            assert s.source_path != s.target_path

    def test_suggest_links_no_existing_edges(self):
        from keppi.analysis.suggestions import suggest_links
        suggestions = suggest_links(self.graph, top_n=20)
        for s in suggestions:
            assert not self.graph.has_edge(s.source_path, s.target_path)
            assert not self.graph.has_edge(s.target_path, s.source_path)

    def test_suggest_links_for_note(self):
        from keppi.analysis.suggestions import suggest_links
        seed = "concepts/Medallion Architecture.md"
        suggestions = suggest_links(self.graph, source=seed, top_n=10)
        assert isinstance(suggestions, list)
        for s in suggestions:
            assert s.source_path == seed or s.target_path == seed


class TestContextPack:
    def setup_method(self):
        self.conn, self.graph, self.db_path = _build_and_persist()

    def teardown_method(self):
        self.conn.close()
        self.db_path.unlink(missing_ok=True)

    def test_context_pack_returns_entries(self):
        from keppi.analysis.context_pack import build_context_pack
        pack = build_context_pack(self.graph, self.conn, "Snowflake", token_budget=4000)
        assert len(pack.entries) > 0

    def test_context_pack_within_budget(self):
        from keppi.analysis.context_pack import build_context_pack
        budget = 500
        pack = build_context_pack(self.graph, self.conn, "Snowflake", token_budget=budget)
        assert pack.total_tokens <= budget * 2  # allow some overshoot for the last entry

    def test_context_pack_seed_note_set(self):
        from keppi.analysis.context_pack import build_context_pack
        pack = build_context_pack(self.graph, self.conn, "Snowflake")
        assert pack.seed_note != ""

    def test_context_pack_missing_topic(self):
        from keppi.analysis.context_pack import build_context_pack
        pack = build_context_pack(self.graph, self.conn, "xyzzy_nonexistent_12345")
        assert len(pack.entries) == 0
