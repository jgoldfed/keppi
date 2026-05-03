"""Tests for embed_all_notes and _read_note_body."""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from keppi.graph.builder import _read_note_body, embed_all_notes
from keppi.parser.config import Config


def _make_conn():
    """In-memory SQLite with nodes + meta tables (no vec_embeddings)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE nodes (
            path TEXT PRIMARY KEY,
            title TEXT,
            headings TEXT DEFAULT '[]'
        );
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE vec_embeddings (
            path TEXT PRIMARY KEY,
            embedding BLOB
        );
    """)
    conn.commit()
    return conn


def _make_provider(vec_size: int = 4):
    config = Config()
    config.embed.dimension = vec_size
    provider = MagicMock()
    provider.embed.return_value = [0.1] * vec_size
    provider.embed_batch.side_effect = lambda texts: [[0.1] * vec_size for _ in texts]
    provider.config = config
    return provider


class TestReadNoteBody:
    def test_reads_body_from_disk(self, tmp_path):
        note = tmp_path / "note.md"
        note.write_text("Hello world content", encoding="utf-8")
        result = _read_note_body(tmp_path, "note.md")
        assert result == "Hello world content"

    def test_strips_frontmatter(self, tmp_path):
        note = tmp_path / "note.md"
        note.write_text("---\nkey: val\ntitle: My Note\n---\nThis is the body.", encoding="utf-8")
        result = _read_note_body(tmp_path, "note.md")
        assert result == "This is the body."
        assert "key: val" not in result

    def test_returns_empty_when_file_missing(self, tmp_path):
        result = _read_note_body(tmp_path, "does_not_exist.md")
        assert result == ""

    def test_no_frontmatter_returns_full_text(self, tmp_path):
        note = tmp_path / "note.md"
        note.write_text("Just plain content.", encoding="utf-8")
        result = _read_note_body(tmp_path, "note.md")
        assert result == "Just plain content."

    def test_returns_full_text_without_truncation(self, tmp_path):
        note = tmp_path / "note.md"
        long_text = "x" * 10000
        note.write_text(long_text, encoding="utf-8")
        result = _read_note_body(tmp_path, "note.md")
        assert len(result) == 10000


