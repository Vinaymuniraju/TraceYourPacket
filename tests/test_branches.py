import pytest
from pathlib import Path

from tracemap.asn import AsnResolver
from tracemap.cables import load_cables
from tracemap.cli import main
from tracemap.geo import GeoResolver
from tracemap.mapviz import build_map_data, render_map
from tracemap.parser import merge_traces, parse_traceroute
from tracemap.runner import build_command

S = Path(__file__).resolve().parent.parent / "samples"


def _t(*lines):
    return parse_traceroute("traceroute to 203.0.113.10 (203.0.113.10), 30 hops max, 60 byte packets\n"
                            + "\n".join(lines))


def test_merge_pools_probes_and_orders_by_frequency():
    a = _t(" 1  192.168.1.1  1.0 ms  1.1 ms  1.2 ms", " 2  10.0.0.1  5 ms  192.0.2.7  6 ms  10.0.0.1  5 ms")
    b = _t(" 1  192.168.1.1  1.3 ms  1.1 ms  1.0 ms", " 2  192.0.2.7  6 ms  192.0.2.7  7 ms  192.0.2.7  6 ms",
           " 3  203.0.113.10  9 ms  9 ms  9 ms")
    m = merge_traces([a, b])
    assert [h.ttl for h in m.hops] == [1, 2, 3]
    assert len(m.hops[0].responders) == 1 and len(m.hops[0].responders[0].rtts) == 6
    h2 = m.hops[1]
    assert h2.responders[0].ip == "192.0.2.7" and len(h2.responders[0].rtts) == 4   # most probes first
    assert h2.responders[1].ip == "10.0.0.1" and len(h2.responders[1].rtts) == 2
    assert m.reached and m.target_ip == "203.0.113.10"


def test_merge_sums_losses_and_rejects_empty():
    a = _t(" 1  * * *")
    b = _t(" 1  * * 192.0.2.1  3 ms")
    m = merge_traces([a, b])
    assert m.hops[0].lost == 5 and m.hops[0].responders[0].ip == "192.0.2.1"
    with pytest.raises(ValueError):
        merge_traces([])


def test_probes_option_in_command_and_validation():
    assert "-q" not in build_command("8.8.8.8", system="Linux")
    assert build_command("8.8.8.8", system="Linux", probes=6)[:5] == ["traceroute", "-n", "-m", "25", "-q"]
    assert "-q" not in build_command("8.8.8.8", system="Windows", probes=6)
    for bad in (0, 11):
        with pytest.raises(ValueError):
            build_command("8.8.8.8", system="Linux", probes=bad)


def _data():
    tr = parse_traceroute((S / "traceroute_sample.txt").read_text())
    g = GeoResolver(geo_file=S / "geo_sample.json", use_network=False, cache_path=None)
    geo = {r.ip: g.lookup(r.ip) for h in tr.hops for r in h.responders}
    asn = {k: v for k, v in AsnResolver(asn_file=S / "asn_sample.json", use_network=False).lookup_many(
        [r.ip for h in tr.hops for r in h.responders]).items() if v}
    return build_map_data(tr, geo, "udp", load_cables("illustrative", offline=True), (12.97, 77.59), asn=asn)


def test_map_data_has_branch_for_balanced_hop():
    d = _data()
    assert d["branches"] == 1
    h = d["hops"][9]
    assert h["probesTotal"] == 3 and h["probesMain"] == 2
    alt = h["alts"][0]
    assert alt["ip"] == "192.0.2.13" and alt["far"] and alt["probes"] == 1 and "Boston" in alt["label"]
    assert d["hops"][0]["alts"] == []


def test_same_place_alternative_is_not_drawn_far():
    tr = _t(" 1  192.0.2.1  1 ms  192.0.2.2  1 ms  192.0.2.1  1 ms")
    g = GeoResolver(geo_file=S / "geo_sample.json", use_network=False, cache_path=None)
    geo = {"192.0.2.1": g.lookup("192.0.2.1"), "192.0.2.2": g.lookup("192.0.2.1")}
    d = build_map_data(tr, geo, "udp", load_cables("illustrative", offline=True), (50.0, 8.0))
    assert d["hops"][0]["alts"][0]["far"] is False and d["hops"][0]["alts"][0]["lat"] is None


def test_report_explains_load_balancing_with_shares(tmp_path):
    rc = main(["--input", str(S / "traceroute_sample.txt"), "--geo-file", str(S / "geo_sample.json"),
               "--asn-file", str(S / "asn_sample.json"), "--offline", "--no-cache", "--cables", "illustrative",
               "--origin", "12.97,77.59", "-o", str(tmp_path)])
    assert rc == 0
    html = (tmp_path / "route_203.0.113.10.html").read_text()
    assert "Load balancing:" in html and "2 of 3 probes" in html and "1 of 3 probes" in html


def test_cli_merges_two_input_files(tmp_path):
    f1, f2 = tmp_path / "a.txt", tmp_path / "b.txt"
    f1.write_text("traceroute to 203.0.113.10 (203.0.113.10), 30 hops max\n 1  192.168.1.1  1 ms  1 ms  1 ms\n"
                  " 2  203.0.113.10  9 ms  9 ms  9 ms\n")
    f2.write_text("traceroute to 203.0.113.10 (203.0.113.10), 30 hops max\n 1  192.168.1.254  1 ms  1 ms  1 ms\n"
                  " 2  203.0.113.10  9 ms  9 ms  9 ms\n")
    rc = main(["--input", str(f1), "--input", str(f2), "--offline", "--no-cache", "--no-asn",
               "--cables", "illustrative", "--origin", "12.97,77.59", "-o", str(tmp_path / "o")])
    assert rc == 0
    html = (tmp_path / "o" / "route_203.0.113.10.html").read_text()
    assert "192.168.1.254" in html and "192.168.1.1" in html


def test_map_html_contains_branch_data_escaped():
    d = _data()
    d["hops"][9]["alts"][0]["label"] = "</script><b>x"
    assert "</script><b>x" not in render_map(d)
