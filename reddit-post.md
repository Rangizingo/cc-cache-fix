# Title: Found the root cause of the insane token drain in Claude Code and patched it. Here's the fix.

If you're on Max and watching your usage bar melt like it's on fast forward, this is probably why. I spent a full session reverse-engineering the minified cli.js and found two bugs that silently nuke prompt caching on resumed sessions.

## What's actually happening

Claude Code has a function called `db8` that filters what gets saved to your session files (the JSONL files in `~/.claude/projects/`). For non-Anthropic users, it strips out ALL attachment-type messages. Sounds harmless, except some of those attachments are `deferred_tools_delta` records that track which tools have already been announced to the model.

When you resume a session, Claude Code scans your message history to figure out "what tools did I already tell the model about?" But because `db8` nuked those records from the session file, it finds nothing. So it re-announces every single deferred tool from scratch. Every. Single. Resume.

This breaks the cache prefix in three ways:
1. The system reminders that were at `messages[0]` in the fresh session now land at `messages[N]`
2. The billing hash (computed from your first user message) changes because the first message content is different
3. The `cache_control` breakpoint shifts because the message array is a different length

Net result: your entire conversation gets rebuilt as `cache_creation` tokens instead of hitting `cache_read`. The longer the conversation, the worse it gets.

## The numbers from my actual session

Stock `claude`, same conversation, watching the cache ratio drop with every turn:

```
Turn 1:  cache_read: 15,451  cache_creation:  7,473  ratio: 67%
Turn 5:  cache_read: 15,451  cache_creation: 16,881  ratio: 48%
Turn 10: cache_read: 15,451  cache_creation: 35,006  ratio: 31%
Turn 15: cache_read: 15,451  cache_creation: 42,970  ratio: 26%
```

cache_read NEVER moved. Stuck at 15,451 (just the system prompt). Everything else was full-price token processing.

After applying the patch:

```
Turn 1 (resume): cache_read:  7,208  cache_creation: 49,748  ratio: 13%  (structural reset, expected)
Turn 2:          cache_read: 56,956  cache_creation:    728  ratio: 99%
Turn 3:          cache_read: 57,684  cache_creation:    611  ratio: 99%
```

26% to 99%. That's the difference.

## There's also a second bug

The standalone binary (the one installed at `~/.local/share/claude/`) uses a custom Bun fork that rewrites a sentinel value `cch=00000` in every outgoing API request. If your conversation happens to contain that string, it breaks the cache prefix. Running via Node.js (`node cli.js`) instead of the binary eliminates this entirely.

Related issues: https://github.com/anthropics/claude-code/issues/40524 and https://github.com/anthropics/claude-code/issues/34629

## The fix

Two parts:

**1. Run via npm/Node.js instead of the standalone binary.** This kills the sentinel replacement bug.

**2. Patch `db8` to preserve cache-relevant attachments.** This is the big one.

The original `db8`:
```js
function db8(A){
  if(A.type==="attachment"&&ss1()!=="ant"){
    if(A.attachment.type==="hook_additional_context"
       &&a6(process.env.CLAUDE_CODE_SAVE_HOOK_ADDITIONAL_CONTEXT))return!0;
    return!1  // ← drops EVERYTHING else, including deferred_tools_delta
  }
  if(A.type==="progress"&&Ns6(A.data?.type))return!1;
  return!0
}
```

The patched version just adds two types to the allowlist:
```js
if(A.attachment.type==="deferred_tools_delta")return!0;
if(A.attachment.type==="mcp_instructions_delta")return!0;
```

That's it. Two lines. The deferred tool announcements survive to the session file, so on resume the delta computation sees "I already announced these" and doesn't re-emit them. Cache prefix stays stable.

## How to apply it yourself

I wrote a patch script that handles everything. Tested on v2.1.81 with Max x20.

```bash
mkdir -p ~/cc-cache-fix && cd ~/cc-cache-fix

# Install the npm version locally (doesn't touch your stock claude)
npm install @anthropic-ai/claude-code@2.1.81

# Back up the original
cp node_modules/@anthropic-ai/claude-code/cli.js node_modules/@anthropic-ai/claude-code/cli.js.orig

# Apply the patch (find db8 and add the two allowlist lines)
python3 -c "
import sys
path = 'node_modules/@anthropic-ai/claude-code/cli.js'
with open(path) as f: src = f.read()

old = 'if(A.attachment.type===\"hook_additional_context\"&&a6(process.env.CLAUDE_CODE_SAVE_HOOK_ADDITIONAL_CONTEXT))return!0;return!1}'
new = old.replace('return!1}',
    'if(A.attachment.type===\"deferred_tools_delta\")return!0;'
    'if(A.attachment.type===\"mcp_instructions_delta\")return!0;'
    'return!1}')

if old not in src:
    print('ERROR: pattern not found, wrong version?'); sys.exit(1)
src = src.replace(old, new, 1)

with open(path, 'w') as f: f.write(src)
print('Patched. Verify:')
print('  FOUND' if new.split('return!1}')[0] in open(path).read() else '  FAILED')
"

# Run it
node node_modules/@anthropic-ai/claude-code/cli.js
```

Or make a wrapper script so you can just type `claude-patched`:

```bash
cat > ~/.local/bin/claude-patched << 'EOF'
#!/usr/bin/env bash
exec node ~/cc-cache-fix/node_modules/@anthropic-ai/claude-code/cli.js "$@"
EOF
chmod +x ~/.local/bin/claude-patched
```

Stock `claude` stays completely untouched. Zero risk.

## What you should see

Run a session, resume it, check the JSONL:

```bash
# Check your latest session's cache stats
tail -50 ~/.claude/projects/*/*.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    try: d = json.loads(line.strip())
    except: continue
    u = d.get('usage') or d.get('message',{}).get('usage')
    if not u or 'cache_read_input_tokens' not in u: continue
    cr, cc = u.get('cache_read_input_tokens',0), u.get('cache_creation_input_tokens',0)
    total = cr + cc + u.get('input_tokens',0)
    print(f'CR:{cr:>7,}  CC:{cc:>7,}  ratio:{cr/total*100:.0f}%' if total else '')
"
```

If consecutive resumes show cache_read growing and cache_creation staying small, you're good.

**Note:** The first resume after a fresh session will still show low cache_read (the message structure changes going from fresh to resumed). That's normal. Every resume after that should hit 95%+ cache ratio.

## Caveats

- Tested on v2.1.81 only. Function names are minified and will change across versions.
- The patch script pattern-matches on the exact `db8` string, so it'll fail safely if the code changes.
- This doesn't help with output tokens, only input caching.
- If Anthropic fixes this upstream, you can just go back to stock `claude` and delete the patch directory.

Hopefully Anthropic picks this up. The fix is literally two lines in their source.
