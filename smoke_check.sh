#!/usr/bin/env bash
set -euo pipefail

BASE="$(cd "$(dirname "$0")" && pwd)"
INSTALLER="$BASE/install.sh"
CLAUDE_CMD="claude-patched"
TIMEOUT="240"
RUN_INSTALLER="1"
RUN_TEST="1"

usage() {
  cat <<'EOF'
Usage: ./smoke_check.sh [options]

Options:
  --installer <path>   Installer script to run (default: ./install.sh)
  --cmd <command>      Claude command for test_cache.py (default: claude-patched)
  --timeout <seconds>  Timeout for test_cache.py (default: 240)
  --skip-install       Skip installer phase
  --skip-test          Skip test_cache.py phase
  -h, --help           Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --installer)
      INSTALLER="$2"
      shift 2
      ;;
    --cmd)
      CLAUDE_CMD="$2"
      shift 2
      ;;
    --timeout)
      TIMEOUT="$2"
      shift 2
      ;;
    --skip-install)
      RUN_INSTALLER="0"
      shift
      ;;
    --skip-test)
      RUN_TEST="0"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "$RUN_INSTALLER" == "1" && ! -f "$INSTALLER" ]]; then
  echo "Installer not found: $INSTALLER" >&2
  exit 2
fi

if ! [[ "$TIMEOUT" =~ ^[0-9]+$ ]] || [[ "$TIMEOUT" -lt 30 ]]; then
  echo "Timeout must be an integer >= 30" >&2
  exit 2
fi

mkdir -p "$BASE/results"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="$BASE/results/smoke_${STAMP}.txt"
touch "$REPORT"

echo "============================================================"
echo "  Claude Code Cache Fix Smoke Check"
echo "  installer: $INSTALLER"
echo "  command:   $CLAUDE_CMD"
echo "  timeout:   ${TIMEOUT}s"
echo "  report:    $REPORT"
echo "============================================================"

if [[ "$RUN_INSTALLER" == "1" ]]; then
  echo "[1/2] Running installer..."
  bash "$INSTALLER"
else
  echo "[1/2] Installer skipped"
fi

test_exit=0
if [[ "$RUN_TEST" == "1" ]]; then
  echo "[2/2] Running cache test..."
  set +e
  python3 "$BASE/test_cache.py" "$CLAUDE_CMD" --timeout "$TIMEOUT" --debug-transcript | tee "$REPORT"
  test_exit=${PIPESTATUS[0]}
  set -e
else
  echo "[2/2] Cache test skipped"
fi

sentinel_line="$(grep -E 'SENTINEL REPLACEMENT:' "$REPORT" | tail -1 || true)"
resume_line="$(grep -E 'RESUME CACHE:' "$REPORT" | head -1 || true)"
overall_line="$(grep -E '(No known cache bugs detected|bug detected|bugs detected|INCONCLUSIVE)' "$REPORT" | tail -1 || true)"

status="PASS"
if [[ "$RUN_TEST" != "1" ]]; then
  status="SKIPPED"
elif [[ $test_exit -ne 0 ]]; then
  status="FAIL"
fi

echo
echo "==================== SHAREABLE SUMMARY ======================"
echo "Smoke Check Status: $status"
if [[ -n "$sentinel_line" ]]; then
  echo "$sentinel_line"
fi
if [[ -n "$resume_line" ]]; then
  echo "$resume_line"
fi
if [[ -n "$overall_line" ]]; then
  echo "Overall: $overall_line"
fi
echo "Full report: $REPORT"
echo "============================================================="

if [[ "$status" == "FAIL" ]]; then
  exit 1
fi
