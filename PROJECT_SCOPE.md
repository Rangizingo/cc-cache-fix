# PROJECT_SCOPE

## Scope 1: Public Patch Toolkit Hardening

### 1.1 Documentation Baseline
- Status: Complete
- Goal: Add root `README.md` with Linux/macOS install + verify commands.
- Outcome: Completed.

### 1.2 Durable Task Tracking
- Status: Complete
- Goal: Add project scope tracking file for future incremental work.
- Outcome: Completed with this file.

### 1.3 One-Command Smoke Validation
- Status: Complete
- Goal: Add a script that runs installer + `test_cache.py` and prints a shareable pass/fail summary.
- Outcome: Completed via `smoke_check.sh`.

## Next Candidate Work

### 2.1 CI Smoke Job (Optional)
- Status: Pending
- Goal: Add a manual GitHub Action that runs lint/syntax checks only (no live API calls).

### 2.2 Version Drift Guard (Optional)
- Status: Pending
- Goal: Add a quick check that warns when upstream Claude Code version changes and patch patterns may need updates.
