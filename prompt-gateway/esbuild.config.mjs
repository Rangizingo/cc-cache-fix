import * as esbuild from "esbuild";

const shared = {
  bundle: true,
  platform: "node",
  target: "node20",
  format: "esm",
  sourcemap: true,
  // better-sqlite3 is a native addon — must stay external
  external: ["better-sqlite3"],
  banner: {
    // ESM needs createRequire for native modules
    js: `
import { createRequire } from 'module';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
const require = createRequire(import.meta.url);
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
`.trim(),
  },
};

// CLI: agent command
await esbuild.build({
  ...shared,
  entryPoints: ["src/bin/agent.ts"],
  outfile: "dist/agent.mjs",
});

// Daemon: prompt-gateway server
await esbuild.build({
  ...shared,
  entryPoints: ["src/index.ts"],
  outfile: "dist/prompt-gateway.mjs",
});

console.log("✓ Built dist/agent.mjs");
console.log("✓ Built dist/prompt-gateway.mjs");
