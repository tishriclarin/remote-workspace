//! Encrypted device inventory and ciphertext-only backup.
//! The local 256-bit key is deliberately NOT part of cloud-synced backups.
//! OS user permissions protect that key; OS keychain migration is planned.
use chacha20poly1305::{
    aead::{Aead, AeadCore, KeyInit, OsRng, rand_core::RngCore},
    Key, XChaCha20Poly1305, XNonce,
};
use chrono::{Local, Utc};
use argon2::{Algorithm, Argon2, Params, Version};
use zeroize::Zeroizing;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
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
    let key = load_key(root)?;
    decrypt_with_key(&key, payload)
}
fn decrypt_with_key(key: &[u8; KEY_LEN], payload: &[u8]) -> Result<Vec<u8>> {
    if payload.len() < MAGIC.len() + NONCE_LEN + 16
        || !payload.starts_with(MAGIC) {
        return Err("Invalid encrypted vault format".into());
    }
    if payload.len() as u64 > MAX_VAULT_SIZE + 1024 {
        return Err("Encrypted vault exceeds size limit".into());
    }
    let cipher = XChaCha20Poly1305::new(Key::from_slice(key));
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


const RECOVERY_MAGIC: &[u8] = b"SSHWSRCV1";
const RECOVERY_SALT_LEN: usize = 16;
const RECOVERY_MIN_PASSWORD_CHARS: usize = 16;
const RECOVERY_MAX_BYTES: u64 = 4096;

fn recovery_derived_key(passphrase: &str, salt: &[u8; RECOVERY_SALT_LEN]) -> Result<Zeroizing<[u8; KEY_LEN]>> {
    if passphrase.chars().count() < RECOVERY_MIN_PASSWORD_CHARS || passphrase.len() > 1024 {
        return Err("Recovery passphrase must contain 16-1024 characters".into());
    }
    let params = Params::new(65536, 3, 1, Some(32))
        .map_err(|_| "Cannot initialize recovery key derivation")?;
    let mut derived = Zeroizing::new([0u8; KEY_LEN]);
    let argon = Argon2::new(Algorithm::Argon2id, Version::V0x13, params);
    argon.hash_password_into(passphrase.as_bytes(), salt, &mut derived[..])
        .map_err(|_| "Recovery key derivation failed")?;
    Ok(derived)
}

/// Export a password-protected copy of the device vault key. This file is not
/// automatically included in cloud backups and never contains the host inventory.
pub fn recovery_export(root: &Path, destination: &Path, passphrase: &str) -> Result<()> {
    let _ = read(root)?.ok_or("Initialize the vault first")?;
    if destination.extension().and_then(|x| x.to_str()) != Some("sshwskey") {
        return Err("Recovery key file must end in .sshwskey".into());
    }
    if destination.is_symlink() || destination.exists() {
        return Err("Refusing to overwrite or follow an existing recovery key path".into());
    }
    let salt: [u8; RECOVERY_SALT_LEN] = {
        let mut value = [0u8; RECOVERY_SALT_LEN];
        OsRng.fill_bytes(&mut value);
        value
    };
    let wrapping_key = recovery_derived_key(passphrase, &salt)?;
    let local_key = Zeroizing::new(load_key(root)?);
    let cipher = XChaCha20Poly1305::new(Key::from_slice(&wrapping_key[..]));
    let nonce = XChaCha20Poly1305::generate_nonce(&mut OsRng);
    let ciphertext = cipher.encrypt(&nonce, &local_key[..])
        .map_err(|_| "Recovery encryption failed")?;
    let mut data = Vec::with_capacity(RECOVERY_MAGIC.len()+RECOVERY_SALT_LEN+NONCE_LEN+ciphertext.len());
    data.extend_from_slice(RECOVERY_MAGIC);
    data.extend_from_slice(&salt);
    data.extend_from_slice(&nonce);
    data.extend_from_slice(&ciphertext);
    let directory = destination.parent().ok_or("Recovery path needs a parent directory")?;
    if !directory.is_dir() {
        return Err("Recovery destination directory does not exist".into());
    }
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)] {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(destination).map_err(|e| e.to_string())?;
    if let Err(error) = file.write_all(&data).and_then(|_| file.sync_all()) {
        let _ = fs::remove_file(destination);
        return Err(format!("Cannot persist protected recovery key: {error}"));
    }
    Ok(())
}

fn open_recovery_key(file: &Path, passphrase: &str) -> Result<Zeroizing<[u8; KEY_LEN]>> {
    if file.is_symlink() || !file.is_file() {
        return Err("Recovery file must be a regular file".into());
    }
    let len = fs::metadata(file).map_err(|e|e.to_string())?.len();
    if len > RECOVERY_MAX_BYTES { return Err("Recovery key envelope is too large".into()); }
    let raw = fs::read(file).map_err(|e|e.to_string())?;
    let prefix = RECOVERY_MAGIC.len();
    if !raw.starts_with(RECOVERY_MAGIC) ||
       raw.len() != prefix + RECOVERY_SALT_LEN + NONCE_LEN + KEY_LEN + 16 {
        return Err("Unknown or corrupted recovery key envelope".into());
    }
    let salt: [u8; RECOVERY_SALT_LEN] = raw[prefix..prefix+RECOVERY_SALT_LEN]
        .try_into().map_err(|_| "Invalid recovery salt")?;
    let derived = recovery_derived_key(passphrase, &salt)?;
    let cipher = XChaCha20Poly1305::new(Key::from_slice(&derived[..]));
    let start = prefix + RECOVERY_SALT_LEN;
    let nonce = XNonce::from_slice(&raw[start..start+NONCE_LEN]);
    let decrypted = cipher.decrypt(nonce, &raw[start+NONCE_LEN..])
        .map_err(|_| "Invalid recovery passphrase or tampered envelope")?;
    if decrypted.len() != KEY_LEN { return Err("Invalid recovered key length".into()); }
    let mut key = Zeroizing::new([0u8; KEY_LEN]);
    key.copy_from_slice(&decrypted);
    Ok(key)
}

