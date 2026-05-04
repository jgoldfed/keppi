---
type: project
subtype: tool
status: active
updated: 2026-04-30
created: 2026-04-29
tags: [project, keppi, knowledge-graph, mcp, open-source, architecture, spec]
related_to:
  - "[[Keppi Project]]"
  - "[[Context Engineering]]"
  - "[[Vibe Coding]]"
---

# Keppi — Knowledge Engine for Precise Pattern Intelligence

> Stop burning tokens. Start querying smarter.

## The Name

**Keppi** stands for **Knowledge Engine for Precise Pattern Intelligence**.

- **K**nowledge — your vault, your notes, your second brain
- **E**ngine — it computes, traverses, analyzes. Not a viewer, an engine.
- **P**recise — not "read everything," but read *exactly what matters*. Precise context.
- **P**attern — it finds patterns: communities, gaps, hubs, bridges, drift. Pattern intelligence.
- **I**ntelligence — blast radius, context packs, suggestions. It doesn't just map — it reasons.

There's also a personal layer. *Keppi* (קעפּי) is the Yiddish diminutive of *kop* — "little head." A *yidishe kop* is someone who finds the connections others miss. That's exactly what this tool does. The name works on both levels.

**Tagline:** *Your yidishe kop for your second brain.*

**Public acronym:** Knowledge Engine for Precise Pattern Intelligence.
**Personal story:** It also sounds like the Yiddish word my grandmother used for "little head" — and a yidishe kop finds the connections nobody else sees.

## The Pitch (with Karpathy)

Karpathy showed us how to compile knowledge: dump everything in `/raw`, have an LLM incrementally compile it into a structured wiki, then query the wiki instead of re-reading raw sources. "Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase."

This works beautifully at 100 notes. At 1000+, the wiki itself becomes too large for a single context window. You're back to guessing what context to load.

**Keppi is the query engine that makes Karpathy's wiki scale.** It maps your wiki's structure, computes blast radius, generates context packs, detects gaps, and serves it all to AI assistants via MCP.

Karpathy built the compiler. Keppi built the index.

> The code-review-graph for knowledge bases. Build a structural map of your notes, trace impact chains, and give AI assistants precise context instead of dumping everything.

## The Problem

AI assistants working with personal knowledge bases (Obsidian vaults, Zettelkastens, PKM systems) face the same token-waste problem that code-review-graph solves for code:

1. **Full-vault dumps are expensive.** Every time you ask an AI a question about your knowledge, it either reads everything (expensive, slow) or reads nothing (shallow, wrong).
2. **Search isn't traversal.** Semantic search finds similar notes, but doesn't trace relationship chains: "This concept is related to these three people, who are connected to these two projects, which affects this decision."
3. **No impact analysis.** When a concept in your knowledge base changes (new understanding, corrected fact, shifted strategy), there's no way to compute which other notes are affected. The "blast radius" of an idea.
4. **Existing tools are half-measures.** InfraNodus detects gaps but doesn't serve AI context. Smart Connections does semantic search but not graph traversal. Graphiti builds temporal graphs from conversations but doesn't parse existing vault structures.

## The Solution

A tool that:

1. **Parses your vault** into a graph of entities, concepts, and their relationships (using frontmatter, wikilinks, tags -- the structure you already have)
2. **Traces blast radius** when a concept changes: follow all wikilinks out, backlinks in, and tag overlaps to compute the minimal set of affected notes
3. **Serves precise context** to any AI assistant via MCP: "What do I need to read about topic X?" returns a curated subgraph, not a keyword dump
4. **Detects structural gaps** like InfraNodus, but as queryable data for AI, not just visualizations
5. **Is user-agnostic**: works with any Obsidian vault (or any directory of markdown files) given a minimal configuration

## Design Principles

