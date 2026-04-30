"""Keyword search across titles, tags, headings, and body content."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass
class SearchResult:
    path: str
    title: str
    score: float
    match_context: str
    match_fields: list[str]


def keyword_search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
) -> list[SearchResult]:
    """
    Simple keyword search using SQLite LIKE across node metadata.
    Returns results ordered by a basic relevance score.
    """
    terms = [t.strip().lower() for t in query.split() if t.strip()]
    if not terms:
        return []

    results: dict[str, SearchResult] = {}
    cur = conn.cursor()

    for row in cur.execute("SELECT path, title, tags, headings FROM nodes"):
        path = row["path"]
        title = row["title"] or ""
        tags_raw = row["tags"] or "[]"
        headings_raw = row["headings"] or "[]"

        try:
            tags = json.loads(tags_raw)
        except (json.JSONDecodeError, TypeError):
            tags = []
        try:
            headings = json.loads(headings_raw)
        except (json.JSONDecodeError, TypeError):
            headings = []

        score = 0.0
        match_fields = []

        title_lower = title.lower()
        tags_str = " ".join(str(t).lower() for t in tags)
        headings_str = " ".join(str(h).lower() for h in headings)

        for term in terms:
            if term in title_lower:
                score += 3.0
                if "title" not in match_fields:
                    match_fields.append("title")
            if term in tags_str:
                score += 2.0
                if "tags" not in match_fields:
                    match_fields.append("tags")
            if term in headings_str:
                score += 1.5
                if "headings" not in match_fields:
                    match_fields.append("headings")

        if score > 0 and path not in results:
            results[path] = SearchResult(
                path=path,
                title=title,
                score=score,
                match_context=_build_context(title, tags, headings, terms),
                match_fields=match_fields,
            )

    # Full-text body search from a separate content lookup (if content cache table exists)
    try:
        for row in cur.execute("SELECT path, body FROM content_cache"):
            path = row["path"]
            body = (row["body"] or "").lower()
            score = 0.0
            for term in terms:
                count = body.count(term)
                if count:
                    score += min(count * 0.5, 2.0)  # cap body score at 2
            if score > 0:
                if path in results:
                    results[path].score += score
                    if "body" not in results[path].match_fields:
                        results[path].match_fields.append("body")
                else:
                    title_row = conn.execute("SELECT title, tags, headings FROM nodes WHERE path = ?", (path,)).fetchone()
                    if title_row:
                        results[path] = SearchResult(
                            path=path,
                            title=title_row["title"] or path,
                            score=score,
                            match_context=_body_snippet(row["body"] or "", terms),
                            match_fields=["body"],
                        )
    except sqlite3.OperationalError:
        pass  # content_cache table may not exist yet

    ranked = sorted(results.values(), key=lambda r: -r.score)
    return ranked[:limit]


def _build_context(title: str, tags: list, headings: list, terms: list[str]) -> str:
    parts = []
    if title:
        parts.append(f"title: {title}")
    if tags:
        matched_tags = [t for t in tags if any(term in str(t).lower() for term in terms)]
        if matched_tags:
            parts.append(f"tags: {', '.join(str(t) for t in matched_tags)}")
    if headings:
        matched_h = [h for h in headings if any(term in str(h).lower() for term in terms)]
        if matched_h:
            parts.append(f"headings: {', '.join(str(h) for h in matched_h[:3])}")
    return " | ".join(parts)


def _body_snippet(body: str, terms: list[str]) -> str:
    """Extract a short snippet around the first match."""
    body_lower = body.lower()
    for term in terms:
        idx = body_lower.find(term)
        if idx >= 0:
            start = max(0, idx - 40)
            end = min(len(body), idx + len(term) + 60)
            snippet = body[start:end].replace("\n", " ").strip()
            return f"...{snippet}..."
    return ""
