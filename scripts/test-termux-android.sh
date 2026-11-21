#!/data/data/com.termux/files/usr/bin/bash
# Android/Termux ARM64 read-only smoke test; never connects to remote devices.
set -Eeuo pipefail
export PATH="$HOME/.cargo/bin:$PATH"
echo "[1/5] Android architecture"
uname -m
case "$(uname -m)" in aarch64|arm64) ;; *) echo "Unsupported phone CPU for this test"; exit 2;; esac
echo "[2/5] Build dependencies"
pkg update -y
pkg install -y rust clang make pkg-config openssl git
echo "[3/5] Checkout source"
REPO_URL="https://github.com/tishriclarin/remote-workspace.git"
WORKDIR="${HOME}/remote-workspace-test"
if [ -d "$WORKDIR/.git" ]; then
  git -C "$WORKDIR" fetch --prune origin main
  git -C "$WORKDIR" checkout main
  git -C "$WORKDIR" pull --ff-only
else
  git clone "$REPO_URL" "$WORKDIR"
fi
cd "$WORKDIR/companion"
echo "[4/5] Run unit tests and build native Android/Termux binary"
cargo test
cargo build --release
BIN="$PWD/target/release/remoteworkspace"
"$BIN" --help || true
echo "[5/5] MCP protocol read-only smoke test"
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"termux-smoke-test","version":"1"}}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"run_shell","arguments":{"command":"touch /tmp/unsafe"}}}' | "$BIN" mcp | tee "$HOME/remote-workspace-mcp-test.jsonl"
if grep -q '"name":"execute_command"' "$HOME/remote-workspace-mcp-test.jsonl"; then
  echo "FAIL: unsafe command tool exposed"; exit 1
fi
if ! grep -q '"isError":true' "$HOME/remote-workspace-mcp-test.jsonl"; then
  echo "FAIL: unsafe tool was not rejected"; exit 1
fi
echo "PASS: Android binary built; MCP initialized; unsafe write rejected"
echo "Report: $HOME/remote-workspace-mcp-test.jsonl"
