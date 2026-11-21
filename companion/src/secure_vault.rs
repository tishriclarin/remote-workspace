//! Encrypted device inventory and ciphertext-only backup.
//! The local 256-bit key is deliberately NOT part of cloud-synced backups.
//! OS user permissions protect that key; OS keychain migration is planned.
use chacha20poly1305::{
    aead::{Aead, AeadCore, KeyInit, OsRng, rand_core::RngCore},
    Key, XChaCha20Poly1305, XNonce,
};
use chrono::{Local, Utc};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use tempfile::NamedTempFile;

const MAGIC: &[u8] = b"SSHWSVLT1";
const NONCE_LEN: usize = 24;
const KEY_LEN: usize = 32;
const MAX_VAULT_SIZE: u64 = 16 * 1024 * 1024;
type Result<T> = std::result::Result<T, String>;

fn key_path(root: &Path) -> PathBuf { root.join("vault.key") }
fn vault_path(root: &Path) -> PathBuf { root.join("hosts.vault") }

fn owner_dir(root: &Path) -> Result<()> {
    fs::create_dir_all(root).map_err(|e| e.to_string())?;
    #[cfg(unix)] {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn load_key(root: &Path) -> Result<[u8; KEY_LEN]> {
    let path = key_path(root);
    if path.is_symlink() { return Err("Refusing symlinked vault key".into()); }
    #[cfg(unix)] {
        use std::os::unix::fs::PermissionsExt;
        let md = fs::metadata(&path).map_err(|_| "Vault key unavailable".to_string())?;
        if md.permissions().mode() & 0o077 != 0 {
            return Err("Vault key permissions are not owner-only".into());
        }
    }
    let raw = fs::read(&path).map_err(|_| "Vault key unavailable".to_string())?;
    if raw.len() != KEY_LEN { return Err("Vault key has invalid length".into()); }
    let mut key = [0_u8; KEY_LEN];
    key.copy_from_slice(&raw);
    Ok(key)
}

fn initialize_key(root: &Path) -> Result<()> {
    owner_dir(root)?;
    let path = key_path(root);
    if path.exists() { load_key(root)?; return Ok(()); }
    let mut key = [0_u8; KEY_LEN];
    OsRng.fill_bytes(&mut key);
    let mut opts = OpenOptions::new();
    opts.write(true).create_new(true);
    #[cfg(unix)] {
        use std::os::unix::fs::OpenOptionsExt;
        opts.mode(0o600);
    }
    let mut f = opts.open(&path).map_err(|e| e.to_string())?;
    f.write_all(&key).map_err(|e| e.to_string())?;
    f.sync_all().map_err(|e| e.to_string())
}

fn encrypt(root: &Path, plaintext: &[u8]) -> Result<Vec<u8>> {
    if plaintext.len() as u64 > MAX_VAULT_SIZE { return Err("Inventory exceeds size limit".into()); }
    let key = load_key(root)?;
    let cipher = XChaCha20Poly1305::new(Key::from_slice(&key));
    let nonce = XChaCha20Poly1305::generate_nonce(&mut OsRng);
    let ciphertext = cipher.encrypt(&nonce, plaintext)
        .map_err(|_| "Cannot encrypt inventory")?;
    let mut output = Vec::with_capacity(MAGIC.len() + NONCE_LEN + ciphertext.len());
    output.extend_from_slice(MAGIC);
    output.extend_from_slice(&nonce);
    output.extend_from_slice(&ciphertext);
    Ok(output)
}

fn decrypt(root: &Path, payload: &[u8]) -> Result<Vec<u8>> {
    if payload.len() < MAGIC.len() + NONCE_LEN + 16
        || !payload.starts_with(MAGIC) {
        return Err("Invalid encrypted vault format".into());
    }
    if payload.len() as u64 > MAX_VAULT_SIZE + 1024 {
        return Err("Encrypted vault exceeds size limit".into());
    }
    let key = load_key(root)?;
    let cipher = XChaCha20Poly1305::new(Key::from_slice(&key));
    cipher.decrypt(
        XNonce::from_slice(&payload[MAGIC.len()..MAGIC.len() + NONCE_LEN]),
        &payload[MAGIC.len() + NONCE_LEN..]
    ).map_err(|_| "Vault integrity verification failed or wrong local key".into())
}

