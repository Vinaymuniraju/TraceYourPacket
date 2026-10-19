"""Build the self-contained HTML packet-path report."""
from __future__ import annotations

from html import escape as esc
from typing import Optional

from .geo import GeoInfo, classify_ip, haversine_km
from .parser import Hop, Trace
from .report_css import CSS

# What each probe type looks like on the wire and how the end host answers.
METHODS = {
    "udp": {
        "name": "UDP",
        "proto": 17,
        "probe": "UDP datagram",
        "final_short": "ICMP 3/3 port unreachable",
        "final_long": "ICMP type 3, code 3 (destination unreachable: port unreachable)",
        "final_why": "Nothing listens on the high UDP port, so the destination's IP stack "
        "answers with an ICMP error. That error is how traceroute knows it arrived.",
        "match": "the UDP source and destination ports quoted inside the ICMP error",
    },
    "icmp": {
        "name": "ICMP",
        "proto": 1,
        "probe": "ICMP echo request",
        "final_short": "ICMP 0/0 echo reply",
        "final_long": "ICMP type 0, code 0 (echo reply)",
        "final_why": "The destination's kernel answers every echo request with an echo reply.",
        "match": "the ICMP identifier and sequence number quoted inside the ICMP error",
    },
    "tcp": {
        "name": "TCP",
        "proto": 6,
        "probe": "TCP SYN",
        "final_short": "TCP SYN-ACK / RST",
        "final_long": "TCP SYN-ACK (port open) or RST (port closed)",
        "final_why": "The destination answers a SYN with SYN-ACK if a service listens, "
        "or with RST if not. Either one proves arrival.",
        "match": "the TCP source port and sequence number quoted inside the ICMP error",
    },
}


def _ms(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:.1f} ms"


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


_SHORT = {
    "Default gateway (your router)": "Your router",
    "ISP carrier-grade NAT gateway": "ISP CGNAT",
    "Router in private address space": "Private router",
    "Router (documentation address)": "Router",
    "Destination host": "Destination",
}


def _role(hop: Hop, idx: int, cls: str, is_dest: bool) -> str:
    if is_dest:
        return "Destination host"
    if cls.startswith("private") and idx == 0:
        return "Default gateway (your router)"
    if cls.startswith("carrier-grade"):
        return "ISP carrier-grade NAT gateway"
    if cls.startswith("private"):
        return "Router in private address space"
    if cls.startswith("documentation"):
        return "Router (documentation address)"
    return "Router"


