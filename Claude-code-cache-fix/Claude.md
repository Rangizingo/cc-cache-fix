# Claude Code Token & Cache Investigation

## Mission

Investigate and patch Claude Code’s source code to fix excessive token consumption burning through usage limits at 10-20x expected rates. A Max x20 plan user sent ONE message in a fresh 0-context session — 41.9k visible tokens — and it consumed 5% of the 5-hour limit. That should barely register.

Two cache-busting bugs are documented below as a starting point. **Do not assume they are the complete picture.** Use the source code in `src/` to independently verify every claim and hunt for anything else that explains disproportionate usage.

-----

## Confirmed Bug 1: Sentinel Replacement Breaks Cache

**File:** `src/constants/system.ts:82` — `getAttributionHeader()`

The standalone binary’s custom Bun fork searches the serialized JSON body for the FIRST `cch=00000` and replaces zeros with a hash. Since `messages[]` serializes before `system[]` in JSON, if conversation history contains the literal `cch=00000` (from discussing CC internals, reading source, CLAUDE.md), the replacement hits messages instead of system → mutates content every request → cache prefix broken → full rebuild.

**Evidence:** Comment at line 64-68 explicitly documents the mechanism. The `feature('NATIVE_CLIENT_ATTESTATION')` gate controls injection.

## Confirmed Bug 2: –resume Always Breaks Cache

**Files:**

- `src/utils/attachments.ts:~1455` — `getDeferredToolsDeltaAttachment()`
- `src/utils/messages.ts:~1481` — `reorderAttachmentsForAPI()` — attachments bubble up until blocked by assistant msg or tool_result
- `src/utils/fingerprint.ts` — `computeFingerprint()` uses chars at positions [4,7,20] of first user message text
- `src/services/api/claude.ts:~3063` — `addCacheBreakpoints()` marks `messages[last]`

Fresh session: deferred_tools_delta bubbles to `messages[0]` (~13KB). Resume: blocked by existing assistant messages, lands at `messages[N]`. Result: messages[0] differs → fingerprint differs → system prompt cc_version differs → triple cache bust.

## Suspected Additional Causes — INVESTIGATE THESE

### Hidden Token Overhead

- `src/constants/prompts.ts` `getSystemPrompt()` — assembles 15-25KB+ of invisible system prompt. Quantify exact token count.
- Tool schemas serialized every request. `src/utils/analyzeContext.ts` has `countToolDefinitionTokens()`. With MCP + builtins this could be huge.
- Adaptive thinking (`src/services/api/claude.ts:~1611`) has NO budget cap. These are billed but invisible to user.
- Redacted thinking — generated, billed, content hidden.

### Multiple API Calls Per User Turn

- Find ALL `queryModel`, `queryHaiku`, `queryModelWithoutStreaming` call sites. Title generation, compaction, classifiers, side-queries — each one bills tokens.

### Rate Limit Weighting

- `src/services/claudeAiLimits.ts` — utilization comes from server headers. Does `cache_creation` weigh more than `cache_read` toward the rate limit? If cache_creation costs 10x more toward limits, that explains 5% from 41.9k.

### Fast Mode

- `src/utils/modelCost.ts` — Opus 4.6 fast mode = $30/$150/MTok (2x normal). Check if fast mode latches on without user awareness.

### Workload Routing

- `src/constants/system.ts` `cc_workload` field — could wrong value route to tighter-limit pool?

-----

## Local Cache Research

Current caching is server-side only. Investigate feasibility of client-side caching:

- `src/services/api/claude.ts` `getCacheControl()` — returns `{ type: 'ephemeral', ttl: '1h' }` for eligible users, 5min default
- The `useCachedMC` / `CachedMCEditsBlock` / `pinnedEdits` system — already doing incremental cache edits?
- `src/history.ts` — session persistence already stores conversation state
- Could we cache response hashes locally to skip duplicate API calls?
- Could system prompt + tool schemas be sent once and referenced by hash?
- Could compaction results be cached locally to avoid re-compaction on resume?

-----

## Deliverables

1. **Root cause analysis** — every identified issue with file:line, mechanism, and quantified token impact
1. **Patches** — minimal TypeScript fixes for each bug. Must not break attestation/billing. Must maintain cache hits for non-buggy cases
1. **Diagnostic script** — standalone tool to detect active cache bugs (log analysis or MITM)
1. **Local caching proposal** — architecture doc with estimated savings and implementation plan
1. **Reddit post draft** — community-friendly writeup for r/ClaudeAI

## Working Rules

- Cite file:line for every claim
- Show math when estimating tokens/costs
- Trace actual source to confirm assumptions — don’t speculate
- Patches must be safe — attestation exists for fraud prevention, don’t break it
- Use ultrathink for complex analysis
