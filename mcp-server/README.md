# Keppi MCP Server

MCP server that exposes the [Keppi](https://github.com/nicholasgasior/keppi) knowledge graph CLI as MCP tools. Runs via stdio transport for integration with OpenClaw or any MCP-compatible client.

## Prerequisites

- Node.js 18+
- Keppi CLI installed and on PATH (or set `KEPPI_BIN` env var)
- An Obsidian vault with an existing Keppi graph (run `keppi build` first)

## Setup

```bash
cd /home/envybot/clawd/mcp-servers/keppi-mcp
npm install
```

## Running

**Development:**
```bash
npx tsx src/index.ts
```

**Production (build first):**
```bash
npm run build
npm start
```

## Tools

| Tool | Keppi Command | Description |
|------|--------------|-------------|
| `keppi_search` | `search` + `semantic-search` | Semantic + keyword search across the vault |
| `keppi_context_pack` | `context-pack` | Build a minimal token-budgeted reading set for a topic |
| `keppi_blast_radius` | `blast-radius` | Trace connections from a note via BFS |
| `keppi_suggest_links` | `suggest-links` | Find missing connections based on tag overlap |
| `keppi_communities` | `communities` | Detect topical clusters (Louvain algorithm) |
| `keppi_gaps` | `gaps` | Find structural gaps between clusters |
| `keppi_orphans` | `orphans` | Find notes with zero connections |
| `keppi_bridges` | `bridges` | Find boundary-spanning notes (betweenness centrality) |
| `keppi_drift` | `drift` | Find stale notes connected to fresh ones |
| `keppi_hubs` | `hubs` | Top notes by degree centrality |
| `keppi_broken_links` | `broken-links` | List broken wikilinks |
| `keppi_path` | `path` | Shortest path between two notes |
| `keppi_update` | `update` | Incremental graph update |
| `keppi_embed_force` | `embed --force` | Force full re-embedding |
| `keppi_stats` | `stats` | Show graph statistics |

## OpenClaw Configuration

Add this to your `openclaw.json` under the `mcpServers` key:

```json
{
  "mcpServers": {
    "keppi": {
      "command": "node",
      "args": ["/home/envybot/clawd/mcp-servers/keppi-mcp/dist/index.js"],
      "env": {
        "KEPPI_BIN": "/home/envybot/.local/bin/keppi"
      }
    }
  }
}
```

Or for development mode:

```json
{
  "mcpServers": {
    "keppi": {
      "command": "npx",
      "args": ["tsx", "/home/envybot/clawd/mcp-servers/keppi-mcp/src/index.ts"],
      "env": {
        "KEPPI_BIN": "/home/envybot/.local/bin/keppi"
      }
    }
  }
}
```

After updating `openclaw.json`, restart the gateway:

```bash
openclaw gateway restart
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KEPPI_BIN` | `/home/envybot/.local/bin/keppi` | Path to the `keppi` CLI binary |

## Default Vault

All tools default to `/home/envybot/Documents/Obsidian Vault`. You can override the vault path per-call with the `vault` parameter.

## Architecture

Each MCP tool shells out to the `keppi` CLI binary using `child_process.execFile`, captures stdout, and returns it as tool result text. Errors are caught and returned as error text rather than crashing the server.

The `keppi_search` tool is special — it runs both `keppi search` (keyword) and `keppi semantic-search` (vector) in sequence and merges the results, giving both exact and fuzzy matches in one call.