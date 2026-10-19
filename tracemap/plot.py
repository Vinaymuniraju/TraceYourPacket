"""Draw the route on a world map with great-circle arcs between hops."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .geo import GeoInfo
from .parser import Hop


def great_circle_segments(lat1, lon1, lat2, lon2, n=80):
    """Points along the great circle, split where it crosses the date line.

    Basemap's own drawgreatcircle breaks with recent pyproj releases, so the
    arc is computed here.
    """
    from pyproj import Geod

    pts = Geod(ellps="sphere").npts(lon1, lat1, lon2, lat2, n)
    path = [(lon1, lat1)] + list(pts) + [(lon2, lat2)]
    segments, current = [], [path[0]]
    for prev, cur in zip(path, path[1:]):
        if abs(cur[0] - prev[0]) > 180:
            segments.append(current)
            current = []
        current.append(cur)
    segments.append(current)
    return segments


def _extent(points):
    """Map corners: crop the poles, zoom in longitude only for compact routes."""
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    span = max(lons) - min(lons)
    if span < 100.0:
        lon_lo, lon_hi = max(-180.0, min(lons) - 15.0), min(180.0, max(lons) + 15.0)
    else:
        lon_lo, lon_hi = -180.0, 180.0
    lat_lo, lat_hi = min(lats) - 15.0, max(lats) + 15.0
    # Aim for a map about twice as wide as it is tall.
    want = (lon_hi - lon_lo) * 0.45
    if lat_hi - lat_lo < want:
        grow = (want - (lat_hi - lat_lo)) / 2
        lat_lo, lat_hi = lat_lo - grow, lat_hi + grow
    # Clamp to usable latitudes, shifting the window rather than shrinking it.
    if lat_lo < -60.0:
        lat_hi += -60.0 - lat_lo
        lat_lo = -60.0
    if lat_hi > 80.0:
        lat_lo -= lat_hi - 80.0
        lat_hi = 80.0
    return max(-60.0, lat_lo), min(80.0, lat_hi), lon_lo, lon_hi


def plot_route(
    located: list[tuple[Hop, GeoInfo]],
    out_png: Path,
    show: bool = False,
    origin: Optional[tuple[float, float]] = None,
    title: str = "",
) -> None:
    import matplotlib

    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.basemap import Basemap

    pts_all = [(g.lat, g.lon) for _, g in located]
    if origin:
        pts_all.append(origin)
    lat_lo, lat_hi, lon_lo, lon_hi = _extent(pts_all)
    m = Basemap(
        projection="mill",
        llcrnrlat=lat_lo, urcrnrlat=lat_hi,
        llcrnrlon=lon_lo, urcrnrlon=lon_hi,
        lon_0=(lon_lo + lon_hi) / 2,
        resolution="l",
    )
    fig = plt.figure(figsize=(12, 12 * m.aspect + 0.7), edgecolor="w")
    try:
        m.shadedrelief(scale=0.05)
    except Exception:  # relief image missing: fall back to plain land and sea
        m.drawmapboundary(fill_color="#cfe3f2")
        m.fillcontinents(color="#e8e4d8", lake_color="#cfe3f2")
    m.drawcoastlines(linewidth=0.4, color="#555")

    points: list[tuple[float, float]] = []
    if origin:
        points.append(origin)
    points += [(g.lat, g.lon) for _, g in located]

    # Arcs first so the dots sit on top. Skip a segment only when both ends
    # are at exactly the same place.
    for (la1, lo1), (la2, lo2) in zip(points, points[1:]):
        if (la1, lo1) != (la2, lo2):
            for seg in great_circle_segments(la1, lo1, la2, lo2):
                if len(seg) > 1:
                    xs, ys = m([p[0] for p in seg], [p[1] for p in seg])
                    plt.plot(xs, ys, color="#1f5fbf", linewidth=1.6, zorder=3)

    if origin:
        x, y = m(origin[1], origin[0])
        m.scatter(x, y, 90, marker="s", color="#1a7f37", zorder=5, label="You (origin)")

    last_ttl = located[-1][0].ttl if located else None
    # One marker per place; its label lists every TTL that landed there.
    places: dict[tuple[float, float], list[int]] = {}
    for hop, geo in located:
        places.setdefault((geo.lat, geo.lon), []).append(hop.ttl)
    for (lat, lon), ttls in places.items():
        x, y = m(lon, lat)
        final = last_ttl in ttls
        m.scatter(
            x,
            y,
            120 if final else 45,
            marker="*" if final else "o",
            color="#1a7f37" if final else "#d1242f",
            edgecolor="white",
            linewidth=0.6,
            zorder=5,
        )
        plt.annotate(
            ",".join(str(t) for t in ttls),
            (x, y),
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=8,
            fontweight="bold",
            color="#222",
            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.7),
        )

    if title:
        plt.title(title, fontsize=11)
    plt.tight_layout()
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=130)
    if show:
        plt.show()
    plt.close(fig)