fn atomic_private_file(path: &Path, content: &[u8]) -> Result<()> {
    let parent = path.parent().ok_or("No parent directory")?;
    owner_dir(parent)?;
    if path.is_symlink() { return Err("Refusing to overwrite symlink".into()); }
    let mut temp = NamedTempFile::new_in(parent).map_err(|e| e.to_string())?;
    temp.write_all(content).map_err(|e| e.to_string())?;
    temp.as_file().sync_all().map_err(|e| e.to_string())?;
    temp.persist(path).map_err(|e| format!("Cannot commit encrypted vault file: {}", e.error))?;
    Ok(())
}

pub fn initialize(root: &Path) -> Result<()> {
    owner_dir(root)?;
    if !vault_path(root).exists() && root.join("hosts.json").exists() {
        return Err("Legacy hosts.json contains plaintext host data. Run 'sshworkspace vault migrate' before setup".into());
    }
    if vault_path(root).exists() && !key_path(root).exists() {
        return Err("Existing encrypted vault key missing. Refusing to generate an unusable new key".into());
    }
    initialize_key(root)?;
    if !vault_path(root).exists() {
        atomic_private_file(&vault_path(root), &encrypt(root, b"[]")?)?;
    }
    let _ = read(root)?;
    Ok(())
}

pub fn read(root: &Path) -> Result<Option<Vec<u8>>> {
    if !vault_path(root).exists() {
        if root.join("hosts.json").exists() {
            return Err("Legacy plaintext host inventory detected; run 'sshworkspace vault migrate'".into());
        }
        return Ok(None);
    }
    let metadata = fs::metadata(vault_path(root)).map_err(|e| e.to_string())?;
    if metadata.len() > MAX_VAULT_SIZE + 1024 { return Err("Vault too large".into()); }
    let bytes = fs::read(vault_path(root)).map_err(|e| e.to_string())?;
    Ok(Some(decrypt(root, &bytes)?))
}

pub fn write(root: &Path, plaintext: &[u8]) -> Result<()> {
    if !vault_path(root).exists() {
        initialize(root)?;
    }
    let cipher = encrypt(root, plaintext)?;
    atomic_private_file(&vault_path(root), &cipher)
}

pub fn migrate_legacy(root: &Path) -> Result<()> {
    let legacy = root.join("hosts.json");
    if vault_path(root).exists() { return Err("Encrypted vault already exists; cannot migrate over it".into()); }
    if !legacy.is_file() || legacy.is_symlink() { return Err("No safe legacy hosts.json file to migrate".into()); }
    let plaintext = fs::read(&legacy).map_err(|e| e.to_string())?;
    let parsed: Vec<Value> = serde_json::from_slice(&plaintext)
        .map_err(|_| "Legacy inventory is not valid JSON host list")?;
    for host in &parsed {
        if !host.get("alias").and_then(Value::as_str).is_some() {
            return Err("Legacy host profile lacks alias".into());
        }
    }
    owner_dir(root)?;
    initialize_key(root)?;
    atomic_private_file(&vault_path(root), &encrypt(root, &plaintext)?)?;
    let confirmation = decrypt(root, &fs::read(vault_path(root)).map_err(|e| e.to_string())?)?;
    if confirmation != plaintext { return Err("Legacy migration verification failed".into()); }
    // Keep an explicit plaintext legacy file for owner-managed removal;
    // NEVER silently delete an inventory without user consent.
    eprintln!("WARNING: hosts.json remains unencrypted. Remove or securely retire it after confirming the migrated vault.");
    Ok(())
}

fn sha256(content: &[u8]) -> String {
    format!("{:x}", Sha256::digest(content))
}

fn safe_slug(description: &str) -> Result<String> {
    if description.trim().is_empty() || description.len() > 200 ||
        description.chars().any(char::is_control) {
        return Err("Backup description must be 1-200 printable characters".into());
    }
    let slug: String = description.to_lowercase().chars()
        .map(|ch| if ch.is_ascii_alphanumeric() { ch } else { '-' })
        .collect::<String>()
        .split('-').filter(|s| !s.is_empty())
        .collect::<Vec<_>>().join("-");
    Ok(slug.chars().take(50).collect::<String>().trim_matches('-').to_string())
}

