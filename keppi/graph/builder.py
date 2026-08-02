"""Build a NetworkX graph from parsed notes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import networkx as nx

from keppi.parser.config import Config
from keppi.parser.markdown import ParsedNote
from keppi.search.providers import serialize_vector

CHUNK_SIZE = 1600
CHUNK_OVERLAP = 200


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks. Returns [text] if short enough."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += chunk_size - overlap
    return chunks


def _read_note_body(vault_path: Path, rel_path: str) -> str:
    """Read a note's markdown file from the vault, strip YAML frontmatter.
    Returns "" on any read error. Chunking is handled by the caller.
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


def _embed_with_bisection(conn, path: str, chunks: list[str], provider) -> tuple[int, int]:
    """Embed chunks, bisecting any that hit context-length limits.

    Returns (chunks_stored, errors). Bisection stops when a sub-chunk is too
    small to split further (< 200 chars), counting it as an error instead.

    Uses batch embedding when available for better throughput.
    """
    from keppi.search.providers import ContextLengthError
    from keppi.search.semantic import embed_and_store

    # Try batch embed first
    try:
        vectors = provider.embed_batch(chunks)
        stored = errors = 0
        for i, (text, vec) in enumerate(zip(chunks, vectors)):
            if not vec:
                # Empty vector — bisection fallback for this chunk
                if len(text) <= 200:
                    errors += 1
                else:
                    mid = len(text) // 2
                    sub_chunks = [text[:mid], text[mid:]]
                    sub_vectors = provider.embed_batch(sub_chunks)
                    for j, (sub_text, sub_vec) in enumerate(zip(sub_chunks, sub_vectors)):
                        if sub_vec:
                            embed_and_store(conn, f"{path}::{i + j}", sub_text, provider, _vec=sub_vec)
                            stored += 1
                        else:
                            errors += 1
            else:
                embed_and_store(conn, f"{path}::{i}", text, provider, _vec=vec)
                stored += 1
        return stored, errors
    except ContextLengthError:
        pass  # Fall through to individual bisection
    except Exception:
        pass  # Fall through to individual bisection

    # Fallback: individual embed with bisection
    stored = errors = 0
    pending = list(chunks)
    key = 0

    while pending:
        text = pending.pop(0)
        try:
            embed_and_store(conn, f"{path}::{key}", text, provider)
            key += 1
            stored += 1
        except ContextLengthError:
            if len(text) <= 200:
                errors += 1
            else:
                mid = len(text) // 2
                pending.insert(0, text[mid:])
                pending.insert(0, text[:mid])
        except Exception:
            errors += 1

    return stored, errors


