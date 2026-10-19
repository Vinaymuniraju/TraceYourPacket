import io
import json
import os
import time
import urllib.error

import pytest

from tracemap import cables as C
from tracemap.cables import CableDataError, load_cables


def _geo(n=30):
    """A FeatureCollection shaped like TeleGeography's cable-geo.json."""
    feats = []
    for i in range(n):
        lon = -170 + i * 10
        feats.append({
            "type": "Feature",
            "properties": {"id": f"cable-{i}", "name": f"Test Cable {i}", "color": "#aabbcc",
                           "feature_id": f"cable-{i}-0"},
            "geometry": {"type": "MultiLineString",
                         "coordinates": [[[lon, 10.0], [lon + 5, 12.0], [lon + 9, 10.0]],
                                         [[lon + 9, 10.0], [lon + 12, 20.0]]]},
        })
    return {"type": "FeatureCollection", "features": feats}


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Opener:
    def __init__(self, body=None, exc=None):
        self.body, self.exc, self.calls = body, exc, 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        if self.exc:
            raise self.exc
        return FakeResp(self.body)


def _body(n=30):
    return json.dumps(_geo(n)).encode()


def test_download_then_cache_hit(tmp_path):
    op = Opener(_body())
    cs = load_cables("telegeography", cache_dir=tmp_path, opener=op)
    assert cs.real and cs.source == "telegeography" and not cs.note
    assert len(cs.cables) == 30 and op.calls == 1
    assert (tmp_path / "cable-geo.json").exists()
    assert not list(tmp_path.glob("*.tmp"))          # atomic write left nothing behind
    load_cables("telegeography", cache_dir=tmp_path, opener=op)
    assert op.calls == 1                              # fresh cache, no second download


def test_refresh_forces_download(tmp_path):
    op = Opener(_body())
    load_cables("auto", cache_dir=tmp_path, opener=op)
    load_cables("auto", cache_dir=tmp_path, opener=op, refresh=True)
    assert op.calls == 2


def test_failure_uses_stale_cache_and_says_so(tmp_path):
    load_cables("auto", cache_dir=tmp_path, opener=Opener(_body()))
    f = tmp_path / "cable-geo.json"
    old = time.time() - 40 * 86400
    os.utime(f, (old, old))
    cs = load_cables("auto", cache_dir=tmp_path, opener=Opener(exc=urllib.error.URLError("no route")))
    assert cs.real and "download failed" in cs.note and "40 days ago" in cs.note


def test_auto_falls_back_to_illustrative_with_reason(tmp_path):
    cs = load_cables("auto", cache_dir=tmp_path, opener=Opener(exc=TimeoutError("slow")))
    assert not cs.real and cs.source == "illustrative"
    assert "unavailable" in cs.note and "TimeoutError" in cs.note


def test_telegeography_mode_fails_loudly(tmp_path):
    with pytest.raises(CableDataError):
        load_cables("telegeography", cache_dir=tmp_path, opener=Opener(exc=OSError("blocked")))


@pytest.mark.parametrize("body", [b"not json", b'{"type":"FeatureCollection","features":[]}',
                                  json.dumps(_geo(3)).encode(), b"[]"])
def test_bad_downloads_are_rejected_and_not_cached(tmp_path, body):
    cs = load_cables("auto", cache_dir=tmp_path, opener=Opener(body))
    assert not cs.real
    assert not (tmp_path / "cable-geo.json").exists()


def test_oversized_download_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "MAX_DOWNLOAD_BYTES", 1000)
    cs = load_cables("auto", cache_dir=tmp_path, opener=Opener(_body()))
    assert not cs.real and "larger than" in cs.note


def test_corrupt_cache_is_ignored(tmp_path):
    (tmp_path / "cable-geo.json").write_text("{broken")
    cs = load_cables("auto", cache_dir=tmp_path, offline=True)
    assert not cs.real and "offline" in cs.note


def test_offline_uses_cache_never_network(tmp_path):
    load_cables("auto", cache_dir=tmp_path, opener=Opener(_body()))
    op = Opener(exc=AssertionError("network used while offline"))
    cs = load_cables("auto", cache_dir=tmp_path, offline=True, opener=op)
    assert cs.real and op.calls == 0


def test_cables_file_errors_are_clean(tmp_path):
    bad = tmp_path / "x.geojson"
    bad.write_text("nope")
    with pytest.raises(CableDataError):
        load_cables("auto", path=bad)
    empty = tmp_path / "e.geojson"
    empty.write_text('{"type":"FeatureCollection","features":[]}')
    with pytest.raises(CableDataError):
        load_cables("auto", path=empty)
    with pytest.raises(CableDataError):
        load_cables("auto", path=tmp_path / "missing.geojson")


def test_cables_file_ok(tmp_path):
    f = tmp_path / "mine.geojson"
    f.write_text(json.dumps(_geo(2)))
    cs = load_cables("auto", path=f)
    assert cs.real and cs.source == "file" and len(cs.cables) == 2


def test_real_shaped_data_routes_across_an_ocean():
    graph = C.CableGraph(C.parse_geojson(_geo()))
    leg = graph.route((-160.0, 10.0), (-40.0, 20.0))
    assert leg.cable_km > 0 and leg.cables


def test_cli_telegeography_failure_exits_1(tmp_path, monkeypatch, capsys):
    from pathlib import Path
    from tracemap.cli import main
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    S = Path(__file__).resolve().parent.parent / "samples"
    rc = main(["--input", str(S / "traceroute_sample.txt"), "--geo-file", str(S / "geo_sample.json"),
               "--offline", "--no-cache", "--cables", "telegeography", "-o", str(tmp_path / "o")])
    assert rc == 1 and "unavailable" in capsys.readouterr().err
