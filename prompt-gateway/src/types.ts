import { z } from "zod";

// ---------------------------------------------------------------------------
// Surface / origin
// ---------------------------------------------------------------------------

export const Surface = z.enum([
  "cursor",
  "cli",
  "desktop",
  "local-agent",
  "api",
]);
export type Surface = z.infer<typeof Surface>;

// ---------------------------------------------------------------------------
// Enums used across the contract
// ---------------------------------------------------------------------------

export const Verbosity = z.enum(["low", "medium", "high"]);
export type Verbosity = z.infer<typeof Verbosity>;

export const Autonomy = z.enum(["suggest", "confirm", "auto"]);
export type Autonomy = z.infer<typeof Autonomy>;

export const ExecutionMode = z.enum(["think", "plan_then_act", "act"]);
export type ExecutionMode = z.infer<typeof ExecutionMode>;

export const RiskLevel = z.enum(["low", "medium", "high"]);
export type RiskLevel = z.infer<typeof RiskLevel>;

export const OutputType = z.enum([
  "text",
  "json",
  "patch",
  "command-list",
  "report",
]);
export type OutputType = z.infer<typeof OutputType>;

export const TaskType = z.enum([
  "code_edit",
  "code_review",
  "debug",
  "refactor",
  "test",
  "docs",
  "shell",
  "agent_architecture",
  "design_spec",
  "query",
  "deploy",
  "unknown",
]);
export type TaskType = z.infer<typeof TaskType>;

export const RunStatus = z.enum([
  "pending",
  "compiling",
  "awaiting_approval",
  "executing",
  "validating",
  "completed",
  "failed",
  "cancelled",
]);
export type RunStatus = z.infer<typeof RunStatus>;

// ---------------------------------------------------------------------------
// Canonical Task Contract — the lingua franca
// ---------------------------------------------------------------------------

export const TaskContract = z.object({
  request_id: z.string().uuid(),
  session_id: z.string(),
  timestamp: z.string().datetime(),

  origin: z.object({
    surface: Surface,
    cwd: z.string().optional(),
    git_ref: z.string().optional(),
    env_profile: z.string().optional(),
  }),

  intent: z.object({
    primary: z.string(),
    task_type: TaskType,
  }),

  objective: z.string(),
  constraints: z.array(z.string()),
  assumptions: z.array(z.string()).default([]),

  preferences: z.object({
    verbosity: Verbosity.default("medium"),
    autonomy: Autonomy.default("confirm"),
  }),

  context: z.object({
    workspace_roots: z.array(z.string()).default([]),
    files: z.array(z.string()).default([]),
    memory_keys: z.array(z.string()).default([]),
    environment: z.record(z.string()).default({}),
  }),

  tools: z.object({
    allow: z.array(z.string()).default([]),
    deny: z.array(z.string()).default([]),
  }),

  risk: z.object({
    level: RiskLevel,
    approval_required: z.boolean(),
    reasons: z.array(z.string()).default([]),
  }),

  plan: z.object({
    steps: z.array(z.string()).default([]),
  }),

  output: z.object({
    type: OutputType,
    format: z.string().optional(),
  }),

  execution: z.object({
    mode: ExecutionMode,
    timeout_sec: z.number().default(900),
    target_surface: Surface.optional(),
  }),

  validation: z.object({
    checks: z.array(z.string()).default([]),
    success_criteria: z.array(z.string()).default([]),
  }),
});

export type TaskContract = z.infer<typeof TaskContract>;

// ---------------------------------------------------------------------------
// Compile request (raw input from any adapter)
// ---------------------------------------------------------------------------

export const CompileRequest = z.object({
  raw_input: z.string(),
  session_id: z.string().optional(),
  surface: Surface.default("cli"),
  cwd: z.string().optional(),
  git_ref: z.string().optional(),
  env_profile: z.string().optional(),
  files: z.array(z.string()).optional(),
  preferences: z
    .object({
      verbosity: Verbosity.optional(),
      autonomy: Autonomy.optional(),
    })
    .optional(),
});

export type CompileRequest = z.infer<typeof CompileRequest>;

// ---------------------------------------------------------------------------
// Run record (persisted)
// ---------------------------------------------------------------------------

export const RunRecord = z.object({
  id: z.string().uuid(),
  session_id: z.string(),
  status: RunStatus,
  contract: TaskContract,
  result: z.any().optional(),
  error: z.string().optional(),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
});

export type RunRecord = z.infer<typeof RunRecord>;

// ---------------------------------------------------------------------------
// Policy rule
// ---------------------------------------------------------------------------

export interface PolicyRule {
  id: string;
  description: string;
  evaluate(contract: TaskContract): PolicyDecision;
}

export interface PolicyDecision {
  allowed: boolean;
  approval_required: boolean;
  reason: string;
  modified_contract?: Partial<TaskContract>;
}

// ---------------------------------------------------------------------------
// Adapter interface
// ---------------------------------------------------------------------------

export interface InputAdapter {
  readonly surface: Surface;
  parse(raw: unknown): CompileRequest;
}

// ---------------------------------------------------------------------------
// Router target
// ---------------------------------------------------------------------------

export interface RouteTarget {
  surface: Surface;
  reason: string;
  fallback?: Surface;
}
