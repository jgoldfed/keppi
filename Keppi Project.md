---
type: project
subtype: tool
status: active
updated: 2026-04-30
created: 2026-04-29
tags: [project, keppi, knowledge-graph, mcp, open-source, tool-building]
related_to:
  - "[[Context Engineering]]"
  - "[[Vibe Coding]]"
  - "[[Builder to Architect Shift]]"
url: "https://github.com/tirth8205/code-review-graph"
---

# Keppi — Knowledge Engine for Precise Pattern Intelligence

> **Your yidishe kop for your second brain.**

## The Name

**Keppi** stands for **Knowledge Engine for Precise Pattern Intelligence** — the public acronym. Every letter means something specific to the product:

- **K**nowledge — your vault, your notes, your second brain
- **E**ngine — it computes, traverses, analyzes. Not a viewer, an engine.
- **P**recise — not "read everything," but read *exactly what matters*. Precise context.
- **P**attern — it finds patterns: communities, gaps, hubs, bridges, drift. Pattern intelligence.
- **I**ntelligence — blast radius, context packs, suggestions. It doesn't just map — it reasons.

There's also a personal layer. *Keppi* (קעפּי) is the Yiddish diminutive of *kop* — "little head." A *yidishe kop* is someone who finds the connections others miss. That's exactly what this tool does. The name works on both levels.

## What It Does

Parses any Obsidian vault (or directory of markdown files) into a structural graph, then serves **blast-radius analysis**, **context packs**, **gap detection**, and **graph queries** via CLI and MCP.

**Three killer features:**

1. **Blast radius for ideas** — When a concept changes, trace every wikilink, backlink, and tag overlap to compute which notes are affected. "I updated my understanding of Medallion Architecture" → returns Meridian Partners, Project Atlas, Data Integration Patterns, Databricks.

2. **Context packs** — Instead of dumping your whole vault (20K+ tokens), give the AI exactly the 8 most relevant notes (~4K tokens) for the topic. Token-budgeted, prioritized by edge weight and centrality.

3. **Gap detection** — Find idea clusters with no bridges between them. "Your career notes and your technical practice notes never cross-reference, even though they should."

## Inspiration

Inspired by [code-review-graph](https://github.com/tirth8205/code-review-graph) which does this for codebases. Keppi does it for knowledge bases — the same blast-radius concept, but for ideas instead of functions.

Karpathy's LLM Wiki pattern (compile raw sources into a structured wiki, query the wiki) validated the market. Keppi solves the scaling problem that pattern creates: at 500+ notes, the wiki itself becomes too large for a single context window. Keppi is the query engine that makes Karpathy's wiki scale.

## Key Design Principles

- **Convention over configuration** — Use what's already in your vault (frontmatter, wikilinks, tags). Don't require a new schema.
- **User-configurable prerequisites** — Any required conventions are set by the user in `keppi.toml`, not imposed by the tool.
- **Local-first, private** — No data leaves your machine. No cloud APIs for core operations.
- **MCP-native** — First-class MCP server so any AI assistant (Claude, Cursor, OpenClaw, Codex) can query the graph.
- **Works with any markdown** — Optimized for Obsidian but not limited to it. Zero-config mode works on any directory of `.md` files.

## Tech Stack

Python 3.10+, NetworkX, SQLite, python-frontmatter, typer, watchdog, rich. MCP server via FastMCP.

## Project Files

- [[Keppi Project]] — This overview (you are here)
- [[PROJECT]] — Full design spec: architecture, data model, all 28+ MCP tools, config schema, competitive analysis, market analysis, plugin architecture, 5-phase build plan
- [[PRPs/keppi-phase1|Phase 1 PRP]] — Product Requirements Prompt for building Phase 1 MVP. The actual prompt you'd paste into Windsurf or Claude Code. Includes real vault examples, code patterns, implementation steps, validation criteria, and gotchas.

## Phase 1 MVP Scope

1. Parse vault → build graph (SQLite + NetworkX)
2. CLI: `init`, `build`, `update`, `stats`, `blast-radius`, `traverse`, `search`, `orphans`
3. File watcher for incremental updates
4. Works on any Obsidian vault with zero configuration

## Status

**Phase: MCP Server Built** — Phase 3 complete. CLI + analysis + MCP server working. Testing and refinement in progress.

---

*Last updated: 2026-04-30*