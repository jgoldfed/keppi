"""Markdown parser: frontmatter, wikilinks, embeds, inline tags, headings."""

from __future__ import annotations

import hashlib
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import frontmatter

# Wikilinks: [[Note]], [[Note|Alias]], [[Note#Section]], [[Note#^block]]
# Embeds must be matched BEFORE wikilinks so we don't double-count
EMBED_RE = re.compile(r'!\[\[([^\]]+)\]\]')
WIKILINK_RE = re.compile(r'(?<!!)(?<!\[)\[\[([^\]\n]+)\]\]')
INLINE_TAG_RE = re.compile(r'(?:^|\s)#([a-zA-Z][\w/-]*)', re.MULTILINE)
HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
# Wikilinks in frontmatter related_to: "[[Note Name]]"
FM_WIKILINK_RE = re.compile(r'\[\[([^\]]+)\]\]')


@dataclass
class ParsedNote:
    path: str
    title: str
    frontmatter_data: dict = field(default_factory=dict)
    body: str = ""
    wikilinks: list[str] = field(default_factory=list)
    embeds: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    related_to: list[str] = field(default_factory=list)
    content_hash: str = ""
    word_count: int = 0
    parse_error: Optional[str] = None


def _strip_link_extras(link: str) -> str:
    """Strip alias (|Display), heading (#Section), and block (#^id) from a wikilink target."""
    link = link.split("|")[0].strip()
    link = link.split("#")[0].strip()
    return link


def _extract_tags(fm_data: dict, body: str, tags_field: str | bool) -> list[str]:
    """Extract and merge frontmatter tags + inline body tags."""
    tags: list[str] = []

    if tags_field and isinstance(tags_field, str):
        raw = fm_data.get(tags_field, [])
        if isinstance(raw, str):
            tags.extend([t.strip() for t in raw.split(",") if t.strip()])
        elif isinstance(raw, list):
            tags.extend(str(t).strip() for t in raw if t)

    for m in INLINE_TAG_RE.finditer(body):
        tags.append(m.group(1))

    return list(dict.fromkeys(tags))  # deduplicate, preserve order


def _extract_related_to(fm_data: dict, related_field: str | bool) -> list[str]:
    """Extract related_to targets (strips [[wikilink]] brackets)."""
    if not related_field or not isinstance(related_field, str):
        return []
    raw = fm_data.get(related_field, [])
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    targets = []
    for item in raw:
        item = str(item).strip()
        # Could be "[[Note Name]]" or just "Note Name"
        m = FM_WIKILINK_RE.search(item)
        if m:
            targets.append(_strip_link_extras(m.group(1)))
        elif item:
            targets.append(item)
    return targets


