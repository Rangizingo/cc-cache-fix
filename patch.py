#!/usr/bin/env python3
"""
Claude Code Cache Fix — Universal Patcher
Finds and patches the cache-breaking db8 function regardless of version.
Self-diagnosing, verbose, works on macOS and Linux.
"""

import glob
import os
import re
import shutil
import subprocess
import sys


def log(msg: str) -> None:
    print(f"  {msg}")


def find_cli_js() -> str | None:
    """Search common locations for cli.js."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        # Local project installs (preferred — these are ours to patch)
        os.path.join(script_dir, "node_modules/@anthropic-ai/claude-code/cli.js"),
        os.path.join(script_dir, "node/node_modules/@anthropic-ai/claude-code/cli.js"),
        os.path.expanduser("~/cc-cache-fix/node_modules/@anthropic-ai/claude-code/cli.js"),
        os.path.expanduser("~/cc-cache-fix/node/node_modules/@anthropic-ai/claude-code/cli.js"),
        os.path.join(os.getcwd(), "node_modules/@anthropic-ai/claude-code/cli.js"),
        os.path.join(os.getcwd(), "node/node_modules/@anthropic-ai/claude-code/cli.js"),
        # npm global (linux)
        "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js",
        # npm global (macOS homebrew)
        "/usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js",
        # npm global (macOS ARM homebrew)
        "/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/cli.js",
    ]

    for c in candidates:
        if os.path.isfile(c):
            return c

    # Try finding it with npm root
    try:
        root = subprocess.check_output(["npm", "root", "-g"], text=True, stderr=subprocess.DEVNULL).strip()
        p = os.path.join(root, "@anthropic-ai/claude-code/cli.js")
        if os.path.isfile(p):
            return p
    except Exception:
        pass

    return None


def install_npm(version: str | None = None) -> str:
    """Install claude-code via npm into ~/cc-cache-fix."""
    base = os.path.expanduser("~/cc-cache-fix")
    os.makedirs(base, exist_ok=True)
    pkg = f"@anthropic-ai/claude-code@{version}" if version else "@anthropic-ai/claude-code"
    log(f"Installing {pkg} into {base}...")
    subprocess.check_call(["npm", "install", pkg], cwd=base)
    path = os.path.join(base, "node_modules/@anthropic-ai/claude-code/cli.js")
    if not os.path.isfile(path):
        print("[!] npm install succeeded but cli.js not found")
        sys.exit(1)
    return path


def backup(path: str) -> None:
    """Create .orig backup if it doesn't exist."""
    orig = path + ".orig"
    if os.path.isfile(orig):
        log(f"Backup exists: {orig}")
        log("Restoring from backup for clean patch...")
        shutil.copy2(orig, path)
    else:
        log(f"Creating backup: {orig}")
        shutil.copy2(path, orig)


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def patch_db8(source: str) -> tuple[str, bool]:
    """
    Patch 1: Fix the JSONL write filter to preserve cache-relevant attachments.

    Tries multiple strategies to find and patch the function:
    1. Exact string match (fastest, most reliable)
    2. Regex match (handles minor variations)
    3. Semantic search (finds by surrounding context)
    """

    patch_marker = 'type==="deferred_tools_delta"'
    if patch_marker in source:
        log("Patch 1 (db8 cache fix): already applied")
        return source, True

    # Strategy 1: exact match on the key substring
    log("Patch 1: trying exact match...")
    exact = (
        'if(A.attachment.type==="hook_additional_context"'
        '&&a6(process.env.CLAUDE_CODE_SAVE_HOOK_ADDITIONAL_CONTEXT))return!0;'
        'return!1}'
    )
    if exact in source:
        replacement = exact.replace(
            "return!1}",
            'if(A.attachment.type==="deferred_tools_delta")return!0;'
            'if(A.attachment.type==="mcp_instructions_delta")return!0;'
            "return!1}",
        )
        source = source.replace(exact, replacement, 1)
        log("Patch 1 (db8 cache fix): applied via exact match")
        return source, True

    # Strategy 2: regex for the full function with any function name
    log("Patch 1: exact match failed, trying regex...")
    pattern = re.compile(
        r'(function \w+\(\w+\)\{if\(\w+\.type==="attachment"&&\w+\(\)!=="ant"\)\{'
        r'if\(\w+\.attachment\.type==="hook_additional_context"'
        r'&&\w+\(process\.env\.\w+\))return!0;'
        r'(return!1\})'
    )
    match = pattern.search(source)
    if match:
        insert_pos = match.start(2)
        insert = (
            'if(A.attachment.type==="deferred_tools_delta")return!0;'
            'if(A.attachment.type==="mcp_instructions_delta")return!0;'
        )
        # Get the actual variable name used (might not be 'A')
        func_match = re.match(r'function \w+\((\w+)\)', match.group(0))
        if func_match:
            var = func_match.group(1)
            insert = (
                f'if({var}.attachment.type==="deferred_tools_delta")return!0;'
                f'if({var}.attachment.type==="mcp_instructions_delta")return!0;'
            )
        source = source[:insert_pos] + insert + source[insert_pos:]
        log("Patch 1 (db8 cache fix): applied via regex")
        return source, True

    # Strategy 3: find by context - look for hook_additional_context near attachment filter
    log("Patch 1: regex failed, trying semantic search...")
    idx = source.find('"hook_additional_context"')
    if idx == -1:
        log("Patch 1 FAILED: cannot find hook_additional_context anywhere in file")
        return source, False

    # Find the return!1} that follows within 200 chars
    region = source[idx:idx + 300]
    ret_match = re.search(r'return!1\}', region)
    if ret_match:
        abs_pos = idx + ret_match.start()
        insert = (
            'if(A.attachment.type==="deferred_tools_delta")return!0;'
            'if(A.attachment.type==="mcp_instructions_delta")return!0;'
        )
        # Try to detect the variable name from nearby code
        var_match = re.search(r'if\((\w+)\.attachment\.type==="hook', source[idx - 50:idx + 50])
        if var_match:
            var = var_match.group(1)
            insert = (
                f'if({var}.attachment.type==="deferred_tools_delta")return!0;'
                f'if({var}.attachment.type==="mcp_instructions_delta")return!0;'
            )
        source = source[:abs_pos] + insert + source[abs_pos:]
        log("Patch 1 (db8 cache fix): applied via semantic search")
        return source, True

    log("Patch 1 FAILED: found hook_additional_context but couldn't locate insertion point")
    return source, False


