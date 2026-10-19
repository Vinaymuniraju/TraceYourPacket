"""Turn a parsed trace into an Analysis: locations, networks, hostname hints and sanity findings.

Everything the report, the map, the saved snapshots and the diff engine need about one run lives
in an Analysis, so each of those works the same on a live trace and on one loaded from disk.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .asn import AsnInfo, AsnResolver, default_cache_path as asn_cache_path
from .geo import GeoInfo, GeoResolver, default_cache_path as geo_cache_path
from .hints import apply_hints, reverse_dns
from .parser import Trace
from .sanity import Finding, check_hops


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Options:
    """The lookup choices that decide what Analysis does (built from the command line)."""
    offline: bool = False
    no_cache: bool = False
    geo_file: Optional[Path] = None
    asn_file: Optional[Path] = None
    no_asn: bool = False
    no_rdns: bool = False


@dataclass
class Analysis:
    trace: Trace
    method: str
    origin: Optional[tuple[float, float]]
    geo: dict[str, Optional[GeoInfo]]
    asn: dict[str, AsnInfo]
    names: dict[str, str] = field(default_factory=dict)       # reverse-DNS names
    hint_messages: list[str] = field(default_factory=list)
    findings: dict[int, Finding] = field(default_factory=dict)
    taken_at: str = field(default_factory=utc_now_iso)

    @property
    def label(self) -> str:
        return self.trace.target or self.trace.target_ip or "route"


def analyse(trace: Trace, method: str, origin: Optional[tuple[float, float]], opts: Options,
            taken_at: Optional[str] = None) -> Analysis:
    ips = [r.ip for hop in trace.hops for r in hop.responders]

    resolver = GeoResolver(geo_file=opts.geo_file, use_network=not opts.offline,
                           cache_path=None if opts.no_cache else geo_cache_path())
    geo: dict[str, Optional[GeoInfo]] = {}
    for ip in dict.fromkeys(ips):
        geo[ip] = resolver.lookup(ip)
    resolver.save()

    asn: dict[str, AsnInfo] = {}
    if not opts.no_asn:
        ar = AsnResolver(asn_file=opts.asn_file, use_network=not opts.offline,
                         cache_path=None if opts.no_cache else asn_cache_path())
        asn = {ip: v for ip, v in ar.lookup_many(ips).items() if v}
        ar.save()

    names = {} if (opts.offline or opts.no_rdns) else reverse_dns(ips)
    messages = apply_hints(trace, geo, origin, names)
    return Analysis(trace, method, origin, geo, asn, names, messages,
                    check_hops(trace, geo, origin), taken_at or utc_now_iso())