def embed_all_notes(
    conn: sqlite3.Connection,
    provider,
    vault_path: Path,
    *,
    force: bool = False,
    progress_callback=None,
) -> dict:
    """
    Embed all notes not yet in vec_embeddings, using overlapping chunks.
    force=True re-embeds everything.
    progress_callback: optional callable(current: int, total: int, title: str)
    Returns {"embedded": N, "skipped": N, "errors": N, "error_paths": list[str], "chunks": N}

    Processes notes in batches of 8: embed all chunks for the batch in one
    provider call, bulk-insert with executemany, commit, then advance.
    Progress is durable after every batch.
    """
    needs_rebuild = conn.execute(
        "SELECT value FROM meta WHERE key='embed_needs_rebuild'"
    ).fetchone()
    if needs_rebuild and needs_rebuild["value"] == "1":
        force = True
        conn.execute("DELETE FROM meta WHERE key='embed_needs_rebuild'")
        conn.commit()

    try:
        all_chunk_paths = {
            row["path"] for row in conn.execute("SELECT path FROM vec_embeddings")
        }
    except Exception:
        all_chunk_paths = set()

    already_notes: set[str] = set()
    for chunk_path in all_chunk_paths:
        sep = chunk_path.find("::")
        already_notes.add(chunk_path[:sep] if sep != -1 else chunk_path)

    all_notes = conn.execute("SELECT path, title, headings FROM nodes").fetchall()

    embedded = skipped = errors = chunks_total = 0
    error_paths: list[str] = []
    expected_dim = provider.config.embed.dimension

    # ── Phase 1: collect notes to embed ─────────────────────────────────
    pending: list[tuple[str, str, list[str]]] = []  # (path, title, chunks)
    for row in all_notes:
        path = row["path"]
        if not force and path in already_notes:
            skipped += 1
            continue
        text = _read_note_body(vault_path, path)
        if not text:
            headings = []
            try:
                headings = json.loads(row["headings"] or "[]")
            except Exception:
                pass
            text = row["title"] or ""
            if headings:
                text += "\n" + "\n".join(str(h) for h in headings)
        if not text.strip():
            skipped += 1
            continue
        pending.append((path, row["title"] or path, chunk_text(text)))

    if not pending:
        return {"embedded": embedded, "skipped": skipped, "errors": errors,
                "error_paths": error_paths, "chunks": chunks_total}

    total_to_embed = len(pending)
    notes_done = 0
    note_stored: dict[str, int] = {}
    note_errors: dict[str, int] = {}

    # ── Phase 2: batch loop — embed + bulk-insert + commit per batch ─────
    NOTES_PER_BATCH = 8

    for batch_start in range(0, len(pending), NOTES_PER_BATCH):
        batch_notes = pending[batch_start:batch_start + NOTES_PER_BATCH]

        # Flatten all chunks for this batch
        batch_flat = [
            (path, ci, text)
            for path, _, chunks in batch_notes
            for ci, text in enumerate(chunks)
        ]
        batch_texts = [t for _, _, t in batch_flat]

        # Delete stale embeddings before writing new ones
        for path, _, _ in batch_notes:
            try:
                conn.execute(
                    "DELETE FROM vec_embeddings WHERE path = ? OR path LIKE ?",
                    (path, path + "::%"),
                )
            except Exception:
                pass

        # Embed all chunks in one provider call
        try:
            vecs = provider.embed_batch(batch_texts)
        except Exception:
            vecs = [[] for _ in batch_texts]

        # Build bulk-insert list; use running counter per note so bisected
        # sub-chunks never collide with subsequent chunk keys in the same note.
        insert_rows: list[tuple[str, bytes]] = []
        chunk_counter: dict[str, int] = {}

        for (path, _ci, text), vec in zip(batch_flat, vecs):
            key = chunk_counter.get(path, 0)
            if vec and len(vec) == expected_dim:
                insert_rows.append((f"{path}::{key}", serialize_vector(vec)))
                chunk_counter[path] = key + 1
                note_stored[path] = note_stored.get(path, 0) + 1
            elif not vec and len(text) > 200:
                # Context-length failure: bisect and retry
                mid = len(text) // 2
                sub_chunks = [text[:mid], text[mid:]]
                try:
                    sub_vecs = provider.embed_batch(sub_chunks)
                except Exception:
                    sub_vecs = [[], []]
                for sub_text, sub_vec in zip(sub_chunks, sub_vecs):
                    if sub_vec and len(sub_vec) == expected_dim:
                        insert_rows.append((f"{path}::{key}", serialize_vector(sub_vec)))
                        key += 1
                        note_stored[path] = note_stored.get(path, 0) + 1
                    else:
                        note_errors[path] = note_errors.get(path, 0) + 1
                chunk_counter[path] = key
            else:
                note_errors[path] = note_errors.get(path, 0) + 1

        if insert_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO vec_embeddings (path, embedding) VALUES (?, ?)",
                insert_rows,
            )
        try:
            conn.commit()
        except Exception:
            pass

        notes_done += len(batch_notes)
        if progress_callback:
            _, last_title, _ = batch_notes[-1]
            progress_callback(notes_done, total_to_embed, last_title)

    # Tally final results
    for path, _, _ in pending:
        stored = note_stored.get(path, 0)
        if stored == 0:
            errors += 1
            error_paths.append(path)
        else:
            embedded += 1
        chunks_total += stored

    return {
        "embedded": embedded,
        "skipped": skipped,
        "errors": errors,
        "error_paths": error_paths,
        "chunks": chunks_total,
    }

# Emoji prefixes commonly used in Obsidian section headings
_EMOJI_HEADING_PREFIXES = (
    "🎯", "📅", "✍️", "🏆", "📋", "💬", "📎", "🔗", "💡", "🔑",
    "📌", "⭐", "🔥", "✅", "⬜", "📝", "🔍", "🧠", "📊",
    "🏠", "💼", "🚀", "⚙️", "🛠", "📚", "🎓", "🔔", "📍",
)

# Generic placeholder names from templates and schema docs
_PLACEHOLDER_NAMES = frozenset({
    "Summary", "Notes", "Meetings", "Note", "Notes and Thoughts",
    "Clippings", "Source 1",
    # wiki-ops.md schema examples
    "Concept A", "Concept B", "Concept A vs Concept B",
    "Related Concept", "Source A", "Source Name",
    "Does Scale Improve Reasoning?",
    # wiki-ops.md / index.md structural references
    "Wikilinks", "wikilinks", "double bracket",
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
