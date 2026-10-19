"""Validate the target and run the system traceroute without a shell."""
from __future__ import annotations

import ipaddress
import platform
import re
import socket
import subprocess
import sys
import threading
from typing import Optional

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)


class TargetError(ValueError):
    pass


def validate_target(target: str) -> tuple[str, str]:
    """Return (name, ipv4). Rejects anything that is not a plain host or IPv4.

    A leading '-' is refused so the value can never be read as an option by
    the traceroute binary.
    """
    target = target.strip()
    if not target or target.startswith("-"):
        raise TargetError(f"invalid target: {target!r}")
    try:
        addr = ipaddress.ip_address(target)
    except ValueError:
        addr = None
    if addr is not None:
        if addr.version != 4:
            raise TargetError("only IPv4 targets are supported")
        return target, str(addr)
    if not _HOST_RE.match(target):
        raise TargetError(f"invalid target: {target!r}")
    try:
        infos = socket.getaddrinfo(target, None, socket.AF_INET)
    except socket.gaierror as exc:
        raise TargetError(f"cannot resolve {target!r}: {exc}") from exc
    return target, infos[0][4][0]


def build_command(
    ip: str, method: str = "udp", max_hops: int = 25, system: Optional[str] = None
) -> list[str]:
    """Build the argv list for the platform's traceroute tool."""
    system = system or platform.system()
    if not 1 <= max_hops <= 64:
        raise ValueError("max_hops must be between 1 and 64")
    if system == "Windows":
        # tracert always sends ICMP echo requests.
        return ["tracert", "-d", "-h", str(max_hops), "-4", ip]
    if system in ("Linux", "Darwin"):
        cmd = ["traceroute", "-n", "-m", str(max_hops)]
        if method == "icmp":
            cmd += ["-I"] if system == "Linux" else ["-P", "ICMP"]
        elif method == "tcp":
            cmd += ["-T"] if system == "Linux" else ["-P", "TCP"]
        return cmd + [ip]
    raise RuntimeError(f"unsupported operating system: {system}")


def run_traceroute(cmd: list[str], echo: bool = True, timeout: float = 300.0) -> str:
    """Run the command, echoing lines as they arrive, and return all output."""
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"'{cmd[0]}' not found. On Debian/Ubuntu: sudo apt install traceroute"
        ) from exc
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    lines: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line)
            if echo:
                sys.stdout.write(line)
                sys.stdout.flush()
        proc.wait()
    finally:
        timer.cancel()
    if proc.returncode not in (0, None) and not lines:
        raise RuntimeError(f"{cmd[0]} exited with status {proc.returncode}")
    return "".join(lines)
