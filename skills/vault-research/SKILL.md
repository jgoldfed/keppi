---
name: vault-research
description: >
  Deep evidence research across the Obsidian vault using Keppi MCP tools and the
  Obsidian CLI. Use when wiki-search has been tried and is insufficient — raw meeting
  transcripts, comprehensive multi-note analysis, or when the wiki has no coverage.
  NOT for quick entity/concept lookups — use wiki-search for those. Triggers:
  "find everything about X across my notes", "what did we discuss in meetings about Y",
  "give me the full picture on Z", any question requiring 4+ raw note reads.
---

# Vault Research (Deep)

Comprehensive vault research using Keppi MCP tools for graph navigation and note
reading via the best available method. Use this when wiki-search is insufficient.

**Keppi calls use MCP tools directly** — not bash, not CLI.
**Note reading** uses the best available tool in priority order — see Tool Availability below.

---

## Tool Availability — Check First

Before starting, determine what tools are available. This controls the read strategy.

| Situation                                    | Read Strategy                                          |
| -------------------------------------------- | ------------------------------------------------------ |
| Desktop Commander + obsidian-cli available   | Use `obsidian read` via DC (preferred)                 |
| Desktop Commander available, no obsidian-cli | Use `Desktop Commander:read_file` with full vault path |
| Neither available                            | Use `keppi:context_pack` only — no direct reads        |

**To check vault path** (needed for read_file fallback):

```
Desktop Commander:start_process
  command: obsidian vault info=path
  shell: powershell.exe
  timeout_ms: 8000
```

Returns something like `C:\Users\username\Documents\Obsidian Vault`.
Store this — you'll need it to build full paths for `read_file`.

---

## When to Use This Skill

- Deep evidence retrieval from raw meeting transcripts
- Comprehensive analysis requiring 4+ note reads
- Questions that need specific quotes or step-by-step reconstruction
- The wiki has no coverage or is stale for this topic
- "Summarize everything across all my notes about X"

## Try wiki-search First

If the question is about a known entity, person, project, or concept, **try wiki-search
first**. It answers 80% of queries in 2-3 reads at 1/10th the token cost.
Come here when wiki-search sends you — or when you know you need raw source depth.

---

## Steps

### Step 0 — Quick Wiki Check

Even for deep research, check the wiki first. It may have a synthesis that reframes
what you need from raw notes. Wiki reads are ~400 tokens vs 3,000–8,000 for transcripts.

```
Desktop Commander:start_process
  command: obsidian read file=index
  shell: powershell.exe
  timeout_ms: 8000
```

If a relevant wiki page exists, read it. Use it as a **map** for the raw note reads
ahead — the `sources:` frontmatter field tells you exactly which raw notes to target.

---

### Step 1 — Find Entry Points

```python
keppi:keyword_search(query="<topic keywords>", limit=5)
```

Run 1-2 targeted searches. Keep queries to 2-4 words. Keep `limit` at 5 or below —
on a 2,600+ node vault, larger limits return more payload with diminishing value.
Each query must be meaningfully different — repeating terms returns the same results.

---

### Step 2 — Trace Connections (Blast Radius)

```python
keppi:blast_radius(note="<TopResultNote>", depth=2)
```

This gives you the structural map — which notes are connected and how strongly.
`related_to` edges (weight 2.0) are more meaningful than tag overlaps (weight 0–0.5).
Use depth=2; depth 3+ gets noisy and slow on large vaults.

> **Performance note:** Avoid `keppi:query_node` unless you specifically need full
> inbound + outbound edge metadata. On a 2,600+ node vault it returns 150+ edges
> (large payload, slow). `blast_radius` is faster and gives you the structure you need.

---

### Step 3 — Build the Context Pack

```python
keppi:context_pack(query="<topic>", budget=8000)
```

Keppi selects the minimal set of notes fitting within the token budget, ranked by
relevance to the query. This is your reading list.

**Token budget guide:**

| Scope                        | Budget        |
| ---------------------------- | ------------- |
| Quick deep-dive              | 4,000         |
| Standard research            | 8,000         |
| Comprehensive analysis       | 12,000–16,000 |
| Full context (use sparingly) | 20,000+       |

**No Desktop Commander / obsidian-cli?** Stop here. The context pack itself contains
the note content — synthesize directly from it without separate reads.

---

### Step 4 — Read the Notes

Read each note from the context pack via the best available method, highest relevance first.

#### Option A: obsidian-cli via Desktop Commander (preferred)

**CRITICAL: Always use `shell: powershell.exe` — not `shell: cmd`.**
CMD truncates arguments at the first space, breaking all filenames with spaces.
PowerShell handles spaces correctly when using single-quoted arguments.

Single-word names:

```
Desktop Commander:start_process
  command: obsidian read file=NoteName
  shell: powershell.exe
  timeout_ms: 10000
```

Names with spaces — wrap the entire argument in single quotes:

```
Desktop Commander:start_process
  command: obsidian read 'file=Note Name With Spaces'
  shell: powershell.exe
  timeout_ms: 10000
```

Read by exact vault-relative path (also handles spaces correctly in PowerShell):

