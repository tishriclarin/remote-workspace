#!/data/data/com.termux/files/usr/bin/bash
# Smoke-test an already-built Android ARM64 companion. No package installs,
# source checkout, compilation, remote device access, or configuration writes.
set -Eeuo pipefail

if [[ "$(uname -m)" != "aarch64" && "$(uname -m)" != "arm64" ]]; then
  echo 'ERROR: Android ARM64 device required' >&2
  exit 2
fi

# An ARM64 Linux host is not necessarily Android. Require Android's system
# property service before invoking any supplied executable.
if ! command -v getprop >/dev/null 2>&1; then
  echo 'ERROR: Android system property service required' >&2
  exit 2
fi
SDK=$(getprop ro.build.version.sdk 2>/dev/null) || {
  echo 'ERROR: Android SDK property unavailable' >&2
  exit 2
}
if [[ ! "$SDK" =~ ^[0-9]+$ ]]; then
  echo 'ERROR: Android SDK property invalid' >&2
  exit 2
fi
# The Android artifact is compiled with cargo-ndk -p 28.
if (( 10#$SDK < 28 )); then
  echo 'ERROR: Android API level 28 or newer required' >&2
  exit 2
fi

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/cloud-built/remoteworkspace" >&2
  exit 2
fi
BIN="$1"
if [[ ! -f "$BIN" || ! -x "$BIN" ]]; then
  echo 'ERROR: executable cloud-built companion file required' >&2
  exit 2
fi

"$BIN" doctor
# Avoid predictable output paths and symlink clobbering; clean up after testing.
REPORT=$(mktemp "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/remote-workspace-mcp.XXXXXXXX")
trap 'rm -f -- "$REPORT"' EXIT
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"termux-smoke-test","version":"1"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"run_shell","arguments":{"command":"touch /tmp/unsafe"}}}' \
  | "$BIN" mcp > "$REPORT"
if grep -Eq '"name"[[:space:]]*:[[:space:]]*"(execute_command|run_shell)"' "$REPORT"; then
  echo 'FAIL: unsafe command tool exposed' >&2
  exit 1
fi
if ! grep -Eq '"id"[[:space:]]*:[[:space:]]*1([[:space:]]*[,}]|$)' "$REPORT" || ! grep -q '"protocolVersion"' "$REPORT"; then
  echo 'FAIL: MCP initialization response missing' >&2
  exit 1
fi
if ! grep -Eq '"id"[[:space:]]*:[[:space:]]*2([[:space:]]*[,}]|$)' "$REPORT" || ! grep -q '"tools"' "$REPORT"; then
  echo 'FAIL: MCP tool listing missing' >&2
  exit 1
fi
if ! grep -Eq '"id"[[:space:]]*:[[:space:]]*3([[:space:]]*[,}]|$)' "$REPORT" || ! grep -Eq '"isError"[[:space:]]*:[[:space:]]*true|"code"[[:space:]]*:[[:space:]]*-32601' "$REPORT"; then
  echo 'FAIL: unsafe tool was not rejected' >&2
  exit 1
fi
echo 'PASS: prebuilt Android binary initialized MCP and rejected unsafe write'
