#!/usr/bin/env python3
"""
usage_audit.py — Inspect Claude transcript usage to estimate cache efficiency.

Examples:
  python3 usage_audit.py
  python3 usage_audit.py --top 12 --window 8
  python3 usage_audit.py --session 065f5aa7-53ff-48e2-a2a4-fd4d9924be52
  python3 usage_audit.py --include-subagents
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_TOP = 8
DEFAULT_WINDOW = 6


@dataclass
class TurnUsage:
    cache_read: int
    cache_creation: int
    input_tokens: int
    output_tokens: int

    @property
    def total_cached(self) -> int:
        return self.cache_read + self.cache_creation

    @property
    def read_ratio(self) -> float | None:
        if self.total_cached <= 0:
            return None
        return self.cache_read / self.total_cached


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit Claude transcript cache efficiency from local JSONL files."
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=f"Show N most recently modified sessions (default: {DEFAULT_TOP}).",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW,
        help=f"Rolling window size for ratio summary (default: {DEFAULT_WINDOW}).",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="Specific session_id to inspect.",
    )
    parser.add_argument(
        "--include-subagents",
        action="store_true",
        help="Include subagent transcripts.",
    )
    return parser.parse_args()


def find_transcripts(include_subagents: bool) -> list[str]:
    base = Path.home() / ".claude" / "projects"
    paths = glob.glob(str(base / "**" / "*.jsonl"), recursive=True)
    if not include_subagents:
        paths = [p for p in paths if "/subagents/" not in p]
    return sorted(paths, key=os.path.getmtime, reverse=True)


def read_usage(path: str) -> list[TurnUsage]:
    out: list[TurnUsage] = []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return out

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        usage = (obj.get("message") or {}).get("usage") or {}
        cr = int(usage.get("cache_read_input_tokens", 0) or 0)
        cc = int(usage.get("cache_creation_input_tokens", 0) or 0)
        inp = int(usage.get("input_tokens", 0) or 0)
        out_tokens = int(usage.get("output_tokens", 0) or 0)
        if cr == 0 and cc == 0 and inp == 0 and out_tokens == 0:
            continue
        out.append(TurnUsage(cr, cc, inp, out_tokens))
    return out


def mean_ratio(turns: list[TurnUsage]) -> float | None:
    numer = sum(t.cache_read for t in turns)
    denom = sum(t.total_cached for t in turns)
    if denom <= 0:
        return None
    return numer / denom


def classify(turns: list[TurnUsage]) -> str:
    if not turns:
        return "no-data"
    ratio = mean_ratio(turns)
    if ratio is None:
        return "no-data"
    if ratio >= 0.70:
        return "healthy"
    if ratio >= 0.40:
        return "mixed"
    return "poor"


def format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}"


def session_id_from_path(path: str) -> str:
    return Path(path).stem


def run() -> int:
    args = parse_args()
    paths = find_transcripts(args.include_subagents)
    if args.session:
        paths = [p for p in paths if Path(p).stem == args.session]

    if not paths:
        print("No transcript files found.")
        return 1

    shown = 0
    for path in paths:
        turns = read_usage(path)
        if not turns:
            continue

        last = turns[-1]
        window = turns[-args.window :]
        status = classify(window)
        last_ratio = last.read_ratio
        window_ratio = mean_ratio(window)

        sid = session_id_from_path(path)
        print(f"Session: {sid}")
        print(f"  file: {path}")
        print(f"  turns_with_usage: {len(turns)}")
        print(
            "  last_turn: "
            f"cache_read={last.cache_read:,} "
            f"cache_creation={last.cache_creation:,} "
            f"read_ratio={format_ratio(last_ratio)} "
            f"input={last.input_tokens:,} "
            f"output={last.output_tokens:,}"
        )
        print(
            f"  window({len(window)})_ratio={format_ratio(window_ratio)} "
            f"status={status}"
        )
        print()

        shown += 1
        if args.session is None and shown >= args.top:
            break

    if shown == 0:
        print("No assistant usage rows found in selected transcripts.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
