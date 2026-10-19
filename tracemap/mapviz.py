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
from .sanity import check_hops
from .asn import AsnInfo, colour_for


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
    asn: Optional[dict] = None,
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

    findings = check_hops(trace, geo, origin)
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
        info = (asn or {}).get(h.ip) if h.ip else None
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
            "host": next((r.hostname for r in h.responders if r.hostname), None),
            "locSource": g.source if g else None,
            "locNote": g.note if g else None,
            "net": (info.key if info else ("unknown" if h.ip else None)),
            "asnLabel": (info.label if info else None),
            "check": ({"level": findings[idx].level, "msg": findings[idx].message()}
                      if idx in findings else None),
        })

    order: list[str] = []
    labels: dict[str, str] = {}
    for h, ho in zip(trace.hops, hops_out):
        if ho["net"] and ho["net"] not in order:
            order.append(ho["net"])
        if ho["net"] and ho["asnLabel"]:
            labels.setdefault(ho["net"], ho["asnLabel"])
    nets_out = []
    for k in order:
        col = "#6b7894" if k == "unknown" else colour_for(k, order)
        nets_out.append({"key": k, "label": ("Unknown network" if k == "unknown" else labels.get(k, k)),
                         "color": col, "hops": [ho["ttl"] for ho in hops_out if ho["net"] == k]})
    handoffs = find_handoffs(hops_out)
    for ho in hops_out:
        ho["handoff"] = next((x for x in handoffs if x["ttl"] == ho["ttl"]), None)

    if graph is None:
        graph = CableGraph(cableset.cables)
    legs = route_stations(graph, [(s["lon"], s["lat"]) for s in stations])
    legs_out = []
    used: list[str] = []
    for leg in legs:
        for n in leg.cables:
            if n not in used:
                used.append(n)
        arrive = next((ho for ho in hops_out if ho["station"] == len(legs_out) + 1 and ho["net"]), None)
        legs_out.append({
            "net": (arrive["net"] if arrive else (legs_out[-1]["net"] if legs_out else None)),
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
        "nets": nets_out,
        "handoffs": handoffs,
        "warnings": len(findings),
        "cables": {
            "features": features,
            "landings": list(landings.values())[:5000],
            "source": cableset.source,
            "attribution": cableset.attribution,
            "real": cableset.real,
            "note": cableset.note,
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


def cable_section_html(data: dict) -> str:
    """Leg-by-leg cable table for the report (all text escaped)."""
    st, hops, legs = data["stations"], data["hops"], data["legs"]
    # best observed RTT per station (last hop that sits at that station)
    rtt_at: dict[int, float] = {}
    ttl_at: dict[int, list[int]] = {}
    for h in hops:
        ttl_at.setdefault(h["station"], []).append(h["ttl"])
        if h["rtt"]:
            rtt_at[h["station"]] = h["rtt"]["avg"]
    rows = []
    prev = None
    for i, leg in enumerate(legs):
        a, b = st[i], st[i + 1]
        floor = leg["km"] / 100.0  # round trip over fibre ~ 2 * km / 200 km per ms
        ra, rb = rtt_at.get(i), rtt_at.get(i + 1)
        delta = f"{rb - ra:+.1f} ms" if ra is not None and rb is not None else "-"
        kinds = []
        for sg in leg["segments"]:
            kinds.append("cable: " + (sg["name"] or "unnamed") if sg["kind"] == "cable"
                         else "overland link (straight-line estimate)")
        ttls = ttl_at.get(i + 1, [])
        rows.append(
            "<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (i + 1, escape(a["label"]), escape(b["label"]),
               ", ".join("TTL %s" % t for t in ttls) or "-",
               "{:,.0f} km".format(leg["km"]),
               "{:,.0f} km".format(leg["cableKm"]),
               escape("; ".join(kinds) or "direct"),
               "%s / %.1f ms" % (delta, floor))
        )
    stt = data["stats"]
    used = ", ".join(escape(n) for n in data["usedCables"]) or "none"
    src = escape(data["cables"]["source"])
    note = (
        "Cable names are illustrative corridors, not real systems." if not data["cables"]["real"]
        else "Cable geometry from " + escape(data["cables"]["attribution"])
    )
    pct = (100.0 * stt["cableKm"] / stt["totalKm"]) if stt["totalKm"] else 0
    return (
        "<h2>Cable path, leg by leg</h2>"
        "<style>.stats>div>b,.stats>div>span{{display:block}}</style>"
        "<div class='stats'>"
        "<div><b>{:,.0f} km</b><span>total path</span></div>"
        "<div><b>{:,.0f} km</b><span>on submarine cable ({:.0f}%)</span></div>"
        "<div><b>{:,.0f} km</b><span>overland estimate</span></div>"
        "<div><b>{}</b><span>fibre RTT floor</span></div>"
        "<div><b>{}</b><span>observed RTT</span></div></div>".format(
            stt["totalKm"], stt["cableKm"], pct, stt["landKm"],
            "-" if stt["floorMs"] is None else "%.0f ms" % stt["floorMs"],
            "-" if stt["rttMs"] is None else "%.0f ms" % stt["rttMs"])
        + "<div class='scroll'><table class='hops'><thead><tr><th>Leg</th><th>From</th><th>To</th>"
          "<th>Hops arriving</th><th>Length</th><th>On cable</th><th>Carried by</th>"
          "<th>RTT step / floor</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        "<p><b>Cables on this route:</b> " + used + "</p>"
        "<p class='muted'>How to read this. Traceroute reports routers, not cables, so the carrier of each "
        "leg is inferred: the shortest path over a graph of cable landing points, with straight-line "
        "overland links where no cable is near. Length is great-circle or along the drawn cable. "
        "The floor is the round-trip time light needs in fibre (about 200 km per ms one way); the "
        "observed step should be at or above it, and a step far above it points to queueing, detours "
        "or a longer real route. A hop whose location came from an IP database may sit at the "
        "operator's head office, not at the router. Cable data: " + src + ". " + note + "</p>"
    )


def hop_cable_notes(data: dict) -> dict[int, str]:
    """Hop index -> HTML note saying which leg and cable the probe used to get there."""
    st, hops, legs = data["stations"], data["hops"], data["legs"]
    out: dict[int, str] = {}
    seen_station = 0
    for i, h in enumerate(hops):
        s = h["station"]
        if s > seen_station and s - 1 < len(legs):
            leg = legs[s - 1]
            names = [sg["name"] for sg in leg["segments"] if sg["kind"] == "cable" and sg["name"]]
            how = ("over " + ", ".join(escape(n) for n in dict.fromkeys(names))) if names else "over land (straight-line estimate)"
            out[i] = (
                "<b>Cable map:</b> this probe moved from <b>%s</b> to <b>%s</b>, %s km (%s km on cable), %s. "
                "Light needs at least %.1f ms round trip for that leg."
                % (escape(st[s - 1]["label"]), escape(st[s]["label"]),
                   "{:,.0f}".format(leg["km"]), "{:,.0f}".format(leg["cableKm"]), how, leg["km"] / 100.0)
            )
            seen_station = s
        elif h["located"] or h["ip"]:
            out[i] = ("<b>Cable map:</b> still at <b>%s</b>, so no long-haul link was crossed to reach this hop."
                      % escape(st[s]["label"]))
    return out


def find_handoffs(hops: list[dict]) -> list[dict]:
    """Where traffic changes from one network to the next (local and unknown hops are skipped).

    The first public network is "your ISP"; its first change is where you leave it.
    """
    out: list[dict] = []
    prev = None
    for h in hops:
        k = h.get("net")
        if not k or k in ("local", "unknown"):
            continue
        if prev and k != prev["net"]:
            out.append({"ttl": h["ttl"], "ip": h["ip"], "from": prev["label"], "to": h["asnLabel"] or k,
                        "fromKey": prev["net"], "toKey": k, "leavesIsp": not out})
        prev = {"net": k, "label": h["asnLabel"] or k}
    return out


def network_section_html(data: dict) -> str:
    """Report section: the networks on the path and where traffic changes hands."""
    nets, handoffs = data.get("nets") or [], data.get("handoffs") or []
    if not nets:
        return ""
    rows = []
    for n in nets:
        ttls = n["hops"]
        span = "TTL %d" % ttls[0] if len(ttls) == 1 else "TTL %d to %d (%d hops)" % (ttls[0], ttls[-1], len(ttls))
        rows.append("<tr><td><span style='display:inline-block;width:11px;height:11px;border-radius:3px;"
                    "background:%s;margin-right:8px'></span>%s</td><td>%s</td></tr>"
                    % (escape(n["color"]), escape(n["label"]), escape(span)))
    hand = "".join(
        "<li><b>TTL %d</b> (<span class='mono'>%s</span>): %s &rarr; <b>%s</b>%s</li>"
        % (h["ttl"], escape(h["ip"] or "?"), escape(h["from"]), escape(h["to"]),
           " <i>(you leave your ISP here)</i>" if h["leavesIsp"] else "")
        for h in handoffs)
    return (
        "<h2>Networks on the path</h2>"
        "<p class='muted'>Each router address belongs to one network (autonomous system). The map colours "
        "the route by network. Where the colour changes, your traffic is handed from one operator to the next.</p>"
        "<div class='scroll'><table class='hops'><thead><tr><th>Network</th><th>Hops</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table></div>"
        + ("<h3>Handoffs</h3><ul>" + hand + "</ul>" if hand else
           "<p class='muted'>No change of network was seen on the public part of the path.</p>")
        + "<p class='muted'>Network data comes from RIPEstat or your --asn-file. Private and carrier-grade NAT "
          "addresses belong to your own or your ISP's network and are shown as local.</p>"
    )
