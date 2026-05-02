# Keppi Semantic Chunking — Implementation Spec

Add overlapping chunking to semantic embeddings so long notes are fully indexed
instead of truncated. This is a targeted change on top of the existing semantic
search implementation.

Read ALL existing source files before writing any changes:
 keppi/graph/builder.py — `_read_note_body()`, `embed_all_notes()`
 keppi/search/semantic.py — `embed_and_store()`, `semantic_search()`
 keppi/graph/storage.py — `ensure_vec_table()`, vec_embeddings schema
 keppi/graph/incremental.py — auto-embed hook
 keppi/cli/main.py — `keppi embed` and `keppi semantic-search` commands
 keppi/mcp/server.py — `semantic_search` and `get_embed_status` MCP tools

---

## CONTEXT

Currently `_read_note_body()` truncates notes to 8000 chars before embedding.
128 of 1483 vault notes exceed this limit (some up to 267K chars). Truncation
loses the majority of long notes — meeting transcripts, research docs, blog drafts.

Chunking splits long notes into overlapping 8000-char windows, each getting its
own embedding. Search returns the best-matching chunk per note, deduplicated by
note path.

## CONSTRAINTS

1. Backward compatible — if no chunks exist yet, everything works as before.
2. Simple — one table, no new tables. Change the primary key format.
3. Chunking happens at embed time, transparent to search callers.
4. Embedding failure on one chunk does not block other chunks or other notes.

---

## DESIGN

### Chunking Rules

- `CHUNK_SIZE = 8000` characters
- `CHUNK_OVERLAP = 200` characters
- Notes ≤ 8000 chars: single chunk, no overlap needed
- Notes > 8000 chars: split into chunks of CHUNK_SIZE with CHUNK_OVERLAP overlap
  between consecutive chunks
- The last chunk may be shorter than CHUNK_SIZE

### Chunking Algorithm

```python
def chunk_text(text: str, chunk_size: int = 8000, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks. Returns ['text'] if short enough."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
        if end >= len(text):
            break
    # Remove duplicate final chunk if overlap caused it
    if len(chunks) >= 2 and chunks[-1] == chunks[-2][-len(chunks[-1]):]:
        chunks.pop()
    return chunks
```

### vec_embeddings Primary Key Change

**Current:** `path TEXT PRIMARY KEY` — one row per note, key = `"0-Inbox/Some Note.md"`
**New:** `path TEXT PRIMARY KEY` — one row per chunk, key = `"0-Inbox/Some Note.md::0"`, `"0-Inbox/Some Note.md::1"`, etc.

The `::N` suffix is the chunk index. Notes with a single chunk (≤8000 chars) get
`::0`. The `::` separator is unlikely to appear in real file paths.

### Search Deduplication

`semantic_search()` returns the **best chunk per note** — lowest distance wins.
When multiple chunks from the same note match, only the best is returned.

The KNN query already uses `k = limit`. After deduplication, the result may have
fewer than `limit` results. To compensate, request `k = limit * 3` from sqlite-vec
then deduplicate down to `limit`.

### Delete Behavior

When a note is deleted or re-embedded, delete ALL chunks for that note using:
```sql
DELETE FROM vec_embeddings WHERE path LIKE ? || '::%'
```
This catches `path::0`, `path::1`, etc.

### get_embed_status Change

Count unique notes (not chunks) by stripping the `::N` suffix:
```sql
SELECT COUNT(DISTINCT SUBSTR(path, 1, INSTR(path, '::') - 1)) FROM vec_embeddings
```
Or simpler: just count total chunks and note it in the response.

---

## FILE CHANGES

### FILE 1: keppi/graph/builder.py

Add `chunk_text()` function at module level.

Remove the `max_chars` parameter from `_read_note_body()` — it should return the
full body again. Truncation is no longer needed because chunking handles long notes.

Update `embed_all_notes()`:
- Call `chunk_text(text)` to get chunks
- For each chunk, call `embed_and_store(conn, f"{path}::{i}", chunk_text, provider)`
- Track chunks embedded per note for the progress callback

Update the progress callback to count chunks, not notes:
- Progress bar shows total chunks (approximate — calculate as `sum(ceil(body_len / 8000))` for all notes)

Update the watcher auto-embed code (same chunking logic):
- Embed all chunks for a changed note
- Delete old chunks with `LIKE path || '::%'`

