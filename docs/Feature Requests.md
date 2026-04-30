---
type: project
subtype: feature-request
status: active
updated: 2026-04-30
created: 2026-04-30
tags: [keppi, feature-request, onboarding, ux]
related_to:
  - "[[Keppi Project]]"
  - "[[Keppi]]"
---

# Keppi Feature Requests

## FR-001: Smart `keppi init` — Auto-Detect Vault Patterns

**Priority:** High
**Status:** Open
**Created:** 2026-04-30

### Problem

When a new user runs `keppi init`, they get sensible defaults (`.obsidian`, `.git`, `templates`, `.trash`, `*.excalidraw.md`). But every vault has unique patterns that should be excluded — archive folders, attachment directories, specialized subfolders. Right now, users have to know TOML syntax and manually edit `~/.keppi/keppi.toml` to add these.

For a research student who just installed Keppi, this is a barrier. They don't know what `.base` files are or why `4-Archives` should be excluded. They just want `keppi build` to work cleanly.

### Solution

Enhance `keppi init` to scan the vault directory for common patterns and suggest exclusions interactively:

```bash
$ keppi init /path/to/vault

🔍 Scanning vault for common patterns...

Found directories that look like archives:
  - 4-Archives/         (1,204 notes, likely old content)
  - Navigation-Hubs-archived/  (208 notes)

Found directories with binary/attachment files:
  - attachments/        (342 files, mostly images and PDFs)

Found Obsidian Bases files:
  - *.base              (12 files)

Include these in exclude_dirs/exclude_patterns? [Y/n] Y

✅ Added 4-Archives, Navigation-Hubs-archived to exclude_dirs
✅ Added attachments to exclude_dirs
✅ Added *.base to exclude_patterns

Created ~/.keppi/keppi.toml
Vault: /path/to/vault
```

### Detection Heuristics

| Pattern | Detection Logic | Suggestion |
|---------|----------------|------------|
| Archive folders | Directory names containing "archive", "old", "backup", "archived" | Add to `exclude_dirs` |
| Attachment folders | Directories with >50% non-.md files (images, PDFs) | Add to `exclude_dirs` |
| Template folders | Named "templates" or "tpl" (already default) | Already excluded |
| Obsidian Bases | `*.base` files present | Add `*.base` to `exclude_patterns` |
| Excalidraw | `*.excalidraw.md` files present | Already default |
| Daily note patterns | `YYYY-MM-DD.md` filenames in bulk | Note count, offer to exclude old ones |
| Large binary dirs | Directories with >90% non-text files | Add to `exclude_dirs` |
| Dot directories | `.obsidian`, `.git`, `.trash` | Already default |

### Implementation Notes

- Scan should be fast — just `os.listdir` + file extension counting, not full content parsing
- Interactive by default (prompt for each suggestion), `--quick` accepts all suggestions
- `--no-scan` skips detection, writes pure defaults (current behavior)
- Show note counts for each suggestion so users understand *why* it's being excluded
- After init, print a summary: "Excluding 1,204 notes from 2 directories. Graph will index 1,454 notes."

### Acceptance Criteria

- [ ] `keppi init` scans vault and suggests exclusions
- [ ] Interactive mode lets user accept/reject each suggestion
- [ ] `--quick` accepts all suggestions automatically
- [ ] `--no-scan` skips detection (current behavior)
- [ ] Works on any Obsidian vault or markdown directory
- [ ] Handles vaults with no unusual patterns gracefully (just writes defaults)

---

*Feature requests for Keppi — Knowledge Engine for Precise Pattern Intelligence*