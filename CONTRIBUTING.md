# Contributing

Contributions are welcome. This is a MIT-licensed project.

## Setup

```bash
git clone https://github.com/keppi/keppi
cd keppi
uv sync --all-extras
```

## Running Tests

```bash
uv run pytest                    # All tests
uv run pytest tests/test_mcp.py  # Specific module
uv run pytest -x                 # Stop on first failure
```

Tests use a demo vault in `tests/fixtures/demo_vault/` with 16 markdown files covering the main parsing and graph scenarios.

## Linting

```bash
uv run ruff check keppi/          # Check
uv run ruff check keppi/ --fix    # Auto-fix
```

## Adding a New MCP Tool

1. Implement the analysis logic in `keppi/analysis/` or `keppi/search/`
2. Add a `@mcp.tool()` function in `keppi/mcp/server.py`
3. Add a test in `tests/test_mcp.py` using the `_build_graph_and_db()` fixture
4. Add the CLI equivalent in `keppi/cli/main.py`
5. Document in `docs/mcp-tools.md`

## Adding a New CLI Command

1. Add a `@app.command()` function in `keppi/cli/main.py`
2. Use `_load_graph_from_db(config)` for commands that need the graph
3. Output with `console.print()` and `rich.table.Table` for tabular data
4. Document in `docs/cli-reference.md`

## Architecture

```
keppi/
├── parser/      — Markdown + frontmatter parsing; Config loading
├── graph/       — NetworkX graph construction, SQLite persistence, incremental updates
├── analysis/    — Blast radius, communities, gaps, centrality, drift, context pack, suggestions
├── search/      — Keyword search
├── mcp/         — FastMCP server (20+ tools)
├── watch/       — Watchdog file watcher daemon
└── cli/         — Typer CLI (24 commands)
```

Key invariant: **all node keys are POSIX paths** (forward slashes, relative to vault root). This is enforced via `.as_posix()` in `parser/markdown.py` and `graph/incremental.py`.

## Windows Notes

- Run tests with `uv run pytest` (not bare `pytest`)
- Set `PYTHONUTF8=1` when running CLI commands that use Rich spinners
- All path operations use `.as_posix()` to avoid `\` vs `/` inconsistencies