class TestEmbedAllNotes:
    def test_reads_body_from_disk(self, tmp_path):
        """embed_all_notes uses file body, not just title."""
        conn = _make_conn()
        conn.execute("INSERT INTO nodes (path, title, headings) VALUES (?, ?, ?)",
                     ("note.md", "My Note", "[]"))
        conn.commit()

        note_file = tmp_path / "note.md"
        note_file.write_text("The full note body content.", encoding="utf-8")

        provider = _make_provider()
        result = embed_all_notes(conn, provider, tmp_path)

        assert result["embedded"] == 1
        assert result["errors"] == 0
        # Provider should have been called with the body content
        call_text = provider.embed_batch.call_args[0][0][0]
        assert "full note body" in call_text

    def test_strips_frontmatter(self, tmp_path):
        """Frontmatter is stripped before passing to provider."""
        conn = _make_conn()
        conn.execute("INSERT INTO nodes (path, title, headings) VALUES (?, ?, ?)",
                     ("note.md", "Title", "[]"))
        conn.commit()

        note_file = tmp_path / "note.md"
        note_file.write_text("---\ntitle: Title\n---\nBody text only.", encoding="utf-8")

        provider = _make_provider()
        embed_all_notes(conn, provider, tmp_path)

        call_text = provider.embed_batch.call_args[0][0][0]
        assert "Body text only." in call_text
        assert "title: Title" not in call_text

    def test_falls_back_to_title_when_file_missing(self, tmp_path):
        """When file doesn't exist, embeds title + headings instead."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO nodes (path, title, headings) VALUES (?, ?, ?)",
            ("missing.md", "My Title", '["Heading 1"]'),
        )
        conn.commit()

        provider = _make_provider()
        result = embed_all_notes(conn, provider, tmp_path)

        assert result["embedded"] == 1
        call_text = provider.embed_batch.call_args[0][0][0]
        assert "My Title" in call_text

    def test_skips_already_embedded(self, tmp_path):
        """force=False skips notes already in vec_embeddings."""
        conn = _make_conn()
        conn.execute("INSERT INTO nodes (path, title, headings) VALUES (?, ?, ?)",
                     ("note.md", "Note", "[]"))
        conn.execute("INSERT INTO vec_embeddings (path, embedding) VALUES (?, ?)",
                     ("note.md", b"\x00" * 16))
        conn.commit()

        provider = _make_provider()
        result = embed_all_notes(conn, provider, tmp_path, force=False)

        assert result["skipped"] == 1
        assert result["embedded"] == 0
        provider.embed.assert_not_called()

    def test_force_reembeds_all(self, tmp_path):
        """force=True re-embeds notes already in vec_embeddings."""
        conn = _make_conn()
        note_file = tmp_path / "note.md"
        note_file.write_text("Some content", encoding="utf-8")

        conn.execute("INSERT INTO nodes (path, title, headings) VALUES (?, ?, ?)",
                     ("note.md", "Note", "[]"))
        conn.execute("INSERT INTO vec_embeddings (path, embedding) VALUES (?, ?)",
                     ("note.md", b"\x00" * 16))
        conn.commit()

        provider = _make_provider()
        result = embed_all_notes(conn, provider, tmp_path, force=True)

        assert result["embedded"] == 1
        provider.embed_batch.assert_called()

    def test_error_counted_not_raised(self, tmp_path):
        """Provider failure increments errors dict, does not raise."""
        conn = _make_conn()
        conn.execute("INSERT INTO nodes (path, title, headings) VALUES (?, ?, ?)",
                     ("note.md", "Note", "[]"))
        conn.commit()

        note_file = tmp_path / "note.md"
        note_file.write_text("Content", encoding="utf-8")

        provider = MagicMock()
        provider.embed.side_effect = RuntimeError("provider exploded")
        provider.config = Config()
        provider.config.embed.dimension = 4

        result = embed_all_notes(conn, provider, tmp_path)

        assert result["errors"] == 1
        assert "note.md" in result["error_paths"]
        assert result["embedded"] == 0

    def test_rebuild_flag_forces_reembed(self, tmp_path):
        """meta['embed_needs_rebuild']='1' triggers full re-embed and clears flag."""
        conn = _make_conn()
        note_file = tmp_path / "note.md"
        note_file.write_text("Some content", encoding="utf-8")

        conn.execute("INSERT INTO nodes (path, title, headings) VALUES (?, ?, ?)",
                     ("note.md", "Note", "[]"))
        conn.execute("INSERT INTO vec_embeddings (path, embedding) VALUES (?, ?)",
                     ("note.md", b"\x00" * 16))
        conn.execute("INSERT INTO meta (key, value) VALUES ('embed_needs_rebuild', '1')")
        conn.commit()

        provider = _make_provider()
        result = embed_all_notes(conn, provider, tmp_path, force=False)

        # Should have re-embedded despite force=False because flag was set
        assert result["embedded"] == 1

        # Flag should be cleared
        row = conn.execute("SELECT value FROM meta WHERE key='embed_needs_rebuild'").fetchone()
        assert row is None

    def test_short_note_gets_single_chunk_key(self, tmp_path):
        """A note under CHUNK_SIZE chars produces exactly one row with ::0 key."""
        conn = _make_conn()
        conn.execute("INSERT INTO nodes (path, title, headings) VALUES (?, ?, ?)",
                     ("note.md", "Short Note", "[]"))
        conn.commit()
        (tmp_path / "note.md").write_text("Short content", encoding="utf-8")

        provider = _make_provider()
        result = embed_all_notes(conn, provider, tmp_path)

        rows = conn.execute("SELECT path FROM vec_embeddings").fetchall()
        assert len(rows) == 1
        assert rows[0]["path"] == "note.md::0"
        assert result["chunks"] == 1

    def test_long_note_produces_multiple_chunks(self, tmp_path):
        """A note over CHUNK_SIZE chars produces multiple vec_embeddings rows."""
        conn = _make_conn()
        conn.execute("INSERT INTO nodes (path, title, headings) VALUES (?, ?, ?)",
                     ("note.md", "Long Note", "[]"))
        conn.commit()

        long_text = "word " * 2000  # ~10000 chars, more than CHUNK_SIZE=1600
        (tmp_path / "note.md").write_text(long_text, encoding="utf-8")

        provider = _make_provider()
        result = embed_all_notes(conn, provider, tmp_path)

        assert result["embedded"] == 1
        rows = conn.execute(
            "SELECT path FROM vec_embeddings ORDER BY path"
        ).fetchall()
        paths = [r["path"] for r in rows]
        assert "note.md::0" in paths
        assert "note.md::1" in paths
        assert result["chunks"] >= 2

    def test_old_format_key_is_skipped(self, tmp_path):
        """Old-format embeddings (no ::N) cause the note to be skipped."""
        conn = _make_conn()
        conn.execute("INSERT INTO nodes (path, title, headings) VALUES (?, ?, ?)",
                     ("note.md", "Note", "[]"))
        conn.execute("INSERT INTO vec_embeddings (path, embedding) VALUES (?, ?)",
                     ("note.md", b"\x00" * 16))
        conn.commit()

        provider = _make_provider()
        result = embed_all_notes(conn, provider, tmp_path, force=False)

        assert result["skipped"] == 1
        assert result["embedded"] == 0
        provider.embed.assert_not_called()

    def test_reembed_cleans_up_old_chunks(self, tmp_path):
        """force=True replaces stale chunks and doesn't leave orphan rows."""
        conn = _make_conn()
        (tmp_path / "note.md").write_text("Short content", encoding="utf-8")
        conn.execute("INSERT INTO nodes (path, title, headings) VALUES (?, ?, ?)",
                     ("note.md", "Note", "[]"))
        # Pre-populate with two chunks (as if a longer version was previously embedded)
        conn.execute("INSERT INTO vec_embeddings (path, embedding) VALUES (?, ?)",
                     ("note.md::0", b"\x00" * 16))
        conn.execute("INSERT INTO vec_embeddings (path, embedding) VALUES (?, ?)",
                     ("note.md::1", b"\x00" * 16))
        conn.commit()

        provider = _make_provider()
        result = embed_all_notes(conn, provider, tmp_path, force=True)

        assert result["embedded"] == 1
        rows = conn.execute("SELECT path FROM vec_embeddings").fetchall()
        paths = [r["path"] for r in rows]
        # The old ::1 row should be gone; only ::0 remains for the short note
        assert paths == ["note.md::0"]
