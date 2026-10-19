import json
from pathlib import Path

import pytest

from tracemap.analysis import Options, analyse
from tracemap.cli import main
from tracemap.parser import parse_traceroute
from tracemap.snapshot import (SnapshotError, list_runs, load_history, load_snapshot,
                               load_snapshot_dict, save_snapshot, to_snapshot)

S = Path(__file__).resolve().parent.parent / "samples"


def make(taken="2026-10-19T10:00:00Z"):
    t = parse_traceroute((S / "traceroute_sample.txt").read_text())
    t.target = "example.com"
    o = Options(offline=True, no_cache=True, geo_file=S / "geo_sample.json", asn_file=S / "asn_sample.json")
    return analyse(t, "udp", (12.97, 77.59), o, taken_at=taken)


def test_round_trip(tmp_path):
    a = make()
    p = save_snapshot(a, tmp_path)
    b = load_snapshot(p)
    assert len(b.trace.hops) == len(a.trace.hops)
    assert b.geo["192.0.2.13"].city == a.geo["192.0.2.13"].city
    assert b.origin == a.origin and b.taken_at == a.taken_at
    assert to_snapshot(b)["hops"] == to_snapshot(a)["hops"]


def test_history_order_and_before(tmp_path):
    for t in ("2026-10-19T10:00:00Z", "2026-10-19T09:00:00Z", "2026-10-19T11:00:00Z"):
        save_snapshot(make(t), tmp_path)
    runs = load_history(tmp_path, "example.com")
    assert [r.taken_at for r in runs] == ["2026-10-19T09:00:00Z", "2026-10-19T10:00:00Z", "2026-10-19T11:00:00Z"]
    assert len(load_history(tmp_path, "example.com", before="2026-10-19T10:00:00Z")) == 1
    assert len(list_runs(tmp_path)) == 3


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(format="x"),
    lambda d: d.update(version=9),
    lambda d: d.update(hops=[]),
    lambda d: d.update(method="gopher"),
    lambda d: d.update(saved_at="yesterday"),
    lambda d: d["hops"][0]["responders"][0].update(ip="not-an-ip"),
    lambda d: d["hops"][0]["responders"][0].update(rtts=["a"]),
    lambda d: d["hops"][0]["responders"][0].update(lat=999, lon=0),
    lambda d: d["hops"][0].update(ttl=0),
    lambda d: d["hops"].append(dict(d["hops"][0])),
    lambda d: d.update(origin=[1]),
])
def test_rejects_bad_files(mutate):
    d = to_snapshot(make())
    mutate(d)
    with pytest.raises(SnapshotError):
        load_snapshot_dict(d)


def test_rejects_non_json_and_huge(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("{nope")
    with pytest.raises(SnapshotError):
        load_snapshot(f)
    f.write_text(" " * (5 * 1024 * 1024 + 1))
    with pytest.raises(SnapshotError):
        load_snapshot(f)


def test_html_in_strings_is_kept_as_text_only():
    d = to_snapshot(make())
    d["hops"][0]["responders"][0]["hostname"] = "<script>alert(1)</script>" * 40
    b = load_snapshot_dict(d)
    assert len(b.names[d["hops"][0]["responders"][0]["ip"]]) <= 253


def test_cli_saves_lists_and_replays(tmp_path, capsys):
    out, hist = tmp_path / "o", tmp_path / "h"
    base = ["example.com", "--input", str(S / "traceroute_sample.txt"), "--offline", "--no-cache",
            "--geo-file", str(S / "geo_sample.json"), "--asn-file", str(S / "asn_sample.json"),
            "--origin", "12.97,77.59", "--cables", "illustrative", "-o", str(out), "--history-dir", str(hist)]
    assert main(base + ["--run-time", "2026-10-19T10:00:00Z"]) == 0
    assert len(list_runs(hist)) == 1
    assert main(["--history", "--history-dir", str(hist)]) == 0
    assert "20261019T100000Z" in capsys.readouterr().out
    run = list_runs(hist)[0][1]
    out2 = tmp_path / "o2"
    assert main(["--from-run", str(run), "-o", str(out2), "--history-dir", str(hist)]) == 0
    assert len(list_runs(hist)) == 1          # replay does not save again
    assert (out2 / "route_example.com.html").exists()
    assert main(base + ["--no-save", "--run-time", "bad"]) == 2
    assert main(["--from-run", str(tmp_path / "missing.json")]) == 2