# --------------------------------------------------------------------------
# Sequence diagram
# --------------------------------------------------------------------------
def sequence_svg(trace: Trace, geo: dict, method: str) -> str:
    m = METHODS[method]
    hops = trace.hops
    n = len(hops)
    colw, x0, row0, rowh = 132, 76, 118, 72
    xs = [x0 + i * colw for i in range(n + 1)]
    width = xs[-1] + 90
    height = row0 + n * rowh + 20
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" '
        f'aria-label="Sequence diagram of each TTL probe and its ICMP reply">',
        "<defs>"
        '<marker id="aFw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
        'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--fw)"/></marker>'
        '<marker id="aBk" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
        'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--bk)"/></marker>'
        '<marker id="aOk" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
        'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--ok)"/></marker>'
        '<marker id="aBad" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
        'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--bad)"/></marker>'
        "</defs>",
    ]

    # Node boxes and lifelines.
    for i in range(n + 1):
        x = xs[i]
        if i == 0:
            l1, l2, l3, cls = "You", "source", "", "box"
        else:
            hop = hops[i - 1]
            is_dest = trace.reached and i == n
            if hop.ip:
                g = geo.get(hop.ip)
                l1 = f"TTL {hop.ttl}"
                l2 = hop.ip
                role = _role(hop, i - 1, classify_ip(hop.ip), is_dest)
                l3 = g.city if g and g.city else _SHORT.get(role, role)
                cls = "box dest" if is_dest else "box"
            else:
                l1, l2, l3, cls = f"TTL {hop.ttl}", "no reply", "* * *", "box none"
        out.append(f'<line class="life" x1="{x}" y1="78" x2="{x}" y2="{height - 10}"/>')
        out.append(f'<rect class="{cls}" x="{x - 59}" y="20" width="118" height="58" rx="8"/>')
        out.append(f'<text x="{x}" y="38" text-anchor="middle" font-size="11" font-weight="700">{esc(l1)}</text>')
        out.append(f'<text class="m" x="{x}" y="54" text-anchor="middle" font-size="11">{esc(l2)}</text>')
        out.append(f'<text x="{x}" y="69" text-anchor="middle" font-size="10.5" '
                   f'style="fill:var(--muted)">{esc(_short(l3, 19))}</text>')

    # One probe per row.
    for k, hop in enumerate(hops, start=1):
        y = row0 + (k - 1) * rowh
        xk = xs[k]
        is_dest = trace.reached and k == n
        lost = hop.ip is None
        fw_cls = "lost" if lost else "fw"
        mk = "aBad" if lost else "aFw"
        out.append(f'<line class="{fw_cls}" x1="{x0 + 2}" y1="{y}" x2="{xk - 12}" y2="{y}" marker-end="url(#{mk})"/>')
        out.append(f'<text class="m halo" x="{x0 + 10}" y="{y - 7}" font-size="11" '
                   f'style="fill:var(--fw)">{esc(m["name"])} probe, TTL={hop.ttl}</text>')
        for j in range(1, k):
            out.append(f'<circle class="ttl" cx="{xs[j]}" cy="{y}" r="10"/>')
            out.append(f'<text x="{xs[j]}" y="{y + 4}" text-anchor="middle" font-size="11" '
                       f'font-weight="700">{hop.ttl - j}</text>')
        if lost:
            out.append(f'<circle class="ttl0" cx="{xk}" cy="{y}" r="10"/>')
            out.append(f'<text x="{xk}" y="{y + 4}" text-anchor="middle" font-size="12" '
                       f'style="fill:var(--bad)" font-weight="700">×</text>')
            out.append(f'<text class="halo" x="{x0 + 10}" y="{y + 27}" font-size="11" '
                       f'style="fill:var(--bad)">no reply ({hop.lost} probes lost)</text>')
            continue
        out.append(f'<circle class="ttl0" cx="{xk}" cy="{y}" r="10"/>')
        out.append(f'<text x="{xk}" y="{y + 4}" text-anchor="middle" font-size="11" '
                   f'style="fill:var(--bad)" font-weight="700">0</text>')
        back = "ok" if is_dest else "bk"
        mb = "aOk" if is_dest else "aBk"
        label = m["final_short"] if is_dest else "ICMP 11/0 time exceeded"
        out.append(f'<line class="{back}" x1="{xk}" y1="{y + 10}" x2="{xk}" y2="{y + 34}"/>')
        out.append(f'<line class="{back}" x1="{xk}" y1="{y + 34}" x2="{x0 + 2}" y2="{y + 34}" marker-end="url(#{mb})"/>')
        colour = "var(--ok)" if is_dest else "var(--bk)"
        out.append(f'<text class="m halo" x="{x0 + 10}" y="{y + 28}" font-size="11" '
                   f'style="fill:{colour}">{esc(label)} · {esc(_ms(hop.rtt_avg))}</text>')
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------
# Per-hop analysis
# --------------------------------------------------------------------------
def _hop_notes(trace: Trace, idx: int, geo: dict, method: str) -> list[str]:
    hop = trace.hops[idx]
    notes: list[str] = []
    later_answers = any(h.ip for h in trace.hops[idx + 1:])

    if hop.ip is None:
        if later_answers:
            notes.append(
                "No reply, yet later hops answered, so packets did pass through this router. "
                "It most likely drops or rate-limits the ICMP errors it generates, or a "
                "firewall filters them."
            )
        else:
            notes.append(
                "No reply and nothing answered after it. A firewall may block the probes, "
                "or the destination does not respond to this probe type. Try --method icmp or tcp."
            )
        return notes

    cls = classify_ip(hop.ip)
    if cls.startswith("carrier-grade"):
        notes.append("Address from 100.64.0.0/10: your ISP shares public addresses between "
                     "customers (CGNAT). A second NAT happens here or just beyond.")
    if idx == 0 and cls.startswith("private"):
        notes.append("Hop 1 is the next device on your local link. Your computer sends probes "
                     "to its MAC address after an ARP lookup.")
    if len(hop.responders) > 1:
        ips = ", ".join(r.ip for r in hop.responders)
        notes.append(f"Several addresses answered for this TTL ({esc(ips)}). That points to "
                     "load balancing across equal-cost paths: the router hashes the packet "
                     "headers, and the probes took different routes.")
    if hop.lost:
        notes.append(f"{hop.lost} of the probes for this TTL got no answer (loss or rate limiting).")
    if hop.flags:
        notes.append("traceroute flags: " + esc(" ".join(hop.flags)) +
                     " (for example !H host unreachable, !N network unreachable, !X filtered).")

    rtts = hop.rtts
    if rtts and len(rtts) > 1:
        spread = max(rtts) - min(rtts)
        if spread > 5 and spread > 0.2 * (hop.rtt_avg or 1):
            notes.append(f"RTT varies by {spread:.1f} ms across probes. Routers handle ICMP "
                         "generation on a slow path, so some jitter at a hop is normal.")

    # Latency step against the previous hop that answered.
    prev_idx = next((j for j in range(idx - 1, -1, -1) if trace.hops[j].ip), None)
    if prev_idx is not None and hop.rtt_avg is not None and trace.hops[prev_idx].rtt_avg is not None:
        delta = hop.rtt_avg - trace.hops[prev_idx].rtt_avg
        if delta > 40:
            text = (f"RTT jumps by {delta:.0f} ms from hop {trace.hops[prev_idx].ttl}. "
                    "That size of step usually means a long-haul or undersea link")
            g1, g2 = geo.get(trace.hops[prev_idx].ip), geo.get(hop.ip)
            if g1 and g2:
                km = haversine_km(g1, g2)
                text += (f": the two locations are about {km:,.0f} km apart, which costs at "
                         f"least {km / 100:.0f} ms round trip in fibre")
            notes.append(text + ".")
        elif delta < -3:
            notes.append("RTT is lower than at the previous hop. Intermediate routers answer "
                         "ICMP on a slow path and the return route can differ, so a hop's RTT "
                         "is not a clean latency measurement of that router.")
    return notes