- **Convention over configuration**: Use what's already in your vault (frontmatter, wikilinks, tags). Don't require a new schema.
- **User-configurable prerequisites**: Any required conventions (tag format, frontmatter fields, directory structure) are set by the user during setup, not imposed by the tool.
- **Incremental, not batch**: Parse once, update on file changes (like code-review-graph's git hooks, but for note saves).
- **Local-first, private**: No data leaves your machine. No cloud APIs required for core graph operations. Embeddings optional (for semantic search, can use local models).
- **MCP-native**: First-class MCP server so any AI assistant (Claude, Cursor, OpenClaw, Codex) can query the graph.
- **Obsidian-native but not Obsidian-exclusive**: Optimized for Obsidian vault structure (wikilinks, frontmatter, tags) but works with any markdown directory.

---

## Architecture

### Three Layers (Same Pattern as code-review-graph)

```
┌─────────────────────────────────────────────────┐
│              MCP Server (28+ tools)              │
│   blast_radius, traverse, search, gaps, ...     │
├─────────────────────────────────────────────────┤
│              Graph Engine (SQLite)               │
│   Nodes (notes, entities, concepts)             │
│   Edges (wikilinks, tags, references)           │
│   Metadata (frontmatter, file stats)            │
├─────────────────────────────────────────────────┤
│              Parser Layer                        │
│   Markdown → Frontmatter → Wikilinks → Tags     │
│   Incremental update on file change              │
└─────────────────────────────────────────────────┘
```

### Data Model

#### Nodes (from markdown files)

Every parsed markdown file becomes a node with:

| Property | Source | Example |
|----------|--------|---------|
| `id` | File path (relative to vault root) | `wiki/entities/Meridian Partners.md` |
| `title` | First H1 or filename | `Meridian Partners` |
| `type` | Frontmatter `type` field (if exists) | `entity` |
| `subtype` | Frontmatter `subtype` field (if exists) | `company` |
| `status` | Frontmatter `status` field (if exists) | `active` |
| `tags` | Frontmatter `tags` + inline `#tags` | `[wiki, entity, snowflake]` |
| `aliases` | Frontmatter `aliases` | `[MP, Meridian Partners]` |
| `word_count` | Body word count | `423` |
| `updated` | File mtime or frontmatter `updated` | `2026-04-28` |
| `content_hash` | SHA-256 of file content | `a3f2...` |
| `outbound_links` | Parsed `[[wikilinks]]` | `[[Snowflake]], [[Nexus Consulting]]` |
| `headings` | Parsed `## Heading` structure | `[Summary, Key Facts, ...]` |

#### Edges (relationships between notes)

| Edge Type | Source | Direction | Weight |
|-----------|--------|-----------|--------|
| `wikilink` | `[[Note Name]]` in body | Source → Target | 1 (existence), 0.5 (broken/unresolved) |
| `related_to` | Frontmatter `related_to` | Bidirectional | 2 (explicit semantic link) |
| `tag_overlap` | Shared tags | Bidirectional | Jaccard coefficient of tag overlap |
| `folder_proximity` | Same directory | Bidirectional | 0.3 (weak structural signal) |
| `backlink` | Reverse of wikilink | Target → Source | Same as wikilink weight |
| `embed` | `![[Note]]` transclusion | Source → Target | 1.5 (stronger than link) |

### Graph Operations

#### 1. Blast Radius (Impact Analysis)

**The killer feature.** Given a set of changed notes, compute all notes that could be affected.

```
blast_radius(changed_notes, depth=2) → Set of affected notes
```

Algorithm:
1. Start with changed notes as seed set
2. For each seed, follow all outbound edges (wikilinks, related_to) → direct dependents
3. For each seed, follow all inbound edges (backlinks) → direct dependencies
4. Recurse up to `depth` hops
5. Weight edges by type: `related_to` (2.0) > `embed` (1.5) > `wikilink` (1.0) > `tag_overlap` (0.5)
6. Return notes above a configurable relevance threshold

**Use case:** "I just updated my understanding of Medallion Architecture. What else in my vault is affected?" → Returns Meridian Partners, Project Atlas, Data Integration Patterns, Databricks -- the actual blast radius of the idea change.

#### 2. Context Pack (Minimal Reading Set)

**The token-saver.** Given a topic, compute the minimal set of notes an AI needs to read.

```
context_pack(topic, token_budget=4000) → Ordered list of notes with excerpts
```

Algorithm:
1. Find the most relevant seed note(s) for the topic (semantic + keyword search)
2. Expand via blast_radius from seeds, but with a token budget constraint
3. Prioritize by: edge weight × node centrality × recency
4. Return ordered list with key excerpts (not full file contents)
5. Total tokens stay within budget

**Use case:** Instead of feeding 59 wiki pages (probably 20K+ tokens) to an AI, feed it exactly the 8 most relevant pages (~4K tokens) that cover the topic.

#### 3. Gap Detection (Structural Blind Spots)

**The InfraNodus feature, but queryable.** Find idea clusters with no bridges.

```
detect_gaps(min_cluster_size=3) → List of gap descriptions
```

Algorithm:
1. Run community detection (Louvain) on the graph
2. Find communities with zero or weak cross-community edges
3. For each gap, identify the two clusters and what they have in common (shared tags, overlapping concepts)
4. Generate gap description: "Cluster A (career, interviewing) and Cluster B (databricks, snowflake) share the tag #data but have no wikilinks between them"

**Use case:** "Where are my knowledge blind spots?" → Identifies that your career strategy notes and your technical practice notes never cross-reference, even though they should.

#### 4. Traverse (Graph Navigation)

```
traverse(start_note, direction="both", max_depth=3, edge_types=["wikilink", "related_to"]) → Subgraph
```

#### 5. Hub & Bridge Analysis

- **Hub nodes**: High degree centrality (notes that connect many other notes -- your "keystone" ideas)
- **Bridge nodes**: High betweenness centrality (notes that connect otherwise separate clusters -- your "boundary spanners")
- **Orphan nodes**: No inbound or outbound edges (notes nobody references -- potential dead ends or hidden gems)

#### 6. Community Detection

Run Louvain/Leiden to find topical clusters in your vault. Each community becomes a "knowledge neighborhood."

#### 7. Temporal Drift

Track which notes are stale (not updated recently, but connected to recently-updated notes). These are candidates for review: "Your understanding of X changed last week, but this note about Y still assumes the old understanding."

---

## MCP Tools (28+ tools)

### Core Graph Tools

| Tool | Description |
|------|-------------|
| `build_or_update_graph` | Parse vault and build/update the graph |
| `get_graph_stats` | Node count, edge count, community count, orphans, etc. |
| `query_graph` | Get node details, neighbors, edges for a specific note |

### Context & Impact Tools

| Tool | Description |
|------|-------------|
| `get_blast_radius` | Impact analysis: what notes are affected by changes to these notes? |
| `get_context_pack` | Token-budgeted minimal reading set for a topic or question |
| `get_review_context` | Like context_pack but optimized for reviewing/updating a specific note |

### Navigation Tools

| Tool | Description |
|------|-------------|
| `traverse_graph` | BFS/DFS traversal from any node with depth/edge-type filters |
| `find_path` | Shortest path between two notes (how are these ideas connected?) |
| `find_hubs` | Most-connected notes (keystone ideas) |
| `find_bridges` | Notes connecting separate clusters (boundary spanners) |
| `find_orphans` | Notes with no connections (dead ends or hidden gems) |

### Analysis Tools

| Tool | Description |
|------|-------------|
| `detect_gaps` | Structural gaps between idea clusters |
| `detect_communities` | Topical clusters in the vault |
| `get_community_details` | Detailed view of a specific community |
| `detect_drift` | Stale notes connected to recently-updated notes (temporal drift) |
| `get_surprising_connections` | Notes connected despite being in different communities |
| `get_knowledge_gaps` | Unconnected notes that probably should be (based on tag/content overlap) |

### Search Tools

| Tool | Description |
|------|-------------|
| `semantic_search` | Search notes by meaning (requires embeddings, optional) |
| `keyword_search` | Search notes by keyword/phrase |
| `tag_search` | Search notes by tag |
| `hybrid_search` | Combine semantic + keyword + tag search |

### Maintenance Tools

| Tool | Description |
|------|-------------|
| `list_stale` | Notes not updated in N days |
| `list_unlinked` | Notes with zero inbound/outbound edges |
| `list_broken_links` | Wikilinks pointing to non-existent notes |
| `suggest_links` | Notes that should probably link to each other (based on content/tag overlap) |
| `generate_wiki_page` | Auto-generate a summary wiki page for a community or cluster |

### Multi-Vault Tools

| Tool | Description |
|------|-------------|
| `list_vaults` | List registered vaults |
| `cross_vault_search` | Search across multiple vaults |
| `cross_vault_gaps` | Gaps between vaults |

---

## User Configuration (config.toml)

The tool must be user-configurable with zero assumptions about vault structure. Everything is declared:

```toml
# keppi.toml - placed in vault root or specified via --config

[vault]
path = "/path/to/vault"           # or "." for current directory
file_extensions = [".md"]         # file types to index
exclude_dirs = [".obsidian", ".git", "templates"]
exclude_patterns = ["*.excalidraw.md"]  # glob patterns to skip

[frontmatter]
# Map frontmatter fields to graph properties
# User declares which fields exist and what they mean
type_field = "type"               # frontmatter key for node type (e.g., entity/concept/synthesis)
subtype_field = "subtype"         # frontmatter key for subtype (e.g., person/company/idea)
status_field = "status"           # frontmatter key for lifecycle status
updated_field = "updated"         # frontmatter key for last-updated date
tags_field = "tags"               # frontmatter key for tags
aliases_field = "aliases"         # frontmatter key for aliases
related_field = "related_to"      # frontmatter key for explicit relationships
sources_field = "sources"         # frontmatter key for source references
url_field = "url"                 # frontmatter key for external URLs

# Set to false to disable if your vault doesn't use these
type_field = false               # no type classification in this vault
status_field = false              # no status tracking

[links]
wikilink_pattern = "\\[\\[([^\\]]+)\\]"  # regex for wikilinks
embed_pattern = "!\\[\\[([^\\]]+)\\]"   # regex for embeds/transclusions
resolve_strategy = "title"        # "title" = match by note title, "path" = match by file path
case_sensitive = false            # wikilink resolution case sensitivity

[tags]
# How tags appear in your vault
inline_tags = true                # parse #tags from body text
frontmatter_tags = true           # parse tags from frontmatter
nested_separator = "/"           # for tags like "project/active"

[graph]
# Edge weight configuration
wikilink_weight = 1.0
embed_weight = 1.5
related_to_weight = 2.0
tag_overlap_weight = 0.5
folder_proximity_weight = 0.3

# Community detection
community_algorithm = "louvain"   # "louvain" or "leiden"
min_community_size = 3

# Blast radius defaults
default_depth = 2
relevance_threshold = 0.3

[embeddings]
enabled = false                   # set true for semantic search
model = "all-MiniLM-L6-v2"       # sentence-transformers model (local)
# or for API embeddings:
# provider = "openai"
# model = "text-embedding-3-small"
# api_key_env = "OPENAI_API_KEY"  # env var name for API key

[storage]
graph_db = "~/.keppi/graphs/{vault_hash}.db"  # SQLite database location
content_cache = true              # cache file contents for faster queries
cache_max_age_days = 30

[mcp]
name = "keppi"                    # MCP server name
port = 0                         # 0 = stdio, >0 = SSE on that port

[watch]
enabled = true                    # auto-update on file changes
debounce_ms = 2000               # wait 2s after last change before re-indexing
ignore_patterns = [".obsidian/*"]
```

### Zero-Config Mode

If no `keppi.toml` exists, the tool runs with sensible defaults:
- Scan all `.md` files in current directory (recursively)
- Parse wikilinks, frontmatter tags, inline tags
- No type/subtype classification (all nodes are type "note")
- Standard edge weights
- No embeddings (keyword + graph search only)
- SQLite DB in `~/.keppi/graphs/`

This means it works out of the box with ANY Obsidian vault, or any directory of markdown files.

---

## Technical Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.10+ | Same as code-review-graph; broad ecosystem |
| Package manager | uv | Fast, modern, same as code-review-graph |
| Graph engine | NetworkX + SQLite | NetworkX for in-memory graph algorithms, SQLite for persistent storage |
| Markdown parsing | python-frontmatter + regex | Parse YAML frontmatter + extract wikilinks/tags |
| Community detection | python-louvain or networkx.community | Louvain/Leiden algorithm |
| Embeddings (optional) | sentence-transformers | Local, free, no API key needed |
| MCP server | FastMCP or mcp-python-sdk | Standard MCP implementation |
| File watching | watchdog | Cross-platform file change detection |
| CLI | click or typer | Clean CLI interface |

### Why Not Neo4j / Heavy Graph DB?

- SQLite is file-based, zero-config, portable. Users don't need to run a database server.
- NetworkX handles graphs up to ~100K nodes in memory easily. Our vaults are 500-5000 notes.
- For the target scale (personal knowledge bases), SQLite + NetworkX is the right tool. Not enterprise infrastructure.

---

## CLI Commands

```bash
# Setup
keppi init                         # Interactive setup wizard → creates keppi.toml
keppi init --quick                  # Zero-config defaults, no prompts

# Build
keppi build                        # Parse vault and build graph
keppi build --vault /path/to/vault # Specify vault path
keppi build --full                  # Force full rebuild (not incremental)

# Update
keppi update                       # Incremental update (only changed files)

# Watch (daemon mode)
keppi watch                        # Start file watcher daemon
keppi watch --stop                 # Stop watcher

# Query
keppi blast-radius "Medallion Architecture"    # What's affected by this concept?
keppi context-pack "job search"               # What should I read about this topic?
keppi gaps                                     # Where are the structural gaps?
keppi traverse "Databricks" --depth 3          # Navigate from this note
keppi hubs                                     # What are my keystone notes?
keppi orphans                                  # What notes have no connections?
keppi path "Databricks" "Career Positioning"   # How are these connected?
keppi drift                                    # What's stale but connected to recent changes?

# Search
keppi search "snowflake migration"            # Hybrid search
keppi search "snowflake" --type semantic       # Semantic only (needs embeddings)
keppi search "interview" --type keyword       # Keyword only

# MCP
keppi mcp                        # Start MCP server (stdio)
keppi mcp --port 3000             # Start MCP server (SSE)

# Analysis
keppi stats                      # Graph statistics
keppi communities                 # List detected communities
keppi broken-links                # Find broken wikilinks
keppi suggest-links               # Suggest missing connections

# Export
keppi export --format json        # Export graph as JSON
keppi export --format graphml     # Export as GraphML (for Gephi, etc.)
keppi export --format obsidian    # Export as Obsidian vault with wikilinks
```

---

## Project Plan

### Phase 1: Foundation (MVP - ~1 week)

**Goal:** Parse a vault, build a graph, answer basic queries.

- [ ] Project scaffold (pyproject.toml, directory structure)
- [ ] Config parser (keppi.toml with defaults)
- [ ] Markdown parser: frontmatter, wikilinks, tags, headings
- [ ] Graph builder: nodes from files, edges from links/tags
- [ ] SQLite persistence: store graph + content hashes for incremental updates
- [ ] CLI: `init`, `build`, `update`, `stats`
- [ ] Basic queries: `blast-radius`, `traverse`, `search` (keyword)

### Phase 2: Intelligence (~1 week)

**Goal:** Add the analysis features that make this genuinely useful.

- [ ] Context pack generation (token-budgeted reading set)
- [ ] Community detection (Louvain)
- [ ] Gap detection (cross-community analysis)
- [ ] Hub/bridge/orphan detection
- [ ] Temporal drift detection
- [ ] Broken link detection
- [ ] Link suggestions (content/tag overlap → "these should probably connect")
- [ ] CLI: all query/analysis commands

### Phase 3: MCP Server (1 week)

**Goal:** Any AI assistant can query the graph.

- [ ] MCP server with all 28+ tools
- [ ] stdio transport (for Claude Desktop, OpenClaw)
- [ ] SSE transport (for remote/web clients)
- [ ] Tool documentation and workflow hints
- [ ] Auto-detect platform and write MCP config (like code-review-graph's `install` command)
- [ ] CLI: `keppi mcp`, `keppi install --platform openclaw`

### Phase 4: Polish & Share (1 week)

**Goal:** Make it something other people can actually use.

- [ ] `keppi init` interactive wizard with vault auto-detection
- [ ] Comprehensive docs (README, usage guide, config reference)
- [ ] PyPI package (`pip install keppi`)
- [ ] Demo vault for testing/documentation
- [ ] GitHub Actions CI (lint, test, build)
- [ ] Contribution guide
- [ ] Blog post / Show HN

### Phase 5: Advanced Features (post-launch)

- [ ] Embedding support (local sentence-transformers + optional API)
- [ ] Multi-vault support
- [ ] Obsidian plugin (visual graph view with gap highlighting)
- [ ] Temporal graph (track how relationships change over time, like Graphiti)
- [ ] Auto-generate wiki pages from community clusters
- [ ] Export to Obsidian canvas format
- [ ] Web UI for graph exploration

---

## File Structure

```
keppi/
├── pyproject.toml
├── README.md
├── LICENSE (MIT)
├── keppi/
│   ├── __init__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py              # click/typer CLI entry point
│   │   ├── build.py
│   │   ├── query.py
│   │   └── mcp_cmd.py
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── markdown.py          # frontmatter + wikilink + tag extraction
│   │   └── config.py            # keppi.toml parser
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── builder.py           # build NetworkX graph from parsed notes
│   │   ├── storage.py           # SQLite persistence layer
│   │   └── incremental.py       # diff-based incremental updates
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── blast_radius.py      # impact analysis
│   │   ├── context_pack.py      # token-budgeted reading set
│   │   ├── communities.py        # Louvain community detection
│   │   ├── gaps.py              # structural gap detection
│   │   ├── centrality.py        # hub/bridge/orphan analysis
│   │   ├── drift.py             # temporal drift detection
│   │   └── suggestions.py       # link suggestions
│   ├── search/
│   │   ├── __init__.py
│   │   ├── keyword.py           # keyword/BM25 search
│   │   ├── semantic.py          # embedding-based search (optional)
│   │   └── hybrid.py            # combined search
│   ├── mcp/
│   │   ├── __init__.py
│   │   └── server.py            # MCP server implementation
│   ├── watch/
│   │   ├── __init__.py
│   │   └── daemon.py            # file watcher daemon
│   └── utils/
│       ├── __init__.py
│       └── tokens.py            # token estimation utilities
├── tests/
│   ├── test_parser.py
│   ├── test_graph.py
│   ├── test_analysis.py
│   ├── test_mcp.py
│   └── fixtures/
│       └── demo_vault/          # test vault with sample notes
└── docs/
    ├── configuration.md
    ├── mcp-tools.md
    ├── cli-reference.md
    └── architecture.md
```

---

## Key Differentiators from Existing Tools

| Feature | Keppi (this) | code-review-graph | Graphiti | InfraNodus | Smart Connections |
|---------|-------------|-------------------|----------|------------|-------------------|
| **Target** | Knowledge bases | Code repos | Conversations | Knowledge bases | Knowledge bases |
| **Graph type** | Semantic + structural | AST (code structure) | Temporal (episodes) | Text network | Embeddings only |
| **Blast radius** | ✅ Concept-level | ✅ Code-level | ❌ | ❌ | ❌ |
| **Context packs** | ✅ Token-budgeted | ✅ Token-budgeted | ❌ | ❌ | ❌ |
| **Gap detection** | ✅ Algorithmic | ❌ | ❌ | ✅ Visual only | ❌ |
| **MCP server** | ✅ 28+ tools | ✅ 28 tools | ✅ | ❌ | ✅ Limited |
| **Local-first** | ✅ | ✅ | ✅ | ❌ Cloud | ✅ |
| **Zero config** | ✅ | ❌ Requires Python + setup | ❌ Requires Docker | ❌ Paid | ❌ Obsidian plugin |
| **Works without Obsidian** | ✅ Any markdown | N/A | N/A | ✅ | ❌ |
| **Temporal drift** | ✅ | ❌ | ✅ | ❌ | ❌ |
| **Link suggestions** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Community detection** | ✅ | ✅ | ❌ | ✅ Implicit | ❌ |

---

## Name

**Keppi** — Knowledge Graph Context Engine

Pronounced "kay-gee-see-ee" or casually "kag-see."

Alternative names considered:
- `notegraph` — too generic
- `vaultgraph` — Obsidian-specific connotation
- `mindmap-mcp` — misleading (not a mind map tool)
- `context-graph` — too vague

Open to better names. The GitHub repo name and PyPI package name need to be available.

---

## Market & Use-Case Analysis

### Primary Users

**The tool is not for casual note-takers. It's for people with 500+ notes who treat their vault as a second brain and regularly ask AI assistants to work with their knowledge.**

#### User Profile 1: AI-Augmented Knowledge Worker
- Structured vault with frontmatter, wikilinks, tags
- Uses Claude/Cursor/OpenClaw daily to work with their knowledge
- Wants "give me exactly what I need about topic X" instead of dumping 20K tokens every conversation
- **Pain is real.** Every session requires deciding what context to load. Blast-radius would save real tokens and time.
- **Size:** ~50-100K globally, growing fast

#### User Profile 2: Researcher/Writer with a Zettelkasten
- Hundreds or thousands of interconnected notes
- Knows notes are connected but can't see the structure
- Wants to find gaps, discover unexpected connections, understand which ideas are central
- InfraNodus serves some of this market (paid, visualization-only) — Keppi serves it with queryable data and AI integration
- **Size:** ~200K globally

#### User Profile 3: Team/Organization Using Obsidian
- Multiple people contributing to a shared vault
- Knowledge gets orphaned, duplicated, or stale without anyone noticing
- Drift detection, orphan detection, and link suggestions surface problems before they compound
- **Size:** ~10-20K orgs

#### User Profile 4: Non-Obsidian Markdown Users
- Academics, developers, writers using plain markdown directories
- Same needs as above but without Obsidian-specific features
- Zero-config mode serves this segment directly
- **Size:** Unknown but large (academics alone who use markdown: potentially millions)

### Market Sizing (Rough)

| Segment | Size | Willingness to Pay |
|---------|------|-------------------|
| Obsidian power users (500+ notes, daily AI) | ~50-100K | Free tool, $5-10/mo for Pro features |
| Zettelkasten/research community | ~200K | Same |
| Teams/orgs using Obsidian | ~10-20K orgs | $10-20/user/mo |
| Non-Obsidian markdown users | Large but fragmented | Free tier gets adoption |

The Obsidian plugin ecosystem has ~2M users. Smart Connections (closest comp) has 200K+ downloads. InfraNodus charges €29/month. The potential user base for "make your knowledge base queryable by AI" is real but fragmented.

### What Keppi Does That Obsidian Doesn't

Obsidian's built-in graph view is **visual** — you can see clusters and orphans, but you can't *query* them. You can't ask:
- "What notes are affected if this concept changes?" (blast radius)
- "What should I read to understand this topic?" (context packs)
- "Where are the structural gaps in my knowledge?" (gap detection)
- "Which notes should connect but don't?" (link suggestions)

The graph is decorative. Keppi makes it computational.

The MCP angle makes it bigger than an Obsidian plugin. Smart Connections gives you semantic search inside Obsidian. Keppi gives you structural graph queries + blast radius + gap detection + AI context management through a protocol any AI tool can speak — Claude Desktop, Cursor, OpenClaw, Codex, wherever you work.

### What Would Make It Take Off

1. **Zero-config experience.** `pip install keppi && keppi build` must just work on any vault. No setup wizard, no config file required. Config is for power users. If it doesn't work instantly, people bounce.

2. **Integration story.** Plug into where people already work. MCP gets Claude Desktop, Cursor, OpenClaw. Obsidian plugin gets the vault UI. VS Code extension gets developers. Each integration multiplies the addressable market.

3. **Aha moment in < 2 minutes.** The first `keppi blast-radius "some concept"` or `keppi gaps` has to deliver something surprising and useful. "Oh, I didn't realize those two ideas were completely disconnected." That's the moment someone tells a friend.

### Competitive Positioning

| Tool | What It Does | What It Doesn't Do |
|------|-------------|-------------------|
| **Obsidian Graph View** | Visual clusters and orphans | Can't query, compute, or serve AI |
| **Smart Connections** | Semantic search (embeddings) | No graph traversal, no blast radius, no gap detection |
| **InfraNodus** | Visual gap detection | Paid, no AI context serving, no MCP, visualization-only |
| **Graphiti MCP** | Temporal knowledge graph from conversations | Doesn't parse existing vaults; builds from scratch from chat |
| **Hybrid Search MCP** | BM25 + semantic search for Obsidian | Still search, not traversal |
| **code-review-graph** | AST graph for codebases | Different domain entirely (inspiration, not competitor) |
| **Keppi (this)** | Structural graph + blast radius + context packs + gap detection + MCP | — |

### Honest Assessment

**For our vault and workflow:** Extremely useful. Solves a real problem encountered every session — deciding what context to load for an AI assistant.

**For the broader community:** Useful but needs zero-config experience and the aha moment to get traction.

**Who uses it:** The intersection of "serious vault" + "uses AI assistants" + "wants structure, not just search." That's 10-50K people today, growing fast as AI-assisted PKM becomes mainstream.

**The risk isn't demand — it's friction.** The tool works, people want it. The risk is that onboarding friction kills adoption before the aha moment. That's why zero-config matters more than any single feature.

**Why it's worth building:**
1. It solves our real problem (would use it daily)
2. It's a portfolio piece demonstrating architecture, MCP, and graph thinking
3. The AI+PKM space is nascent — first mover with a good tool and MCP integration could establish the standard

### Go-To-Market Sketch

1. **Launch on GitHub** with a README that shows the aha moment in the first 30 seconds (`keppi gaps` output on a demo vault)
2. **Post to r/ObsidianMD and r/PKMS** with "I built blast-radius analysis for my notes"
3. **Show HN** with the MCP angle — "Give any AI assistant precise context from your knowledge base"
4. **MCP server registry** — get listed on awesome-mcp-servers and mcpservers.org
5. **Obsidian plugin** — Phase 5, but the integration story multiplies reach
6. **PyPI** — `pip install keppi` needs to be one command

---

## Success Metrics

1. **Token reduction**: On a 500-note vault, a context pack for a specific topic should use 5-10x fewer tokens than feeding the whole vault.
2. **Blast radius accuracy**: When a note changes, the blast radius should include 90%+ of notes a human would identify as affected (high recall, moderate precision is fine).
3. **Build time**: Initial parse of 500 notes < 10 seconds. Incremental update < 2 seconds.
4. **Zero-config works**: `pip install keppi && keppi build` on any Obsidian vault produces a useful graph without configuration.
5. **MCP integration**: Works with Claude Desktop, OpenClaw, and Cursor within 5 minutes of setup.

---

## Obsidian Plugin Architecture (Phase 5)

### Why a Plugin, Not a Rewrite

The Obsidian plugin is the **distribution multiplier**. CLI + MCP gets you 10-50K AI power users. The Obsidian plugin gets you the other 1.9M Obsidian users who never touch a terminal.

But the core engine stays Python. NetworkX doesn't exist in JS. sentence-transformers doesn't exist in JS. The Python ecosystem for graph algorithms and NLP is mature; the JS equivalents are thin or nonexistent. Rewriting the analysis engine in TypeScript would sacrifice correctness and capability for one platform.

**The architecture: TypeScript plugin as UI layer, Python engine as backend, connected via a local HTTP bridge.**

### Architecture

```
┌─────────────────────────────────────────┐
│           Obsidian Plugin               │
│   (TypeScript, views, commands, UI)     │
│                                         │
│   ┌─────────────┐   ┌────────────────┐  │
│   │ Graph View  │   │ Settings Panel │  │
│   │ Panel       │   │ (keppi.toml)    │  │
│   └──────┬──────┘   └───────┬────────┘  │
│          │                  │           │
│          └──────┬───────────┘           │
│                 │                        │
│          ┌──────▼──────┐                │
│          │  Bridge API  │                │
│          │  (HTTP/IPC)  │                │
│          └──────┬──────┘                │
└─────────────────┼────────────────────────┘
                  │
┌─────────────────▼────────────────────────┐
│           Keppi Core (Python)              │
│   (Same codebase — graph engine,         │
│    SQLite, analysis, MCP)                │
│                                          │
│   CLI ─── MCP Server ─── Bridge API      │
└──────────────────────────────────────────┘
```

The plugin handles views, commands, and settings. The Python engine handles graph computation. They communicate through a lightweight FastAPI bridge with 5-6 endpoints.

### Plugin Features

**Core View: Graph Context Panel (sidebar)**
- **Blast radius** — "6 notes affected by changes here" with expandable list
- **Related context** — "Read these 4 notes to understand this topic" (context pack, in-UI)
- **Orphan warning** — "This note has no inbound links" (badge/alert)
- **Gap indicator** — "This cluster has no bridge to your career notes"

**Commands:**
- `Keppi: Show Blast Radius` — modal with ranked affected notes
- `Keppi: Find Gaps` — shows structural gaps with suggestions
- `Keppi: Suggest Links` — "These notes should probably link" with one-click `[[link]]` insertion
- `Keppi: Rebuild Graph` — manual rebuild trigger
- `Keppi: Show Stats` — vault graph statistics

**Settings Panel:**
- All `keppi.toml` options exposed through Obsidian's settings UI
- Embeddings toggle (local sentence-transformers or API)
- Edge weight sliders (visual adjustment for blast radius aggressiveness)
- Engine status indicator (running/stopped/install needed)

### Bridge API

The bridge between the Obsidian plugin and the Python backend. Minimal, ~200 lines of FastAPI.

```
GET  /graph/stats              — node/edge counts, density, orphans
GET  /blast-radius?note=X       — ranked list of affected notes with relevance scores
GET  /context-pack?topic=X     — token-budgeted reading set
GET  /gaps                      — structural gaps between clusters
GET  /search?q=X               — hybrid search results
POST /rebuild                   — trigger graph rebuild
GET  /suggest-links?note=X      — link suggestions for a note
```

### Why Python Backend + TypeScript Plugin (Not Pure TypeScript)

| Approach | Pros | Cons |
|----------|------|------|
| **Pure TypeScript plugin** | No Python dependency, one install | No NetworkX, no sentence-transformers, rewrite entire analysis engine |
| **Python backend + TS plugin** | Leverage Python ecosystem, share core with CLI/MCP | Two processes, need Python installed |
| **WASM-compiled Python** | Single install, no Python needed | Limited library support, complex build, performance issues |
| **Remote API** | No local Python needed | Privacy concerns (vault data over network), latency, requires hosting |

**Python backend + TypeScript plugin is the right call.** This pattern already exists in the Obsidian ecosystem — Smart Connections runs a local embedding server, Excalidraw calls Python for some features. The plugin can manage the Python process lifecycle: check if `keppi` is installed, offer to install via `pip`, start/stop the background process. Users don't need to touch a terminal.

### Plugin Directory Structure

```
obsidian-plugin/
├── src/
│   ├── main.ts              # Plugin entry, settings, commands
│   ├── views/
│   │   ├── BlastRadiusView.ts    # Sidebar panel
│   │   ├── ContextPackView.ts    # Reading set panel
│   │   ├── GapsView.ts           # Gap detection results
│   │   └── StatsView.ts          # Graph statistics
│   ├── bridge.ts            # HTTP client to Python backend
│   ├── settings.ts          # Settings UI (maps to keppi.toml)
│   └── suggestor.ts         # Editor suggestor for link suggestions
├── manifest.json
├── styles.css
├── package.json
├── tsconfig.json
└── esbuild.config.mjs
```

### User Install Flow

**Casual user (Obsidian-first):**
```
1. Install Keppi plugin from Obsidian Community Plugins
2. Plugin detects: "Keppi engine not found. Install now?"
3. Clicks "Install" → plugin runs: pip install keppi (or bundles a Python wheel)
4. Plugin runs: keppi build (first-time graph build, progress bar in UI)
5. Done. Sidebar shows graph stats. Commands available.
```

**Power user (CLI-first):**
```
1. pip install keppi
2. keppi init --quick && keppi build
3. Install Obsidian plugin
4. Plugin auto-detects running engine
```

### Phasing Rationale

**The Obsidian plugin is Phase 5, not Phase 1.** The sequence:

1. **Phase 1-3:** Build the core engine (CLI + analysis + MCP). Make it excellent. Get traction with AI power users via MCP.
2. **Phase 4:** Polish, docs, PyPI, GitHub, Show HN.
3. **Phase 5:** Add the Obsidian plugin as a UI layer on top of the proven engine.

If we build the plugin first, we spend all our time on TypeScript UI work and never get the analysis engine right. The engine is the hard part and the valuable part. The plugin is a viewport.

But it absolutely should become an Obsidian plugin. That's where the 2M users are. The MCP + CLI gets the 10-50K power users. The Obsidian plugin gets the rest.

### Revenue Model (If We Ever Care)

| Tier | Price | What you get |
|------|-------|-------------|
| **Free** | $0 | Full CLI, MCP server, all analysis features, bridge API |
| **Pro** | $5/mo or $40/yr | Obsidian plugin + visualizations + auto-updates |

The CLI and MCP are always free. The plugin is the premium surface because it's where the casual user lives. This is the Smart Connections model (core free, pro features paid) and it works.

---

## License

MIT — Same as code-review-graph. Maximum shareability.

---

*Project spec v1.2 — 2026-04-29 (added market analysis + Obsidian plugin architecture)*
*Author: The Keppi Project*