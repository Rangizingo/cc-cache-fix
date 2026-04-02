import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createMcpServer } from "./mcp/server.js";
import { createHttpServer } from "./server/http.js";
import { Storage } from "./storage/db.js";

// ---------------------------------------------------------------------------
// prompt-gateway daemon entry point
//
// Runs two servers:
//   1. MCP server on stdio (for Cursor, Claude, Codex, etc.)
//   2. HTTP server on port 4840 (for CLI, desktop, API clients)
//
// Usage:
//   npx prompt-gateway          # starts both servers
//   npx prompt-gateway --http   # HTTP only
//   npx prompt-gateway --mcp    # MCP stdio only
// ---------------------------------------------------------------------------

async function main() {
  const args = process.argv.slice(2);
  const httpOnly = args.includes("--http");
  const mcpOnly = args.includes("--mcp");
  const port = parseInt(args.find((a) => a.startsWith("--port="))?.split("=")[1] ?? "4840");

  const storage = new Storage();

  if (!httpOnly) {
    // Start MCP server on stdio
    const mcpServer = createMcpServer(storage);
    const transport = new StdioServerTransport();
    await mcpServer.connect(transport);

    if (mcpOnly) {
      console.error("[prompt-gateway] MCP server running on stdio");
      return;
    }
  }

  if (!mcpOnly) {
    // Start HTTP server
    const { app } = createHttpServer(storage, port);
    app.listen(port, () => {
      console.error(`[prompt-gateway] HTTP server listening on http://localhost:${port}`);
      console.error(`[prompt-gateway] Endpoints:`);
      console.error(`  POST /compile      — compile raw input to task contract`);
      console.error(`  POST /execute      — execute a compiled contract`);
      console.error(`  POST /approve      — approve/deny pending runs`);
      console.error(`  POST /validate     — validate execution results`);
      console.error(`  GET  /runs/:id     — get run details`);
      console.error(`  GET  /runs         — list recent runs`);
      console.error(`  GET  /capabilities — list gateway capabilities`);
      console.error(`  GET  /health       — health check`);
    });
  }
}

main().catch((err) => {
  console.error("[prompt-gateway] Fatal:", err);
  process.exit(1);
});
