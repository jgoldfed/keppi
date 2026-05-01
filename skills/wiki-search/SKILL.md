---
name: wiki-search
description: >
  Fast, token-efficient vault research using the Karpathy wiki layer (3-Resources/wiki/)
  as the primary fast path, with Keppi MCP tools as fallback. Use this INSTEAD of
  vault-research when the question involves a known entity, person, project, concept, or
  relationship that is likely already synthesized in the wiki. The wiki layer is
  pre-compiled and compact — 200-400 words vs. 2,000-10,000 for raw source notes.
  Triggers: "what do I know about X", "tell me about [person/company/project]",
  "how does X relate to Y", "find my notes on X". NOT for deep evidence retrieval
  from raw transcripts — use vault-research for that.
---

# Wiki + Keppi Search

Fast vault research using the wiki layer first, Keppi MCP tools second, raw notes
only as a last resort. Optimized for speed and token efficiency.

**All vault reads use the Obsidian CLI** via `Desktop Commander:start_process` with
`shell: cmd`. This resolves notes by wikilink name through Obsidian's internal index —
no full paths, no filesystem traversal.

**Keppi calls use MCP tools directly** — `keppi:keyword_search`, `keppi:query_node`.
Not bash. Not CLI.

---

## When to Use This Skill

- Questions about a **known entity**: person, company, project, tool, concept
- Questions about **relationships**: "how does X connect to Y", "what's the status of Z"
- Quick factual lookups: pricing, dates, decisions, agreements, names
- Any question where you'd expect a synthesized answer, not a raw transcript

## When to Use vault-research Instead

- Deep evidence retrieval from raw meeting transcripts
- Questions that need specific quotes or step-by-step detail from source notes
- Comprehensive analysis requiring 4+ raw note reads
- The wiki is absent or stale for this topic

---

## The Two-Lane Model

```
Wiki Fast Lane   →  Pre-compiled pages via obsidian CLI  (~1-3 reads)
Keppi Graph Lane →  Navigate to answer when wiki misses  (~2-4 MCP calls + obsidian reads)
Raw Note Lane    →  Last resort                          (escalate to vault-research if 3+)
```

**Stop at the first lane that answers the question.**

---

## Obsidian CLI Pattern

```
Desktop Commander:start_process
  command: obsidian <command> <args>
  shell: cmd        ← ALWAYS cmd. PowerShell swallows output silently.
  timeout_ms: 8000
```

| Purpose | Command |
|---------|---------|
| Read wiki index | `obsidian read file=index` |
| Read a note (single word) | `obsidian read file=DGEA` |
| Find note path (spaces in name) | `obsidian search query="Dan Goodman" limit=1` |
| Read by path | `obsidian read path=3-Resources/wiki/entities/Dan Goodman.md` |

**Filenames with spaces:** `file=` breaks on spaces. Use `obsidian search` to get the
exact path, then `obsidian read path=<path>`. Alternatively, `keppi:query_node` returns
the exact vault path which can be passed directly to `obsidian read path=`.

---

## Steps

### Step 1 — Check the Wiki Index (always first)

```
Desktop Commander:start_process
  command: obsidian read file=index
  shell: cmd
  timeout_ms: 8000
```

Scan for a matching entity, concept, or synthesis. Found one? **Go to Step 2.**
Nothing? **Skip to Step 3.**

> ~1-2KB. Always worth reading first.

---

### Step 2 — Read Wiki Pages (Fast Lane)

Single-word names:
```
Desktop Commander:start_process
  command: obsidian read file=DGEA
  shell: cmd
  timeout_ms: 8000
```

Names with spaces — search first, then read by path:
```
Desktop Commander:start_process
  command: obsidian search query="Dan Goodman" limit=1
  shell: cmd
  timeout_ms: 8000

Desktop Commander:start_process
  command: obsidian read path=3-Resources/wiki/entities/Dan Goodman.md
  shell: cmd
  timeout_ms: 8000
```

**Parse frontmatter first:**
- `status` — active/stable/stale/archived
- `related_to` — connected wiki pages (read these next if needed, still Fast Lane)
- `sources` — raw source notes (only follow for granular detail)
- `updated` — last modified date

Question answered? **Done.** Wiki thin or stale? **Move to Step 3.**

> 2-3 wiki pages ≈ 800-1,200 tokens. One raw transcript ≈ 3,000-8,000 tokens.

---

### Step 3 — Keppi Keyword Search (Graph Lane)

```python
keppi:keyword_search(query="<topic keywords>", limit=5)
```

Check results. **Any hits are wiki pages** (path starts with `3-Resources/wiki/`)?
- YES → Read them via obsidian CLI → back to Step 2 logic.
- NO → All hits are raw notes → proceed to Step 4.

---

### Step 4 — Keppi Graph Navigation (Graph Lane continued)

```python
keppi:query_node(note="<NoteTitle>")
```

Inspect `outbound_edges` and `inbound_edges`. Look for wiki pages in the edge list
(path starts with `3-Resources/wiki/`). Read those via obsidian CLI.

- Found wiki pages? → Read them. **Done.**
- No wiki pages in graph? → Topic not yet synthesized. Move to Step 5.

---

### Step 5 — Read Raw Notes (Last Resort)

```
Desktop Commander:start_process
  command: obsidian read file=NoteTitle
  shell: cmd
  timeout_ms: 10000
```

For notes with spaces, use the exact path from `keppi:query_node`:
```
Desktop Commander:start_process
  command: obsidian read path=<exact-path-from-keppi>
  shell: cmd
  timeout_ms: 10000
```

**Hard limit: 2-3 raw notes.** If more are needed, escalate to `vault-research`.

---

## Decision Tree

```
Is topic in wiki/index.md?
├── YES → obsidian read wiki page(s) → check related_to → Answer? DONE
└── NO  → keppi:keyword_search
          ├── Hits include wiki pages? → obsidian read them → Answer? DONE
          └── Hits are raw notes only?
              └── keppi:query_node → edges include wiki pages?
                  ├── YES → obsidian read those wiki pages → Answer? DONE
                  └── NO  → obsidian read 1-2 raw notes → DONE
                            (escalate to vault-research if 3+ needed)
```

---

## Token Budget

| Lane | Tool Calls | Approx. Tokens |
|------|-----------|----------------|
| Wiki Fast Lane (1 page) | 2 | ~400-600 |
| Wiki Fast Lane (3 pages) | 4 | ~1,000-1,500 |
| Graph Lane + 2 wiki pages | 5-6 | ~1,500-2,500 |
| Raw Note (1 transcript) | 1 | ~3,000-8,000 |
| vault-research (full) | 8-12 | ~8,000-16,000 |
