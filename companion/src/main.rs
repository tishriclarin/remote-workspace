//! Local-first SSH Workspace companion. No arbitrary command execution tools.
//! Credentials stay on the user's device. SSH uses an embedded libssh2 engine.
mod secure_vault;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use ssh2::{CheckResult, KnownHostFileKind, Session};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufRead, Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::time::Duration;

type AppResult<T> = Result<T, String>;
const VERSION: &str = env!("CARGO_PKG_VERSION");
const MAX_OUTPUT: u64 = 4096;

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
enum GatewayMode { Client, Central }
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum BackupMode { Local, CloudSync }
impl Default for BackupMode { fn default() -> Self { Self::Local } }
#[derive(Debug, Serialize, Deserialize, Default)]
#[serde(default)]
struct BackupSettings {
    mode: BackupMode,
    directory: Option<String>,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(default)]
struct Settings {
    gateway_mode: GatewayMode,
    central_mcp_url: Option<String>,
    read_only: bool,
    require_approval_for_changes: bool,
    backup: BackupSettings,
}
impl Default for Settings {
    fn default() -> Self {
        Self { gateway_mode: GatewayMode::Client, central_mcp_url: None,
               read_only: true, require_approval_for_changes: true,
               backup: BackupSettings::default() }
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Host {
    alias: String,
    address: String,
    username: String,
    #[serde(default = "default_port")]
    port: u16,
    #[serde(default)]
    identity_file: Option<String>,
    #[serde(default)]
    known_hosts_file: Option<String>,
    #[serde(default)]
    certificate_file: Option<String>,
    #[serde(default)]
    vendor: Option<String>,
    #[serde(default)]
    protocol: Option<String>,
}
fn default_port() -> u16 { 22 }

fn home() -> PathBuf {
    env::var_os("HOME").or_else(|| env::var_os("USERPROFILE"))
        .map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."))
}
fn data_dir() -> PathBuf {
    if let Some(p) = env::var_os("SSHWORKSPACE_HOME") { return PathBuf::from(p); }
    if cfg!(windows) {
        env::var_os("APPDATA").map(PathBuf::from).unwrap_or_else(home).join("ssh-workspace")
    } else if cfg!(target_os = "macos") {
        home().join("Library/Application Support/ssh-workspace")
    } else {
        env::var_os("XDG_CONFIG_HOME").map(PathBuf::from)
            .unwrap_or_else(|| home().join(".config")).join("ssh-workspace")
    }
}
fn ensure_dir(dir: &Path) -> AppResult<()> {
    fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    #[cfg(unix)] {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(dir, fs::Permissions::from_mode(0o700))
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}
fn save<T: Serialize>(filename: &str, value: &T) -> AppResult<()> {
    let dir = data_dir();
    ensure_dir(&dir)?;
    let path = dir.join(filename);
    let mut options = OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)] {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&path).map_err(|e| e.to_string())?;
    #[cfg(unix)] {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600))
            .map_err(|e| e.to_string())?;
    }
    let body = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
    file.write_all(&body).map_err(|e| e.to_string())?;
    file.write_all(b"\n").map_err(|e| e.to_string())
}
fn read_settings() -> AppResult<Settings> {
    let path = data_dir().join("settings.json");
    if !path.exists() { return Ok(Settings::default()); }
    serde_json::from_reader(File::open(path).map_err(|e| e.to_string())?)
        .map_err(|e| format!("Invalid settings: {e}"))
}
fn read_hosts() -> AppResult<Vec<Host>> {
    let plaintext = match secure_vault::read(&data_dir())? {
        Some(bytes) => bytes,
        None => return Ok(vec![]),
    };
    let hosts: Vec<Host> = serde_json::from_slice(&plaintext)
        .map_err(|e| format!("Invalid encrypted host configuration: {e}"))?;
    for host in &hosts { validate_host(host)?; }
    Ok(hosts)
}
fn save_hosts(hosts: &[Host]) -> AppResult<()> {
    let plaintext = serde_json::to_vec_pretty(hosts).map_err(|e| e.to_string())?;
    secure_vault::write(&data_dir(), &plaintext)
}
fn valid_alias(alias: &str) -> bool {
    !alias.is_empty() && alias.len() <= 64 && alias.bytes()
        .all(|c| c.is_ascii_alphanumeric() || b"._-".contains(&c))
}
fn validate_host(h: &Host) -> AppResult<()> {
    if !valid_alias(&h.alias) || h.address.trim().is_empty() || h.address.len() > 253
       || h.username.trim().is_empty() || h.username.len() > 128 || h.port == 0 {
        return Err("Invalid host alias, address, username, or port".into());
    }
    if h.address.contains(char::is_whitespace) || h.username.contains(char::is_whitespace) {
        return Err("Host address and username must not contain whitespace".into());
    }
    if h.protocol.as_deref().is_some_and(|protocol| protocol != "ssh") {
        return Err("The native companion only supports SSH; Telnet is disabled".into());
    }
    if let Some(vendor) = &h.vendor {
        if !["linux","mikrotik","cisco","juniper","huawei","zte","other"].contains(&vendor.as_str()) {
            return Err("Unsupported vendor label".into());
        }
    }
    Ok(())
}
fn expand_home(path: &str) -> PathBuf {
    if path == "~" { return home(); }
    if let Some(suffix) = path.strip_prefix("~/") { return home().join(suffix); }
    PathBuf::from(path)
}
fn known_hosts_path(h: &Host) -> PathBuf {
    h.known_hosts_file.as_deref().map(expand_home)
        .unwrap_or_else(|| home().join(".ssh/known_hosts"))
}
fn get_host(alias: &str) -> AppResult<Host> {
    read_hosts()?.into_iter().find(|h| h.alias == alias)
        .ok_or_else(|| "Unknown saved host alias".into())
}

