#Requires -Version 5.1
<#
.SYNOPSIS
  prompt-gateway setup for Windows.
  Installs, builds, configures MCP clients, and adds to PATH.
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$GatewayBin = Join-Path $ScriptDir "dist\prompt-gateway.mjs"
$AgentBin   = Join-Path $ScriptDir "dist\agent.mjs"
$BinDir     = Join-Path $ScriptDir "bin"

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  prompt-gateway setup (Windows)"                   -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

# ── Check Node ──────────────────────────────────────
$nodePath = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodePath) {
    Write-Host "✗ Node.js not found. Install Node 20+ first." -ForegroundColor Red
    exit 1
}
$nodeVer = (node -v) -replace '^v', ''
$nodeMajor = [int]($nodeVer.Split('.')[0])
if ($nodeMajor -lt 20) {
    Write-Host "✗ Node $nodeVer found, need 20+." -ForegroundColor Red
    exit 1
}
Write-Host "✓ Node v$nodeVer" -ForegroundColor Green

# ── Install deps ────────────────────────────────────
Write-Host "  Installing dependencies..."
npm install --silent 2>$null | Out-Null
Write-Host "✓ Dependencies installed" -ForegroundColor Green

# ── Build ───────────────────────────────────────────
Write-Host "  Building bundles..."
node esbuild.config.mjs
Write-Host "✓ Built" -ForegroundColor Green

# ── CLI batch shims ─────────────────────────────────
if (-not (Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir | Out-Null }

$NodeExe = (Get-Command node).Source

# agent.cmd
@"
@echo off
"$NodeExe" "$AgentBin" %*
"@ | Set-Content (Join-Path $BinDir "agent.cmd") -Encoding ASCII

# prompt-gateway.cmd
@"
@echo off
"$NodeExe" "$GatewayBin" %*
"@ | Set-Content (Join-Path $BinDir "prompt-gateway.cmd") -Encoding ASCII

Write-Host "✓ CLI shims created" -ForegroundColor Green

# ── MCP config helper ──────────────────────────────
$McpEntry = @{
    command = $NodeExe
    args    = @($GatewayBin, "--mcp")
}

function Set-McpConfig {
    param(
        [string]$FilePath,
        [string]$Label,
        [string]$WrapperKey = "mcpServers"
    )

    $dir = Split-Path -Parent $FilePath
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    if (Test-Path $FilePath) {
        $cfg = Get-Content $FilePath -Raw | ConvertFrom-Json
    } else {
        $cfg = [PSCustomObject]@{}
    }

    # Ensure wrapper key exists
    if (-not ($cfg.PSObject.Properties.Name -contains $WrapperKey)) {
        $cfg | Add-Member -NotePropertyName $WrapperKey -NotePropertyValue ([PSCustomObject]@{})
    }

    # Check if already configured
    if ($cfg.$WrapperKey.PSObject.Properties.Name -contains "prompt-gateway") {
        Write-Host "✓ $Label — already configured" -ForegroundColor Green
        return
    }

    # Add entry
    $cfg.$WrapperKey | Add-Member -NotePropertyName "prompt-gateway" -NotePropertyValue ([PSCustomObject]$McpEntry)
    $cfg | ConvertTo-Json -Depth 10 | Set-Content $FilePath -Encoding UTF8
    Write-Host "✓ $Label — configured" -ForegroundColor Green
}

Write-Host ""
Write-Host "  Configuring MCP clients..."

$configured = 0

# ── Cursor (global) ────────────────────────────────
$cursorConfig = Join-Path $env:USERPROFILE ".cursor\mcp.json"
Set-McpConfig -FilePath $cursorConfig -Label "Cursor (global)"
$configured++

# ── Claude Desktop ─────────────────────────────────
$claudeDesktop = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
Set-McpConfig -FilePath $claudeDesktop -Label "Claude Desktop"
$configured++

# ── Claude Code ─────────────────────────────────────
$claudeCode = Join-Path $env:USERPROFILE ".claude\settings.json"
Set-McpConfig -FilePath $claudeCode -Label "Claude Code"
$configured++

# ── VS Code ────────────────────────────────────────
$vscodePath = Join-Path $env:APPDATA "Code\User\settings.json"
if (Test-Path (Split-Path -Parent $vscodePath)) {
    if (-not (Test-Path $vscodePath)) {
        '{}' | Set-Content $vscodePath -Encoding UTF8
    }
    $vsCfg = Get-Content $vscodePath -Raw | ConvertFrom-Json
    $vsKey = "mcp.servers"

    if (-not ($vsCfg.PSObject.Properties.Name -contains $vsKey)) {
        $vsCfg | Add-Member -NotePropertyName $vsKey -NotePropertyValue ([PSCustomObject]@{})
    }

    if (-not ($vsCfg.$vsKey.PSObject.Properties.Name -contains "prompt-gateway")) {
        $vsCfg.$vsKey | Add-Member -NotePropertyName "prompt-gateway" -NotePropertyValue ([PSCustomObject]@{
            command = $NodeExe
            args    = @($GatewayBin, "--mcp")
        })
        $vsCfg | ConvertTo-Json -Depth 10 | Set-Content $vscodePath -Encoding UTF8
        Write-Host "✓ VS Code — configured" -ForegroundColor Green
    } else {
        Write-Host "✓ VS Code — already configured" -ForegroundColor Green
    }
    $configured++
}

# ── Windsurf ────────────────────────────────────────
$windsurfConfig = Join-Path $env:USERPROFILE ".windsurf\mcp.json"
if (Test-Path (Join-Path $env:USERPROFILE ".windsurf")) {
    Set-McpConfig -FilePath $windsurfConfig -Label "Windsurf"
    $configured++
}

# ── PATH ────────────────────────────────────────────
Write-Host ""
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$BinDir;$userPath", "User")
    $env:Path = "$BinDir;$env:Path"
    Write-Host "✓ Added to user PATH" -ForegroundColor Green
} else {
    Write-Host "✓ Already in PATH" -ForegroundColor Green
}

# ── Done ────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  All done! $configured MCP clients configured."    -ForegroundColor Cyan
Write-Host ""
Write-Host "  Usage:"
Write-Host ""
Write-Host '    agent "fix the auth race and keep changes minimal"'
Write-Host '    agent --json "add a health endpoint"'
Write-Host "    prompt-gateway --http"
Write-Host ""
Write-Host "  Open a new terminal for PATH changes to take effect."
Write-Host "  Your MCP clients will see prompt-gateway tools on next restart."
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""
