"""Keppi command-line interface."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from keppi.parser.config import DEFAULT_CONFIG_TOML, Config, _find_config, load_config

_log = logging.getLogger("keppi.embed")
if os.environ.get("KEPPI_DEBUG") == "1":
    logging.basicConfig(level=logging.DEBUG)

try:
    import toml as _toml
except ImportError:
    _toml = None  # type: ignore[assignment]

app = typer.Typer(
    name="keppi",
    help="Keppi — Knowledge Graph Context Engine. Parse your Obsidian vault into a queryable graph.",
    add_completion=False,
)
config_app = typer.Typer(name="config", help="Get or set keppi.toml values.", add_completion=False)
app.add_typer(config_app, name="config")
console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_get_nested(d: dict, key: str) -> tuple:
    """Return (value, found) for a dot-notation key."""
    parts = key.split(".")
    for part in parts:
        if not isinstance(d, dict) or part not in d:
            return None, False
        d = d[part]
    return d, True


def _config_set_nested(d: dict, key: str, value) -> None:
    """Set a dot-notation key in a nested dict, creating intermediate dicts as needed."""
    parts = key.split(".")
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value


def _vault_hash(vault_root: Path) -> str:
    return hashlib.sha256(str(vault_root).encode()).hexdigest()[:12]


def _get_db_path(config: Config) -> Path:
    vault_root = config.vault_root()
    return config.db_path(_vault_hash(vault_root))


def _load_graph_from_db(config: Config):
    from keppi.graph.storage import load_graph, open_db

    db_path = _get_db_path(config)
    if not db_path.exists():
        vault_root = config.vault_root()
        console.print(f"[red]No graph found.[/red] Run: keppi build {vault_root}")
        raise typer.Exit(1)
    conn = open_db(db_path)
    graph = load_graph(conn)
    return graph, conn


def _resolve_note(graph, query: str) -> str | None:
    from keppi.analysis.blast_radius import find_node_by_title

    return find_node_by_title(graph, query)


def _detect_vault() -> Path | None:
    """Walk up from cwd looking for .obsidian/ directory."""
    current = Path.cwd()
    for _ in range(10):
        if (current / ".obsidian").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _install_claude_desktop(vault_path: Path) -> None:
    import platform

    if platform.system() == "Windows":
        config_dir = Path.home() / "AppData" / "Roaming" / "Claude"
    elif platform.system() == "Darwin":
        config_dir = Path.home() / "Library" / "Application Support" / "Claude"
    else:
        config_dir = Path.home() / ".config" / "Claude"

    config_file = config_dir / "claude_desktop_config.json"

    if config_file.exists():
        existing = json.loads(config_file.read_text(encoding="utf-8"))
    else:
        existing = {}

    mcp_servers = existing.setdefault("mcpServers", {})
    mcp_servers["keppi"] = {
        "command": sys.executable,
        "args": ["-m", "keppi.mcp.server"],
        "env": {"KEPPI_VAULT": str(vault_path)},
    }

    config_dir.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    console.print(f"[green]Configured Claude Desktop[/green] → {config_file}")


def _install_cursor(vault_path: Path) -> None:
    config_file = Path.home() / ".cursor" / "mcp.json"

    if config_file.exists():
        existing = json.loads(config_file.read_text(encoding="utf-8"))
    else:
        existing = {}

    mcp_servers = existing.setdefault("mcpServers", {})
    mcp_servers["keppi"] = {
        "command": sys.executable,
        "args": ["-m", "keppi.mcp.server"],
        "env": {"KEPPI_VAULT": str(vault_path)},
    }

    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    console.print(f"[green]Configured Cursor[/green] → {config_file}")


def _run_auto_embed(conn, config, vault_path, console, label: str = "") -> None:
    """Run embedding pass silently after build or watch. Fails gracefully.

    Failures log at DEBUG level (set KEPPI_DEBUG=1 to see them) but never
    propagate — auto-embed must not break build or watch.

    Skips auto-embed on first build (0% coverage) — it would hang for minutes.
    User should run 'keppi embed' explicitly for initial indexing.
    """
    try:
        from keppi.graph.builder import embed_all_notes
        from keppi.graph.storage import ensure_vec_table
        from keppi.search.providers import get_provider

        if not ensure_vec_table(conn, config.embed.dimension):
            _log.debug("auto-embed skipped: sqlite-vec unavailable")
            return

        # Skip auto-embed on first build (0% coverage) — it would hang for
        # minutes. User should run 'keppi embed' explicitly for initial indexing.
        try:
            total = conn.execute("SELECT COUNT(*) as c FROM nodes").fetchone()["c"]
            existing = conn.execute("SELECT COUNT(*) as c FROM vec_embeddings").fetchone()["c"]
        except Exception:
            existing = 0
            total = 0
        if total > 0 and existing == 0:
            console.print(
                f"[dim]  ↳ Semantic search not yet indexed. "
                f"Run [bold]keppi embed {vault_path}[/bold] to enable it.[/dim]"
            )
            return

        provider = get_provider(config)
        result = embed_all_notes(conn, provider, vault_path)

        if result["embedded"] > 0:
            console.print(
                f"[dim]  ↳ Embedded {result['embedded']} notes"
                + (f" ({result['errors']} errors)" if result["errors"] else "")
                + "[/dim]"
            )
        if result["errors"] > 0:
            console.print(
                f"[yellow]  ↳ {result['errors']} embedding errors "
                f"(run 'keppi embed' to retry)[/yellow]"
            )
    except Exception as e:
        _log.debug("auto-embed failed (%s): %s", label, e, exc_info=True)


def _suggest_similar(graph, query: str) -> None:
    """Print up to 5 notes with titles containing the query words."""
    words = query.lower().split()
    matches = []
    for node, data in graph.nodes(data=True):
        if str(node).startswith("__broken__"):
            continue
        title = data.get("title", "").lower()
        if any(w in title for w in words):
            matches.append(data.get("title", node))
    if matches:
        console.print("[dim]Similar notes:[/dim]")
        for m in matches[:5]:
            console.print(f"  • {m}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def init(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory (default: auto-detect)"),
    quick: bool = typer.Option(False, "--quick", help="Write defaults without prompts"),
) -> None:
    """Initialize keppi configuration in ~/.keppi/keppi.toml."""
    if _toml is None:
        console.print("[red]toml package required.[/red] Run: uv add toml")
        raise typer.Exit(1)

    if vault:
        vault_path = Path(vault).resolve()
    else:
        detected = _detect_vault()
        vault_path = detected or Path.cwd()
        if detected:
            console.print(f"[dim]Auto-detected Obsidian vault:[/dim] {vault_path}")

    keppi_dir = Path.home() / ".keppi"
    config_file = keppi_dir / "keppi.toml"

    # Offer to migrate old vault-root config (interactive only, not with --quick)
    migrate_content: str | None = None
    old_vault_config = vault_path / "keppi.toml"
    if old_vault_config.exists() and not config_file.exists() and not quick:
        console.print(f"[yellow]Found old vault-root config:[/yellow] {old_vault_config}")
        if typer.confirm("Migrate it to ~/.keppi/keppi.toml?", default=True):
            migrate_content = old_vault_config.read_text(encoding="utf-8")

    if config_file.exists() and not quick:
        console.print(f"[yellow]keppi.toml already exists:[/yellow] {config_file}")
        if not typer.confirm("Overwrite?", default=False):
            raise typer.Exit(0)

    keppi_dir.mkdir(parents=True, exist_ok=True)
    base = _toml.loads(migrate_content or DEFAULT_CONFIG_TOML)
    base.setdefault("vault", {})["path"] = str(vault_path)
    config_file.write_text(_toml.dumps(base), encoding="utf-8")

    console.print("[green]Created[/green] ~/.keppi/keppi.toml")
    console.print(f"[dim]Vault:[/dim] {vault_path}")


@app.command()
def build(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
) -> None:
    """Parse all notes and build the graph from scratch."""
    from keppi.graph.builder import GraphBuilder
    from keppi.graph.storage import open_db, save_graph
    from keppi.parser.markdown import collect_markdown_files, parse_note

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    vault_root = config.vault_root()

    files = collect_markdown_files(
        vault_root,
        config.vault.file_extensions,
        config.vault.exclude_dirs,
        config.vault.exclude_patterns,
    )

    builder = GraphBuilder(config)
    notes = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Parsing notes…", total=len(files))
        for f in files:
            note = parse_note(f, vault_root)
            builder.add_note(note)
            notes.append(note)
            progress.advance(task)

    with console.status("Building edges…"):
        for note in notes:
            builder.add_edges(note)
        builder.compute_tag_edges()

    db_path = _get_db_path(config)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with console.status("Saving graph…"):
        conn = open_db(db_path)
        save_graph(conn, builder.graph, str(vault_root))

    node_count = sum(1 for n in builder.graph.nodes if not str(n).startswith("__broken__"))
    edge_count = builder.graph.number_of_edges()
    console.print(
        f"[green]Built[/green] {node_count} notes, {edge_count:,} edges → {db_path}"
    )

    # Check if embeddings exist and hint if not
    if config.embed.auto_embed:
        try:
            from keppi.graph.storage import ensure_vec_table
            if ensure_vec_table(conn, config.embed.dimension):
                existing = conn.execute("SELECT COUNT(*) as c FROM vec_embeddings").fetchone()["c"]
                if existing == 0:
                    console.print(
                        f"[dim]  ↳ Semantic search not yet indexed. "
                        f"Run [bold]keppi embed {vault_path}[/bold] to enable it.[/dim]"
                    )
        except Exception:
            pass

    # Auto-embed is intentionally NOT run after `keppi build`. Full embed
    # can take 30+ minutes with Ollama on a large vault. Users should run
    # `keppi embed` explicitly. Auto-embed only fires on file watcher events
    # (incremental, one note at a time) which are fast.

    conn.close()


@app.command()
def update(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
) -> None:
    """Incremental update — only parses changed files."""
    from keppi.graph.incremental import incremental_update
    from keppi.graph.storage import load_graph, open_db

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)

    db_path = _get_db_path(config)
    if not db_path.exists():
        console.print("[yellow]No existing graph found — running full build.[/yellow]")
        ctx = typer.get_current_context()
        ctx.invoke(build, vault=vault)
        return

    conn = open_db(db_path)
    graph = load_graph(conn)

    with console.status("Scanning for changes…"):
        counts = incremental_update(conn, graph, config)

    conn.close()
    console.print(
        f"[green]Updated[/green] +{counts['added']} added, "
        f"~{counts['updated']} changed, -{counts['deleted']} removed, "
        f"{counts['unchanged']} unchanged"
    )


@app.command()
def stats(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
) -> None:
    """Show graph statistics."""
    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    from keppi.analysis.suggestions import find_broken_links

    real_nodes = [n for n in graph.nodes if not str(n).startswith("__broken__")]
    edges = list(graph.edges(data=True))

    edge_type_counts: dict[str, int] = {}
    for _, _, data in edges:
        t = data.get("type", "unknown")
        edge_type_counts[t] = edge_type_counts.get(t, 0) + 1

    orphan_count = sum(
        1 for n in real_nodes
        if graph.in_degree(n) == 0 and graph.out_degree(n) == 0
    )
    broken = find_broken_links(graph)

    console.print(f"Nodes:    {len(real_nodes):,}  ({len(real_nodes) - orphan_count:,} notes, {orphan_count} orphans)")
    console.print(f"Edges:    {len(edges):,}")
    if len(real_nodes) > 1:
        density = len(edges) / (len(real_nodes) * (len(real_nodes) - 1))
        console.print(f"Density:  {density:.6f}")
    type_str = "  ".join(f"{k}: {v:,}" for k, v in sorted(edge_type_counts.items(), key=lambda x: -x[1]))
    console.print(f"Edge types:  {type_str}")
    console.print(f"Broken links: {len(broken)}")
    conn.close()


@app.command()
def watch(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    stop: bool = typer.Option(False, "--stop", help="Stop the running watcher"),
) -> None:
    """Start (or stop) a background file watcher for automatic incremental updates."""
    from keppi.watch.daemon import stop_watcher

    if stop:
        if stop_watcher():
            console.print("[green]Watcher stopped.[/green]")
        else:
            console.print("[yellow]No watcher running.[/yellow]")
        return

    from keppi.watch.daemon import start_watcher

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    db_path = _get_db_path(config)

    if not db_path.exists():
        console.print("[red]No graph found.[/red] Run: keppi build first.")
        raise typer.Exit(1)

    start_watcher(config, db_path)


@app.command(name="blast-radius")
def blast_radius(
    note: str = typer.Argument(..., help="Note title or path"),
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    depth: int = typer.Option(2, "--depth", "-d", help="BFS depth"),
    threshold: float = typer.Option(0.3, "--threshold", "-t", help="Minimum relevance score"),
    direction: str = typer.Option("both", "--direction", help="'out', 'in', or 'both'"),
) -> None:
    """BFS impact analysis — which notes are affected if NOTE changes."""
    from keppi.analysis.blast_radius import compute_blast_radius

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    seed = _resolve_note(graph, note)
    if seed is None:
        console.print(f"[red]Note not found:[/red] {note}")
        _suggest_similar(graph, note)
        conn.close()
        raise typer.Exit(1)

    results = compute_blast_radius(graph, seed, depth=depth, threshold=threshold, direction=direction)

    table = Table(title=f"Blast radius: {note} (depth={depth})")
    table.add_column("Title", style="bold")
    table.add_column("Relevance", justify="right")
    table.add_column("Distance", justify="right")
    table.add_column("Edge types")

    for r in results:
        table.add_row(
            r.title,
            f"{r.relevance:.2f}",
            str(r.distance),
            ", ".join(r.edge_types),
        )

    console.print(table)
    console.print(f"[dim]{len(results)} notes affected[/dim]")
    conn.close()


@app.command()
def traverse(
    note: str = typer.Argument(..., help="Note title or path"),
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    depth: int = typer.Option(2, "--depth", "-d", help="Traversal depth"),
) -> None:
    """Expand the graph from a note, showing all reachable notes."""
    from collections import deque

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    seed = _resolve_note(graph, note)
    if seed is None:
        console.print(f"[red]Note not found:[/red] {note}")
        _suggest_similar(graph, note)
        conn.close()
        raise typer.Exit(1)

    visited: dict[str, int] = {seed: 0}
    queue: deque = deque([(seed, 0)])

    while queue:
        current, dist = queue.popleft()
        if dist >= depth:
            continue
        for _, neighbor, data in graph.out_edges(current, data=True):
            if neighbor not in visited and not str(neighbor).startswith("__broken__"):
                visited[neighbor] = dist + 1
                queue.append((neighbor, dist + 1))

    table = Table(title=f"Traversal: {note} (depth={depth})")
    table.add_column("Title", style="bold")
    table.add_column("Distance", justify="right")
    table.add_column("Path")

    for node, dist in sorted(visited.items(), key=lambda x: (x[1], x[0])):
        if node == seed:
            continue
        data = graph.nodes[node]
        table.add_row(data.get("title", node), str(dist), node)

    console.print(table)
    conn.close()


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum results"),
) -> None:
    """Keyword search across title, tags, headings, and body."""
    from keppi.search.keyword import keyword_search

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    results = keyword_search(conn, query, limit=limit)

    if not results:
        console.print(f"[yellow]No results for:[/yellow] {query}")
        conn.close()
        return

    table = Table(title=f"Search: {query}")
    table.add_column("Title", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Tags")

    for r in results:
        import json as _json
        try:
            tags = _json.loads(r.tags) if isinstance(r.tags, str) else r.tags
        except Exception:
            tags = []
        table.add_row(r.title, f"{r.score:.1f}", ", ".join(tags[:5]))

    console.print(table)

    # Tip: show semantic search hint if embeddings exist
    try:
        count = conn.execute("SELECT COUNT(*) as c FROM vec_embeddings").fetchone()["c"]
        if count > 0:
            console.print(
                f"[dim]Tip: keppi semantic-search '{query}' for meaning-based results[/dim]"
            )
    except Exception:
        pass

    conn.close()


@app.command()
def embed(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    force: bool = typer.Option(False, "--force", help="Re-embed all notes, ignoring existing embeddings"),
) -> None:
    """Build semantic embeddings for all notes in the vault."""
    from keppi.graph.builder import embed_all_notes
    from keppi.graph.storage import ensure_vec_table, open_db
    from keppi.search.providers import get_provider

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)

    db_path = _get_db_path(config)
    if not db_path.exists():
        console.print(f"[red]No graph found.[/red] Run: keppi build {vault_path}")
        raise typer.Exit(1)

    conn = open_db(db_path)

    if not ensure_vec_table(conn, config.embed.dimension):
        console.print(
            "[red]sqlite-vec not available.[/red] "
            "Install it: pip install sqlite-vec"
        )
        conn.close()
        raise typer.Exit(1)

    # Warn if a dimension rebuild is pending
    try:
        rebuild_flag = conn.execute(
            "SELECT value FROM meta WHERE key='embed_needs_rebuild'"
        ).fetchone()
        if rebuild_flag and rebuild_flag["value"] == "1":
            console.print(
                "[yellow]Warning: dimension change detected — full rebuild required.[/yellow]"
            )
    except Exception:
        pass

    try:
        provider = get_provider(config)
    except Exception as e:
        console.print(f"[red]Provider error:[/red] {e}")
        conn.close()
        raise typer.Exit(1)

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Embedding notes", total=None)

        def cb(current: int, total: int, title: str) -> None:
            progress.update(
                task,
                total=total,
                completed=current,
                description=f"Embedding: {title[:40]}",
            )

        try:
            result = embed_all_notes(conn, provider, vault_path, force=force, progress_callback=cb)
        except RuntimeError as e:
            err = str(e)
            if "Ollama" in err or "localhost:11434" in err:
                url = config.embed.base_url or "http://localhost:11434"
                console.print(f"[red]Could not reach Ollama at {url}[/red]")
                console.print("Run: ollama serve")
            else:
                console.print(f"[red]Embedding error:[/red] {e}")
                if config.embed.provider == "openai":
                    console.print(f"Check your {config.embed.api_key_env} env var")
            conn.close()
            raise typer.Exit(1)

    table = Table(title="Embed results")
    table.add_column("Result", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Embedded", str(result["embedded"]))
    table.add_row("Chunks", str(result.get("chunks", 0)))
    table.add_row("Skipped", str(result["skipped"]))
    table.add_row("Errors", str(result["errors"]))
    console.print(table)

    if result["errors"] > 0:
        console.print(
            f"[yellow]{result['errors']} errors — run with KEPPI_DEBUG=1 for details[/yellow]"
        )

    conn.close()


@app.command(name="semantic-search")
def semantic_search(
    query: str = typer.Argument(..., help="Natural language search query"),
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results"),
    subfolder: Optional[str] = typer.Option(None, "--subfolder", help="Restrict to a subfolder (e.g. 'wiki' or 'projects/active')"),
) -> None:
    """Semantic vector search — finds notes by meaning, not just keywords."""
    from keppi.graph.storage import ensure_vec_table, open_db
    from keppi.search.providers import get_provider
    from keppi.search.semantic import semantic_search as _search

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)

    db_path = _get_db_path(config)
    if not db_path.exists():
        console.print(f"[red]No graph found.[/red] Run: keppi build {vault_path}")
        raise typer.Exit(1)

    conn = open_db(db_path)

    if not ensure_vec_table(conn, config.embed.dimension):
        console.print(
            "[red]sqlite-vec not available.[/red] "
            "Install it: pip install sqlite-vec"
        )
        conn.close()
        raise typer.Exit(1)

    # Check that embeddings exist
    try:
        count = conn.execute("SELECT COUNT(*) as c FROM vec_embeddings").fetchone()["c"]
        if count == 0:
            console.print(
                f"[yellow]No embeddings found.[/yellow] "
                f"Run: keppi embed {vault_path}"
            )
            conn.close()
            raise typer.Exit(1)
    except Exception:
        console.print(f"[yellow]No embeddings found.[/yellow] Run: keppi embed {vault_path}")
        conn.close()
        raise typer.Exit(1)

    try:
        provider = get_provider(config)
    except Exception as e:
        console.print(f"[red]Provider error:[/red] {e}")
        conn.close()
        raise typer.Exit(1)

    search_subfolder = subfolder or config.vault.wiki_subfolder or None

    try:
        results = _search(conn, query, provider, limit=limit, subfolder=search_subfolder)
    except RuntimeError as e:
        err = str(e)
        if "Ollama" in err or "localhost:11434" in err:
            url = config.embed.base_url or "http://localhost:11434"
            console.print(f"[red]Could not reach Ollama at {url}[/red]")
            console.print("Run: ollama serve")
        else:
            console.print(f"[red]Provider error:[/red] {e}")
            if config.embed.provider == "openai":
                console.print(f"Check your {config.embed.api_key_env} env var")
        conn.close()
        raise typer.Exit(1)

    if not results:
        console.print(
            f"[yellow]No results.[/yellow] "
            f"Run: keppi embed {vault_path} to build embeddings first."
        )
        conn.close()
        return

    table = Table(title=f"Semantic search: {query}")
    table.add_column("Distance", justify="right")
    table.add_column("Strength")
    table.add_column("Title", style="bold")
    table.add_column("Path")

    for r in results:
        dist = round(r.distance, 4)
        if r.distance < 0.3:
            dist_str = f"[green]{dist}[/green]"
        elif r.distance < 0.5:
            dist_str = f"[yellow]{dist}[/yellow]"
        else:
            dist_str = f"[red]{dist}[/red]"
        path_display = r.path if len(r.path) <= 55 else "..." + r.path[-52:]
        table.add_row(dist_str, r.match_context.replace(" match", ""), r.title, path_display)

    console.print(table)
    conn.close()


@app.command()
def orphans(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
) -> None:
    """Notes with zero inbound and zero outbound connections."""
    from keppi.analysis.centrality import find_orphans

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    results = find_orphans(graph)

    if not results:
        console.print("[green]No orphans found.[/green]")
        conn.close()
        return

    table = Table(title=f"Orphans ({len(results)})")
    table.add_column("Title", style="bold")
    table.add_column("Path")

    for r in results:
        table.add_row(r.title, r.path)

    console.print(table)
    conn.close()


@app.command()
def communities(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    min_size: int = typer.Option(3, "--min-size", help="Minimum community size"),
    top: int = typer.Option(10, "--top", "-n", help="Maximum communities to show"),
) -> None:
    """Detect topical clusters using the Louvain algorithm."""
    from keppi.analysis.communities import detect_communities

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    with console.status("Detecting communities…"):
        comms = detect_communities(graph, min_size=min_size)

    comms = comms[:top]

    table = Table(title=f"Communities (min_size={min_size})")
    table.add_column("#", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Representative", style="bold")
    table.add_column("Top tags")

    for i, c in enumerate(comms, 1):
        import json as _json
        try:
            tags = _json.loads(c.top_tags) if isinstance(c.top_tags, str) else c.top_tags
        except Exception:
            tags = c.top_tags if isinstance(c.top_tags, list) else []
        rep_data = graph.nodes.get(c.representative, {})
        rep_title = rep_data.get("title", c.representative)
        table.add_row(str(i), str(c.size), rep_title, ", ".join(tags[:5]))

    console.print(table)
    conn.close()


@app.command()
def gaps(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    max_bridges: int = typer.Option(2, "--max-bridges", help="Max bridge edges to call it a gap"),
    min_shared: int = typer.Option(1, "--min-shared", help="Minimum shared tags"),
) -> None:
    """Find structural gaps between clusters."""
    from keppi.analysis.communities import detect_communities
    from keppi.analysis.gaps import detect_gaps

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    with console.status("Detecting communities and gaps…"):
        comms = detect_communities(graph, min_size=2)
        gap_list = detect_gaps(graph, comms, max_bridge_edges=max_bridges, min_shared_tags=min_shared)

    if not gap_list:
        console.print("[green]No significant gaps found.[/green]")
        conn.close()
        return

    table = Table(title=f"Structural gaps ({len(gap_list)})")
    table.add_column("Community A", style="bold")
    table.add_column("Community B", style="bold")
    table.add_column("Shared tags")
    table.add_column("Bridge edges", justify="right")

    for g in gap_list:
        table.add_row(
            g.community_a_rep,
            g.community_b_rep,
            ", ".join(g.shared_tags[:5]),
            str(g.bridge_edges),
        )

    console.print(table)
    conn.close()


@app.command()
def hubs(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    top: int = typer.Option(10, "--top", "-n", help="Number of hubs to show"),
) -> None:
    """Top notes by degree centrality."""
    from keppi.analysis.centrality import find_hubs

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    results = find_hubs(graph, top_n=top)

    table = Table(title=f"Top {top} hubs")
    table.add_column("Rank", justify="right")
    table.add_column("Title", style="bold")
    table.add_column("Centrality", justify="right")

    for i, r in enumerate(results, 1):
        table.add_row(str(i), r.title, f"{r.score:.4f}")

    console.print(table)
    conn.close()


@app.command()
def bridges(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    top: int = typer.Option(10, "--top", "-n", help="Number of bridges to show"),
) -> None:
    """Top boundary-spanning notes by betweenness centrality. (Can be slow on large vaults.)"""
    from keppi.analysis.centrality import find_bridges

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    with console.status("Computing betweenness centrality (may take a moment)…"):
        results = find_bridges(graph, top_n=top)

    table = Table(title=f"Top {top} bridges")
    table.add_column("Rank", justify="right")
    table.add_column("Title", style="bold")
    table.add_column("Betweenness", justify="right")

    for i, r in enumerate(results, 1):
        table.add_row(str(i), r.title, f"{r.score:.4f}")

    console.print(table)
    conn.close()


@app.command()
def drift(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    stale: int = typer.Option(30, "--stale", help="Days without update to be stale"),
    recent: int = typer.Option(14, "--recent", help="Days to consider recent"),
) -> None:
    """Find stale notes connected to recently-updated ones."""
    from keppi.analysis.drift import detect_drift

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    results = detect_drift(graph, stale_days=stale, recent_days=recent)

    if not results:
        console.print("[green]No drift detected.[/green]")
        conn.close()
        return

    table = Table(title=f"Drift: stale >{stale}d, neighbor updated <{recent}d")
    table.add_column("Stale note", style="bold")
    table.add_column("Last updated")
    table.add_column("Days stale")
    table.add_column("Connected to recent")

    for r in results:
        table.add_row(r.title, r.last_updated, str(r.days_stale), r.reason)

    console.print(table)
    conn.close()


@app.command(name="broken-links")
def broken_links(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    top: int = typer.Option(0, "--top", "-n", help="Limit results (0 = all)"),
) -> None:
    """List broken wikilinks (targets that don't exist)."""
    from keppi.analysis.suggestions import find_broken_links

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    broken = find_broken_links(graph)
    if top:
        broken = broken[:top]

    if not broken:
        console.print("[green]No broken links found.[/green]")
        conn.close()
        return

    table = Table(title=f"Broken links ({len(broken)})")
    table.add_column("Source", style="bold")
    table.add_column("Source path", style="dim")
    table.add_column("Missing target", style="red")

    for b in broken:
        table.add_row(
            b.get("source_title", b.get("source_path", "")),
            b.get("source_path", ""),
            b.get("target_name", b.get("target", "")),
        )

    console.print(table)
    conn.close()


@app.command(name="suggest-links")
def suggest_links(
    note: Optional[str] = typer.Argument(None, help="Note title (omit for global)"),
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    top: int = typer.Option(10, "--top", "-n", help="Maximum suggestions"),
    min_score: float = typer.Option(0.3, "--min-score", help="Minimum suggestion score"),
) -> None:
    """Suggest missing connections based on tag overlap and shared neighbors."""
    from keppi.analysis.suggestions import suggest_links as _suggest

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    source = None
    if note:
        source = _resolve_note(graph, note)
        if source is None:
            console.print(f"[red]Note not found:[/red] {note}")
            conn.close()
            raise typer.Exit(1)

    with console.status("Computing link suggestions…"):
        results = _suggest(graph, source, top_n=top, min_score=min_score)

    if not results:
        console.print("[green]No link suggestions found.[/green]")
        conn.close()
        return

    title = f"Link suggestions for: {note}" if note else "Global link suggestions"
    table = Table(title=title)
    table.add_column("From", style="bold")
    table.add_column("From path", style="dim")
    table.add_column("To", style="bold")
    table.add_column("To path", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Reason")

    for r in results:
        table.add_row(
            r.source_title,
            r.source_path,
            r.target_title,
            r.target_path,
            f"{r.score:.2f}",
            "; ".join(r.reasons),
        )

    console.print(table)
    conn.close()


@app.command(name="context-pack")
def context_pack(
    topic: str = typer.Argument(..., help="Topic or note title"),
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    budget: int = typer.Option(4000, "--budget", help="Token budget"),
    depth: int = typer.Option(2, "--depth", "-d", help="Blast radius depth"),
) -> None:
    """Build a minimal token-budgeted reading set for a topic."""
    from keppi.analysis.context_pack import build_context_pack

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    with console.status("Building context pack…"):
        pack = build_context_pack(graph, conn, topic, token_budget=budget, depth=depth)

    table = Table(
        title=f"Context pack: {topic}  ({pack.total_tokens:,}/{budget:,} tokens)"
    )
    table.add_column("Title", style="bold")
    table.add_column("Relevance", justify="right")
    table.add_column("~Tokens", justify="right")
    table.add_column("Tags")

    for e in pack.entries:
        import json as _json
        try:
            tags = _json.loads(e.tags) if isinstance(e.tags, str) else e.tags
        except Exception:
            tags = e.tags if isinstance(e.tags, list) else []
        table.add_row(
            e.title,
            f"{e.relevance:.2f}",
            str(e.estimated_tokens),
            ", ".join(tags[:4]),
        )

    console.print(table)
    conn.close()


@app.command()
def path(
    source: str = typer.Argument(..., help="Source note title"),
    target: str = typer.Argument(..., help="Target note title"),
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
) -> None:
    """Shortest path between two notes (ignores edge direction)."""
    import networkx as nx

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)

    src_node = _resolve_note(graph, source)
    if src_node is None:
        console.print(f"[red]Source not found:[/red] {source}")
        conn.close()
        raise typer.Exit(1)

    tgt_node = _resolve_note(graph, target)
    if tgt_node is None:
        console.print(f"[red]Target not found:[/red] {target}")
        conn.close()
        raise typer.Exit(1)

    # Structural-only path by default — tag_overlap creates false bridges
    structural_types = {"wikilink", "related_to", "embed", "semantic_similarity"}
    undirected = nx.Graph()
    undirected.add_nodes_from(n for n in graph.nodes if not str(n).startswith("__broken__"))
    for u, v, d in graph.edges(data=True):
        if d.get("type") in structural_types:
            undirected.add_edge(u, v)
    try:
        shortest = nx.shortest_path(undirected, src_node, tgt_node)
    except nx.NetworkXNoPath:
        console.print(f"[yellow]No path found between:[/yellow] {source} → {target}")
        conn.close()
        return
    except nx.NodeNotFound as e:
        console.print(f"[red]Node not found:[/red] {e}")
        conn.close()
        raise typer.Exit(1)

    titles = [graph.nodes[n].get("title", n) for n in shortest]
    console.print(f"[bold]{len(shortest) - 1} hop(s):[/bold] " + " → ".join(titles))
    conn.close()


@app.command(name="mcp-server")
def mcp_server(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    transport: str = typer.Option("stdio", "--transport", help="'stdio' or 'sse'"),
    port: int = typer.Option(3000, "--port", help="Port for SSE transport"),
) -> None:
    """Start the MCP server."""
    import os

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    os.environ["KEPPI_VAULT"] = str(vault_path)

    from keppi.mcp.server import mcp

    if transport == "sse":
        mcp.run(transport="sse", port=port)
    else:
        mcp.run(transport="stdio")


@app.command()
def install(
    platform: str = typer.Argument(..., help="Platform: 'claude' or 'cursor'"),
    vault: Optional[str] = typer.Option(None, "--vault", help="Vault directory"),
) -> None:
    """Auto-configure Keppi as an MCP server for a platform."""
    vault_path = Path(vault).resolve() if vault else Path.cwd()

    if platform == "claude":
        _install_claude_desktop(vault_path)
    elif platform == "cursor":
        _install_cursor(vault_path)
    else:
        console.print(f"[red]Unknown platform:[/red] {platform}. Use 'claude' or 'cursor'.")
        raise typer.Exit(1)


@app.command()
def export(
    vault: Optional[str] = typer.Option(None, "--vault", "-v", help="Vault directory"),
    format: str = typer.Option("json", "--format", "-f", help="'json' or 'graphml'"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file (default: stdout)"),
) -> None:
    """Export the graph to JSON or GraphML."""
    import networkx as nx

    vault_path = Path(vault).resolve() if vault else Path.cwd()
    config = load_config(vault_path)
    config.vault.path = str(vault_path)
    graph, conn = _load_graph_from_db(config)
    conn.close()

    real_nodes = {n for n in graph.nodes if not str(n).startswith("__broken__")}
    subgraph = graph.subgraph(real_nodes)

    if format == "graphml":
        data = "\n".join(nx.generate_graphml(subgraph))
        if output:
            Path(output).write_text(data, encoding="utf-8")
            console.print(f"[green]Exported GraphML[/green] → {output}")
        else:
            print(data)
    else:
        node_list = []
        for n, d in subgraph.nodes(data=True):
            node_list.append({
                "path": n,
                "title": d.get("title", ""),
                "type": d.get("type", ""),
                "tags": d.get("tags", []),
                "word_count": d.get("word_count", 0),
            })

        edge_list = []
        for src, dst, d in subgraph.edges(data=True):
            edge_list.append({
                "src": src,
                "dst": dst,
                "type": d.get("type", ""),
                "weight": d.get("weight", 1.0),
            })

        payload = {
            "node_count": len(node_list),
            "edge_count": len(edge_list),
            "nodes": node_list,
            "edges": edge_list,
        }

        json_str = json.dumps(payload, indent=2)
        if output:
            Path(output).write_text(json_str, encoding="utf-8")
            console.print(f"[green]Exported JSON[/green] → {output}")
        else:
            print(json_str)


@config_app.command("get")
def config_get(
    key: Optional[str] = typer.Argument(None, help="Dot-notation key (e.g. vault.exclude_dirs). Omit to print entire config."),
) -> None:
    """Print a config value, or the entire config when no key is given."""
    if _toml is None:
        console.print("[red]toml package required.[/red] Run: uv add toml")
        raise typer.Exit(1)

    config_file = _find_config(Path.cwd())
    if config_file is None:
        console.print("[red]keppi.toml not found.[/red] Run: keppi init")
        raise typer.Exit(1)

    raw = _toml.loads(config_file.read_text(encoding="utf-8"))

    if key is None:
        console.print(_toml.dumps(raw), markup=False, highlight=False)
        return

    value, found = _config_get_nested(raw, key)
    if not found:
        console.print(f"[red]Key not found:[/red] {key}")
        raise typer.Exit(1)

    console.print(value)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Dot-notation key (e.g. graph.relevance_threshold)"),
    value: str = typer.Argument(..., help="Value parsed as TOML — strings need quotes, e.g. '\"mydir\"'"),
) -> None:
    """Set a config value. VALUE is parsed as TOML (numbers, strings, lists all work)."""
    if _toml is None:
        console.print("[red]toml package required.[/red] Run: uv add toml")
        raise typer.Exit(1)

    config_file = _find_config(Path.cwd())
    if config_file is None:
        console.print("[red]keppi.toml not found.[/red] Run: keppi init")
        raise typer.Exit(1)

    try:
        parsed_value = _toml.loads(f"x = {value}")["x"]
    except Exception:
        parsed_value = value  # fall back to treating as a raw string

    raw = _toml.loads(config_file.read_text(encoding="utf-8"))
    _config_set_nested(raw, key, parsed_value)
    config_file.write_text(_toml.dumps(raw), encoding="utf-8")
    console.print(f"[green]Set[/green] {key} = {parsed_value!r}  ({config_file})")


@config_app.command("add")
def config_add(
    key: str = typer.Argument(..., help="Dot-notation key to a list (e.g. vault.exclude_dirs)"),
    value: str = typer.Argument(..., help="String value to append"),
) -> None:
    """Append a string value to a list config key."""
    if _toml is None:
        console.print("[red]toml package required.[/red] Run: uv add toml")
        raise typer.Exit(1)

    config_file = _find_config(Path.cwd())
    if config_file is None:
        console.print("[red]keppi.toml not found.[/red] Run: keppi init")
        raise typer.Exit(1)

    raw = _toml.loads(config_file.read_text(encoding="utf-8"))
    current, found = _config_get_nested(raw, key)

    if not found:
        current = []
    elif not isinstance(current, list):
        console.print(f"[red]{key} is not a list.[/red]")
        raise typer.Exit(1)

    if value not in current:
        _config_set_nested(raw, key, list(current) + [value])
        config_file.write_text(_toml.dumps(raw), encoding="utf-8")

    console.print(f"[green]Added[/green] {value!r} to {key}  ({config_file})")


@config_app.command("remove")
def config_remove(
    key: str = typer.Argument(..., help="Dot-notation key to a list (e.g. vault.exclude_dirs)"),
    value: str = typer.Argument(..., help="String value to remove"),
) -> None:
    """Remove a string value from a list config key."""
    if _toml is None:
        console.print("[red]toml package required.[/red] Run: uv add toml")
        raise typer.Exit(1)

    config_file = _find_config(Path.cwd())
    if config_file is None:
        console.print("[red]keppi.toml not found.[/red] Run: keppi init")
        raise typer.Exit(1)

    raw = _toml.loads(config_file.read_text(encoding="utf-8"))
    current, found = _config_get_nested(raw, key)

    if not found or not isinstance(current, list):
        console.print(f"[red]{key} is not a list or does not exist.[/red]")
        raise typer.Exit(1)

    if value in current:
        _config_set_nested(raw, key, [v for v in current if v != value])
        config_file.write_text(_toml.dumps(raw), encoding="utf-8")

    console.print(f"[green]Removed[/green] {value!r} from {key}  ({config_file})")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
