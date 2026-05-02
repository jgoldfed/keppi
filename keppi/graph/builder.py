"""Build a NetworkX graph from parsed notes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import networkx as nx

from keppi.parser.config import Config
from keppi.parser.markdown import ParsedNote


def _read_note_body(vault_path: Path, rel_path: str) -> str:
    """
    Read a note's markdown file from the vault, strip YAML frontmatter,
    return the body. Returns "" on any read error.
    """
    full_path = vault_path / rel_path
    try:
        text = full_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    # Strip YAML frontmatter if present
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    return text.strip()


def embed_all_notes(
    conn: sqlite3.Connection,
    provider,
    vault_path: Path,
    *,
    force: bool = False,
    progress_callback=None,
) -> dict:
    """
    Embed all notes not yet in vec_embeddings.
    force=True re-embeds everything.
    progress_callback: optional callable(current: int, total: int, title: str)
    Returns {"embedded": N, "skipped": N, "errors": N, "error_paths": list[str]}

    If meta['embed_needs_rebuild'] == '1', forces full rebuild and clears the flag.

    Reads note body directly from the markdown file via vault_path / nodes.path.
    Falls back to title + headings only if the file is unreadable or empty.
    """
    import json as _json

    needs_rebuild = conn.execute(
        "SELECT value FROM meta WHERE key='embed_needs_rebuild'"
    ).fetchone()
    if needs_rebuild and needs_rebuild["value"] == "1":
        force = True
        conn.execute("DELETE FROM meta WHERE key='embed_needs_rebuild'")
        conn.commit()

    try:
        already = {
            row["path"] for row in conn.execute("SELECT path FROM vec_embeddings")
        }
    except Exception:
        already = set()

    all_notes = conn.execute(
        "SELECT path, title, headings FROM nodes"
    ).fetchall()

    embedded = skipped = errors = 0
    error_paths: list[str] = []
    total = len(all_notes)

    for i, row in enumerate(all_notes):
        path = row["path"]

        if not force and path in already:
            skipped += 1
            continue

        # Primary: read full markdown body from disk
        text = _read_note_body(vault_path, path)

        # Fallback: title + headings if file is unreadable or empty
        if not text:
            headings = []
            try:
                headings = _json.loads(row["headings"] or "[]")
            except Exception:
                pass
            text = row["title"] or ""
            if headings:
                text += "\n" + "\n".join(str(h) for h in headings)

        if not text.strip():
            skipped += 1
            continue

        if progress_callback:
            progress_callback(i + 1, total, row["title"] or path)

        try:
            from keppi.search.semantic import embed_and_store
            embed_and_store(conn, path, text, provider)
            embedded += 1
        except Exception:
            errors += 1
            error_paths.append(path)

    return {
        "embedded": embedded,
        "skipped": skipped,
        "errors": errors,
        "error_paths": error_paths,
    }

# Emoji prefixes commonly used in Obsidian section headings
_EMOJI_HEADING_PREFIXES = (
    "🎯", "📅", "✍️", "🏆", "📋", "💬", "📎", "🔗", "💡", "🔑",
    "📌", "⭐", "🔥", "✅", "⬜", "📝", "🔍", "🧠", "📊",
    "🏠", "💼", "🚀", "⚙️", "🛠", "📚", "🎓", "🔔", "📍",
)

# Generic placeholder names from templates
_PLACEHOLDER_NAMES = frozenset({
    "Summary", "Notes", "Meetings", "Note", "Notes and Thoughts",
    "Clippings", "Source 1",
})


def _is_heading_like(target: str) -> bool:
    """Check if a wikilink target looks like a section heading, not a note title."""
    # Emoji-prefixed targets are almost always section headings
    if any(target.startswith(emoji) for emoji in _EMOJI_HEADING_PREFIXES):
        return True
    # Generic placeholder names from daily note templates
    if target in _PLACEHOLDER_NAMES:
        return True
    return False


class GraphBuilder:
    def __init__(self, config: Config):
        self.config = config
        self.graph: nx.DiGraph = nx.DiGraph()
        # Maps for wikilink resolution
        self._title_to_path: dict[str, str] = {}   # lower_title → rel_path
        self._alias_to_path: dict[str, str] = {}   # lower_alias → rel_path
        self._stem_to_path: dict[str, str] = {}    # lower_stem → rel_path

    # ------------------------------------------------------------------
    # Phase 1: add nodes
    # ------------------------------------------------------------------

    def add_note(self, note: ParsedNote) -> None:
        """Add a parsed note as a node."""
        fm = note.frontmatter_data
        cfg = self.config.frontmatter

        def _get(field_cfg: object, default: str = "") -> str:
            if not field_cfg or not isinstance(field_cfg, str):
                return default
            return str(fm.get(field_cfg, default))

        self.graph.add_node(
            note.path,
            title=note.title,
            type=_get(cfg.type_field, "note"),
            subtype=_get(cfg.subtype_field, ""),
            status=_get(cfg.status_field, ""),
            updated=_get(cfg.updated_field, ""),
            tags=json.dumps(note.tags),
            headings=json.dumps(note.headings),
            word_count=note.word_count,
            content_hash=note.content_hash,
            parse_error=note.parse_error or "",
        )

        # Register title and aliases for link resolution
        key = note.title.lower() if not self.config.links.case_sensitive else note.title
        self._title_to_path[key] = note.path

        stem = Path(note.path).stem
        stem_key = stem.lower() if not self.config.links.case_sensitive else stem
        self._stem_to_path[stem_key] = note.path

        alias_field = cfg.aliases_field
        if alias_field and isinstance(alias_field, str):
            aliases = fm.get(alias_field, [])
            if isinstance(aliases, str):
                aliases = [aliases]
            for alias in aliases or []:
                ak = str(alias).lower() if not self.config.links.case_sensitive else str(alias)
                self._alias_to_path[ak] = note.path

    # ------------------------------------------------------------------
    # Phase 2: add edges (called after ALL notes are added)
    # ------------------------------------------------------------------

    def add_edges(self, note: ParsedNote) -> None:
        """Add edges from wikilinks, embeds, related_to."""
        w = self.config.graph

        for target in note.embeds:
            # Skip non-markdown embed targets (images, PDFs, .base files, etc.)
            if any(target.lower().endswith(ext) for ext in (
                ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".pptx",
                ".xlsx", ".docx", ".base", ".csv", ".json", ".canvas",
            )):
                continue
            target_path = self._resolve(target)
            if target_path:
                self._add_or_update_edge(note.path, target_path, "embed", w.embed_weight)
            # Unresolved embed targets for non-.md files are silently skipped
            # They don't contribute to broken link counts

        for target in note.wikilinks:
            target_path = self._resolve(target)
            if target_path:
                self._add_or_update_edge(note.path, target_path, "wikilink", w.wikilink_weight)
            elif _is_heading_like(target):
                # Skip section-heading-style targets (emoji headings, template placeholders)
                # These resolve in Obsidian by matching headings within notes, not as separate notes
                continue
            else:
                self.graph.add_edge(note.path, f"__broken__:{target}", type="wikilink_broken", weight=0.0)

        for target in note.related_to:
            target_path = self._resolve(target)
            if target_path:
                self._add_or_update_edge(note.path, target_path, "related_to", w.related_to_weight)
                # related_to is bidirectional
                self._add_or_update_edge(target_path, note.path, "related_to", w.related_to_weight)

    def compute_tag_edges(self) -> None:
        """Add tag_overlap edges between notes sharing tags (after all notes added)."""
        weight = self.config.graph.tag_overlap_weight
        # Build tag → [paths] index
        tag_index: dict[str, list[str]] = {}
        real_nodes = [n for n in self.graph.nodes if not str(n).startswith("__broken__")]
        for node in real_nodes:
            data = self.graph.nodes[node]
            tags = json.loads(data.get("tags", "[]"))
            for tag in tags:
                tag_index.setdefault(tag, []).append(node)

        # For each pair of notes sharing a tag, compute Jaccard similarity
        pairs_processed: set[frozenset] = set()
        for tag, paths in tag_index.items():
            if len(paths) < 2:
                continue
            for i, a in enumerate(paths):
                for b in paths[i + 1 :]:
                    pair = frozenset((a, b))
                    if pair in pairs_processed:
                        continue
                    pairs_processed.add(pair)

                    tags_a = set(json.loads(self.graph.nodes[a].get("tags", "[]")))
                    tags_b = set(json.loads(self.graph.nodes[b].get("tags", "[]")))
                    if not tags_a or not tags_b:
                        continue
                    jaccard = len(tags_a & tags_b) / len(tags_a | tags_b)
                    edge_weight = weight * jaccard
                    if edge_weight > 0:
                        self._add_or_update_edge(a, b, "tag_overlap", edge_weight)
                        self._add_or_update_edge(b, a, "tag_overlap", edge_weight)

    def compute_folder_edges(self) -> None:
        """Add folder_proximity edges between notes in the same directory."""
        weight = self.config.graph.folder_proximity_weight
        folder_index: dict[str, list[str]] = {}
        real_nodes = [n for n in self.graph.nodes if not str(n).startswith("__broken__")]
        for node in real_nodes:
            folder = str(Path(node).parent)
            folder_index.setdefault(folder, []).append(node)

        for folder, paths in folder_index.items():
            if len(paths) < 2:
                continue
            for i, a in enumerate(paths):
                for b in paths[i + 1 :]:
                    self._add_or_update_edge(a, b, "folder_proximity", weight)
                    self._add_or_update_edge(b, a, "folder_proximity", weight)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve(self, title: str) -> str | None:
        """Resolve a wikilink title to a node path."""
        key = title.lower() if not self.config.links.case_sensitive else title
        # 1. Exact title match
        if key in self._title_to_path:
            return self._title_to_path[key]
        # 2. Alias match
        if key in self._alias_to_path:
            return self._alias_to_path[key]
        # 3. Stem match (filename without extension)
        if key in self._stem_to_path:
            return self._stem_to_path[key]
        # 4. Path-based match: if the title contains /, try matching as a relative path
        if "/" in title:
            # Try the path directly (with .md extension)
            path_key = title.lower() if not self.config.links.case_sensitive else title
            for node in self.graph.nodes:
                if node.lower() == path_key or node.lower() == path_key + ".md":
                    return node
            # Also try just the filename stem
            stem = Path(title).stem.lower()
            if stem in self._stem_to_path:
                return self._stem_to_path[stem]
        return None

    def _add_or_update_edge(self, src: str, dst: str, edge_type: str, weight: float) -> None:
        """Add edge, or upgrade if an edge of same/stronger type already exists."""
        if self.graph.has_edge(src, dst):
            existing = self.graph[src][dst]
            if existing.get("weight", 0) < weight:
                self.graph[src][dst]["type"] = edge_type
                self.graph[src][dst]["weight"] = weight
        else:
            self.graph.add_edge(src, dst, type=edge_type, weight=weight)