fn connect(h: &Host) -> AppResult<Session> {
    let settings = read_settings()?;
    if settings.gateway_mode != GatewayMode::Client {
        return Err("Central gateway selected: connect ChatGPT to your configured HTTPS MCP endpoint instead".into());
    }
    let endpoints = (h.address.as_str(), h.port).to_socket_addrs()
        .map_err(|_| "Could not resolve SSH host".to_string())?;
    let mut stream: Option<TcpStream> = None;
    for addr in endpoints.take(8) {
        if let Ok(s) = TcpStream::connect_timeout(&addr, Duration::from_secs(6)) {
            stream = Some(s); break;
        }
    }
    let stream = stream.ok_or_else(|| "SSH connection unavailable".to_string())?;
    stream.set_read_timeout(Some(Duration::from_secs(12))).map_err(|e| e.to_string())?;
    stream.set_write_timeout(Some(Duration::from_secs(12))).map_err(|e| e.to_string())?;
    let mut session = Session::new().map_err(|e| e.to_string())?;
    session.set_timeout(12_000);
    session.set_tcp_stream(stream);
    session.handshake().map_err(|_| "SSH handshake failed".to_string())?;
    let (server_key, _) = session.host_key().ok_or("SSH server did not present a host key")?;
    let mut known = session.known_hosts().map_err(|e| e.to_string())?;
    let kh_file = known_hosts_path(h);
    known.read_file(&kh_file, KnownHostFileKind::OpenSSH)
        .map_err(|_| format!("Trusted host-key file not found or unreadable: {}", kh_file.display()))?;
    match known.check_port(&h.address, h.port, server_key) {
        CheckResult::Match => {},
        _ => return Err("SSH host-key verification failed. Verify the fingerprint out of band and pin it locally".into()),
    }
    if let Some(key) = &h.identity_file {
        session.userauth_pubkey_file(&h.username, None, &expand_home(key), None)
            .map_err(|_| "SSH key authentication failed".to_string())?;
    } else {
        let mut agent = session.agent().map_err(|e| e.to_string())?;
        agent.connect().map_err(|_| "SSH agent is unavailable; configure identity_file".to_string())?;
        agent.list_identities().map_err(|e| e.to_string())?;
        let mut authenticated = false;
        for identity in agent.identities().map_err(|e| e.to_string())? {
            if agent.userauth(&h.username, &identity).is_ok() { authenticated = true; break; }
        }
        if !authenticated { return Err("SSH agent authentication failed".into()); }
    }
    if !session.authenticated() { return Err("SSH authentication failed".into()); }
    Ok(session)
}
fn execute_fixed(h: &Host, probe: &str) -> AppResult<String> {
    // Never accept a command string from an MCP request; these probes are fixed.
    let command = match probe {
        "platform" => "uname -s; uname -m",
        "uptime" => "cat /proc/uptime",
        _ => return Err("Unsupported diagnostic probe".into()),
    };
    let session = connect(h)?;
    let mut channel = session.channel_session().map_err(|_| "Cannot open SSH channel")?;
    channel.exec(command).map_err(|_| "SSH diagnostic command failed")?;
    let mut output = String::new();
    channel.take(MAX_OUTPUT + 1).read_to_string(&mut output)
        .map_err(|_| "SSH response is not valid text")?;
    if output.len() as u64 > MAX_OUTPUT { return Err("SSH response exceeded size limit".into()); }
    Ok(output)
}
fn gateway_status() -> AppResult<Value> {
    let s = read_settings()?;
    Ok(json!({
        "version": VERSION,
        "gateway_mode": s.gateway_mode,
        "central_mcp_url": s.central_mcp_url,
        "read_only": s.read_only,
        "require_approval_for_changes": s.require_approval_for_changes,
        "platform": env::consts::OS,
        "architecture": env::consts::ARCH,
        "config_directory": data_dir().display().to_string(),
        "transport": "local_stdio",
        "inventory_encrypted": secure_vault::status(&data_dir())["encrypted_inventory_present"],
        "backup_mode": s.backup.mode,
        "backup_configured": s.backup.directory.is_some(),
        "connection_route": "host_managed_local_mcp",
        "requires_additional_openai_api_key": false,
        "requires_tunnel_for_local_host_execution": false,
        "requires_supported_local_mcp_host": true,
        "remote_tunnel_connected": null
    }))
}
fn installation_guidance() -> Value {
    json!({
        "platform": env::consts::OS,
        "architecture": env::consts::ARCH,
        "build_artifacts": "https://github.com/tishriclarin/ssh-workspace/actions/workflows/companion-build.yml",
        "instructions": "Choose a verified build matching your OS and CPU, approve the installer, then configure the native MCP companion. Browser extensions and mobile apps require their own approved installations.",
        "cannot_silently_install": true,
        "browser_mcp_tunnel_included": false,
        "default_route": "host_managed_local_mcp",
        "local_chatgpt_requires_additional_pairing": false,
        "web_mobile_without_local_mcp_host": "not_supported_without_explicit_connection",
        "supported_tunnel_client": "https://platform.openai.com/settings/organization/tunnels",
        "android_app_included": false,
        "ios_app_included": false
    })
}
fn tools() -> Vec<Value> {
    let alias_schema = json!({"type":"object","properties":{"alias":{"type":"string"}},"required":["alias"],"additionalProperties":false});
    vec![
        json!({"name":"get_gateway_status","description":"Read local-first gateway settings and connectivity status.","inputSchema":{"type":"object","properties":{},"additionalProperties":false},"annotations":{"readOnlyHint":true}}),
        json!({"name":"get_installation_options","description":"Show approved native-companion installation paths.","inputSchema":{"type":"object","properties":{},"additionalProperties":false},"annotations":{"readOnlyHint":true}}),
        json!({"name":"get_vault_status","description":"Read encryption and configured backup status without exposing secrets.","inputSchema":{"type":"object","properties":{},"additionalProperties":false},"annotations":{"readOnlyHint":true}}),
        json!({"name":"list_ssh_hosts","description":"List saved host aliases only; no credentials returned.","inputSchema":{"type":"object","properties":{},"additionalProperties":false},"annotations":{"readOnlyHint":true}}),
        json!({"name":"check_ssh_connection","description":"Authenticate to a pinned SSH host without executing a command.","inputSchema":alias_schema,"annotations":{"readOnlyHint":true}}),
        json!({"name":"get_ssh_host_platform","description":"Read OS and CPU architecture from a pinned SSH host.","inputSchema":{"type":"object","properties":{"alias":{"type":"string"}},"required":["alias"],"additionalProperties":false},"annotations":{"readOnlyHint":true}}),
        json!({"name":"get_ssh_host_uptime","description":"Read Linux uptime from a pinned SSH host.","inputSchema":{"type":"object","properties":{"alias":{"type":"string"}},"required":["alias"],"additionalProperties":false},"annotations":{"readOnlyHint":true}})
    ]
}
fn tool_call(params: &Value) -> AppResult<Value> {
    let name = params.get("name").and_then(Value::as_str).ok_or("Missing tool name")?;
    let args = params.get("arguments").cloned().unwrap_or_else(|| json!({}));
    let alias = || -> AppResult<&str> {
        let value = args.get("alias").and_then(Value::as_str).ok_or("Missing host alias")?;
        if !valid_alias(value) { return Err("Invalid host alias".into()); }
        Ok(value)
    };
    match name {
        "get_gateway_status" => gateway_status(),
        "get_installation_options" => Ok(installation_guidance()),
        "get_vault_status" => Ok(json!({
            "vault": secure_vault::status(&data_dir()),
            "backup_mode": read_settings()?.backup.mode,
            "backup_configured": read_settings()?.backup.directory.is_some()
        })),
        "list_ssh_hosts" => Ok(json!({"aliases": read_hosts()?.iter().map(|h| &h.alias).collect::<Vec<_>>()})),
        "check_ssh_connection" => {
            let h = get_host(alias()?)?;
            connect(&h)?;
            Ok(json!({"alias":h.alias,"status":"connected"}))
        },
        "get_ssh_host_platform" => {
            let h = get_host(alias()?)?;
            let output = execute_fixed(&h,"platform")?;
            let mut lines = output.lines();
            Ok(json!({"alias":h.alias,"system":lines.next().unwrap_or("").trim(),"architecture":lines.next().unwrap_or("").trim()}))
        },
        "get_ssh_host_uptime" => {
            let h = get_host(alias()?)?;
            let output = execute_fixed(&h,"uptime")?;
            let uptime: f64 = output.split_whitespace().next().ok_or("Invalid uptime response")?
                .parse().map_err(|_| "Invalid uptime number")?;
            if !uptime.is_finite() || uptime < 0.0 { return Err("Invalid uptime response".into()); }
            Ok(json!({"alias":h.alias,"uptime_seconds":uptime.floor() as u64}))
        },
        _ => Err("Unknown or unauthorized tool".into())
    }
}
fn handle_mcp(req: &Value) -> Option<Value> {
    let id = req.get("id")?.clone();
    let method = req.get("method").and_then(Value::as_str).unwrap_or("");
    let response = match method {
        "initialize" => json!({"protocolVersion":"2025-03-26","capabilities":{"tools":{"listChanged":false}},"serverInfo":{"name":"ssh-workspace-companion","version":VERSION}}),
        "ping" => json!({}),
        "tools/list" => json!({"tools":tools()}),
        "tools/call" => {
            match tool_call(&req["params"]) {
                Ok(result) => json!({"content":[{"type":"text","text":result.to_string()}],"isError":false}),
                Err(error) => json!({"content":[{"type":"text","text":error}],"isError":true}),
            }
        },
        _ => return Some(json!({"jsonrpc":"2.0","id":id,"error":{"code":-32601,"message":"Method not found"}}))
    };
    Some(json!({"jsonrpc":"2.0","id":id,"result":response}))
}
fn mcp_stdio() -> AppResult<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    for line in stdin.lock().lines() {
        let line = line.map_err(|e| e.to_string())?;
        let value: Value = match serde_json::from_str(&line) {
            Ok(value) => value,
            Err(_) => continue,
        };
        if let Some(reply) = handle_mcp(&value) {
            writeln!(stdout,"{reply}").map_err(|e| e.to_string())?;
            stdout.flush().map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}
fn native_messaging() -> AppResult<()> {
    // Browser native messaging is limited to status and installation guidance.
    // Do not expose SSH operations to arbitrary browser extensions or webpages.
    let mut input = io::stdin().lock();
    let mut output = io::stdout().lock();
    loop {
        let mut size = [0u8; 4];
        if input.read_exact(&mut size).is_err() { break; }
        let count = u32::from_ne_bytes(size) as usize;
        if count > 65536 { return Err("Oversized native-messaging frame".into()); }
        let mut payload = vec![0u8; count];
        input.read_exact(&mut payload).map_err(|e| e.to_string())?;
        let request: Value = serde_json::from_slice(&payload).unwrap_or(json!({}));
        let reply = match request.get("action").and_then(Value::as_str) {
            Some("status") => gateway_status().unwrap_or_else(|_| json!({"error":"Settings unavailable"})),
            Some("installation") => installation_guidance(),
            _ => json!({"error":"Unsupported action"})
        };
        let body = serde_json::to_vec(&reply).map_err(|e| e.to_string())?;
        output.write_all(&(body.len() as u32).to_ne_bytes()).map_err(|e| e.to_string())?;
        output.write_all(&body).map_err(|e| e.to_string())?;
        output.flush().map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn save_native_manifest(path: &Path, manifest: &Value) -> AppResult<()> {
    let mut options = OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)] {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).map_err(|e| e.to_string())?;
    serde_json::to_writer_pretty(&mut file, manifest).map_err(|e| e.to_string())
}
fn register_chromium_host(extension_id: &str) -> AppResult<()> {
    // A Chrome extension ID is 32 lowercase characters a through p.
    if extension_id.len() != 32 || !extension_id.bytes().all(|b| (b'a'..=b'p').contains(&b)) {
        return Err("Supply the 32-letter extension ID shown by Chromium after installation".into());
    }
    let executable = env::current_exe().map_err(|e| e.to_string())?;
    let manifest = json!({
        "name": "com.sshworkspace.companion",
        "description": "SSH Workspace local companion status",
        "path": executable.to_string_lossy().to_string(),
        "type": "stdio",
        "allowed_origins": [format!("chrome-extension://{extension_id}/")]
    });
    #[cfg(windows)]
    {
        use std::process::Command;
        let dir = data_dir().join("native-host");
        ensure_dir(&dir)?;
        let path = dir.join("com.sshworkspace.companion.json");
        save_native_manifest(&path, &manifest)?;
        let key = r"HKCU\Software\Google\Chrome\NativeMessagingHosts\com.sshworkspace.companion";
        let result = Command::new("reg")
            .args(["add", key, "/ve", "/t", "REG_SZ", "/d"])
            .arg(path.to_string_lossy().to_string()).arg("/f")
            .status().map_err(|e| e.to_string())?;
        if !result.success() { return Err("Could not register Chrome native messaging host".into()); }
    }
    #[cfg(target_os = "macos")]
    {
        let dir = home().join("Library/Application Support/Google/Chrome/NativeMessagingHosts");
        ensure_dir(&dir)?;
        save_native_manifest(&dir.join("com.sshworkspace.companion.json"), &manifest)?;
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        for dir in [
            home().join(".config/google-chrome/NativeMessagingHosts"),
            home().join(".config/chromium/NativeMessagingHosts"),
        ] {
            ensure_dir(&dir)?;
            save_native_manifest(&dir.join("com.sshworkspace.companion.json"), &manifest)?;
        }
    }
    println!("Registered native host for extension {extension_id} (status only).");
    Ok(())
}


fn tunnel_id_valid(value: &str) -> bool {
    value.starts_with("tunnel_") && value.len() >= 20 && value.len() <= 128 &&
        value[7..].bytes().all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
}
fn tunnel_command() -> AppResult<String> {
    let binary = env::current_exe().map_err(|error| error.to_string())?;
    let raw = binary.to_string_lossy();
    #[cfg(windows)] {
        if raw.contains('"') { return Err("Invalid binary path".into()); }
        Ok(format!("\"{}\" mcp", raw))
    }
    #[cfg(not(windows))] {
        Ok(format!("'{}' mcp", raw.replace('\'', "'\\''")))
    }
}
fn tunnel_action(args: &[String]) -> AppResult<()> {
    use std::process::Command;
    let profile = "ssh-workspace-local";
    let action = args.get(2).map(String::as_str).unwrap_or("");
    let mut cmd = Command::new("tunnel-client");
    match action {
        "init" => {
            if args.len() != 4 || !tunnel_id_valid(&args[3]) {
                return Err("Usage: sshworkspace tunnel init tunnel_<id>".into());
            }
            cmd.args(["init", "--sample", "sample_mcp_stdio_local", "--profile",
                      profile, "--tunnel-id", &args[3], "--mcp-command", &tunnel_command()?]);
        }
        "doctor" if args.len() == 3 => {
            cmd.args(["doctor", "--profile", profile, "--explain"]);
        }
        "run" if args.len() == 3 => {
            cmd.args(["run", "--profile", profile]);
        }
        _ => return Err("Usage: sshworkspace tunnel init TUNNEL_ID | doctor | run".into())
    }
    let result = cmd.status().map_err(|_| {
        "The official OpenAI tunnel-client is not installed. Obtain the supported binary from https://platform.openai.com/settings/organization/tunnels".to_string()
    })?;
    if !result.success() { return Err(format!("Official tunnel-client returned status: {result}")); }
    Ok(())
}


