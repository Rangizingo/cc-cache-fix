import { v4 as uuid } from "uuid";
import {
  TaskContract,
  type CompileRequest,
  type ExecutionMode,
  type OutputType,
  type RiskLevel,
  type TaskType,
} from "../types.js";
import { classify } from "./classifier.js";
import { extractConstraints } from "./constraint-extractor.js";
import { selectContext } from "./context-selector.js";

// ---------------------------------------------------------------------------
// Contract builder — the core compilation pipeline.
//
//   raw input -> classify -> extract constraints -> select context
//             -> assess risk -> choose execution mode -> emit contract
// ---------------------------------------------------------------------------

export function compileContract(req: CompileRequest): TaskContract {
  // 1. Classify intent
  const classification = classify(req.raw_input);

  // 2. Extract constraints
  const extraction = extractConstraints(req.raw_input);

  // 3. Select context
  const context = selectContext({
    task_type: classification.task_type,
    cwd: req.cwd,
    files_mentioned: extraction.files_mentioned,
    tools_mentioned: extraction.tools_mentioned,
  });

  // Merge adapter-provided files
  if (req.files?.length) {
    for (const f of req.files) {
      if (!context.files.includes(f)) context.files.push(f);
    }
  }

  // 4. Assess risk
  const risk = assessRisk(classification.task_type, extraction.constraints);

  // 5. Determine execution mode
  const mode = chooseExecutionMode(classification.task_type, risk.level);

  // 6. Choose output type
  const outputType = chooseOutputType(classification.task_type);

  // 7. Determine allowed / denied tools
  const tools = resolveTools(extraction.tools_mentioned, classification.task_type);

  // 8. Generate plan steps
  const steps = generatePlanSteps(classification.task_type, req.raw_input);

  // 9. Generate validation checks
  const checks = generateValidationChecks(classification.task_type);

  // 10. Build contract
  const now = new Date().toISOString();

  const contract: TaskContract = TaskContract.parse({
    request_id: uuid(),
    session_id: req.session_id ?? uuid(),
    timestamp: now,

    origin: {
      surface: req.surface,
      cwd: req.cwd,
      git_ref: req.git_ref,
      env_profile: req.env_profile,
    },

    intent: {
      primary: classification.primary_intent,
      task_type: classification.task_type,
    },

    objective: req.raw_input,
    constraints: extraction.constraints,
    assumptions: extraction.assumptions,

    preferences: {
      verbosity: req.preferences?.verbosity ?? "medium",
      autonomy: req.preferences?.autonomy ?? "confirm",
    },

    context: {
      workspace_roots: context.workspace_roots,
      files: context.files,
      memory_keys: context.memory_keys,
      environment: context.environment,
    },

    tools,
    risk,

    plan: { steps },

    output: {
      type: outputType,
    },

    execution: {
      mode,
      timeout_sec: risk.level === "high" ? 300 : 900,
      target_surface: req.surface,
    },

    validation: {
      checks,
      success_criteria: generateSuccessCriteria(classification.task_type),
    },
  });

  return contract;
}

// ---------------------------------------------------------------------------
// Risk assessment
// ---------------------------------------------------------------------------

function assessRisk(
  taskType: TaskType,
  constraints: string[]
): { level: RiskLevel; approval_required: boolean; reasons: string[] } {
  const reasons: string[] = [];

  const HIGH_RISK_TYPES = new Set(["deploy", "shell"]);
  const MEDIUM_RISK_TYPES = new Set(["code_edit", "refactor", "debug"]);

  let level: RiskLevel = "low";

  if (HIGH_RISK_TYPES.has(taskType)) {
    level = "high";
    reasons.push(`Task type '${taskType}' is inherently high-risk`);
  } else if (MEDIUM_RISK_TYPES.has(taskType)) {
    level = "medium";
    reasons.push(`Task type '${taskType}' modifies code`);
  }

  // Escalate if constraints mention destructive operations
  const destructiveSignals = /\b(delete|remove|drop|force|reset|overwrite|destroy)\b/i;
  for (const c of constraints) {
    if (destructiveSignals.test(c)) {
      level = "high";
      reasons.push(`Constraint mentions destructive operation: "${c}"`);
    }
  }

  return {
    level,
    approval_required: level === "high",
    reasons,
  };
}

// ---------------------------------------------------------------------------
// Execution mode
// ---------------------------------------------------------------------------

function chooseExecutionMode(
  taskType: TaskType,
  riskLevel: RiskLevel
): ExecutionMode {
  if (riskLevel === "high") return "plan_then_act";
  if (taskType === "query" || taskType === "docs") return "think";
  if (taskType === "design_spec" || taskType === "agent_architecture")
    return "plan_then_act";
  return "act";
}

