import json
from pathlib import Path

from tracemap.cables import load_cables
from tracemap.cli import main
from tracemap.geo import GeoInfo, GeoResolver
from tracemap.mapviz import build_map_data, render_map
from tracemap.parser import parse_traceroute

S = Path(__file__).resolve().parent.parent / "samples"


def _data(extra_geo=None):
    tr = parse_traceroute((S / "traceroute_sample.txt").read_text())
    r = GeoResolver(geo_file=S / "geo_sample.json", use_network=False, cache_path=None)
    geo = {h.ip: r.lookup(h.ip) for h in tr.hops if h.ip}
    if extra_geo:
        geo.update(extra_geo)
    return tr, geo


def test_map_data_and_route_on_cables():
    tr, geo = _data()
    cs = load_cables("illustrative", offline=True)
    d = build_map_data(tr, geo, "udp", cs, (12.97, 77.59))
    assert d and d["stats"]["totalKm"] > 1000
    assert d["stats"]["cableKm"] > 0
    assert len(d["legs"]) == len(d["stations"]) - 1
    assert not d["cables"]["real"]


def test_none_when_nothing_located():
    tr, _ = _data()
    assert build_map_data(tr, {}, "udp", load_cables("illustrative", offline=True)) is None


def test_render_escapes_and_no_placeholder_injection():
    tr, geo = _data()
    ip = next(h.ip for h in tr.hops if h.ip and geo.get(h.ip))
    geo[ip] = GeoInfo(geo[ip].lat, geo[ip].lon, "</script><b>__JS__", "", "", "")
    d = build_map_data(tr, geo, "udp", load_cables("illustrative", offline=True), (12.97, 77.59))
    html = render_map(d)
    assert "</script><b>" not in html
    assert html.count("<script") == 5


def test_cli_writes_map(tmp_path):
    rc = main(["--input", str(S / "traceroute_sample.txt"), "--geo-file", str(S / "geo_sample.json"),
               "--offline", "--no-cache", "--origin", "12.97,77.59", "--cables", "illustrative",
               "-o", str(tmp_path)])
    assert rc == 0
    assert list(tmp_path.glob("*_map.html"))