fn user_install_directory() -> PathBuf {
    if let Some(root) = env::var_os("SSHWORKSPACE_INSTALL_ROOT") {
        return PathBuf::from(root);
    }
    if cfg!(windows) {
        env::var_os("LOCALAPPDATA").map(PathBuf::from)
            .unwrap_or_else(home).join("SSHWorkspace/bin")
    } else if cfg!(target_os = "macos") {
        home().join("Library/Application Support/SSHWorkspace/bin")
    } else {
        env::var_os("XDG_DATA_HOME").map(PathBuf::from)
            .unwrap_or_else(|| home().join(".local/share")).join("ssh-workspace/bin")
    }
}
fn install_for_user() -> AppResult<()> {
    use std::process;
    let source = env::current_exe().map_err(|e| e.to_string())?;
    let target_dir = user_install_directory();
    ensure_dir(&target_dir)?;
    let name = if cfg!(windows) { "sshworkspace.exe" } else { "sshworkspace" };
    let target = target_dir.join(name);
    if source == target {
        println!("SSH Workspace is already installed at {}", target.display());
        return Ok(());
    }
    if target.is_symlink() {
        return Err("Refusing to replace a symlinked executable".into());
    }
    // Copy into a new file in the same directory; never write into a privileged OS path.
    let temporary = target_dir.join(format!(".sshworkspace-install-{}.tmp", process::id()));
    let result = (|| -> AppResult<()> {
        let mut existing = File::open(&source).map_err(|e| e.to_string())?;
        let mut opts = OpenOptions::new();
        opts.write(true).create_new(true);
        #[cfg(unix)] {
            use std::os::unix::fs::OpenOptionsExt;
            opts.mode(0o700);
        }
        let mut next = opts.open(&temporary).map_err(|e| e.to_string())?;
        io::copy(&mut existing, &mut next).map_err(|e| e.to_string())?;
        next.sync_all().map_err(|e| e.to_string())?;
        #[cfg(unix)] {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&temporary, fs::Permissions::from_mode(0o700))
                .map_err(|e| e.to_string())?;
        }
        fs::rename(&temporary, &target).map_err(|e| format!(
            "Cannot replace executable (close a running copy first): {e}"
        ))?;
        Ok(())
    })();
    if result.is_err() { let _ = fs::remove_file(&temporary); }
    result?;
    println!("Installed SSH Workspace v{VERSION} for this OS user at {}", target.display());
    println!("No administrator privileges or other software installations were requested.");
    Ok(())
}