// ---------------------------------------------------------------------------
// Output type
// ---------------------------------------------------------------------------

function chooseOutputType(taskType: TaskType): OutputType {
  const map: Partial<Record<TaskType, OutputType>> = {
    code_edit: "patch",
    refactor: "patch",
    debug: "patch",
    shell: "command-list",
    deploy: "command-list",
    query: "text",
    docs: "text",
    design_spec: "report",
    agent_architecture: "report",
    code_review: "report",
    test: "patch",
  };
  return map[taskType] ?? "text";
}

// ---------------------------------------------------------------------------
// Tool resolution
// ---------------------------------------------------------------------------

function resolveTools(
  mentioned: string[],
  taskType: TaskType
): { allow: string[]; deny: string[] } {
  const BASE_TOOLS = ["filesystem", "shell", "git", "editor"];
  const TASK_TOOLS: Partial<Record<TaskType, string[]>> = {
    code_edit: ["filesystem", "editor", "git"],
    debug: ["filesystem", "editor", "git", "shell"],
    shell: ["shell", "filesystem"],
    deploy: ["shell", "git", "docker"],
    test: ["filesystem", "shell", "git"],
    code_review: ["filesystem", "git"],
    docs: ["filesystem", "editor"],
  };

  const allowed = new Set<string>(TASK_TOOLS[taskType] ?? BASE_TOOLS);
  for (const t of mentioned) {
    allowed.add(t);
  }

  // Never allow dangerous tools by default
  const deny = ["database_admin", "cloud_admin", "secrets_manager"];

  return {
    allow: [...allowed],
    deny,
  };
}

// ---------------------------------------------------------------------------
// Plan generation
// ---------------------------------------------------------------------------

function generatePlanSteps(taskType: TaskType, _input: string): string[] {
  const BASE_STEPS: Partial<Record<TaskType, string[]>> = {
    code_edit: [
      "Identify files to modify",
      "Read current code",
      "Apply changes",
      "Verify changes compile/lint",
    ],
    debug: [
      "Reproduce the issue",
      "Identify root cause",
      "Implement fix",
      "Verify fix",
      "Check for regressions",
    ],
    refactor: [
      "Understand current structure",
      "Plan refactoring approach",
      "Apply changes incrementally",
      "Run tests",
      "Verify behavior preservation",
    ],
    test: [
      "Identify test targets",
      "Write test cases",
      "Run tests",
      "Verify coverage",
    ],
    shell: [
      "Validate command safety",
      "Execute command",
      "Verify output",
    ],
    deploy: [
      "Check deployment prerequisites",
      "Run pre-deploy checks",
      "Execute deployment",
      "Verify deployment",
      "Run smoke tests",
    ],
    code_review: [
      "Read changed files",
      "Check for issues",
      "Compile findings",
      "Produce report",
    ],
    docs: [
      "Identify documentation targets",
      "Write documentation",
      "Review for accuracy",
    ],
    design_spec: [
      "Analyze requirements",
      "Research existing patterns",
      "Draft specification",
      "Review for completeness",
    ],
    query: ["Research question", "Compile answer"],
  };

  return BASE_STEPS[taskType] ?? ["Analyze task", "Execute", "Validate"];
}

// ---------------------------------------------------------------------------
// Validation checks
// ---------------------------------------------------------------------------

function generateValidationChecks(taskType: TaskType): string[] {
  const checks: string[] = ["output_matches_contract"];

  if (["code_edit", "refactor", "debug", "test"].includes(taskType)) {
    checks.push("code_compiles", "tests_pass", "no_new_lint_errors");
  }
  if (taskType === "deploy") {
    checks.push("deploy_health_check", "rollback_plan_exists");
  }
  if (taskType === "shell") {
    checks.push("exit_code_zero", "no_destructive_side_effects");
  }

  return checks;
}

// ---------------------------------------------------------------------------
// Success criteria
// ---------------------------------------------------------------------------

function generateSuccessCriteria(taskType: TaskType): string[] {
  const criteria: Record<string, string[]> = {
    code_edit: ["Changes applied correctly", "Code compiles", "Tests pass"],
    debug: ["Bug is fixed", "Root cause identified", "No regressions"],
    refactor: ["Behavior preserved", "Code improved", "Tests pass"],
    test: ["Tests written", "Tests pass", "Coverage adequate"],
    shell: ["Command executed successfully", "Expected output produced"],
    deploy: ["Deployment successful", "Health checks pass"],
    code_review: ["All files reviewed", "Issues documented"],
    docs: ["Documentation complete", "Accurate"],
    design_spec: ["Spec complete", "Requirements covered"],
    query: ["Question answered", "Answer accurate"],
  };
  return criteria[taskType] ?? ["Task completed successfully"];
}
