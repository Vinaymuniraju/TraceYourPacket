"""Submarine cable data and a simple router that lays a traceroute over it.

Data sources, in the order `load_cables(mode="auto")` tries them:

1. TeleGeography's public map data (https://www.submarinecablemap.com), fetched on your
   machine and cached. Their data is licensed CC BY-NC-SA 3.0 (check their terms before
   reusing it); it is therefore never bundled with this project.
2. A GeoJSON file you pass with --cables-file (same format).
3. A small hand-made set of *illustrative* corridors shipped with this project. These follow
   the general geography of the big cable routes but are not surveyed and carry no real
   cable names. They keep the map and the tests working offline.

The router answers: "if a packet had to get from hop A to hop B over fibre, which cables
and landing stations would it most plausibly use?" A traceroute does not reveal this, so
every path produced here is an inference and the map says so.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import logging
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("tracemap.cables")

ASSETS = Path(__file__).resolve().parent / "assets"
CABLE_URL = "https://www.submarinecablemap.com/api/v3/cable/cable-geo.json"
ATTRIBUTION_TG = "Cable data: TeleGeography, submarinecablemap.com (CC BY-NC-SA 3.0)"
ATTRIBUTION_ILLUSTRATIVE = (
    "Illustrative cable corridors: hand-placed and approximate, not real cable routes"
)
EARTH_R = 6371.0088
PALETTE = ["#22d3ee", "#e879f9", "#a3e635", "#fbbf24", "#fb923c", "#60a5fa", "#f472b6", "#34d399"]

LonLat = tuple[float, float]


@dataclass
class Cable:
    name: str
    color: str
    lines: list[list[LonLat]]


class CableDataError(Exception):
    """Cable data was required but could not be loaded."""


@dataclass
class CableSet:
    cables: list[Cable]
    source: str  # "telegeography", "file", "illustrative" or "none"
    attribution: str
    real: bool
    note: str = ""  # why this is not the first-choice data (fallback, stale cache), else ""


@dataclass
class Segment:
    kind: str  # "cable" or "land"
    name: Optional[str]
    coords: list[LonLat]
    km: float
    color: Optional[str] = None


@dataclass
class Leg:
    segments: list[Segment] = field(default_factory=list)

    @property
    def km(self) -> float:
        return sum(s.km for s in self.segments)

    @property
    def cable_km(self) -> float:
        return sum(s.km for s in self.segments if s.kind == "cable")

    @property
    def cables(self) -> list[str]:
        out: list[str] = []
        for s in self.segments:
            if s.kind == "cable" and s.name and s.name not in out:
                out.append(s.name)
        return out


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------
def hav_km(a: LonLat, b: LonLat) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(h)))


def path_km(coords: list[LonLat]) -> float:
    return sum(hav_km(p, q) for p, q in zip(coords, coords[1:]))


def _hav_matrix(lon1, lat1, lon2, lat2) -> np.ndarray:
    """Pairwise great-circle km between two sets of points (arrays in degrees)."""
    p1, p2 = np.radians(lat1)[:, None], np.radians(lat2)[None, :]
    dl = np.radians(lon2)[None, :] - np.radians(lon1)[:, None]
    dp = p2 - p1
    h = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def decimate(line: list[LonLat], min_km: float) -> list[LonLat]:
    """Drop vertices closer than min_km to the previous kept one (ends are kept)."""
    if len(line) <= 2:
        return line
    out = [line[0]]
    for p in line[1:-1]:
        if hav_km(out[-1], p) >= min_km:
            out.append(p)
    out.append(line[-1])
    return out


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def _color_for(name: str) -> str:
    return PALETTE[int(hashlib.md5(name.encode()).hexdigest(), 16) % len(PALETTE)]


def parse_geojson(data: dict) -> list[Cable]:
    """Accepts a FeatureCollection of LineString / MultiLineString features."""
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise ValueError("not a GeoJSON FeatureCollection")
    cables: list[Cable] = []
    for feat in data["features"]:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        if geom.get("type") == "LineString":
            raw = [geom.get("coordinates", [])]
        elif geom.get("type") == "MultiLineString":
            raw = geom.get("coordinates", [])
        else:
            continue
        lines = []
        try:
            for ln in raw:
                pts = [(float(p[0]), float(p[1])) for p in ln if len(p) >= 2]
                if len(pts) >= 2:
                    lines.append(pts)
        except (TypeError, ValueError):
            continue  # skip a malformed feature, keep the rest
        if not lines:
            continue
        name = str(props.get("name") or "Unnamed cable")
        color = str(props.get("color") or "")
        if not (color.startswith("#") and len(color) in (4, 7)):
            color = _color_for(name)
        cables.append(Cable(name, color, lines))
    return cables


def load_illustrative() -> list[Cable]:
    return parse_geojson(json.loads((ASSETS / "illustrative_corridors.geojson").read_text()))


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "tracemap"


MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024
MIN_REAL_CABLES = 20  # the real map has hundreds; far fewer means a wrong or truncated file


def _read_cache(cache: Path) -> Optional[list[Cable]]:
    try:
        cables = parse_geojson(json.loads(cache.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return cables if len(cables) >= MIN_REAL_CABLES else None


def _age_text(cache: Path) -> str:
    days = (time.time() - cache.stat().st_mtime) / 86400
    return "today" if days < 1 else f"{int(days)} days ago"


def fetch_telegeography(cache_dir: Optional[Path] = None, timeout: float = 20.0,
                        max_age_days: float = 14.0, force: bool = False,
                        offline: bool = False, opener=None) -> tuple[Optional[list[Cable]], str]:
    """Return (cables, note). cables is None when nothing usable exists.

    A cached copy younger than max_age_days is used without touching the network. Otherwise the
    data is downloaded, checked (size cap, valid JSON, plausible number of cables) and written to
    the cache atomically. If the download fails, an older cached copy is used and `note` says so.
    `opener` replaces urllib.request.urlopen (for tests).
    """
    opener = opener or urllib.request.urlopen
    cache = (cache_dir or default_cache_dir()) / "cable-geo.json"
    have = cache.exists()
    fresh = have and not force and (time.time() - cache.stat().st_mtime) < max_age_days * 86400
    reason = ""
    if not fresh and not offline:
        req = urllib.request.Request(CABLE_URL, headers={
            "User-Agent": "TraceYourPacket/2.0 (+https://github.com/Vinaymuniraju/TraceYourPacket)"})
        try:
            with opener(req, timeout=timeout) as resp:
                body = resp.read(MAX_DOWNLOAD_BYTES + 1)
            if len(body) > MAX_DOWNLOAD_BYTES:
                raise ValueError("response larger than %d MB" % (MAX_DOWNLOAD_BYTES // 2**20))
            cables = parse_geojson(json.loads(body))
            if len(cables) < MIN_REAL_CABLES:
                raise ValueError("only %d cables in the download, expected many more" % len(cables))
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp")
            tmp.write_bytes(body)
            os.replace(tmp, cache)  # a crash never leaves a half-written cache
            return cables, ""
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError, AttributeError) as exc:
            reason = f"download failed ({exc.__class__.__name__}: {exc})"
            log.warning("could not fetch cable data: %s", exc)
    cached = _read_cache(cache) if cache.exists() else None
    if cached:
        note = ""
        if reason:
            note = f"{reason}; using the copy cached {_age_text(cache)}"
        elif offline and not fresh:
            note = f"offline; using the copy cached {_age_text(cache)}"
        return cached, note
    if not reason:
        reason = "offline and no cached copy" if offline else "no usable cached copy"
    return None, reason


def load_cables(mode: str = "auto", path: Optional[Path] = None, offline: bool = False,
                cache_dir: Optional[Path] = None, refresh: bool = False,
                opener=None) -> CableSet:
    """mode: auto | telegeography | illustrative | none.

    `telegeography` raises CableDataError when real data is unavailable. `auto` falls back to the
    illustrative corridors and records why in CableSet.note.
    """
    if mode == "none":
        return CableSet([], "none", "", False)
    if path:
        try:
            cables = parse_geojson(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise CableDataError(f"cannot read cable file {path}: {exc}") from exc
        if not cables:
            raise CableDataError(f"{path} contains no LineString or MultiLineString cables")
        illustrative = all("Illustrative corridor" in c.name for c in cables)
        return CableSet(cables, "illustrative" if illustrative else "file",
                        ATTRIBUTION_ILLUSTRATIVE if illustrative else f"Cable data: {Path(path).name}",
                        not illustrative)
    note = ""
    if mode in ("auto", "telegeography"):
        got, why = fetch_telegeography(cache_dir, offline=offline, force=refresh, opener=opener)
        if got:
            return CableSet(got, "telegeography", ATTRIBUTION_TG, True, why)
        if mode == "telegeography":
            raise CableDataError(f"TeleGeography cable data unavailable: {why}")
        note = f"Real cable data unavailable ({why}); showing illustrative corridors"
    return CableSet(load_illustrative(), "illustrative", ATTRIBUTION_ILLUSTRATIVE, False, note)


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------
class CableGraph:
    """Landing stations as nodes, cables as edges, plus costly overland links.

    Overland fibre costs `land_cost` times its straight-line length, so long hauls prefer
    cables and short hops stay on land.
    """

    def __init__(self, cables: list[Cable], snap_km: float = 40.0, land_km: float = 700.0,
                 land_cost: float = 1.6, k_near: int = 6):
        self.land_cost = land_cost
        self.nodes: list[LonLat] = []
        self.adj: dict[int, list[tuple[int, float, Segment]]] = {}
        ends: list[tuple[LonLat, Cable, list[LonLat], int]] = []
        for cab in cables:
            for line in cab.lines:
                ends.append((line[0], cab, line, 0))
                ends.append((line[-1], cab, line, 1))
        if not ends:
            self.arr = np.zeros((0, 2))
            return

        pts = np.array([e[0] for e in ends])
        parent = list(range(len(ends)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        # Merge endpoints that sit within snap_km: they are the same landing station.
        for lo in range(0, len(ends), 400):
            blk = _hav_matrix(pts[lo:lo + 400, 0], pts[lo:lo + 400, 1], pts[:, 0], pts[:, 1])
            ii, jj = np.nonzero(blk <= snap_km)
            for i, j in zip(ii + lo, jj):
                if i < j:
                    parent[find(int(i))] = find(int(j))
        ids: dict[int, int] = {}
        node_of = []
        for i in range(len(ends)):
            r = find(i)
            if r not in ids:
                ids[r] = len(self.nodes)
                self.nodes.append(ends[r][0])
            node_of.append(ids[r])
        self.arr = np.array(self.nodes)
        self.adj = {i: [] for i in range(len(self.nodes))}

        for e in range(0, len(ends), 2):
            _, cab, line, _ = ends[e]
            a, b = node_of[e], node_of[e + 1]
            if a == b:
                continue
            km = path_km(line)
            fwd = Segment("cable", cab.name, line, km, cab.color)
            back = Segment("cable", cab.name, line[::-1], km, cab.color)
            self.adj[a].append((b, km, fwd))
            self.adj[b].append((a, km, back))

        # Overland links to the nearest few stations.
        n = len(self.nodes)
        seen: set[tuple[int, int]] = set()
        for lo in range(0, n, 400):
            blk = _hav_matrix(self.arr[lo:lo + 400, 0], self.arr[lo:lo + 400, 1],
                              self.arr[:, 0], self.arr[:, 1])
            for r in range(blk.shape[0]):
                i = lo + r
                blk[r, i] = np.inf
                order = np.argsort(blk[r])[:k_near]
                for j in order:
                    d = float(blk[r, j])
                    if d > land_km:
                        break
                    key = (min(i, int(j)), max(i, int(j)))
                    if key in seen:
                        continue
                    seen.add(key)
                    a, b = self.nodes[i], self.nodes[int(j)]
                    self.adj[i].append((int(j), d * land_cost, Segment("land", None, [a, b], d)))
                    self.adj[int(j)].append((i, d * land_cost, Segment("land", None, [b, a], d)))

    # ---- queries ----------------------------------------------------------
    def _near(self, p: LonLat, k: int, within_km: float) -> list[tuple[int, float]]:
        if len(self.nodes) == 0:
            return []
        d = _hav_matrix(np.array([p[0]]), np.array([p[1]]), self.arr[:, 0], self.arr[:, 1])[0]
        idx = np.argsort(d)[:k]
        return [(int(i), float(d[i])) for i in idx if d[i] <= within_km]

    def route(self, a: LonLat, b: LonLat, direct_km: float = 1200.0,
              entry_km: float = 2500.0) -> Leg:
        """Plausible fibre path from point a to point b (both lon, lat)."""
        straight = hav_km(a, b)
        direct = Leg([Segment("land", None, [a, b], straight)])
        if straight < direct_km or not self.nodes:
            return direct

        starts = self._near(a, 4, entry_km)
        ends = {i: d for i, d in self._near(b, 4, entry_km)}
        if not starts or not ends:
            return direct

        dist: dict[int, float] = {}
        prev: dict[int, tuple[int, Segment]] = {}
        heap: list[tuple[float, int]] = []
        for i, d in starts:
            c = d * self.land_cost
            if c < dist.get(i, math.inf):
                dist[i] = c
                prev.pop(i, None)
                heapq.heappush(heap, (c, i))
        best, best_node = math.inf, None
        while heap:
            c, u = heapq.heappop(heap)
            if c > dist.get(u, math.inf):
                continue
            if c >= best:
                break
            if u in ends:
                total = c + ends[u] * self.land_cost
                if total < best:
                    best, best_node = total, u
            for v, w, seg in self.adj[u]:
                nc = c + w
                if nc < dist.get(v, math.inf):
                    dist[v] = nc
                    prev[v] = (u, seg)
                    heapq.heappush(heap, (nc, v))

        if best_node is None or best >= straight * self.land_cost:
            return direct

        segs: list[Segment] = []
        node = best_node
        while node in prev:
            u, seg = prev[node]
            segs.append(seg)
            node = u
        segs.reverse()
        first = self.nodes[node]
        last = self.nodes[best_node]
        leg = Leg()
        if hav_km(a, first) > 1:
            leg.segments.append(Segment("land", None, [a, first], hav_km(a, first)))
        leg.segments += segs
        if hav_km(last, b) > 1:
            leg.segments.append(Segment("land", None, [last, b], hav_km(last, b)))
        return leg


def route_stations(graph: CableGraph, stations: list[LonLat]) -> list[Leg]:
    """Leg i joins station i-1 to station i (so the list is one shorter)."""
    return [graph.route(a, b) for a, b in zip(stations, stations[1:])]
