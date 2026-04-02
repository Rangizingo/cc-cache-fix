import type { InputAdapter, CompileRequest, Surface } from "../types.js";

// ---------------------------------------------------------------------------
// Cursor / IDE adapter — parses requests from Cursor's MCP client,
// extracting workspace info and IDE-specific metadata.
//
// In Cursor, this adapter is consumed indirectly: Cursor connects to the
// MCP server, and the MCP tools handle the compilation. This adapter is
// for when the gateway receives HTTP requests from a Cursor extension.
// ---------------------------------------------------------------------------

export interface CursorPayload {
  prompt: string;
  workspace_root?: string;
  active_file?: string;
  selected_text?: string;
  git_ref?: string;
  session_id?: string;
}

export class CursorAdapter implements InputAdapter {
  readonly surface: Surface = "cursor";

  parse(raw: unknown): CompileRequest {
    const payload = raw as CursorPayload;

    // Build raw input from available context
    let input = payload.prompt ?? String(raw);
    if (payload.selected_text) {
      input += `\n\n[Selected code]:\n${payload.selected_text}`;
    }

    return {
      raw_input: input,
      surface: "cursor",
      cwd: payload.workspace_root,
      git_ref: payload.git_ref,
      session_id: payload.session_id,
      files: payload.active_file ? [payload.active_file] : undefined,
    };
  }
}
