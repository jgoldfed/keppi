# Configuration Reference

Keppi works with **zero configuration** — `keppi build` on any vault produces a useful graph without any setup. Config is for power users who want to tune behavior.

## Creating a Config File

```bash
keppi init /path/to/vault          # Interactive (auto-detects Obsidian vault)
keppi init /path/to/vault --quick  # Non-interactive, writes defaults
```

This creates `keppi.toml` in your vault directory.

## Config Discovery

Keppi walks up the directory tree from the vault root looking for `keppi.toml`. If none is found, defaults are used. You can also place `keppi.toml` in a parent directory to apply it to multiple vaults.

---

## Full Config Reference

```toml
[vault]
# Root directory of your vault.
# Default: directory containing keppi.toml (or CWD if no config file)
path = "."

# File extensions to parse.
# Default: [".md"]
extensions = [".md"]

# Directories to exclude from parsing.
# Default: [".obsidian", ".git", "templates"]
exclude_dirs = [".obsidian", ".git", "templates", "archive", "_archive"]

# Specific files to exclude (relative to vault root).
# Default: []
exclude_files = []


[graph]
# Minimum Jaccard coefficient for a tag-overlap edge to be created.
# Higher = fewer tag edges, faster build. Lower = denser graph.
# Default: 0.1  (two notes sharing 10% of their tags get an edge)
tag_overlap_min = 0.1

# Maximum number of tag-overlap edges. Set lower for large vaults.
# Default: 500
max_tag_edges = 500


[links]
# Whether wikilink resolution is case-sensitive.
# Default: false (case-insensitive: [[data quality]] matches "Data Quality")
case_sensitive = false


[analysis]
# Default depth for blast-radius and traverse commands.
# Default: 2
default_depth = 2

# Default relevance threshold for blast-radius results.
# Default: 0.3  (drop anything with < 30% of the seed's relevance)
default_threshold = 0.3


[storage]
# Directory where graph databases (SQLite) are stored.
# Each vault gets its own .db file, keyed by a hash of the vault path.
# Default: ~/.keppi/graphs
db_dir = "~/.keppi/graphs"
```

---

## Edge Weights

The graph uses weighted directed edges. Weights affect blast-radius relevance decay:

| Edge type | Weight | Source |
|-----------|--------|--------|
| `wikilink` | 1.0 | `[[Note]]` in body |
| `embed` | 1.5 | `![[Note]]` (embed is a stronger dependency) |
| `related_to` | 2.0 | `related_to:` frontmatter list |
| `tag_overlap` | 0–0.5 × Jaccard | Shared tags (capped at 0.5) |
| `folder_proximity` | 0.3 | Same directory |

When a note is reachable via multiple edge types, the strongest edge wins.

**Relevance decay formula:**
```
new_relevance = parent_relevance × edge_weight
```

So from a seed (relevance=1.0), a `related_to` edge (weight=2.0) yields relevance=2.0 — which is then capped at 1.0 in the output — while a `tag_overlap` edge at Jaccard=0.2 yields relevance=0.1.

---

## Frontmatter Fields

Keppi reads these frontmatter fields if present:

```yaml
---
title: My Note Title         # Used as display name (default: filename stem)
tags: [tag1, tag2]           # Tag list (also supports "tags: tag1, tag2" string)
date: 2026-01-15             # Used for drift detection
type: concept                # Arbitrary type label (shown in stats, tables)
related_to:                  # Creates high-weight edges
  - Other Note
  - Another Note
aliases:                     # Alternative titles for wikilink resolution
  - My Alt Name
---
```

All other frontmatter fields are stored as node attributes and queryable via the MCP `query_node` tool.