```
Desktop Commander:start_process
  command: obsidian read path=1-Projects/DGEA/Some Note With Spaces.md
  shell: powershell.exe
  timeout_ms: 10000
```

#### Option B: Desktop Commander read_file (fallback — no obsidian-cli needed)

Use `Desktop Commander:read_file` with the full Windows path. Handles spaces natively.
Build the path as: `<vault_path>\<relative_path_from_keppi_result>`

Example:

```
Desktop Commander:read_file
  path: C:\Users\username\Documents\Obsidian Vault\1-Projects\DGEA\2025-12-16 Meeting.md
```

The exact relative path comes from the `path` field in keppi search/blast_radius results.

#### Option C: No Desktop Commander — keppi:context_pack only

Skip Step 4 entirely. The context pack from Step 3 contains the note content.
Synthesize directly from that output.

---

### Step 5 — Synthesize

Combine graph structure (blast radius relevance scores) with note content to answer
the question. Cite notes by title. If the research reveals new cross-connections not
in the wiki, note them — they're candidates for a wiki update.

---

### Step 6 — Promotion Rule: Close the Wiki Gap

Deep research often surfaces facts that should live in the wiki, not just in your answer. Every time you had to read 4+ raw notes to assemble an answer, the wiki needs updating.

**The rule:** If you assembled facts from multiple raw notes that would have answered the question on their own, promote them. The wiki is a queryable facts layer, not a summary layer.

| Promote to wiki | Leave in raw notes |
|---|---|
| Key facts, figures, pricing, dates | Full meeting transcripts |
| Status, decisions, outcomes | Detailed context and quotes |
| Strategy summaries | Step-by-step reasoning |
| Anything you'll query again | One-time reference material |

**How to promote:**
1. After synthesizing your answer, identify the 1-3 key facts that required raw note reads
2. Add them as a concise section to the relevant wiki page (e.g., `## Pricing`, `## Key Dates`, `## Status`)
3. Add a wikilink to each source note: `Source: [[Source Note Name]]`
4. Result: next query on this topic resolves in a single wiki read (~400 tokens) instead of a full research pass (~8,000–16,000 tokens)

**Example:** A "summarize everything about the Cetera project" query required reading 5 raw meeting notes. The key facts — contract status, deliverables, deadlines — get promoted to the `Cetera` wiki page. Next time, the wiki fast lane answers the factual questions; only deep evidence retrieval needs the research path.

---

## Obsidian CLI Quick Reference

```
Desktop Commander:start_process
  command: obsidian <command> <args>
  shell: powershell.exe   ← ALWAYS PowerShell. CMD truncates on spaces.
  timeout_ms: 10000
```

| Purpose                 | Command                                             |
| ----------------------- | --------------------------------------------------- |
| Get vault path          | `obsidian vault info=path`                          |
| Read wiki index         | `obsidian read file=index`                          |
| Read note (no spaces)   | `obsidian read file=NoteName`                       |
| Read note (with spaces) | `obsidian read 'file=Note Name'`                    |
| Read by exact path      | `obsidian read 'path=1-Projects/DGEA/Note Name.md'` |
| Search for path         | `obsidian search 'query=Note Title' limit=1`        |

---

## Keppi MCP Tools Used in This Skill

| Tool                   | Use                                          | Performance                                                        |
| ---------------------- | -------------------------------------------- | ------------------------------------------------------------------ |
| `keppi:keyword_search` | Find entry-point notes by keyword            | Fast — use limit=5                                                 |
| `keppi:blast_radius`   | Map structural connections from a seed note  | Moderate                                                           |
| `keppi:context_pack`   | Token-budgeted reading list with content     | Moderate                                                           |
| `keppi:query_node`     | Full graph metadata + all edges for one note | **Slow on large vaults** — avoid unless you need the raw edge list |

---

## Performance Rules

- **Prefer `keyword_search` + `blast_radius` over `query_node`** — query_node on a
  2,600+ node vault returns 150+ edges (large payload, slow round-trip over MCP).
- **Keep `keyword_search` limit ≤ 5** — more results = more MCP payload for little gain.
- **Keep `blast_radius` depth ≤ 2** — depth 3+ fans out to thousands of nodes.
- **Wiki reads are cheap** — ~400 tokens vs 3,000–8,000 for a raw transcript. Always
  try the wiki fast lane before committing to raw note reads.
- **context_pack with a tight budget** is better than reading 10 raw notes individually.
- **Promote key facts after deep research** — if you assembled an answer from 4+ raw notes, add the key facts to the relevant wiki page. Next query resolves at wiki-lane cost (~400 tokens) instead of a full research pass (~8,000–16,000 tokens).

---

## Important Notes

- **Try wiki-search first** — if the topic has a wiki page, save 80% of the tokens
- **Keppi MCP tools, not bash** — `keppi:keyword_search`, not `keppi search ...`
- **Always `shell: powershell.exe`** — CMD truncates filenames at spaces
- **Single-quote space-containing args** — `'file=Note Name'` not `file="Note Name"`
- **read_file is your spacing fallback** — when obsidian-cli chokes, use DC:read_file
  with the full vault path
- **context_pack is your no-DC fallback** — synthesize from it directly if no file reads available
- **Cite note titles** in your answer so sources are traceable
