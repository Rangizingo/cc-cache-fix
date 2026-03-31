Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Version = "2.1.81"
$Base = Split-Path -Parent $MyInvocation.MyCommand.Path
$NodeDir = Join-Path $Base "node"
$CliPath = Join-Path $NodeDir "node_modules/@anthropic-ai/claude-code/cli.js"
$CliBackup = "$CliPath.orig"
$PatchScript = Join-Path $Base "patches/apply-patches.py"
$WrapperDir = Join-Path $HOME ".local/bin"
$CmdWrapper = Join-Path $WrapperDir "claude-patched.cmd"
$PsWrapper = Join-Path $WrapperDir "claude-patched.ps1"

Write-Host "========================================"
Write-Host "  Claude Code Cache Fix Installer"
Write-Host "  Target: v$Version (Windows)"
Write-Host "========================================"
Write-Host ""

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name not found. Install it first and rerun."
    }
}

Require-Command "node"
Require-Command "npm"

$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    $PythonCmd = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $PythonCmd) {
    throw "python (or py launcher) not found. Install Python 3 first."
}

if (-not (Test-Path -Path $PatchScript)) {
    throw "Patch script not found: $PatchScript"
}

if (-not (Test-Path -Path $CliPath)) {
    Write-Host "[*] Installing @anthropic-ai/claude-code@$Version..."
    npm install --prefix $NodeDir "@anthropic-ai/claude-code@$Version" | Out-Host
} else {
    Write-Host "[*] cli.js already installed"
}

if (-not (Test-Path -Path $CliBackup)) {
    Write-Host "[*] Backing up cli.js -> cli.js.orig"
    Copy-Item -Path $CliPath -Destination $CliBackup
} else {
    Write-Host "[*] Backup already exists"
}

Write-Host "[*] Restoring from backup..."
Copy-Item -Path $CliBackup -Destination $CliPath -Force

Write-Host "[*] Applying patches..."
& $PythonCmd.Source $PatchScript $CliPath | Out-Host

$PatchedVersion = (& node $CliPath --version 2>$null).Trim()
Write-Host "[*] Patched version: $PatchedVersion"
if ($PatchedVersion -ne "$Version (Claude Code)") {
    Write-Host "[!] Version mismatch after patching. Restoring backup."
    Copy-Item -Path $CliBackup -Destination $CliPath -Force
    throw "Patch verification failed"
}

New-Item -ItemType Directory -Path $WrapperDir -Force | Out-Null
if (Test-Path $CmdWrapper) { Remove-Item $CmdWrapper -Force }
if (Test-Path $PsWrapper) { Remove-Item $PsWrapper -Force }

$cmdBody = @"
@echo off
node "$CliPath" %*
"@
Set-Content -Path $CmdWrapper -Value $cmdBody -Encoding ASCII

$psBody = @"
param([Parameter(ValueFromRemainingArguments=`$true)][string[]]`$Args)
& node "$CliPath" @Args
exit `$LASTEXITCODE
"@
Set-Content -Path $PsWrapper -Value $psBody -Encoding ASCII

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if (-not (($userPath -split ";") -contains $WrapperDir)) {
    $newPath = if ([string]::IsNullOrWhiteSpace($userPath)) { $WrapperDir } else { "$userPath;$WrapperDir" }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "[*] Added $WrapperDir to User PATH"
}

Write-Host ""
Write-Host "Done. Open a NEW terminal and run:"
Write-Host "  claude-patched --version"
Write-Host "Stock 'claude' command is untouched."