def _hop_card(trace: Trace, idx: int, geo: dict, method: str) -> str:
    m = METHODS[method]
    hop = trace.hops[idx]
    is_dest = trace.reached and idx == len(trace.hops) - 1
    cls_card = "card dest" if is_dest else ("card none" if hop.ip is None else "card")

    if hop.ip is None:
        head = f"<h3>TTL {hop.ttl} · no reply</h3>"
        badges = '<span class="badge">* * *</span>'
        steps = (
            f"<ol><li>You send a {esc(m['probe'])} with IP TTL={hop.ttl}.</li>"
            f"<li>Routers before this point forward it, each subtracting 1.</li>"
            f"<li>It reaches TTL 0 at the router for hop {hop.ttl}, but no ICMP error reaches you.</li></ol>"
        )
    else:
        g = geo.get(hop.ip)
        cls = classify_ip(hop.ip)
        head = f'<h3>TTL {hop.ttl} · <span class="mono">{esc(hop.ip)}</span></h3>'
        badges = f'<span class="badge">{esc(_role(hop, idx, cls, is_dest))}</span>'
        badges += f'<span class="badge">{esc(cls)}</span>'
        if g:
            badges += f'<span class="badge">{esc(g.label)}</span>'
        names = [r.hostname for r in hop.responders if r.hostname]
        if names:
            badges += f'<span class="badge">{esc(names[0])}</span>'
        badges += (f'<span class="badge">RTT min/avg/max '
                   f'{esc(_ms(hop.rtt_min))} / {esc(_ms(hop.rtt_avg))} / {esc(_ms(hop.rtt_max))}</span>')
        passed = hop.ttl - 1
        if passed == 0:
            before = "No router sits before this one, so the probe arrives with TTL=1."
        else:
            arrive = "TTL=1" if not is_dest else "TTL of 1 or more"
            before = (f"The {passed} router{'s' if passed != 1 else ''} before this one each "
                      f"subtract 1 from TTL, so it arrives here with {arrive}.")
        fwd = (f"<li>You send a {esc(m['probe'])} with IP TTL={hop.ttl} to {esc(trace.target_ip or trace.target)}.</li>"
               f"<li>{before}</li>")
        if is_dest:
            steps = (
                "<ol>" + fwd +
                f"<li>The destination accepts the packet. {esc(m['final_why'])}</li>"
                f"<li>It replies with {esc(m['final_long'])}. Traceroute matches it to the probe "
                f"using {esc(m['match'])}.</li>"
                f"<li>RTT = time the reply arrived minus time the probe left: {esc(_ms(hop.rtt_avg))} on average.</li></ol>"
            )
        else:
            steps = (
                "<ol>" + fwd +
                "<li>The router subtracts 1, gets 0 and discards the packet (RFC 1812).</li>"
                f"<li>It sends ICMP type 11, code 0 (time exceeded in transit) from {esc(hop.ip)} to you. "
                "The error quotes the dropped packet's IP header plus 8 bytes of its payload.</li>"
                f"<li>Traceroute matches it to the probe using {esc(m['match'])}. "
                f"RTT = {esc(_ms(hop.rtt_avg))} on average.</li></ol>"
            )
    notes = _hop_notes(trace, idx, geo, method)
    notes_html = ""
    if notes:
        notes_html = "<ul>" + "".join(f"<li>{n}</li>" for n in notes) + "</ul>"
    return f'<div class="{cls_card}">{head}{badges}{steps}{notes_html}</div>'


