"""IP classification and geolocation (with cache, timeout and offline mode)."""
from __future__ import annotations

import ipaddress
import json
import logging
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger("tracemap.geo")

API_URL = "https://geolocation-db.com/json/{ip}"

_NETS = [
    ("private (RFC 1918)", ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]),
    ("carrier-grade NAT (RFC 6598)", ["100.64.0.0/10"]),
    ("loopback", ["127.0.0.0/8"]),
    ("link-local", ["169.254.0.0/16"]),
    ("documentation range", ["192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"]),
    ("benchmarking range", ["198.18.0.0/15"]),
]
_PARSED = [(label, [ipaddress.ip_network(n) for n in nets]) for label, nets in _NETS]


def classify_ip(ip: str) -> str:
    """Return a short label: 'public' or the reserved range the address is in."""
    addr = ipaddress.ip_address(ip)
    for label, nets in _PARSED:
        if any(addr in n for n in nets):
            return label
    return "public" if addr.is_global else "reserved"


def is_public(ip: str) -> bool:
    return classify_ip(ip) == "public"


@dataclass
class GeoInfo:
    lat: float
    lon: float
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    org: Optional[str] = None

    @property
    def label(self) -> str:
        parts = [p for p in (self.city, self.country) if p]
        return ", ".join(parts) if parts else f"{self.lat:.2f}, {self.lon:.2f}"


def _clean(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", "Not found", "None", "null") else text


def _from_dict(d: dict) -> Optional[GeoInfo]:
    try:
        lat = float(d["latitude"] if "latitude" in d else d["lat"])
        lon = float(d["longitude"] if "longitude" in d else d["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if lat == 0.0 and lon == 0.0:
        return None
    return GeoInfo(
        lat=lat,
        lon=lon,
        city=_clean(d.get("city")),
        region=_clean(d.get("state") or d.get("region")),
        country=_clean(d.get("country_name") or d.get("country")),
        org=_clean(d.get("org")),
    )


def haversine_km(a: GeoInfo, b: GeoInfo) -> float:
    r = 6371.0088
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def default_cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "tracemap" / "geo.json"


class GeoResolver:
    """Look up IPs: geo file first, then cache, then the network API.

    Only public addresses are ever sent to the API. Pass use_network=False
    to stay fully offline.
    """

    def __init__(
        self,
        geo_file: Optional[Path] = None,
        use_network: bool = True,
        cache_path: Optional[Path] = None,
        timeout: float = 5.0,
    ):
        self.use_network = use_network
        self.timeout = timeout
        self.cache_path = cache_path
        self._file: dict[str, dict] = {}
        self._cache: dict[str, dict] = {}
        self._dirty = False
        if geo_file:
            self._file = json.loads(Path(geo_file).read_text())
        if cache_path and Path(cache_path).exists():
            try:
                self._cache = json.loads(Path(cache_path).read_text())
            except (OSError, ValueError):
                self._cache = {}

    def lookup(self, ip: str) -> Optional[GeoInfo]:
        if ip in self._file:  # an explicit entry always wins
            return _from_dict(self._file[ip])
        if not is_public(ip):
            return None
        if ip in self._cache:
            return _from_dict(self._cache[ip])
        if not self.use_network:
            return None
        info = self._fetch(ip)
        if info:
            self._cache[ip] = asdict(info) | {"latitude": info.lat, "longitude": info.lon}
            self._dirty = True
        return info

    def _fetch(self, ip: str) -> Optional[GeoInfo]:
        ipaddress.ip_address(ip)  # never build a URL from unvalidated text
        url = API_URL.format(ip=ip)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                charset = resp.info().get_content_charset("utf-8")
                data = json.loads(resp.read().decode(charset))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.warning("geolocation lookup failed for %s: %s", ip, exc)
            return None
        return _from_dict(data) if isinstance(data, dict) else None

    def save(self) -> None:
        if not (self._dirty and self.cache_path):
            return
        try:
            Path(self.cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.cache_path).write_text(json.dumps(self._cache))
        except OSError as exc:
            log.warning("could not write geo cache: %s", exc)
