"""Per-leg latency analysis: observed RTT step against the physical minimum.

For each leg of the inferred path (station to station) we compare

* the **step**: how much the RTT grew between the previous station and this one, with
* the **floor**: the round trip light needs in fibre over the leg's length (km / 100 ms).

The ratio and the sign of the step give a plain-language verdict. A traceroute measures only the
forward path to each router plus whatever path the reply takes, so verdicts are hints:

* a negative or tiny step on a long leg points to an **asymmetric return path** or a slow ICMP
  path at the earlier router, not to a faster network;
* a step far above the floor points to a **longer real route** than the inferred one, queueing,
  or a slow return path.
"""
from __future__ import annotations

from html import escape
from typing import Optional

SHORT_FLOOR_MS = 2.0     # below this, the leg is local and ratios mean little


def _verdict(step: Optional[float], floor: float) -> tuple[str, str]:
    """(code, text) for one leg."""
    if step is None:
        return "unknown", "No RTT at the end of this leg."
    if floor < SHORT_FLOOR_MS:
        return "short", "Short link; the time is mostly router and queueing delay."
    if step < 0:
        return "asym", ("RTT went down. The reply to the earlier hop probably took a slower path, so the "
                        "return route differs from the forward one.")
    if step < 0.7 * floor:
        return "asym", ("Step is smaller than light needs for this distance. Either the return route is "
                        "asymmetric or the location is wrong.")
    ratio = step / floor
    excess = step - floor
    if ratio <= 1.5:
        return "ok", "Close to the physical limit for this distance."
    if ratio <= 3 or excess < 20:
        return "detour", ("Somewhat above the minimum. Real fibre is rarely a straight line, so a detour or "
                          "some queueing is normal.")
    return "slow", (f"{excess:,.0f} ms above the minimum. Likely a much longer real route than the inferred "
                    "one, congestion, or a slow return path.")


def leg_latency(data: dict) -> list[dict]:
    """One dict per leg: from, to, km, floor, step, excess, ratio, verdict, text, cables."""
    st, hops, legs = data["stations"], data["hops"], data["legs"]
    first_rtt: dict[int, float] = {}
    for h in hops:
        if h["rtt"] and h["station"] not in first_rtt:
            first_rtt[h["station"]] = h["rtt"]["avg"]
    last = None if data.get("originGuess") else 0.0   # you are at station 0 when your position is known
    out = []
    for i, leg in enumerate(legs):
        end = first_rtt.get(i + 1)
        floor = leg["km"] / 100.0
        start = last if i == 0 else first_rtt.get(i)
        if i > 0 and start is None:
            start = out[-1]["rtt_end"] if out else None
        step = (end - start) if (end is not None and start is not None) else None
        code, text = _verdict(step, floor)
        out.append({
            "leg": i + 1, "from": st[i]["label"], "to": st[i + 1]["label"], "km": leg["km"],
            "floor": floor, "step": step, "rtt_end": end if end is not None else start,
            "excess": (step - floor) if step is not None else None,
            "ratio": (step / floor) if (step is not None and floor > 0) else None,
            "code": code, "text": text, "cables": leg["cables"],
        })
    return out


def slowest(rows: list[dict]) -> Optional[dict]:
    cand = [r for r in rows if r["excess"] is not None and r["code"] not in ("short",)]
    return max(cand, key=lambda r: r["excess"]) if cand else None


_LABEL = {"ok": "near the limit", "detour": "some detour", "slow": "excess latency",
          "asym": "asymmetric?", "short": "short link", "unknown": "no data"}