fn vault_command(args: &[String]) -> AppResult<()> {
    match args.get(2).map(String::as_str) {
        Some("status") if args.len() == 3 => {
            println!("{}", serde_json::to_string_pretty(&secure_vault::status(&data_dir()))
                .map_err(|e|e.to_string())?);
            Ok(())
        },
        Some("migrate") if args.len() == 3 => {
            let old = data_dir().join("hosts.json");
            let data = fs::read(&old).map_err(|_| "No legacy hosts.json available")?;
            let hosts: Vec<Host> = serde_json::from_slice(&data)
                .map_err(|_| "Legacy host profiles are invalid")?;
            for host in &hosts { validate_host(host)?; }
            secure_vault::migrate_legacy(&data_dir())?;
            println!("Migrated {} profiles into authenticated encrypted vault.", hosts.len());
            println!("Review and remove old hosts.json (still plaintext) when satisfied.");
            Ok(())
        },
        _ => Err("Usage: sshworkspace vault status | migrate".into())
    }
}
fn backup_command(args: &[String]) -> AppResult<()> {
    match args.get(2).map(String::as_str) {
        Some("status") if args.len() == 3 => {
            let s = read_settings()?;
            println!("{}", serde_json::to_string_pretty(&json!({
                "mode": s.backup.mode, "destination_configured": s.backup.directory.is_some(),
                "destination": s.backup.directory,
                "encrypted": true, "includes_key": false
            })).map_err(|e|e.to_string())?);
            Ok(())
        },
        Some("configure") if args.len() == 5 => {
            let mode = match args[3].as_str() {
                "local" => BackupMode::Local,
                "cloud-sync" => BackupMode::CloudSync,
                _ => return Err("Mode must be local or cloud-sync".into())
            };
            if args[4].trim().is_empty() { return Err("Backup directory must not be empty".into()); }
            let directory = expand_home(&args[4]);
            if directory == data_dir() {
                return Err("Use a separate backup directory, not the local vault directory".into());
            }
            ensure_dir(&directory)?;
            let mut s = read_settings()?;
            s.backup.mode = mode;
            s.backup.directory = Some(directory.to_string_lossy().to_string());
            save("settings.json", &s)?;
            println!("Encrypted backup destination configured at {}", directory.display());
            if mode == BackupMode::CloudSync {
                println!("Ensure a trusted cloud synchronization client syncs this folder. No cloud upload API is built in.");
            }
            Ok(())
        },
        Some("run") if args.len() == 4 => {
            let s = read_settings()?;
            let folder = s.backup.directory.ok_or(
                "Configure a backup destination first: sshworkspace backup configure local|cloud-sync DIR")?;
            let mode = match s.backup.mode {
                BackupMode::Local => "local", BackupMode::CloudSync => "cloud-sync"
            };
            let receipt = secure_vault::backup(&data_dir(), &PathBuf::from(folder), &args[3], mode)?;
            println!("{}", serde_json::to_string_pretty(&receipt).map_err(|e|e.to_string())?);
            Ok(())
        },
        Some("restore") if args.len() == 5 && args[4] == "--confirm" => {
            secure_vault::restore(&data_dir(), &expand_home(&args[3]))?;
            for host in read_hosts()? { validate_host(&host)?; }
            println!("Encrypted backup restored after explicit confirmation. Previous ciphertext retained for local recovery.");
            Ok(())
        },
        _ => Err("Usage: sshworkspace backup status | configure local|cloud-sync DIR | run DESCRIPTION | restore FILE --confirm".into())
    }
}

