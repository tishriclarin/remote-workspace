"""Local MCP tools for an encrypted SSH workspace."""

import asyncio
import math
import os
import re
import signal
from collections.abc import Callable
from contextlib import contextmanager
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ValidationError

from vault import Alias, ConnectionOptions, Group, Host, Inventory, Vault

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True,
)


def ssh_args(host: Host, command: str) -> list[str]:
    argv = [
        "/usr/bin/ssh", "-F", "/dev/null", "-n", "-T",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "UpdateHostKeys=no",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", f"UserKnownHostsFile={host.known_hosts_file}",
        "-o", "IdentityAgent=none",
        "-o", "ClearAllForwardings=yes",
        "-o", "ForwardAgent=no",
        "-o", f"ConnectTimeout={host.connect_timeout}",
        "-o", "ChannelTimeout=session=8s",
        "-o", f"Compression={'yes' if host.protocol_compression else 'no'}",
        "-o", f"PreferredAuthentications={host.auth}",
        "-o", "KbdInteractiveAuthentication=no",
    ]
    if host.auth == "password":
        argv += ["-o", "BatchMode=no", "-o", "NumberOfPasswordPrompts=1", "-o", "PubkeyAuthentication=no"]
    else:
        argv += ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-i", str(host.identity_file)]
        if host.certificate_file is not None:
            argv += ["-o", f"CertificateFile={host.certificate_file}"]
    for option, algorithms in (
        ("Ciphers", host.ciphers),
        ("KexAlgorithms", host.kex_algorithms),
        ("MACs", host.macs),
        ("HostKeyAlgorithms", host.host_key_algorithms),
        ("PubkeyAcceptedAlgorithms", host.pubkey_algorithms),
    ):
        if algorithms is not None:
            argv += ["-o", f"{option}={','.join(algorithms)}"]
    if host.bind_address is not None:
        argv += ["-b", str(host.bind_address)]
    if host.bind_interface is not None:
        argv += ["-B", host.bind_interface]
    return [*argv, "-p", str(host.port), "-l", host.account, "--", host.address, command]


@contextmanager
def ssh_process_args(host: Host, command: str):
    argv = ssh_args(host, command)
    if host.password is None:
        yield argv, ()
        return

    read_fd, write_fd = os.pipe()
    try:
        with os.fdopen(write_fd, "wb") as pipe:
            pipe.write(host.password.get_secret_value().encode() + b"\n")
        yield ["/usr/bin/sshpass", "-d", str(read_fd), *argv], (read_fd,)
    finally:
        os.close(read_fd)


async def run_ssh(host: Host, command: str) -> bytes:
    async with asyncio.timeout(host.connect_timeout + 8):
        with ssh_process_args(host, command) as (argv, descriptors):
            proc = await asyncio.create_subprocess_exec(
                *argv,
                pass_fds=descriptors,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
        try:
            output = bytearray()
            while chunk := await proc.stdout.read(512):
                output.extend(chunk)
                if len(output) > 1024:
                    raise ToolError("SSH returned an unexpected response.")
            if await proc.wait():
                raise ToolError("The SSH check failed.")
            return bytes(output)
        finally:
            if proc.returncode is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await proc.wait()


class Connection(BaseModel):
    host: Alias
    status: Literal["connected", "unavailable"]


class Platform(BaseModel):
    host: Alias
    system: str
    architecture: str


class Uptime(BaseModel):
    host: Alias
    uptime_seconds: int


def build_server(load_inventory: Callable[[], Inventory]) -> FastMCP:
    mcp = FastMCP(
        "SSH Workspace",
        instructions=(
            "Use saved host aliases for SSH diagnostics. Ask which host if unclear. "
            "Only apply per-check overrides explicitly requested by the user."
        ),
    )
    slots = asyncio.Semaphore(8)

    def saved_hosts() -> dict[Alias, Host]:
        try:
            return load_inventory().hosts
        except FileNotFoundError:
            raise ToolError("Initialize the local SSH Workspace vault before running diagnostics.") from None
        except (OSError, ValueError):
            raise ToolError("The local SSH Workspace vault could not be opened.") from None

    def saved_host(alias: Alias, overrides: ConnectionOptions | None) -> Host:
        host = saved_hosts().get(alias)
        if host is None:
            raise ToolError("That host alias is not in your local SSH Workspace vault.")
        if overrides is None:
            return host
        changes = overrides.model_dump(mode="python", exclude_unset=True)
        if changes.get("bind_address") is not None and "bind_interface" not in changes:
            changes["bind_interface"] = None
        if changes.get("bind_interface") is not None and "bind_address" not in changes:
            changes["bind_address"] = None
        try:
            return Host.model_validate({**host.model_dump(mode="python"), **changes})
        except ValidationError:
            raise ToolError("That override is incompatible with the saved SSH profile.") from None

    async def check(host: Host, command: str) -> bytes:
        try:
            async with asyncio.timeout(host.connect_timeout + 10), slots:
                return await run_ssh(host, command)
        except (OSError, TimeoutError):
            raise ToolError("The SSH check failed.") from None

    @mcp.tool(annotations=READ_ONLY)
    def list_ssh_hosts(group: Group | None = None) -> list[Alias]:
        """List SSH host aliases saved on this machine, optionally filtered by group."""
        return sorted(alias for alias, profile in saved_hosts().items()
                      if group is None or profile.group == group)

    @mcp.tool(annotations=READ_ONLY)
    async def check_ssh_connection(host: Alias, overrides: ConnectionOptions | None = None) -> Connection:
        """Check if SSH authentication succeeds on a saved host."""
        profile = saved_host(host, overrides)
        try:
            await check(profile, "true")
        except ToolError:
            return Connection(host=host, status="unavailable")
        return Connection(host=host, status="connected")

    @mcp.tool(annotations=READ_ONLY)
    async def get_ssh_host_platform(host: Alias, overrides: ConnectionOptions | None = None) -> Platform:
        """Read the kernel family and CPU architecture of a saved SSH host."""
        output = (await check(saved_host(host, overrides), "uname -sm")).split()
        if len(output) != 2 or not all(re.fullmatch(rb"[A-Za-z0-9_.-]{1,48}", value) for value in output):
            raise ToolError("The host returned an unsupported platform response.")
        return Platform(host=host, system=output[0].decode(), architecture=output[1].decode())

    @mcp.tool(annotations=READ_ONLY)
    async def get_ssh_host_uptime(host: Alias, overrides: ConnectionOptions | None = None) -> Uptime:
        """Read uptime in seconds from a saved Linux SSH host."""
        output = (await check(saved_host(host, overrides), "cat /proc/uptime")).split()
        if not output or not re.fullmatch(rb"[0-9]{1,12}(?:\.[0-9]{1,9})?", output[0]):
            raise ToolError("The host returned an unsupported uptime response.")
        return Uptime(host=host, uptime_seconds=math.floor(float(output[0])))

    return mcp


if __name__ == "__main__":
    build_server(lambda: Vault.from_env().load()).run(transport="stdio")
