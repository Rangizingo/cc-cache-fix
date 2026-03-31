# Claude Code Cache Fix

Patch + test toolkit for the known Claude Code cache issues:
- resume cache regression (`deferred_tools_delta` / `mcp_instructions_delta`)
- sentinel replacement behavior (`cch=00000`)

This repo keeps stock `claude` untouched and gives you a separate `claude-patched` command.

## Quick Start (Linux + macOS)

From repo root:

```bash
./install.sh
```

Then open a new terminal and verify:

```bash
type -a claude-patched
python3 test_cache.py claude-patched --timeout 240 --debug-transcript
```

If you specifically want the interactive mac installer:

```bash
./install-mac.sh
```

## Smoke Check (installer + test + summary)

Run:

```bash
./smoke_check.sh --timeout 240
```

What it does:
- runs installer (`install.sh` by default)
- runs `test_cache.py`
- saves full output under `results/`
- prints a short PASS/FAIL block you can paste into a post

## Usage Audit (real sessions)

To audit recent session cache efficiency:

```bash
python3 usage_audit.py --top 10 --window 8
```

Healthy sessions usually show high read ratio in the recent window.

## Notes

- Requires `node`, `npm`, and `python3`.
- Requires Claude auth (`ANTHROPIC_API_KEY` or Claude local auth setup).
- A currently running old `claude-patched` process will not auto-update; start a new session after patching.