/// Restore into a clean SSHWORKSPACE_HOME only. Never replace a live vault
/// key or silently lose existing host profiles on a different device.
pub fn recovery_import_fresh(root: &Path, recovery_file: &Path,
                              backup_file: &Path, passphrase: &str) -> Result<()> {
    if root.join("vault.key").exists() || root.join("vault.key").is_symlink() ||
       root.join("hosts.vault").exists() || root.join("hosts.vault").is_symlink() ||
       root.join("hosts.json").exists() || root.join("hosts.json").is_symlink() {
        return Err("Recovery requires an empty vault directory; existing data will not be overwritten".into());
    }
    if backup_file.is_symlink() || !backup_file.is_file() ||
       backup_file.extension().and_then(|x|x.to_str()) != Some("vault") {
        return Err("Choose a regular encrypted .vault backup".into());
    }
    if fs::metadata(backup_file).map_err(|e|e.to_string())?.len() > MAX_VAULT_SIZE + 1024 {
        return Err("Encrypted backup exceeds size limit".into());
    }
    let key = open_recovery_key(recovery_file, passphrase)?;
    let backup = fs::read(backup_file).map_err(|e|e.to_string())?;
    let plaintext = decrypt_with_key(&key, &backup)?;
    let hosts: Vec<Value> = serde_json::from_slice(&plaintext)
        .map_err(|_| "Backup does not contain a host inventory")?;
    for host in hosts {
        if !host.get("alias").and_then(Value::as_str).is_some() ||
           !host.get("address").and_then(Value::as_str).is_some() ||
           !host.get("username").and_then(Value::as_str).is_some() {
            return Err("Backup contains invalid host profile".into());
        }
    }
    owner_dir(root)?;
    let key_file = root.join("vault.key");
    let mut opts = OpenOptions::new();
    opts.write(true).create_new(true);
    #[cfg(unix)] {
        use std::os::unix::fs::OpenOptionsExt;
        opts.mode(0o600);
    }
    let mut f = opts.open(&key_file).map_err(|e|e.to_string())?;
    if let Err(e) = f.write_all(&key[..]).and_then(|_| f.sync_all()) {
        let _ = fs::remove_file(&key_file);
        return Err(format!("Could not persist recovered key: {e}"));
    }
    if let Err(error) = atomic_private_file(&vault_path(root), &backup) {
        let _ = fs::remove_file(&key_file);
        return Err(error);
    }
    Ok(())
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
    fn portable_recovery_from_separate_key_and_backup() {
        let old = tempdir().unwrap();
        let new = tempdir().unwrap();
        let files = tempdir().unwrap();
        initialize(old.path()).unwrap();
        write(old.path(), br#"[{"alias":"router","address":"192.0.2.10","username":"operator"}]"#).unwrap();
        let receipt = backup(old.path(),files.path(),"Before migrating device","cloud-sync").unwrap();
        let archive = files.path().join(receipt["backup_name"].as_str().unwrap());
        let recovery_file = files.path().join("offline-recovery.sshwskey");
        recovery_export(old.path(),&recovery_file,"very-long-unique-recovery-passphrase").unwrap();
        assert!(recovery_import_fresh(new.path(),&recovery_file,&archive,"wrong-passphrase-long").is_err());
        assert!(!new.path().join("vault.key").exists());
        recovery_import_fresh(new.path(),&recovery_file,&archive,"very-long-unique-recovery-passphrase").unwrap();
        assert_eq!(read(new.path()).unwrap().unwrap(),read(old.path()).unwrap().unwrap());
        assert!(recovery_import_fresh(new.path(),&recovery_file,&archive,"very-long-unique-recovery-passphrase").is_err());
    }

    #[test]
    fn recovery_envelope_integrity_is_enforced() {
        let root = tempdir().unwrap();
        let dest = tempdir().unwrap();
        initialize(root.path()).unwrap();
        let path = dest.path().join("offline.sshwskey");
        recovery_export(root.path(),&path,"a-unique-recovery-password-123").unwrap();
        let mut raw = fs::read(&path).unwrap();
        let last = raw.len() - 1;
        raw[last] ^= 1;
        fs::write(&path,raw).unwrap();
        let backup = dest.path().join("sample.vault");
        fs::copy(root.path().join("hosts.vault"),&backup).unwrap();
        assert!(recovery_import_fresh(dest.path().join("fresh").as_path(),&path,&backup,"a-unique-recovery-password-123").is_err());
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