# --------------------------------------------------------------------------
# Header anatomy
# --------------------------------------------------------------------------
def _bits(rows: list[list[tuple]]) -> str:
    """rows: list of rows; each cell is (label, bits, value, css-class)."""
    out = ['<div class="bits">']
    for row in rows:
        assert sum(c[1] for c in row) == 32, row
        for label, bits, value, cls in row:
            out.append(
                f'<div class="{cls}" style="grid-column:span {bits}">'
                f"<small>{esc(label)}{'' if label.endswith(')') else f' · {bits} bit' + ('s' if bits != 1 else '')}</small>"
                f"{esc(value)}</div>"
            )
    out.append("</div>")
    return "".join(out)


def _l4_rows(method: str, payload: int) -> list[list[tuple]]:
    if method == "udp":
        return [[("Source port", 16, "ephemeral port", "ill"),
                 ("Destination port", 16, "33434 + probe number", "")],
                [("Length", 16, str(8 + payload), ""), ("Checksum", 16, "computed", "")]]
    if method == "icmp":
        return [[("Type", 8, "8 (echo request)", ""), ("Code", 8, "0", ""),
                 ("Checksum", 16, "computed", "")],
                [("Identifier", 16, "process id", "ill"),
                 ("Sequence", 16, "grows with each probe", "")]]
    return [[("Source port", 16, "ephemeral port", "ill"), ("Destination port", 16, "80 (default)", "")],
            [("Sequence number", 32, "random, identifies the probe", "ill")],
            [("Data offset and flags", 16, "SYN set", ""), ("Window", 16, "default", "ill")]]


def anatomy_html(trace: Trace, method: str) -> str:
    m = METHODS[method]
    example = next((h for h in trace.hops[1:] if h.ip), None) or next((h for h in trace.hops if h.ip), None)
    k = example.ttl if example else 1
    router_ip = example.ip if example else "router address"
    total = trace.packet_size or 60
    payload = max(total - 20 - (8 if method == "udp" else 20 if method == "tcp" else 8), 0)
    target = trace.target_ip or trace.target

    probe_rows = [
        [("Version", 4, "4", ""), ("IHL", 4, "5", ""), ("DSCP/ECN", 8, "0x00", "ill"),
         ("Total length", 16, f"{total} bytes", "")],
        [("Identification", 16, "varies", "ill"), ("Flags", 3, "0", "ill"), ("Fragment offset", 13, "0", "ill")],
        [("TTL", 8, f"{k}", "hl"), ("Protocol", 8, f"{m['proto']} ({m['name']})", ""),
         ("Header checksum", 16, "recomputed at every hop", "")],
        [("Source address", 32, "your IP (a NAT device rewrites it on the way out)", "ill")],
        [("Destination address", 32, target, "")],
    ] + _l4_rows(method, payload)

    reply_rows = [
        [("Version", 4, "4", ""), ("IHL", 4, "5", ""), ("DSCP/ECN", 8, "0xc0", "ill"),
         ("Total length", 16, "56 or more", "ill")],
        [("Identification", 16, "varies", "ill"), ("Flags and offset", 16, "0", "ill")],
        [("TTL", 8, "router's start value (64 or 255) minus the hops back", "ill"),
         ("Protocol", 8, "1 (ICMP)", ""), ("Header checksum", 16, "computed", "")],
        [("Source address", 32, f"{router_ip} (the router that dropped your probe)", "hl")],
        [("Destination address", 32, "your IP (translated back by NAT)", "ill")],
        [("ICMP type", 8, "11 (time exceeded)", "hl"), ("Code", 8, "0 (TTL expired in transit)", "hl"),
         ("Checksum", 16, "computed", "")],
        [("Unused", 32, "zero (RFC 4884 may carry a length here)", "")],
        [("Quoted original IPv4 header (20 bytes, one row per 4 bytes in reality)", 32,
          f"src = you, dst = {target}, TTL as it arrived (usually 1), proto {m['proto']}", "")],
        [("First 8 bytes of the original payload (64 bits)", 32,
          f"the {m['name']} header fields traceroute uses to pair this error with a probe", "")],
    ]
    ruler = '<div class="ruler"><span>0</span><span>8</span><span>16</span><span>24 … 31</span></div>'
    return (
        f"<h3>Outgoing probe, as sent with TTL={k}</h3>{ruler}{_bits(probe_rows)}"
        f"<h3>Reply from {esc(router_ip)}: ICMP time exceeded</h3>{ruler}{_bits(reply_rows)}"
        '<p class="muted">Highlighted cells are the fields that make traceroute work. Italic '
        "cells are typical values that differ per machine. Sizes follow the default probe "
        f"({total} bytes).</p>"
    )


