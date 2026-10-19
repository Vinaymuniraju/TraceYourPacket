"""Writes tracemap/assets/illustrative_corridors.geojson.

These are hand-placed, approximate waypoints that follow the general geography of the
world's main submarine-cable corridors. They are NOT surveyed routes and carry no real
cable names. They exist so the map and the routing code work offline and in tests.
Real routes come from TeleGeography data (see tracemap/cables.py).
"""
import json
from pathlib import Path

PALETTE = ["#22d3ee", "#e879f9", "#a3e635", "#fbbf24", "#fb923c", "#60a5fa", "#f472b6", "#34d399"]

# Each entry: label, list of lines; a line is a list of [lon, lat]. Lines that cross the
# date line are split at +-180, the way real cable data is.
CORRIDORS = [
    ("Arabian Sea to Red Sea", [[[72.88,19.08],[66,16.5],[58,13.5],[51,12.3],[44.5,12.0],[43.15,11.6],[42.7,13.2],[41,16],[38.5,20.5],[36,25],[33.5,28.2],[32.65,29.1]]]),
    ("Eastern Mediterranean to Marseille", [[[29.9,31.2],[26,33.8],[20,35.2],[15,36.0],[11,37.6],[8.8,38.5],[7.0,39.3],[5.8,41.5],[5.37,43.3]]]),
    ("Mumbai to Gulf", [[[72.88,19.08],[65,21],[58,23.5],[56.33,25.12]]]),
    ("Gulf to Gulf of Aden", [[[56.33,25.12],[59,22.5],[57,19],[54.1,17.0],[51,13.5],[45,12.3],[43.15,11.6]]]),
    ("Bay of Bengal to Malacca Strait", [[[80.27,13.08],[84,9],[90,6.5],[95.3,5.8],[98,5.3],[100,4],[101.5,2.8],[103,1.6],[103.85,1.30]]]),
    ("India west coast", [[[72.88,19.08],[72.4,14],[74.5,10.5],[76.27,9.93]]]),
    ("Kochi to Colombo", [[[76.27,9.93],[77.2,8],[79.85,6.93]]]),
    ("Colombo to Chennai", [[[79.85,6.93],[81.2,9],[80.27,13.08]]]),
    ("Colombo to Malacca Strait", [[[79.85,6.93],[88,5],[96,5.6],[98,5.3]]]),
    ("South China Sea", [[[103.85,1.30],[106,3.5],[109,7],[111,13],[113.5,19],[114.17,22.32]]]),
    ("Luzon Strait", [[[120.98,14.6],[118,17],[114.17,22.32]]]),
    ("East China Sea to Japan", [[[114.17,22.32],[118,23.2],[121.8,24.85],[126,28],[131,31],[135,33.2],[139.95,34.95]]]),
    ("North Pacific", [[[139.95,34.95],[150,37],[165,40],[180,41.5]], [[-180,41.5],[-165,41.8],[-150,40],[-135,38.5],[-122.5,37.7]]]),
    ("Central Pacific", [[[139.95,34.95],[141,28],[144.8,13.45]], [[144.8,13.45],[160,16],[180,18.5]], [[-180,18.5],[-165,20],[-157.86,21.3]], [[-157.86,21.3],[-145,25],[-135,30],[-125,33.5],[-118.4,33.9]]]),
    ("Java Sea to Western Australia", [[[103.85,1.30],[105.5,-3.5],[106.85,-6.2],[108,-12],[110,-20],[114,-28],[115.86,-31.95]]]),
    ("Southern Australia", [[[115.86,-31.95],[114.5,-35],[120,-36],[130,-36.5],[140,-38.6],[143,-39.6],[148,-38.5],[151.2,-33.87]]]),
    ("Tasman Sea", [[[151.2,-33.87],[160,-35],[170,-36.5],[174.76,-36.85]]]),
    ("South Pacific", [[[174.76,-36.85],[180,-33]], [[-180,-33],[-172,-20],[-165,-5],[-160,10],[-157.86,21.3]]]),
    ("North Atlantic (UK to New Jersey)", [[[-4.55,50.83],[-15,49.5],[-30,48],[-45,45.5],[-58,42.5],[-67,40.5],[-74.0,40.3]]]),
    ("North Atlantic (Iberia to Virginia)", [[[-2.98,43.38],[-12,44.5],[-30,43.5],[-50,40.5],[-65,37.5],[-75.97,36.85]]]),
    ("English Channel", [[[1.35,51.1],[1.6,51.0],[1.85,50.95]]]),
    ("North Sea", [[[1.7,52.7],[3.5,52.5],[4.6,52.45]]]),
    ("Iberia to Marseille", [[[-9.14,38.7],[-9.5,36.0],[-5.9,35.9],[-2,36.5],[2,38.3],[5.37,43.3]]]),
    ("Iberia to West Africa", [[[-9.14,38.7],[-13,30],[-17.5,20],[-17.45,14.7]]]),
    ("Gulf of Guinea", [[[-17.45,14.7],[-16,9],[-10,4.5],[-3,3.8],[3.4,6.45]]]),
    ("Atlantic coast of Africa", [[[3.4,6.45],[5,0],[9,-5],[13.2,-8.8],[13.5,-17],[15,-26],[18.4,-33.9]]]),
    ("Southern Africa to East Africa", [[[18.4,-33.9],[28,-35.5],[36,-27],[41,-15],[40.5,-8],[39.67,-4.05]]]),
    ("East Africa to India", [[[39.67,-4.05],[50,-2],[62,6],[70,14],[72.88,19.08]]]),
    ("East Africa to Gulf of Aden", [[[39.67,-4.05],[43,2],[46,8],[43.15,11.6]]]),
    ("South Atlantic (Africa to Brazil)", [[[3.4,6.45],[-10,3],[-25,0],[-38.5,-3.7]]]),
    ("South Atlantic (south)", [[[18.4,-33.9],[0,-33],[-20,-30],[-42,-23.5]]]),
    ("Brazil coast", [[[-43.2,-22.9],[-38,-15],[-34,-8],[-38.5,-3.7]]]),
    ("Caribbean to Florida", [[[-38.5,-3.7],[-45,2],[-55,8],[-62,14],[-66.1,18.4],[-74,22.5],[-80.1,25.8]]]),
    ("US East coast", [[[-80.1,25.8],[-78,30],[-75,35],[-75.97,36.85],[-73.5,38.5],[-74.0,40.3]]]),
    ("Southern Indian Ocean", [[[18.4,-33.9],[45,-37],[80,-34],[115.86,-31.95]]]),
]

features = []
for i, (label, lines) in enumerate(CORRIDORS):
    features.append({
        "type": "Feature",
        "properties": {"name": f"Illustrative corridor: {label} (approximate)",
                       "color": PALETTE[i % len(PALETTE)], "illustrative": True},
        "geometry": {"type": "MultiLineString", "coordinates": lines},
    })
out = Path(__file__).resolve().parent.parent / "tracemap" / "assets" / "illustrative_corridors.geojson"
out.write_text(json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")))
print(len(features), "corridors ->", out, out.stat().st_size, "bytes")
