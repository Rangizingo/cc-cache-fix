import Database from "better-sqlite3";
import type { TaskContract, RunRecord, RunStatus } from "../types.js";
import { v4 as uuid } from "uuid";
import * as path from "node:path";
import * as fs from "node:fs";

// ---------------------------------------------------------------------------
// Storage layer — SQLite for runs, approvals, memory, and policies.
// ---------------------------------------------------------------------------

export class Storage {
  private db: Database.Database;

  constructor(dbPath?: string) {
    const resolvedPath = dbPath ?? path.join(process.cwd(), ".prompt-gateway", "gateway.db");
    const dir = path.dirname(resolvedPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    this.db = new Database(resolvedPath);
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("foreign_keys = ON");
    this.migrate();
  }

  // -------------------------------------------------------------------------
  // Migrations
  // -------------------------------------------------------------------------

  private migrate(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        contract TEXT NOT NULL,
        result TEXT,
        error TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
      );

      CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id);
      CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);

      CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        approved INTEGER NOT NULL DEFAULT 0,
        approved_by TEXT,
        reason TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );

      CREATE INDEX IF NOT EXISTS idx_approvals_run ON approvals(run_id);

      CREATE TABLE IF NOT EXISTS memory (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'general',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
      );

      CREATE INDEX IF NOT EXISTS idx_memory_category ON memory(category);

      CREATE TABLE IF NOT EXISTS policies (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        rule TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );

      CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT REFERENCES runs(id),
        level TEXT NOT NULL DEFAULT 'info',
        message TEXT NOT NULL,
        data TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );

      CREATE INDEX IF NOT EXISTS idx_logs_run ON logs(run_id);
    `);
  }

  // -------------------------------------------------------------------------
  // Runs
  // -------------------------------------------------------------------------

  createRun(contract: TaskContract): RunRecord {
    const now = new Date().toISOString();
    const record: RunRecord = {
      id: contract.request_id,
      session_id: contract.session_id,
      status: "pending",
      contract,
      created_at: now,
      updated_at: now,
    };

    this.db
      .prepare(
        `INSERT INTO runs (id, session_id, status, contract, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?)`
      )
      .run(
        record.id,
        record.session_id,
        record.status,
        JSON.stringify(record.contract),
        record.created_at,
        record.updated_at
      );

    return record;
  }

  getRun(id: string): RunRecord | undefined {
    const row = this.db
      .prepare("SELECT * FROM runs WHERE id = ?")
      .get(id) as RawRunRow | undefined;

    if (!row) return undefined;
    return this.parseRunRow(row);
  }

  updateRunStatus(id: string, status: RunStatus, result?: unknown, error?: string): void {
    const now = new Date().toISOString();
    this.db
      .prepare(
        `UPDATE runs SET status = ?, result = ?, error = ?, updated_at = ? WHERE id = ?`
      )
      .run(status, result ? JSON.stringify(result) : null, error ?? null, now, id);
  }

  listRuns(sessionId?: string, limit = 50): RunRecord[] {
    let rows: RawRunRow[];
    if (sessionId) {
      rows = this.db
        .prepare("SELECT * FROM runs WHERE session_id = ? ORDER BY created_at DESC LIMIT ?")
        .all(sessionId, limit) as RawRunRow[];
    } else {
      rows = this.db
        .prepare("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?")
        .all(limit) as RawRunRow[];
    }
    return rows.map((r) => this.parseRunRow(r));
  }

  // -------------------------------------------------------------------------
  // Approvals
  // -------------------------------------------------------------------------

  createApproval(runId: string, approved: boolean, approvedBy?: string, reason?: string): void {
    this.db
      .prepare(
        `INSERT INTO approvals (id, run_id, approved, approved_by, reason)
         VALUES (?, ?, ?, ?, ?)`
      )
      .run(uuid(), runId, approved ? 1 : 0, approvedBy ?? null, reason ?? null);

    this.updateRunStatus(runId, approved ? "executing" : "cancelled");
  }

  // -------------------------------------------------------------------------
  // Memory
  // -------------------------------------------------------------------------

  setMemory(key: string, value: string, category = "general"): void {
    this.db
      .prepare(
        `INSERT OR REPLACE INTO memory (key, value, category, updated_at)
         VALUES (?, ?, ?, datetime('now'))`
      )
      .run(key, value, category);
  }

  getMemory(key: string): string | undefined {
    const row = this.db
      .prepare("SELECT value FROM memory WHERE key = ?")
      .get(key) as { value: string } | undefined;
    return row?.value;
  }

  getMemoryByCategory(category: string): Array<{ key: string; value: string }> {
    return this.db
      .prepare("SELECT key, value FROM memory WHERE category = ?")
      .all(category) as Array<{ key: string; value: string }>;
  }

  // -------------------------------------------------------------------------
  // Logs
  // -------------------------------------------------------------------------

  log(runId: string | null, level: string, message: string, data?: unknown): void {
    this.db
      .prepare(
        `INSERT INTO logs (run_id, level, message, data) VALUES (?, ?, ?, ?)`
      )
      .run(runId, level, message, data ? JSON.stringify(data) : null);
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  private parseRunRow(row: RawRunRow): RunRecord {
    return {
      id: row.id,
      session_id: row.session_id,
      status: row.status as RunStatus,
      contract: JSON.parse(row.contract) as TaskContract,
      result: row.result ? JSON.parse(row.result) : undefined,
      error: row.error ?? undefined,
      created_at: row.created_at,
      updated_at: row.updated_at,
    };
  }

  close(): void {
    this.db.close();
  }
}

interface RawRunRow {
  id: string;
  session_id: string;
  status: string;
  contract: string;
  result: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}
