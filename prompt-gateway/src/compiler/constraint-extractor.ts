// ---------------------------------------------------------------------------
// Constraint extractor — pulls constraints, assumptions, referenced files,
// and tools from raw user input.
//
// Rule-based with pattern matching. Swap for LLM-backed extraction in prod.
// ---------------------------------------------------------------------------

export interface Extraction {
  constraints: string[];
  assumptions: string[];
  files_mentioned: string[];
  tools_mentioned: string[];
}

// File path patterns
const FILE_PATTERN = /(?:^|\s)((?:\.{0,2}\/)?[\w./-]+\.[\w]+)/g;
const QUOTED_PATH = /["'`]((?:\.{0,2}\/)?[\w./-]+\.[\w]+)["'`]/g;

// Constraint signal phrases
const CONSTRAINT_SIGNALS: Array<{ pattern: RegExp; prefix: string }> = [
  { pattern: /\bmust\b\s+(.+?)(?:[.!,;]|$)/gi, prefix: "" },
  { pattern: /\bshould\b\s+(.+?)(?:[.!,;]|$)/gi, prefix: "" },
  { pattern: /\bdon'?t\b\s+(.+?)(?:[.!,;]|$)/gi, prefix: "Do not " },
  { pattern: /\bdo\s+not\b\s+(.+?)(?:[.!,;]|$)/gi, prefix: "Do not " },
  { pattern: /\bnever\b\s+(.+?)(?:[.!,;]|$)/gi, prefix: "Never " },
  { pattern: /\bonly\b\s+(.+?)(?:[.!,;]|$)/gi, prefix: "Only " },
  { pattern: /\bno\s+more\s+than\b\s+(.+?)(?:[.!,;]|$)/gi, prefix: "Limit: " },
  { pattern: /\bkeep\b\s+(.+?)(?:[.!,;]|$)/gi, prefix: "Keep " },
  { pattern: /\bwithout\b\s+(.+?)(?:[.!,;]|$)/gi, prefix: "Without " },
  { pattern: /\bpreserve\b\s+(.+?)(?:[.!,;]|$)/gi, prefix: "Preserve " },
  { pattern: /\bminimal\b/gi, prefix: "Keep changes minimal" },
];

// Tool / capability signals
const TOOL_SIGNALS: Array<{ pattern: RegExp; tool: string }> = [
  { pattern: /\bgit\b/i, tool: "git" },
  { pattern: /\bdocker\b/i, tool: "docker" },
  { pattern: /\bnpm|yarn|pnpm|bun\b/i, tool: "package_manager" },
  { pattern: /\bshell|bash|terminal|command\b/i, tool: "shell" },
  { pattern: /\bdatabase|sql|postgres|mysql|sqlite\b/i, tool: "database" },
  { pattern: /\bapi|http|fetch|curl\b/i, tool: "http" },
  { pattern: /\beditor|vim|vscode\b/i, tool: "editor" },
  { pattern: /\bfilesystem|file|directory|folder\b/i, tool: "filesystem" },
];

export function extractConstraints(input: string): Extraction {
  const constraints: string[] = [];
  const assumptions: string[] = [];
  const filesSet = new Set<string>();
  const toolsSet = new Set<string>();

  // Extract files
  for (const regex of [FILE_PATTERN, QUOTED_PATH]) {
    let m: RegExpExecArray | null;
    const r = new RegExp(regex.source, regex.flags);
    while ((m = r.exec(input)) !== null) {
      const path = m[1];
      // Filter out obvious non-paths
      if (path.length > 3 && !path.startsWith("http")) {
        filesSet.add(path);
      }
    }
  }

  // Extract constraints
  for (const signal of CONSTRAINT_SIGNALS) {
    let m: RegExpExecArray | null;
    const r = new RegExp(signal.pattern.source, signal.pattern.flags);
    while ((m = r.exec(input)) !== null) {
      const constraint = m[1] ? signal.prefix + m[1].trim() : signal.prefix;
      if (constraint.length > 3) {
        constraints.push(constraint);
      }
    }
  }

  // Extract tools
  for (const signal of TOOL_SIGNALS) {
    if (signal.pattern.test(input)) {
      toolsSet.add(signal.tool);
    }
  }

  // Infer assumptions from lack of specificity
  if (filesSet.size === 0) {
    assumptions.push("No specific files mentioned — will scan workspace");
  }
  if (constraints.length === 0) {
    assumptions.push("No explicit constraints — applying safe defaults");
  }

  return {
    constraints: [...new Set(constraints)],
    assumptions,
    files_mentioned: [...filesSet],
    tools_mentioned: [...toolsSet],
  };
}
