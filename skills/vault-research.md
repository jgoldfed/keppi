---
name: vault-research
description: >
  Research a topic across the Obsidian vault using Keppi's graph engine.
  Use when asked to find evidence, synthesize information, or answer questions
  that require reading multiple connected notes. NOT for simple keyword lookups
  — use this when the question needs context from related notes, trace connections,
  or provide a cohesive answer from multiple sources.
---

# Vault Research

Research a question across the vault using Keppi's graph traversal and context packing.

## When to Use

- "What would be affected if I move to another city?"
- "What connects my current project to my career plans?"
- "Summarize everything I know about the Acme project"
- "Tell me about my contract negotiations with that client"
- Any question that needs *multiple related notes* to answer, not just one keyword match

## Steps

### 1. Find the entry points

Run `keppi search` to find the most relevant notes for the topic:

```bash
keppi search "job relocation" ~/Documents/Obsidian\ Vault
keppi search "moving costs" ~/Documents/Obsidian\ Vault
```

### 2. Trace the connections

Run `keppi blast-radius` on the most relevant notes to find everything connected:

```bash
keppi blast-radius "Job Relocation" --depth 2 ~/Documents/Obsidian\ Vault
keppi blast-radius "Career Planning" --depth 2 ~/Documents/Obsidian\ Vault
```

This gives you the structural map — what's connected to the topic and how strongly.

### 3. Build the context pack

Run `keppi context-pack` with a token budget appropriate for the model:

```bash
keppi context-pack "relocation impact" --budget 8000 ~/Documents/Obsidian\ Vault
```

This selects the minimal set of notes that fit within the token budget, ranked by relevance. For deep research, use 12000-16000 tokens. For quick answers, 4000-6000.

### 4. Read the sources

Read each note returned by the context pack using the `read` tool. Start with the highest-relevance notes.

### 5. Synthesize the answer

Combine the graph structure (blast radius) with the content (read notes) to answer the question. Cite specific notes by title.

### 6. Update the wiki (optional)

If the research reveals new connections or insights, update relevant wiki pages in `3-Resources/wiki/`.

## Example

**Question:** "What would be affected if I relocate for a job?"

**Step 1 — Search:**
```bash
keppi search "relocation" ~/Documents/Obsidian\ Vault
```
→ Finds 5 notes mentioning relocation

**Step 2 — Blast radius:**
```bash
keppi blast-radius "Job Relocation" --depth 2 ~/Documents/Obsidian\ Vault
```
→ Job Relocation → Housing → Cost of Living → Commute → School Districts → Remote Work Policy

**Step 3 — Context pack:**
```bash
keppi context-pack "relocation impact" --budget 8000 ~/Documents/Obsidian\ Vault
```
→ Returns 6 notes fitting 7,847 tokens

**Step 4 — Read:** Read each note, starting with highest relevance.

**Step 5 — Synthesize:** Combine findings into a cohesive answer citing specific sources.

## Token Budget Guide

| Model | Recommended Budget | Notes |
|-------|-------------------|-------|
| Quick question | 4000 | 2-3 notes |
| Standard research | 8000 | 4-6 notes |
| Deep analysis | 12000-16000 | 8-12 notes |
| Full context | 20000+ | Use sparingly |

## Important

- Always run `keppi search` first to find entry points — don't assume you know which notes exist
- Use `--depth 2` for blast radius (depth 3+ gets noisy)
- Start with a smaller token budget and increase if needed
- Cite note titles in your answer so the user can find them
- If Keppi returns no results, the topic may not be in the vault — say so