import * as child_process from "node:child_process";
import type { InputAdapter, CompileRequest, Surface } from "../types.js";

// ---------------------------------------------------------------------------
// CLI adapter — captures cwd, git state, env profile, and wraps raw input
// into a CompileRequest.
// ---------------------------------------------------------------------------

export class CliAdapter implements InputAdapter {
  readonly surface: Surface = "cli";

  parse(raw: unknown): CompileRequest {
    const input = typeof raw === "string" ? raw : String(raw);

    return {
      raw_input: input,
      surface: "cli",
      cwd: process.cwd(),
      git_ref: getGitRef(),
      env_profile: process.env.NODE_ENV ?? "development",
    };
  }
}

function getGitRef(): string | undefined {
  try {
    return child_process
      .execSync("git rev-parse --short HEAD 2>/dev/null", {
        encoding: "utf-8",
        timeout: 3000,
      })
      .trim() || undefined;
  } catch {
    return undefined;
  }
}
