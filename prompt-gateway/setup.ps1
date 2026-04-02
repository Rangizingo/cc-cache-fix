#Requires -Version 5.1
<#
.SYNOPSIS
  prompt-gateway setup for Windows.
  Installs, builds, auto-configures all MCP clients, adds to PATH.

.DESCRIPTION
  Run directly:   .\setup.ps1
  Or double-click: setup.bat
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$GatewayBin = Join-Path $ScriptDir "dist\prompt-gateway.mjs"
$AgentBin   = Join-Path $ScriptDir "dist\agent.mjs"
$BinDir     = Join-Path $ScriptDir "bin"

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  prompt-gateway setup (Windows)"                  -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ── Check Node ──────────────────────────────────────
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
    Write-Host "[X] Node.js not found. Install Node 20+ first:" -ForegroundColor Red
    Write-Host "    https://nodejs.org/" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
$NodeExe = $nodeCmd.Source
$nodeVer = (node -v) -replace '^v', ''
$nodeMajor = [int]($nodeVer.Split('.')[0])
if ($nodeMajor -lt 20) {
    Write-Host "[X] Node $nodeVer found, need 20+." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Node v$nodeVer" -ForegroundColor Green

# ── Install deps ────────────────────────────────────
Write-Host "     Installing dependencies..."
$npmOutput = npm install 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[X] npm install failed:" -ForegroundColor Red
    Write-Host $npmOutput
    exit 1
}
Write-Host "[OK] Dependencies installed" -ForegroundColor Green

# ── Build ───────────────────────────────────────────
Write-Host "     Building bundles..."
node esbuild.config.mjs
if ($LASTEXITCODE -ne 0) {
    Write-Host "[X] Build failed" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Built" -ForegroundColor Green

# ── CLI shims ───────────────────────────────────────
if (-not (Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir | Out-Null }

# .cmd for cmd.exe and Windows Terminal
@"
@echo off
"$NodeExe" "$AgentBin" %*
"@ | Set-Content (Join-Path $BinDir "agent.cmd") -Encoding ASCII

@"
@echo off
"$NodeExe" "$GatewayBin" %*
"@ | Set-Content (Join-Path $BinDir "prompt-gateway.cmd") -Encoding ASCII

# .ps1 for PowerShell terminals
@"
#!/usr/bin/env pwsh
& "$NodeExe" "$AgentBin" @args
"@ | Set-Content (Join-Path $BinDir "agent.ps1") -Encoding UTF8

@"
#!/usr/bin/env pwsh
& "$NodeExe" "$GatewayBin" @args
"@ | Set-Content (Join-Path $BinDir "prompt-gateway.ps1") -Encoding UTF8

Write-Host "[OK] CLI shims created (cmd + PowerShell)" -ForegroundColor Green

# ── MCP config helper ──────────────────────────────
# Windows paths have backslashes that must be escaped in JSON.
# Use forward slashes which Node.js handles fine on Windows.
$GatewayBinJson = $GatewayBin -replace '\\', '/'
$NodeExeJson    = $NodeExe -replace '\\', '/'

function Set-McpConfig {
    param(
        [string]$FilePath,
        [string]$Label,
        [string]$WrapperKey = "mcpServers"
    )

    $dir = Split-Path -Parent $FilePath
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    # Read or create
    if (Test-Path $FilePath) {
        try {
            $raw = Get-Content $FilePath -Raw -ErrorAction Stop
            if ([string]::IsNullOrWhiteSpace($raw)) { $raw = '{}' }
            $cfg = $raw | ConvertFrom-Json
        } catch {
            Write-Host "  [!] $Label — could not parse $(Split-Path -Leaf $FilePath), skipping" -ForegroundColor Yellow
            return
        }
    } else {
        $cfg = [PSCustomObject]@{}
    }

    # Ensure wrapper key
    if (-not ($cfg.PSObject.Properties.Name -contains $WrapperKey)) {
        $cfg | Add-Member -NotePropertyName $WrapperKey -NotePropertyValue ([PSCustomObject]@{})
    }

    # Already there?
    if ($cfg.$WrapperKey.PSObject.Properties.Name -contains "prompt-gateway") {
        Write-Host "[OK] $Label — already configured" -ForegroundColor Green
        return
    }

    # Add entry with forward-slash paths
    $entry = [PSCustomObject]@{
        command = $NodeExeJson
        args    = @($GatewayBinJson, "--mcp")
    }
    $cfg.$WrapperKey | Add-Member -NotePropertyName "prompt-gateway" -NotePropertyValue $entry
    $cfg | ConvertTo-Json -Depth 10 | Set-Content $FilePath -Encoding UTF8
    Write-Host "[OK] $Label — configured" -ForegroundColor Green
}

Write-Host ""
Write-Host "  Configuring MCP clients..." -ForegroundColor Cyan

$configured = 0

# ── Cursor ─────────────────────────────────────────
$cursorConfig = Join-Path $env:USERPROFILE ".cursor\mcp.json"
Set-McpConfig -FilePath $cursorConfig -Label "Cursor"
$configured++

# ── Claude Desktop ─────────────────────────────────
$claudeDesktop = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
Set-McpConfig -FilePath $claudeDesktop -Label "Claude Desktop"
$configured++

# ── Claude Code ────────────────────────────────────
$claudeCode = Join-Path $env:USERPROFILE ".claude\settings.json"
Set-McpConfig -FilePath $claudeCode -Label "Claude Code"
$configured++

# ── VS Code ───────────────────────────────────────
$vscodeDir = Join-Path $env:APPDATA "Code\User"
if (Test-Path $vscodeDir) {
    $vscodePath = Join-Path $vscodeDir "settings.json"
    if (-not (Test-Path $vscodePath)) {
        '{}' | Set-Content $vscodePath -Encoding UTF8
    }

    try {
        $vsCfg = Get-Content $vscodePath -Raw | ConvertFrom-Json
        $vsKey = "mcp.servers"

        if (-not ($vsCfg.PSObject.Properties.Name -contains $vsKey)) {
            $vsCfg | Add-Member -NotePropertyName $vsKey -NotePropertyValue ([PSCustomObject]@{})
        }

        if (-not ($vsCfg.$vsKey.PSObject.Properties.Name -contains "prompt-gateway")) {
            $vsCfg.$vsKey | Add-Member -NotePropertyName "prompt-gateway" -NotePropertyValue ([PSCustomObject]@{
                command = $NodeExeJson
                args    = @($GatewayBinJson, "--mcp")
            })
            $vsCfg | ConvertTo-Json -Depth 10 | Set-Content $vscodePath -Encoding UTF8
            Write-Host "[OK] VS Code — configured" -ForegroundColor Green
        } else {
            Write-Host "[OK] VS Code — already configured" -ForegroundColor Green
        }
        $configured++
    } catch {
        Write-Host "  [!] VS Code — could not parse settings.json, skipping" -ForegroundColor Yellow
    }
}

# ── Windsurf ───────────────────────────────────────
$windsurfDir = Join-Path $env:USERPROFILE ".windsurf"
if (Test-Path $windsurfDir) {
    $windsurfConfig = Join-Path $windsurfDir "mcp.json"
    Set-McpConfig -FilePath $windsurfConfig -Label "Windsurf"
    $configured++
}

# ── JetBrains IDEs ─────────────────────────────────
# JetBrains stores MCP config per-project or globally.
# We write to the global location if any JetBrains IDE is detected.
$jbConfigDir = Join-Path $env:APPDATA "JetBrains"
if (Test-Path $jbConfigDir) {
    # Find the most recent IDE config dir
    $latestIde = Get-ChildItem $jbConfigDir -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestIde) {
        $jbMcpDir  = Join-Path $latestIde.FullName "options"
        $jbMcpFile = Join-Path $jbMcpDir "mcp.json"
        Set-McpConfig -FilePath $jbMcpFile -Label "JetBrains ($($latestIde.Name))"
        $configured++
    }
}

# ── PATH ───────────────────────────────────────────
Write-Host ""
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }

