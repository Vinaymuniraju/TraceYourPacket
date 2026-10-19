"""Use router hostnames (airport and city codes) to check or correct IP-database locations.

Operators name routers after the city they sit in, for example ``ae-1.cr2-fra2.ip.example.net``
(Frankfurt) or ``be2.ear1.london1.level3.net``. That is usually more accurate than an IP database,
which often places every address of a carrier at its head office.

A hostname is a hint, not proof, so it only changes a location when the physics agrees:

* no IP-database location at all: the hint is used and marked ``source="hostname"``;
* the database already agrees (within 300 km): nothing changes;
* they disagree and the RTT rules out the database location but not the hint: the hint wins and
  the hop gets a note saying so;
* they disagree and the RTT rules out neither: the database location stays and a note says what
  the hostname suggested.
"""
from __future__ import annotations

import json
import re
import socket
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Optional

from .geo import GeoInfo, classify_ip, haversine_km
from .parser import Trace
from .sanity import _reference, judge
from .cables import ASSETS

_TABLE: Optional[dict] = None
AGREE_KM = 300.0
_PART = re.compile(r"^([a-z]{3,})(\d{0,3})$")


@dataclass
class Hint:
    city: str
    country: str
    lat: float
    lon: float
    token: str

    def geo(self, note: Optional[str] = None) -> GeoInfo:
        return GeoInfo(self.lat, self.lon, self.city, None, self.country, None,
                       source="hostname", note=note)


def _table() -> dict:
    global _TABLE
    if _TABLE is None:
        _TABLE = json.loads((ASSETS / "city_codes.json").read_text(encoding="utf-8"))
    return _TABLE


def hint_from_hostname(host: Optional[str]) -> Optional[Hint]:
    """Return the city a router hostname points to, or None when absent or ambiguous."""
    if not host or len(host) > 253:
        return None
    t = _table()
    labels = host.lower().rstrip(".").split(".")
    scan = labels[:-2] if len(labels) > 2 else labels[:1]   # skip operator.tld
    found: dict[str, Hint] = {}
    for label in scan:
        for part in re.split(r"[-_]", label):
            m = _PART.match(part)
            if not m:
                continue
            word, digits = m.group(1), m.group(2)
            code = None
            if len(word) == 3 and digits and word in t["codes"]:
                code = word                      # lax1, fra02: needs the digit to be trusted
            elif len(word) >= 4 and word in t["names"]:
                code = t["names"][word]          # london, frankfurt1
            if code:
                city, country, lat, lon = t["codes"][code]
                found.setdefault(city, Hint(city, country, lat, lon, part))
    return next(iter(found.values())) if len(found) == 1 else None


def reverse_dns(ips: list[str], timeout: float = 4.0, workers: int = 16) -> dict[str, str]:
    """PTR lookups for public addresses only, with an overall deadline."""
    targets = [ip for ip in dict.fromkeys(ips) if classify_ip(ip) == "public"]
    out: dict[str, str] = {}
    if not targets:
        return out

    def one(ip):
        try:
            return ip, socket.gethostbyaddr(ip)[0]
        except (OSError, UnicodeError):
            return ip, None

    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        futs = [ex.submit(one, ip) for ip in targets]
        done, _ = wait(futs, timeout=timeout)
        for f in done:
            ip, name = f.result()
            if name:
                out[ip] = name
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return out


def apply_hints(trace: Trace, geo: dict, origin: Optional[tuple[float, float]] = None,
                names: Optional[dict[str, str]] = None) -> list[str]:
    """Update `geo` in place using hostnames. Returns one human-readable line per change/disagreement."""
    names = names or {}
    messages: list[str] = []
    ref = _reference(trace, geo, origin)
    for h in trace.hops:
        if not h.ip:
            continue
        host = names.get(h.ip) or next((r.hostname for r in h.responders if r.ip == h.ip and r.hostname), None)
        hint = hint_from_hostname(host)
        if not hint:
            continue
        db = geo.get(h.ip)
        if db is None:
            note = f"Located from the hostname {host} ({hint.token}); the IP database had no entry."
            geo[h.ip] = hint.geo(note)
            messages.append(f"hop {h.ttl} {h.ip}: {note}")
            continue
        dist = haversine_km(db, GeoInfo(hint.lat, hint.lon))
        if dist < AGREE_KM:
            continue
        cand = GeoInfo(hint.lat, hint.lon)
        if ref:
            db_bad = judge(h.rtts, db, *ref)
            hint_bad = judge(h.rtts, cand, *ref)
        else:
            db_bad = hint_bad = None
        if db_bad and not hint_bad:
            note = (f"Hostname {host} says {hint.city} ({hint.token}), {dist:,.0f} km from the IP database "
                    f"location {db.label}. The RTT rules out {db.label}, so {hint.city} is used.")
            geo[h.ip] = hint.geo(note)
        else:
            note = (f"Hostname {host} suggests {hint.city} ({hint.token}), {dist:,.0f} km from "
                    f"{db.label}. Kept {db.label} because the RTT does not settle it.")
            db.note = note
        messages.append(f"hop {h.ttl} {h.ip}: {note}")
    return messages