# --------------------------------------------------------------------------
# Layer-by-layer panels
# --------------------------------------------------------------------------
def _layers(rows: list[tuple[str, str]]) -> str:
    return "".join(f'<div class="layer"><b>{esc(a)}</b><span>{b}</span></div>' for a, b in rows)


def panels_html(trace: Trace, method: str) -> str:
    m = METHODS[method]
    first_private = bool(trace.hops and trace.hops[0].ip and classify_ip(trace.hops[0].ip).startswith("private"))
    target = esc(trace.target_ip or trace.target)
    probe_l4 = {
        "udp": "UDP header: random source port, destination port 33434 and up (one per probe).",
        "icmp": "ICMP echo request: identifier = process id, sequence number per probe.",
        "tcp": "TCP SYN to port 80 with a random sequence number per probe.",
    }[method]
    panels = []

    panels.append(("1 · vis_route.py on your computer", _layers([
        ("Application", "Validates the target (IPv4 or hostname, never an option string), resolves a "
         "hostname with a DNS A lookup, then starts the system <code>traceroute</code> as a child "
         "process with an argument list, so no shell is involved."),
        ("traceroute", f"For TTL 1, 2, 3 … it sends 3 probes per TTL. It sets the TTL on the socket "
         f"(<code>setsockopt IP_TTL</code>), calls <code>sendto()</code> and reads ICMP errors from a "
         "raw ICMP socket. It prints one line per hop."),
        ("Transport", esc(probe_l4)),
        ("Network", f"Kernel builds the IPv4 header: TTL=k, protocol {m['proto']}, destination {target}. "
         "The routing table picks the default route."),
        ("Link", "ARP finds the gateway's MAC address (cached). The NIC sends an Ethernet or Wi-Fi "
         "frame addressed to the gateway."),
    ])))

    gw = "Your home router" if first_private else "First router"
    gw_rows = [
        ("Link", "Receives the frame and strips the Ethernet header."),
        ("Network", "Checks the TTL. If it is 1 the router stops here and sends ICMP time exceeded; "
         "otherwise it subtracts 1 and updates the header checksum."),
    ]
    if first_private:
        gw_rows.append(("NAT", "Rewrites your private source address and port to its own public (or ISP-NAT) "
                        "address and stores a connection-tracking entry. That entry lets an ICMP error "
                        "coming back be translated to your private address."))
    gw_rows.append(("Forwarding", "Looks up the next hop (usually the ISP) and re-frames the packet for the "
                    "uplink (PPPoE, Ethernet, GPON)."))
    panels.append((f"2 · {gw}", _layers(gw_rows)))

    panels.append(("3 · Each transit router", _layers([
        ("Ingress", "Line card receives the packet and parses the IP header."),
        ("Lookup", "Longest-prefix match in the forwarding table picks the egress port. With equal-cost "
         "routes it hashes the addresses and ports, so probes of one traceroute can split across paths."),
        ("TTL", "TTL−1, checksum update, forward. At TTL 0 the packet is dropped and handed to the "
         "control-plane CPU."),
        ("ICMP", "The CPU builds ICMP type 11 code 0, sourced from one of its own addresses, and "
         "sends it toward you. Routers rate-limit this, so these hops show higher or patchier RTT than "
         "real traffic sees. MPLS networks can hide hops entirely."),
        ("Return", "The error is routed independently. The way back can be a different path than the "
         "way out."),
    ])))

    panels.append(("4 · Destination host", _layers([
        ("Link / IP", f"Frame accepted, destination address {target} matches the host, TTL is not an issue."),
        ("Transport", esc(m["final_why"])),
        ("Reply", esc(m["final_long"]) + ". After this reply traceroute stops."),
        ("If silent", "A firewall or a host that ignores this probe type gives a run of * * * at the end. "
         "Another <code>--method</code> often gets through."),
    ])))

    panels.append(("5 · vis_route.py after the trace", _layers([
        ("Parse", "Reads each output line, collecting responder addresses and RTTs. Handles Linux, macOS "
         "and Windows layouts, lost probes and several responders per TTL."),
        ("Classify", "Private, CGNAT and documentation addresses are never sent anywhere."),
        ("Geolocate", "For each public hop: local cache first, then one HTTPS request to the geolocation "
         "service (DNS lookup, TCP handshake, TLS handshake, <code>GET /json/&lt;ip&gt;</code>, JSON reply, "
         "5 s timeout). <code>--offline</code> skips the network."),
        ("Draw", "Basemap draws the map. Great-circle arcs join consecutive located hops."),
        ("Write", "PNG map, JSON data and this HTML report go to the output folder."),
    ])))

    return '<div class="panels">' + "".join(
        f'<div class="panel"><h3>{esc(title)}</h3>{body}</div>' for title, body in panels) + "</div>"