if ($userPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$BinDir;$userPath", "User")
    $env:Path = "$BinDir;$env:Path"
    Write-Host "[OK] Added to user PATH" -ForegroundColor Green
    $pathChanged = $true
} else {
    Write-Host "[OK] Already in PATH" -ForegroundColor Green
    $pathChanged = $false
}

# ── Quick test ─────────────────────────────────────
Write-Host ""
Write-Host "  Running quick test..." -ForegroundColor Cyan
$testOutput = & $NodeExe $AgentBin --json "test" 2>&1
$testParsed = $testOutput | ConvertFrom-Json -ErrorAction SilentlyContinue
if ($testParsed.contract.request_id) {
    Write-Host "[OK] Gateway works" -ForegroundColor Green
} else {
    Write-Host "  [!] Quick test returned unexpected output" -ForegroundColor Yellow
}

# ── Done ───────────────────────────────────────────
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  All done! $configured MCP clients configured."  -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Usage:" -ForegroundColor White
Write-Host ""
Write-Host '    agent "fix the auth race and keep changes minimal"' -ForegroundColor Yellow
Write-Host '    agent --json "add a health endpoint"'               -ForegroundColor Yellow
Write-Host '    prompt-gateway --http'                              -ForegroundColor Yellow
Write-Host ""

if ($pathChanged) {
    Write-Host "  >> Open a NEW terminal for PATH changes. <<" -ForegroundColor Magenta
    Write-Host ""
}

Write-Host "  MCP clients will see prompt-gateway tools on next restart:" -ForegroundColor White
Write-Host "    Cursor, Claude Desktop, Claude Code, VS Code" -ForegroundColor Gray
if (Test-Path (Join-Path $env:USERPROFILE ".windsurf")) {
    Write-Host "    Windsurf" -ForegroundColor Gray
}
if (Test-Path (Join-Path $env:APPDATA "JetBrains")) {
    Write-Host "    JetBrains" -ForegroundColor Gray
}
Write-Host ""

# Keep window open if launched via double-click
if ($Host.Name -eq 'ConsoleHost' -and [Environment]::GetCommandLineArgs().Count -le 1) {
    Read-Host "Press Enter to close"
}
