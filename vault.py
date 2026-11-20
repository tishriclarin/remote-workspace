"""Encrypted storage for local SSH profiles."""

import fcntl
import json
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress, SecretStr, field_validator, model_validator

from local_paths import config_directory

Alias = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
Address = Annotated[str, Field(pattern=r"^[a-zA-Z0-9:][a-zA-Z0-9.:-]{0,252}$")]
Group = Annotated[str, Field(min_length=1, max_length=80)]
Algorithm = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}$")]
Algorithms = Annotated[list[Algorithm], Field(min_length=1, max_length=32)]


class ConnectionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    ciphers: Algorithms | None = None
    kex_algorithms: Algorithms | None = None
    macs: Algorithms | None = None
    host_key_algorithms: Algorithms | None = None
    pubkey_algorithms: Algorithms | None = None
    connect_timeout: int = Field(default=4, ge=1, le=15)
    protocol_compression: bool = False
    bind_address: IPvAnyAddress | None = None
    bind_interface: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$")] | None = None

    @model_validator(mode="after")
    def check_binding(self):
        if self.bind_address is not None and self.bind_interface is not None:
            raise ValueError("Set either a local source address or a local interface")
        return self


class Host(ConnectionOptions):
    address: Address
    hostname: Address | None = None
    port: int = Field(default=22, ge=1, le=65535)
    account: str = Field(pattern=r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}$")
    group: Group = "default"
    comment: str = Field(default="", max_length=1000)
    auth: Literal["publickey", "password"] = "publickey"
    password: SecretStr | None = Field(default=None, repr=False)
    identity_file: Path | None = None
    certificate_file: Path | None = None
    known_hosts_file: Path

    @field_validator("identity_file", "certificate_file", "known_hosts_file")
    @classmethod
    def check_paths(cls, path: Path | None) -> Path | None:
        if path is not None and (not path.is_absolute() or re.search(r'[\s%"\\$]', str(path))):
            raise ValueError("Use an absolute file path without whitespace, expansions, or quotes")
        return path

    @field_validator("group", "comment")
    @classmethod
    def check_text(cls, text: str) -> str:
        if not text.isprintable() and text:
            raise ValueError("Use printable text")
        if text != text.strip():
            raise ValueError("Remove surrounding whitespace")
        return text

    @field_validator("password")
    @classmethod
    def check_password(cls, secret: SecretStr | None) -> SecretStr | None:
        if secret is not None:
            password = secret.get_secret_value()
            if not 1 <= len(password.encode()) <= 1024 or any(c in password for c in "\0\r\n"):
                raise ValueError("Use a password of 1 to 1024 bytes without newline or NUL characters")
        return secret

    @model_validator(mode="after")
    def check_auth(self):
        if self.auth == "password":
            if self.password is None or self.identity_file or self.certificate_file or self.pubkey_algorithms:
                raise ValueError("Password authentication needs a password and no public-key options")
        elif self.identity_file is None or self.password is not None:
            raise ValueError("Public-key authentication needs an identity file and no password")
        return self


class Inventory(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    hosts: dict[Alias, Host] = Field(default_factory=dict)


class VaultError(ValueError):
    pass


class Vault:
    def __init__(self, path: Path, key: bytes | str):
        self.path = path
        self.cipher = Fernet(key)

    @classmethod
    def from_env(cls):
        config = config_directory()
        vault = Path(os.environ.get("SSH_WORKSPACE_VAULT") or config / "hosts.vault")
        key_path = Path(os.environ.get("SSH_WORKSPACE_VAULT_KEY_FILE") or config / "vault.key")
        if vault.resolve() == key_path.resolve():
            raise VaultError("Use distinct vault and key file paths")
        with key_path.open("rb") as key:
            if os.fstat(key.fileno()).st_mode & 0o077:
                raise VaultError("Remove group and other access from the vault key file")
            return cls(vault, key.read(128).strip())

    def load(self) -> Inventory:
        with self.path.open("rb") as source:
            if os.fstat(source.fileno()).st_mode & 0o077:
                raise VaultError("Remove group and other access from the vault")
            encrypted = source.read(4 * 1024 * 1024 + 1)
        if len(encrypted) > 4 * 1024 * 1024:
            raise VaultError("The vault exceeds the 4 MiB storage limit")
        try:
            return Inventory.model_validate_json(self.cipher.decrypt(encrypted))
        except InvalidToken:
            raise VaultError("Vault authentication failed. Check the key and vault file.") from None

    def update(self, apply: Callable[[Inventory], Inventory], *, initialize=False):
        lock_path = self.path.with_name(self.path.name + ".lock")
        with os.fdopen(os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), "rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if initialize and self.path.exists():
                raise VaultError("The vault already exists")
            current = Inventory() if initialize else self.load()
            updated = apply(current)
            self._write(Inventory.model_validate(updated.model_dump(mode="python")))

    def _write(self, inventory: Inventory):
        data = inventory.model_dump(mode="json")
        for alias, profile in inventory.hosts.items():
            data["hosts"][alias]["password"] = (
                profile.password.get_secret_value() if profile.password is not None else None
            )
        encrypted = self.cipher.encrypt(json.dumps(data).encode())
        if len(encrypted) > 4 * 1024 * 1024:
            raise VaultError("The vault exceeds the 4 MiB storage limit")
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.")
        try:
            with os.fdopen(fd, "wb") as temp:
                temp.write(encrypted)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(name, self.path)
            parent_fd = os.open(self.path.parent, os.O_DIRECTORY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        finally:
            Path(name).unlink(missing_ok=True)
