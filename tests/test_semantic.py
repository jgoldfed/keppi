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
        conn.commit.assert_called_once()

    def test_embed_and_store_dimension_mismatch_raises(self):
        """Provider returning wrong-length vector raises RuntimeError with clear message."""
        from keppi.search.semantic import embed_and_store

        provider = _make_provider([0.1, 0.2], dimension=768)  # 2 vs expected 768

        conn = MagicMock()
        with pytest.raises(RuntimeError, match="dimension mismatch"):
            embed_and_store(conn, "notes/test.md", "text", provider)

        conn.execute.assert_not_called()


class TestSemanticSearch:
    def test_semantic_search_empty_graceful(self):
        """Returns [] when vec_embeddings table doesn't exist — no exception."""
        from keppi.search.semantic import semantic_search

        conn = MagicMock()
        # Simulate OperationalError on the SQL query (table missing)
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

    def test_semantic_search_path_prefix_filters(self, tmp_path):
        """path_prefix=... is passed in the SQL LIKE clause."""
        from keppi.search.semantic import semantic_search

        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []

        provider = _make_provider([0.1] * 4)
        semantic_search(conn, "query", provider, limit=5, path_prefix="3-Resources/wiki/")

        # Should have called execute at least once with the path_prefix
        call_args_list = conn.execute.call_args_list
        assert len(call_args_list) >= 1
        # The SQL should contain LIKE
        sql = call_args_list[0][0][0]
        assert "LIKE" in sql
        params = call_args_list[0][0][1]
        assert any("3-Resources/wiki/" in str(p) for p in params)

    def test_semantic_search_no_prefix_omits_like(self):
        """path_prefix=None uses the simpler query without LIKE."""
        from keppi.search.semantic import semantic_search

        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []

        provider = _make_provider([0.1] * 4)
        semantic_search(conn, "query", provider, limit=5, path_prefix=None)

        sql = conn.execute.call_args[0][0]
        assert "LIKE" not in sql
