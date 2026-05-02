# MCP Tools Reference

Keppi exposes 20 tools to any MCP-compatible AI assistant (Claude Desktop, Cursor, OpenClaw, etc.).

## Setup

```bash
keppi install claude --vault /path/to/vault   # Claude Desktop
keppi install cursor --vault /path/to/vault   # Cursor
```

Or start the server manually:
```bash
keppi mcp-server /path/to/vault               # stdio (default)
keppi mcp-server /path/to/vault --transport sse --port 3000  # SSE
```

---

## Graph Overview

### `get_graph_stats`
Returns overall graph statistics.

**No parameters.**

**Returns:**
```json
{
  "node_count": 2682,
  "edge_count": 764123,
  "orphan_count": 29,
  "density": 0.000106,
  "edge_types": {"wikilink": 3847, "tag_overlap": 759812, "related_to": 245, "embed": 219}
}
```

### `query_node`
Get full details for a specific note.

**Parameters:**
- `note` (str) — Note title or path
- `vault_path` (str, optional) — Vault directory

**Returns:** Node attributes, outbound edges, inbound edges, tags, word count.

---

## Traversal & Paths

### `blast_radius`
BFS impact analysis from a note. Answers: "what notes are affected if this one changes?"

**Parameters:**
- `note` (str) — Starting note title
- `depth` (int, default 2) — BFS depth
- `threshold` (float, default 0.3) — Minimum relevance score to include
- `direction` (str, default "both") — "out", "in", or "both"
- `vault_path` (str, optional)

**Returns:**
```json
{
  "count": 5,
  "seed": "concepts/Medallion Architecture.md",
  "results": [
    {"path": "...", "title": "Data Quality", "relevance": 0.95, "distance": 1},
    ...
  ]
}
```

### `traverse_graph`
Expand the graph from a note to depth N, collecting all reachable nodes.

**Parameters:**
- `note` (str) — Starting note title
- `depth` (int, default 2)
- `vault_path` (str, optional)

**Returns:** All reachable nodes with distance and edge types.

### `find_path`
Shortest path between two notes (undirected BFS).

**Parameters:**
- `source` (str) — Source note title
- `target` (str) — Target note title
- `vault_path` (str, optional)

**Returns:**
```json
{
  "hops": 3,
  "path": ["Data Pipeline", "Data Governance", "Cloud DB", "Cloud Analytics"]
}
```

---

## Context & Search

### `context_pack`
Build a minimal token-budgeted reading set for a topic. The key tool for AI context management.

**Parameters:**
- `topic` (str) — Topic or note title
- `token_budget` (int, default 4000) — Maximum tokens to include
- `depth` (int, default 2) — Blast radius depth for neighbor discovery
- `vault_path` (str, optional)

**Returns:**
```json
{
  "entry_count": 5,
  "seed_note": "Medallion Architecture",
  "estimated_tokens": 3847,
  "token_budget": 4000,
  "entries": [
    {"title": "Medallion Architecture", "relevance": 1.0, "estimated_tokens": 850, "tags": ["data-engineering"]},
    ...
  ]
}
```

### `semantic_search`
Vector KNN search — finds notes by meaning, not keywords. Handles chunked notes transparently: long notes are indexed as overlapping 8 000-char segments, and results are deduplicated to one entry per note (best-matching chunk wins).

**Parameters:**
- `query` (str) — Natural language query
- `limit` (int, default 10) — Max results after deduplication
- `wiki_only` (bool, default false) — Restrict to `3-Resources/wiki/`
- `path_prefix` (str, optional) — Restrict to any subdirectory prefix
- `vault_path` (str, optional)

**Returns:**
```json
{
  "count": 3,
  "query": "consequences of leaving a job",
  "scope": "full vault",
  "results": [
    {"path": "1-Projects/Job Search.md", "title": "Job Search", "distance": 0.18, "match_strength": "strong match"},
    {"path": "2-Areas/Career.md",        "title": "Career",     "distance": 0.31, "match_strength": "moderate match"}
  ]
}
```

**Distance guide:** < 0.3 strong · 0.3–0.5 moderate · > 0.5 weak (fall back to `keyword_search`).

Returns `{"error": "embeddings_not_built"}` if `keppi embed` has not been run.

### `get_embed_status`
Check embedding coverage before running `semantic_search`.

**Parameters:**
- `vault_path` (str, optional)

**Returns:**
```json
{
  "total_notes": 1483,
  "embedded_notes": 1483,
  "total_chunks": 1621,
  "coverage_percent": 100.0,
  "needs_rebuild": false,
  "stored_dimension": 768,
  "configured_provider": "ollama",
  "configured_model": "nomic-embed-text",
  "ready_for_semantic_search": true,
  "action_needed": null
}
```

`total_chunks` ≥ `embedded_notes` because long notes produce multiple chunks. `embedded_notes` counts unique notes (not chunks), so `coverage_percent` reflects note coverage.

### `keyword_search`
Search notes by keyword across title, tags, headings, and body.

**Parameters:**
- `query` (str)
- `limit` (int, default 20)
- `vault_path` (str, optional)

### `tag_search`
Find all notes with a specific tag.

**Parameters:**
- `tag` (str) — Tag name (without `#`)
- `vault_path` (str, optional)

---

## Analysis

### `find_hubs`
Top notes by degree centrality (most connections).

**Parameters:**
- `top_n` (int, default 10)
- `vault_path` (str, optional)

### `find_orphans`
Notes with zero inbound and zero outbound connections.

**No required parameters.**

### `detect_communities`
Louvain community detection — finds topical clusters.

**Parameters:**
- `min_size` (int, default 2) — Minimum community size to report
- `vault_path` (str, optional)

**Returns:** List of communities with size, top tags, and representative note.

### `detect_gaps`
Structural gaps: community pairs with shared tags but few connecting edges.

**Parameters:**
- `max_bridge_edges` (int, default 2) — Max bridges to consider a "gap"
- `min_shared_tags` (int, default 1)
- `vault_path` (str, optional)

### `detect_drift`
Find stale notes that are directly connected to recently-updated ones.

**Parameters:**
- `stale_days` (int, default 30) — Days without update to be "stale"
- `recent_days` (int, default 14) — Days to consider "recent"
- `vault_path` (str, optional)

---

## Links & Health

### `list_broken_links`
All wikilinks pointing to notes that don't exist.

**No required parameters.**

### `suggest_links`
Suggest missing connections based on tag overlap and shared neighbors.

**Parameters:**
- `note` (str, optional) — Limit to suggestions for one note; omit for global
- `top_n` (int, default 10)
- `min_score` (float, default 0.3)
- `vault_path` (str, optional)

### `list_stale`
Notes not modified in N days.

**Parameters:**
- `days` (int, default 30)
- `vault_path` (str, optional)

### `get_surprising_connections`
Unexpected high-relevance connections between distant notes.

**Parameters:**
- `top_n` (int, default 10)
- `vault_path` (str, optional)

---

## Example AI Workflow

```
Human: "I'm writing about data lakehouses. What should I read?"

AI uses: context_pack("data lakehouse", token_budget=4000)
→ Returns 5 most relevant notes within budget
→ AI reads those notes and answers with full context
```

```
Human: "Find notes about career transitions"

AI uses: get_embed_status() → ready_for_semantic_search: true
AI uses: semantic_search("career transitions and job changes", limit=5)
→ Returns best-matching notes by meaning, deduplicated per note
→ Distances < 0.3 are read first; > 0.5 triggers keyword_search fallback
```