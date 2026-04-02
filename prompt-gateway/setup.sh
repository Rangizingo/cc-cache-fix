#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  prompt-gateway setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

# Check node
if ! command -v node &>/dev/null; then
  echo "✗ Node.js not found. Install Node 20+ first."
  exit 1
fi

NODE_VERSION=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_VERSION" -lt 20 ]; then
  echo "✗ Node $NODE_VERSION found, need 20+."
  exit 1
fi
echo "✓ Node $(node -v)"

# Install deps
echo "  Installing dependencies..."
npm install --silent 2>/dev/null
echo "✓ Dependencies installed"

# Build
echo "  Building bundles..."
node esbuild.config.mjs
echo "✓ Built"

# Create symlinks in a bin dir
mkdir -p "$SCRIPT_DIR/bin"

cat > "$SCRIPT_DIR/bin/agent" << 'SHIM'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec node "$SCRIPT_DIR/dist/agent.mjs" "$@"
SHIM
chmod +x "$SCRIPT_DIR/bin/agent"

cat > "$SCRIPT_DIR/bin/prompt-gateway" << 'SHIM'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec node "$SCRIPT_DIR/dist/prompt-gateway.mjs" "$@"
SHIM
chmod +x "$SCRIPT_DIR/bin/prompt-gateway"

echo "✓ CLI shims created in bin/"
echo

# Shell integration hint
AGENT_PATH="$SCRIPT_DIR/bin"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Done! Add to your PATH:"
echo
echo "    export PATH=\"$AGENT_PATH:\$PATH\""
echo
echo "  Then use:"
echo
echo "    agent \"fix the auth race and keep changes minimal\""
echo "    agent --json \"add a health endpoint\""
echo "    prompt-gateway --http           # start HTTP daemon"
echo "    prompt-gateway --mcp            # start MCP server"
echo
echo "  MCP integration (Cursor / Claude Desktop):"
echo
echo "    prompt-gateway --mcp-config     # print config snippet"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
