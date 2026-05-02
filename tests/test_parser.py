"""Tests for the markdown parser."""

from __future__ import annotations

from pathlib import Path

from keppi.parser.markdown import collect_markdown_files, parse_note

VAULT = Path(__file__).parent / "fixtures" / "demo_vault"


def _parse(filename: str, **kwargs):
    filepath = VAULT / filename
    return parse_note(filepath, VAULT, **kwargs)


class TestBasicParsing:
    def test_parse_entity_note(self):
        note = _parse("entities/Meridian Partners.md")
        assert note.title == "Meridian Partners"
        assert note.frontmatter_data["type"] == "entity"
        assert note.frontmatter_data["subtype"] == "company"
        assert "wiki" in note.tags
        assert "entity" in note.tags
        assert note.parse_error is None

    def test_parse_concept_note(self):
        note = _parse("concepts/Medallion Architecture.md")
        assert note.title == "Medallion Architecture"
        assert "data-engineering" in note.tags
        assert len(note.headings) >= 2

    def test_no_frontmatter(self):
        note = _parse("no_frontmatter.md")
        assert note.title == "Plain Markdown Note"
        assert note.frontmatter_data == {}
        assert note.parse_error is None
        assert "data-engineering" in note.tags  # inline tag

    def test_string_tags(self):
        """tags: career (string, not list) must parse to ['career']."""
        note = _parse("string_tags.md")
        assert "career" in note.tags

    def test_content_hash_is_hex(self):
        note = _parse("entities/Snowflake.md" if False else "concepts/Snowflake.md")
        assert len(note.content_hash) == 16
        int(note.content_hash, 16)  # must be valid hex

    def test_word_count_positive(self):
        note = _parse("concepts/Medallion Architecture.md")
        assert note.word_count > 10


class TestWikilinkParsing:
    def test_body_wikilinks(self):
        note = _parse("concepts/Medallion Architecture.md")
        assert "Fidelity" in note.wikilinks
        assert "Schwab" in note.wikilinks

    def test_embed_separate_from_wikilink(self):
        note = _parse("embed_note.md")
        assert "Snowflake" in note.embeds
        assert "Databricks" in note.wikilinks
        assert "Snowflake" not in note.wikilinks  # embed, not wikilink

    def test_alias_stripped(self):
        note = _parse("wikilink_alias.md")
        # [[Snowflake|the Snowflake platform]] → "Snowflake"
        assert "Snowflake" in note.wikilinks
        # [[Snowflake|...]] should NOT appear verbatim
        for w in note.wikilinks:
            assert "|" not in w

    def test_heading_stripped(self):
        note = _parse("wikilink_alias.md")
        # [[Medallion Architecture#Layers]] → "Medallion Architecture"
        assert "Medallion Architecture" in note.wikilinks
        for w in note.wikilinks:
            assert "#" not in w

    def test_related_to_parsed(self):
        note = _parse("entities/Meridian Partners.md")
        assert "Medallion Architecture" in note.related_to
        assert "Snowflake" in note.related_to

    def test_broken_links_recorded(self):
        note = _parse("broken_links.md")
        assert "Nonexistent Note A" in note.wikilinks
        assert "Snowflake" in note.wikilinks


class TestCollectFiles:
    def test_collect_finds_markdown(self):
        files = collect_markdown_files(VAULT, [".md"], [".obsidian", ".git", "templates"], ["*.excalidraw.md"])
        assert len(files) >= 10

    def test_collect_excludes_obsidian_dir(self):
        obsidian = VAULT / ".obsidian" / "test.md"
        obsidian.parent.mkdir(exist_ok=True)
        obsidian.write_text("test")
        try:
            files = collect_markdown_files(VAULT, [".md"], [".obsidian"], [])
            paths = [str(f) for f in files]
            assert not any(".obsidian" in p for p in paths)
        finally:
            obsidian.unlink()
            obsidian.parent.rmdir()

    def test_collect_excludes_excalidraw(self):
        exc = VAULT / "diagram.excalidraw.md"
        exc.write_text("excalidraw content")
        try:
            files = collect_markdown_files(VAULT, [".md"], [], ["*.excalidraw.md"])
            names = [f.name for f in files]
            assert "diagram.excalidraw.md" not in names
        finally:
            exc.unlink()