pub fn backup(root: &Path, destination: &Path, description: &str, mode: &str) -> Result<Value> {
    let _ = read(root)?.ok_or("Vault not initialized")?;
    let slug = safe_slug(description)?;
    let now = Local::now();
    let stamp = now.format("%Y%m%d-%H%M%S").to_string();
    let random = OsRng.next_u32();
    let identifier = format!("{}-{}-{:08x}", stamp,
        if slug.is_empty() {"vault"} else {&slug}, random);
    owner_dir(destination)?;
    let bytes = fs::read(vault_path(root)).map_err(|e| e.to_string())?;
    let archive = destination.join(format!("sshworkspace-{}.vault", identifier));
    let mut opts = OpenOptions::new();
    opts.write(true).create_new(true);
    #[cfg(unix)] {
        use std::os::unix::fs::OpenOptionsExt;
        opts.mode(0o600);
    }
    let mut f = opts.open(&archive).map_err(|e| e.to_string())?;
    f.write_all(&bytes).map_err(|e| e.to_string())?;
    f.sync_all().map_err(|e| e.to_string())?;
    let receipt = json!({
        "backup_name": archive.file_name().and_then(|x|x.to_str()).unwrap_or(""),
        "saved_at_local": now.to_rfc3339(),
        "saved_at_utc": Utc::now().to_rfc3339(),
        "description": description,
        "mode": mode,
        "encrypted": true,
        "key_included": false,
        "sha256": sha256(&bytes)
    });
    atomic_private_file(&destination.join(format!("sshworkspace-{}.json", identifier)),
                        serde_json::to_string_pretty(&receipt).map_err(|e|e.to_string())?.as_bytes())?;
    Ok(receipt)
}

pub fn restore(root: &Path, backup_file: &Path) -> Result<()> {
    if backup_file.is_symlink() || backup_file.extension().and_then(|x|x.to_str()) != Some("vault") {
        return Err("Choose a regular .vault backup, not a symlink".into());
    }
    let ciphertext = fs::read(backup_file).map_err(|e|e.to_string())?;
    let plaintext = decrypt(root, &ciphertext)?;
    let _: Vec<Value> = serde_json::from_slice(&plaintext)
        .map_err(|_| "Backup does not contain a JSON host inventory")?;
    if vault_path(root).exists() {
        let original = fs::read(vault_path(root)).map_err(|e|e.to_string())?;
        let recovery = root.join(format!("hosts.pre-restore-{}.vault", Utc::now().format("%Y%m%d%H%M%S")));
        let mut opts = OpenOptions::new();
        opts.create_new(true).write(true);
        #[cfg(unix)] {
            use std::os::unix::fs::OpenOptionsExt;
            opts.mode(0o600);
        }
        let mut f = opts.open(recovery).map_err(|e|e.to_string())?;
        f.write_all(&original).map_err(|e|e.to_string())?;
        f.sync_all().map_err(|e|e.to_string())?;
    }
    atomic_private_file(&vault_path(root), &ciphertext)
}

pub fn status(root: &Path) -> Value {
    json!({
        "encrypted_inventory_present": vault_path(root).is_file(),
        "local_key_present": key_path(root).is_file(),
        "legacy_plaintext_present": root.join("hosts.json").is_file(),
        "cipher": "XChaCha20-Poly1305",
        "key_storage": "local_owner_only_file",
        "backup_key_exported": false
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn roundtrip_and_integrity_detection() {
        let root = tempdir().unwrap();
        initialize(root.path()).unwrap();
        write(root.path(), br#"[{"alias":"demo"}]"#).unwrap();
        let data = read(root.path()).unwrap().unwrap();
        assert_eq!(data, br#"[{"alias":"demo"}]"#);
        let path = root.path().join("hosts.vault");
        let mut encrypted = fs::read(&path).unwrap();
        assert!(!String::from_utf8_lossy(&encrypted).contains("demo"));
        let last = encrypted.len() - 1;
        encrypted[last] ^= 1;
        fs::write(path, encrypted).unwrap();
        assert!(read(root.path()).is_err());
    }

    #[test]
    fn backups_exclude_key_and_restore() {
        let root = tempdir().unwrap();
        let storage = tempdir().unwrap();
        initialize(root.path()).unwrap();
        write(root.path(), br#"[{"alias":"first"}]"#).unwrap();
        let receipt = backup(root.path(),storage.path(),"Lab router before update","local").unwrap();
        assert_eq!(receipt["key_included"], false);
        let filename = receipt["backup_name"].as_str().unwrap();
        assert!(!filename.contains(' '));
        assert!(!storage.path().join("vault.key").exists());
        write(root.path(), b"[]").unwrap();
        restore(root.path(), &storage.path().join(filename)).unwrap();
        assert_eq!(read(root.path()).unwrap().unwrap(), br#"[{"alias":"first"}]"#);
    }

    #[test]
    fn refuses_unapproved_legacy_migration() {
        let root = tempdir().unwrap();
        fs::write(root.path().join("hosts.json"), b"[]").unwrap();
        assert!(initialize(root.path()).is_err());
        migrate_legacy(root.path()).unwrap();
        assert!(root.path().join("hosts.json").exists());
        assert!(read(root.path()).is_ok());
    }
}