# --------------------------------------------------------------------------
# Full page
# --------------------------------------------------------------------------
def render_report(
    trace: Trace,
    geo: dict[str, Optional[GeoInfo]],
    method: str,
    map_png_b64: Optional[str],
    origin: Optional[tuple[float, float]] = None,
    map_doc: Optional[str] = None,
    cable_html: str = "",
) -> str:
    method = method if method in METHODS else "udp"
    hops = trace.hops
    answered = [h for h in hops if h.ip]
    last = answered[-1] if answered else None

    # Geographic length of the path and the physical lower bound on RTT.
    pts: list[GeoInfo] = []
    if origin:
        pts.append(GeoInfo(origin[0], origin[1]))
    pts += [geo[h.ip] for h in hops if h.ip and geo.get(h.ip)]
    km = sum(haversine_km(a, b) for a, b in zip(pts, pts[1:]))
    floor_ms = km / 100.0  # 200 km per ms in fibre, there and back
    countries = []
    for h in hops:
        g = geo.get(h.ip) if h.ip else None
        if g and g.country and g.country not in countries:
            countries.append(g.country)

    max_avg = max((h.rtt_avg or 0 for h in hops), default=1) or 1
    rows = []
    for idx, h in enumerate(hops):
        g = geo.get(h.ip) if h.ip else None
        cls = classify_ip(h.ip) if h.ip else "-"
        pct = 0 if h.rtt_avg is None else max(2, int(100 * h.rtt_avg / max_avg))
        rows.append(
            f"<tr><td>{h.ttl}</td><td class='mono'>{esc(h.ip or '* * *')}</td>"
            f"<td>{esc(_role(h, idx, cls, trace.reached and idx == len(hops) - 1)) if h.ip else 'no reply'}</td>"
            f"<td>{esc(g.label) if g else '<span class=muted>not located</span>'}</td>"
            f"<td>{esc(_ms(h.rtt_min))}</td><td>{esc(_ms(h.rtt_avg))}</td><td>{esc(_ms(h.rtt_max))}</td>"
            f"<td style='width:140px'><div class='bar' style='width:{pct}%'></div></td></tr>"
        )

    stats = [
        (str(len(hops)), "hops to " + ("destination" if trace.reached else "last answer")),
        (f"{len(answered)}/{len(hops)}", "hops that answered"),
        (_ms(last.rtt_avg) if last else "-", "RTT at the last answering hop"),
        (f"{km:,.0f} km" if km else "-", "geographic path length (approx.)"),
        (f"{floor_ms:.0f} ms" if km else "-", "fibre-speed floor for that path"),
        (str(len(countries)) if countries else "-",
         "countries: " + ", ".join(countries) if countries else "countries crossed"),
    ]
    stat_html = "".join(f'<div class="stat"><b>{esc(v)}</b><span>{esc(k)}</span></div>' for v, k in stats)

    map_html = (
        f'<img class="map" alt="Route map" src="data:image/png;base64,{map_png_b64}">'
        if map_png_b64 else '<p class="muted">No hop could be located, so there is no map.</p>'
    )
    m = METHODS[method]
    title = f"Packet path to {trace.target or trace.target_ip}"

    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{esc(title)}</title><style>{CSS}</style></head><body><main>",
        f"<h1>{esc(title)}</h1>",
        f"<p class='muted'>Target <span class='mono'>{esc(trace.target_ip or '?')}</span> · "
        f"probe type {esc(m['name'])} · destination "
        f"{'reached' if trace.reached else 'not reached'}</p>",
        f"<div class='stats'>{stat_html}</div>",
        "<h2>Route on the map</h2>",
        (
            "<iframe class='cablemap' title='Interactive submarine cable map' loading='lazy' "
            "sandbox='allow-scripts' style='width:100%;height:78vh;min-height:560px;border:1px solid "
            "var(--line,#334);border-radius:12px;background:#050912' srcdoc=\""
            + esc(map_doc) + "\"></iframe>"
            if map_doc else ""
        ),
        map_html, cable_html,
        "<h2>How the packets travelled</h2>",
        "<p>Each row is one probe. It leaves your computer with a TTL that equals the row's number. "
        "The circle on every router it crosses shows the TTL left after that router subtracted 1. "
        "Where the TTL reaches 0 the router drops the probe and answers with an ICMP error, so each "
        "reply tells you who sits at that distance.</p>",
        "<div class='legend'>"
        f"<span><i style='border-color:var(--fw)'></i>{esc(m['name'])} probe going out</span>"
        "<span><i style='border-color:var(--bk)'></i>ICMP time exceeded coming back</span>"
        f"<span><i style='border-color:var(--ok)'></i>{esc(m['final_short'])} from the destination</span>"
        "<span><i style='border-color:var(--bad);border-top-style:dashed'></i>probe with no reply</span>"
        "</div>",
        f"<div class='scroll'>{sequence_svg(trace, geo, method)}</div>",
        "<h2>Hop table</h2>",
        "<table class='hops'><thead><tr><th>TTL</th><th>Address</th><th>Role</th><th>Location</th>"
        "<th>Min</th><th>Avg</th><th>Max</th><th>RTT</th></tr></thead><tbody>" + "".join(rows) +
        "</tbody></table>",
    ]
    if km:
        ratio = (last.rtt_avg / floor_ms) if (last and last.rtt_avg and floor_ms) else None
        txt = (f"The located hops add up to about {km:,.0f} km. Light in fibre covers roughly "
               f"200 km per millisecond, so a round trip over that distance cannot be faster than "
               f"about {floor_ms:.0f} ms.")
        if ratio:
            txt += f" The last answer took {last.rtt_avg:.0f} ms, {ratio:.1f}× that floor"
            txt += (". Real routes are longer than the straight line between cities, and every router "
                    "adds queueing and processing time.")
        parts.append(f"<p>{esc(txt)}</p>")
    parts += [
        "<h2>What happened at each hop</h2>",
        "<div class='cards'>" + "".join(_hop_card(trace, i, geo, method) for i in range(len(hops))) + "</div>",
        "<h2>What each device and program does</h2>", panels_html(trace, method),
        "<h2>Packet anatomy</h2>", anatomy_html(trace, method),
        "<footer><p>Reading the numbers: a hop's RTT includes the time its router needs to generate "
        "the ICMP error, so it is not a clean measure of the link. Locations come from a geolocation "
        "database and can be off by hundreds of kilometres, especially for routers. Addresses shown are "
        "the ones routers put in their replies, which are not always the interface the probe came in on.</p></footer>",
        "</main></body></html>",
    ]
    return "".join(parts)
