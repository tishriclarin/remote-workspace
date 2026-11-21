//! Minimal authenticated remote MCP gateway. Does not proxy SSH credentials.
use axum::{extract::State, http::{HeaderMap, StatusCode}, response::IntoResponse, routing::{get, post}, Json, Router};
use serde_json::{json, Value};
use std::{env, net::SocketAddr, sync::Arc};
use subtle::ConstantTimeEq;

struct Config { bearer: String }
fn authorized(headers: &HeaderMap, config: &Config) -> bool {
    let supplied = headers.get("authorization").and_then(|h| h.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "));
    supplied.is_some_and(|s| s.as_bytes().ct_eq(config.bearer.as_bytes()).into())
}
async fn health() -> &'static str { "ok" }
async fn mcp(State(config): State<Arc<Config>>, headers: HeaderMap, Json(request): Json<Value>) -> impl IntoResponse {
    if !authorized(&headers, &config) {
        return (StatusCode::UNAUTHORIZED, Json(json!({"error":"unauthorized"})));
    }
    let id = request.get("id").cloned().unwrap_or(Value::Null);
    let method = request.get("method").and_then(Value::as_str).unwrap_or("");
    if id.is_null() && method == "notifications/initialized" {
        return (StatusCode::ACCEPTED, Json(json!({})));
    }
    let response = match method {
        "initialize" => json!({"jsonrpc":"2.0","id":id,"result":{
            "protocolVersion":"2025-03-26",
            "capabilities":{"tools":{"listChanged":false}},
            "serverInfo":{"name":"sshworkspace-gateway","version":"0.1.0"}
        }}),
        "ping" => json!({"jsonrpc":"2.0","id":id,"result":{}}),
        "tools/list" => json!({"jsonrpc":"2.0","id":id,"result":{"tools":[{
            "name":"gateway_status",
            "description":"Check gateway availability. No device access is implied.",
            "inputSchema":{"type":"object","properties":{},"additionalProperties":false},
            "annotations":{"readOnlyHint":true}
        }]}}),
        "tools/call" => {
            let name = request.pointer("/params/name").and_then(Value::as_str).unwrap_or("");
            if name == "gateway_status" {
                json!({"jsonrpc":"2.0","id":id,"result":{"content":[{"type":"text","text":"Gateway online; device pairing and SSH forwarding not configured."}]}})
            } else {
                json!({"jsonrpc":"2.0","id":id,"error":{"code":-32601,"message":"Unknown tool"}})
            }
        },
        _ => json!({"jsonrpc":"2.0","id":id,"error":{"code":-32601,"message":"Method not found"}})
    };
    (StatusCode::OK, Json(response))
}
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let token = env::var("SSHWORKSPACE_GATEWAY_TOKEN").expect("Set SSHWORKSPACE_GATEWAY_TOKEN");
    assert!(token.len() >= 32, "Gateway token must be at least 32 characters");
    let bind = env::var("SSHWORKSPACE_GATEWAY_BIND").unwrap_or_else(|_| "127.0.0.1:8787".into());
    let addr: SocketAddr = bind.parse()?;
    if !addr.ip().is_loopback() && env::var("SSHWORKSPACE_ALLOW_PLAINTEXT_REMOTE").as_deref() != Ok("1") {
        panic!("Non-loopback bind requires TLS termination and explicit SSHWORKSPACE_ALLOW_PLAINTEXT_REMOTE=1");
    }
    let app = Router::new().route("/healthz", get(health)).route("/mcp", post(mcp))
        .with_state(Arc::new(Config { bearer: token }));
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bearer_authentication() {
        let cfg = Config { bearer: "a".repeat(32) };
        let mut headers = HeaderMap::new();
        assert!(!authorized(&headers, &cfg));
        headers.insert("authorization", format!("Bearer {}", cfg.bearer).parse().unwrap());
        assert!(authorized(&headers, &cfg));
        headers.insert("authorization", "Bearer invalid".parse().unwrap());
        assert!(!authorized(&headers, &cfg));
    }
}
