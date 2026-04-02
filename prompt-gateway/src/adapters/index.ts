export { CliAdapter } from "./cli.js";
export { CursorAdapter } from "./cursor.js";
export { DesktopAdapter } from "./desktop.js";
export { LocalAgentAdapter } from "./local-agent.js";

import type { InputAdapter, Surface } from "../types.js";
import { CliAdapter } from "./cli.js";
import { CursorAdapter } from "./cursor.js";
import { DesktopAdapter } from "./desktop.js";
import { LocalAgentAdapter } from "./local-agent.js";

const ADAPTERS: Record<Surface, InputAdapter> = {
  cli: new CliAdapter(),
  cursor: new CursorAdapter(),
  desktop: new DesktopAdapter(),
  "local-agent": new LocalAgentAdapter(),
  api: new CliAdapter(), // API uses same parsing as CLI
};

export function getAdapter(surface: Surface): InputAdapter {
  return ADAPTERS[surface];
}
