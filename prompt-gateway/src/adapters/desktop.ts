import type { InputAdapter, CompileRequest, Surface } from "../types.js";

// ---------------------------------------------------------------------------
// Desktop app adapter — thin transport layer for the desktop UI surface.
//
// The desktop app is a UI/approval surface over the same gateway. It should
// NOT have its own prompt logic — just transport, identity, and session.
// ---------------------------------------------------------------------------

export interface DesktopPayload {
  prompt: string;
  session_id?: string;
  workspace_root?: string;
  user_id?: string;
  preferences?: {
    verbosity?: "low" | "medium" | "high";
    autonomy?: "suggest" | "confirm" | "auto";
  };
}

export class DesktopAdapter implements InputAdapter {
  readonly surface: Surface = "desktop";

  parse(raw: unknown): CompileRequest {
    const payload = raw as DesktopPayload;

    return {
      raw_input: payload.prompt ?? String(raw),
      surface: "desktop",
      cwd: payload.workspace_root,
      session_id: payload.session_id,
      preferences: payload.preferences,
    };
  }
}
