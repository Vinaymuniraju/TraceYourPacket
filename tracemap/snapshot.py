"""Save an Analysis to disk and load it back, with strict validation.

A snapshot holds everything needed to show or compare a run later without any network access:
the hops, their RTTs, the locations and the networks that were used at the time. Files are
read back as untrusted input: every field is type-checked, ranges are enforced, strings are
truncated and the file size is capped. Anything else raises SnapshotError.
"""
from __future__ import annotations

import ipaddress
import json
import math
import os
import re
from pathlib import Path
from typing import Optional

from .analysis import Analysis
from .asn import AsnInfo
from .geo import GeoInfo
from .parser import Hop, Responder, Trace
from .sanity import check_hops

FORMAT = "tracemap-run"
VERSION = 1
MAX_BYTES = 5 * 1024 * 1024
MAX_HOPS = 255
MAX_RESPONDERS = 32
MAX_RTTS = 200


class SnapshotError(Exception):
    """The file is not a valid snapshot."""


def default_history_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "tracemap" / "history"


def safe_name(target: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", target or "route")[:80] or "route"


def run_filename(taken_at: str) -> str:
    return re.sub(r"[^0-9TZ]", "", taken_at) + ".json"


# ---------------------------------------------------------------- writing
def to_snapshot(a: Analysis) -> dict:
    t = a.trace
    hops = []
    for h in t.hops:
        resp = []
        for r in h.responders:
            g = a.geo.get(r.ip)
            n = a.asn.get(r.ip)
            resp.append({
                "ip": r.ip,
                "hostname": r.hostname or a.names.get(r.ip),
                "rtts": r.rtts,
                "lat": g.lat if g else None, "lon": g.lon if g else None,
                "city": g.city if g else None, "region": g.region if g else None,
                "country": g.country if g else None, "org": g.org if g else None,
                "loc_source": g.source if g else None, "loc_note": g.note if g else None,
                "asn": n.asn if n else None, "net_name": n.name if n else None,
                "net_source": n.source if n else None,
            })
        hops.append({"ttl": h.ttl, "lost": h.lost, "flags": h.flags, "responders": resp})
    return {
        "format": FORMAT, "version": VERSION, "saved_at": a.taken_at,
        "target": t.target, "target_ip": t.target_ip, "method": a.method, "style": t.style,
        "origin": list(a.origin) if a.origin else None, "max_hops": t.max_hops,
        "packet_size": t.packet_size, "hops": hops,
    }


def save_snapshot(a: Analysis, history_dir: Path) -> Path:
    d = Path(history_dir) / safe_name(a.label)
    d.mkdir(parents=True, exist_ok=True)
    path = d / run_filename(a.taken_at)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(to_snapshot(a), separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- reading
def _s(v, field: str, n: int = 200, allow_none: bool = True) -> Optional[str]:
    if v is None and allow_none:
        return None
    if not isinstance(v, str):
        raise SnapshotError(f"{field} must be text")
    return v[:n]


def _num(v, field: str, lo: float, hi: float, allow_none: bool = False) -> Optional[float]:
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise SnapshotError(f"{field} must be a number between {lo} and {hi}")
    return float(v)


def _int(v, field: str, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise SnapshotError(f"{field} must be an integer between {lo} and {hi}")
    return v


def _ip(v, field: str) -> str:
    try:
        return str(ipaddress.IPv4Address(v))
    except (ValueError, TypeError):
        raise SnapshotError(f"{field} is not an IPv4 address")


def _time(v) -> str:
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", v):
        raise SnapshotError("saved_at must look like 2026-10-19T16:30:00Z")
    return v


def load_snapshot_dict(raw) -> Analysis:
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise SnapshotError("not a tracemap run file")
    if raw.get("version") != VERSION:
        raise SnapshotError(f"unsupported snapshot version {raw.get('version')!r}")
    hops_raw = raw.get("hops")
    if not isinstance(hops_raw, list) or not hops_raw or len(hops_raw) > MAX_HOPS:
        raise SnapshotError("hops must be a non-empty list")
    method = raw.get("method")
    if method not in ("udp", "icmp", "tcp"):
        raise SnapshotError("method must be udp, icmp or tcp")
    style = raw.get("style", "unix")
    if style not in ("unix", "windows"):
        raise SnapshotError("style must be unix or windows")
    origin = raw.get("origin")
    if origin is not None:
        if not (isinstance(origin, list) and len(origin) == 2):
            raise SnapshotError("origin must be [lat, lon]")
        origin = (_num(origin[0], "origin lat", -90, 90), _num(origin[1], "origin lon", -180, 180))
    target_ip = raw.get("target_ip")
    trace = Trace(
        target=_s(raw.get("target"), "target", 253, False) or "",
        target_ip=_ip(target_ip, "target_ip") if target_ip else None,
        max_hops=_int(raw["max_hops"], "max_hops", 1, 255) if raw.get("max_hops") is not None else None,
        packet_size=_int(raw["packet_size"], "packet_size", 1, 65535) if raw.get("packet_size") is not None else None,
        style=style, hops=[])
    geo: dict[str, Optional[GeoInfo]] = {}
    asn: dict[str, AsnInfo] = {}
    names: dict[str, str] = {}
    seen_ttl = set()
    for i, h in enumerate(hops_raw):
        if not isinstance(h, dict):
            raise SnapshotError(f"hop {i} must be an object")
        ttl = _int(h.get("ttl"), "ttl", 1, 255)
        if ttl in seen_ttl:
            raise SnapshotError(f"duplicate ttl {ttl}")
        seen_ttl.add(ttl)
        flags = h.get("flags", [])
        if not isinstance(flags, list) or len(flags) > 16:
            raise SnapshotError("flags must be a short list")
        hop = Hop(ttl, [], _int(h.get("lost", 0), "lost", 0, 10000), [str(f)[:8] for f in flags])
        resp_raw = h.get("responders", [])
        if not isinstance(resp_raw, list) or len(resp_raw) > MAX_RESPONDERS:
            raise SnapshotError("too many responders")
        for r in resp_raw:
            if not isinstance(r, dict):
                raise SnapshotError("responder must be an object")
            ip = _ip(r.get("ip"), "ip")
            rtts_raw = r.get("rtts", [])
            if not isinstance(rtts_raw, list) or len(rtts_raw) > MAX_RTTS:
                raise SnapshotError("rtts must be a list")
            rtts = [_num(x, "rtt", 0, 1e6) for x in rtts_raw]
            host = _s(r.get("hostname"), "hostname", 253)
            hop.responders.append(Responder(ip, rtts, host))
            if host:
                names[ip] = host
            lat = _num(r.get("lat"), "lat", -90, 90, True)
            lon = _num(r.get("lon"), "lon", -180, 180, True)
            if lat is not None and lon is not None and ip not in geo:
                geo[ip] = GeoInfo(lat, lon, _s(r.get("city"), "city"), _s(r.get("region"), "region"),
                                  _s(r.get("country"), "country"), _s(r.get("org"), "org"),
                                  _s(r.get("loc_source"), "loc_source", 20) or "ip-database",
                                  _s(r.get("loc_note"), "loc_note", 400))
            elif ip not in geo:
                geo[ip] = None
            if r.get("net_name") is not None and ip not in asn:
                a = r.get("asn")
                asn[ip] = AsnInfo(_int(a, "asn", 1, 2**32 - 1) if a is not None else None,
                                  _s(r.get("net_name"), "net_name", 80) or "unknown operator", None,
                                  _s(r.get("net_source"), "net_source", 20) or "ripestat")
        trace.hops.append(hop)
    trace.hops.sort(key=lambda x: x.ttl)
    an = Analysis(trace, method, origin, geo, asn, names, [], {}, _time(raw.get("saved_at")))
    an.findings = check_hops(trace, geo, origin)
    return an


def load_snapshot(path: Path) -> Analysis:
    p = Path(path)
    try:
        if p.stat().st_size > MAX_BYTES:
            raise SnapshotError("file is too large to be a run snapshot")
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"cannot read {p.name}: {exc}") from exc
    return load_snapshot_dict(raw)


# ---------------------------------------------------------------- history
def list_runs(history_dir: Path, target: Optional[str] = None) -> list[tuple[str, Path]]:
    """(target folder name, path) for saved runs, oldest first. Skips unreadable files' names only."""
    root = Path(history_dir)
    if not root.is_dir():
        return []
    dirs = [root / safe_name(target)] if target else sorted(d for d in root.iterdir() if d.is_dir())
    out = []
    for d in dirs:
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                if re.fullmatch(r"\d{8}T\d{6}Z\.json", f.name):
                    out.append((d.name, f))
    return out


def load_history(history_dir: Path, target: str, limit: int = 12,
                 before: Optional[str] = None) -> list[Analysis]:
    """Most recent runs for a target, oldest first. Unreadable files are skipped."""
    files = [f for _, f in list_runs(history_dir, target)]
    if before:
        files = [f for f in files if f.name < run_filename(before)]
    runs = []
    for f in files[-limit:]:
        try:
            runs.append(load_snapshot(f))
        except SnapshotError:
            continue
    return runs
