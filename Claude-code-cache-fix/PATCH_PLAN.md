# Patch Plan: Fix Two Cache-Busting Bugs in Claude Code

> **Goal**: Apply two minimal, safe patches to fix cache-busting bugs that cause 10-20x token overconsumption. Test locally to confirm, then submit to Anthropic.

---

## Why 41.9k Visible Tokens Eats 5% of Max x20

| Component | Tokens (est.) | Visible? |
|---|---|---|
| System prompt (static) | ~5,300 | No |
| System prompt (dynamic) | ~1,500 | No |
| Tool schemas (23+ builtins) | ~12,000 | No |
| Attribution header + cc_version | ~100 | No |
| Deferred tools delta attachment | ~3,000 | No |
| User message | ~200 | Yes |
| **Total INPUT to API** | **~22,100** | |
| Thinking tokens (adaptive, unbounded) | 10k-50k+ | No |
| Output tokens | ~8,000 | Yes |
| Title gen side-query (Haiku) | ~500 | No |

With working cache: 22K input at 0.1x (cache_read) = **2.2K effective**.
With cache BUSTED: 22K input at 1.25x (cache_creation) = **27.5K effective** — **12.5x more expensive**.
If fast mode auto-activates (6x multiplier): single turn can cost **$2-5 of limit**.

---

## Patch 1: Sentinel Collision Fix

### The Bug

- `src/constants/system.ts:82` injects `cch=00000` placeholder in the attribution header
- Bun's native HTTP stack does a **first-occurrence** string replacement of `cch=00000` in the serialized JSON body
- Request object at `src/services/api/claude.ts:1700-1728` has field order: `model`, `messages`, `system`
- **`messages[]` serializes before `system[]`** in JSON
- If ANY message text contains literal `cch=00000` (discussing CC internals, reading source, quoting CLAUDE.md), Bun replaces THAT instead of the real sentinel
- Message content mutated → cache prefix invalidated → full rebuild every turn

### The Fix

**File**: `src/utils/messages.ts`
**Location**: After line ~2293 (end of the `.forEach(message => {...})` loop), before line ~2301 (`const relocated = ...`)

#### Step 1: Add the sanitization function (above `normalizeMessagesForAPI` or at end of file)

```typescript
/**
 * Prevent collision with the cch=00000 attestation sentinel.
 * Bun's native HTTP stack does first-occurrence replacement in serialized JSON;
 * messages[] serializes before system[], so a literal match in message content
 * gets replaced instead of the real sentinel → mutates content → busts cache.
 *
 * Fix: insert U+200B (zero-width space) between "cch" and "=" in message text
 * so Bun's exact-match search skips it. Invisible in display.
 */
const CCH_SENTINEL_PATTERN = /cch=00000/g
const CCH_SAFE_REPLACEMENT = 'cch\u200B=00000'

function sanitizeCchSentinel(
  messages: (UserMessage | AssistantMessage)[],
): (UserMessage | AssistantMessage)[] {
  return messages.map(msg => {
    if (msg.type === 'user') {
      const content = msg.message.content
      if (typeof content === 'string') {
        if (!content.includes('cch=00000')) return msg
        return {
          ...msg,
          message: {
            ...msg.message,
            content: content.replace(CCH_SENTINEL_PATTERN, CCH_SAFE_REPLACEMENT),
          },
        }
      }
      if (Array.isArray(content)) {
        let changed = false
        const newContent = content.map(block => {
          if (block.type === 'text' && block.text.includes('cch=00000')) {
            changed = true
            return {
              ...block,
              text: block.text.replace(CCH_SENTINEL_PATTERN, CCH_SAFE_REPLACEMENT),
            }
          }
          return block
        })
        if (!changed) return msg
        return { ...msg, message: { ...msg.message, content: newContent } }
      }
    }
    if (msg.type === 'assistant') {
      let changed = false
      const newContent = msg.message.content.map(block => {
        if (block.type === 'text' && block.text.includes('cch=00000')) {
          changed = true
          return {
            ...block,
            text: block.text.replace(CCH_SENTINEL_PATTERN, CCH_SAFE_REPLACEMENT),
          }
        }
        return block
      })
      if (!changed) return msg
      return { ...msg, message: { ...msg.message, content: newContent } }
    }
    return msg
  })
}
```

#### Step 2: Call it in the normalization pipeline

Find this code around line ~2295-2305:

```typescript
    }) // <-- end of .forEach(message => { ... })

  // Relocate text siblings off tool_reference messages ...
  const relocated = checkStatsigFeatureGate_CACHED_MAY_BE_STALE(
    'tengu_toolref_defer_j8m',
  )
    ? relocateToolReferenceSiblings(result)
    : result
```

Change to:

```typescript
    }) // <-- end of .forEach(message => { ... })

  // Sanitize cch=00000 sentinel to prevent attestation collision (cache bug #1)
  const sentinelSafe = sanitizeCchSentinel(result)

  // Relocate text siblings off tool_reference messages ...
  const relocated = checkStatsigFeatureGate_CACHED_MAY_BE_STALE(
    'tengu_toolref_defer_j8m',
  )
    ? relocateToolReferenceSiblings(sentinelSafe)
    : sentinelSafe
```

