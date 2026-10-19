"""Command line entry point."""
from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from .geo import GeoResolver, default_cache_path, classify_ip
from .parser import parse_traceroute
from .runner import TargetError, build_command, run_traceroute, validate_target


def _origin(text: str) -> tuple[float, float]:
    try:
        lat, lon = (float(p) for p in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("use LAT,LON, for example 12.97,77.59")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise argparse.ArgumentTypeError("coordinates out of range")
    return lat, lon


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vis_route.py",
        description="Trace the route to a host, plot it on a map and write a "
        "packet-path report.",
    )
    p.add_argument("target", nargs="?", help="IPv4 address or hostname")
    p.add_argument("--method", choices=["udp", "icmp", "tcp"], default=None,
                   help="probe type (default: udp; tracert on Windows is always icmp)")
    p.add_argument("--max-hops", type=int, default=25, help="maximum TTL (default 25)")
    p.add_argument("--timeout", type=float, default=300.0,
                   help="kill traceroute after this many seconds (default 300)")
    p.add_argument("--input", type=Path, metavar="FILE",
                   help="parse a saved traceroute/tracert output instead of running it")
    p.add_argument("--geo-file", type=Path, metavar="JSON",
                   help="use IP -> location entries from this file first")
    p.add_argument("--offline", action="store_true",
                   help="never call the geolocation API (only --geo-file and cache)")
    p.add_argument("--no-cache", action="store_true", help="do not read or write the geo cache")
    p.add_argument("--origin", type=_origin, metavar="LAT,LON",
                   help="draw your own location as the start of the route")
    p.add_argument("-o", "--outdir", type=Path, default=Path("output"),
                   help="where to write the PNG, HTML and JSON (default ./output)")
    p.add_argument("--cables", choices=["auto", "telegeography", "illustrative", "none"],
                   default="auto", help="submarine cable data for the interactive map (default auto)")
    p.add_argument("--cables-file", type=Path, metavar="GEOJSON",
                   help="use your own cable GeoJSON instead of downloading")
    p.add_argument("--no-map", action="store_true", help="skip the interactive cable map")
    p.add_argument("--no-report", action="store_true", help="skip the HTML packet-path report")
    p.add_argument("--show", action="store_true", help="open an interactive map window")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    # 1. Get the raw traceroute text.
    if args.input:
        text = args.input.read_text()
    else:
        if not args.target:
            print("error: give a target or --input FILE", file=sys.stderr)
            return 2
        try:
            name, ip = validate_target(args.target)
            cmd = build_command(ip, args.method or "udp", args.max_hops)
        except (TargetError, ValueError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"$ {' '.join(cmd)}")
        try:
            text = run_traceroute(cmd, timeout=args.timeout)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    # 2. Parse it.
    trace = parse_traceroute(text)
    if not args.input:
        trace.target = trace.target or name
        trace.target_ip = trace.target_ip or ip
    if not trace.hops:
        print("error: no hops found in the traceroute output", file=sys.stderr)
        return 1
    method = args.method or ("icmp" if trace.style == "windows" else "udp")

    # 3. Geolocate public hops.
    resolver = GeoResolver(
        geo_file=args.geo_file,
        use_network=not args.offline,
        cache_path=None if args.no_cache else default_cache_path(),
    )
    geo = {}
    for hop in trace.hops:
        for r in hop.responders:
            if r.ip not in geo:
                geo[r.ip] = resolver.lookup(r.ip)
    resolver.save()
    located = [(h, geo[h.ip]) for h in trace.hops if h.ip and geo.get(h.ip)]

    # 4. Outputs.
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", trace.target or "route")
    args.outdir.mkdir(parents=True, exist_ok=True)
    png = args.outdir / f"route_{safe}.png"
    if located:
        from .plot import plot_route

        plot_route(located, png, show=args.show, origin=args.origin,
                   title=f"Route to {trace.target} ({trace.target_ip})")
        print(f"map:    {png}")
    else:
        print("note: no hop could be located, so no map was drawn")

    data = {
        "target": trace.target,
        "target_ip": trace.target_ip,
        "method": method,
        "reached": trace.reached,
        "hops": [
            {
                "ttl": h.ttl,
                "lost_probes": h.lost,
                "flags": h.flags,
                "responders": [
                    {
                        "ip": r.ip,
                        "class": classify_ip(r.ip),
                        "hostname": r.hostname,
                        "rtts_ms": r.rtts,
                        "location": (geo[r.ip].label if geo.get(r.ip) else None),
                        "lat": geo[r.ip].lat if geo.get(r.ip) else None,
                        "lon": geo[r.ip].lon if geo.get(r.ip) else None,
                    }
                    for r in h.responders
                ],
            }
            for h in trace.hops
        ],
    }
    js = args.outdir / f"route_{safe}.json"
    js.write_text(json.dumps(data, indent=2))
    print(f"data:   {js}")

    if not args.no_report:
        from .report import render_report

        png_b64 = base64.b64encode(png.read_bytes()).decode() if located else None
        html = args.outdir / f"route_{safe}.html"
        html.write_text(render_report(trace, geo, method, png_b64, args.origin), encoding="utf-8")
        print(f"report: {html}")

    if not args.no_map and args.cables != "none":
        from .cables import load_cables
        from .mapviz import build_map_data, render_map

        cs = load_cables(args.cables, args.cables_file, offline=args.offline)
        mdata = build_map_data(trace, geo, method, cs, args.origin)
        if mdata:
            mp = args.outdir / f"route_{safe}_map.html"
            mp.write_text(render_map(mdata), encoding="utf-8")
            print(f"map:    {mp}  (cables: {cs.source})")
        else:
            print("map:    skipped (no hop could be located)")

    print(f"{len(trace.hops)} hops, destination {'reached' if trace.reached else 'not reached'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
