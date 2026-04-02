#!/usr/bin/env node

import { CliAdapter } from "../adapters/cli.js";
import { compileContract } from "../compiler/index.js";
import { PolicyEngine } from "../policy/engine.js";
import { route, checkCapabilities } from "../router/index.js";

// ---------------------------------------------------------------------------
// CLI entry point — the "agent" command
//
// Usage:
//   agent "fix the auth race and keep changes minimal"
//   agent --json "add a health check endpoint"
//   echo "refactor the router" | agent
//
// Captures cwd, git state, env, compiles to contract, evaluates policy,
// routes, and outputs the result.
// ---------------------------------------------------------------------------

async function main() {
  const args = process.argv.slice(2);
  const jsonOutput = args.includes("--json");
  const filteredArgs = args.filter((a) => !a.startsWith("--"));

  // Get input from args or stdin
  let input: string;
  if (filteredArgs.length > 0) {
    input = filteredArgs.join(" ");
  } else if (!process.stdin.isTTY) {
    input = await readStdin();
  } else {
    console.error("Usage: agent <prompt>");
    console.error('  agent "fix the auth race and keep changes minimal"');
    console.error('  agent --json "add a health check endpoint"');
    console.error('  echo "refactor the router" | agent');
    process.exit(1);
  }

  // Adapt
  const adapter = new CliAdapter();
  const req = adapter.parse(input);

  // Compile
  const contract = compileContract(req);

  // Evaluate policy
  const policyEngine = new PolicyEngine();
  const evaluation = policyEngine.evaluate(contract);

  // Route
  const target = route(contract);
  const caps = checkCapabilities(target.surface, contract.tools.allow);

  if (jsonOutput) {
    // Full JSON output
    console.log(
      JSON.stringify(
        { contract, policy: evaluation, routing: { target, capabilities: caps } },
        null,
        2
      )
    );
  } else {
    // Human-readable output
    console.log("━".repeat(60));
    console.log("  PROMPT GATEWAY — Task Contract");
    console.log("━".repeat(60));
    console.log();
    console.log(`  Request:     ${contract.request_id}`);
    console.log(`  Task type:   ${contract.intent.task_type}`);
    console.log(`  Intent:      ${contract.intent.primary}`);
    console.log(`  Objective:   ${contract.objective}`);
    console.log(`  Risk:        ${contract.risk.level}${contract.risk.approval_required ? " (approval required)" : ""}`);
    console.log(`  Exec mode:   ${contract.execution.mode}`);
    console.log(`  Output:      ${contract.output.type}`);
    console.log(`  Timeout:     ${contract.execution.timeout_sec}s`);
    console.log();

    if (contract.constraints.length > 0) {
      console.log("  Constraints:");
      for (const c of contract.constraints) {
        console.log(`    • ${c}`);
      }
      console.log();
    }

    if (contract.assumptions.length > 0) {
      console.log("  Assumptions:");
      for (const a of contract.assumptions) {
        console.log(`    • ${a}`);
      }
      console.log();
    }

    console.log("  Plan:");
    for (let i = 0; i < contract.plan.steps.length; i++) {
      console.log(`    ${i + 1}. ${contract.plan.steps[i]}`);
    }
    console.log();

    console.log(`  Tools allowed: ${contract.tools.allow.join(", ")}`);
    console.log(`  Tools denied:  ${contract.tools.deny.join(", ")}`);
    console.log();

    console.log("  Routing:");
    console.log(`    Target:    ${target.surface}`);
    console.log(`    Reason:    ${target.reason}`);
    if (target.fallback) {
      console.log(`    Fallback:  ${target.fallback}`);
    }
    if (caps.missing.length > 0) {
      console.log(`    ⚠ Missing:  ${caps.missing.join(", ")}`);
    }
    console.log();

    console.log("  Policy:");
    console.log(`    Allowed:   ${evaluation.allowed ? "yes" : "NO"}`);
    console.log(`    Approval:  ${evaluation.approval_required ? "REQUIRED" : "not required"}`);
    console.log(`    Summary:   ${evaluation.summary}`);
    console.log();

    console.log("  Validation checks:");
    for (const check of contract.validation.checks) {
      console.log(`    • ${check}`);
    }
    console.log();

    console.log("  Success criteria:");
    for (const sc of contract.validation.success_criteria) {
      console.log(`    ✓ ${sc}`);
    }
    console.log();
    console.log("━".repeat(60));
  }
}

function readStdin(): Promise<string> {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf-8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data.trim()));
  });
}

main().catch((err) => {
  console.error("Error:", err);
  process.exit(1);
});
