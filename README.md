# TraceYourPacket

**See your packets cross the ocean floor.**

TraceYourPacket runs a traceroute, puts every hop on a map, infers which submarine cables and
overland links the packets probably crossed, and animates the probes and their ICMP replies along
that path. It also writes one self-contained HTML report that explains, hop by hop, what each
router, device and program did with the packet.

- Interactive, zoomable cable map with animated packets (probe by probe, or continuous flow)
- Per-hop technical notes: TTL, ICMP, NAT, CGNAT, load balancing, latency jumps
- Leg-by-leg table: distance, kilometres on cable, which cable, observed RTT against the physical minimum
- Works offline from a saved traceroute; one HTML file, no server, no CDN
- Safe by construction: no shell, validated targets, private addresses never leave your machine

> **Read this first:** the cable path is **inferred, not measured**. Traceroute reports IP routers,
> not cables. See [How the cable path is inferred](#how-the-cable-path-is-inferred).

This started as a rework of [Vinaymuniraju/vis_route](https://github.com/Vinaymuniraju/vis_route)
(itself a fork) and keeps its `./vis_route.py <ip>` entry point. Licence: GPLv3.

## Contents

1. [What you get](#what-you-get)
2. [Quick start](#quick-start)
3. [Usage](#usage)
4. [Reading the map](#reading-the-map)
5. [Reading the report](#reading-the-report)
6. [How it works](#how-it-works)
7. [How the cable path is inferred](#how-the-cable-path-is-inferred)
8. [Data sources and licences](#data-sources-and-licences)
9. [Privacy and security](#privacy-and-security)
10. [Project layout](#project-layout)
11. [Development](#development)
12. [Limits](#limits)
13. [Roadmap](#roadmap)
14. [What changed from the original script](#what-changed-from-the-original-script)

## What you get

For `./vis_route.py 203.0.113.10` the output folder holds:

| File | Contents |
|---|---|
| `route_<target>.html` | The full report. The interactive cable map is pinned at the top and linked to every hop note |
| `route_<target>_map.html` | Just the interactive cable map, as its own file |
| `route_<target>.json` | Hops, RTTs, address classes and locations as data |
| `route_<target>.png` | Classic static map. Only written with `--png`, or when no cable map could be made |

Every HTML file is self-contained: scripts, styles, the world map and the cable data are inlined,
so you can email the file or open it with no network.

An example run on synthetic data is committed in `example_output/`.

## Quick start

```
sudo apt install traceroute          # Linux. macOS and Windows already ship a traceroute
git clone https://github.com/Vinaymuniraju/TraceYourPacket && cd TraceYourPacket
pip install .                        # installs the `tracemap` command (add ".[png]" for the static PNG map)
tracemap 8.8.8.8 --origin 12.97,77.59 --open
```

`--open` opens the finished report in your browser. Without installing, `./vis_route.py 8.8.8.8` and
`python -m tracemap 8.8.8.8` do the same thing from the project folder.

No network and no traceroute binary? Replay the bundled sample:

```
./vis_route.py --input samples/traceroute_sample.txt \
               --geo-file samples/geo_sample.json \
               --offline --cables illustrative --origin 12.97,77.59
```

Requirements: Python 3.9 or newer (developed on 3.13), `numpy`, and a browser. `matplotlib`, `basemap` and `pyproj` are
only needed for the optional static PNG (`pip install ".[png]"`).

## Usage

```
./vis_route.py TARGET [options]
python -m tracemap.cli TARGET [options]      # same thing
```

| Option | Meaning |
|---|---|
| `TARGET` | IPv4 address or hostname |
| `--method udp\|icmp\|tcp` | Probe type. Default `udp`. `icmp` and `tcp` use `traceroute -I` / `-T` and usually need root. `tracert` on Windows is always ICMP |
| `--max-hops N` | Maximum TTL, 1 to 64 (default 25) |
| `--timeout S` | Kill traceroute after S seconds (default 300) |
| `--input FILE` | Parse a saved `traceroute` or `tracert` output instead of running one |
| `--geo-file JSON` | IP to location entries, used before anything else |
| `--offline` | Never call the geolocation API or download cable data (uses `--geo-file`, the cache and bundled data only) |
| `--no-cache` | Do not read or write the geolocation cache |
| `--origin LAT,LON` | Draw your own location as the start of the route |
| `--cables auto\|telegeography\|illustrative\|none` | Cable data source for the map (default `auto`) |
| `--cables-file GEOJSON` | Use your own cable GeoJSON instead of downloading |
| `--refresh-cables` | Ignore the cached cable data and download it again |
| `--no-rdns` | Do not look up router hostnames (they are used as location hints; see below) |
| `--open` | Open the finished report in your browser |
| `--no-map` | Skip the interactive cable map |
| `--no-report` | Skip the HTML report |
| `--png` | Also write the classic static PNG map |
| `--show` | Open the static map in a window (with `--png`) |
| `-o, --outdir DIR` | Output folder (default `./output`) |
| `-v` | Log lookup problems |

Exit codes: `0` success, `1` the traceroute failed or required data was unavailable (for example
`--cables telegeography` with no download and no cache), `2` bad arguments.

### Common recipes

```
./vis_route.py example.org --method icmp            # ICMP probes
./vis_route.py 8.8.8.8 --cables telegeography       # require real cable data
./vis_route.py --input saved.txt --offline          # nothing leaves your machine
./vis_route.py 1.1.1.1 --cables-file my_cables.geojson
./vis_route.py 9.9.9.9 --no-map --png               # classic static map only
```

### Cable data modes

| Mode | Behaviour |
|---|---|
| `auto` | Try the TeleGeography download (cached for 14 days), then an older cached copy, then the bundled illustrative corridors. The map says which one it used and why |
| `telegeography` | Real data only; exits with an error if it cannot be fetched or read from the cache |
| `illustrative` | Bundled hand-placed corridors. Always works offline, clearly labelled on the map |
| `none` | No cables; the route is drawn as plain great-circle legs |

## Reading the map

- **Dark world map** with country borders, a graticule, and every cable drawn as a glowing line.
  Hover a cable to see its name.
- **Route:** white dashes over submarine cable, gold dashes over land (a straight-line estimate).
- **Packets:** blue dots are probes going out, orange dots are ICMP replies coming back, and a red
  burst marks the router where the TTL hit 0.
- **Packet inspector** (top right): current probe, IP TTL, probe type, position along the path,
  hop RTT, and a plain-language line about what is happening.
- **Hop list** (side panel): click a hop to replay it. The bar under each hop shows its RTT.
- **Probe strip** (bottom): one button per TTL; lost probes are red.
- **Controls:** pause, restart, next probe, speed, fit route, world view, probe-by-probe or
  continuous flow, and layer toggles (cables, landings, borders, grid, labels).
- **Zoom and pan** with the mouse wheel and drag. The map auto-orients so the route is centred.
- A chip says whether the cables shown are **illustrative** or **TeleGeography**, and the credit
  line at the bottom is always visible.

## Reading the report

The report page keeps the map pinned at the top while you scroll the technical notes below it.

- **Click any hop card or hop-table row** and that probe replays on the map.
- **Click a hop on the map** and the matching note is highlighted and scrolled into view
  ("Follow playback" turns this on or off, "Pin map" lets the map scroll away).

Sections:

1. **Route on the map:** the interactive cable map.
2. **Cable path, leg by leg:** total path length, kilometres on cable, overland estimate, the
   fibre RTT floor, the observed RTT, and a table per leg (from, to, hops arriving, length, which
   cable carried it, RTT step against the physical floor).
3. **How the packets travelled:** a sequence diagram with one row per TTL showing the probe going
   out, the TTL left after each router, the drop at TTL 0, and the ICMP error returning with its RTT.
4. **Hop table:** address, role, location, RTT min/avg/max with a bar.
5. **What happened at each hop:** one card per TTL, with a "Cable map" note (which leg and cable the
   probe used to get there), the step-by-step packet story, and notes such as CGNAT, load balancing
   and large latency jumps with the distance that explains them.
6. **What each device and program does:** your computer, your home router (NAT), transit routers
   and the destination, plus what this program does before and after.
7. **Packet anatomy:** IPv4 and UDP/ICMP/TCP headers of a probe and of the ICMP "time exceeded"
   reply, with the fields that make traceroute work highlighted.

## Checking the locations

IP-geolocation databases often place a carrier's routers at its head office, which breaks the map.
Two checks, both automatic, catch most of that:

**1. Physics check.** A reply cannot come back faster than light travels there and back. For every
located hop, the best RTT is compared with the straight-line round trip from you (or from the first
located hop when you did not pass `--origin`; the bound is relaxed by that hop's own RTT so it stays valid).

| Level | Meaning |
|---|---|
| `impossible` | Faster than light in a vacuum (about 300 km/ms). The location is certainly wrong |
| `suspicious` | Faster than light in fibre over a straight line (about 200 km/ms, 5% tolerance). The location is very likely wrong, or the address is anycast |

Hops closer than 300 km are skipped because city-level location error is larger than the signal. Flagged
hops show a warning in the map's hop list, a "doubtful locations" chip, a note in the report and a
`warn:` line on the terminal.

**2. Hostname hints.** Operators name routers after their city (`ae1.cr2-fra2.ip.example.net`,
`be2.ear1.london1.level3.net`). TraceYourPacket looks up each public hop's reverse DNS name (unless
`--offline` or `--no-rdns`) and reads airport and city codes from it using a small bundled table of
about 100 hub cities. A hostname never overrides the database on its own; it only changes a location when
the physics agrees:

- the database has no location: the hostname location is used (marked "Located from hostname");
- both agree within 300 km: nothing changes;
- they disagree and the RTT rules out the database location but not the hostname's: the hostname wins,
  and the hop's note says so;
- they disagree and the RTT settles nothing: the database stays and the note shows what the hostname suggested.

Bare three-letter codes without a digit (`fra`, `pop`) are ignored because they collide with ordinary
router words; `fra2` and `frankfurt` are accepted. Two different cities in one name count as ambiguous
and are ignored.

## How it works

```
  traceroute / tracert output ─┐
  or --input FILE              ├─► parser ─► hops (TTL, responders, RTTs, flags)
                               ┘                 │
                                                 ▼
  geolocation (cache, --geo-file, API) ──► located hops ──► stations (hops < 5 km apart merge)
                                                 │
  cable data (TeleGeography / illustrative) ─► cable graph ─► shortest route per leg
                                                 │
                              ┌──────────────────┴──────────────────┐
                              ▼                                     ▼
                     interactive map (d3 + SVG)           HTML report (sequence diagram,
                     animated packets                     hop cards, leg table, anatomy)
```

How traceroute itself works, as the report explains per hop:

1. Your computer sends a probe with IP TTL = 1, then 2, then 3, and so on.
2. Each router subtracts 1 from the TTL. The router that makes it 0 drops the packet and sends back
   ICMP type 11, code 0 (time exceeded) quoting the start of the dropped packet.
3. Traceroute matches each reply to its probe and records who answered and the round-trip time.
4. The destination answers differently: ICMP port unreachable (UDP probes), echo reply (ICMP probes),
   or SYN-ACK / RST (TCP probes). That ends the trace.

Things that make real traces confusing, and that the report points out when it sees them:
NAT and carrier-grade NAT (`100.64.0.0/10`), several routers answering one TTL (load balancing,
ECMP), routers that rate-limit or ignore ICMP (`* * *`), and return paths that differ from the
forward path.

## How the cable path is inferred

Traceroute does not know about cables. TraceYourPacket estimates them like this:

1. Each hop with a known location becomes a **station**. Hops under 5 km apart merge into one.
   Hops with no location stay at the previous station.
2. Cable endpoints become **landing stations** in a graph. Cables are edges. Landings within 40 km
   of each other are joined.
3. Where no cable is near, **overland edges** (up to 700 km, with a 1.6x cost penalty) link nearby
   landings.
4. For each pair of consecutive stations, a **Dijkstra shortest path** over that graph gives the
   leg. If the stations are less than 1,200 km apart, the leg is drawn direct.
5. The leg's length, the part on cable, and the fibre minimum RTT are computed from the geometry.
   The minimum uses about 200 km per millisecond one way (light in glass).

Consequences you should keep in mind:

- The named cable is the **most plausible** one for that corridor, not a confirmed carrier.
- Router locations from IP databases are often an operator's head office, so some legs will be
  wrong or implausibly short. The location checks above catch many, not all, of these.
- If the observed RTT step on a leg is **below** the floor, the location data is wrong. If it is far
  **above**, expect queueing, a longer real route, or an inflated reply time at that router.

## Data sources and licences

| Data | Source | Licence | How it is used |
|---|---|---|---|
| Submarine cable routes | [TeleGeography Submarine Cable Map](https://www.submarinecablemap.com) | CC BY-NC-SA 3.0 (non-commercial, share-alike, attribution) | Downloaded at run time, cached, **never bundled in this repo**. Credit is shown on the map |
| Illustrative cable corridors | `tools/make_illustrative.py` | Part of this project (GPLv3) | Hand-placed, approximate, labelled "illustrative" everywhere they appear |
| World map | Natural Earth via `world-atlas` 2.0.2 | Public domain (Natural Earth), ISC (package) | Bundled and inlined |
| d3 7.9.0, topojson-client 3.1.0 | npm | ISC | Bundled and inlined |
| Router geolocation | [geolocation-db.com](https://geolocation-db.com) | Their terms | Queried over HTTPS for public hop IPs only, cached locally |

See `tracemap/assets/THIRD_PARTY.md`. Because the TeleGeography data is non-commercial, do not use
maps generated from it in commercial products without checking their terms.

## Privacy and security

- **Only public hop addresses** are sent to the geolocation API. Private (RFC 1918), carrier-grade
  NAT, loopback, link-local and documentation addresses are never sent.
- `--offline` with `--geo-file` sends **nothing** anywhere and downloads nothing.
- Results are cached at `~/.cache/tracemap/`. `--no-cache` disables the geolocation cache.
- **Reverse DNS:** hostname hints need a PTR lookup per public hop, sent to your normal DNS resolver
  (the same thing `traceroute` does when you leave off `-n`). `--no-rdns` or `--offline` turns it off.
- **No shell is ever used.** The target is validated (IPv4 or hostname, no leading `-`) and passed to
  `traceroute` as a list argument, so `8.8.8.8; anything` is rejected.
- Untrusted strings (hostnames, city names from the API) are HTML-escaped or inserted with
  `textContent`, and the map data is serialised so it cannot close a `<script>` tag or inject
  template placeholders. The map in the report runs in a sandboxed iframe.
- **Share reports with care:** a report contains the path to the target and, if you used
  `--origin`, your location. Your own public IP is not added, but the first public hop often reveals
  your ISP and city.

## Project layout

```
vis_route.py             entry point (calls tracemap.cli)
tracemap/
  cli.py                 argument parsing, orchestration, outputs
  runner.py              target validation, building and running traceroute (no shell)
  parser.py              Linux/macOS and Windows output parser
  geo.py                 IP classification, geolocation with cache, haversine
  cables.py              cable data loading (download, validate, cache), graph, Dijkstra routing
  sanity.py              physical RTT-versus-distance checks on hop locations
  hints.py               router hostname to city hints, reverse DNS
  mapviz.py              builds the map data, renders the offline map, leg table, per-hop notes
  report.py, report_css.py   the HTML report
  plot.py                optional static matplotlib/basemap map
  assets/                map.html/.css/.js, d3, topojson, world atlas, illustrative cables
samples/                 synthetic traceroute and geolocation (RFC 5737 addresses)
tools/make_illustrative.py   generates the illustrative corridors
tools/make_city_codes.py     generates assets/city_codes.json (airport and city codes)
tests/                   pytest suite
example_output/          generated from the samples only
```

## Development

```
pip install -r requirements-dev.txt
python -m pytest
```

The suite covers the parser (Linux, macOS, Windows layouts), target validation, geolocation and
caching, cable routing, map data, HTML escaping and placeholder injection, and the CLI end to end.
Browser behaviour was checked manually with headless Chromium screenshots.

Regenerate the example output (synthetic data only, never a real trace):

```
./vis_route.py --input samples/traceroute_sample.txt --geo-file samples/geo_sample.json \
    --offline --no-cache --origin 12.97,77.59 --cables illustrative -o example_output
```

## Limits

- IPv4 only.
- Router geolocation is rough, often only the country or the operator's head office.
- The cable path is a plausible inference, and illustrative corridors are not real cable routes.
- A hop's RTT includes the router's time to build the ICMP error, so it is not a clean latency
  figure for that router.
- Paths are one-way: the return path can differ and traceroute cannot see it.
- The live TeleGeography download and a real `traceroute` run were not exercised in the sandbox
  where this was built (no outbound access, no `traceroute` binary). Live mode was tested with a
  stand-in executable that prints the sample output. Please try both once on your machine.

## Roadmap

- **Phase 1, trustworthy: done.** Robust cable download with validation, atomic cache and clear
  fallback notes; physically impossible RTT detection; hostname location hints; `tracemap <host> --open`.
  Still to do on your machine: confirm the live TeleGeography download against the real service.
- **Phase 2, richer analysis:** ASN and operator per hop with the path coloured by network, multi-probe
  discovery of load-balanced branches, latency-per-leg chart.
- **Phase 3, history:** saved runs, route diffing, timeline replay, comparing destinations, scheduled
  traces with change alerts.
- **Phase 4, sharing:** privacy mode, GIF/video export, live streaming of hops, IPv6, web UI, Docker.

## What changed from the original script

Bugs and risks fixed:

- The target was pasted into a `shell=True` command, so `8.8.8.8; anything` ran. It now goes
  through validation and an argument list with no shell.
- `getopt.getopt(sys.argv, "h")` was given the script name too, so `-h` never worked. Replaced by
  `argparse`.
- The first located hop never got a dot, and an arc was skipped whenever
  `lat_diff + lon_diff == 0`, even for different places. Both fixed.
- `basemap`'s `drawgreatcircle` fails with current `pyproj`. Arcs are now computed directly and
  split at the date line.
- Private addresses (192.168.x.x and so on) were sent to the geolocation API. They are skipped.
- Geolocation calls had no timeout and a bare `except:` hid every error.
- Linux/macOS and Windows code paths were two copies of the same loop. There is one now, and the
  parser handles `*`, mixed loss, several routers per TTL, `!N` style flags and hostnames.
- Output goes to files instead of only `plt.show()`, so it works on a server with no display.
- The unused `gcmap` dependency is gone.

New: offline replay, JSON export, interactive submarine-cable map with animated packet flow,
linked HTML packet-path report, map cropping to the route, tests.

## Licence

GPLv3, see `LICENSE`. Third-party files keep their own licences (see above).
