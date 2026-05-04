# CLI Reference

All commands accept an optional `vault` argument (defaults to `.`). For most commands you can either pass the vault as a positional argument or set `path` in `keppi.toml`.

## Global Options

```
keppi --help          Show help
keppi <command> --help  Show help for a specific command
```

---

## Core Commands

### `keppi init [vault] [--quick]`
Initialize configuration.

- Auto-detects Obsidian vaults (looks for `.obsidian/` directory)
- `--quick` — Write defaults without prompts

```bash
keppi init                           # Interactive, auto-detects vault
keppi init ~/my-vault                # Specific path
keppi init ~/my-vault --quick        # Non-interactive
```

### `keppi build [vault]`
Parse all notes and build the graph from scratch.

- Shows progress with file count and elapsed time
- Stores graph in `~/.keppi/graphs/<vault_hash>.db`
- Safe to re-run; always does a full rebuild

```bash
keppi build                          # Current directory
keppi build ~/Documents/Obsidian\ Vault
```

### `keppi update [vault]`
Incremental update — only parses changed files.

- Compares SHA-256 content hashes to detect changes
- Much faster than `build` for daily use
- Falls back to `build` if no DB exists

```bash
keppi update
```

### `keppi stats [vault]`
Show graph statistics.

```
Nodes:    2682  (2653 notes, 29 orphans)
Edges:    764K
Density:  0.000106
Edge types:  tag_overlap: 759812  wikilink: 3847  related_to: 245  embed: 219
Broken links: 522
```

### `keppi watch [vault] [--stop]`
Start a background file watcher for automatic incremental updates.

- Debounces rapid saves (2-second window)
- Runs as a background process; PID stored in `~/.keppi/watcher.pid`
- `--stop` — Stop the running watcher

```bash
keppi watch ~/Documents/Obsidian\ Vault    # Start
keppi watch --stop                          # Stop
```

---

## Analysis Commands

### `keppi blast-radius <note> [vault] [--depth N] [--threshold F]`
BFS impact analysis — which notes are affected if `<note>` changes.

- `--depth` (default 2) — How many hops to traverse
- `--threshold` (default 0.3) — Minimum relevance to show (0–1)

```bash
keppi blast-radius "Medallion Architecture" ~/my-vault
keppi blast-radius "Data Quality" --depth 3 --threshold 0.2
```

### `keppi traverse <note> [vault] [--depth N]`
Expand the graph from a note, showing all reachable notes with edge types.

```bash
keppi traverse "Snowflake" --depth 2
```

### `keppi path <source> <target> [vault]`
Shortest path between two notes (ignores edge direction).

```bash
keppi path "Cloud Analytics" "Career Planning"
```

### `keppi context-pack <topic> [vault] [--budget N] [--depth N]`
Build a minimal token-budgeted reading set.

- `--budget` (default 4000) — Token budget (1 token ≈ 0.75 words)
- `--depth` (default 2) — Blast radius depth for neighbor discovery

```bash
keppi context-pack "data lakehouse" --budget 8000
keppi context-pack "Medallion Architecture" ~/my-vault
```

### `keppi communities [vault] [--min-size N] [--top N]`
Detect topical clusters using the Louvain algorithm.

```bash
keppi communities --min-size 3 --top 10
```

### `keppi gaps [vault] [--max-bridges N] [--min-shared N]`
Find structural gaps between clusters.

- `--max-bridges` (default 2) — Treat pairs with ≤N bridges as a gap
- `--min-shared` (default 1) — Only report gaps with ≥N shared tags

```bash
keppi gaps --max-bridges 1 --min-shared 2
```

### `keppi hubs [vault] [--top N]`
Top notes by degree centrality.

```bash
keppi hubs --top 20
```

### `keppi bridges [vault] [--top N]`
Top boundary-spanning notes by betweenness centrality.

Note: can be slow on large vaults (O(VE) algorithm).

```bash
keppi bridges --top 10
```

### `keppi orphans [vault]`
Notes with zero inbound and zero outbound connections.