def latency_section_html(data: dict) -> str:
    rows = leg_latency(data)
    plotted = [r for r in rows if r["step"] is not None]
    if not plotted:
        return ""
    vmax = max(max(r["step"], r["floor"]) for r in plotted)
    vmax = max(vmax, 1.0)
    left, right, top, rowh, bar = 300, 150, 30, 44, 18
    width = 900
    inner = width - left - right
    height = top + rowh * len(rows) + 28

    def x(v):
        return left + max(0.0, v) / vmax * inner

    parts = [f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Round-trip time added by each leg "
             f"compared with the physical minimum' style='width:100%;height:auto;display:block'>"]
    # recessive hairline grid and axis labels
    step_ms = next(s for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000) if vmax / s <= 6)
    t = 0
    while t <= vmax + 1e-9:
        gx = x(t)
        parts.append(f"<line x1='{gx:.1f}' x2='{gx:.1f}' y1='{top - 6}' y2='{height - 26}' "
                     f"stroke='var(--line)' stroke-width='1'/>")
        parts.append(f"<text x='{gx:.1f}' y='{height - 8}' text-anchor='middle' font-size='11' "
                     f"style='fill:var(--muted)'>{t:g} ms</text>")
        t += step_ms
    for i, r in enumerate(rows):
        cy = top + i * rowh + rowh / 2
        title = f"Leg {r['leg']}: {r['from']} to {r['to']}"
        parts.append(f"<text x='{left - 12}' y='{cy - 3:.1f}' text-anchor='end' font-size='12.5'>"
                     f"{escape(_short(title, 44))}</text>")
        parts.append(f"<text x='{left - 12}' y='{cy + 12:.1f}' text-anchor='end' font-size='11' "
                     f"style='fill:var(--muted)'>{r['km']:,.0f} km · {escape(_LABEL[r['code']])}</text>")
        tip = (f"{title}\nLength {r['km']:,.0f} km\nPhysical minimum {r['floor']:.1f} ms\n"
               + (f"Observed step {r['step']:.1f} ms\n" if r["step"] is not None else "No RTT\n") + r["text"])
        parts.append(f"<g class='legbar' tabindex='0'><title>{escape(tip)}</title>")
        if r["step"] is not None and r["step"] > 0:
            w = max(2.0, x(r["step"]) - left)
            parts.append(f"<path d='{_rbar(left, cy - bar / 2, w, bar)}' fill='var(--fw)'/>")
            lx = max(left + w, x(r["floor"])) + 10   # keep the value clear of the floor tick
            parts.append(f"<text x='{lx:.1f}' y='{cy + 4:.1f}' font-size='12' class='m'>"
                         f"{r['step']:.1f} ms</text>")
        elif r["step"] is not None:
            parts.append(f"<text x='{left + 8}' y='{cy + 4:.1f}' font-size='12' class='m'>{r['step']:.1f} ms</text>")
        # floor marker: a thin ink tick with a ring in the surface colour
        fx = x(r["floor"])
        parts.append(f"<line x1='{fx:.1f}' x2='{fx:.1f}' y1='{cy - 14}' y2='{cy + 14}' stroke='var(--card)' "
                     f"stroke-width='6' stroke-linecap='round'/>")
        parts.append(f"<line x1='{fx:.1f}' x2='{fx:.1f}' y1='{cy - 13}' y2='{cy + 13}' stroke='var(--fg)' "
                     f"stroke-width='2' stroke-linecap='round'/>")
        parts.append("</g>")
    parts.append("</svg>")

    sl = slowest(rows)
    call = ""
    if sl and sl["code"] in ("slow", "detour"):
        call = (f"<p><b>Biggest excess:</b> leg {sl['leg']} ({escape(sl['from'])} to {escape(sl['to'])}), "
                f"{sl['step']:.0f} ms observed against a {sl['floor']:.0f} ms minimum "
                f"({sl['excess']:.0f} ms over). {escape(sl['text'])}</p>")
    asym = [r for r in rows if r["code"] == "asym"]
    note = ""
    if asym:
        note = ("<p><b>Possible asymmetric return path</b> on leg"
                + ("s " if len(asym) > 1 else " ") + ", ".join(str(r["leg"]) for r in asym)
                + ". Traceroute only sees the forward path; the replies can come back another way.</p>")
    table = (
        "<details><summary>Show as a table</summary><div class='scroll'><table class='hops'><thead><tr>"
        "<th>Leg</th><th>From</th><th>To</th><th>Length</th><th>Physical minimum</th><th>Observed step</th>"
        "<th>Verdict</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td>{r['leg']}</td><td>{escape(r['from'])}</td><td>{escape(r['to'])}</td>"
            f"<td>{r['km']:,.0f} km</td><td>{r['floor']:.1f} ms</td>"
            f"<td>{'-' if r['step'] is None else format(r['step'], '.1f') + ' ms'}</td>"
            f"<td>{escape(_LABEL[r['code']])}: {escape(r['text'])}</td></tr>" for r in rows)
        + "</tbody></table></div></details>")
    return (
        "<h2>Latency per leg</h2>"
        "<p class='muted'>How much round-trip time each leg adds (blue bar) against the least that light "
        "needs in fibre over that distance (black tick). A bar ending near its tick is about as fast as "
        "physics allows; a bar far beyond it has detour, queueing or a slower reply path. Hover a bar for details.</p>"
        "<div class='scroll' style='padding:8px 10px'>" + "".join(parts) + "</div>" + call + note + table
        + "<style>.legbar:hover rect,.legbar:focus{outline:none}.legbar:hover path,.legbar:focus path{opacity:.8}"
          "details summary{cursor:pointer;margin:10px 0;color:var(--muted)}</style>"
    )


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _rbar(x: float, y: float, w: float, h: float) -> str:
    """A bar that is square at the baseline (left) and has a 4px rounded data end (right)."""
    r = min(4.0, w / 2, h / 2)
    return (f"M{x:.1f},{y:.1f}H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}"
            f"V{y + h - r:.1f}Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f}H{x:.1f}Z")