def parse_note(
    filepath: Path,
    vault_root: Path,
    *,
    type_field: str | bool = "type",
    subtype_field: str | bool = "subtype",
    status_field: str | bool = "status",
    updated_field: str | bool = "updated",
    tags_field: str | bool = "tags",
    aliases_field: str | bool = "aliases",
    related_field: str | bool = "related_to",
    case_sensitive: bool = False,
) -> ParsedNote:
    """Parse a single markdown file into a ParsedNote."""
    try:
        raw_bytes = filepath.read_bytes()
    except OSError as e:
        rel = filepath.relative_to(vault_root).as_posix()
        return ParsedNote(path=rel, title=filepath.stem, parse_error=str(e))

    content_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
    rel_path = filepath.relative_to(vault_root).as_posix()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            post = frontmatter.loads(raw_bytes.decode("utf-8", errors="replace"))
        fm_data = dict(post.metadata)
        body_text = post.content
    except Exception as e:
        # Malformed frontmatter — treat entire file as body
        fm_data = {}
        body_text = raw_bytes.decode("utf-8", errors="replace")
        return ParsedNote(
            path=rel_path,
            title=filepath.stem,
            frontmatter_data=fm_data,
            body=body_text,
            content_hash=content_hash,
            word_count=len(body_text.split()),
            parse_error=f"frontmatter error: {e}",
        )

    # Title: first H1 heading or filename stem
    headings = [m.group(2).strip() for m in HEADING_RE.finditer(body_text)]
    # Strip wikilinks from heading text (e.g. "# [[Note Title]]")
    clean_headings = [FM_WIKILINK_RE.sub(lambda m: m.group(1), h) for h in headings]
    title = clean_headings[0] if clean_headings else filepath.stem
    # Remove any remaining | alias parts from title
    title = title.split("|")[0].strip()

    # Strip code blocks (```...```) and inline code (`...`) before extracting wikilinks
    # so that pandas double-bracket syntax like df[[c for c in ...]] isn't parsed as wikilinks
    _code_block_re = re.compile(r'```[\s\S]*?```', re.MULTILINE)
    _inline_code_re = re.compile(r'`[^`\n]+`')
    _body_for_links = _code_block_re.sub('', body_text)
    _body_for_links = _inline_code_re.sub('', _body_for_links)

    # Embeds first, then wikilinks (so embeds don't appear in wikilinks)
    embed_targets = [_strip_link_extras(m.group(1)) for m in EMBED_RE.finditer(body_text)]
    embed_set = set(embed_targets)

    raw_wikilinks = [_strip_link_extras(m.group(1)) for m in WIKILINK_RE.finditer(_body_for_links)]
    # Filter out targets that are embeds (already captured above)
    wikilinks = [w for w in raw_wikilinks if w not in embed_set]
    # Filter out code/template fragments (dataviewjs expressions, shell vars, etc.)
    _junk_patterns = (
        "'", "dv.", "javascript:", "<", ">",     # existing filters
        "$", "string(", "!= ", "= \"${",          # Dataview/shell fragments
        ".pdf", ".docx", ".json", ".bak", ".dump", # file references (non-.md)
        ".js", ".base",                    # JavaScript and Obsidian Bases file refs
    )
    wikilinks = [w for w in wikilinks if not any(
        pat in w for pat in _junk_patterns
    )]
    # Filter out targets that start with special chars (code artifacts)
    wikilinks = [w for w in wikilinks if not w.startswith(("\"", "-z "))]
    # Filter out Python/pandas expressions that look like wikilinks (e.g. df[[c for c in ...]])
    wikilinks = [w for w in wikilinks if not any(
        kw in w for kw in (" for ", " in ", "if ", "else ", "lambda ", "def ", "import ",
        "return ", "yield ", "class ", "print(", "len(", "range(",
    ))]
    # Filter out targets that look like Python expressions (contain common operators)
    wikilinks = [w for w in wikilinks if not any(op in w for op in ("= ", "==", "!=", ">=", "<="))]
    # Filter out targets containing typical code patterns (function calls, list comprehensions)
    wikilinks = [w for w in wikilinks if not re.search(r'\w+\(', w)]
    # Filter out generic placeholder names used in templates/examples
    _placeholder_names = {
        "Other Page", "Another Page", "Source Note", "Entity Name",
        "Other Entity", "Concept Name", "Prerequisite Concept",
        "Downstream Concept", "Synthesis Title", "Parent Entity",
        "Child Item", "Note Name", "Nonexistent Note", "Page Name",
        "Alternative Approach", "Source 2", "Note-Name",
        "Another-Note", "Related-Note-1", "Related-Note-2",
        "Wikilinks", "wikilinks", "double bracket",
        "redirects", "attachments", "templates",
        # wiki-ops.md schema examples
        "Concept A", "Concept B", "Concept A vs Concept B",
        "Related Concept", "Source A", "Source Name",
        "Does Scale Improve Reasoning?",
        # Daily note template headings parsed as wikilinks
        "Timeline", "What Went Well", "What actually went wrong",
        # Copilot conversation section headings
        "Option 1: Add as a Separate \"Detailed Activity Log\" Section",
        "Scenario A: If \"OpenClaw\" is your Software/Coding Project",
    }
    wikilinks = [w for w in wikilinks if w not in _placeholder_names]

    tags = _extract_tags(fm_data, body_text, tags_field)
    related = _extract_related_to(fm_data, related_field)

    if not case_sensitive:
        # Normalise for later resolution (keep originals for display)
        pass  # resolution handles case-insensitivity in builder

    return ParsedNote(
        path=rel_path,
        title=title,
        frontmatter_data=fm_data,
        body=body_text,
        wikilinks=wikilinks,
        embeds=embed_targets,
        tags=tags,
        headings=clean_headings,
        related_to=related,
        content_hash=content_hash,
        word_count=len(body_text.split()),
    )


def collect_markdown_files(
    vault_root: Path,
    extensions: list[str],
    exclude_dirs: list[str],
    exclude_patterns: list[str],
) -> list[Path]:
    """Recursively collect all markdown files, honouring exclusions."""
    import fnmatch

    files: list[Path] = []
    exclude_dirs_lower = {d.lower() for d in exclude_dirs}

    for p in vault_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in extensions:
            continue

        # Check if any part of the path is an excluded directory
        parts_lower = {part.lower() for part in p.relative_to(vault_root).parts[:-1]}
        if parts_lower & exclude_dirs_lower:
            continue

        # Check exclude patterns against filename
        name = p.name
        if any(fnmatch.fnmatch(name, pat) for pat in exclude_patterns):
            continue

        files.append(p)

    return sorted(files)