### FILE 2: keppi/search/semantic.py

Update `embed_and_store()` — no changes needed (it just inserts a row).

Update `semantic_search()`:
- Change the JOIN to extract the note path from the chunk key:
  ```sql
  SELECT v.path, SUBSTR(v.path, 1, INSTR(v.path, '::') - 1) AS note_path,
         n.title, v.distance
  FROM vec_embeddings v
  JOIN nodes n ON SUBSTR(v.path, 1, INSTR(v.path, '::') - 1) = n.path
  WHERE v.embedding MATCH ? AND k = ?
  ORDER BY v.distance
  ```
- Request `k = limit * 3` from sqlite-vec
- Deduplicate by `note_path`, keeping the lowest distance per note
- Apply `path_prefix` filter on `note_path`, not `v.path`
- Return `SemanticResult.path = note_path` (without `::N` suffix)
- Truncate `limit` results after deduplication

Handle the case where a note has no `::` in its path (single-chunk notes from
before chunking was added): `INSTR(path, '::')` returns 0, so use a CASE expression
or COALESCE to handle it.

### FILE 3: keppi/graph/incremental.py

Update the auto-embed hook:
- Use `chunk_text()` to chunk the note body
- Embed each chunk with `path::N` keys
- Delete old chunks: `DELETE FROM vec_embeddings WHERE path LIKE ? || '::%'`

Update the delete hook:
- Change from `DELETE FROM vec_embeddings WHERE path = ?`
  to `DELETE FROM vec_embeddings WHERE path LIKE ? || '::%'`

### FILE 4: keppi/mcp/server.py

Update `semantic_search` MCP tool:
- No code changes needed — it calls `semantic_search()` from semantic.py which
  now returns deduplicated results with `note_path`

Update `get_embed_status` MCP tool:
- Add `total_chunks` field: `SELECT COUNT(*) FROM vec_embeddings`
- Keep `embedded_notes` as count of unique note paths
- Update `coverage_percent` to use unique note paths, not chunk count

### FILE 5: keppi/cli/main.py

Update `keppi embed` command:
- No major changes — `embed_all_notes()` handles chunking internally
- Progress bar now shows chunks (not notes)
- Summary table: add a "Chunks" row showing total chunks embedded

Update `keppi semantic-search` command:
- No changes — results are already deduplicated by `semantic_search()`

### FILE 6: tests/

Add `tests/test_chunking.py`:
- `test_chunk_text_short`: text ≤ 8000 chars returns single chunk
- `test_chunk_text_long`: text > 8000 chars returns multiple chunks
- `test_chunk_text_overlap`: consecutive chunks share 200 chars of overlap
- `test_chunk_text_last_short`: last chunk can be shorter than 8000
- `test_chunk_key_format`: keys are `path::0`, `path::1`, etc.

Update `tests/test_embed_all_notes.py`:
- `test_long_note_produces_multiple_chunks`: a note > 8000 chars results in
  multiple vec_embeddings rows with `::0`, `::1` suffixes
- `test_search_deduplicates_chunks`: multiple chunks from same note, only
  best result returned

Update `tests/test_semantic.py`:
- `test_semantic_search_deduplication`: insert chunks for same note, search
  returns the note once with the best distance

---

## MIGRATION

Existing embeddings have keys like `"0-Inbox/Note.md"` (no `::N` suffix).
New embeddings use `"0-Inbox/Note.md::0"`, etc.

**Simple migration:** On next `keppi embed`, set `embed_needs_rebuild = '1'`
which forces a full rebuild. Old single-key rows get replaced by chunked rows.

No explicit migration code needed — the rebuild flag already exists.

---

## FINAL CHECKLIST

- [ ] `ruff check keppi/ tests/` passes
- [ ] `mypy keppi/` passes
- [ ] `pytest tests/ -v` all pass
- [ ] Short notes (≤8000 chars) produce exactly 1 chunk with `::0` suffix
- [ ] Long notes produce multiple chunks with proper overlap
- [ ] `semantic_search` returns each note at most once (deduplicated)
- [ ] `path_prefix` filter works correctly with chunked keys
- [ ] Delete note removes all chunks (`LIKE path || '::%'`)
- [ ] Watcher re-embeds all chunks on note change
- [ ] `get_embed_status` counts unique notes, not total chunks
- [ ] Backward compatible — works with or without chunked embeddings