fn init() -> AppResult<()> {
    let dir = data_dir();
    ensure_dir(&dir)?;
    if !dir.join("settings.json").exists() { save("settings.json",&Settings::default())?; }
    secure_vault::initialize(&dir)?;
    println!("SSH Workspace local-first configuration initialized at {}",dir.display());
    println!("Pin SSH server host keys in ~/.ssh/known_hosts before connecting.");
    println!("Register this binary as a local stdio MCP server with: sshworkspace mcp");
    Ok(())
}
fn run() -> AppResult<()> {
    let args: Vec<String> = env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("mcp") => mcp_stdio(),
        Some("native-messaging") => native_messaging(),
        Some(v) if v.starts_with("chrome-extension://") => native_messaging(),
        Some("register-chrome") => register_chromium_host(args.get(2).ok_or("Missing extension ID")?),
        Some("tunnel") => tunnel_action(&args),
        Some("setup") => init(),
        Some("vault") => vault_command(&args),
        Some("backup") => backup_command(&args),
        Some("doctor") | Some("status") => {
            println!("{}",serde_json::to_string_pretty(&gateway_status()?).map_err(|e| e.to_string())?);
            println!("Saved SSH host profiles: {}", read_hosts()?.len());
            Ok(())
        },
        Some("install") if args.len() == 3 && args[2] == "--user" => install_for_user(),
        Some("install") => {
            println!("{}", serde_json::to_string_pretty(&installation_guidance()).map_err(|e|e.to_string())?);
            Ok(())
        },
        Some("gateway") => {
            let mut settings = read_settings()?;
            match args.get(2).map(String::as_str) {
                Some("client") if args.len() == 3 => { settings.gateway_mode = GatewayMode::Client; },
                Some("central") if args.len() == 4 => {
                    let url = &args[3];
                    if !url.starts_with("https://") || url.contains('@') || url.len() > 2048 {
                        return Err("Central MCP gateway must be a valid HTTPS URL without embedded credentials".into());
                    }
                    settings.gateway_mode = GatewayMode::Central;
                    settings.central_mcp_url = Some(url.clone());
                },
                _ => return Err("Usage: sshworkspace gateway client | central https://gateway.example/mcp".into())
            }
            save("settings.json",&settings)?;
            println!("Gateway mode: {:?}",settings.gateway_mode);
            Ok(())
        },
        Some("host") if args.get(2).map(String::as_str) == Some("add") => {
            if args.len() < 6 || args.len() > 8 {
                return Err("Usage: sshworkspace host add ALIAS ADDRESS USERNAME [PORT] [IDENTITY_FILE]".into());
            }
            let host = Host {
                alias: args[3].clone(), address: args[4].clone(), username: args[5].clone(),
                port: if let Some(p) = args.get(6) { p.parse().map_err(|_| "Invalid SSH port")? } else {22},
                identity_file: args.get(7).cloned(), known_hosts_file: None,
                certificate_file: None, vendor: None, protocol: None
            };
            validate_host(&host)?;
            let mut hosts = read_hosts()?;
            if hosts.iter().any(|h| h.alias == host.alias) { return Err("Alias already exists".into()); }
            hosts.push(host);
            save_hosts(&hosts)?;
            println!("Host alias saved. SSH connection requires independently verified pinned host key.");
            Ok(())
        },
        _ => {
            println!("SSH Workspace companion v{VERSION}");
            println!("  setup          Create local-first settings and host inventory");
            println!("  doctor         Check local settings and host count");
            println!("  gateway client | central HTTPS_URL");
            println!("  host add ALIAS ADDRESS USERNAME [PORT] [IDENTITY_FILE]");
            println!("  vault status | migrate  Encrypted device host inventory");
            println!("  backup status | configure local|cloud-sync DIR | run DESCRIPTION");
            println!("  backup restore FILE --confirm");
            println!("  mcp            Run local stdio MCP server");
            println!("  native-messaging  Browser extension status host (no SSH command API)");
            println!("  register-chrome EXTENSION_ID  Restrict native-host status to this extension");
            println!("  tunnel init ID | doctor | run  Official OpenAI Secure MCP Tunnel integration");
            println!("  install        Print platform-specific setup guidance");
            println!("  install --user Copy the approved native binary to a private user-owned directory");
            Ok(())
        }
    }
}
fn main() {
    if let Err(error) = run() {
        eprintln!("sshworkspace: {error}");
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn local_first_read_only_defaults() {
        let defaults = Settings::default();
        assert_eq!(defaults.gateway_mode, GatewayMode::Client);
        assert!(defaults.read_only);
        assert!(defaults.require_approval_for_changes);
        assert!(defaults.central_mcp_url.is_none());
    }
    #[test]
    fn aliases_are_bounded_and_safe() {
        assert!(valid_alias("branch-router_1"));
        for alias in ["", "../etc/passwd", "bad alias", "a/b", "x\n"] { assert!(!valid_alias(alias)); }
    }
    #[test]
    fn backup_defaults_local_without_destination() {
        let default = Settings::default();
        assert_eq!(default.backup.mode, BackupMode::Local);
        assert!(default.backup.directory.is_none());
    }
    #[test]
    fn no_arbitrary_command_tool() {
        assert!(tools().iter().all(|t|t["name"] != "execute_command"));
        assert!(tool_call(&json!({"name":"run_shell","arguments":{"command":"whoami"}})).is_err());
    }
    #[test]
    fn native_install_path_is_user_scoped() {
        let path = user_install_directory();
        assert!(!path.as_os_str().is_empty());
        assert!(path.to_string_lossy().contains("ssh-workspace")
            || path.to_string_lossy().contains("SSHWorkspace")
            || env::var_os("SSHWORKSPACE_INSTALL_ROOT").is_some());
    }
    #[test]
    fn tunnel_id_input_is_bounded() {
        assert!(tunnel_id_valid("tunnel_0123456789abcdef0123456789abcdef"));
        assert!(!tunnel_id_valid("tunnel_;rm -rf /"));
        assert!(!tunnel_id_valid("unknown"));
    }
    #[test]
    fn notifications_have_no_response() {
        assert!(handle_mcp(&json!({"jsonrpc":"2.0","method":"notifications/initialized"})).is_none());
    }
}
