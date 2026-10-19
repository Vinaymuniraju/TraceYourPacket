from pathlib import Path

from tracemap.parser import parse_traceroute

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

LINUX = """traceroute to dns.google (8.8.8.8), 30 hops max, 60 byte packets
 1  _gateway (192.168.0.1)  0.512 ms  0.480 ms  0.455 ms
 2  * * *
 3  10.1.1.1  4.1 ms * 10.1.1.2  5.0 ms
 4  72.14.1.1  9.9 ms !N  10.2 ms  10.0 ms
 5  8.8.8.8  12.3 ms  12.1 ms  12.2 ms
"""

WINDOWS = """
Tracing route to dns.google [8.8.8.8]
over a maximum of 30 hops:

  1    <1 ms    <1 ms    <1 ms  192.168.0.1
  2     *        *        *     Request timed out.
  3     8 ms     9 ms     *     10.0.0.1
  4    12 ms    12 ms    13 ms  dns.google [8.8.8.8]

Trace complete.
"""


def test_linux_header_and_hops():
    t = parse_traceroute(LINUX)
    assert (t.target, t.target_ip, t.max_hops, t.packet_size) == ("dns.google", "8.8.8.8", 30, 60)
    assert [h.ttl for h in t.hops] == [1, 2, 3, 4, 5]
    assert t.hops[0].responders[0].hostname == "_gateway"
    assert t.hops[0].ip == "192.168.0.1"
    assert t.reached


def test_all_lost_hop():
    h = parse_traceroute(LINUX).hops[1]
    assert h.ip is None and h.lost == 3 and h.rtt_avg is None


def test_mixed_loss_and_two_responders():
    h = parse_traceroute(LINUX).hops[2]
    assert [r.ip for r in h.responders] == ["10.1.1.1", "10.1.1.2"]
    assert h.responders[0].rtts == [4.1]
    assert h.lost == 1


def test_flags_are_captured():
    h = parse_traceroute(LINUX).hops[3]
    assert h.flags == ["!N"]
    assert len(h.rtts) == 3


def test_windows_layout():
    t = parse_traceroute(WINDOWS)
    assert t.style == "windows" and t.max_hops == 30 and t.target_ip == "8.8.8.8"
    assert [h.ttl for h in t.hops] == [1, 2, 3, 4]
    assert t.hops[0].rtts == [1.0, 1.0, 1.0]
    assert t.hops[1].ip is None and t.hops[1].lost == 3
    assert t.hops[2].ip == "10.0.0.1" and t.hops[2].lost == 1 and len(t.hops[2].rtts) == 2
    assert t.hops[3].responders[0].hostname == "dns.google"
    assert t.reached


def test_continuation_line_joins_previous_hop():
    text = "traceroute to 1.1.1.1 (1.1.1.1), 30 hops max, 60 byte packets\n" \
           " 1  10.0.0.1  1.0 ms  1.1 ms\n    10.0.0.2  2.0 ms\n"
    t = parse_traceroute(text)
    assert len(t.hops) == 1
    assert [r.ip for r in t.hops[0].responders] == ["10.0.0.1", "10.0.0.2"]


def test_garbage_and_blank_lines_are_ignored():
    t = parse_traceroute("\n\nsomething odd\n 1  1.2.3.4  1 ms\n")
    assert len(t.hops) == 1


def test_invalid_octets_are_not_addresses():
    t = parse_traceroute(" 1  999.1.1.1  1 ms\n")
    assert t.hops == [] or t.hops[0].ip is None


def test_empty_input():
    assert parse_traceroute("").hops == []


def test_sample_file():
    t = parse_traceroute((SAMPLES / "traceroute_sample.txt").read_text())
    assert len(t.hops) == 11 and t.reached
    assert t.hops[9].responders[1].ip == "192.0.2.13"


def test_windows_single_line_header_for_ip_target():
    text = ("Tracing route to 8.8.8.8 over a maximum of 30 hops\n\n"
            "  1    <1 ms    <1 ms    <1 ms  192.168.0.1\n"
            "  2    12 ms    12 ms    12 ms  8.8.8.8\n")
    t = parse_traceroute(text)
    assert t.style == "windows" and t.max_hops == 30 and t.target_ip == "8.8.8.8"
    assert t.reached and len(t.hops) == 2
