import express, { type Request, type Response } from "express";
import { compileContract } from "../compiler/index.js";
import { PolicyEngine } from "../policy/engine.js";
import { route, checkCapabilities } from "../router/index.js";
import { validate, formatResponse } from "../validator/index.js";
import { Storage } from "../storage/db.js";
import { CompileRequest } from "../types.js";

// ---------------------------------------------------------------------------
// HTTP gateway server — REST endpoints for the prompt gateway daemon.
//
// Endpoints:
//   POST /compile    — compile raw input into a task contract
//   POST /execute    — (stub) execute a compiled contract
//   POST /approve    — approve or deny a pending run
//   GET  /runs/:id   — get run details
//   GET  /runs       — list recent runs
//   GET  /capabilities — list gateway capabilities
// ---------------------------------------------------------------------------

export function createHttpServer(storage: Storage, port = 4840) {
  const app = express();
  app.use(express.json());

  const policyEngine = new PolicyEngine();

  // -----------------------------------------------------------------------
  // POST /compile
  // -----------------------------------------------------------------------
  app.post("/compile", (req: Request, res: Response) => {
    try {
      const parsed = CompileRequest.safeParse(req.body);
      if (!parsed.success) {
        res.status(400).json({
          error: "Invalid compile request",
          details: parsed.error.issues,
        });
        return;
      }

      const contract = compileContract(parsed.data);
      const run = storage.createRun(contract);

      // Auto-evaluate policy
      const evaluation = policyEngine.evaluate(contract);
      storage.log(run.id, "info", "Compiled and evaluated", { evaluation });

      if (!evaluation.allowed) {
        storage.updateRunStatus(run.id, "failed", null, evaluation.summary);
      } else if (evaluation.approval_required) {
        storage.updateRunStatus(run.id, "awaiting_approval");
      }

      // Auto-route
      const target = route(contract);
      const caps = checkCapabilities(target.surface, contract.tools.allow);

      res.json({
        contract,
        policy: evaluation,
        routing: { target, capabilities: caps },
        run_id: run.id,
      });
    } catch (err) {
      storage.log(null, "error", "Compile failed", { error: String(err) });
      res.status(500).json({ error: String(err) });
    }
  });

  // -----------------------------------------------------------------------
  // POST /execute (stub — actual execution is surface-specific)
  // -----------------------------------------------------------------------
  app.post("/execute", (req: Request, res: Response) => {
    const { request_id } = req.body;
    if (!request_id) {
      res.status(400).json({ error: "request_id required" });
      return;
    }

    const run = storage.getRun(request_id);
    if (!run) {
      res.status(404).json({ error: `Run ${request_id} not found` });
      return;
    }

    if (run.status === "awaiting_approval") {
      res.status(403).json({
        error: "Run requires approval before execution",
        run_id: run.id,
        status: run.status,
      });
      return;
    }

    // In a real implementation, this dispatches to the target surface.
    // For the MVP, we mark as executing and return the contract for the
    // downstream agent to consume.
    storage.updateRunStatus(run.id, "executing");
    storage.log(run.id, "info", "Execution started");

    res.json({
      run_id: run.id,
      status: "executing",
      contract: run.contract,
      message: "Contract dispatched to execution surface. Poll GET /runs/:id for status.",
    });
  });

  // -----------------------------------------------------------------------
  // POST /approve
  // -----------------------------------------------------------------------
  app.post("/approve", (req: Request, res: Response) => {
    const { request_id, approved, reason } = req.body;
    if (!request_id || approved === undefined) {
      res.status(400).json({ error: "request_id and approved required" });
      return;
    }

    const run = storage.getRun(request_id);
    if (!run) {
      res.status(404).json({ error: `Run ${request_id} not found` });
      return;
    }

    storage.createApproval(run.id, approved, "http-client", reason);
    storage.log(run.id, "info", approved ? "Approved" : "Denied", { reason });

    res.json({
      run_id: run.id,
      approved,
      status: approved ? "executing" : "cancelled",
    });
  });

  // -----------------------------------------------------------------------
  // POST /validate
  // -----------------------------------------------------------------------
  app.post("/validate", (req: Request, res: Response) => {
    const { request_id, result } = req.body;
    if (!request_id) {
      res.status(400).json({ error: "request_id required" });
      return;
    }

    const run = storage.getRun(request_id);
    if (!run) {
      res.status(404).json({ error: `Run ${request_id} not found` });
      return;
    }

    const validation = validate(run.contract, result);
    const status = validation.passed ? "completed" : "failed";
    const response = formatResponse(run.contract, result, validation, status);

    storage.updateRunStatus(run.id, status, result);
    storage.log(run.id, "info", "Validated", { validation });

    res.json(response);
  });

  // -----------------------------------------------------------------------
  // GET /runs/:id
  // -----------------------------------------------------------------------
  app.get("/runs/:id", (req: Request, res: Response) => {
    const id = String(req.params.id);
    const run = storage.getRun(id);
    if (!run) {
      res.status(404).json({ error: `Run ${id} not found` });
      return;
    }
    res.json(run);
  });

  // -----------------------------------------------------------------------
  // GET /runs
  // -----------------------------------------------------------------------
  app.get("/runs", (req: Request, res: Response) => {
    const sessionId = typeof req.query.session_id === "string" ? req.query.session_id : undefined;
    const limit = parseInt(String(req.query.limit ?? "50")) || 50;
    const runs = storage.listRuns(sessionId, limit);
    res.json(runs);
  });

  // -----------------------------------------------------------------------
  // GET /capabilities
  // -----------------------------------------------------------------------
  app.get("/capabilities", (_req: Request, res: Response) => {
    res.json({
      version: "0.1.0",
      surfaces: ["cursor", "cli", "desktop", "local-agent", "api"],
      task_types: [
        "code_edit", "code_review", "debug", "refactor", "test",
        "docs", "shell", "agent_architecture", "design_spec",
        "query", "deploy",
      ],
      execution_modes: ["think", "plan_then_act", "act"],
      endpoints: {
        compile: "POST /compile",
        execute: "POST /execute",
        approve: "POST /approve",
        validate: "POST /validate",
        runs: "GET /runs",
        run: "GET /runs/:id",
        capabilities: "GET /capabilities",
      },
      mcp: {
        tools: [
          "compile", "evaluate", "route", "approve",
          "validate", "get-run", "list-runs", "capabilities",
        ],
        resources: ["contract-schema"],
        prompts: ["task-compiler"],
      },
    });
  });

  // -----------------------------------------------------------------------
  // Health check
  // -----------------------------------------------------------------------
  app.get("/health", (_req: Request, res: Response) => {
    res.json({ status: "ok", timestamp: new Date().toISOString() });
  });

  return { app, port };
}
