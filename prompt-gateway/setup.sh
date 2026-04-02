#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GATEWAY_BIN="$SCRIPT_DIR/dist/prompt-gateway.mjs"
AGENT_BIN="$SCRIPT_DIR/dist/agent.mjs"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  prompt-gateway setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

# ── Check node ──────────────────────────────────────
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

# ── Install deps ────────────────────────────────────
echo "  Installing dependencies..."
npm install --silent 2>/dev/null
echo "✓ Dependencies installed"

# ── Build ───────────────────────────────────────────
echo "  Building bundles..."
node esbuild.config.mjs
echo "✓ Built"

# ── CLI shims ───────────────────────────────────────
mkdir -p "$SCRIPT_DIR/bin"

cat > "$SCRIPT_DIR/bin/agent" << SHIM
#!/usr/bin/env bash
exec node "$AGENT_BIN" "\$@"
SHIM
chmod +x "$SCRIPT_DIR/bin/agent"

cat > "$SCRIPT_DIR/bin/prompt-gateway" << SHIM
#!/usr/bin/env bash
exec node "$GATEWAY_BIN" "\$@"
SHIM
chmod +x "$SCRIPT_DIR/bin/prompt-gateway"

echo "✓ CLI shims created"

# ── Auto-configure MCP clients ─────────────────────

NODE_BIN="$(which node)"
MCP_ENTRY='{"command":"'"$NODE_BIN"'","args":["'"$GATEWAY_BIN"'","--mcp"]}'

# Helper: merge prompt-gateway into an MCP config JSON file.
# Creates the file if it doesn't exist. Preserves existing servers.
configure_mcp_file() {
  local file="$1"
  local label="$2"
  local wrapper_key="${3:-}"  # optional top-level key (e.g. "mcpServers" vs nested)

  mkdir -p "$(dirname "$file")"

  if [ ! -f "$file" ]; then
    # Create fresh
    if [ -n "$wrapper_key" ]; then
      echo "{\"$wrapper_key\":{\"prompt-gateway\":$MCP_ENTRY}}" | node -e "
        process.stdin.setEncoding('utf8');
        let d=''; process.stdin.on('data',c=>d+=c);
        process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(d),null,2)+'\n'));
      " > "$file"
    else
      echo "{\"prompt-gateway\":$MCP_ENTRY}" | node -e "
        process.stdin.setEncoding('utf8');
        let d=''; process.stdin.on('data',c=>d+=c);
        process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(d),null,2)+'\n'));
      " > "$file"
    fi
    echo "✓ $label — created $file"
    return
  fi

  # File exists — merge without clobbering
  local tmp="${file}.tmp.$$"
  local merge_result
  merge_result=$(node -e "
    const fs = require('fs');
    const cfg = JSON.parse(fs.readFileSync('$file','utf8'));
    const entry = $MCP_ENTRY;
    const key = '$wrapper_key';
    if (key) {
      if (!cfg[key]) cfg[key] = {};
      if (cfg[key]['prompt-gateway']) { process.exit(0); }
      cfg[key]['prompt-gateway'] = entry;
    } else {
      if (cfg['prompt-gateway']) { process.exit(0); }
      cfg['prompt-gateway'] = entry;
    }
    fs.writeFileSync('$tmp', JSON.stringify(cfg, null, 2) + '\n');
    process.stdout.write('wrote');
  " 2>/dev/null) || true

  if [ -f "$tmp" ]; then
    mv "$tmp" "$file"
    echo "✓ $label — updated $file"
  else
    echo "✓ $label — already configured"
  fi
}

echo
echo "  Configuring MCP clients..."

CONFIGURED=0

# ── Cursor ──────────────────────────────────────────
# Global: ~/.cursor/mcp.json
CURSOR_GLOBAL="$HOME/.cursor/mcp.json"
configure_mcp_file "$CURSOR_GLOBAL" "Cursor (global)" "mcpServers"
CONFIGURED=$((CONFIGURED + 1))

# ── Claude Desktop ──────────────────────────────────
if [ "$(uname)" = "Darwin" ]; then
  CLAUDE_DESKTOP="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
else
  # Linux (XDG)
  CLAUDE_DESKTOP="${XDG_CONFIG_HOME:-$HOME/.config}/Claude/claude_desktop_config.json"
fi
configure_mcp_file "$CLAUDE_DESKTOP" "Claude Desktop" "mcpServers"
CONFIGURED=$((CONFIGURED + 1))

