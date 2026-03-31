#!/usr/bin/env python3
"""
apply-patches.py — Patch Claude Code cli.js to fix cache bugs.

Patch 1: Modify db8 JSONL write filter to persist deferred_tools_delta and
         mcp_instructions_delta attachments. Fixes resume cache regression.

Patch 2: Force 1-hour cache TTL on all cache_control markers. The API may
         ignore this if your plan doesn't support it, but it costs nothing to try.

Usage:
    python3 apply-patches.py /path/to/cli.js
"""

import re
import sys

# ── Patch definitions ────────────────────────────────────────────────────────

# Original db8: drops all attachment-type messages except hook_additional_context
DB8_ORIGINAL = (
    'function db8(A){'
    'if(A.type==="attachment"&&ss1()!=="ant"){'
    'if(A.attachment.type==="hook_additional_context"'
    '&&a6(process.env.CLAUDE_CODE_SAVE_HOOK_ADDITIONAL_CONTEXT))return!0;'
    'return!1}'
    'if(A.type==="progress"&&Ns6(A.data?.type))return!1;'
    'return!0}'
)

# Patched db8: also allows deferred_tools_delta and mcp_instructions_delta
DB8_PATCHED = (
    'function db8(A){'
    'if(A.type==="attachment"&&ss1()!=="ant"){'
    'if(A.attachment.type==="hook_additional_context"'
    '&&a6(process.env.CLAUDE_CODE_SAVE_HOOK_ADDITIONAL_CONTEXT))return!0;'
    'if(A.attachment.type==="deferred_tools_delta")return!0;'
    'if(A.attachment.type==="mcp_instructions_delta")return!0;'
    'return!1}'
    'if(A.type==="progress"&&Ns6(A.data?.type))return!1;'
    'return!0}'
)

# Original fingerprint selector: first user message, including meta messages
FINGERPRINT_ORIGINAL = 'function FA9(A){let q=A.find((_)=>_.type==="user");'
FINGERPRINT_PATCHED = (
    'function FA9(A){let q=A.find((_)=>_.type==="user"&&!("isMeta"in _&&_.isMeta));'
)


def apply_patches(path: str) -> None:
    print(f"[*] Reading {path} ({''})...")
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    print(f"    {len(source):,} bytes")

    # ── Patch 1: db8 attachment filter ────────────────────────────────────
    if DB8_PATCHED in source:
        print("[*] Patch 1 (db8 attachment filter): already applied, skipping")
    elif DB8_ORIGINAL in source:
        source = source.replace(DB8_ORIGINAL, DB8_PATCHED, 1)
        print("[*] Patch 1 (db8 attachment filter): applied")
    else:
        # Try regex fallback in case whitespace differs slightly
        pattern = re.compile(
            r'function db8\(A\)\{if\(A\.type==="attachment"&&ss1\(\)!=="ant"\)\{'
            r'if\(A\.attachment\.type==="hook_additional_context"'
            r'&&a6\(process\.env\.CLAUDE_CODE_SAVE_HOOK_ADDITIONAL_CONTEXT\)\)return!0;'
            r'return!1\}'
        )
        match = pattern.search(source)
        if match:
            old = match.group(0)
            new = old.replace(
                "return!1}",
                'if(A.attachment.type==="deferred_tools_delta")return!0;'
                'if(A.attachment.type==="mcp_instructions_delta")return!0;'
                "return!1}",
                1,
            )
            source = source[:match.start()] + new + source[match.end():]
            print("[*] Patch 1 (db8 attachment filter): applied via regex fallback")
        else:
            print("[!] Patch 1 FAILED: could not find db8 function")
            print("    Expected pattern not found. Has cli.js been updated?")
            sys.exit(1)

    # ── Patch 1b: fingerprint source should ignore meta user messages ───────
    # Source equivalent:
    # extractFirstMessageText(messages.find(msg => msg.type==='user' && !msg.isMeta))
    if FINGERPRINT_PATCHED in source:
        print("[*] Patch 1b (fingerprint meta skip): already applied, skipping")
    elif FINGERPRINT_ORIGINAL in source:
        source = source.replace(FINGERPRINT_ORIGINAL, FINGERPRINT_PATCHED, 1)
        print("[*] Patch 1b (fingerprint meta skip): applied")
    else:
        # Regex fallback for different minifier variable names
        pattern = re.compile(
            r'function \w+\(\w+\)\{let \w+=\w+\.find\(\((\w+)\)=>\1\.type==="user"\);'
        )
        match = pattern.search(source)
        if match:
            var = match.group(1)
            old = match.group(0)
            new = old.replace(
                f'{var}.type==="user"',
                f'{var}.type==="user"&&!('
                f'"isMeta"in {var}&&{var}.isMeta'
                f')',
                1,
            )
            source = source[:match.start()] + new + source[match.end():]
            print("[*] Patch 1b (fingerprint meta skip): applied via regex fallback")
        else:
            print("[!] Patch 1b WARNING: could not find fingerprint selector, skipping")
            print("    Non-critical; resume first-turn cache may still miss.")

    # ── Patch 2: Force 1-hour cache TTL ─────────────────────────────────
    # sjY() gates whether cache_control gets ttl:"1h". It checks subscription
    # status and a server-side feature flag allowlist. We bypass all of that.
    # If the API doesn't support 1h for your plan, it silently ignores it.
    SJY_ORIGINAL = 'function sjY(A){if(QA()==="bedrock"'
    SJY_PATCHED = 'function sjY(A){return!0;if(QA()==="bedrock"'

    if SJY_PATCHED in source:
        print("[*] Patch 2 (force 1h cache TTL): already applied, skipping")
    elif SJY_ORIGINAL in source:
        source = source.replace(SJY_ORIGINAL, SJY_PATCHED, 1)
        print("[*] Patch 2 (force 1h cache TTL): applied")
    else:
        print("[!] Patch 2 WARNING: could not find sjY function, skipping")
        print("    1h cache TTL not forced. Non-critical, continuing.")

    # ── Write back ────────────────────────────────────────────────────────
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    print(f"[*] Wrote patched file ({len(source):,} bytes)")

    # ── Verify ────────────────────────────────────────────────────────────
    with open(path, "r", encoding="utf-8") as f:
        verify = f.read()

    ok = True
    if DB8_PATCHED in verify:
        print("[*] Verification: Patch 1 (db8) confirmed")
    else:
        print("[!] Verification FAILED: Patch 1 (db8) not found in output")
        ok = False

    if FINGERPRINT_PATCHED in verify:
        print("[*] Verification: Patch 1b (fingerprint meta skip) confirmed")
    elif FINGERPRINT_ORIGINAL not in verify:
        print("[*] Verification: Patch 1b skipped (pattern not found)")
    else:
        print("[!] Verification FAILED: Patch 1b (fingerprint meta skip) not applied")
        ok = False

    if SJY_PATCHED in verify:
        print("[*] Verification: Patch 2 (1h TTL) confirmed")
    elif SJY_ORIGINAL not in verify:
        print("[*] Verification: Patch 2 skipped (sjY not found)")
    else:
        print("[!] Verification FAILED: Patch 2 (1h TTL) not applied")
        ok = False

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-cli.js>")
        sys.exit(1)
    apply_patches(sys.argv[1])
