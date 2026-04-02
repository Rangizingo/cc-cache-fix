import type { TaskType } from "../types.js";

// ---------------------------------------------------------------------------
// Context selector — assembles only the relevant context for a task.
//
// Anti-stuffing: we do NOT dump the whole workspace. We pick context sources
// based on task type, mentioned files, and available tools.
// ---------------------------------------------------------------------------

export interface ContextQuery {
  task_type: TaskType;
  cwd?: string;
  files_mentioned: string[];
  tools_mentioned: string[];
}

export interface SelectedContext {
  workspace_roots: string[];
  files: string[];
  memory_keys: string[];
  environment: Record<string, string>;
}

// Task types that need repo context
const REPO_AWARE: Set<TaskType> = new Set([
  "code_edit",
  "code_review",
  "debug",
  "refactor",
  "test",
  "deploy",
]);

// Task types that need environment context
const ENV_AWARE: Set<TaskType> = new Set([
  "shell",
  "deploy",
  "debug",
]);

// Memory keys by task type
const MEMORY_KEYS: Partial<Record<TaskType, string[]>> = {
  code_edit: ["recent_edits", "project_conventions"],
  debug: ["recent_errors", "recent_edits", "known_issues"],
  refactor: ["project_conventions", "architecture_notes"],
  test: ["test_patterns", "coverage_gaps"],
  deploy: ["deploy_history", "deploy_config"],
  code_review: ["project_conventions", "review_checklist"],
};

export function selectContext(query: ContextQuery): SelectedContext {
  const result: SelectedContext = {
    workspace_roots: [],
    files: [],
    memory_keys: [],
    environment: {},
  };

  // Workspace roots
  if (query.cwd) {
    result.workspace_roots.push(query.cwd);
  }

  // Files — start with explicitly mentioned ones
  result.files.push(...query.files_mentioned);

  // If repo-aware task but no files mentioned, note the workspace root
  if (REPO_AWARE.has(query.task_type) && result.files.length === 0 && query.cwd) {
    // Don't add the whole repo, just mark the root for later scanning
    result.workspace_roots.push(query.cwd);
  }

  // Memory keys
  const keys = MEMORY_KEYS[query.task_type];
  if (keys) {
    result.memory_keys.push(...keys);
  }

  // Environment context
  if (ENV_AWARE.has(query.task_type)) {
    result.environment["NODE_ENV"] = process.env.NODE_ENV ?? "development";
    result.environment["SHELL"] = process.env.SHELL ?? "unknown";
    // Do NOT leak sensitive env vars
  }

  return result;
}
