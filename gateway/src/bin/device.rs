//! Outbound device agent. Explicitly run on the same machine as remoteworkspace.
//! No inbound ports. All SSH commands are still enforced by the Rust companion.
use serde_json::{json,Value};
use std::{env,process::Stdio,time::Duration};
use tokio::{io::{AsyncBufReadExt,AsyncWriteExt,BufReader},process::Command};
const ALLOWED: &[&str] = &["get_gateway_status","get_vault_status","list_ssh_hosts","check_ssh_connection","get_ssh_host_platform","get_ssh_host_uptime"];
async fn execute(binary: &str, name: &str, arguments: Value) -> Result<Value,String> {
    if !ALLOWED.contains(&name) { return Err("Tool not authorized".into()); }
    let mut child = Command::new(binary).arg("mcp").stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null())
        .kill_on_drop(true).spawn().map_err(|e|e.to_string())?;
    let mut stdin=child.stdin.take().ok_or("stdin unavailable")?;
    let stdout=child.stdout.take().ok_or("stdout unavailable")?;
    let mut reader=BufReader::new(stdout).lines();
    let req=json!({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":name,"arguments":arguments}});
    stdin.write_all(format!("{req}\n").as_bytes()).await.map_err(|e|e.to_string())?;
    stdin.flush().await.map_err(|e|e.to_string())?;
    let response=tokio::time::timeout(Duration::from_secs(15),reader.next_line()).await
        .map_err(|_|"Companion timeout".to_string())?
        .map_err(|e|e.to_string())?.ok_or("Companion closed connection")?;
    if response.len()>65536 {return Err("Oversized companion response".into());}
    let value:Value=serde_json::from_str(&response).map_err(|e|e.to_string())?;
    value.get("result").cloned().ok_or_else(||"Companion rejected request".into())
}
#[tokio::main]
async fn main()->Result<(),Box<dyn std::error::Error>> {
    let base=env::var("REMOTEWORKSPACE_GATEWAY_URL")?;
    if !base.starts_with("https://") && !base.starts_with("http://127.0.0.1:") && !base.starts_with("http://localhost:") {
        return Err("Gateway URL must be HTTPS except loopback development".into());
    }
    let token=env::var("REMOTEWORKSPACE_DEVICE_TOKEN")?;
    if token.len()<32 {return Err("Device token too short".into());}
    let binary=env::var("REMOTEWORKSPACE_COMPANION_BIN").unwrap_or_else(|_|"remoteworkspace".into());
    let client=reqwest::Client::builder().timeout(Duration::from_secs(25)).build()?;
    loop {
        let job=client.get(format!("{}/device/poll",base.trim_end_matches('/'))).bearer_auth(&token).send().await;
        match job {
            Ok(resp) if resp.status().is_success()=>{
                if let Ok(payload)=resp.json::<Value>().await {
                    if let (Some(id),Some(name))=(payload.get("id").and_then(Value::as_u64),payload.get("name").and_then(Value::as_str)){
                        let args=payload.get("arguments").cloned().unwrap_or_else(||json!({}));
                        let response=match execute(&binary,name,args).await {
                            Ok(value)=>value,
                            Err(error)=>json!({"isError":true,"content":[{"type":"text","text":error}]})
                        };
                        let _=client.post(format!("{}/device/result",base.trim_end_matches('/')))
                            .bearer_auth(&token).json(&json!({"id":id,"response":response})).send().await;
                    }
                }
            },
            Ok(resp) if resp.status()==reqwest::StatusCode::UNAUTHORIZED => return Err("Device authentication rejected".into()),
            _=>{}
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}
