"""Build the interactive, self-contained map: cables, inferred route, animated packets."""
from __future__ import annotations

import json
import re
from html import escape
from typing import Optional

from .cables import ASSETS, CableGraph, CableSet, decimate, hav_km, route_stations
from .geo import GeoInfo, classify_ip
from .parser import Trace
from .report import METHODS, _role


_PORTS = {"udp": "dst port 33434+", "icmp": "", "tcp": "dst port 80"}


def _r(coords, nd):
    return [[round(x, nd), round(y, nd)] for x, y in coords]


def _json_for_script(obj) -> str:
    """JSON that is safe inside a <script> element."""
    return (
        json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def build_map_data(
    trace: Trace,
    geo: dict[str, Optional[GeoInfo]],
    method: str,
    cableset: CableSet,
    origin: Optional[tuple[float, float]] = None,
    graph: Optional[CableGraph] = None,
) -> Optional[dict]:
    """Return the data blob for the map, or None when nothing can be placed."""
    method = method if method in METHODS else "udp"
    located_any = any(h.ip and geo.get(h.ip) for h in trace.hops)
    if not located_any and not origin:
        return None

    stations: list[dict] = []
    origin_guess = origin is None
    if origin:
        stations.append({"lat": origin[0], "lon": origin[1], "label": "You"})
    else:
        first = next(geo[h.ip] for h in trace.hops if h.ip and geo.get(h.ip))
        stations.append({"lat": first.lat, "lon": first.lon, "label": first.label})

    hops_out = []
    for idx, h in enumerate(trace.hops):
        g = geo.get(h.ip) if h.ip else None
        if g:
            last = stations[-1]
            can_merge = len(stations) > 1 or origin_guess
            near = hav_km((last["lon"], last["lat"]), (g.lon, g.lat)) < 5.0
            if can_merge and near:
                station = len(stations) - 1
            else:
                stations.append({"lat": g.lat, "lon": g.lon, "label": g.label})
                station = len(stations) - 1
        else:
            station = len(stations) - 1  # no location: assume it sits where the last known hop is
        cls = classify_ip(h.ip) if h.ip else "-"
        is_dest = trace.reached and idx == len(trace.hops) - 1
        hops_out.append({
            "ttl": h.ttl,
            "ip": h.ip,
            "cls": cls,
            "role": _role(h, idx, cls, is_dest) if h.ip else "no reply",
            "rtt": ({"min": h.rtt_min, "avg": h.rtt_avg, "max": h.rtt_max} if h.rtts else None),
            "lost": h.lost if h.ip is None else 0,
            "flags": h.flags,
            "station": station,
            "located": bool(g),
            "label": g.label if g else "",
        })

    if graph is None:
        graph = CableGraph(cableset.cables)
    legs = route_stations(graph, [(s["lon"], s["lat"]) for s in stations])
    legs_out = []
    used: list[str] = []
    for leg in legs:
        for n in leg.cables:
            if n not in used:
                used.append(n)
        legs_out.append({
            "km": round(leg.km, 1),
            "cableKm": round(leg.cable_km, 1),
            "cables": leg.cables,
            "segments": [
                {"kind": s.kind, "name": s.name, "color": s.color,
                 "km": round(s.km, 1), "coords": _r(s.coords, 4)}
                for s in leg.segments
            ],
        })

    # Cables for the backdrop; real data is thinned so the page stays small.
    features, landings = [], {}
    for cab in cableset.cables:
        lines = []
        for ln in cab.lines:
            ln2 = decimate(ln, 12.0) if cableset.real else ln
            lines.append(_r(ln2, 2 if cableset.real else 3))
            for p in (ln[0], ln[-1]):
                landings[(round(p[0], 1), round(p[1], 1))] = [round(p[0], 2), round(p[1], 2)]
        features.append({"n": cab.name, "c": cab.color, "l": lines})

    total = sum(l.km for l in legs)
    cable_km = sum(l.cable_km for l in legs)
    answered = [h for h in trace.hops if h.ip and h.rtt_avg is not None]
    rtt = answered[-1].rtt_avg if answered else None
    m = METHODS[method]
    return {
        "target": trace.target,
        "target_ip": trace.target_ip,
        "reached": trace.reached,
        "originGuess": origin_guess,
        "proto": {"name": m["name"], "port": _PORTS[method]},
        "final_short": m["final_short"],
        "stations": stations,
        "hops": hops_out,
        "legs": legs_out,
        "usedCables": used,
        "cables": {
            "features": features,
            "landings": list(landings.values())[:5000],
            "source": cableset.source,
            "attribution": cableset.attribution,
            "real": cableset.real,
        },
        "stats": {
            "totalKm": total,
            "cableKm": cable_km,
            "landKm": total - cable_km,
            "floorMs": (total / 100.0) if total else None,
            "rttMs": rtt,
        },
    }


def render_map(data: dict) -> str:
    """Inline everything into one HTML file that works offline."""
    tpl = (ASSETS / "map.html").read_text(encoding="utf-8")
    libs = {
        "__D3__": (ASSETS / "d3.min.js").read_text(encoding="utf-8"),
        "__TOPO__": (ASSETS / "topojson-client.min.js").read_text(encoding="utf-8"),
        "__JS__": (ASSETS / "map.js").read_text(encoding="utf-8"),
    }
    for name, text in libs.items():
        if "</script" in text.lower():
            raise RuntimeError(f"{name} contains a closing script tag and cannot be inlined")
    world = (ASSETS / "countries-50m.json").read_text(encoding="utf-8")
    title = escape(f"Packet path to {data.get('target') or data.get('target_ip')}")
    repl = {
        "TITLE": title,
        "CSS": (ASSETS / "map.css").read_text(encoding="utf-8"),
        "DATA": _json_for_script(data),
        "WORLD": world,
        "D3": libs["__D3__"],
        "TOPO": libs["__TOPO__"],
        "JS": libs["__JS__"],
    }
    # One pass over the template: inserted text is never scanned for placeholders again.
    return re.sub(r"__(TITLE|CSS|DATA|WORLD|D3|TOPO|JS)__", lambda m: repl[m.group(1)], tpl)
