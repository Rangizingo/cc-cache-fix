#!/usr/bin/env bash
set -euo pipefail

BASE="$(cd "$(dirname "$0")" && pwd)"
CLI_JS="$BASE/node/node_modules/@anthropic-ai/claude-code/cli.js"
VERSION="2.1.81"

echo "=== Claude Code Cache Fix installer ==="
echo "Base: $BASE"

if ! command -v node >/dev/null 2>&1; then
    echo "[!] node not found. Install Node.js first."
    exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
    echo "[!] npm not found. Install Node.js/npm first."
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "[!] python3 not found. Install Python 3 first."
    exit 1
fi

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

# 6. Create wrapper
mkdir -p "$HOME/.local/bin"
WRAPPER="$HOME/.local/bin/claude-patched"
if [ -L "$WRAPPER" ] || [ -f "$WRAPPER" ]; then
    rm -f "$WRAPPER"
fi
cat > "$WRAPPER" << WRAPPER_EOF
#!/usr/bin/env bash
exec node "$CLI_JS" "\$@"
WRAPPER_EOF
chmod +x "$WRAPPER"
echo "[*] Wrote ~/.local/bin/claude-patched"

echo ""
echo "Done. Run 'claude-patched' to use the patched version."
echo "Stock 'claude' command is untouched."
