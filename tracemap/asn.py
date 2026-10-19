"""Which network (autonomous system) owns each hop.

Lookup order for an address:

1. an entry in the file given with --asn-file (always wins, also for reserved ranges, so the
   bundled sample can be replayed offline);
2. private, carrier-grade NAT and other non-public ranges: no lookup, labelled as "your network";
3. the local cache (~/.cache/tracemap/asn.json);
4. RIPEstat's prefix-overview API (https://stat.ripe.net), unless offline.

Only public addresses are ever sent to RIPEstat. Failures are logged and never cached.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .geo import classify_ip

log = logging.getLogger("tracemap.asn")
API_URL = "https://stat.ripe.net/data/prefix-overview/data.json?resource={ip}"
MAX_BODY = 2 * 1024 * 1024

# Distinct on a dark background and readable next to the cable colours. Local networks get grey.
NET_PALETTE = ["#7c9cff", "#ff8a65", "#4dd0a1", "#f7c948", "#c58bff", "#5ad1e6", "#ff6f91", "#a3d95b"]
LOCAL_COLOR = "#8b9ab3"


_LOCAL_NAMES = {
    "private (RFC 1918)": "Your network",
    "loopback": "Your computer",
    "link-local": "Your network",
    "carrier-grade NAT (RFC 6598)": "Your ISP (carrier-grade NAT)",
}


@dataclass
class AsnInfo:
    asn: Optional[int]          # None for local (private/CGNAT) networks
    name: str
    prefix: Optional[str] = None
    source: str = "ripestat"    # "ripestat", "file", "local"

    @property
    def label(self) -> str:
        return f"AS{self.asn} {self.name}" if self.asn else self.name

    @property
    def key(self) -> str:
        """Stable id for colouring and grouping hops by network."""
        return f"AS{self.asn}" if self.asn else "local"


def default_cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "tracemap" / "asn.json"


def _clean_name(text: str) -> str:
    return " ".join(str(text).split())[:80] or "unknown operator"


def parse_ripestat(data) -> Optional[AsnInfo]:
    """Extract (asn, holder, prefix) from a RIPEstat prefix-overview response, or None."""
    try:
        d = data["data"]
        asns = d.get("asns") or []
        if not asns:
            return None
        first = asns[0]
        asn = int(first["asn"])
        if not 0 < asn < 2**32:
            return None
        return AsnInfo(asn, _clean_name(first.get("holder") or ""), d.get("resource") or None, "ripestat")
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


class AsnResolver:
    def __init__(self, asn_file: Optional[Path] = None, use_network: bool = True,
                 cache_path: Optional[Path] = None, timeout: float = 5.0, opener=None):
        self.use_network = use_network
        self.timeout = timeout
        self.cache_path = cache_path
        self.opener = opener or urllib.request.urlopen
        self._nets: list[tuple[ipaddress._BaseNetwork, AsnInfo]] = []
        self._cache: dict[str, dict] = {}
        self._dirty = False
        if asn_file:
            raw = json.loads(Path(asn_file).read_text(encoding="utf-8"))
            for key, val in raw.items():
                if key.startswith("_"):
                    continue
                net = ipaddress.ip_network(key, strict=False)
                self._nets.append((net, AsnInfo(int(val["asn"]), _clean_name(val.get("name", "")),
                                                str(net), "file")))
            self._nets.sort(key=lambda x: -x[0].prefixlen)   # longest prefix first
        if cache_path and Path(cache_path).exists():
            try:
                self._cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._cache = {}

    def lookup(self, ip: str) -> Optional[AsnInfo]:
        addr = ipaddress.ip_address(ip)
        for net, info in self._nets:
            if addr in net:
                return info
        cls = classify_ip(ip)
        if cls != "public":
            return AsnInfo(None, _LOCAL_NAMES.get(cls, cls.split(" (")[0].capitalize()), None, "local")
        cached = self._cache.get(ip)
        if cached:
            return AsnInfo(cached["asn"], cached["name"], cached.get("prefix"), "ripestat")
        if not self.use_network:
            return None
        info = self._fetch(ip)
        if info:
            self._cache[ip] = {"asn": info.asn, "name": info.name, "prefix": info.prefix}
            self._dirty = True
        return info

    def _fetch(self, ip: str) -> Optional[AsnInfo]:
        ipaddress.ip_address(ip)   # never build a URL from unvalidated text
        url = API_URL.format(ip=urllib.parse.quote(ip, safe=""))
        req = urllib.request.Request(url, headers={"User-Agent": "TraceYourPacket/2.1"})
        try:
            with self.opener(req, timeout=self.timeout) as resp:
                body = resp.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise ValueError("response too large")
            return parse_ripestat(json.loads(body))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.warning("ASN lookup failed for %s: %s", ip, exc)
            return None

    def lookup_many(self, ips: list[str], workers: int = 8) -> dict[str, Optional[AsnInfo]]:
        uniq = list(dict.fromkeys(ips))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            return dict(zip(uniq, ex.map(self.lookup, uniq)))

    def save(self) -> None:
        if not (self._dirty and self.cache_path):
            return
        try:
            Path(self.cache_path).parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(str(self.cache_path) + ".tmp")
            tmp.write_text(json.dumps(self._cache), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except OSError as exc:
            log.warning("could not write ASN cache: %s", exc)


def colour_for(key: str, order: list[str]) -> str:
    """Colour of a network: local is grey, others take palette colours in route order."""
    if key == "local":
        return LOCAL_COLOR
    nets = [k for k in order if k != "local"]
    return NET_PALETTE[nets.index(key) % len(NET_PALETTE)] if key in nets else NET_PALETTE[0]
