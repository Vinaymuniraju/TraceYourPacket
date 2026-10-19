import json
from pathlib import Path

from tracemap.cli import main
from tracemap.geo import GeoInfo
from tracemap.parser import parse_traceroute
from tracemap.plot import great_circle_segments
from tracemap.report import render_report

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def test_end_to_end_with_sample(tmp_path, capsys):
    rc = main([
        "--input", str(SAMPLES / "traceroute_sample.txt"),
        "--geo-file", str(SAMPLES / "geo_sample.json"),
        "--offline", "--no-cache", "--origin", "12.97,77.59", "--png",
        "--cables", "illustrative", "-o", str(tmp_path),
    ])
    assert rc == 0
    png = tmp_path / "route_203.0.113.10.png"
    html = tmp_path / "route_203.0.113.10.html"
    data = json.loads((tmp_path / "route_203.0.113.10.json").read_text())
    assert png.stat().st_size > 10_000
    text = html.read_text()
    assert text.startswith("<!doctype html>")
    assert 'id="cablemap"' in text.replace("'", '"') and "data:image/png" not in text
    assert 'data-hop="3"' in text.replace("'", '"')
    assert data["reached"] and len(data["hops"]) == 11
    assert data["hops"][4]["responders"] == []          # the lost hop
    assert data["hops"][0]["responders"][0]["location"] is None  # private, not located


def test_missing_target_is_an_error(capsys):
    assert main([]) == 2


def test_bad_target_is_refused(capsys):
    assert main(["--", "-h"]) == 2
    assert main(["8.8.8.8; id"]) == 2


def test_empty_input_file(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("nothing useful")
    assert main(["--input", str(f), "-o", str(tmp_path / "o")]) == 1


def test_report_escapes_untrusted_geo_text():
    trace = parse_traceroute(
        "traceroute to 8.8.8.8 (8.8.8.8), 30 hops max, 60 byte packets\n"
        " 1  8.8.8.8  1.0 ms  1.0 ms  1.0 ms\n"
    )
    evil = GeoInfo(1.0, 2.0, city="<script>alert(1)</script>", country='"><img src=x>')
    page = render_report(trace, {"8.8.8.8": evil}, "udp", None)
    assert "<script>alert(1)</script>" not in page
    assert "<img src=x>" not in page
    assert "&lt;script&gt;" in page


def test_report_for_each_method_and_windows_style():
    for method in ("udp", "icmp", "tcp"):
        trace = parse_traceroute((SAMPLES / "traceroute_sample.txt").read_text())
        page = render_report(trace, {}, method, None)
        assert "Packet anatomy" in page and "TTL" in page


def test_great_circle_splits_at_the_date_line():
    segs = great_circle_segments(35.0, 139.0, 37.0, -122.0)  # Tokyo to San Francisco
    assert len(segs) >= 2
    for seg in segs:
        lons = [p[0] for p in seg]
        assert max(lons) - min(lons) < 180


def test_no_png_by_default_with_map(tmp_path):
    rc = main(["--input", str(SAMPLES / "traceroute_sample.txt"), "--geo-file", str(SAMPLES / "geo_sample.json"),
               "--offline", "--no-cache", "--cables", "illustrative", "-o", str(tmp_path)])
    assert rc == 0 and not list(tmp_path.glob("*.png"))


def test_open_flag_opens_the_report(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    rc = main(["--input", str(SAMPLES / "traceroute_sample.txt"), "--geo-file", str(SAMPLES / "geo_sample.json"),
               "--offline", "--no-cache", "--cables", "illustrative", "--open", "-o", str(tmp_path)])
    assert rc == 0 and len(opened) == 1
    assert opened[0].startswith("file://") and opened[0].endswith(".html")


def test_no_rdns_and_offline_never_resolve_names(tmp_path, monkeypatch):
    def boom(ip):
        raise AssertionError("reverse DNS used")
    monkeypatch.setattr("socket.gethostbyaddr", boom)
    for extra in (["--offline"], ["--no-rdns"]):
        rc = main(["--input", str(SAMPLES / "traceroute_sample.txt"), "--geo-file", str(SAMPLES / "geo_sample.json"),
                   "--no-cache", "--cables", "illustrative", "--origin", "12.97,77.59",
                   "-o", str(tmp_path / extra[0].strip("-")), *extra])
        assert rc == 0
