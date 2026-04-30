# Keppi Roadmap & Feature Requests

## FR-001: Smart `keppi init` — Auto-Detect Vault Patterns

**Priority:** High | **Status:** Open

### Problem

When a new user runs `keppi init`, they get sensible defaults (`.obsidian`, `.git`, `templates`, `.trash`, `*.excalidraw.md`). But every vault has unique patterns — archive folders, attachment directories, Bases files — that should be excluded. Users currently need to know TOML syntax and manually edit `~/.keppi/keppi.toml`.

### Solution

Enhance `keppi init` to scan the vault for common patterns and suggest exclusions:

```bash
$ keppi init /path/to/vault

🔍 Scanning vault for common patterns...

Found directories that look like archives:
  - 4-Archives/         (1,204 notes, likely old content)

Found directories with binary/attachment files:
  - attachments/        (342 files)

Found Obsidian Bases files:
  - *.base              (12 files)

Include these in exclude_dirs/exclude_patterns? [Y/n] Y

✅ Created ~/.keppi/keppi.toml
```

### Detection Heuristics

| Pattern | Detection | Suggestion |
|---------|-----------|------------|
| Archive folders | Names containing "archive", "old", "backup" | `exclude_dirs` |
| Attachment folders | >50% non-.md files | `exclude_dirs` |
| Obsidian Bases | `*.base` files present | `exclude_patterns` |
| Large binary dirs | >90% non-text files | `exclude_dirs` |

### Implementation Notes

- Fast scan: `os.listdir` + extension counting, not full parse
- Interactive by default, `--quick` accepts all, `--no-scan` skips
- Show note counts so users understand *why*
- Print summary: "Excluding 1,204 notes from 2 directories. Graph will index 1,454 notes."

### Acceptance Criteria

- [ ] `keppi init` scans and suggests exclusions
- [ ] Interactive accept/reject per suggestion
- [ ] `--quick` accepts all suggestions
- [ ] `--no-scan` skips detection (current behavior)
- [ ] Works on any vault or markdown directory
- [ ] Handles vaults with no unusual patterns gracefully

---

## FR-002: `keppi visualize` — Interactive Graph Visualization

**Priority:** Medium | **Status:** Open

### Problem

The graph is a powerful mental model, but `keppi stats` and `keppi blast-radius` output are text-only. For people who think visually (which is most of us), seeing the connections as an interactive graph makes the value immediately obvious.

### Solution

Generate an interactive HTML visualization using PyVis/NetworkX:

```bash
$ keppi visualize "Cloud Vendor" --depth 2 --output network.html --open
```

### Features

- **`--center`** — Focus on a specific node (person, project, concept)
- **`--depth`** — 1-hop or 2-hop blast radius from center
- **`--edge-types`** — Filter to wikilinks, related_to, tag_overlap, or all
- **`--max-nodes`** — Cap large graphs at 200 nodes (default)
- **Color-coded categories** — people (red), projects (teal), companies (blue), concepts (green), entities (yellow), meetings (plum), other (gray)
- **Interactive** — Drag nodes, zoom, click for details, filter by group
- **`--open`** — Launch browser automatically
- **Dark mode** by default

### Implementation Notes

- PyVis generates self-contained HTML (no server needed)
- Node categories determined by frontmatter `type` field or folder heuristics
- Edge widths proportional to weight (related_to > wikilink > tag_overlap)
- Physics toggle for layout control
- Legend auto-generated from categories present in the graph

### Acceptance Criteria

- [ ] `keppi visualize` generates interactive HTML
- [ ] `--center` focuses on a specific node
- [ ] `--depth` controls blast radius (1 or 2 hops)
- [ ] `--max-nodes` caps graph size
- [ ] `--open` launches browser
- [ ] Color coding by node type
- [ ] Works with vaults of 1,000+ notes
- [ ] Output file is self-contained (no external dependencies)

---

## FR-003: `keppi connect` — Auto-Generate Wikilinks and related_to

**Priority:** High | **Status:** Open

### Problem

Keppi's graph traversal depends on explicit connections — `[[wikilinks]]` and `related_to:` frontmatter. Users who write in Obsidian-fluent markdown naturally create these. But most people's notes are pasted articles, meeting transcripts, PDF exports, and scratch notes with **zero wikilinks** and **no frontmatter**.

For these users, Keppi degrades to tag-based search. The blast radius, context packs, and traversal features that make Keppi valuable all depend on connection data that doesn't exist yet.

This is the **adoption blocker**. Without connections, Keppi is just a search engine with extra steps.

### Solution

`keppi connect` analyzes the graph's existing structure (tags, content similarity, shared neighbors) and **writes connection data into note files**:

1. **`related_to:` frontmatter** — Add explicit semantic links between notes the graph identifies as strongly connected
2. **`[[wikilinks]]`** — Insert brackets around mentions of other note titles found in note body text
3. **Accept/reject workflow** — Show suggestions, let the user confirm or modify before writing

```bash
$ keppi connect

🔍 Analyzing graph for missing connections...

Found 847 potential connections across 394 notes.

Top suggestions:
  1. [[Data Platform Migration]] → related_to: [[Job Search]], [[Career]], [[Family Plans]]
     Score: 0.94 | Tags: relocation, career, family | Shared neighbors: 5

  2. [[Cloud Analytics]] → related_to: [[Data Pipeline]], [[Cloud DB]]
     Score: 0.89 | Tags: data, cloud, databricks | Shared neighbors: 3

  3. [[Integration Project]] → related_to: [[Cloud Vendor]], [[Parent Org]], [[Compliance]]
     Score: 0.87 | Tags: project, stitch | Shared neighbors: 4

  ...

Review mode: [a]ccept all | [s]kip | [i]nteractive (one-by-one) [i]: i

1/847: Add related_to: [[Job Search]], [[Career]], [[Family Plans]] to Data Platform Migration? [Y/n/e/d]
  Y = accept (add all three)
  n = skip
  e = edit (choose which links to add)
  d = show diff (preview frontmatter change)

> Y
✅ Updated: 3-Resources/wiki/entities/Data Platform Migration.md

2/847: Add [[Data Pipeline]], [[Cloud DB]] as wikilinks in Cloud Analytics note? [Y/n/e/d]
> e
  Add [[Data Pipeline]]? [Y/n] Y
  Add [[Cloud DB]]? [Y/n] Y
✅ Updated: wiki/entities/Cloud Analytics.md

...
```

### Three Connection Strategies

**Strategy 1: `related_to` frontmatter (high confidence)**

The `suggest_links` algorithm already computes this. For note pairs with:
- High tag Jaccard (>0.4) **AND** shared neighbors (>2)
- No existing edge between them
- Confidence score >0.7

→ Suggest as `related_to:` frontmatter additions.

This is the highest-value connection type. It's explicit, weighted at 2.0 in the graph, and doesn't require modifying note body text.

**Strategy 2: Inline wikilinks (medium confidence)**

Scan note body text for **exact title mentions** of other notes in the graph:
- "I met with Cloud Vendor yesterday" → `I met with [[Cloud Vendor]] yesterday`
- "We discussed the Data Pipeline" → `We discussed the [[Data Pipeline]]`

Rules to avoid false positives:
- Only match titles ≥ 3 words long (avoid `[[the]]`, `[[data]]`)
- Only match when title appears in a natural sentence context (not inside code blocks, URLs, or existing wikilinks)
- Respect existing formatting — don't bracket titles inside `backticks`, HTML tags, or Dataview queries
- Only suggest if the note pair has some existing connection (tag overlap or shared neighbor)

**Strategy 3: Content-based clusters (low confidence, bulk mode)**

For notes with no tags, no wikilinks, and no frontmatter — the "pasted slop" scenario:
- Run TF-IDF or simple word overlap on note bodies
- Group notes with >40% content overlap into clusters
- Suggest `related_to:` links between cluster members
- Lower confidence threshold, require explicit accept in interactive mode

This catches notes like "meeting-notes-2024-03-15.md" that mention the same projects and people but have zero explicit connections.

### CLI Interface

```bash
# Interactive review (default)
keppi connect

# Review only related_to suggestions
keppi connect --strategy related_to

# Review only wikilink suggestions
keppi connect --strategy wikilinks

# Accept all suggestions with score >0.7 (no review)
keppi connect --auto-accept --min-score 0.7

# Preview only — show what would change, don't write
keppi connect --dry-run

# Limit to specific notes
keppi connect --note "Data Platform Migration"
keppi connect --note "3-Resources/wiki/entities/*"

# Limit to specific connection types
keppi connect --type related_to    # frontmatter only
keppi connect --type wikilinks     # inline brackets only
```

### Output Formats

```bash
# Terminal (default): interactive accept/reject
keppi connect

# JSON: for scripting and AI agent integration
keppi connect --dry-run --format json > suggestions.json

# Markdown: for review in Obsidian
keppi connect --dry-run --format markdown > "0-Inbox/Keppi Suggestions.md"
```

The JSON format enables MCP integration:

```json
{
  "suggestions": [
    {
      "source": "3-Resources/wiki/entities/Data Platform Migration.md",
      "target_title": "Job Search",
      "target_path": "projects/Job Search.md",
      "strategy": "related_to",
      "score": 0.94,
      "reasons": ["shared tags: relocation, career", "shared neighbors: Career, Family Plans, Compliance"],
      "action": "add_frontmatter",
      "field": "related_to",
      "value": "[[Job Search]]"
    },
    {
      "source": "wiki/entities/Cloud Analytics.md",
      "target_title": "Data Pipeline",
      "target_path": "3-Resources/wiki/concepts/Data Pipeline.md",
      "strategy": "wikilink",
      "score": 0.72,
      "reasons": ["title mentioned in body text", "tag overlap: data, cloud"],
      "action": "add_wikilink",
      "line": 4,
      "original": "We discussed the Data Pipeline pattern",
      "replacement": "We discussed the [[Data Pipeline]] pattern"
    }
  ]
}
```

### MCP Integration

Add a new MCP tool so AI assistants can request and apply connections:

```python
@mcp_tool
async def suggest_connections(
    note: str | None = None,  # specific note, or None for global
    strategy: str = "all",     # "related_to", "wikilinks", "all"
    min_score: float = 0.3,
    top_n: int = 20,
    auto_apply: bool = False   # False = preview only, True = write to files
) -> dict:
    """Suggest or apply missing connections for a note or across the vault."""
```

This enables the LLM wiki flywheel:
1. AI reads a raw note
2. AI calls `suggest_connections(note="Data Platform Migration", auto_apply=False)`
3. AI reviews suggestions, applies the relevant ones with `auto_apply=True`
4. `keppi update` rebuilds the graph with new connections
5. Next query is smarter because the graph is richer

### Safety Guarantees

- **Dry-run by default**: `--dry-run` shows what would change without writing
- **YAML preservation**: Use a proper YAML parser (not regex) for frontmatter modifications
- **No content rewriting**: Wikilink insertion only brackets existing text — never paraphrases or restructures
- **Backup**: `--backup` creates `.keppi/backups/` before modifications
- **Idempotent**: Running `keppi connect` twice produces the same suggestions (won't suggest links that already exist)
- **Undo**: `keppi connect --undo` restores from backup

### Implementation Plan

**Phase 1: related_to suggestions (1-2 days)**
- Extend existing `suggest_links()` algorithm with confidence scoring
- Add `related_to` frontmatter writing (YAML-safe)
- Interactive CLI with accept/reject/edit/diff
- `--dry-run` and `--format json` modes

**Phase 2: Inline wikilinks (2-3 days)**
- Title matching engine with false-positive filters
- Context-aware insertion (avoid code blocks, URLs, existing links)
- Title length minimum (≥3 words) and uniqueness check
- Diff preview before writing

**Phase 3: Content clusters (1-2 days)**
- TF-IDF or simple word overlap for untagged, unlinked notes
- Cluster detection using existing community detection
- Bulk `related_to` suggestions for cluster members
- Lower confidence threshold, require explicit accept

**Phase 4: MCP tool (1 day)**
- `suggest_connections` MCP tool
- `auto_apply` flag for AI-driven connection writing
- Integration with `keppi update` for graph refresh

### Why This Matters

Without FR-003, Keppi works great for people who already write in Obsidian-fluent markdown. With it, Keppi works for **everyone** — even people whose notes are pasted articles and meeting transcripts with zero explicit connections.

This is the feature that bridges Karpathy's LLM wiki pattern (which assumes you'll curate wikilinks by hand or have an LLM write them) and Keppi's graph engine (which needs those connections to do traversal). `keppi connect` is the auto-wiring that makes the graph useful for notes that were never written to be graphed.

### Acceptance Criteria

- [ ] `keppi connect --dry-run` shows suggestions without writing
- [ ] `keppi connect --strategy related_to` adds frontmatter links with interactive review
- [ ] `keppi connect --strategy wikilinks` brackets title mentions in body text
- [ ] `keppi connect --auto-accept --min-score 0.7` writes without review
- [ ] `keppi connect --format json` outputs machine-readable suggestions
- [ ] `keppi connect --format markdown` outputs reviewable Obsidian note
- [ ] Idempotent: no duplicate suggestions on re-run
- [ ] YAML frontmatter preserved (comments, ordering, multi-line values)
- [ ] Wikilink insertion avoids code blocks, URLs, existing links, and Dataview blocks
- [ ] Title matching requires ≥3 words and uniqueness in the graph
- [ ] `--backup` creates restore point before modifications
- [ ] `--undo` restores from backup
- [ ] MCP tool `suggest_connections` available with `auto_apply` flag
- [ ] Works on vaults with zero existing connections (the "pasted slop" scenario)