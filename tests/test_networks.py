from pathlib import Path

from tracemap.asn import AsnResolver
from tracemap.cables import load_cables
from tracemap.cli import main
from tracemap.geo import GeoResolver
from tracemap.mapviz import build_map_data, find_handoffs, network_section_html, render_map
from tracemap.parser import parse_traceroute

S = Path(__file__).resolve().parent.parent / "samples"


def _data(asn_file=S / "asn_sample.json"):
    tr = parse_traceroute((S / "traceroute_sample.txt").read_text())
    g = GeoResolver(geo_file=S / "geo_sample.json", use_network=False, cache_path=None)
    geo = {h.ip: g.lookup(h.ip) for h in tr.hops if h.ip}
    ips = [r.ip for h in tr.hops for r in h.responders]
    asn = {k: v for k, v in AsnResolver(asn_file=asn_file, use_network=False).lookup_many(ips).items() if v}
    return build_map_data(tr, geo, "udp", load_cables("illustrative", offline=True), (12.97, 77.59), asn=asn)


def test_networks_in_route_order_with_distinct_colours():
    d = _data()
    keys = [n["key"] for n in d["nets"]]
    assert keys == ["local", "AS64496", "AS64497", "AS64498", "AS64499", "AS64500"]
    assert len({n["color"] for n in d["nets"]}) == len(keys)
    assert d["nets"][0]["color"] == "#8b9ab3"        # local is grey
    assert all(leg["net"] for leg in d["legs"])


def test_handoffs_and_leaving_the_isp():
    d = _data()
    h = d["handoffs"]
    assert [x["toKey"] for x in h] == ["AS64497", "AS64498", "AS64499", "AS64500"]
    assert h[0]["leavesIsp"] and not any(x["leavesIsp"] for x in h[1:])
    assert h[0]["ttl"] == 6 and "Transit West" in h[0]["to"]


def test_hops_carry_network_and_handoff():
    d = _data()
    assert d["hops"][0]["net"] == "local"
    assert d["hops"][4]["net"] is None                     # the lost hop
    assert d["hops"][5]["handoff"]["leavesIsp"]


def test_without_asn_data_everything_is_unknown_and_safe():
    tr = parse_traceroute((S / "traceroute_sample.txt").read_text())
    g = GeoResolver(geo_file=S / "geo_sample.json", use_network=False, cache_path=None)
    geo = {h.ip: g.lookup(h.ip) for h in tr.hops if h.ip}
    d = build_map_data(tr, geo, "udp", load_cables("illustrative", offline=True), (12.97, 77.59))
    assert [n["key"] for n in d["nets"]] == ["unknown"] and d["handoffs"] == []
    assert "No change of network" in network_section_html(d)


def test_handoffs_skip_local_and_unknown():
    hops = [{"ttl": 1, "ip": "a", "net": "local", "asnLabel": "x"},
            {"ttl": 2, "ip": "b", "net": "AS1", "asnLabel": "AS1 One"},
            {"ttl": 3, "ip": "c", "net": "unknown", "asnLabel": None},
            {"ttl": 4, "ip": "d", "net": "AS2", "asnLabel": "AS2 Two"}]
    out = find_handoffs(hops)
    assert len(out) == 1 and out[0]["ttl"] == 4 and out[0]["leavesIsp"]


def test_hostile_operator_name_is_escaped_in_report_and_map():
    d = _data()
    d["nets"][1]["label"] = "<img src=x onerror=alert(1)>"
    sec = network_section_html(d)
    assert "<img" not in sec and "&lt;img" in sec
    html = render_map(d)
    assert "<img src=x" not in html


def test_cli_report_has_network_column(tmp_path):
    rc = main(["--input", str(S / "traceroute_sample.txt"), "--geo-file", str(S / "geo_sample.json"),
               "--asn-file", str(S / "asn_sample.json"), "--offline", "--no-cache", "--cables", "illustrative",
               "-o", str(tmp_path)])
    assert rc == 0
    html = (tmp_path / "route_203.0.113.10.html").read_text()
    assert "Networks on the path" in html and "AS64497" in html and "you leave your ISP" in html


def test_no_asn_flag_makes_no_lookups(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("ASN lookup attempted")
    monkeypatch.setattr("tracemap.asn.AsnResolver.lookup", boom)
    rc = main(["--input", str(S / "traceroute_sample.txt"), "--geo-file", str(S / "geo_sample.json"),
               "--offline", "--no-cache", "--no-asn", "--cables", "illustrative", "-o", str(tmp_path)])
    assert rc == 0