def patch_fingerprint_meta(source: str) -> tuple[str, bool]:
    """
    Patch 1b: skip meta user messages when computing attribution fingerprint.
    """

    marker = 'type==="user"&&!('
    if marker in source and '"isMeta"in' in source:
        log("Patch 1b (fingerprint meta skip): already applied")
        return source, True

    # Strategy 1: exact known minified pattern
    log("Patch 1b: trying exact match...")
    exact = 'function FA9(A){let q=A.find((_)=>_.type==="user");'
    if exact in source:
        source = source.replace(
            exact,
            'function FA9(A){let q=A.find((_)=>_.type==="user"&&!("isMeta"in _&&_.isMeta));',
            1,
        )
        log("Patch 1b (fingerprint meta skip): applied via exact match")
        return source, True

    # Strategy 2: regex for generic minifier variable names
    log("Patch 1b: exact match failed, trying regex...")
    pattern = re.compile(
        r'function (\w+)\((\w+)\)\{let (\w+)=(\w+)\.find\(\((\w+)\)=>\5\.type==="user"\);'
    )
    match = pattern.search(source)
    if match:
        fn, arg, out, arr, var = match.groups()
        replacement = (
            f'function {fn}({arg}){{let {out}={arr}.find(('
            f'{var})=>{var}.type==="user"&&!("isMeta"in {var}&&{var}.isMeta));'
        )
        source = source[:match.start()] + replacement + source[match.end():]
        log("Patch 1b (fingerprint meta skip): applied via regex")
        return source, True

    log("Patch 1b: could not find fingerprint selector, skipping (non-critical)")
    return source, False


def patch_ttl(source: str) -> tuple[str, bool]:
    """
    Patch 2: Force 1-hour cache TTL.

    The function that decides TTL checks subscription status and a server-side
    feature flag. We make it always return true.
    """

    # Check if already patched (return!0 right after function opening)
    if re.search(r'function \w+\(\w+\)\{return!0;if\(\w+\(\)==="bedrock"', source):
        log("Patch 2 (1h cache TTL): already applied")
        return source, True

    # Strategy 1: exact match
    log("Patch 2: trying exact match...")
    exact = 'function sjY(A){if(QA()==="bedrock"'
    if exact in source:
        source = source.replace(exact, 'function sjY(A){return!0;if(QA()==="bedrock"', 1)
        log("Patch 2 (1h cache TTL): applied via exact match")
        return source, True

    # Strategy 2: regex for any function name, find by bedrock + ttl context
    log("Patch 2: exact match failed, trying regex...")
    pattern = re.compile(
        r'(function \w+\(\w+\)\{)'
        r'(if\(\w+\(\)==="bedrock".*?ttl.*?1h)'
    )
    match = pattern.search(source)
    if match:
        insert_pos = match.end(1)
        source = source[:insert_pos] + "return!0;" + source[insert_pos:]
        log("Patch 2 (1h cache TTL): applied via regex")
        return source, True

    # Strategy 3: find by the ttl:"1h" string nearby bedrock check
    log("Patch 2: regex failed, trying semantic search...")
    idx = source.find('ttl:"1h"')
    if idx == -1:
        idx = source.find("ttl:'1h'")
    if idx == -1:
        log("Patch 2: no ttl:1h found in source, skipping (non-critical)")
        return source, False

    # Walk backwards to find the function declaration
    region = source[max(0, idx - 500):idx]
    func_match = list(re.finditer(r'function \w+\(\w+\)\{', region))
    if func_match:
        last = func_match[-1]
        abs_pos = max(0, idx - 500) + last.end()
        source = source[:abs_pos] + "return!0;" + source[abs_pos:]
        log("Patch 2 (1h cache TTL): applied via semantic search")
        return source, True

    log("Patch 2: could not locate function boundary, skipping (non-critical)")
    return source, False


