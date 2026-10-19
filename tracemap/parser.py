"""Parse traceroute (Linux/macOS) and tracert (Windows) output into hops."""
from __future__ import annotations

import ipaddress
import re
import statistics
from dataclasses import dataclass, field
from typing import Optional

_TOKEN_RE = re.compile(
    r"(?P<pair>[^\s()\[\]*]+\s+[(\[](?:\d{1,3}\.){3}\d{1,3}[)\]])"  # "name (1.2.3.4)" / "name [1.2.3.4]"
    r"|(?P<ip>\b(?:\d{1,3}\.){3}\d{1,3}\b)"
    r"|(?P<rtt><?\s?\d+(?:\.\d+)?\s*ms\b)"
    r"|(?P<star>\*)"
    r"|(?P<flag>![A-Za-z0-9<>]+)"
)
_PAIR_RE = re.compile(r"^(?P<host>\S+)\s+[(\[](?P<ip>[\d.]+)[)\]]$")
_HOP_RE = re.compile(r"^\s*(\d+)\s+(.*)$")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_HDR_UNIX = re.compile(
    r"traceroute to (?P<host>\S+) \((?P<ip>[\d.]+)\)"
    r"(?:, (?P<max>\d+) hops max)?(?:, (?P<size>\d+) byte packets)?"
)
_HDR_WIN = re.compile(r"Tracing route to (?P<host>\S+)(?: \[(?P<ip>[\d.]+)\])?")
_HDR_WIN_MAX = re.compile(r"maximum of (\d+) hops")


@dataclass
class Responder:
    """One router address that answered probes for a given TTL."""

    ip: str
    rtts: list[float] = field(default_factory=list)
    hostname: Optional[str] = None


@dataclass
class Hop:
    ttl: int
    responders: list[Responder] = field(default_factory=list)
    lost: int = 0
    flags: list[str] = field(default_factory=list)

    def responder(self, ip: str) -> Responder:
        for r in self.responders:
            if r.ip == ip:
                return r
        r = Responder(ip)
        self.responders.append(r)
        return r

    @property
    def ip(self) -> Optional[str]:
        return self.responders[0].ip if self.responders else None

    @property
    def rtts(self) -> list[float]:
        return [v for r in self.responders for v in r.rtts]

    @property
    def rtt_min(self) -> Optional[float]:
        return min(self.rtts) if self.rtts else None

    @property
    def rtt_max(self) -> Optional[float]:
        return max(self.rtts) if self.rtts else None

    @property
    def rtt_avg(self) -> Optional[float]:
        return statistics.fmean(self.rtts) if self.rtts else None


@dataclass
class Trace:
    target: str = ""
    target_ip: Optional[str] = None
    max_hops: Optional[int] = None
    packet_size: Optional[int] = None
    style: str = "unix"  # "unix" or "windows"
    hops: list[Hop] = field(default_factory=list)

    @property
    def reached(self) -> bool:
        return bool(self.hops and self.target_ip and self.hops[-1].ip == self.target_ip)


def _valid_ip(text: str) -> bool:
    try:
        ipaddress.IPv4Address(text)
        return True
    except ValueError:
        return False


def _tokens(rest: str) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for m in _TOKEN_RE.finditer(rest):
        kind = m.lastgroup
        val = m.group(kind)
        if kind == "pair":
            pm = _PAIR_RE.match(val)
            if pm and _valid_ip(pm.group("ip")):
                out.append(("host", pm.group("host")))
                out.append(("ip", pm.group("ip")))
            continue
        if kind == "ip" and not _valid_ip(val):
            continue
        if kind == "rtt":
            val = float(_NUM_RE.search(val).group())
        out.append((kind, val))
    return out


def _apply(hop: Hop, toks: list[tuple[str, object]]) -> None:
    """Fold the tokens of one output line into a hop."""
    has_rtt = any(k == "rtt" for k, _ in toks)
    if toks and toks[-1][0] == "ip" and has_rtt:
        # Windows layout: "<rtt> <rtt> <rtt> [host] ip"
        resp = hop.responder(str(toks[-1][1]))
        for kind, val in toks[:-1]:
            if kind == "rtt":
                resp.rtts.append(float(val))
            elif kind == "star":
                hop.lost += 1
            elif kind == "host":
                resp.hostname = str(val)
        return
    current: Optional[Responder] = None
    pending_host: Optional[str] = None
    for kind, val in toks:
        if kind == "host":
            pending_host = str(val)
        elif kind == "ip":
            current = hop.responder(str(val))
            if pending_host:
                current.hostname = pending_host
                pending_host = None
        elif kind == "rtt":
            if current is not None:
                current.rtts.append(float(val))
        elif kind == "star":
            hop.lost += 1
        elif kind == "flag":
            hop.flags.append(str(val))


def parse_traceroute(text: str) -> Trace:
    """Parse the full text output of traceroute or tracert."""
    trace = Trace()
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue

        mm = _HDR_WIN_MAX.search(line)
        if mm:
            trace.max_hops = int(mm.group(1))
            if "Tracing route" not in line and not _HOP_RE.match(line):
                continue
        m = _HDR_UNIX.search(line)
        if m:
            trace.target = m.group("host")
            trace.target_ip = m.group("ip")
            trace.max_hops = int(m.group("max")) if m.group("max") else None
            trace.packet_size = int(m.group("size")) if m.group("size") else None
            continue
        m = _HDR_WIN.search(line)
        if m:
            trace.style = "windows"
            trace.target = m.group("host")
            ip = m.group("ip") or (m.group("host") if _valid_ip(m.group("host")) else None)
            trace.target_ip = ip
            continue

        hm = _HOP_RE.match(line)
        if hm:
            ttl = int(hm.group(1))
            toks = _tokens(hm.group(2))
            if not toks and "timed out" not in hm.group(2).lower():
                continue  # not a hop line
            if trace.hops and trace.hops[-1].ttl == ttl:
                hop = trace.hops[-1]
            else:
                hop = Hop(ttl)
                trace.hops.append(hop)
            _apply(hop, toks)
        elif trace.hops:
            # Continuation line: more responders for the previous hop.
            toks = _tokens(line)
            if any(k in ("ip", "rtt") for k, _ in toks):
                _apply(trace.hops[-1], toks)
    return trace


def merge_traces(traces: list[Trace]) -> Trace:
    """Combine several runs of the same trace into one.

    For every TTL, the responders from all runs are united and their RTTs pooled. Responders are
    ordered by how many probes they answered, so the most common router is the main one and the
    rest are the alternative branches of a load-balanced path. Lost probes are summed.
    """
    if not traces:
        raise ValueError("nothing to merge")
    first = traces[0]
    out = Trace(first.target, first.target_ip, first.max_hops, first.packet_size, first.style, [])
    for t in traces[1:]:
        out.target = out.target or t.target
        out.target_ip = out.target_ip or t.target_ip
    for ttl in sorted({h.ttl for t in traces for h in t.hops}):
        merged = Hop(ttl)
        for t in traces:
            for h in t.hops:
                if h.ttl != ttl:
                    continue
                merged.lost += h.lost
                for f in h.flags:
                    if f not in merged.flags:
                        merged.flags.append(f)
                for r in h.responders:
                    m = merged.responder(r.ip)
                    m.rtts.extend(r.rtts)
                    m.hostname = m.hostname or r.hostname
        merged.responders.sort(key=lambda r: -len(r.rtts))   # stable: ties keep first-seen order
        out.hops.append(merged)
    # A run that stopped early leaves trailing hops only some runs saw; keep through the last one
    # that any run reached, which is what the loop above already does.
    return out
