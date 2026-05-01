# Keppi — README Draft (Public Launch)

> **Knowledge Engine for Precise Pattern Intelligence**
> 
> *Keppi (קעפּי) — Yiddish diminutive of kop. A little head that finds connections others miss.*

Parse any Obsidian vault (or markdown directory) into a queryable knowledge graph. Trace blast radius, find structural gaps, and give any AI assistant precisely the context it needs.

[![CI](https://github.com/keppi/keppi/actions/workflows/ci.yml/badge.svg)](https://github.com/keppi/keppi/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/keppi)](https://pypi.org/project/keppi/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Why Keppi?

Karpathy's [LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) demonstrated a powerful idea: have an LLM incrementally build and maintain a persistent wiki of interlinked markdown files, then query the wiki instead of re-reading raw sources. It works great — until your wiki grows beyond a few hundred pages.

The missing piece isn't the wiki itself. It's the **query layer**. Similarity search finds textually related content. But when you're deciding whether to relocate for a job, you don't need pages that mention the city name — you need the pages *connected* to that decision: your job search, your consulting contract, your partner's business, your legal case. That's structural knowledge, and similarity search can't find it.

**Keppi builds the graph that makes the wiki queryable at scale.** It parses every wikilink, tag, frontmatter field, and folder relationship into a weighted directed graph, then answers: "Given this topic, what's the minimal set of notes I need — and how are they connected?"

## The Problem in One Screenshot

```
$ keppi stats ~/Documents/Obsidian\ Vault

 Nodes:    1,471  (1,471 notes, 0 orphans)
 Edges:    267,581
 Density:  0.124
 Edge types:  tag_overlap: 261,722  wikilink: 2,505  related_to: 572
 Broken links: 0
```

1,471 notes. 267K connections. Zero broken links. Every note knows its neighbors.

## 60-Second Demo

```
# What does a project affect? Data Platform Migration note?
$ keppi blast-radius "Data Platform Migration" --depth 2

Blast Radius: Data Platform Migration (depth=2)
Seed: entities/Data Platform Migration

  1. Job Search              relevance=0.89  distance=1
  2. Cloud Vendor           relevance=0.82  distance=1
  3. Cloud Analytics             relevance=0.71  distance=1
  4. Client Contract                 relevance=0.68  distance=1
  5. Integration Project                 relevance=0.65  distance=1
  6. Family Plans     relevance=0.61  distance=1
  7. Career                 relevance=0.58  distance=1
  8. Compliance                 relevance=0.55  distance=2
  9. CRM Platform             relevance=0.42  distance=2
 10. Expertise Reversal      relevance=0.31  distance=2
```

That's not search. That's **knowing which notes matter** for a decision you're about to make. A data platform migration affects your job search, your client contracts, your integration project, and your family's plans. All from one query.

## Where It Extends Karpathy's Vision

Karpathy's LLM Wiki has three layers: raw sources → wiki → schema. The missing piece is the **graph layer** between wiki and query.

```
Raw Sources  →  Wiki  →  ┌─────────────┐  →  Context Pack
  (immutable)   (LLM-owned)  │  Keppi Graph  │     (for AI)
                              └─────────────┘
                                    │
                          ┌─────────┼─────────┐
                          │         │         │
                     blast-radius  gaps  communities
                     traverse     orphans  drift
                     context-pack  hubs   suggest-links
```

The wiki is the *what*. Keppi is the *how everything connects*. Without the graph, you're doing keyword search on a wiki. With it, you're doing relevance-ranked traversal that understands which connections carry weight.

**What this enables that similarity search can't:**

| Question | Similarity Search | Graph Traversal |
|----------|------------------|-----------------|
| "What does a data platform migration affect?" | Pages containing "migration" or "platform" | Job Search → Career → Cloud Vendor → Integration Project → Compliance → Client Contract |
| "What's connected to Cloud Analytics?" | Pages mentioning "Cloud Analytics" | Data Pipeline → Cloud DB → Data Governance → Integration Project → Vendor Alpha |
| "What haven't I connected?" | Can't detect | Gaps between clusters, orphan notes |

## Features

### Core Commands

```bash
keppi init                              # Auto-detect vault, write config
keppi build ~/Documents/Obsidian\ Vault  # Parse & build graph
keppi stats ~/Documents/Obsidian\ Vault   # Node/edge/density summary

# Analysis
keppi blast-radius "Data Pipeline" --depth 2
keppi traverse "Cloud DB" --depth 3
keppi path "Cloud Analytics" "Career"
keppi context-pack "data lakehouse" --budget 4000
keppi communities
keppi gaps
keppi hubs
keppi bridges
keppi orphans
keppi drift

# Search & Links
keppi search "databricks"
keppi broken-links
keppi suggest-links "Cloud Vendor"

# Config
keppi config get vault.exclude_dirs
keppi config add vault.exclude_dirs "_archive"
keppi config set graph.relevance_threshold 0.5
```

### MCP Server (Claude Desktop, Cursor)

```bash
keppi install claude    # Auto-configure for Claude Desktop
keppi install cursor    # Auto-configure for Cursor
```

20+ graph-aware tools available to any MCP-compatible AI assistant: `blast_radius`, `context_pack`, `find_gaps`, `suggest_links`, `keyword_search`, and more.

For other MCP clients (OpenClaw, etc.), use `keppi mcp-server /path/to/vault` and configure manually.

### Coming Soon

```bash
# Interactive visualization (FR-002, in development)
keppi visualize "Data Platform Migration" --depth 2 --output migration.html --open
```

Generates an interactive HTML graph you can drag, zoom, and filter. Color-coded by node type, edge-weighted by relationship type.

---

## Installation

```bash
pip install keppi
```

Or with `uv`:

```bash
uv tool install keppi
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
keppi blast-radius "some concept" ~/Documents/Obsidian\ Vault
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

---

## Acknowledgments

Keppi extends the ideas in [Karpathy's LLM Wiki](https://github.com/karpathy/llm.wiki) — the insight that you should compile raw notes into a structured wiki and query the wiki instead of re-reading sources. We add the graph layer that makes that approach scale beyond a few hundred notes.

The name **Keppi** (קעפּי) is the Yiddish diminutive of *kop* (head). A little head that finds connections others miss.