# ── Claude Code ─────────────────────────────────────
CLAUDE_CODE="$HOME/.claude/settings.json"
if [ -f "$CLAUDE_CODE" ]; then
  RESULT=$(node -e "
    const fs = require('fs');
    const cfg = JSON.parse(fs.readFileSync('$CLAUDE_CODE','utf8'));
    if (!cfg.mcpServers) cfg.mcpServers = {};
    if (cfg.mcpServers['prompt-gateway']) { process.exit(0); }
    cfg.mcpServers['prompt-gateway'] = $MCP_ENTRY;
    fs.writeFileSync('$CLAUDE_CODE', JSON.stringify(cfg, null, 2) + '\n');
    process.stdout.write('wrote');
  " 2>/dev/null)
  if [ "$RESULT" = "wrote" ]; then
    echo "✓ Claude Code — updated $CLAUDE_CODE"
  else
    echo "✓ Claude Code — already configured"
  fi
  CONFIGURED=$((CONFIGURED + 1))
else
  configure_mcp_file "$CLAUDE_CODE" "Claude Code" "mcpServers"
  CONFIGURED=$((CONFIGURED + 1))
fi

# ── VS Code (Copilot MCP) ──────────────────────────
VSCODE_SETTINGS="$HOME/.vscode/settings.json"
if [ -d "$HOME/.vscode" ] || command -v code &>/dev/null; then
  if [ ! -f "$VSCODE_SETTINGS" ]; then
    mkdir -p "$HOME/.vscode"
    echo '{}' > "$VSCODE_SETTINGS"
  fi
  VS_RESULT=$(node -e "
    const fs = require('fs');
    const cfg = JSON.parse(fs.readFileSync('$VSCODE_SETTINGS','utf8'));
    const key = 'mcp.servers';
    if (!cfg[key]) cfg[key] = {};
    if (cfg[key]['prompt-gateway']) { process.exit(0); }
    cfg[key]['prompt-gateway'] = { command: '$NODE_BIN', args: ['$GATEWAY_BIN', '--mcp'] };
    fs.writeFileSync('$VSCODE_SETTINGS', JSON.stringify(cfg, null, 2) + '\n');
    process.stdout.write('wrote');
  " 2>/dev/null)
  if [ "$VS_RESULT" = "wrote" ]; then
    echo "✓ VS Code — updated $VSCODE_SETTINGS"
  else
    echo "✓ VS Code — already configured"
  fi
  CONFIGURED=$((CONFIGURED + 1))
fi

# ── Windsurf ────────────────────────────────────────
if [ -d "$HOME/.windsurf" ]; then
  WINDSURF_CONFIG="$HOME/.windsurf/mcp.json"
  configure_mcp_file "$WINDSURF_CONFIG" "Windsurf" "mcpServers"
  CONFIGURED=$((CONFIGURED + 1))
fi

# ── JetBrains IDEs ─────────────────────────────────
JB_CONFIG_BASE=""
if [ "$(uname)" = "Darwin" ]; then
  JB_CONFIG_BASE="$HOME/Library/Application Support/JetBrains"
else
  JB_CONFIG_BASE="${XDG_CONFIG_HOME:-$HOME/.config}/JetBrains"
fi
if [ -d "$JB_CONFIG_BASE" ]; then
  # Find the most recent IDE config
  JB_LATEST=$(ls -dt "$JB_CONFIG_BASE"/*/ 2>/dev/null | head -1)
  if [ -n "$JB_LATEST" ]; then
    JB_MCP_FILE="$JB_LATEST/options/mcp.json"
    JB_NAME=$(basename "$JB_LATEST")
    configure_mcp_file "$JB_MCP_FILE" "JetBrains ($JB_NAME)" "mcpServers"
    CONFIGURED=$((CONFIGURED + 1))
  fi
fi

# ── PATH setup ──────────────────────────────────────
echo
AGENT_PATH="$SCRIPT_DIR/bin"
SHELL_RC=""
PATH_ALREADY=0

if echo "$PATH" | tr ':' '\n' | grep -qx "$AGENT_PATH"; then
  PATH_ALREADY=1
fi

if [ "$PATH_ALREADY" -eq 0 ]; then
  # Detect shell config file
  if [ -n "${ZSH_VERSION:-}" ] || [ "$(basename "${SHELL:-}")" = "zsh" ]; then
    SHELL_RC="$HOME/.zshrc"
  elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
  elif [ -f "$HOME/.bash_profile" ]; then
    SHELL_RC="$HOME/.bash_profile"
  elif [ -f "$HOME/.profile" ]; then
    SHELL_RC="$HOME/.profile"
  fi

  if [ -n "$SHELL_RC" ]; then
    MARKER="# prompt-gateway PATH"
    if ! grep -q "$MARKER" "$SHELL_RC" 2>/dev/null; then
      echo "" >> "$SHELL_RC"
      echo "$MARKER" >> "$SHELL_RC"
      echo "export PATH=\"$AGENT_PATH:\$PATH\"" >> "$SHELL_RC"
      echo "✓ Added to PATH in $SHELL_RC"
    else
      echo "✓ PATH already in $SHELL_RC"
    fi
  fi
fi

# ── Quick test ──────────────────────────────────────
echo "  Running quick test..."
TEST_OUTPUT=$(node "$SCRIPT_DIR/dist/agent.mjs" --json "test" 2>/dev/null)
if echo "$TEST_OUTPUT" | node -e "const d=require('fs').readFileSync(0,'utf8');const j=JSON.parse(d);process.exit(j.contract?.request_id?0:1)" 2>/dev/null; then
  echo "✓ Gateway works"
else
  echo "⚠ Quick test returned unexpected output"
fi

# ── Done ────────────────────────────────────────────
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  All done! $CONFIGURED MCP clients configured."
echo
echo "  Usage:"
echo
echo "    agent \"fix the auth race and keep changes minimal\""
echo "    agent --json \"add a health endpoint\""
echo "    prompt-gateway --http"
echo
if [ "$PATH_ALREADY" -eq 0 ] && [ -n "$SHELL_RC" ]; then
  echo "  Restart your shell or run:"
  echo "    source $SHELL_RC"
  echo
fi
echo "  Your MCP clients (Cursor, Claude, VS Code) will"
echo "  see prompt-gateway tools on next restart."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
