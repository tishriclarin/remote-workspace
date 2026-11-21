//! Rust MCP gateway with explicit device enrollment and bounded outbound polling.
//! The device owns SSH keys. No arbitrary commands or credentials cross the gateway.
use axum::{extract::State, http::{HeaderMap, StatusCode}, response::IntoResponse, routing::{get, post}, Json, Router};
use serde_json::{json, Value};
use std::{collections::{HashMap,VecDeque}, env, net::SocketAddr, sync::{Arc,atomic::{AtomicU64,Ordering}}, time::Duration};
use subtle::ConstantTimeEq;
use tokio::sync::{Mutex,oneshot};

const MAX_QUEUE: usize = 32;
const MAX_BODY: usize = 65536;
struct Pending { sender: oneshot::Sender<Value> }
struct DeviceState { queue: VecDeque<Value>, pending: HashMap<u64, Pending> }
struct Config {
    bearer: String, device_token: String,
    state: Mutex<DeviceState>, counter: AtomicU64
}
fn matches_token(headers: &HeaderMap, expected: &str) -> bool {
    let supplied = headers.get("authorization").and_then(|h| h.to_str().ok()).and_then(|v| v.strip_prefix("Bearer "));
    supplied.is_some_and(|s| s.as_bytes().ct_eq(expected.as_bytes()).into())
}
fn authorized(headers: &HeaderMap, config: &Config) -> bool { matches_token(headers, &config.bearer) }
fn device_authorized(headers: &HeaderMap, config: &Config) -> bool { matches_token(headers, &config.device_token) }
async fn health() -> &'static str { "ok" }
async fn poll(State(config): State<Arc<Config>>, headers: HeaderMap) -> impl IntoResponse {
    if !device_authorized(&headers, &config) { return (StatusCode::UNAUTHORIZED, Json(json!({"error":"unauthorized"}))); }
    let mut state = config.state.lock().await;
    match state.queue.pop_front() {
        Some(job) => (StatusCode::OK, Json(job)),
        None => (StatusCode::OK, Json(json!({"job":null})))
    }
}
async fn result(State(config): State<Arc<Config>>, headers: HeaderMap, Json(payload): Json<Value>) -> impl IntoResponse {
    if !device_authorized(&headers, &config) { return (StatusCode::UNAUTHORIZED, Json(json!({"error":"unauthorized"}))); }
    let Some(id) = payload.get("id").and_then(Value::as_u64) else {
        return (StatusCode::BAD_REQUEST, Json(json!({"error":"invalid id"})));
    };
    let Some(response) = payload.get("response") else {
        return (StatusCode::BAD_REQUEST, Json(json!({"error":"missing response"})));
    };
    if response.to_string().len() > MAX_BODY {
        return (StatusCode::PAYLOAD_TOO_LARGE, Json(json!({"error":"response too large"})));
    }
    let mut state = config.state.lock().await;
    match state.pending.remove(&id) {
        Some(p) => {
            let _ = p.sender.send(response.clone());
            (StatusCode::OK, Json(json!({"accepted":true})))
        },
        None => (StatusCode::NOT_FOUND, Json(json!({"error":"unknown or expired request"})))
    }
}
async fn call_device(config: Arc<Config>, name: &str, args: Value) -> Result<Value, &'static str> {
    // Strictly allowlisted read-only commands. The companion must independently enforce this.
    if !["get_gateway_status","get_vault_status","list_ssh_hosts","check_ssh_connection","get_ssh_host_platform","get_ssh_host_uptime"].contains(&name) {
        return Err("Tool not allowed");
    }
    let id = config.counter.fetch_add(1, Ordering::Relaxed);
    let (tx, rx) = oneshot::channel();
    {
        let mut state = config.state.lock().await;
        if state.queue.len() >= MAX_QUEUE { return Err("Device queue full"); }
        state.pending.insert(id, Pending { sender: tx });
        state.queue.push_back(json!({"id":id,"name":name,"arguments":args}));
    }
    let outcome = tokio::time::timeout(Duration::from_secs(20), rx).await;
    let mut state = config.state.lock().await;
    state.pending.remove(&id);
    match outcome {
        Ok(Ok(value)) => Ok(value),
        _ => { state.queue.retain(|job| job.get("id").and_then(Value::as_u64) != Some(id)); Err("Device offline or request timed out") }
    }
}
async fn mcp(State(config): State<Arc<Config>>, headers: HeaderMap, Json(request): Json<Value>) -> impl IntoResponse {
    if !authorized(&headers, &config) { return (StatusCode::UNAUTHORIZED, Json(json!({"error":"unauthorized"}))); }
    if request.to_string().len() > MAX_BODY { return (StatusCode::PAYLOAD_TOO_LARGE, Json(json!({"error":"request too large"}))); }
    let id = request.get("id").cloned().unwrap_or(Value::Null);
    let method = request.get("method").and_then(Value::as_str).unwrap_or("");
    if id.is_null() && method == "notifications/initialized" {
        return (StatusCode::ACCEPTED, Json(json!({})));
    }
    let response = match method {
        "initialize" => json!({"jsonrpc":"2.0","id":id,"result":{
            "protocolVersion":"2025-03-26",
            "capabilities":{"tools":{"listChanged":false}},
            "serverInfo":{"name":"sshworkspace-gateway","version":"0.2.0"}
        }}),
        "ping" => json!({"jsonrpc":"2.0","id":id,"result":{}}),
        "tools/list" => json!({"jsonrpc":"2.0","id":id,"result":{"tools":[
            {"name":"gateway_status","description":"Read gateway status.","inputSchema":{"type":"object","properties":{},"additionalProperties":false},"annotations":{"readOnlyHint":true}},
            {"name":"list_ssh_hosts","description":"List aliases on paired device.","inputSchema":{"type":"object","properties":{},"additionalProperties":false},"annotations":{"readOnlyHint":true}},
            {"name":"check_ssh_connection","description":"Check a pinned SSH host.","inputSchema":{"type":"object","properties":{"alias":{"type":"string"}},"required":["alias"],"additionalProperties":false},"annotations":{"readOnlyHint":true}},
            {"name":"get_ssh_host_platform","description":"Read host OS and CPU.","inputSchema":{"type":"object","properties":{"alias":{"type":"string"}},"required":["alias"],"additionalProperties":false},"annotations":{"readOnlyHint":true}},
            {"name":"get_ssh_host_uptime","description":"Read host uptime.","inputSchema":{"type":"object","properties":{"alias":{"type":"string"}},"required":["alias"],"additionalProperties":false},"annotations":{"readOnlyHint":true}}
        ]}}),
        "tools/call" => {
            let name = request.pointer("/params/name").and_then(Value::as_str).unwrap_or("");
            if name == "gateway_status" {
                json!({"jsonrpc":"2.0","id":id,"result":{"content":[{"type":"text","text":"Rust gateway online; companion requests require separate device authorization."}]}})
            } else {
                let args = request.pointer("/params/arguments").cloned().unwrap_or_else(|| json!({}));
                match call_device(config.clone(), name, args).await {
                    Ok(result) => json!({"jsonrpc":"2.0","id":id,"result":result}),
                    Err(error) => json!({"jsonrpc":"2.0","id":id,"error":{"code":-32000,"message":error}})
                }
            }
        },
        _ => json!({"jsonrpc":"2.0","id":id,"error":{"code":-32601,"message":"Method not found"}})
    };
    (StatusCode::OK, Json(response))
}
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let token = env::var("SSHWORKSPACE_GATEWAY_TOKEN").expect("Set SSHWORKSPACE_GATEWAY_TOKEN");
    let device_token = env::var("SSHWORKSPACE_DEVICE_TOKEN").expect("Set SSHWORKSPACE_DEVICE_TOKEN");
    assert!(token.len() >= 32 && device_token.len() >= 32 && token != device_token, "Use two distinct 32+ character tokens");
    let bind = env::var("SSHWORKSPACE_GATEWAY_BIND").unwrap_or_else(|_| "127.0.0.1:8787".into());
    let addr: SocketAddr = bind.parse()?;
    if !addr.ip().is_loopback() && env::var("SSHWORKSPACE_ALLOW_PLAINTEXT_REMOTE").as_deref() != Ok("1") {
        panic!("Non-loopback bind requires TLS termination and explicit SSHWORKSPACE_ALLOW_PLAINTEXT_REMOTE=1");
    }
    let config = Arc::new(Config { bearer:token, device_token, state:Mutex::new(DeviceState {queue:VecDeque::new(),pending:HashMap::new()}), counter:AtomicU64::new(1) });
    let app = Router::new().route("/healthz", get(health)).route("/mcp", post(mcp))
        .route("/device/poll",get(poll)).route("/device/result",post(result)).with_state(config);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn separate_tokens() {
        let mut h=HeaderMap::new();
        h.insert("authorization","Bearer clienttoken".parse().unwrap());
        assert!(matches_token(&h,"clienttoken"));
        assert!(!matches_token(&h,"devicetoken"));
    }
    #[tokio::test]
    async fn reject_unapproved_tool() {
        let cfg=Arc::new(Config {bearer:"a".repeat(32),device_token:"b".repeat(32),state:Mutex::new(DeviceState {queue:VecDeque::new(),pending:HashMap::new()}),counter:AtomicU64::new(1)});
        assert!(call_device(cfg.clone(),"run_shell",json!({})).await.is_err());
        assert!(cfg.state.lock().await.queue.is_empty());
    }
}
