import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { compileContract } from "../compiler/index.js";
import { PolicyEngine } from "../policy/engine.js";
import { route, checkCapabilities } from "../router/index.js";
import { validate, formatResponse } from "../validator/index.js";
import { Storage } from "../storage/db.js";
import type { Surface, CompileRequest } from "../types.js";

// ---------------------------------------------------------------------------
// MCP Server — exposes the prompt gateway as MCP tools, resources, and prompts
// so every MCP-compatible client (Cursor, Claude, Codex, etc.) consumes the
// same capability layer.
// ---------------------------------------------------------------------------

export function createMcpServer(storage: Storage): McpServer {
  const server = new McpServer({
    name: "prompt-gateway",
    version: "0.1.0",
  });

  const policyEngine = new PolicyEngine();

  // -----------------------------------------------------------------------
  // Tools
  // -----------------------------------------------------------------------

  // compile — convert raw input to a task contract
  server.tool(
    "compile",
    "Compile raw human input into a structured task contract",
    {
      raw_input: z.string().describe("Raw user prompt / instruction"),
      surface: z
        .enum(["cursor", "cli", "desktop", "local-agent", "api"])
        .default("cli")
        .describe("Originating surface"),
      cwd: z.string().optional().describe("Current working directory"),
      git_ref: z.string().optional().describe("Current git ref"),
      session_id: z.string().optional().describe("Session identifier"),
    },
    async (args) => {
      const req: CompileRequest = {
        raw_input: args.raw_input,
        surface: args.surface as Surface,
        cwd: args.cwd,
        git_ref: args.git_ref,
        session_id: args.session_id,
      };

      const contract = compileContract(req);
      const run = storage.createRun(contract);
      storage.log(run.id, "info", "Contract compiled", { contract });

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(contract, null, 2),
          },
        ],
      };
    }
  );

  // evaluate — run policy checks on a contract
  server.tool(
    "evaluate",
    "Evaluate a compiled contract against policy rules",
    {
      request_id: z.string().describe("The request_id from a compiled contract"),
    },
    async (args) => {
      const run = storage.getRun(args.request_id);
      if (!run) {
        return {
          content: [{ type: "text" as const, text: `Run ${args.request_id} not found` }],
          isError: true,
        };
      }

      storage.updateRunStatus(run.id, "compiling");
      const evaluation = policyEngine.evaluate(run.contract);
      storage.log(run.id, "info", "Policy evaluated", { evaluation });

      if (!evaluation.allowed) {
        storage.updateRunStatus(run.id, "failed", null, evaluation.summary);
      } else if (evaluation.approval_required) {
        storage.updateRunStatus(run.id, "awaiting_approval");
      }

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(evaluation, null, 2),
          },
        ],
      };
    }
  );

  // route — determine the best execution surface
  server.tool(
    "route",
    "Route a task contract to the best execution surface",
    {
      request_id: z.string().describe("The request_id from a compiled contract"),
    },
    async (args) => {
      const run = storage.getRun(args.request_id);
      if (!run) {
        return {
          content: [{ type: "text" as const, text: `Run ${args.request_id} not found` }],
          isError: true,
        };
      }

      const target = route(run.contract);
      const caps = checkCapabilities(target.surface, run.contract.tools.allow);

      storage.log(run.id, "info", "Routed", { target, capabilities: caps });

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({ target, capabilities: caps }, null, 2),
          },
        ],
      };
    }
  );

  // approve — approve or deny a pending run
  server.tool(
    "approve",
    "Approve or deny a run that requires approval",
    {
      request_id: z.string().describe("The run to approve/deny"),
      approved: z.boolean().describe("Whether to approve"),
      reason: z.string().optional().describe("Reason for decision"),
    },
    async (args) => {
      const run = storage.getRun(args.request_id);
      if (!run) {
        return {
          content: [{ type: "text" as const, text: `Run ${args.request_id} not found` }],
          isError: true,
        };
      }

      storage.createApproval(run.id, args.approved, "mcp-client", args.reason);
      storage.log(run.id, "info", args.approved ? "Approved" : "Denied", {
        reason: args.reason,
      });

      return {
        content: [
          {
            type: "text" as const,
            text: args.approved
              ? `Run ${run.id} approved and ready for execution`
              : `Run ${run.id} denied: ${args.reason ?? "no reason given"}`,
          },
        ],
      };
    }
  );

  // validate — validate execution results against contract
  server.tool(
    "validate",
    "Validate execution results against the task contract",
    {
      request_id: z.string().describe("The run to validate"),
      result: z.string().describe("Execution result (as JSON string)"),
    },
    async (args) => {
      const run = storage.getRun(args.request_id);
      if (!run) {
        return {
          content: [{ type: "text" as const, text: `Run ${args.request_id} not found` }],
          isError: true,
        };
      }

      let parsedResult: unknown;
      try {
        parsedResult = JSON.parse(args.result);
      } catch {
        parsedResult = args.result;
      }

      const validation = validate(run.contract, parsedResult);
      const status = validation.passed ? "completed" : "failed";
      const response = formatResponse(run.contract, parsedResult, validation, status);

      storage.updateRunStatus(run.id, status, parsedResult);
      storage.log(run.id, "info", "Validated", { validation });

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(response, null, 2),
          },
        ],
      };
    }
  );

  // get-run — retrieve a run by ID
  server.tool(
    "get-run",
    "Get details of a specific run",
    {
      request_id: z.string().describe("The run ID"),
    },
    async (args) => {
      const run = storage.getRun(args.request_id);
      if (!run) {
        return {
          content: [{ type: "text" as const, text: `Run ${args.request_id} not found` }],
          isError: true,
        };
      }
      return {
        content: [{ type: "text" as const, text: JSON.stringify(run, null, 2) }],
      };
    }
  );

  // list-runs — list recent runs
  server.tool(
    "list-runs",
    "List recent runs, optionally filtered by session",
    {
      session_id: z.string().optional().describe("Filter by session"),
      limit: z.number().default(20).describe("Max results"),
    },
    async (args) => {
      const runs = storage.listRuns(args.session_id, args.limit);
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(
              runs.map((r) => ({
                id: r.id,
                session_id: r.session_id,
                status: r.status,
                task_type: r.contract.intent.task_type,
                objective: r.contract.objective.slice(0, 100),
                created_at: r.created_at,
              })),
              null,
              2
            ),
          },
        ],
      };
    }
  );

  // capabilities — list available tools and surfaces
  server.tool(
    "capabilities",
    "List gateway capabilities, surfaces, and tool registry",
    {},
    async () => {
      const capabilities = {
        surfaces: ["cursor", "cli", "desktop", "local-agent", "api"],
        task_types: [
          "code_edit", "code_review", "debug", "refactor", "test",
          "docs", "shell", "agent_architecture", "design_spec",
          "query", "deploy",
        ],
        execution_modes: ["think", "plan_then_act", "act"],
        risk_levels: ["low", "medium", "high"],
        output_types: ["text", "json", "patch", "command-list", "report"],
        tools: [
          "filesystem", "shell", "git", "editor", "docker",
          "package_manager", "database", "http",
        ],
      };
      return {
        content: [{ type: "text" as const, text: JSON.stringify(capabilities, null, 2) }],
      };
    }
  );

  // -----------------------------------------------------------------------
  // Resources
  // -----------------------------------------------------------------------

  server.resource(
    "contract-schema",
    "gateway://schema/task-contract",
    async () => ({
      contents: [
        {
          uri: "gateway://schema/task-contract",
          mimeType: "application/json",
          text: JSON.stringify(
            {
              description: "Canonical task contract schema",
              fields: {
                request_id: "uuid",
                session_id: "string",
                timestamp: "ISO 8601 datetime",
                origin: "{ surface, cwd?, git_ref?, env_profile? }",
                intent: "{ primary: string, task_type: TaskType }",
                objective: "string — raw user input",
                constraints: "string[] — extracted constraints",
                assumptions: "string[] — inferred assumptions",
                preferences: "{ verbosity, autonomy }",
                context: "{ workspace_roots, files, memory_keys, environment }",
                tools: "{ allow: string[], deny: string[] }",
                risk: "{ level, approval_required, reasons }",
                plan: "{ steps: string[] }",
                output: "{ type, format? }",
                execution: "{ mode, timeout_sec, target_surface? }",
                validation: "{ checks, success_criteria }",
              },
            },
            null,
            2
          ),
        },
      ],
    })
  );

  // -----------------------------------------------------------------------
  // Prompts
  // -----------------------------------------------------------------------

  server.prompt(
    "task-compiler",
    "System prompt for the task compiler agent",
    () => ({
      messages: [
        {
          role: "user" as const,
          content: {
            type: "text" as const,
            text: `You are the task compiler between a human operator and downstream AI agents.

Do not solve the task directly unless requested.
Convert raw user intent into a precise execution contract.

Always:
1. Infer the primary objective
2. Extract explicit and implicit constraints
3. Identify required context
4. Estimate task risk
5. Determine whether approval is required
6. Choose the best execution mode
7. Define success criteria
8. Produce structured output only

Preserve real user intent.
Do not hallucinate requirements.
Do not expand tool permissions beyond necessity.
Prefer minimal viable plans.

Output a JSON task contract with:
- objective
- task_type
- constraints
- context_needed
- recommended_tools
- disallowed_tools
- execution_mode
- risk_level
- approval_required
- plan_steps
- success_criteria
- output_format
- assumptions`,
          },
        },
      ],
    })
  );

  return server;
}