### Safety Notes

- **No-op for 99.9% of sessions**: Only fires when messages literally contain `cch=00000`
- **Invisible**: Zero-width space (U+200B) renders as nothing in all display contexts
- **Attestation preserved**: The real sentinel in `system[]` is never touched
- **Zero perf overhead**: `includes()` short-circuit before regex

---

## Patch 2: Fingerprint Stability Fix

### The Bug

- `computeFingerprintFromMessages()` at `src/services/api/claude.ts:1325` calls `extractFirstMessageText()` at `src/utils/fingerprint.ts:16-38`
- `extractFirstMessageText()` finds the **first** `msg.type === 'user'` message
- `deferred_tools_delta` attachment (~13KB) gets converted to a UserMessage with `isMeta: true` by `normalizeAttachmentForAPI()` at `src/utils/messages.ts:4178-4192`
- **Fresh session**: No prior assistant messages → attachment bubbles to `messages[0]` via `reorderAttachmentsForAPI()` at `src/utils/messages.ts:1520-1523`
- **Resume session**: Prior assistant messages block bubble → attachment lands at `messages[N]`
- Fresh: fingerprint from attachment text. Resume: fingerprint from real user message
- Different fingerprint → different `cc_version=2.1.87.XXX` in system prompt → **full cache rebuild**

### The Fix

**File**: `src/utils/fingerprint.ts`
**Line**: 19

Find:
```typescript
export function extractFirstMessageText(
  messages: (UserMessage | AssistantMessage)[],
): string {
  const firstUserMessage = messages.find(msg => msg.type === 'user')
```

Change line 19 to:
```typescript
  const firstUserMessage = messages.find(
    msg => msg.type === 'user' && !('isMeta' in msg && msg.isMeta),
  )
```

That's it. One line.

### Why This Works

- `isMeta: true` is set on ALL attachment-derived UserMessages:
  - `deferred_tools_delta`: `src/utils/messages.ts:4191`
  - All other attachment types: lines 3295, 3381, 3395, 3415, 3441, 3449, etc.
- Real user messages NEVER have `isMeta: true` — see `src/utils/processUserInput/processTextPrompt.ts:19-26`
- The `'isMeta' in msg &&` guard is needed because `AssistantMessage` type doesn't have `isMeta`
- If no non-meta user message exists, returns `''` → deterministic fingerprint (always same hash)

### Safety Notes

- **No behavior change** for sessions without resume or attachment position issues
- **Deterministic**: Fingerprint now always comes from the real user's first message
- **Backward compatible**: Fresh sessions where the user message was already first → same result

---

## Files Summary

| File | What to Change | Where |
|---|---|---|
| `src/utils/messages.ts` | Add `sanitizeCchSentinel()` function + call it after line ~2293 | ~50 lines added |
| `src/utils/fingerprint.ts` | Skip `isMeta` messages in `extractFirstMessageText()` | Line 19 (1 line changed) |

---

## How to Test

### Prerequisites

Check `package.json` for build/run scripts. You'll need Bun installed.

### Bug 1 — Sentinel Test

1. **Before patch**: Start a fresh session. Send a message that includes the literal text `cch=00000` (e.g., "What does cch=00000 mean in the attestation header?"). Check the cost tracker or `--debug` output. You should see `cache_creation_input_tokens` is large on EVERY subsequent turn (cache never hits).

2. **After patch**: Same test. After the first turn, subsequent turns should show `cache_read_input_tokens` instead of `cache_creation_input_tokens` (cache is stable).

### Bug 2 — Resume Test

1. **Before patch**: Start a session, exchange 2-3 messages, exit. Resume with `--resume`. Check the first turn's token usage — `cache_creation_input_tokens` will be very high (full rebuild).

2. **After patch**: Same test. First resumed turn should show `cache_read_input_tokens` (cache prefix matches from prior session).

### Regression

- Normal session (no `cch=00000` in messages, no resume): behavior should be identical before/after
- Attestation: Server should not reject requests (the real sentinel in system[] is unchanged)

### Monitoring

To observe cache behavior over time, look at:
- `cache_creation_input_tokens` vs `cache_read_input_tokens` in API response usage
- Cost tracker output (if enabled)
- `--debug` flag for detailed logging
- The `tengu_api_cache_breakpoints` event in `src/services/api/claude.ts:3072`

---

## What to Send to Anthropic

If testing confirms the fixes work:

1. **Bug report** with FINDINGS.md evidence (file:line, mechanism, math)
2. **Proposed patches** — the two diffs above
3. **Test results** — before/after cache_creation vs cache_read numbers
4. **Impact estimate**: These bugs can cause 12.5x-75x cost inflation per turn depending on whether fast mode is also active

The sentinel bug (Patch 1) requires a long-term fix in the Bun binary (`Attestation.zig`) to either:
- Search only within the system prompt portion of the serialized body
- Use a sentinel that can't appear in message content
- Serialize system before messages in the request body

The fingerprint bug (Patch 2) is a pure TypeScript fix with no external dependencies.
