import type { TaskContract, Surface, RouteTarget } from "../types.js";

// ---------------------------------------------------------------------------
// Runtime router — decides which execution surface handles a compiled task.
//
// Route by task type:
//   - Cursor for repo-aware coding
//   - CLI/local agent for shell-heavy work
//   - Desktop app for human-in-the-loop workflows
//   - Specialized local agent for domain tasks
// ---------------------------------------------------------------------------

interface RoutingRule {
  match: (contract: TaskContract) => boolean;
  target: Surface;
  reason: string;
  fallback: Surface;
}

const ROUTING_TABLE: RoutingRule[] = [
  // Shell-heavy work -> CLI
  {
    match: (c) => c.intent.task_type === "shell",
    target: "cli",
    reason: "Shell tasks route to CLI for direct execution",
    fallback: "local-agent",
  },

  // Deploy -> CLI (with approval gate)
  {
    match: (c) => c.intent.task_type === "deploy",
    target: "cli",
    reason: "Deploy tasks route to CLI with approval gate",
    fallback: "api",
  },

  // Repo-aware coding -> Cursor
  {
    match: (c) =>
      ["code_edit", "refactor", "debug", "code_review"].includes(
        c.intent.task_type
      ),
    target: "cursor",
    reason: "Code tasks route to Cursor for repo-aware editing",
    fallback: "cli",
  },

  // Testing -> CLI (runs shell commands)
  {
    match: (c) => c.intent.task_type === "test",
    target: "cli",
    reason: "Test tasks route to CLI for test runner execution",
    fallback: "cursor",
  },

  // Documentation -> Cursor (file editing)
  {
    match: (c) => c.intent.task_type === "docs",
    target: "cursor",
    reason: "Documentation routes to Cursor for file editing",
    fallback: "cli",
  },

  // Design / architecture -> desktop (needs human review)
  {
    match: (c) =>
      ["design_spec", "agent_architecture"].includes(c.intent.task_type),
    target: "desktop",
    reason: "Design specs route to desktop for human-in-the-loop review",
    fallback: "cursor",
  },

  // Queries -> local agent (lightweight)
  {
    match: (c) => c.intent.task_type === "query",
    target: "local-agent",
    reason: "Queries route to local agent for fast resolution",
    fallback: "cli",
  },
];

export function route(contract: TaskContract): RouteTarget {
  // If the contract specifies a target surface, honor it
  if (contract.execution.target_surface) {
    return {
      surface: contract.execution.target_surface,
      reason: "Explicitly specified by contract",
    };
  }

  // Match routing rules
  for (const rule of ROUTING_TABLE) {
    if (rule.match(contract)) {
      return {
        surface: rule.target,
        reason: rule.reason,
        fallback: rule.fallback,
      };
    }
  }

  // Default fallback
  return {
    surface: "cli",
    reason: "No matching routing rule — defaulting to CLI",
    fallback: "local-agent",
  };
}

// ---------------------------------------------------------------------------
// Capability check — verifies a surface can handle the required tools
// ---------------------------------------------------------------------------

const SURFACE_CAPABILITIES: Record<Surface, Set<string>> = {
  cursor: new Set(["filesystem", "editor", "git", "shell", "package_manager"]),
  cli: new Set(["filesystem", "shell", "git", "docker", "package_manager", "database", "http"]),
  desktop: new Set(["filesystem", "editor"]),
  "local-agent": new Set(["filesystem", "shell", "git", "http", "editor"]),
  api: new Set(["http", "shell", "filesystem", "git"]),
};

export function checkCapabilities(
  surface: Surface,
  requiredTools: string[]
): { capable: boolean; missing: string[] } {
  const caps = SURFACE_CAPABILITIES[surface];
  const missing = requiredTools.filter((t) => !caps.has(t));
  return {
    capable: missing.length === 0,
    missing,
  };
}
