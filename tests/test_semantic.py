"""Tests for semantic search and embed_and_store."""
from __future__ import annotations

import sqlite3
import struct
from unittest.mock import MagicMock

import pytest

from keppi.parser.config import Config


def _make_provider(vec: list[float], dimension: int | None = None):
    """Create a mock provider that returns the given vector."""
    config = Config()
    config.embed.dimension = dimension if dimension is not None else len(vec)
    provider = MagicMock()
    provider.embed.return_value = vec
    provider.config = config
    return provider


def _serialize(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


class TestEmbedAndStore:
    def test_embed_and_store_inserts_row(self):
        """embed_and_store calls INSERT OR REPLACE on vec_embeddings."""
        from keppi.search.semantic import embed_and_store

        vec = [0.1] * 4
        provider = _make_provider(vec)

        conn = MagicMock()
        embed_and_store(conn, "notes/test.md", "some text", provider)

        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        sql = call_args[0][0]
        assert "INSERT OR REPLACE INTO vec_embeddings" in sql
        params = call_args[0][1]
        assert params[0] == "notes/test.md"
        assert params[1] == _serialize(vec)
        conn.commit.assert_not_called()

    def test_embed_and_store_dimension_mismatch_raises(self):
        """Provider returning wrong-length vector raises RuntimeError with clear message."""
        from keppi.search.semantic import embed_and_store

        provider = _make_provider([0.1, 0.2], dimension=768)  # 2 vs expected 768

        conn = MagicMock()
        with pytest.raises(RuntimeError, match="dimension mismatch"):
            embed_and_store(conn, "notes/test.md", "text", provider)

        conn.execute.assert_not_called()


class _FakeRow:
    """Dict-like row for mocking sqlite3.Row in semantic search tests."""
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key: str):
        return self._data[key]


class TestSemanticSearch:
    def test_semantic_search_empty_graceful(self):
        """Returns [] when vec_embeddings table doesn't exist — no exception."""
        from keppi.search.semantic import semantic_search

        conn = MagicMock()
        conn.execute.side_effect = sqlite3.OperationalError("no such table: vec_embeddings")

        provider = _make_provider([0.1, 0.2, 0.3])
        results = semantic_search(conn, "test query", provider)
        assert results == []

    def test_semantic_search_provider_failure_graceful(self):
        """Returns [] when provider.embed raises — no exception propagates."""
        from keppi.search.semantic import semantic_search

        conn = MagicMock()
        provider = MagicMock()
        provider.embed.side_effect = RuntimeError("Ollama down")
        provider.config = Config()

        results = semantic_search(conn, "test query", provider)
        assert results == []

    def test_semantic_search_subfolder_filters(self):
        """subfolder restricts results to notes whose path starts with the prefix."""
        from keppi.search.semantic import semantic_search

        knn_result = MagicMock()
        knn_result.fetchall.return_value = [
            _FakeRow({"path": "wiki/Topic.md::0", "distance": 0.1}),
            _FakeRow({"path": "0-Inbox/Note.md::0", "distance": 0.2}),
        ]
        title_result = MagicMock()
        title_result.fetchone.return_value = _FakeRow({"title": "Topic"})

        conn = MagicMock()
        conn.execute.side_effect = [knn_result, title_result]

        provider = _make_provider([0.1] * 4)
        results = semantic_search(conn, "query", provider, limit=5, subfolder="wiki/")

        assert len(results) == 1
        assert results[0].path == "wiki/Topic.md"

    def test_semantic_search_no_subfolder_returns_all(self):
        """subfolder=None returns results from all paths."""
        from keppi.search.semantic import semantic_search

        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []

        provider = _make_provider([0.1] * 4)
        results = semantic_search(conn, "query", provider, limit=5, subfolder=None)
        assert results == []

    def test_semantic_search_deduplicates_chunks(self):
        """Multiple chunks from the same note return only the best-distance result."""
        from keppi.search.semantic import semantic_search

        knn_result = MagicMock()
        knn_result.fetchall.return_value = [
            _FakeRow({"path": "note.md::1", "distance": 0.1}),  # best chunk
            _FakeRow({"path": "note.md::0", "distance": 0.4}),  # worse chunk
            _FakeRow({"path": "other.md::0", "distance": 0.2}),
        ]
        title_note = MagicMock()
        title_note.fetchone.return_value = _FakeRow({"title": "My Note"})
        title_other = MagicMock()
        title_other.fetchone.return_value = _FakeRow({"title": "Other Note"})

        conn = MagicMock()
        conn.execute.side_effect = [knn_result, title_note, title_other]

        provider = _make_provider([0.1] * 4)
        results = semantic_search(conn, "query", provider, limit=10)

        assert len(results) == 2
        note_result = next(r for r in results if r.path == "note.md")
        assert note_result.distance == 0.1  # kept the best chunk distance
        assert note_result.title == "My Note"

    def test_semantic_search_results_sorted_by_distance(self):
        """Results are sorted ascending by distance."""
        from keppi.search.semantic import semantic_search

        knn_result = MagicMock()
        knn_result.fetchall.return_value = [
            _FakeRow({"path": "a.md::0", "distance": 0.5}),
            _FakeRow({"path": "b.md::0", "distance": 0.1}),
            _FakeRow({"path": "c.md::0", "distance": 0.3}),
        ]
        titles = [
            MagicMock(**{"fetchone.return_value": _FakeRow({"title": "B"})}),
            MagicMock(**{"fetchone.return_value": _FakeRow({"title": "C"})}),
            MagicMock(**{"fetchone.return_value": _FakeRow({"title": "A"})}),
        ]
        conn = MagicMock()
        conn.execute.side_effect = [knn_result] + titles

        provider = _make_provider([0.1] * 4)
        results = semantic_search(conn, "query", provider, limit=10)

        assert len(results) == 3
        distances = [r.distance for r in results]
        assert distances == sorted(distances)

    def test_semantic_search_old_format_keys(self):
        """Rows without ::N suffix (old format) are handled as full note paths."""
        from keppi.search.semantic import semantic_search

        knn_result = MagicMock()
        knn_result.fetchall.return_value = [
            _FakeRow({"path": "old/note.md", "distance": 0.2}),  # old format
        ]
        title_result = MagicMock()
        title_result.fetchone.return_value = _FakeRow({"title": "Old Note"})

        conn = MagicMock()
        conn.execute.side_effect = [knn_result, title_result]

        provider = _make_provider([0.1] * 4)
        results = semantic_search(conn, "query", provider, limit=5)

        assert len(results) == 1
        assert results[0].path == "old/note.md"
        assert results[0].title == "Old Note"
