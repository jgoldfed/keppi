---
name: wiki-search
description: >
  Fast, token-efficient vault research using the Karpathy wiki layer (3-Resources/wiki/)
  as the primary fast path, with obsidian search and Keppi MCP tools as fallback. Use
  this INSTEAD of vault-research when the question involves a known entity, person,
  project, concept, or relationship that is likely already synthesized in the wiki.
  The wiki layer is pre-compiled and compact — 200-400 words vs. 2,000-10,000 for
  raw source notes. Triggers: "what do I know about X",
  "tell me about [person/company/project]", "how does X relate to Y",
  "find my notes on X". NOT for deep evidence retrieval from raw transcripts — use
  vault-research for that.
---

# Wiki + Keppi Search

Fast vault research with mandatory promotion. Search the wiki first, fall back to
keyword search then Keppi graph navigation, and always promote facts back to the wiki
so the next query resolves faster.

**All vault reads use the Obsidian CLI** via `Desktop Commander:start_process` with
`shell: powershell.exe`. This resolves notes by wikilink name through Obsidian's
internal index.

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

## The Karpathy Loop

The wiki is a compiled facts layer. Every query that leaves the wiki is a signal that
the wiki is incomplete. The loop is:

```
1. Search wiki → Found? Read it. Done. (~400 tokens)
2. Not found? Search vault → Found? Read it. Promote facts to wiki.
3. Not found? Keppi graph → Found? Read it. Promote facts to wiki.
4. Not found? Deep research → Promote facts to wiki.
```

**Every lane except the first MUST promote facts back to the wiki.** This is how the
wiki gets smarter over time. Without promotion, the wiki stays thin and every query
re-traces the same expensive path.

What to promote:

| Promote to wiki | Leave in raw notes |
|---|---|
| Key facts, figures, pricing, dates | Full meeting transcripts |
| Status, decisions, outcomes | Detailed context and quotes |
| Strategy summaries | Step-by-step reasoning |
| Anything you'll query again | One-time reference material |

The wiki is a queryable facts layer, not a summary layer. Promote the answer, not
the whole source. Add a wikilink back: `Source: [[Source Note Name]]`.

---

## Obsidian CLI Pattern

```
Desktop Commander:start_process
  command: obsidian <command> <args>
  shell: powershell.exe   ← ALWAYS PowerShell. CMD truncates on spaces.
  timeout_ms: 8000
```

| Purpose                 | Command                                             |
| ----------------------- | --------------------------------------------------- |
| Read wiki index         | `obsidian read file=index`                          |
| Read note (no spaces)   | `obsidian read file=NoteName`                       |
| Read note (with spaces) | `obsidian read 'file=Note Name'`                    |
| Search vault            | `obsidian search 'query=search terms' limit=5`     |
| Read by exact path      | `obsidian read 'path=3-Resources/wiki/entities/Dan Goodman.md'` |

**Filenames with spaces:** Use single-quoted arguments in PowerShell.
`'file=Note Name'` not `file="Note Name"`.

---

## Steps

### Step 0 — Semantic Pre-Check (Start Here)

Before keyword search, run a semantic search scoped to your wiki directory.
One call replaces 2-3 trial-and-error keyword searches. Takes ~2 seconds.

**Check if embeddings are ready:**
```
keppi:get_embed_status()
```
If `ready_for_semantic_search` is false, skip to Step 1 (keyword search).

**If ready, run semantic search scoped to wiki:**
```
keppi:semantic_search(
    query="<natural language description of what you need>",
    wiki_only=True,
    limit=5
)
```

**Interpreting results:**

| Distance | Strength | Action |
|---|---|---|
| < 0.3 | strong | Read this wiki page — likely answers the question in 1 read |
| 0.3–0.5 | moderate | Read it, then supplement with Step 1 if needed |
| > 0.5 or empty | weak | Skip to Step 1 — wiki has no strong coverage |

**The payoff:** A strong hit resolves the query in ~400 tokens (1 wiki read).
A weak or empty result is also useful — it tells you the wiki needs a new page.

---

### Step 1 — Check the Wiki Index (always first)

```
Desktop Commander:start_process
  command: obsidian read file=index
  shell: powershell.exe
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
  shell: powershell.exe
  timeout_ms: 8000
```

Names with spaces — search first, then read by path:
```
Desktop Commander:start_process
  command: obsidian search 'query=Dan Goodman' limit=1
  shell: powershell.exe
  timeout_ms: 8000

Desktop Commander:start_process
  command: obsidian read path=3-Resources/wiki/entities/Dan Goodman.md
  shell: powershell.exe
  timeout_ms: 8000
```

