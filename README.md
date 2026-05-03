# Keppi — README

> **Knowledge Engine for Precise Pattern Intelligence**
> 
> *Keppi (קעפּי) — Yiddish diminutive of kop. A little head that finds connections others miss.*

Graph traversal for your Obsidian vault. Find the connections you built but can't follow.

[![CI](https://github.com/jgoldfed/keppi/actions/workflows/ci.yml/badge.svg)](https://github.com/keppi/keppi/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/keppi)](https://pypi.org/project/keppi/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Why Keppi?

Niklas Luhmann, creator of the Zettelkasten system, wrote 70 books using a wooden box of 90,000 index cards. His system worked because every card was linked to others, and he could trace those connections outward. Most knowledge bases have the links. Nobody can follow them. Keppi follows them.

Karpathy's [LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) demonstrated a powerful idea: have an LLM incrementally build and maintain a persistent wiki of interlinked markdown files, then query the wiki instead of re-reading raw sources. It works great — until your wiki grows beyond a few hundred pages.

The missing piece isn't the wiki itself. It's the **query layer**. Similarity search finds textually related content. But when you're deciding whether to relocate for a job, you don't need pages that mention the city name — you need the pages *connected* to that decision: your job search, your consulting contract, your partner's business, your legal case. That's structural knowledge, and similarity search can't find it.

**Keppi doesn't compile external sources into a wiki.**  It traverses the knowledge you've already built and finds the connections you didn't know were there.

**Keppi builds the graph that makes the wiki queryable at scale.** It parses every wikilink, tag, frontmatter field, and folder relationship into a weighted directed graph, then answers: "Given this topic, what's the minimal set of notes I need — and how are they connected?"

## The Problem

Most knowledge bases are disconnected. Notes sit in folders with a few wikilinks and tags, but no real structure. You can't see what's connected, what's broken, or what's missing.

```
Nodes:    2,269
Edges:    614,139
Density:  0.119
Edge types:  tag_overlap: 609,722  wikilink: 2,075  related_to: 342
Broken links: 792
Orphans:      5
```

792 broken links. 5 orphan notes. A pile of tag overlaps masquerading as connections. That's a knowledge base where you can't trust what you find.

**After Keppi:**

```
Nodes:    1,471  (1,471 notes, 0 orphans)
Edges:    268,375
Density:  0.124
Edge types:  tag_overlap: 265,302  wikilink: 2,510  related_to: 562
Broken links: 0
```

1,471 notes. 268K connections. Zero broken links. Every note knows its neighbors.

## 60-Second Demo

```
# What does a relocation affect?
$ keppi blast-radius "Job Relocation" --depth 2

Blast Radius: Job Relocation (depth=2)
Seed: projects/Job Relocation

  1. Family Plans            relevance=0.89  distance=1
  2. Career                  relevance=0.82  distance=1
  3. Client Contract         relevance=0.71  distance=1
  4. Cost of Living          relevance=0.68  distance=1
  5. Job Search              relevance=0.65  distance=1
  6. Housing                 relevance=0.58  distance=1
  7. Commute                 relevance=0.52  distance=2
  8. Schools                 relevance=0.41  distance=2
```

That's not search. That's **knowing which notes matter** for a decision you're about to make. A job relocation affects your family, your career, your client obligations, and your daily life. All from one query.

## Where It Extends Karpathy's Vision

Karpathy's LLM Wiki has three layers: raw sources → wiki → schema. The missing piece is the **graph layer** between wiki and query.

```
Raw Sources  →  Wiki  →       ┌─────────────┐  →  Context Pack
  (immutable)   (LLM-owned)   │ Keppi Graph │     (for AI)
                              └─────────────┘
                                    │
                          ┌─────────┼──────────┐
                          │         │          │
                     blast-radius  gaps   semantic_search
                     traverse     orphans  communities
                     context-pack  hubs   suggest-links
```

The wiki is the *what*. Keppi is the *how everything connects*. Without the graph, you're doing keyword search on a wiki. With it, you're doing relevance-ranked traversal that understands which connections carry weight — and semantic search that finds meaning across your full vault without keyword guessing.

**What this enables that similarity search alone can't:**

| Question | Similarity Search | Graph Traversal |
|----------|------------------|-----------------|
| "What does a relocation affect?" | Pages containing "relocation" | Family Plans → Career → Client Contract → Cost of Living → Housing |
| "What's connected to my analytics platform?" | Pages mentioning "analytics" | Data Pipeline (implements it) → Cloud DB (runs on it) → Data Governance (quality rules) → Vendor Alpha (consulting partner) |
| "What haven't I connected?" | Can't detect | Gaps between clusters, orphan notes |

## Features

Trace blast radius, identify structural gaps, and give any AI assistant the precise context it needs.

### Core Commands

| Command | What it does | Example input → output |
|---------|-------------|--------------------|
| `keppi init` | Auto-detect vault, write config | `keppi init` → finds vault, writes `~/.keppi/keppi.toml` |
| `keppi build` | Parse all notes, build the graph | `keppi build ~/vault` → `1,471 notes, 268K edges` |
| `keppi stats` | Node/edge/density summary | `keppi stats ~/vault` → shows counts, edge types, broken links |

### Analysis

| Command | What it does | Example input → output |
|---------|-------------|--------------------|
| `keppi blast-radius` | Impact analysis — what's affected if this note changes | `keppi blast-radius "Job Relocation" --depth 2` → ranked list of connected notes by relevance |
| `keppi traverse` | Expand the graph outward from a note | `keppi traverse "Databricks" --depth 3` → all notes within 3 hops, with relevance scores |
| `keppi path` | Shortest path between two notes | `keppi path "Databricks" "Career"` → `Databricks → Data Pipeline → Career` |
| `keppi context-pack` | Token-budgeted reading set for AI context | `keppi context-pack "data lakehouse" --budget 4000` → minimal set of notes fitting 4K tokens |
| `keppi communities` | Detect topical clusters via Louvain algorithm | `keppi communities` → groups of tightly-connected notes by topic |
| `keppi gaps` | Find structural gaps — clusters with shared tags but few links | `keppi gaps` → "data-engineering" cluster ↔ "career" cluster: 1 bridge edge |
| `keppi hubs` | Top notes by degree centrality | `keppi hubs` → notes with the most connections |
| `keppi bridges` | Top boundary-spanning notes by betweenness centrality | `keppi bridges` → notes that connect otherwise separate clusters |
| `keppi orphans` | Notes with zero connections | `keppi orphans` → isolated notes that need linking |
| `keppi drift` | Stale notes connected to recently-updated ones | `keppi drift` → old notes that may need refreshing |

### Search & Links

| Command | What it does | Example input → output |
|---------|-------------|--------------------|
| `keppi search` | Keyword search across title, tags, headings, body | `keppi search "databricks"` → matching notes ranked by relevance |
| `keppi semantic-search` | Meaning-based vector search using embeddings | `keppi semantic-search "consequences of leaving a job"` → notes ranked by semantic distance |
| `keppi embed` | Build or refresh the vector embedding index | `keppi embed --force` → chunks and embeds all notes with a progress bar; shows Embedded / Chunks / Skipped / Errors |
| `keppi broken-links` | List all broken wikilinks | `keppi broken-links` → `Source → Missing target` for every broken link |
| `keppi suggest-links` | Suggest missing connections based on content overlap | `keppi suggest-links "Project Alpha"` → notes that should link but don't |

### Semantic Search

Keppi supports meaning-based search powered by vector embeddings. Semantic search finds conceptually related notes even when they use different words — no keyword guessing required.

**How it works:**

1. `keppi build` parses the vault into the graph
2. `keppi embed` generates vector embeddings for every note (stored in the same SQLite DB)
3. `keppi semantic-search` runs KNN vector search against those embeddings

**Embedding providers:**

| Provider | Setup | Model |
|----------|-------|-------|
| Ollama (default) | `ollama pull nomic-embed-text` | `nomic-embed-text` (768-dim) |
| OpenAI | Set `OPENAI_API_KEY` env var | `text-embedding-3-small` (1536-dim) |

**Distance interpretation:**

| Distance | Signal | What to do |
|----------|--------|------------|
| < 0.3 | Strong match | High confidence — this note likely answers the question |
| 0.3–0.5 | Moderate match | Relevant — worth reading |
| > 0.5 | Weak match | Topic may not be well-covered in the vault |

**Auto-embed on watch:** When the file watcher is running (`keppi watch`), newly changed notes are automatically embedded on save when `auto_embed = true` in config (the default).

**Config (`~/.keppi/keppi.toml`):**

```toml
[embed]
provider = "ollama"           # or "openai"
model = "nomic-embed-text"    # model served by provider
dimension = 768               # must match the model
# api_key_env = "OPENAI_API_KEY"   # for openai provider
# base_url = "http://localhost:11434"  # override default URL
auto_embed = true             # auto-embed notes on watch
```

See [keppi.example.toml](keppi.example.toml) for a full annotated example.

### Config

| Command | What it does | Example |
|---------|-------------|--------|
| `keppi config get` | Print config value | `keppi config get vault.exclude_dirs` |
| `keppi config add` | Add to a list value | `keppi config add vault.exclude_dirs "_archive"` |
| `keppi config set` | Set a config value | `keppi config set graph.relevance_threshold 0.5` |

### MCP Server (Claude Desktop, Cursor)

```bash
keppi install claude    # Auto-configure for Claude Desktop
keppi install cursor    # Auto-configure for Cursor
```

19 graph-aware tools available to any MCP-compatible AI assistant: `blast_radius`, `context_pack`, `find_gaps`, `suggest_links`, `keyword_search`, `semantic_search`, `get_embed_status`, and more.

For other MCP clients, use `keppi mcp-server /path/to/vault` and configure manually.

**Semantic MCP tools:**

| Tool | What it does |
|------|-------------|
| `semantic_search` | Vector KNN search by meaning. Supports `wiki_only=True` to scope results to `3-Resources/wiki/`. Returns deduplicated note-level results (best chunk per note) with path, title, and distance. |
| `get_embed_status` | Returns embedding coverage %, `total_chunks`, `ready_for_semantic_search` bool, and action guidance for the AI assistant. |

### Agent Skills

Keppi ships two agent skills for structured research workflows:

- **wiki-search** — Fast path: semantic pre-check → wiki layer (~400-600 tokens) → Keppi graph navigation. The semantic pre-check (`get_embed_status` + `semantic_search(wiki_only=True)`) resolves most queries in a single read without any keyword guessing. Best for known entities, people, projects, and relationships.
- **vault-research** — Deep path: comprehensive multi-note analysis using blast radius, context packs, and raw note reads. Uses semantic search as the primary entry-point finder, falling back to keyword search only when embeddings aren't available. Best for evidence retrieval from meeting transcripts or questions requiring 4+ source notes.

Both skills are in the `skills/` directory and can be added to any MCP-compatible AI assistant.

### Coming Soon

**FR-001: Smart `keppi init`** — Auto-detect vault patterns and suggest exclusions (archive folders, attachment dirs, binary files). No more manual TOML editing.

**FR-002: `keppi visualize`** — Interactive HTML graph visualization with drag, zoom, and filter. Color-coded by node type, edge-weighted by relationship type.

```bash
keppi visualize "Job Relocation" --depth 2 --output relocation.html --open
```

**FR-003: `keppi connect`** — Auto-generate wikilinks and `related_to` frontmatter from graph analysis. The auto-wiring that makes the graph work for notes that were never written to be graphed.

```bash
keppi connect --dry-run           # preview suggestions
keppi connect --auto-accept       # apply high-confidence connections
```

See [ROADMAP.md](docs/ROADMAP.md) for full feature request details.

---

## Installation

```bash
pip install keppi
```

Or with `uv`:

```bash
uv tool install keppi
```

**For semantic search**, install with the `embeddings` extra:

```bash
pip install keppi[embeddings]
# or
uv tool install "keppi[embeddings]"
```

This adds `sqlite-vec` (vector search extension) and `httpx` (HTTP client for embedding providers). Then install an embedding provider:

```bash
# Option A: Ollama (local, free)
ollama pull nomic-embed-text

# Option B: OpenAI (set key in your shell profile)
export OPENAI_API_KEY=sk-...
```

**Requirements:** Python 3.10+. Works with any markdown directory — no Obsidian required.

---

## Quick Start

```bash
# 1. Initialize (auto-detects Obsidian vaults)
keppi init

# 2. Build the graph (~30s for 500 notes)
keppi build ~/Documents/Obsidian\ Vault

# 3. Explore
keppi stats ~/Documents/Obsidian\ Vault
keppi blast-radius "Job Relocation" --depth 2

# 4. Build embeddings for semantic search (requires keppi[embeddings] + Ollama or OpenAI)
keppi embed ~/Documents/Obsidian\ Vault

# 5. Search by meaning
keppi semantic-search "what are the financial consequences of leaving my job"
```

**Windows:** Set `PYTHONUTF8=1` in your environment or prefix commands:
```powershell
$env:PYTHONUTF8=1; keppi build "C:\Users\You\Documents\Obsidian Vault"
```

---

## How It Works

### Graph Model

**Nodes:** One per markdown file. Attributes: title, tags, word count, last-modified date, type, content hash.

**Edge types and weights:**

| Type | Weight | How created |
|------|--------|-------------|
| `wikilink` | 1.0 | `[[Note Title]]` in body |
| `embed` | 1.5 | `![[Note Title]]` (stronger dependency) |
| `related_to` | 2.0 | `related_to:` frontmatter field — explicit semantic link |
| `tag_overlap` | 0–0.5 × Jaccard | Shared tags between notes |
| `folder_proximity` | 0.3 | Notes in same directory |

### Relevance Decay

Blast radius uses BFS with relevance decay: `relevance = parent_relevance × edge_weight`. Results are sorted by relevance descending. A `related_to` link carries 2× the weight of a wikilink, which carries 2× the weight of a tag overlap.

### Semantic Search

Embeddings are generated from the full note body (frontmatter stripped). Long notes are split into overlapping 8 000-char chunks (200-char overlap), each stored as its own embedding. Search returns the best-matching chunk per note, deduplicated — so a 50 000-char meeting transcript is fully indexed, not truncated. Everything is stored in the same SQLite DB using `sqlite-vec` — no separate vector store, no network calls at query time.

### Context Packs

Given a topic and a token budget, Keppi greedily selects the highest-relevance notes that fit within the budget — exactly what you'd paste into an AI context window.

### Community Detection

Louvain algorithm on the undirected graph projection. Gap detection finds community pairs with shared tags but few bridge edges — the places where your vault has knowledge silos.

---

## Real Vault Performance

Built and tested on a real personal knowledge base:

| Metric | Before cleanup | After Keppi |
|--------|---------------|-------------|
| Notes | 2,269 | 1,471 |
| Broken links | 792 | 0 |
| Orphans | 5 | 0 |
| Edges | 614,139 | 267,581 |
| Density | 0.119 | 0.124 |

The cleanup wasn't manual — Keppi identified the problems (`broken-links`, `orphans`, `suggest-links`), and we fixed them. The graph went from a mess of 792 broken links and disconnected notes to a clean, connected knowledge base.

---

## Configuration

Keppi works with zero config out of the box. Config lives at `~/.keppi/keppi.toml` — outside your vault, so it's never affected by Obsidian Sync.

```bash
keppi init                        # auto-detect vault, write config
keppi init --quick                # non-interactive, accept defaults
keppi init --no-scan              # skip vault pattern detection

# CLI config
keppi config get vault.exclude_dirs
keppi config add vault.exclude_dirs "_archive"
keppi config set graph.relevance_threshold 0.5
```

See [keppi.example.toml](keppi.example.toml) for the full config reference.

---

## License

MIT — See [LICENSE](LICENSE).
