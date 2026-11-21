#!/data/data/com.termux/files/usr/bin/bash
# Smoke-test an already-built Android ARM64 companion. No package installs,
# source checkout, compilation, remote device access, or configuration writes.
set -Eeuo pipefail

if [[ "$(uname -m)" != "aarch64" && "$(uname -m)" != "arm64" ]]; then
  echo 'ERROR: Android ARM64 device required' >&2
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
if grep -q '"name":"execute_command"' "$REPORT"; then
  echo 'FAIL: unsafe command tool exposed' >&2
  exit 1
fi
if ! grep -q '"id":1' "$REPORT" || ! grep -q '"protocolVersion"' "$REPORT"; then
  echo 'FAIL: MCP initialization response missing' >&2
  exit 1
fi
if ! grep -q '"id":2' "$REPORT" || ! grep -q '"tools"' "$REPORT"; then
  echo 'FAIL: MCP tool listing missing' >&2
  exit 1
fi
if ! grep -q '"id":3' "$REPORT" || ! grep -Eq '"isError":[[:space:]]*true|"code":[[:space:]]*-32601' "$REPORT"; then
  echo 'FAIL: unsafe tool was not rejected' >&2
  exit 1
fi
echo 'PASS: prebuilt Android binary initialized MCP and rejected unsafe write'
