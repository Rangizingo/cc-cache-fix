#!/usr/bin/env python3
"""
test_cache.py — Test Claude Code for two known cache/replacement bugs.

Bug 1: Sentinel replacement — standalone binary rewrites cch=00000 in request body
Bug 2: Resume cache regression — deferred_tools_delta breaks cache prefix since v2.1.69

Usage:
  python3 test_cache.py                                        # test installed 'claude'
  python3 test_cache.py /path/to/claude                        # test specific binary
  python3 test_cache.py "npx @anthropic-ai/claude-code@2.1.66" # test npm version

Requires: working API key (ANTHROPIC_API_KEY or ~/.claude config)
Cost: ~5 cheap API calls (~$0.01-0.03 total)
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter

DEFAULT_TIMEOUT_SECONDS = 120


def run_claude(
    claude_cmd: list[str], args: list[str], cwd: str, timeout_s: int
) -> dict | None:
    """Run claude with args, return parsed result JSON."""
    cmd = [*claude_cmd, *args, "--output-format", "json"]
    run_env = {**os.environ}
    run_env.pop("CLAUDECODE", None)

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, cwd=cwd, env=run_env
        )
    except subprocess.TimeoutExpired:
        print(f"  ✗ Timeout ({timeout_s}s)")
        return None

    for line in reversed(proc.stdout.strip().split("\n")):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            if d.get("type") == "result":
                return d
        except json.JSONDecodeError:
            continue

    if proc.returncode != 0:
        stderr = proc.stderr.strip()[:200] if proc.stderr else ""
        print(f"  ✗ Exit code {proc.returncode}: {stderr}")
    return None


def extract_cache(result: dict) -> tuple[int, int, str | None]:
    """Extract cache_read, cache_creation, session_id from result."""
    usage = result.get("usage", {})
    cr = usage.get("cache_read_input_tokens", 0)
    cc = usage.get("cache_creation_input_tokens", 0)
    sid = result.get("session_id")
    return cr, cc, sid


def parse_claude_cmd(arg: str) -> list[str]:
    """Parse claude command from argument."""
    if arg.startswith("npx "):
        return arg.split()
    return [arg]


def is_api_error_result(result: dict) -> bool:
    """Best-effort check for API error payloads surfaced as normal result objects."""
    if result.get("is_error") is True:
        return True
    text = str(result.get("result", "")).strip()
    if text.startswith("API Error:"):
        return True
    return '"type":"error"' in text[:300]


def cache_ratio(cache_read: int, cache_creation: int) -> float | None:
    total = cache_read + cache_creation
    if total <= 0:
        return None
    return cache_read / total


def classify_resume_cache(stats: dict) -> str:
    """
    Classify resume cache behavior.

    healthy: resumed turns are mostly cache reads
    degraded: partial reuse, still some meaningful savings
    broken: little/no reuse on resumed turns
    inconclusive: transport/API errors or no usable token stats
    """
    usable: list[dict] = []
    for key in ("resume", "consecutive"):
        row = stats.get(key) or {}
        if row.get("api_error"):
            continue
        if row.get("ratio") is None:
            continue
        usable.append(row)

    if not usable:
        return "inconclusive"

    reads = [int(r.get("cache_read", 0)) for r in usable]
    creations = [int(r.get("cache_creation", 0)) for r in usable]
    ratios = [float(r.get("ratio", 0.0)) for r in usable]

    # Strong failure signature: no read reuse and significant creation volume.
    if max(reads) == 0 and max(creations) >= 5000:
        return "broken"

    # Healthy: clear read-dominant ratio and non-trivial cached prefix.
    if max(ratios) >= 0.65 and sum(reads) >= 8000:
        return "healthy"

    # Degraded but useful: partial read reuse is present.
    if max(ratios) >= 0.40 and max(reads) >= 2000:
        return "degraded"

    return "broken"


def find_session_jsonl(session_id: str) -> str | None:
    """Locate a session JSONL file by session_id."""
    claude_projects = os.path.expanduser("~/.claude/projects")
    direct = glob.glob(os.path.join(claude_projects, "*", f"{session_id}.jsonl"))
    if direct:
        return direct[0]
    return None


def debug_transcript(session_id: str) -> None:
    """Print quick transcript diagnostics for cache debugging."""
    path = find_session_jsonl(session_id)
    if not path:
        print(f"  [debug] transcript file not found for session_id={session_id}")
        return

    counts = Counter()
    first_user = None
    first_non_meta_user = None

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") == "attachment":
                    a = (obj.get("attachment") or {}).get("type", "<unknown>")
                    counts[a] += 1

                if obj.get("type") == "user":
                    content = (obj.get("message") or {}).get("content")
                    text = ""
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "text":
                                text = b.get("text", "")
                                break
                    row = {
                        "isMeta": bool(obj.get("isMeta")),
                        "text": (text or "")[:120].replace("\n", "\\n"),
                    }
                    if first_user is None:
                        first_user = row
                    if first_non_meta_user is None and not row["isMeta"]:
                        first_non_meta_user = row
    except OSError as e:
        print(f"  [debug] failed to read transcript: {e}")
        return

    print(f"  [debug] transcript: {path}")
    if counts:
        key_types = (
            "deferred_tools_delta",
            "mcp_instructions_delta",
            "hook_additional_context",
        )
        show = ", ".join(f"{k}={counts.get(k, 0)}" for k in key_types)
        print(f"  [debug] attachment counts: {show}")
    else:
        print("  [debug] attachment counts: none")

    if first_user:
        print(
            f"  [debug] first user (raw): isMeta={first_user['isMeta']} text='{first_user['text']}'"
        )
    if first_non_meta_user:
        print(
            f"  [debug] first non-meta user: text='{first_non_meta_user['text']}'"
        )


def test_replacement(claude_cmd: list[str], tmpdir: str, timeout_s: int) -> bool | None:
    """Test if sentinel cch=00000 gets replaced. Returns True if replaced, False if not, None on error."""
    print("[*] Testing sentinel replacement...")
    # Ask model to echo back a string containing the sentinel
    r = run_claude(
        claude_cmd,
        ["-p", 'Reply with ONLY this exact string, nothing else: sentinel=cch=00000=end'],
        tmpdir,
        timeout_s,
    )
    if not r:
        print("  ✗ Replacement test failed")
        return None

    result = r.get("result", "")
    print(f"  Sent:     sentinel=cch=00000=end")
    print(f"  Received: {result.strip()[:80]}")

    # Check if 00000 was replaced
    if "cch=00000" in result:
        return False  # not replaced
    elif re.search(r"cch=[0-9a-f]{5}", result):
        replaced_val = re.search(r"cch=([0-9a-f]{5})", result).group(1)
        print(f"  Replaced: 00000 → {replaced_val}")
        return True  # replaced
    else:
        print(f"  ⚠ Could not determine (model may not have echoed correctly)")
        return None


def test_resume_cache(
    claude_cmd: list[str], tmpdir: str, timeout_s: int, debug: bool = False
) -> tuple[str, dict]:
    """Test resume cache behavior. Returns (status, stats)."""
    stats = {}

    # Create test file
    with open(os.path.join(tmpdir, "readme.txt"), "w") as f:
        f.write("ABCDEFGHIJKLMNOP\n")

    # Fresh session
    print("[*] Fresh session...")
    r1 = run_claude(
        claude_cmd,
        ["-p", "Read readme.txt and tell me the first 3 characters. Be brief."],
        tmpdir,
        timeout_s,
    )
    if not r1:
        print("  ✗ Fresh session failed")
        stats["error_stage"] = "fresh"
        return "inconclusive", stats

    cr1, cc1, sid = extract_cache(r1)
    total1 = cr1 + cc1
    stats["fresh"] = {
        "cache_read": cr1,
        "cache_creation": cc1,
        "total": total1,
        "ratio": cache_ratio(cr1, cc1),
        "api_error": is_api_error_result(r1),
    }
    print(f"  cache_read={cr1:,}  cache_creation={cc1:,}")
    print(f"  result: {r1.get('result', '?')[:60]}")
    if stats["fresh"]["api_error"]:
        print("  ⚠ Fresh turn returned API error payload; verdict will be inconclusive.")
        stats["error_stage"] = "fresh_api_error"
        return "inconclusive", stats

    if not sid:
        print("  ✗ No session_id")
        stats["error_stage"] = "fresh_no_session_id"
        return "inconclusive", stats
    stats["session_id"] = sid

    time.sleep(2)

    # Resume
    print("[*] Resume...")
    r2 = run_claude(
        claude_cmd,
        ["--resume", sid, "-p", "What were those 3 characters? Answer from memory, no tools."],
        tmpdir,
        timeout_s,
    )
    if not r2:
        print("  ✗ Resume failed")
        stats["error_stage"] = "resume"
        return "inconclusive", stats

    cr2, cc2, _ = extract_cache(r2)
    stats["resume"] = {
        "cache_read": cr2,
        "cache_creation": cc2,
        "total": cr2 + cc2,
        "ratio": cache_ratio(cr2, cc2),
        "api_error": is_api_error_result(r2),
    }
    print(f"  cache_read={cr2:,}  cache_creation={cc2:,}")
    print(f"  result: {r2.get('result', '?')[:60]}")
    if stats["resume"]["ratio"] is not None:
        print(f"  read_ratio={stats['resume']['ratio']:.1%}")
    if stats["resume"]["api_error"]:
        print("  ⚠ Resume turn returned API error payload.")

    time.sleep(2)

    # Consecutive resume
    print("[*] Consecutive resume...")
    r3 = run_claude(
        claude_cmd,
        ["--resume", sid, "-p", "How many turns have we had? Just the number."],
        tmpdir,
        timeout_s,
    )
    if not r3:
        print("  ✗ Consecutive resume failed")
        stats["error_stage"] = "consecutive_resume"
        return "inconclusive", stats

    cr3, cc3, _ = extract_cache(r3)
    stats["consecutive"] = {
        "cache_read": cr3,
        "cache_creation": cc3,
        "total": cr3 + cc3,
        "ratio": cache_ratio(cr3, cc3),
        "api_error": is_api_error_result(r3),
    }
    print(f"  cache_read={cr3:,}  cache_creation={cc3:,}")
    print(f"  result: {r3.get('result', '?')[:60]}")
    if stats["consecutive"]["ratio"] is not None:
        print(f"  read_ratio={stats['consecutive']['ratio']:.1%}")
    if stats["consecutive"]["api_error"]:
        print("  ⚠ Consecutive resume turn returned API error payload.")

    stats["consecutive_grows"] = (
        cr3 > cr2
        and not stats["resume"]["api_error"]
        and not stats["consecutive"]["api_error"]
    )
    stats["consecutive_creation_drops"] = (
        cc3 < cc2 * 0.8
        and not stats["resume"]["api_error"]
        and not stats["consecutive"]["api_error"]
    )

    status = classify_resume_cache(stats)
    stats["resume_status"] = status

    if debug and sid:
        print("[*] Transcript diagnostics...")
        debug_transcript(sid)

    return status, stats


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    argv = [a for a in sys.argv[1:] if a != "--debug-transcript"]
    debug_transcript_mode = "--debug-transcript" in sys.argv[1:]

    timeout_s = DEFAULT_TIMEOUT_SECONDS
    cleaned_argv: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--timeout":
            if i + 1 >= len(argv):
                print("Usage error: --timeout requires a value in seconds")
                sys.exit(2)
            try:
                timeout_s = int(argv[i + 1])
                if timeout_s < 30:
                    print("Usage error: --timeout must be >= 30 seconds")
                    sys.exit(2)
            except ValueError:
                print("Usage error: --timeout must be an integer (seconds)")
                sys.exit(2)
            i += 2
            continue
        cleaned_argv.append(argv[i])
        i += 1

    claude_arg = cleaned_argv[0] if len(cleaned_argv) > 0 else "claude"
    claude_cmd = parse_claude_cmd(claude_arg)

    print(f"{'═' * 60}")
    print(f"  Claude Code Cache & Replacement Test")
    print(f"  Command: {' '.join(claude_cmd)}")
    print(f"  Timeout: {timeout_s}s")
    print(f"{'═' * 60}")
    print()

    with tempfile.TemporaryDirectory(prefix="cc-cache-test-") as tmpdir:
        # Track session dirs for cleanup
        claude_projects = os.path.expanduser("~/.claude/projects")
        # Snapshot existing dirs before test
        pre_dirs = set(glob.glob(os.path.join(claude_projects, "-tmp-cc-cache-test-*")))

        # ── Bug 1: Sentinel replacement ──
        print(f"{'─' * 60}")
        print(f"  BUG 1: Sentinel replacement (cch=00000)")
        print(f"{'─' * 60}")
        replaced = test_replacement(claude_cmd, tmpdir, timeout_s)
        print()

        # ── Bug 2: Resume cache ──
        print(f"{'─' * 60}")
        print(f"  BUG 2: Resume cache regression")
        print(f"{'─' * 60}")
        resume_status, stats = test_resume_cache(
            claude_cmd, tmpdir, timeout_s, debug=debug_transcript_mode
        )
        print()

        # ── Verdict ──
        print(f"{'═' * 60}")
        print(f"  RESULTS")
        print(f"{'═' * 60}")

        # Replacement verdict
        if replaced is True:
            print(f"  ✗ SENTINEL REPLACEMENT: ACTIVE")
            print(f"    The standalone binary rewrites cch=00000 in every API request.")
            print(f"    If conversation mentions this sentinel, cache prefix breaks.")
            print(f"    Mitigation: use 'npx @anthropic-ai/claude-code' instead")
            print(f"    Issue: https://github.com/anthropics/claude-code/issues/40524")
        elif replaced is False:
            print(f"  ✓ SENTINEL REPLACEMENT: NOT ACTIVE")
        else:
            print(f"  ? SENTINEL REPLACEMENT: INCONCLUSIVE")
        print()

        # Resume cache verdict
        if resume_status == "healthy":
            print(f"  ✓ RESUME CACHE: HEALTHY")
            cr = stats.get("resume", {}).get("cache_read", 0)
            ratio = stats.get("resume", {}).get("ratio")
            ratio_txt = f"{ratio:.1%}" if isinstance(ratio, float) else "n/a"
            print(f"    Resume cache_read={cr:,}, read_ratio={ratio_txt}")
        elif resume_status == "degraded":
            print(f"  ⚠ RESUME CACHE: DEGRADED (PARTIAL REUSE)")
            cr = stats.get("resume", {}).get("cache_read", 0)
            cc = stats.get("resume", {}).get("cache_creation", 0)
            ratio = stats.get("resume", {}).get("ratio")
            ratio_txt = f"{ratio:.1%}" if isinstance(ratio, float) else "n/a"
            print(f"    Resume cache_read={cr:,}, cache_creation={cc:,}, read_ratio={ratio_txt}")
            print(f"    Likely saving usage, but not at full efficiency.")
            print(f"    Issue reference: https://github.com/anthropics/claude-code/issues/34629")
        elif resume_status == "broken":
            print(f"  ✗ RESUME CACHE: BROKEN")
            cr = stats.get("resume", {}).get("cache_read", 0)
            cc = stats.get("resume", {}).get("cache_creation", 0)
            print(f"    Resume cache_read={cr:,}")
            print(f"    cache_creation={cc:,}")
            print(f"    Estimated excess on resume turn: ~${cc * 0.30 / 1e6:.4f}")
            print(f"    Issue: https://github.com/anthropics/claude-code/issues/34629")
        else:
            stage = stats.get("error_stage", "unknown")
            print(f"  ? RESUME CACHE: INCONCLUSIVE")
            print(f"    Test could not complete (stage: {stage}).")
            print(f"    Retry with a higher timeout, e.g. --timeout 240.")
        print()

        # Consecutive
        if stats.get("consecutive_grows"):
            print(f"  ✓ CONSECUTIVE RESUME: WORKING (cache grows between resumes)")
        elif "consecutive" in stats and not stats.get("consecutive", {}).get("api_error"):
            print(f"  ⚠ CONSECUTIVE RESUME: NOT GROWING")
        print()

        # Overall
        print(f"{'─' * 60}")
        bugs = (replaced is True) + (resume_status == "broken")
        inconclusive = (replaced is None) or (resume_status == "inconclusive")
        if bugs == 0:
            if inconclusive:
                print(f"  ? No confirmed cache bugs, but results are inconclusive")
            else:
                print(f"  ★ No known cache bugs detected")
        elif bugs == 1:
            print(f"  ⚠ 1 bug detected — see details above")
        else:
            print(f"  ✗ {bugs} bugs detected — see details above")
        print(f"{'─' * 60}")

        # Cleanup: remove session dirs created during test
        post_dirs = set(glob.glob(os.path.join(claude_projects, "-tmp-cc-cache-test-*")))
        new_dirs = post_dirs - pre_dirs
        for d in new_dirs:
            try:
                shutil.rmtree(d)
            except OSError:
                pass
        if new_dirs:
            print(f"\n  Cleaned up {len(new_dirs)} test session dir(s)")

        return 1 if bugs > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
