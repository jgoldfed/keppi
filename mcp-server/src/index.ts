#!/usr/bin/env node

/**
 * Keppi MCP Server
 *
 * Exposes the Keppi knowledge graph CLI as MCP tools via stdio transport.
 * Keppi is a CLI tool for knowledge graph operations on an Obsidian vault.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { z } from "zod";

const execFileAsync = promisify(execFile);

const DEFAULT_VAULT = "/home/envybot/Documents/Obsidian Vault";
const KEPPI_BIN = process.env.KEPPI_BIN || "/home/envybot/.local/bin/keppi";

/** Run a keppi CLI command and return stdout, or an error message on failure. */
async function runKeppi(args: string[]): Promise<string> {
  try {
    const { stdout, stderr } = await execFileAsync(KEPPI_BIN, args, {
      maxBuffer: 2 * 1024 * 1024, // 2 MB — some commands produce large output
      timeout: 120_000, // 2 minutes — embed can be slow
    });
    // Some keppi commands write progress to stderr; include it if there's no stdout
    if (stdout.trim()) return stdout.trim();
    if (stderr.trim()) return stderr.trim();
    return "(no output)";
  } catch (err: any) {
    const msg = err?.stderr?.toString()?.trim() || err?.message || String(err);
    return `Error: ${msg}`;
  }
}

const server = new McpServer({ name: "keppi-mcp", version: "1.0.0" });

// ─── Tools ───────────────────────────────────────────────────────────────────

server.tool(
  "keppi_search",
  `Semantic + keyword search across the Obsidian vault. Runs \`keppi search\` and \`keppi semantic-search\` and merges results.`,
  {
    query: z.string().describe("Search query — keywords or natural language."),
    top_k: z.number().optional().default(10).describe("Maximum number of results."),
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ query, top_k, vault }) => {
    const kw = await runKeppi(["search", query, "--limit", String(top_k), vault]);
    const sem = await runKeppi(["semantic-search", query, "--limit", String(top_k), vault]);
    return { content: [{ type: "text" as const, text: `## Keyword results\n${kw}\n\n## Semantic results\n${sem}` }] };
  }
);

server.tool(
  "keppi_context_pack",
  `Build a minimal token-budgeted reading set for a topic. Runs \`keppi context-pack\`.`,
  {
    topic: z.string().describe("Topic or note title to build context around."),
    budget: z.number().optional().default(4000).describe("Token budget for the context pack."),
    depth: z.number().optional().default(2).describe("Blast-radius depth for traversal."),
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ topic, budget, depth, vault }) => {
    const result = await runKeppi(["context-pack", topic, "--budget", String(budget), "--depth", String(depth), vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_blast_radius",
  `Trace connections from a note via BFS. Runs \`keppi blast-radius\`.`,
  {
    note: z.string().describe("Note title or path to trace from."),
    depth: z.number().optional().default(2).describe("BFS traversal depth."),
    threshold: z.number().optional().default(0.3).describe("Minimum relevance score."),
    direction: z.enum(["out", "in", "both"]).optional().default("both").describe("Edge direction to follow."),
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ note, depth, threshold, direction, vault }) => {
    const result = await runKeppi(["blast-radius", note, "--depth", String(depth), "--threshold", String(threshold), "--direction", direction, vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_suggest_links",
  `Find missing connections based on tag overlap and shared neighbors. Runs \`keppi suggest-links\`.`,
  {
    note: z.string().optional().describe("Note title (omit for global suggestions)."),
    top: z.number().optional().default(15).describe("Maximum number of suggestions."),
    min_score: z.number().optional().default(0.3).describe("Minimum suggestion score."),
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ note, top, min_score, vault }) => {
    const args = ["suggest-links", "--top", String(top), "--min-score", String(min_score)];
    if (note) args.push(note);
    args.push(vault);
    const result = await runKeppi(args);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_communities",
  `Detect topical clusters using the Louvain algorithm. Runs \`keppi communities\`.`,
  {
    top: z.number().optional().default(10).describe("Maximum number of communities to show."),
    min_size: z.number().optional().default(3).describe("Minimum community size."),
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ top, min_size, vault }) => {
    const result = await runKeppi(["communities", "--top", String(top), "--min-size", String(min_size), vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_gaps",
  `Find structural gaps between clusters. Runs \`keppi gaps\`.`,
  {
    max_bridges: z.number().optional().default(2).describe("Max bridge edges to call it a gap."),
    min_shared: z.number().optional().default(1).describe("Minimum shared tags."),
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ max_bridges, min_shared, vault }) => {
    const result = await runKeppi(["gaps", "--max-bridges", String(max_bridges), "--min-shared", String(min_shared), vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_orphans",
  `Find notes with zero inbound and zero outbound connections. Runs \`keppi orphans\`.`,
  {
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ vault }) => {
    const result = await runKeppi(["orphans", vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_bridges",
  `Find boundary-spanning notes by betweenness centrality. Runs \`keppi bridges\`.`,
  {
    top: z.number().optional().default(10).describe("Number of bridges to show."),
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ top, vault }) => {
    const result = await runKeppi(["bridges", "--top", String(top), vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_drift",
  `Find stale notes connected to recently-updated ones. Runs \`keppi drift\`.`,
  {
    stale: z.number().optional().default(30).describe("Days without update to be considered stale."),
    recent: z.number().optional().default(14).describe("Days to consider recent."),
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ stale, recent, vault }) => {
    const result = await runKeppi(["drift", "--stale", String(stale), "--recent", String(recent), vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_hubs",
  `Top notes by degree centrality. Runs \`keppi hubs\`.`,
  {
    top: z.number().optional().default(10).describe("Number of hubs to show."),
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ top, vault }) => {
    const result = await runKeppi(["hubs", "--top", String(top), vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_broken_links",
  `List broken wikilinks (targets that don't exist). Runs \`keppi broken-links\`.`,
  {
    top: z.number().optional().default(0).describe("Limit results (0 = all)."),
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ top, vault }) => {
    const result = await runKeppi(["broken-links", "--top", String(top), vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_path",
  `Find the shortest path between two notes. Runs \`keppi path\`.`,
  {
    source: z.string().describe("Source note title."),
    target: z.string().describe("Target note title."),
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ source, target, vault }) => {
    const result = await runKeppi(["path", source, target, vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_update",
  `Incremental graph update — only parses changed files. Runs \`keppi update\`.`,
  {
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ vault }) => {
    const result = await runKeppi(["update", vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_embed_force",
  `Force full re-embedding of all notes. Runs \`keppi embed --force\`.`,
  {
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ vault }) => {
    const result = await runKeppi(["embed", "--force", vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

server.tool(
  "keppi_stats",
  `Show graph statistics. Runs \`keppi stats\`.`,
  {
    vault: z.string().optional().default(DEFAULT_VAULT).describe("Vault directory path."),
  },
  async ({ vault }) => {
    const result = await runKeppi(["stats", vault]);
    return { content: [{ type: "text" as const, text: result }] };
  }
);

// ─── Start ───────────────────────────────────────────────────────────────────

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  // Server is now running — stdio transport keeps process alive
}

main().catch((err) => {
  console.error("Fatal error starting keppi-mcp:", err);
  process.exit(1);
});