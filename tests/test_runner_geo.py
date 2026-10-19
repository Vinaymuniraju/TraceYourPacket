import json

import pytest

from tracemap import geo
from tracemap.geo import GeoResolver, classify_ip, haversine_km, is_public
from tracemap.runner import TargetError, build_command, validate_target


# ---- target validation (the old script put this text into a shell) ----------
@pytest.mark.parametrize(
    "bad",
    ["", "-h", "--version", "8.8.8.8; rm -rf /", "$(id)", "a b", "x`y`", "::1", "host_name!"],
)
def test_bad_targets_are_rejected(bad):
    with pytest.raises(TargetError):
        validate_target(bad)


def test_ipv4_literal_is_accepted_without_dns():
    assert validate_target("8.8.8.8") == ("8.8.8.8", "8.8.8.8")


def test_hostname_is_resolved(monkeypatch):
    monkeypatch.setattr(
        "tracemap.runner.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    assert validate_target("example.org") == ("example.org", "93.184.216.34")


def test_command_is_an_argument_list():
    cmd = build_command("8.8.8.8", "udp", 20, system="Linux")
    assert cmd == ["traceroute", "-n", "-m", "20", "8.8.8.8"]
    assert build_command("8.8.8.8", "icmp", 20, system="Linux")[-2:] == ["-I", "8.8.8.8"]
    assert build_command("8.8.8.8", "tcp", 9, system="Darwin")[-3:] == ["-P", "TCP", "8.8.8.8"]
    assert build_command("8.8.8.8", "udp", 9, system="Windows")[0] == "tracert"


def test_max_hops_bounds():
    with pytest.raises(ValueError):
        build_command("8.8.8.8", "udp", 0, system="Linux")
    with pytest.raises(ValueError):
        build_command("8.8.8.8", "udp", 500, system="Linux")


# ---- address classes ---------------------------------------------------------
@pytest.mark.parametrize(
    "ip,label",
    [
        ("192.168.1.1", "private (RFC 1918)"),
        ("10.0.0.1", "private (RFC 1918)"),
        ("172.16.5.5", "private (RFC 1918)"),
        ("100.64.0.1", "carrier-grade NAT (RFC 6598)"),
        ("127.0.0.1", "loopback"),
        ("169.254.1.1", "link-local"),
        ("203.0.113.9", "documentation range"),
        ("8.8.8.8", "public"),
    ],
)
def test_classify(ip, label):
    assert classify_ip(ip) == label


def test_only_public_is_public():
    assert is_public("8.8.8.8")
    assert not is_public("192.168.1.1") and not is_public("100.64.0.1")


# ---- resolver ------------------------------------------------------------------
def test_private_ips_never_touch_the_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(geo.urllib.request, "urlopen", boom)
    r = GeoResolver(use_network=True)
    assert r.lookup("192.168.1.1") is None
    assert r.lookup("100.64.0.1") is None


def test_offline_makes_no_request(monkeypatch):
    monkeypatch.setattr(geo.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    assert GeoResolver(use_network=False).lookup("8.8.8.8") is None


def test_geo_file_wins_and_may_cover_reserved_ranges(tmp_path):
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"203.0.113.5": {"latitude": 1.5, "longitude": 2.5, "city": "X"}}))
    info = GeoResolver(geo_file=f, use_network=False).lookup("203.0.113.5")
    assert (info.lat, info.lon, info.city) == (1.5, 2.5, "X")


def test_api_failure_is_handled(monkeypatch):
    def fail(*a, **k):
        raise geo.urllib.error.URLError("down")

    monkeypatch.setattr(geo.urllib.request, "urlopen", fail)
    assert GeoResolver().lookup("8.8.8.8") is None


def test_bad_api_payloads_give_none():
    assert geo._from_dict({"latitude": "Not found", "longitude": "Not found"}) is None
    assert geo._from_dict({"latitude": 0, "longitude": 0}) is None
    assert geo._from_dict({"latitude": 95, "longitude": 0}) is None
    assert geo._from_dict({}) is None


def test_cache_roundtrip(tmp_path, monkeypatch):
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def info(self):
            class I:
                def get_content_charset(self, d): return "utf-8"
            return I()
        def read(self):
            return json.dumps({"latitude": 37.4, "longitude": -122.1,
                               "city": "Mountain View", "country_name": "United States"}).encode()

    calls = []
    monkeypatch.setattr(geo.urllib.request, "urlopen", lambda *a, **k: calls.append(a) or Resp())
    cache = tmp_path / "geo.json"
    r = GeoResolver(cache_path=cache)
    assert r.lookup("8.8.8.8").city == "Mountain View"
    r.save()
    again = GeoResolver(cache_path=cache, use_network=False)
    assert again.lookup("8.8.8.8").city == "Mountain View"
    assert len(calls) == 1


def test_haversine():
    a = geo.GeoInfo(51.5074, -0.1278)   # London
    b = geo.GeoInfo(40.7128, -74.0060)  # New York
    assert 5500 < haversine_km(a, b) < 5650
    assert haversine_km(a, a) == 0
