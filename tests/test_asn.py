import io
import json
import urllib.error
from pathlib import Path

from tracemap.asn import AsnResolver, colour_for, parse_ripestat

S = Path(__file__).resolve().parent.parent / "samples"


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _ripe(asn=15169, holder="GOOGLE - Google LLC", prefix="8.8.8.0/24"):
    return json.dumps({"data": {"resource": prefix, "asns": [{"asn": asn, "holder": holder}]}}).encode()


class Opener:
    def __init__(self, body=None, exc=None):
        self.body, self.exc, self.urls = body, exc, []

    def __call__(self, req, timeout=None):
        self.urls.append(req.full_url)
        if self.exc:
            raise self.exc
        return FakeResp(self.body)


def test_parse_ripestat_ok_and_bad():
    i = parse_ripestat(json.loads(_ripe()))
    assert i.asn == 15169 and "Google" in i.name and i.prefix == "8.8.8.0/24" and i.label.startswith("AS15169")
    for bad in [{}, {"data": {}}, {"data": {"asns": []}}, {"data": {"asns": [{"asn": "x"}]}},
                {"data": {"asns": [{"asn": 0}]}}, {"data": {"asns": [{"asn": 2**40}]}}, None, []]:
        assert parse_ripestat(bad) is None


def test_private_and_cgnat_are_local_without_network():
    op = Opener(exc=AssertionError("network used"))
    r = AsnResolver(opener=op)
    assert r.lookup("192.168.1.1").key == "local"
    assert r.lookup("100.64.0.1").name.lower().startswith("carrier")
    assert op.urls == []


def test_file_wins_longest_prefix_and_reserved_ranges():
    r = AsnResolver(asn_file=S / "asn_sample.json", use_network=False)
    assert r.lookup("198.51.100.5").asn == 64496
    assert r.lookup("198.51.100.9").asn == 64497
    assert r.lookup("203.0.113.10").asn == 64500


def test_network_lookup_is_cached_and_url_is_safe(tmp_path):
    op = Opener(_ripe())
    cache = tmp_path / "asn.json"
    r = AsnResolver(cache_path=cache, opener=op)
    assert r.lookup("8.8.8.8").asn == 15169
    r.save()
    assert op.urls == ["https://stat.ripe.net/data/prefix-overview/data.json?resource=8.8.8.8"]
    r2 = AsnResolver(cache_path=cache, opener=Opener(exc=AssertionError("cache missed")))
    assert r2.lookup("8.8.8.8").asn == 15169


def test_failures_are_not_cached_and_offline_never_calls(tmp_path):
    cache = tmp_path / "asn.json"
    r = AsnResolver(cache_path=cache, opener=Opener(exc=urllib.error.URLError("down")))
    assert r.lookup("8.8.8.8") is None
    r.save()
    assert not cache.exists()
    off = AsnResolver(use_network=False, opener=Opener(exc=AssertionError("network used")))
    assert off.lookup("8.8.8.8") is None


def test_garbage_response_is_none():
    assert AsnResolver(opener=Opener(b"<html>")).lookup("8.8.8.8") is None


def test_lookup_many_dedupes():
    op = Opener(_ripe())
    out = AsnResolver(opener=op).lookup_many(["8.8.8.8", "8.8.8.8", "192.168.0.1"])
    assert len(op.urls) == 1 and set(out) == {"8.8.8.8", "192.168.0.1"}


def test_colours_follow_route_order():
    order = ["local", "AS1", "AS2"]
    assert colour_for("local", order) == "#8b9ab3"
    assert colour_for("AS1", order) != colour_for("AS2", order)
