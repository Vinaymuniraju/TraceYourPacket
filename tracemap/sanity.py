"""Physical sanity checks on hop locations.

A probe cannot beat the speed of light, so a reply that comes back faster than the round trip
over the straight-line distance means the router is not where the geolocation database says.

Two levels:

* ``impossible``: RTT is below the round trip at the speed of light in a vacuum (about 300 km/ms).
  No network can do this, so the location is certainly wrong.
* ``suspicious``: RTT is below the round trip at the speed of light in fibre (about 200 km/ms)
  over the straight line. Real fibre is never straighter than that, so the location is very
  likely wrong (or the hop is anycast: the same address answers from many places).

If your own position is unknown, distances are measured from the first located hop and the
bound is relaxed by that hop's own RTT: your true distance to it is at most RTT * speed / 2,
so subtracting it keeps the check valid.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .geo import GeoInfo, haversine_km
from .parser import Trace

C_VACUUM_KM_MS = 299.792
C_FIBRE_KM_MS = 200.0
MIN_KM = 300.0       # closer than this, city-level geolocation error swamps the check
FIBRE_TOLERANCE = 0.95


@dataclass
class Finding:
    level: str        # "impossible" | "suspicious"
    rtt_ms: float     # the hop's best (minimum) RTT
    floor_ms: float   # the physical minimum it was compared against
    km: float         # straight-line distance used
    basis: str        # "you" or "first hop"

    def message(self) -> str:
        what = ("faster than light in a vacuum" if self.level == "impossible"
                else "faster than light in fibre over a straight line")
        return (f"Best RTT {self.rtt_ms:.1f} ms is {what} for {self.km:,.0f} km from "
                f"{self.basis} (minimum {self.floor_ms:.1f} ms). The location is probably wrong, "
                "or this address is anycast.")


def _reference(trace: Trace, geo, origin):
    """Return (ref_latlon, slack_ms, basis) or None when no reference point exists."""
    if origin:
        return origin, 0.0, "you"
    for h in trace.hops:
        g = geo.get(h.ip) if h.ip else None
        if g and h.rtts:
            return (g.lat, g.lon), min(h.rtts), "the first located hop"
    return None


def judge(rtts: list, loc: GeoInfo, ref, slack: float, basis: str) -> Optional[Finding]:
    """Compare one hop's RTTs with the minimum physically possible for location `loc`."""
    if not rtts:
        return None
    km = haversine_km(GeoInfo(ref[0], ref[1]), loc)
    if km < MIN_KM:
        return None
    best = min(rtts)
    vac = 2 * km / C_VACUUM_KM_MS - slack
    fib = (2 * km / C_FIBRE_KM_MS) * FIBRE_TOLERANCE - slack
    if best < vac:
        return Finding("impossible", best, max(vac, 0.0), km, basis)
    if best < fib:
        return Finding("suspicious", best, max(fib, 0.0), km, basis)
    return None


def check_hops(trace: Trace, geo: dict[str, Optional[GeoInfo]],
               origin: Optional[tuple[float, float]] = None) -> dict[int, Finding]:
    """Map hop index -> Finding for hops whose RTT contradicts their location."""
    out: dict[int, Finding] = {}
    r = _reference(trace, geo, origin)
    if r is None:
        return out
    ref, slack, basis = r
    for idx, h in enumerate(trace.hops):
        g = geo.get(h.ip) if h.ip else None
        if g:
            f = judge(h.rtts, g, ref, slack, basis)
            if f:
                out[idx] = f
    return out
