# tracemap (vis_route v2)

Runs a traceroute, puts every hop on a world map, and writes an HTML report that shows how
each probe packet travelled from your machine to the destination.

This is a rework of [Vinaymuniraju/vis_route](https://github.com/Vinaymuniraju/vis_route)
(itself a fork). Same idea, same `./vis_route.py <ip>` entry point, GPLv3.

## What you get

For `./vis_route.py 203.0.113.10` the `output/` folder holds:

| File | Contents |
|---|---|
| `route_<target>.png` | Map with a marker per place, hop numbers, and great-circle arcs |
| `route_<target>.html` | Self-contained report (no external files, works offline) |
| `route_<target>.json` | Hops, RTTs, address classes and locations as data |

The HTML report has:

- **Sequence diagram:** one row per TTL. The probe goes out, the TTL left after each router is
  shown on the way, the TTL hits 0, and the ICMP error comes back with its RTT. Lost probes are
  dashed.
- **Hop table and per-hop cards:** step by step what happened at that router, RTT min/avg/max,
  and notes (CGNAT, load balancing, large latency jumps with the distance that explains them).
- **Layer-by-layer panels:** what your computer, your home router (NAT), transit routers and
  the destination each do with the packet, plus what `vis_route.py` does before and after.
- **Packet anatomy:** the IPv4 and UDP/ICMP/TCP headers of a probe and of the ICMP "time
  exceeded" reply, with the fields that make traceroute work highlighted.
- **Distance check:** geographic path length against the fibre-speed lower bound on RTT.

## Install

```
sudo apt install traceroute      # Linux; macOS and Windows already ship one
pip install -r requirements.txt
```

## Use

```
./vis_route.py 8.8.8.8
./vis_route.py example.org --method icmp          # udp (default), icmp or tcp
./vis_route.py 8.8.8.8 --origin 12.97,77.59       # draw where you are as the start
./vis_route.py 8.8.8.8 --show                     # also open an interactive window
```

`--method icmp` and `tcp` on Linux use `traceroute -I` and `-T` (these usually need root).
On Windows `tracert` always sends ICMP.

### Replay a saved trace (no traceroute, no network)

```
./vis_route.py --input samples/traceroute_sample.txt \
               --geo-file samples/geo_sample.json --offline
```

The sample uses reserved documentation addresses (RFC 5737), so it does not describe a real
network. Pass `--method` if the saved trace was not a UDP one.

### Options

```
--max-hops N     maximum TTL, 1 to 64 (default 25)
--timeout S      kill traceroute after S seconds (default 300)
--geo-file JSON  IP to location entries, used before anything else
--offline        never call the geolocation API
--no-cache       do not read or write ~/.cache/tracemap/geo.json
--no-report      skip the HTML report
-o DIR           output folder (default ./output)
-v               log lookup problems
```

## Privacy

Public hop addresses are sent to `geolocation-db.com` over HTTPS to find coordinates. Private,
carrier-grade NAT, loopback, link-local and documentation addresses are never sent. Results are
cached locally. Use `--offline` with `--geo-file` to send nothing.

## What changed from the original script

Bugs and risks fixed:

- The target was pasted into a `shell=True` command, so `8.8.8.8; anything` ran. It now goes
  through validation (IPv4 or hostname, no leading `-`) and an argument list with no shell.
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

New: offline replay, JSON export, HTML packet-path report, map cropping to the route, tests.

## Develop

```
pip install -r requirements-dev.txt
python -m pytest
```

## Limits

- IPv4 only.
- Geolocation of routers is rough, often only to the country or the operator's head office.
- A hop's RTT includes the router's time to make the ICMP error, so it is not a clean latency
  figure for that router.
- The real traceroute was not run in the environment this was built in (no `traceroute`
  binary, no outbound access). Live mode was tested with a stand-in executable that prints the
  sample output; the argument list, parsing and validation paths are real. Please try it once on
  your machine against a real host.