**Parse frontmatter first:**
- `status` — active/stable/stale/archived
- `related_to` — connected wiki pages (read these next if needed, still Fast Lane)
- `sources` — raw source notes (only follow for granular detail)
- `updated` — last modified date

Question answered? **Done. No promotion needed — wiki had it.**

Wiki thin or stale? **Move to Step 3.**

> 2-3 wiki pages ≈ 800-1,200 tokens. One raw transcript ≈ 3,000-8,000 tokens.

---

### Step 3 — Vault Keyword Search (Search Lane)

If the wiki didn't answer the question, search the full vault. This catches raw notes
that contain the answer but haven't been promoted to a wiki page yet.

```
Desktop Commander:start_process
  command: obsidian search 'query=salary severance pricing' limit=5
  shell: powershell.exe
  timeout_ms: 8000
```

- **Hits include wiki pages?** → Read them. You may have missed them in the index.
  Question answered? **Done.**
- **Hits are raw notes only?** → Read the most relevant one (or two if needed).
  Question answered? **Go to Step 6 — promote the facts to the wiki.**
- **No hits?** → Move to Step 4.

---

### Step 4 — Keppi Keyword Search (Graph Lane)

```python
keppi:keyword_search(query="<topic keywords>", limit=5)
```

Check results:
- **Any hits are wiki pages** (path starts with `3-Resources/wiki/`)? → Read them via
  obsidian CLI. Question answered? **Done.**
- **Any hits are raw notes?** → Read the most relevant. Question answered?
  **Go to Step 6 — promote.**
- **No hits?** → Move to Step 5.

---

### Step 5 — Keppi Graph Navigation (Graph Lane continued)

```python
keppi:blast_radius(note="<TopResultNote>", depth=2)
```

Inspect the results. Read the highest-relevance notes. If you find the answer:
**Go to Step 6 — promote.**

If you still haven't found the answer, escalate to `vault-research`.

---

### Step 6 — Promote Facts to Wiki (MANDATORY)

Every time you left the fast lane — whether you found the answer via vault search,
Keppi graph, or raw notes — the wiki is incomplete. Close the gap before you're done.

**The rule:** Any fact you had to search beyond the wiki to find belongs in the wiki.
The search path IS the signal. If you had to dig, promote.

**How to promote:**
1. Identify the 1-3 key facts that made you leave the fast lane
2. Find (or create) the relevant wiki page in `3-Resources/wiki/entities/` or
   `3-Resources/wiki/concepts/`
3. Add a concise section: `## Pricing`, `## Key Dates`, `## Status`, etc.
4. Add a wikilink to the source: `Source: [[Source Note Name]]`
5. Update the `sources:` frontmatter list to include the source note
6. Set `updated:` frontmatter to today's date

**Result:** Next query on this topic resolves in a single wiki read (~400 tokens)
instead of 2-8 tool calls and 3,000-16,000 tokens.

**Example:** You asked "What does Dan Goodman charge?" and had to read a raw email
note to find pricing. Promote a pricing section to the `Dan Goodman` wiki page:

```markdown
## DGEA Pricing
- **Contingency Model:** $1,500 flat + 18% of severance improvement
- **Consultations:** 15min/$135, 30min/$225, 60min/$375
- Source: [[Pricing Information from Dan Goodman (DGEA)]]
```

Next time, the wiki fast lane answers it in one read.

---

## Decision Tree

```
Wiki index has a matching page?
├── YES → Read wiki page(s) → check related_to → Answer? DONE
└── NO  → obsidian search
          ├── Found in vault? → Read it → Answer? → PROMOTE → DONE
          └── Not found → keppi:keyword_search
                          ├── Found? → Read it → Answer? → PROMOTE → DONE
                          └── Not found → keppi:blast_radius
                                          ├── Found? → Read → Answer? → PROMOTE → DONE
                                          └── Not found → Escalate to vault-research
```

Every path that finds an answer outside the wiki MUST promote back to the wiki.

---

## Token Budget

| Lane | Tool Calls | Approx. Tokens | After Promotion |
|------|-----------|----------------|-----------------|
| Wiki Fast Lane (1 page) | 2 | ~400-600 | N/A (already in wiki) |
| Wiki Fast Lane (3 pages) | 4 | ~1,000-1,500 | N/A (already in wiki) |
| Search Lane (1 raw note) | 3-4 | ~3,000-8,000 | ~400 next time |
| Graph Lane | 5-6 | ~1,500-2,500 | ~400 next time |
| Deep research | 8-12 | ~8,000-16,000 | ~400 next time |

Promotion makes every subsequent query on the same topic cost ~400 tokens.
Without promotion, every query re-traces the same expensive path forever.