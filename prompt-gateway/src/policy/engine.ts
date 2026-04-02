import type { PolicyRule, PolicyDecision, TaskContract } from "../types.js";

// ---------------------------------------------------------------------------
// Policy engine — evaluates a compiled contract against a set of rules
// before allowing execution.
//
// Rules answer:
//   - Can this agent do it?
//   - Does this surface have permission?
//   - Is approval required?
//   - Should this run locally or remotely?
//   - Should it dry-run first?
// ---------------------------------------------------------------------------

export class PolicyEngine {
  private rules: PolicyRule[] = [];

  constructor() {
    this.registerDefaults();
  }

  addRule(rule: PolicyRule): void {
    this.rules.push(rule);
  }

  evaluate(contract: TaskContract): PolicyEvaluation {
    const decisions: PolicyDecision[] = [];
    let blocked = false;
    let approvalRequired = contract.risk.approval_required;

    for (const rule of this.rules) {
      const decision = rule.evaluate(contract);
      decisions.push(decision);

      if (!decision.allowed) {
        blocked = true;
      }
      if (decision.approval_required) {
        approvalRequired = true;
      }
    }

    return {
      allowed: !blocked,
      approval_required: approvalRequired,
      decisions,
      summary: blocked
        ? `Blocked by: ${decisions
            .filter((d) => !d.allowed)
            .map((d) => d.reason)
            .join("; ")}`
        : approvalRequired
          ? "Allowed but requires approval"
          : "Allowed",
    };
  }

  private registerDefaults(): void {
    // Rule: high-risk tasks require approval
    this.addRule({
      id: "high-risk-approval",
      description: "High-risk tasks always require approval",
      evaluate(contract: TaskContract): PolicyDecision {
        if (contract.risk.level === "high") {
          return {
            allowed: true,
            approval_required: true,
            reason: "High-risk task requires approval before execution",
          };
        }
        return { allowed: true, approval_required: false, reason: "OK" };
      },
    });

    // Rule: deploy from non-CLI surfaces requires approval
    this.addRule({
      id: "deploy-surface-check",
      description: "Deploy tasks must originate from CLI or API",
      evaluate(contract: TaskContract): PolicyDecision {
        if (
          contract.intent.task_type === "deploy" &&
          !["cli", "api"].includes(contract.origin.surface)
        ) {
          return {
            allowed: true,
            approval_required: true,
            reason: `Deploy from '${contract.origin.surface}' requires explicit approval`,
          };
        }
        return { allowed: true, approval_required: false, reason: "OK" };
      },
    });

    // Rule: deny dangerous tool combinations
    this.addRule({
      id: "tool-scope-guard",
      description: "Block requests that ask for denied tools",
      evaluate(contract: TaskContract): PolicyDecision {
        const denied = contract.tools.deny;
        const requested = contract.tools.allow;
        const violations = requested.filter((t) => denied.includes(t));
        if (violations.length > 0) {
          return {
            allowed: false,
            approval_required: false,
            reason: `Denied tools requested: ${violations.join(", ")}`,
          };
        }
        return { allowed: true, approval_required: false, reason: "OK" };
      },
    });

    // Rule: timeout sanity check
    this.addRule({
      id: "timeout-guard",
      description: "Tasks must have reasonable timeouts",
      evaluate(contract: TaskContract): PolicyDecision {
        if (contract.execution.timeout_sec > 3600) {
          return {
            allowed: false,
            approval_required: false,
            reason: "Timeout exceeds 1 hour maximum",
          };
        }
        return { allowed: true, approval_required: false, reason: "OK" };
      },
    });

    // Rule: unknown task types get elevated scrutiny
    this.addRule({
      id: "unknown-task-guard",
      description: "Unknown task types require approval",
      evaluate(contract: TaskContract): PolicyDecision {
        if (contract.intent.task_type === "unknown") {
          return {
            allowed: true,
            approval_required: true,
            reason: "Unclassified task — requesting human review",
          };
        }
        return { allowed: true, approval_required: false, reason: "OK" };
      },
    });
  }
}

export interface PolicyEvaluation {
  allowed: boolean;
  approval_required: boolean;
  decisions: PolicyDecision[];
  summary: string;
}
