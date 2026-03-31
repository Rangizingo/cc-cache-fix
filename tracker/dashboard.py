"""
Claude Code Cache Fix — Efficiency Tracker Dashboard

Curses TUI that reads from cache_tracker.db and shows a live side-by-side
comparison of stock vs patched Claude Code session efficiency.

Run with: python3 tracker/dashboard.py
"""

import curses
import os
import sys
import time
from datetime import datetime
from typing import NamedTuple

# Allow importing db.py from the same directory as this script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from db import get_db
except ImportError:
    get_db = None  # Handled at render time


REFRESH_INTERVAL = 2  # seconds


class ModeStats(NamedTuple):
    sessions: int
    turns: int
    avg_cache_read: float
    avg_cache_creation: float
    cache_ratio: float  # percentage
    total_cost: float


class DashboardData(NamedTuple):
    stock: ModeStats | None
    patched: ModeStats | None
    recent_turns: list[dict]
    fetched_at: str


def _empty_stats() -> ModeStats:
    return ModeStats(
        sessions=0,
        turns=0,
        avg_cache_read=0.0,
        avg_cache_creation=0.0,
        cache_ratio=0.0,
        total_cost=0.0,
    )


def fetch_data() -> DashboardData:
    """Pull all needed stats from the database in one shot."""
    if get_db is None:
        return DashboardData(
            stock=None,
            patched=None,
            recent_turns=[],
            fetched_at=datetime.now().strftime("%H:%M:%S"),
        )

    try:
        db = get_db()
    except Exception:
        return DashboardData(
            stock=None,
            patched=None,
            recent_turns=[],
            fetched_at=datetime.now().strftime("%H:%M:%S"),
        )

    try:
        stats: dict[str, ModeStats | None] = {}

        for mode in ("stock", "patched"):
            row = db.execute(
                """
                SELECT
                    COUNT(DISTINCT s.session_id)          AS session_count,
                    COUNT(t.id)                           AS turn_count,
                    AVG(t.cache_read_input_tokens)        AS avg_cr,
                    AVG(t.cache_creation_input_tokens)    AS avg_cc,
                    AVG(t.input_tokens)                   AS avg_input,
                    SUM(t.cost_estimate)                  AS total_cost
                FROM sessions s
                LEFT JOIN turns t ON t.session_id = s.session_id
                WHERE s.mode = ?
                """,
                (mode,),
            ).fetchone()

            if row is None or row[1] == 0:
                stats[mode] = None
                continue

            avg_cr = row[2] or 0.0
            avg_cc = row[3] or 0.0
            avg_input = row[4] or 0.0
            denom = avg_cr + avg_cc + avg_input
            ratio = (avg_cr / denom * 100) if denom > 0 else 0.0

            stats[mode] = ModeStats(
                sessions=row[0],
                turns=row[1],
                avg_cache_read=avg_cr,
                avg_cache_creation=avg_cc,
                cache_ratio=ratio,
                total_cost=row[5] or 0.0,
            )

        recent_rows = db.execute(
            """
            SELECT t.timestamp, s.mode,
                   t.cache_read_input_tokens,
                   t.cache_creation_input_tokens,
                   t.cost_estimate
            FROM turns t
            JOIN sessions s ON s.session_id = t.session_id
            ORDER BY t.timestamp DESC
            LIMIT 10
            """,
        ).fetchall()

        recent_turns = [
            {
                "timestamp": r[0],
                "mode": r[1],
                "cache_read": r[2] or 0,
                "cache_creation": r[3] or 0,
                "cost": r[4] or 0.0,
            }
            for r in recent_rows
        ]

        return DashboardData(
            stock=stats.get("stock"),
            patched=stats.get("patched"),
            recent_turns=recent_turns,
            fetched_at=datetime.now().strftime("%H:%M:%S"),
        )

    finally:
        db.close()


def _fmt_num(val: float) -> str:
    """Format a large float as a comma-separated integer string."""
    return f"{int(val):,}"


def _fmt_cost(val: float) -> str:
    return f"${val:.2f}"


