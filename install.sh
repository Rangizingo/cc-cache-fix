#!/usr/bin/env bash
set -euo pipefail

BASE="$(cd "$(dirname "$0")" && pwd)"
CLI_JS="$BASE/node/node_modules/@anthropic-ai/claude-code/cli.js"
VERSION="2.1.81"

echo "=== Claude Code Cache Fix installer ==="
echo "Base: $BASE"

# 1. npm install if needed
if [ ! -f "$CLI_JS" ]; then
    echo "[*] Installing @anthropic-ai/claude-code@$VERSION..."
    npm install --prefix "$BASE/node" "@anthropic-ai/claude-code@$VERSION"
else
    echo "[*] cli.js already installed"
fi

# 2. Backup if needed
if [ ! -f "$CLI_JS.orig" ]; then
    echo "[*] Backing up cli.js -> cli.js.orig"
    cp "$CLI_JS" "$CLI_JS.orig"
else
    echo "[*] Backup already exists"
fi

# 3. Restore from backup before patching (idempotent)
echo "[*] Restoring from backup..."
cp "$CLI_JS.orig" "$CLI_JS"

# 4. Apply patches
echo "[*] Applying patches..."
python3 "$BASE/patches/apply-patches.py" "$CLI_JS"

# 5. Verify
PATCHED_VERSION=$(node "$CLI_JS" --version 2>/dev/null || echo "FAILED")
echo "[*] Patched version: $PATCHED_VERSION"

if [ "$PATCHED_VERSION" != "$VERSION (Claude Code)" ]; then
    echo "[!] Version mismatch after patching. Restoring backup."
    cp "$CLI_JS.orig" "$CLI_JS"
    exit 1
fi

# 6. Link wrapper
WRAPPER="$BASE/bin/claude-patched"
chmod +x "$WRAPPER"
if [ ! -L "$HOME/.local/bin/claude-patched" ]; then
    ln -s "$WRAPPER" "$HOME/.local/bin/claude-patched"
    echo "[*] Linked claude-patched -> ~/.local/bin/"
else
    echo "[*] claude-patched symlink already exists"
fi

echo ""
echo "Done. Run 'claude-patched' to use the patched version."
echo "Stock 'claude' command is untouched."