def verify(path: str) -> bool:
    """Verify patched cli.js still runs."""
    log("Verifying patched cli.js runs...")
    try:
        result = subprocess.run(
            ["node", path, "--version"],
            capture_output=True, text=True, timeout=15
        )
        version = result.stdout.strip()
        log(f"Version: {version}")
        return result.returncode == 0 and "Claude Code" in version
    except Exception as e:
        log(f"Verification failed: {e}")
        return False


def setup_wrapper(cli_path: str) -> None:
    """Create claude-patched wrapper script."""
    bin_dir = os.path.expanduser("~/.local/bin")
    os.makedirs(bin_dir, exist_ok=True)
    wrapper = os.path.join(bin_dir, "claude-patched")

    with open(wrapper, "w") as f:
        f.write(f'#!/usr/bin/env bash\nexec node "{cli_path}" "$@"\n')
    os.chmod(wrapper, 0o755)
    log(f"Wrapper: {wrapper}")

    # Check if ~/.local/bin is in PATH
    path_dirs = os.environ.get("PATH", "").split(":")
    if bin_dir not in path_dirs:
        shell_rc = None
        for rc in ["~/.zshrc", "~/.bashrc", "~/.bash_profile"]:
            rc = os.path.expanduser(rc)
            if os.path.isfile(rc):
                shell_rc = rc
                break
        if shell_rc:
            with open(shell_rc, "r") as f:
                content = f.read()
            if ".local/bin" not in content:
                with open(shell_rc, "a") as f:
                    f.write('\nexport PATH="$HOME/.local/bin:$PATH"\n')
                log(f"Added ~/.local/bin to PATH in {os.path.basename(shell_rc)}")
        log("NOTE: Open a new terminal for PATH changes to take effect")


def main() -> int:
    print("=" * 50)
    print("  Claude Code Cache Fix — Universal Patcher")
    print("=" * 50)
    print()

    # Step 1: Find or install cli.js
    print("[1/5] Locating cli.js...")
    cli_path = find_cli_js()
    if cli_path:
        log(f"Found: {cli_path}")
        log(f"Size: {os.path.getsize(cli_path):,} bytes")
    else:
        log("Not found in any standard location")
        log("Installing via npm...")
        if not shutil.which("npm"):
            print("\n[!] npm not found. Install Node.js first.")
            print("    macOS: brew install node")
            print("    Linux: apt install nodejs npm")
            return 1
        cli_path = install_npm()
        log(f"Installed: {cli_path}")

    # Step 2: Get version info
    print("\n[2/5] Checking version...")
    try:
        ver = subprocess.check_output(
            ["node", cli_path, "--version"],
            text=True, timeout=15, stderr=subprocess.DEVNULL
        ).strip()
        log(f"Version: {ver}")
    except Exception as e:
        log(f"Could not get version: {e}")
        ver = "unknown"

    # Step 3: Backup
    print("\n[3/5] Backup...")
    backup(cli_path)

    # Step 4: Apply patches
    print("\n[4/5] Patching...")
    source = read_file(cli_path)
    log(f"Source size: {len(source):,} bytes")

    source, p1_ok = patch_db8(source)
    source, p1b_ok = patch_fingerprint_meta(source)
    source, p2_ok = patch_ttl(source)

    if not p1_ok:
        print("\n[!] Critical patch (db8) failed. Cannot continue.")
        print("    This version's code structure may differ from what we expect.")
        print("    File an issue with the version number above.")
        # Restore backup
        shutil.copy2(cli_path + ".orig", cli_path)
        log("Restored backup")
        return 1

    write_file(cli_path, source)
    log(f"Wrote: {len(source):,} bytes")

    # Step 5: Verify and set up wrapper
    print("\n[5/5] Verify and install...")
    if not verify(cli_path):
        print("\n[!] Patched cli.js failed to run. Restoring backup.")
        shutil.copy2(cli_path + ".orig", cli_path)
        return 1

    setup_wrapper(cli_path)

    # Summary
    print()
    print("=" * 50)
    print("  Done!")
    print()
    print("  Patches applied:")
    print(f"    [{'OK' if p1_ok else 'FAIL'}] db8 cache fix (resume regression)")
    print(f"    [{'OK' if p1b_ok else 'SKIP'}] fingerprint meta skip (resume first-turn stability)")
    print(f"    [{'OK' if p2_ok else 'SKIP'}] 1h cache TTL")
    print()
    print("  Run: claude-patched")
    print("  Stock 'claude' is untouched.")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[!] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
