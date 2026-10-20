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
from .parser import merge_traces, parse_traceroute
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
        prog="tracemap",
        description="Trace the route to a host, plot it on a map and write a "
        "packet-path report.",
    )
    p.add_argument("target", nargs="?", help="IPv4 address or hostname")
    p.add_argument("--method", choices=["udp", "icmp", "tcp"], default=None,
                   help="probe type (default: udp; tracert on Windows is always icmp)")
    p.add_argument("--max-hops", type=int, default=25, help="maximum TTL (default 25)")
    p.add_argument("--timeout", type=float, default=300.0,
                   help="kill traceroute after this many seconds (default 300)")
    p.add_argument("--probes", type=int, default=3, metavar="N",
                   help="probes per hop on Linux/macOS, 1 to 10 (default 3). More probes reveal more "
                        "load-balanced branches")
    p.add_argument("--runs", type=int, default=1, metavar="N",
                   help="run traceroute N times (1 to 5) and merge the results to find more branches")
    p.add_argument("--input", type=Path, metavar="FILE", action="append",
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
    p.add_argument("--png", action="store_true",
                   help="also write the classic static PNG map (default: only when no cable map is made)")
    p.add_argument("--no-rdns", action="store_true",
                   help="do not look up router hostnames (they are used as location hints)")
    p.add_argument("--asn-file", type=Path, metavar="JSON",
                   help="prefix to AS number/name entries, used before any lookup (see samples/asn_sample.json)")
    p.add_argument("--no-asn", action="store_true",
                   help="do not look up which network (AS) each hop belongs to")
    p.add_argument("--refresh-cables", action="store_true",
                   help="ignore the cached cable data and download it again")
    p.add_argument("--open", action="store_true",
                   help="open the finished report in your browser")
    p.add_argument("--no-map", action="store_true", help="skip the interactive cable map")
    p.add_argument("--no-report", action="store_true", help="skip the HTML packet-path report")
    p.add_argument("--show", action="store_true", help="open an interactive map window")
    p.add_argument("--history-dir", type=Path, metavar="DIR",
                   help="where saved runs live (default ~/.local/share/tracemap/history)")
    p.add_argument("--no-save", action="store_true", help="do not save this run to the history")
    p.add_argument("--history", action="store_true",
                   help="list saved runs (for the target, or all) and exit")
    p.add_argument("--from-run", type=Path, metavar="FILE",
                   help="rebuild the report from a saved run file instead of tracing again")
    p.add_argument("--run-time", metavar="UTC",
                   help="timestamp to record for this run, like 2026-10-19T16:30:00Z (default now)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    from .analysis import Options, analyse
    from .snapshot import (SnapshotError, default_history_dir, list_runs, load_snapshot,
                           save_snapshot)

    hist_dir = args.history_dir or default_history_dir()
    if args.history:
        runs = list_runs(hist_dir, args.target)
        if not runs:
            print(f"no saved runs in {hist_dir}")
            return 0
        for tgt, path in runs:
            print(f"{tgt:30} {path.stem}  {path}")
        return 0

    if args.run_time and not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", args.run_time):
        print("error: --run-time must look like 2026-10-19T16:30:00Z", file=sys.stderr)
        return 2

    opts = Options(offline=args.offline, no_cache=args.no_cache, geo_file=args.geo_file,
                   asn_file=args.asn_file, no_asn=args.no_asn, no_rdns=args.no_rdns)

    if args.from_run:
        try:
            an = load_snapshot(args.from_run)
        except SnapshotError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.origin:
            an.origin = args.origin
        trace, method = an.trace, an.method
        print(f"loaded: {args.from_run} (taken {an.taken_at})")
    else:
        # 1. Get the raw traceroute text.
        texts: list[str] = []
        if args.input:
            try:
                texts = [f.read_text() for f in args.input]
            except OSError as exc:
                print(f"error: cannot read input: {exc}", file=sys.stderr)
                return 2
        else:
            if not args.target:
                print("error: give a target, --input FILE or --from-run FILE", file=sys.stderr)
                return 2
            try:
                name, ip = validate_target(args.target)
                if not 1 <= args.runs <= 5:
                    raise ValueError("runs must be between 1 and 5")
                cmd = build_command(ip, args.method or "udp", args.max_hops, probes=args.probes)
            except (TargetError, ValueError, RuntimeError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            print(f"$ {' '.join(cmd)}")
            try:
                for n in range(args.runs):
                    if args.runs > 1:
                        print(f"run {n + 1} of {args.runs}")
                    texts.append(run_traceroute(cmd, timeout=args.timeout))
            except RuntimeError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1

        # 2. Parse it.
        traces = [parse_traceroute(t) for t in texts]
        trace = merge_traces(traces) if len(traces) > 1 else traces[0]
        if not args.input:
            trace.target = trace.target or name
            trace.target_ip = trace.target_ip or ip
        elif args.target:
            trace.target = args.target
        if not trace.hops:
            print("error: no hops found in the traceroute output", file=sys.stderr)
            return 1
        method = args.method or ("icmp" if trace.style == "windows" else "udp")

        # 3. Locations, networks, hostname hints and sanity checks.
        an = analyse(trace, method, args.origin, opts, taken_at=args.run_time)
        for msg in an.hint_messages:
            print(f"hint:   {msg}", file=sys.stderr)

    geo, asn_map, names = an.geo, an.asn, an.names
    located = [(h, geo[h.ip]) for h in trace.hops if h.ip and geo.get(h.ip)]

    saved_path = None
    if not args.no_save and not args.from_run:
        try:
            saved_path = save_snapshot(an, hist_dir)
            print(f"saved:  {saved_path}")
        except OSError as exc:
            print(f"note:   could not save the run: {exc}", file=sys.stderr)

    # 4. Outputs.
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", trace.target or "route")
    args.outdir.mkdir(parents=True, exist_ok=True)
    png = args.outdir / f"route_{safe}.png"

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
                        "hostname": r.hostname or names.get(r.ip),
                        "rtts_ms": r.rtts,
                        "location": (geo[r.ip].label if geo.get(r.ip) else None),
                        "asn": (asn_map[r.ip].asn if asn_map.get(r.ip) else None),
                        "network": (asn_map[r.ip].name if asn_map.get(r.ip) else None),
                        "location_source": (geo[r.ip].source if geo.get(r.ip) else None),
                        "location_note": (geo[r.ip].note if geo.get(r.ip) else None),
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

    map_doc, cable_html, hop_notes = None, "", None
    findings = an.findings
    for i, f in sorted(findings.items()):
        print(f"warn:   hop {trace.hops[i].ttl} ({trace.hops[i].ip}): {f.message()}", file=sys.stderr)
    if not args.no_map and args.cables != "none":
        from .cables import CableDataError, load_cables
        from .mapviz import build_map_data, cable_section_html, hop_cable_notes, render_map

        try:
            cs = load_cables(args.cables, args.cables_file, offline=args.offline,
                             refresh=args.refresh_cables)
        except CableDataError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if cs.note:
            print(f"note:   {cs.note}", file=sys.stderr)
        mdata = build_map_data(trace, geo, method, cs, an.origin, asn=asn_map)
        if mdata:
            map_doc = render_map(mdata)
            from .latency import latency_section_html
            from .mapviz import network_section_html
            cable_html = (cable_section_html(mdata) + latency_section_html(mdata)
                          + network_section_html(mdata))
            hop_notes = hop_cable_notes(mdata)
            mp = args.outdir / f"route_{safe}_map.html"
            mp.write_text(map_doc, encoding="utf-8")
            print(f"map:    {mp}  (cables: {cs.source})")
        else:
            print("map:    skipped (no hop could be located)")

    if args.png or not map_doc:
        if located:
            try:
                from .plot import plot_route
                plot_route(located, png, show=args.show, origin=an.origin,
                           title=f"Route to {trace.target} ({trace.target_ip})")
                print(f"map:    {png}")
            except ImportError:
                print('error: the static PNG needs the optional plotting packages: '
                      'pip install "traceyourpacket[png]"', file=sys.stderr)
                if args.png:
                    return 1
        else:
            print("note: no hop could be located, so no map was drawn")


    if not args.no_report:
        from .report import render_report

        png_b64 = base64.b64encode(png.read_bytes()).decode() if (located and png.exists() and not map_doc) else None
        html = args.outdir / f"route_{safe}.html"
        html.write_text(render_report(trace, geo, method, png_b64, an.origin, map_doc, cable_html, hop_notes, findings, asn_map), encoding="utf-8")
        print(f"report: {html}")
        if args.open:
            import webbrowser
            if not webbrowser.open(html.resolve().as_uri()):
                print("note:   could not open a browser; open the report file yourself", file=sys.stderr)

    print(f"{len(trace.hops)} hops, destination {'reached' if trace.reached else 'not reached'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
