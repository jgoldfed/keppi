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

Comprehensive vault research using Keppi MCP tools for graph navigation and the
Obsidian CLI for reading. Use this when wiki-search is insufficient.

**Keppi calls use MCP tools directly** — not bash, not CLI.
**All vault reads use the Obsidian CLI** via Desktop Commander with `shell: cmd`.

---

## When to Use This Skill

- Deep evidence retrieval from raw meeting transcripts
- Comprehensive analysis requiring 4+ note reads
- Questions that need specific quotes or step-by-step reconstruction
- The wiki has no coverage or is stale for this topic
- "Summarize everything across all my notes about X"

## Try wiki-search First

If the question is about a known entity, person, project, or concept, **try wiki-search
first**. It answers 80% of queries in 2-3 obsidian reads at 1/10th the token cost.
Come here when wiki-search sends you — or when you know you need raw source depth.

---

## Steps

### Step 0 — Quick Wiki Check

Even for deep research, check the wiki first. It may have a synthesis that reframes
what you need from raw notes.

```
Desktop Commander:start_process
  command: obsidian read file=index
  shell: cmd
  timeout_ms: 8000
```

If a relevant wiki page exists, read it. Use it as a **map** for the raw note reads
ahead — the `sources:` frontmatter field tells you exactly which raw notes to target.

---

### Step 1 — Find Entry Points

```python
keppi:keyword_search(query="<topic keywords>", limit=5)
```

Run 1-2 targeted searches. Keep queries to 2-4 words. Each query must be meaningfully
different — repeating terms returns the same results.

---

### Step 2 — Trace Connections (Blast Radius)

```python
keppi:blast_radius(note="<TopResultNote>", depth=2)
```

This gives you the structural map — which notes are connected, and how strongly.
`related_to` edges (weight 2.0) are more meaningful than tag overlaps (weight 0-0.5).
Use depth=2; depth 3+ gets noisy.

---

### Step 3 — Build the Context Pack

```python
keppi:context_pack(query="<topic>", budget=8000)
```

Keppi selects the minimal set of notes fitting within the token budget, ranked by
relevance to the query. This is your reading list.

**Token budget guide:**

| Scope | Budget |
|-------|--------|
| Quick deep-dive | 4,000 |
| Standard research | 8,000 |
| Comprehensive analysis | 12,000-16,000 |
| Full context (use sparingly) | 20,000+ |

---

### Step 4 — Read the Notes

Read each note from the context pack via obsidian CLI, highest relevance first.

Single-word names:
```
Desktop Commander:start_process
  command: obsidian read file=NoteTitle
  shell: cmd
  timeout_ms: 10000
```

Names with spaces — search first to get the path, then read:
```
Desktop Commander:start_process
  command: obsidian search query="Note Title" limit=1
  shell: cmd
  timeout_ms: 8000

Desktop Commander:start_process
  command: obsidian read path=<returned-path>
  shell: cmd
  timeout_ms: 10000
```

You can also use the exact path returned by `keppi:query_node` directly in
`obsidian read path=<path>`.

---

### Step 5 — Synthesize

Combine graph structure (blast radius relevance scores) with note content to answer
the question. Cite notes by title. If the research reveals new cross-connections not
in the wiki, note them — they're candidates for a wiki update.

---

### Step 6 — Update the Wiki (Optional)

If the research surfaces connections or insights not yet captured:

```
Desktop Commander:start_process
  command: obsidian read file=wiki-ops
  shell: cmd
  timeout_ms: 8000
```

Follow the ingest process in `wiki-ops.md` to create or update the relevant
entity/concept/synthesis page. This closes the Karpathy flywheel loop.

---

## Obsidian CLI Quick Reference

```
Desktop Commander:start_process
  command: obsidian <command> <args>
  shell: cmd        ← ALWAYS cmd. PowerShell swallows output.
  timeout_ms: 10000
```

| Purpose | Command |
|---------|---------|
| Read wiki index | `obsidian read file=index` |
| Read note (single word) | `obsidian read file=NoteName` |
| Search for path (names with spaces) | `obsidian search query="Note Title" limit=1` |
| Read by exact path | `obsidian read path=1-Projects/DGEA/some note.md` |

---

## Keppi MCP Tools Used in This Skill

| Tool | Purpose |
|------|---------|
| `keppi:keyword_search` | Find entry-point notes by keyword |
| `keppi:blast_radius` | Map structural connections from a seed note |
| `keppi:context_pack` | Token-budgeted reading list for AI context |
| `keppi:query_node` | Get full graph metadata + edges for one note |

---

## Important Notes

- **Try wiki-search first** — if the topic has a wiki page, you'll save 80% of the tokens
- **Keppi MCP tools, not bash** — `keppi:keyword_search`, not `keppi search ...`
- **Obsidian CLI, not cat** — `obsidian read`, not shell file reads
- **Always `shell: cmd`** — PowerShell silently swallows obsidian CLI output
- **Cite note titles** in your answer so sources are traceable