```bash
keppi orphans
```

### `keppi drift [vault] [--stale N] [--recent N]`
Find stale notes connected to recently-updated ones.

- `--stale` (default 30) — Days without update to be "stale"
- `--recent` (default 14) — Days to consider "recent"

```bash
keppi drift --stale 60 --recent 7
```

---

## Search & Link Commands

### `keppi search <query> [vault] [--limit N]`
Keyword search. Scores: title match (+3), tag match (+2), heading match (+1.5), body match (up to +2).

```bash
keppi search "data quality" --limit 10
```

### `keppi embed [vault] [--force]`
Build or refresh the vector embedding index for semantic search.

- Long notes are split into overlapping 8 000-char chunks (200-char overlap) — each chunk gets its own embedding. Short notes (≤ 8 000 chars) produce a single chunk. No content is truncated.
- `--force` — Re-embed all notes, replacing existing embeddings

Requires `keppi[embeddings]` install and a running provider (Ollama or OpenAI key).

```bash
keppi embed                    # Embed new/unembedded notes
keppi embed --force            # Full rebuild (use after changing models)
```

**Output:**

```
┌─────────┬───────┐
│ Result  │ Count │
├─────────┼───────┤
│ Embedded│   847 │
│ Chunks  │   921 │  ← ≥ Embedded (long notes produce multiple chunks)
│ Skipped │   636 │
│ Errors  │     0 │
└─────────┴───────┘
```

### `keppi semantic-search <query> [vault] [--limit N] [--subfolder PATH]`
Meaning-based vector search. Finds conceptually related notes even when exact keywords don't match. Results are deduplicated per note — a single note appears at most once, at its best-matching chunk distance.

- `--limit` (default 10) — Maximum results
- `--subfolder PATH` — Restrict to a subfolder (e.g. `wiki` or `projects/active`). Falls back to `wiki_subfolder` in `keppi.toml` if not specified.

Requires embeddings to be built (`keppi embed`).

```bash
keppi semantic-search "consequences of leaving a job"
keppi semantic-search "data quality patterns" --subfolder wiki
keppi semantic-search "career planning" --limit 20
```

**Distance interpretation:**

| Distance | Color  | Signal |
|----------|--------|--------|
| < 0.3    | green  | Strong match — high confidence |
| 0.3–0.5  | yellow | Moderate — worth reading |
| > 0.5    | red    | Weak — topic may be thin in vault |

### `keppi broken-links [vault] [--top N]`
List broken wikilinks (targets that don't exist).

```bash
keppi broken-links
```

### `keppi suggest-links [note] [vault] [--top N] [--min-score F]`
Suggest missing connections based on tag overlap and shared neighbors.

- Omit `note` for global suggestions across all notes
- `--min-score` (default 0.3) — Minimum suggestion score

```bash
keppi suggest-links                          # Global
keppi suggest-links "Medallion Architecture" # For one note
```

---

## Integration Commands

### `keppi mcp-server [vault] [--transport stdio|sse] [--port N]`
Start the MCP server.

- `--transport` (default stdio) — stdio for Claude Desktop; sse for web clients
- `--port` (default 3000) — Port for SSE transport

```bash
keppi mcp-server ~/my-vault                      # stdio (for Claude Desktop)
keppi mcp-server ~/my-vault --transport sse      # SSE
```

### `keppi install <platform> [--vault PATH]`
Auto-configure as an MCP server.

Supported platforms: `claude`, `cursor`

```bash
keppi install claude --vault ~/Documents/Obsidian\ Vault
keppi install cursor --vault ~/Documents/Obsidian\ Vault
```

### `keppi export [vault] [--format json|graphml] [--output PATH]`
Export the graph.

- `--format` (default json) — `json` or `graphml`
- `--output` — Output file (JSON defaults to stdout)

```bash
keppi export --format graphml --output my-vault.graphml
keppi export --format json --output my-vault.json
keppi export --format json | python -m json.tool | head -50    # pretty-print
```
