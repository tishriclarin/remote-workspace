# Remote Workspace Rust remote MCP gateway

The gateway and device agent are **Rust**. The ChatGPT-facing service exposes `POST /mcp` with JSON-RPC MCP methods. The device agent uses outbound HTTP(S) polling and invokes only allowlisted read-only tools in the existing local `remoteworkspace mcp` companion. SSH credentials and private keys remain on the device.

## Local development

```bash
cd gateway
export REMOTEWORKSPACE_GATEWAY_TOKEN="$(openssl rand -hex 32)"
export REMOTEWORKSPACE_DEVICE_TOKEN="$(openssl rand -hex 32)"
cargo run --bin remoteworkspace-gateway
```

On a second terminal on the same computer, using the same device token and a previously compiled Rust SSH companion:

```bash
cd gateway
export REMOTEWORKSPACE_GATEWAY_URL=http://127.0.0.1:8787
export REMOTEWORKSPACE_DEVICE_TOKEN="THE_SAME_DEVICE_TOKEN"
export REMOTEWORKSPACE_COMPANION_BIN=/absolute/path/to/remoteworkspace
cargo run --bin device
```

The two tokens must be distinct. The client token is for the MCP caller and the device token is for the device agent. Do not put either token in source control. The gateway binds to loopback by default. A public deployment must terminate TLS, use production-grade per-user OAuth authorization, enroll each device with a distinct credential, provide a persistent bounded request store, and enforce tool approvals on the device. **The current static single-device tokens are for isolated development only.** Do not expose this gateway on the internet.

## MCP transport

- `POST /mcp` — authenticated MCP JSON-RPC requests
- `GET /device/poll` — separately authenticated device work polling
- `POST /device/result` — separately authenticated device result delivery
- `GET /healthz` — readiness

The gateway is deliberately not a generic remote shell. A disconnected device causes a bounded timeout. Restarting the server drops queued work. No user device has been deployed or paired yet.
