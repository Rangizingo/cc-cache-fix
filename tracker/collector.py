"""
Background JSONL watcher for Claude Code session files.

Polls ~/.claude/projects/*/*.jsonl every 5 seconds, extracts token
usage from assistant messages, and writes results to SQLite via db.py.

Usage:
    python3 tracker/collector.py
    python3 tracker/collector.py --db /path/to/custom.db

Ctrl+C to stop.
"""

import argparse
import json
import signal
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import get_db, insert_turn, upsert_session

# How often to scan for new JSONL content
_POLL_INTERVAL_SECONDS = 5

# How often to print the status summary
_STATUS_INTERVAL_SECONDS = 30

# Markers that indicate the session is running under the patched binary
_PATCHED_MARKERS = ("CC_CACHE_FIX_MODE", "claude-patched")

_PROJECTS_ROOT = Path.home() / ".claude" / "projects"


def _detect_mode(raw_line: str) -> str:
    """Check a raw JSONL line for patched-binary markers.

    Args:
        raw_line: The raw string content of one JSONL line.

    Returns:
        'patched' if a marker is found, otherwise 'unknown' (caller aggregates).
    """
    for marker in _PATCHED_MARKERS:
        if marker in raw_line:
            return "patched"
    return "unknown"


def _extract_usage(obj: dict[str, Any]) -> dict[str, int] | None:
    """Pull token counts out of an assistant message object.

    Args:
        obj: Parsed JSON dict for a single JSONL line.

    Returns:
        Dict with cache_read, cache_creation, input_tokens, output_tokens,
        or None if the line isn't a usable assistant message.
    """
    if obj.get("type") != "assistant":
        return None

    # usage lives at the top level or inside message.usage depending on CC version
    usage: dict[str, Any] | None = obj.get("usage") or (
        obj.get("message", {}) or {}
    ).get("usage")

    if not usage:
        return None

    return {
        "cache_read": int(usage.get("cache_read_input_tokens") or 0),
        "cache_creation": int(usage.get("cache_creation_input_tokens") or 0),
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
    }


def _extract_timestamp(obj: dict[str, Any]) -> str:
    """Return the line's timestamp, or now() if absent."""
    ts = obj.get("timestamp") or obj.get("ts")
    if ts:
        return str(ts)
    return datetime.now(timezone.utc).isoformat()


class Collector:
    """Watches JSONL session files and feeds data into SQLite."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.conn = get_db(db_path)

        # file_path -> byte offset of last read position
        self._file_positions: dict[Path, int] = {}

        # session_id -> number of assistant turns seen so far
        self._turn_counts: defaultdict[str, int] = defaultdict(int)

        # session_id -> detected mode ('patched' | 'unknown')
        # Once a session is tagged 'patched' it stays that way
        self._session_modes: dict[str, str] = {}

        self._sessions_seen: set[str] = set()
        self._last_activity: str = "none"
        self._running = True

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start polling. Blocks until SIGINT."""
        signal.signal(signal.SIGINT, self._handle_sigint)
        signal.signal(signal.SIGTERM, self._handle_sigint)

        print(f"[collector] watching {_PROJECTS_ROOT}")
        print(f"[collector] polling every {_POLL_INTERVAL_SECONDS}s  |  status every {_STATUS_INTERVAL_SECONDS}s")
        print("[collector] Ctrl+C to stop\n")

        last_status_time = time.monotonic()

        while self._running:
            self._poll_once()

            now = time.monotonic()
            if now - last_status_time >= _STATUS_INTERVAL_SECONDS:
                self._print_status()
                last_status_time = now

            # Sleep in small increments so SIGINT is responsive
            for _ in range(_POLL_INTERVAL_SECONDS * 10):
                if not self._running:
                    break
                time.sleep(0.1)

        print("\n[collector] shutting down")
        self.conn.close()

    # ------------------------------------------------------------------
    # Per-poll logic
    # ------------------------------------------------------------------

    def _poll_once(self) -> None:
        """Scan all known JSONL files for new lines."""
        if not _PROJECTS_ROOT.exists():
            return

        for jsonl_file in _PROJECTS_ROOT.glob("*/*.jsonl"):
            self._process_file(jsonl_file)

    def _process_file(self, path: Path) -> None:
        """Read new lines from a JSONL file starting at the tracked offset.

        Args:
            path: Path to the .jsonl session file.
        """
        try:
            file_size = path.stat().st_size
        except OSError:
            return

        offset = self._file_positions.get(path, 0)

        # File was rotated / truncated — reset
        if file_size < offset:
            offset = 0

        if file_size == offset:
            return  # nothing new

        try:
            with path.open("rb") as fh:
                fh.seek(offset)
                new_bytes = fh.read()
        except OSError:
            return

        self._file_positions[path] = offset + len(new_bytes)

        for raw_line in new_bytes.decode("utf-8", errors="replace").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            self._process_line(raw_line)

    def _process_line(self, raw_line: str) -> None:
        """Parse one JSONL line and persist if it's a usable assistant turn.

        Args:
            raw_line: Raw string content of a single JSONL line.
        """
        try:
            obj: dict[str, Any] = json.loads(raw_line)
        except json.JSONDecodeError:
            return

        session_id: str | None = obj.get("sessionId") or obj.get("session_id")
        if not session_id:
            return

        # Update mode detection for this session
        line_mode = _detect_mode(raw_line)
        current_mode = self._session_modes.get(session_id, "unknown")
        if line_mode == "patched" or current_mode == "unknown":
            self._session_modes[session_id] = line_mode

        # Ensure session row exists
        if session_id not in self._sessions_seen:
            upsert_session(
                self.conn,
                session_id,
                mode=self._session_modes[session_id],
                start_time=_extract_timestamp(obj),
            )
            self._sessions_seen.add(session_id)
        else:
            # Refresh mode if it changed to 'patched'
            final_mode = self._session_modes[session_id]
            if final_mode == "patched":
                upsert_session(self.conn, session_id, mode="patched")

        usage = _extract_usage(obj)
        if usage is None:
            return

        self._turn_counts[session_id] += 1
        turn_number = self._turn_counts[session_id]
        timestamp = _extract_timestamp(obj)

        insert_turn(
            conn=self.conn,
            session_id=session_id,
            turn_number=turn_number,
            timestamp=timestamp,
            cache_read=usage["cache_read"],
            cache_creation=usage["cache_creation"],
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
        )

        self._last_activity = f"{session_id[:8]}… turn {turn_number} @ {timestamp}"

    # ------------------------------------------------------------------
    # Status + shutdown
    # ------------------------------------------------------------------

    def _print_status(self) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(
            f"[{ts}] sessions tracked: {len(self._sessions_seen)}"
            f"  |  last: {self._last_activity}"
        )

    def _handle_sigint(self, signum: int, frame: object) -> None:
        print("\n[collector] caught signal, stopping after current poll…")
        self._running = False


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cache efficiency collector for Claude Code sessions"
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=None,
        help="Path to SQLite database (default: tracker/cache_tracker.db)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    collector = Collector(db_path=args.db)
    collector.run()
