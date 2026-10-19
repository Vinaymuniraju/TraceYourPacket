from tracemap.latency import _verdict, latency_section_html, leg_latency, slowest
from tracemap.mapviz import render_map  # noqa: F401  (import check)


def _data(legs, hops, origin_guess=False):
    stations = [{"label": f"S{i}", "lat": 0, "lon": i} for i in range(len(legs) + 1)]
    return {"stations": stations, "legs": legs, "hops": hops, "originGuess": origin_guess}


def _leg(km):
    return {"km": km, "cableKm": 0, "cables": [], "segments": []}


def _hop(ttl, station, rtt):
    return {"ttl": ttl, "station": station, "rtt": ({"avg": rtt, "min": rtt, "max": rtt} if rtt is not None else None)}


def test_verdict_ladder():
    assert _verdict(None, 50)[0] == "unknown"
    assert _verdict(1.0, 0.5)[0] == "short"
    assert _verdict(-3.0, 50)[0] == "asym"
    assert _verdict(10.0, 50)[0] == "asym"        # far smaller than light allows
    assert _verdict(55.0, 50)[0] == "ok"
    assert _verdict(120.0, 50)[0] == "detour"     # 2.4x but only 70 ms over: still 'detour' (ratio <= 3)
    assert _verdict(400.0, 50)[0] == "slow"
    assert _verdict(30.0, 12.0)[0] == "detour"    # ratio 2.5
    assert _verdict(36.0, 12.0)[0] == "detour"    # ratio 3 and excess < 20
    assert _verdict(80.0, 12.0)[0] == "slow"


def test_steps_use_previous_station_and_origin():
    d = _data([_leg(1000), _leg(2000)], [_hop(1, 1, 12.0), _hop(2, 2, 35.0)])
    rows = leg_latency(d)
    assert rows[0]["step"] == 12.0 and rows[1]["step"] == 23.0
    assert abs(rows[1]["floor"] - 20.0) < 1e-9 and abs(rows[1]["excess"] - 3.0) < 1e-9


def test_unknown_origin_gives_no_first_step():
    d = _data([_leg(1000)], [_hop(1, 1, 12.0)], origin_guess=True)
    assert leg_latency(d)[0]["step"] is None


def test_negative_step_is_asymmetric_hint():
    d = _data([_leg(1000), _leg(1000)], [_hop(1, 1, 30.0), _hop(2, 2, 22.0)])
    rows = leg_latency(d)
    assert rows[1]["code"] == "asym" and rows[1]["step"] == -8.0
    html = latency_section_html(d)
    assert "asymmetric return path" in html and "leg 2" in html


def test_slowest_ignores_short_legs():
    d = _data([_leg(10), _leg(1000)], [_hop(1, 1, 40.0), _hop(2, 2, 100.0)])
    assert slowest(leg_latency(d))["leg"] == 2


def test_section_escapes_labels_and_has_table_and_aria():
    d = _data([_leg(1000)], [_hop(1, 1, 30.0)])
    d["stations"][1]["label"] = "<img src=x onerror=1>"
    html = latency_section_html(d)
    assert "<img" not in html and "&lt;img" in html
    assert "role='img'" in html and "<details>" in html and "<title>" in html


def test_no_rtt_no_section():
    d = _data([_leg(1000)], [_hop(1, 1, None)])
    assert latency_section_html(d) == ""
