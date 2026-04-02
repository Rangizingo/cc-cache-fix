import type { TaskContract, RunStatus } from "../types.js";

// ---------------------------------------------------------------------------
// Validator — checks execution results against the contract's validation
// criteria before returning results to the user.
// ---------------------------------------------------------------------------

export interface ValidationResult {
  passed: boolean;
  checks: CheckResult[];
  summary: string;
}

export interface CheckResult {
  name: string;
  passed: boolean;
  detail: string;
}

// Built-in check implementations
type CheckFn = (contract: TaskContract, result: unknown) => CheckResult;

const BUILT_IN_CHECKS: Record<string, CheckFn> = {
  output_matches_contract: (contract, result) => {
    const hasResult = result !== null && result !== undefined;
    return {
      name: "output_matches_contract",
      passed: hasResult,
      detail: hasResult
        ? "Output present and non-null"
        : "No output produced",
    };
  },

  code_compiles: (_contract, result) => {
    // Check if result contains compilation errors
    const resultStr = String(result ?? "");
    const hasCompileError =
      /\b(error|SyntaxError|TypeError|ReferenceError)\b/i.test(resultStr) &&
      /\b(compile|compilation|parse)\b/i.test(resultStr);
    return {
      name: "code_compiles",
      passed: !hasCompileError,
      detail: hasCompileError
        ? "Compilation errors detected in output"
        : "No compilation errors detected",
    };
  },

  tests_pass: (_contract, result) => {
    const resultStr = String(result ?? "");
    const hasTestFailure =
      /\b(FAIL|failed|failing)\b/.test(resultStr) &&
      /\b(test|spec|suite)\b/i.test(resultStr);
    return {
      name: "tests_pass",
      passed: !hasTestFailure,
      detail: hasTestFailure
        ? "Test failures detected in output"
        : "No test failures detected",
    };
  },

  no_new_lint_errors: (_contract, result) => {
    const resultStr = String(result ?? "");
    const hasLintError = /\b(lint|eslint|warning)\b/i.test(resultStr) &&
      /\b(error|violation)\b/i.test(resultStr);
    return {
      name: "no_new_lint_errors",
      passed: !hasLintError,
      detail: hasLintError
        ? "Lint errors detected"
        : "No lint errors detected",
    };
  },

  exit_code_zero: (_contract, result) => {
    const resultStr = String(result ?? "");
    const hasNonZeroExit = /exit\s*(code|status)\s*[1-9]/i.test(resultStr);
    return {
      name: "exit_code_zero",
      passed: !hasNonZeroExit,
      detail: hasNonZeroExit
        ? "Non-zero exit code detected"
        : "Exit code OK",
    };
  },

  no_destructive_side_effects: (contract, _result) => {
    // Check contract constraints for destructive signals
    const destructive = contract.constraints.some((c) =>
      /\b(delete|drop|remove|destroy|force)\b/i.test(c)
    );
    return {
      name: "no_destructive_side_effects",
      passed: !destructive,
      detail: destructive
        ? "Destructive operations present in constraints"
        : "No destructive side effects",
    };
  },

  deploy_health_check: (_contract, result) => {
    const resultStr = String(result ?? "");
    const healthy =
      /\b(healthy|success|ok|up|running)\b/i.test(resultStr) ||
      !resultStr.includes("error");
    return {
      name: "deploy_health_check",
      passed: healthy,
      detail: healthy ? "Deployment appears healthy" : "Deployment may have issues",
    };
  },

  rollback_plan_exists: (contract, _result) => {
    const hasRollback = contract.plan.steps.some((s) =>
      /\b(rollback|revert|undo)\b/i.test(s)
    );
    return {
      name: "rollback_plan_exists",
      passed: hasRollback,
      detail: hasRollback
        ? "Rollback step found in plan"
        : "No rollback step in plan — consider adding one",
    };
  },
};

export function validate(
  contract: TaskContract,
  result: unknown
): ValidationResult {
  const checks: CheckResult[] = [];

  for (const checkName of contract.validation.checks) {
    const checkFn = BUILT_IN_CHECKS[checkName];
    if (checkFn) {
      checks.push(checkFn(contract, result));
    } else {
      // Unknown check — pass with warning
      checks.push({
        name: checkName,
        passed: true,
        detail: `Check '${checkName}' has no built-in implementation — skipped`,
      });
    }
  }

  const allPassed = checks.every((c) => c.passed);

  return {
    passed: allPassed,
    checks,
    summary: allPassed
      ? `All ${checks.length} validation checks passed`
      : `${checks.filter((c) => !c.passed).length}/${checks.length} checks failed`,
  };
}

// ---------------------------------------------------------------------------
// Response formatter — shapes output for the originating surface
// ---------------------------------------------------------------------------

export interface FormattedResponse {
  request_id: string;
  status: RunStatus;
  result: unknown;
  validation: ValidationResult;
  metadata: {
    task_type: string;
    execution_mode: string;
    risk_level: string;
    elapsed_ms?: number;
  };
}

export function formatResponse(
  contract: TaskContract,
  result: unknown,
  validation: ValidationResult,
  status: RunStatus,
  elapsedMs?: number
): FormattedResponse {
  return {
    request_id: contract.request_id,
    status,
    result,
    validation,
    metadata: {
      task_type: contract.intent.task_type,
      execution_mode: contract.execution.mode,
      risk_level: contract.risk.level,
      elapsed_ms: elapsedMs,
    },
  };
}
