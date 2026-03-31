#!/usr/bin/env bash
set -euo pipefail

# Claude Code Cache Fix Installer
# Patches cli.js to fix prompt caching bugs that drain Max plan usage.
# Safe to run multiple times. Stock 'claude' is never touched.

VERSION="2.1.81"
BASE="$HOME/cc-cache-fix"

echo "========================================"
echo "  Claude Code Cache Fix Installer"
echo "  Target: v${VERSION}"
echo "========================================"
echo ""

# Check for Node.js
if ! command -v node &>/dev/null; then
    echo "[!] Node.js not found."
    if command -v brew &>/dev/null; then
        echo "[*] Installing via Homebrew..."
        brew install node
    else
        echo "    Install Node.js first: https://nodejs.org or 'brew install node'"
        echo "    Press any key to exit."
        read -n1
        exit 1
    fi
fi
echo "[*] Node.js: $(node --version)"

# Check for npm
if ! command -v npm &>/dev/null; then
    echo "[!] npm not found. Install Node.js properly."
    echo "    Press any key to exit."
    read -n1
    exit 1
fi

# Create project dir
mkdir -p "$BASE"
cd "$BASE"

# Install npm package
CLI="$BASE/node_modules/@anthropic-ai/claude-code/cli.js"
if [ ! -f "$CLI" ]; then
    echo "[*] Installing @anthropic-ai/claude-code@${VERSION}..."
    npm install "@anthropic-ai/claude-code@${VERSION}"
else
    echo "[*] cli.js already installed"
fi

# Backup
if [ ! -f "$CLI.orig" ]; then
    echo "[*] Backing up cli.js"
    cp "$CLI" "$CLI.orig"
else
    echo "[*] Backup exists"
fi

# Restore from backup (idempotent)
echo "[*] Restoring from backup..."
cp "$CLI.orig" "$CLI"

# Apply patches
echo "[*] Applying patches..."
python3 -c "
import sys
path = '$CLI'
with open(path) as f: src = f.read()

# Patch 1: fix db8 attachment filter (resume cache regression)
old1 = 'if(A.attachment.type==\"hook_additional_context\"&&a6(process.env.CLAUDE_CODE_SAVE_HOOK_ADDITIONAL_CONTEXT))return!0;return!1}'
new1 = old1.replace('return!1}',
    'if(A.attachment.type==\"deferred_tools_delta\")return!0;'
    'if(A.attachment.type==\"mcp_instructions_delta\")return!0;'
    'return!1}')
if old1 not in src:
    print('[!] Patch 1 FAILED: db8 pattern not found. Wrong version?')
    sys.exit(1)
src = src.replace(old1, new1, 1)
print('[*] Patch 1 (db8 cache fix): applied')

# Patch 2: force 1h cache TTL
old2 = 'function sjY(A){if(QA()===\"bedrock\"'
new2 = 'function sjY(A){return!0;if(QA()===\"bedrock\"'
if old2 in src:
    src = src.replace(old2, new2, 1)
    print('[*] Patch 2 (1h cache TTL): applied')
else:
    print('[*] Patch 2: sjY not found, skipping (non-critical)')

with open(path, 'w') as f: f.write(src)

# Verify
with open(path) as f: check = f.read()
if 'deferred_tools_delta' not in check:
    print('[!] Verification FAILED')
    sys.exit(1)
print('[*] Verification: patches confirmed')
"

# Verify it runs
PATCHED_VERSION=$(node "$CLI" --version 2>/dev/null || echo "FAILED")
echo "[*] Patched version: $PATCHED_VERSION"

if [[ "$PATCHED_VERSION" != *"$VERSION"* ]]; then
    echo "[!] Version check failed. Restoring backup."
    cp "$CLI.orig" "$CLI"
    echo "    Press any key to exit."
    read -n1
    exit 1
fi

# Create wrapper
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/claude-patched" << WRAPPER
#!/usr/bin/env bash
exec node "$BASE/node_modules/@anthropic-ai/claude-code/cli.js" "\$@"
WRAPPER
chmod +x "$HOME/.local/bin/claude-patched"
echo "[*] Created ~/.local/bin/claude-patched"

# Ensure PATH includes ~/.local/bin
SHELL_RC=""
if [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -f "$HOME/.bash_profile" ]; then
    SHELL_RC="$HOME/.bash_profile"
fi

if [ -n "$SHELL_RC" ]; then
    if ! grep -q '.local/bin' "$SHELL_RC" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
        echo "[*] Added ~/.local/bin to PATH in $(basename "$SHELL_RC")"
    fi
fi

echo ""
echo "========================================"
echo "  Done!"
echo ""
echo "  Open a new terminal and run:"
echo "    claude-patched"
echo ""
echo "  All flags work as normal:"
echo "    claude-patched --dangerously-skip-permissions"
echo "    claude-patched --resume <session-id>"
echo ""
echo "  Stock 'claude' command is untouched."
echo "========================================"
echo ""
echo "Press any key to close."
read -n1
