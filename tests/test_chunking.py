"""Tests for chunk_text() in keppi.graph.builder."""
from __future__ import annotations

from keppi.graph.builder import CHUNK_OVERLAP, CHUNK_SIZE, chunk_text


class TestChunkText:
    def test_short_text_returns_single_chunk(self):
        text = "x" * 100
        chunks = chunk_text(text)
        assert chunks == [text]

    def test_exactly_chunk_size_returns_single_chunk(self):
        text = "x" * CHUNK_SIZE
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_returns_multiple_chunks(self):
        text = "x" * (CHUNK_SIZE + 1)
        chunks = chunk_text(text)
        assert len(chunks) >= 2

    def test_consecutive_chunks_share_overlap(self):
        text = "abcdefghij" * 900  # 9000 chars > CHUNK_SIZE
        chunks = chunk_text(text)
        assert len(chunks) >= 2
        # Last CHUNK_OVERLAP chars of chunk N == first CHUNK_OVERLAP chars of chunk N+1
        assert chunks[0][-CHUNK_OVERLAP:] == chunks[1][:CHUNK_OVERLAP]

    def test_last_chunk_may_be_shorter(self):
        text = "x" * (CHUNK_SIZE + 100)  # just slightly over
        chunks = chunk_text(text)
        assert len(chunks) >= 2
        assert len(chunks[-1]) < CHUNK_SIZE

    def test_all_content_is_covered(self):
        # Every char should appear in at least one chunk
        text = "abcdefghij" * 1000  # 10000 chars
        chunks = chunk_text(text)
        # Reconstruct: first chunk in full, then only the non-overlapping suffix of each subsequent
        reconstructed = chunks[0]
        for prev, curr in zip(chunks, chunks[1:]):
            reconstructed += curr[CHUNK_OVERLAP:]
        assert reconstructed == text

    def test_chunk_key_format(self):
        path = "0-Inbox/Some Note.md"
        chunks = ["chunk0", "chunk1", "chunk2"]
        keys = [f"{path}::{i}" for i in range(len(chunks))]
        assert keys == [
            "0-Inbox/Some Note.md::0",
            "0-Inbox/Some Note.md::1",
            "0-Inbox/Some Note.md::2",
        ]

    def test_empty_text_returns_single_empty_chunk(self):
        chunks = chunk_text("")
        assert chunks == [""]

    def test_custom_chunk_size(self):
        text = "x" * 20
        chunks = chunk_text(text, chunk_size=10, overlap=2)
        assert len(chunks) >= 2
        assert chunks[0] == "x" * 10
