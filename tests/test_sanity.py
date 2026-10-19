from tracemap.geo import GeoInfo
from tracemap.parser import parse_traceroute
from tracemap.sanity import check_hops

BLR = (12.97, 77.59)
TOKYO = GeoInfo(35.68, 139.69, "Tokyo", None, "Japan")
FRA = GeoInfo(50.11, 8.68, "Frankfurt", None, "Germany")
MUM = GeoInfo(19.07, 72.88, "Mumbai", None, "India")


def _trace(*rows):
    lines = ["traceroute to 203.0.113.10 (203.0.113.10), 30 hops max, 60 byte packets"]
    for i, (ip, rtt) in enumerate(rows, 1):
        lines.append(f" {i}  {ip}  {rtt} ms  {rtt} ms  {rtt} ms" if ip else f" {i}  * * *")
    return parse_traceroute("\n".join(lines))


def test_faster_than_light_is_impossible():
    t = _trace(("198.51.100.1", 5.0))
    f = check_hops(t, {"198.51.100.1": TOKYO}, BLR)
    assert f[0].level == "impossible" and f[0].km > 5000


def test_below_fibre_but_above_vacuum_is_suspicious():
    # Bengaluru to Frankfurt is about 7,500 km: vacuum floor 50 ms, fibre floor 75 ms
    t = _trace(("198.51.100.1", 60.0))
    f = check_hops(t, {"198.51.100.1": FRA}, BLR)
    assert f[0].level == "suspicious"


def test_plausible_rtt_is_not_flagged():
    t = _trace(("198.51.100.1", 125.0))
    assert check_hops(t, {"198.51.100.1": FRA}, BLR) == {}


def test_short_distances_are_ignored():
    # Mumbai is about 840 km from Bengaluru, so 0.2 ms is flagged.
    assert 0 in check_hops(_trace(("198.51.100.1", 0.2)), {"198.51.100.1": MUM}, BLR)
    # Under 300 km, city-level geolocation error is larger than the signal, so nothing is flagged.
    near = GeoInfo(13.08, 77.9)  # about 35 km away
    assert check_hops(_trace(("198.51.100.1", 0.2)), {"198.51.100.1": near}, BLR) == {}


def test_no_origin_uses_first_hop_and_stays_conservative():
    t = _trace(("198.51.100.1", 2.0), ("198.51.100.2", 130.0))
    geo = {"198.51.100.1": MUM, "198.51.100.2": FRA}
    assert check_hops(t, geo, None) == {}              # plausible: no false alarm
    t2 = _trace(("198.51.100.1", 2.0), ("198.51.100.2", 5.0))
    assert 1 in check_hops(t2, geo, None)              # 6,600 km in 5 ms is impossible


def test_unlocated_and_lost_hops_skipped():
    t = _trace((None, 0), ("198.51.100.1", 5.0))
    assert check_hops(t, {}, BLR) == {}


def test_min_rtt_is_used_not_average():
    t = parse_traceroute("traceroute to 1.1.1.1 (1.1.1.1), 30 hops max\n"
                         " 1  198.51.100.1  200.0 ms  4.0 ms  210.0 ms\n")
    assert 0 in check_hops(t, {"198.51.100.1": TOKYO}, BLR)


def test_sample_trace_has_no_warnings():
    from pathlib import Path
    from tracemap.geo import GeoResolver
    S = Path(__file__).resolve().parent.parent / "samples"
    t = parse_traceroute((S / "traceroute_sample.txt").read_text())
    r = GeoResolver(geo_file=S / "geo_sample.json", use_network=False, cache_path=None)
    geo = {h.ip: r.lookup(h.ip) for h in t.hops if h.ip}
    assert check_hops(t, geo, BLR) == {}
