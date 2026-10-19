from tracemap.geo import GeoInfo
from tracemap.hints import apply_hints, hint_from_hostname, reverse_dns
from tracemap.parser import parse_traceroute

BLR = (12.97, 77.59)


def test_hostname_patterns():
    h = hint_from_hostname
    assert h("xe-0-0-1.cr1.lax1.us.zayo.com").city == "Los Angeles"
    assert h("ae1.cr2-fra2.ip4.gtt.net").city == "Frankfurt"
    assert h("ae-2.r20.londen12.uk.bb.gin.ntt.net").city == "London"
    assert h("be2.ear1.Washington1.Level3.net").city == "Ashburn"
    assert h("ge-0-1.Frankfurt.example.net").city == "Frankfurt"


def test_no_false_positives():
    h = hint_from_hostname
    for name in ["core1.ear1.example.com", "gw.pop.example.com", "ae-5.fra.example.net",   # bare code, no digit
                 "ae1.mil1.sea1.example.net",          # two different cities: ambiguous
                 "example.lax1.net",                   # the code sits in the registered domain, not the host part
                 "static-1-2-3-4.cust.example.net", "", None, "a" * 300 + ".net"]:
        assert h(name) is None, name


def _trace(rtt):
    return parse_traceroute("traceroute to 203.0.113.10 (203.0.113.10), 30 hops max\n"
                            f" 1  198.51.100.1  {rtt} ms  {rtt} ms  {rtt} ms\n")


def test_hint_used_when_database_has_no_entry():
    t, geo = _trace(125.0), {}
    msgs = apply_hints(t, geo, BLR, {"198.51.100.1": "ae1.cr2-fra2.ip4.gtt.net"})
    g = geo["198.51.100.1"]
    assert g.city == "Frankfurt" and g.source == "hostname" and msgs


def test_hint_corrects_a_location_the_rtt_rules_out():
    t = _trace(125.0)   # Frankfurt-like latency
    geo = {"198.51.100.1": GeoInfo(35.68, 139.69, "Tokyo", None, "Japan")}  # head office, wrong
    # Tokyo is ~5,900 km from Bengaluru: 125 ms is plausible for Tokyo too, so make it clearly wrong:
    t = _trace(30.0)
    geo = {"198.51.100.1": GeoInfo(51.0, 0.0, "London", None, "United Kingdom")}  # 8,000 km in 30 ms
    apply_hints(t, geo, BLR, {"198.51.100.1": "ae1.cr1-bom2.ip.example.net"})
    g = geo["198.51.100.1"]
    assert g.city == "Mumbai" and g.source == "hostname" and "RTT rules out" in g.note


def test_hint_does_not_override_when_rtt_cannot_decide():
    t = _trace(300.0)
    db = GeoInfo(51.5, -0.13, "London", None, "United Kingdom")
    geo = {"198.51.100.1": db}
    apply_hints(t, geo, BLR, {"198.51.100.1": "ae1.cr1-sin2.ip.example.net"})
    assert geo["198.51.100.1"] is db and db.source == "ip-database" and "Kept London" in db.note


def test_agreeing_hint_changes_nothing():
    t = _trace(125.0)
    db = GeoInfo(50.0, 8.5, "Frankfurt am Main", None, "Germany")
    geo = {"198.51.100.1": db}
    assert apply_hints(t, geo, BLR, {"198.51.100.1": "ae1.cr2-fra2.ip4.gtt.net"}) == []
    assert db.note is None


def test_reverse_dns_skips_private_addresses(monkeypatch):
    seen = []
    monkeypatch.setattr("socket.gethostbyaddr", lambda ip: (seen.append(ip) or ("h.example", [], [ip])))
    out = reverse_dns(["192.168.1.1", "10.0.0.1", "8.8.8.8"])
    assert seen == ["8.8.8.8"] and out == {"8.8.8.8": "h.example"}