def draw(stdscr: "curses.window", data: DashboardData) -> None:
    """Render the full dashboard. Called after every data refresh or resize."""
    stdscr.erase()
    height, width = stdscr.getmaxyx()

    # --- Color pairs ---
    # 1 = header (blue bg)
    # 2 = green (patched better)
    # 3 = red (patched worse)
    # 4 = footer bar
    # 5 = dim label
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(5, curses.COLOR_CYAN, curses.COLOR_BLACK)

    H_PAIR = curses.color_pair(1) | curses.A_BOLD
    G_PAIR = curses.color_pair(2) | curses.A_BOLD
    R_PAIR = curses.color_pair(3) | curses.A_BOLD
    F_PAIR = curses.color_pair(4)
    L_PAIR = curses.color_pair(5)

    MIN_WIDTH = 62
    MIN_HEIGHT = 24

    if width < MIN_WIDTH or height < MIN_HEIGHT:
        msg = f"Terminal too small ({width}x{height}). Need {MIN_WIDTH}x{MIN_HEIGHT}."
        if height > 0 and width > len(msg):
            stdscr.addstr(0, 0, msg[:width])
        stdscr.refresh()
        return

    # Clamp box width to terminal; leave 1 col margin each side
    box_w = min(64, width - 2)
    col = max(0, (width - box_w) // 2)  # center horizontally

    def safe_addstr(row: int, c: int, text: str, attr: int = 0) -> None:
        """Write text, clipping to terminal boundaries silently."""
        if row < 0 or row >= height - 1:
            return
        max_len = width - c
        if max_len <= 0:
            return
        try:
            stdscr.addstr(row, c, text[:max_len], attr)
        except curses.error:
            pass

    def hline(row: int, left: str, fill: str, right: str) -> None:
        inner = fill * (box_w - 2)
        safe_addstr(row, col, f"{left}{inner}{right}")

    def row_text(row: int, text: str, attr: int = 0) -> None:
        """Print a line inside the box borders."""
        inner_w = box_w - 2
        content = text.ljust(inner_w)[:inner_w]
        safe_addstr(row, col, "║", attr)
        safe_addstr(row, col + 1, content, attr)
        safe_addstr(row, col + box_w - 1, "║")

    def row_centered(row: int, text: str, attr: int = 0) -> None:
        inner_w = box_w - 2
        padded = text.center(inner_w)
        safe_addstr(row, col, "║")
        safe_addstr(row, col + 1, padded, attr)
        safe_addstr(row, col + box_w - 1, "║")

    r = 0  # current row cursor

    # Top border
    hline(r, "╔", "═", "╗")
    r += 1

    # Title
    row_centered(r, "Claude Code Cache Fix — Efficiency Tracker", H_PAIR)
    r += 1

    hline(r, "╠", "═", "╣")
    r += 1

    row_text(r, "")
    r += 1

    # Column headers
    row_text(r, f"  {'STOCK':<30}{'PATCHED'}")
    r += 1
    row_text(r, f"  {'─────':<30}{'───────'}")
    r += 1

    stock = data.stock
    patched = data.patched
    no_stock = stock is None
    no_patched = patched is None

    def stat_row(
        label: str,
        s_val: str,
        p_val: str,
        p_better: bool | None = None,
    ) -> None:
        nonlocal r
        left_col = f"  {label:<16}{s_val:<14}"
        # Color patched value based on comparison result
        if p_better is True:
            p_attr = G_PAIR
        elif p_better is False:
            p_attr = R_PAIR
        else:
            p_attr = 0

        line = left_col + p_val
        inner_w = box_w - 2
        # Write the line in two parts: plain left, colored right
        safe_addstr(r, col, "║")
        safe_addstr(r, col + 1, line[:inner_w].ljust(inner_w))
        # Overlay colored patched value
        p_start = col + 1 + len(left_col)
        if p_start < col + box_w - 1:
            safe_addstr(r, p_start, p_val[: col + box_w - 1 - p_start], p_attr)
        safe_addstr(r, col + box_w - 1, "║")
        r += 1

    # Sessions / turns
    s_sessions = str(stock.sessions) if not no_stock else "—"
    p_sessions = str(patched.sessions) if not no_patched else "—"
    stat_row("Sessions:", s_sessions, p_sessions)

    s_turns = str(stock.turns) if not no_stock else "—"
    p_turns = str(patched.turns) if not no_patched else "—"
    stat_row("Turns:", s_turns, p_turns)

    row_text(r, "")
    r += 1

    # Cache read avg
    s_cr = _fmt_num(stock.avg_cache_read) + " avg" if not no_stock else "—"
    p_cr = _fmt_num(patched.avg_cache_read) + " avg" if not no_patched else "—"
    p_cr_better = (
        (patched.avg_cache_read > stock.avg_cache_read)
        if (not no_stock and not no_patched)
        else None
    )
    stat_row("Cache Read:", s_cr, p_cr, p_cr_better)

    # Cache creation avg
    s_cc = _fmt_num(stock.avg_cache_creation) + " avg" if not no_stock else "—"
    p_cc = _fmt_num(patched.avg_cache_creation) + " avg" if not no_patched else "—"
    # Lower creation = better (fewer cache misses)
    p_cc_better = (
        (patched.avg_cache_creation < stock.avg_cache_creation)
        if (not no_stock and not no_patched)
        else None
    )
    stat_row("Cache Create:", s_cc, p_cc, p_cc_better)

    # Cache ratio
    s_ratio = f"{stock.cache_ratio:.1f}%" if not no_stock else "—"
    p_ratio = f"{patched.cache_ratio:.1f}%" if not no_patched else "—"
    p_ratio_better = (
        (patched.cache_ratio > stock.cache_ratio)
        if (not no_stock and not no_patched)
        else None
    )
    stat_row("Cache Ratio:", s_ratio, p_ratio, p_ratio_better)

    row_text(r, "")
    r += 1

    # Cost
    s_cost = _fmt_cost(stock.total_cost) if not no_stock else "—"
    p_cost = _fmt_cost(patched.total_cost) if not no_patched else "—"
    # Lower cost = better
    p_cost_better = (
        (patched.total_cost < stock.total_cost)
        if (not no_stock and not no_patched)
        else None
    )
    stat_row("Est. Cost:", s_cost, p_cost, p_cost_better)

    row_text(r, "")
    r += 1

    # Savings section
    inner_w = box_w - 2
    divider = "─" * (inner_w - 4)
    row_text(r, f"  {divider}")
    r += 1

    if not no_stock and not no_patched:
        savings = stock.total_cost - patched.total_cost
        if stock.total_cost > 0:
            pct = abs(savings) / stock.total_cost * 100
        else:
            pct = 0.0

        if savings > 0:
            savings_text = f"SAVINGS: {_fmt_cost(savings)} ({pct:.1f}% reduction)"
            savings_attr = G_PAIR
        elif savings < 0:
            savings_text = f"OVERSPEND: {_fmt_cost(abs(savings))} ({pct:.1f}% increase)"
            savings_attr = R_PAIR
        else:
            savings_text = "SAVINGS: $0.00 (no difference)"
            savings_attr = 0

        # Write savings line with color
        content = f"  {savings_text}"
        safe_addstr(r, col, "║")
        safe_addstr(r, col + 1, content[:inner_w].ljust(inner_w), savings_attr)
        safe_addstr(r, col + box_w - 1, "║")
        r += 1
    else:
        row_text(r, "  SAVINGS: insufficient data for comparison")
        r += 1

    row_text(r, f"  {divider}")
    r += 1

    row_text(r, "")
    r += 1

    # Recent turns
    row_text(r, "  Recent turns (last 10):", L_PAIR)
    r += 1

    if data.recent_turns:
        for turn in data.recent_turns:
            # Parse ISO timestamp down to HH:MM:SS if possible
            ts = turn["timestamp"] or ""
            try:
                ts = datetime.fromisoformat(ts).strftime("%H:%M:%S")
            except (ValueError, TypeError):
                ts = ts[:8] if ts else "?"

            mode_tag = f"[{turn['mode'][:7]:<7}]"
            cr = _fmt_num(turn["cache_read"])
            cc = _fmt_num(turn["cache_creation"])
            cost_str = f"${turn['cost']:.4f}"
            line = f"  {ts} {mode_tag} CR:{cr} CC:{cc} {cost_str}"
            row_text(r, line)
            r += 1
    else:
        row_text(r, "  No data yet.")
        r += 1

    row_text(r, "")
    r += 1

    # Bottom border
    hline(r, "╠", "═", "╣")
    r += 1

    # Footer
    footer = f"  q: quit  r: refresh  Last update: {data.fetched_at}"
    safe_addstr(r, col, "║")
    safe_addstr(r, col + 1, footer[: inner_w].ljust(inner_w), F_PAIR)
    safe_addstr(r, col + box_w - 1, "║", F_PAIR)
    r += 1

    hline(r, "╚", "═", "╝")

    stdscr.refresh()


def run(stdscr: "curses.window") -> None:
    """Main loop: fetch data, draw, handle input, refresh on timer."""
    curses.curs_set(0)
    stdscr.nodelay(True)  # non-blocking getch
    curses.start_color()
    curses.use_default_colors()

    last_refresh = 0.0
    data: DashboardData | None = None

    while True:
        now = time.monotonic()

        # Fetch fresh data on startup and every REFRESH_INTERVAL seconds
        if data is None or (now - last_refresh) >= REFRESH_INTERVAL:
            data = fetch_data()
            last_refresh = now
            draw(stdscr, data)

        # Input handling (non-blocking)
        try:
            key = stdscr.getch()
        except curses.error:
            key = -1

        if key in (ord("q"), ord("Q")):
            break
        elif key in (ord("r"), ord("R")):
            data = fetch_data()
            last_refresh = now
            draw(stdscr, data)
        elif key == curses.KEY_RESIZE:
            # Terminal was resized; redraw immediately
            curses.update_lines_cols()
            draw(stdscr, data)

        time.sleep(0.05)  # ~20 Hz input poll, keeps CPU near zero


def main() -> None:
    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
