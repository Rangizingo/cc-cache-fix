import type { TaskType } from "../types.js";

// ---------------------------------------------------------------------------
// Intent classifier — maps raw user input to a TaskType + primary intent.
//
// This is a rule-based classifier. In production you'd wire this to an LLM
// call, but the contract output is the same regardless of the backend.
// ---------------------------------------------------------------------------

export interface Classification {
  task_type: TaskType;
  primary_intent: string;
  confidence: number;
}

interface PatternRule {
  pattern: RegExp;
  task_type: TaskType;
  intent_template: string;
}

const RULES: PatternRule[] = [
  // Code editing
  {
    pattern: /\b(add|create|implement|write|build)\b.*\b(function|method|class|component|feature|endpoint|api|route|module)\b/i,
    task_type: "code_edit",
    intent_template: "Create new code",
  },
  {
    pattern: /\b(change|modify|update|edit|replace|rename|move)\b/i,
    task_type: "code_edit",
    intent_template: "Modify existing code",
  },

  // Debugging
  {
    pattern: /\b(fix|bug|error|crash|broken|issue|fail|exception|wrong|not working)\b/i,
    task_type: "debug",
    intent_template: "Fix a bug or error",
  },

  // Refactoring
  {
    pattern: /\b(refactor|restructure|reorganize|clean\s*up|simplify|extract|dedup|split)\b/i,
    task_type: "refactor",
    intent_template: "Refactor code",
  },

  // Testing
  {
    pattern: /\b(test|spec|coverage|assert|expect|mock|stub|unit test|integration test)\b/i,
    task_type: "test",
    intent_template: "Write or run tests",
  },

  // Code review
  {
    pattern: /\b(review|audit|check|inspect|look at|assess|evaluate)\b.*\b(code|pr|pull request|changes|diff)\b/i,
    task_type: "code_review",
    intent_template: "Review code",
  },

  // Shell
  {
    pattern: /\b(run|execute|shell|command|terminal|bash|script)\b/i,
    task_type: "shell",
    intent_template: "Execute shell command",
  },

  // Deploy
  {
    pattern: /\b(deploy|release|publish|ship|push to prod|rollout)\b/i,
    task_type: "deploy",
    intent_template: "Deploy or release",
  },

  // Documentation
  {
    pattern: /\b(doc|document|readme|jsdoc|comment|explain|describe)\b/i,
    task_type: "docs",
    intent_template: "Write documentation",
  },

  // Architecture / design
  {
    pattern: /\b(architect|design|spec|specification|plan|blueprint|proposal|rfc)\b/i,
    task_type: "design_spec",
    intent_template: "Create design specification",
  },
  {
    pattern: /\b(agent|gateway|pipeline|workflow|system|infrastructure)\b.*\b(architect|design|build|create)\b/i,
    task_type: "agent_architecture",
    intent_template: "Design agent architecture",
  },

  // Query / question
  {
    pattern: /\b(what|how|why|where|when|who|which|can you|tell me|explain)\b/i,
    task_type: "query",
    intent_template: "Answer a question",
  },
];

export function classify(input: string): Classification {
  const trimmed = input.trim();
  if (!trimmed) {
    return {
      task_type: "unknown",
      primary_intent: "Unable to classify empty input",
      confidence: 0,
    };
  }

  // Score each rule — first match wins, but we accumulate confidence
  for (const rule of RULES) {
    if (rule.pattern.test(trimmed)) {
      return {
        task_type: rule.task_type,
        primary_intent: rule.intent_template,
        confidence: 0.8,
      };
    }
  }

  return {
    task_type: "unknown",
    primary_intent: "Unclassified task",
    confidence: 0.3,
  };
}
