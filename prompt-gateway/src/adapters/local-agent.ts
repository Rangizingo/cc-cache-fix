import type { InputAdapter, CompileRequest, Surface } from "../types.js";

// ---------------------------------------------------------------------------
// Local agent adapter — for local agents that consume the same contract
// and MCP tool layer. Agents should NOT invent their own operating
// instructions — they consume the canonical contract.
// ---------------------------------------------------------------------------

export interface LocalAgentPayload {
  prompt: string;
  agent_id: string;
  agent_type?: string;
  session_id?: string;
  cwd?: string;
  git_ref?: string;
  capabilities?: string[];
  preferences?: {
    verbosity?: "low" | "medium" | "high";
    autonomy?: "suggest" | "confirm" | "auto";
  };
}

export class LocalAgentAdapter implements InputAdapter {
  readonly surface: Surface = "local-agent";

  parse(raw: unknown): CompileRequest {
    const payload = raw as LocalAgentPayload;

    return {
      raw_input: payload.prompt ?? String(raw),
      surface: "local-agent",
      cwd: payload.cwd,
      git_ref: payload.git_ref,
      session_id: payload.session_id,
      preferences: payload.preferences,
    };
  }
}
