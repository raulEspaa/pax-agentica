"""Build the chart of the New World from the Natural Earth data the map is built from.

The world's coasts from Natural Earth 1:10m admin-1 (public domain, already downloaded by
`make map`) are dissolved, simplified hard and projected plate carrée onto a chart from the
Pacific coast of the Americas to the Spice Islands, with each region beyond the sea, the ports
of Europe the fleets sail from, and the sea roads between them.

    make chart

The output, `src/pax_agentica/data/atlantic_chart.json`, is committed: the game never needs
the input data or shapely.
"""

import json
import sys
from pathlib import Path

import shapely
from shapely.geometry import MultiPolygon, Polygon, box, shape

OUT = Path(__file__).resolve().parents[1] / "src/pax_agentica/data/atlantic_chart.json"

WEST, EAST, SOUTH, NORTH = -128.0, 142.0, -46.0, 66.0  # the chart's window, in degrees
WIDTH = 1200.0  # SVG units across
SIMPLIFY = 0.35  # degrees
MIN_AREA = 1.5  # square degrees: smaller islands are left out (the Antilles are kept below)
KEEP = box(-86, 10, -60, 24)  # the Caribbean: every island counts there

# where each region's colonies lie on the chart (lon, lat), and where its name goes
REGIONS = {
    "north_america": (-70.0, 44.0),
    "caribbean": (-72.0, 19.5),
    "new_spain": (-101.0, 21.0),
    "peru": (-73.0, -12.0),
    "brazil": (-40.0, -9.0),
    "guinea": (-3.0, 6.0),
    "east_indies": (122.0, -2.0),
}
HOME = (-6.0, 37.4)  # Seville and the ports of the Atlantic coast
# the sea roads: waypoints from home (the trade winds, round the Cape)
ROUTES = {
    "north_america": [(-20.0, 46.0), (-45.0, 46.0)],
    "caribbean": [(-16.0, 28.0), (-40.0, 20.0), (-60.0, 17.0)],
    "new_spain": [(-16.0, 28.0), (-45.0, 20.0), (-70.0, 22.0), (-90.0, 22.0)],
    "peru": [(-16.0, 28.0), (-45.0, 15.0), (-78.0, 9.5), (-83.0, 0.0), (-79.0, -10.0)],
    "brazil": [(-18.0, 20.0), (-28.0, 0.0), (-34.0, -8.0)],
    "guinea": [(-16.0, 25.0), (-18.0, 10.0), (-8.0, 4.0)],
    "east_indies": [(-18.0, 20.0), (-12.0, -10.0), (10.0, -36.0), (30.0, -37.0), (55.0, -20.0),
                    (75.0, -5.0), (95.0, 3.0), (108.0, 0.0)],
}  # fmt: skip


def xy(lon: float, lat: float) -> tuple[float, float]:
    scale = WIDTH / (EAST - WEST)
    return round((lon - WEST) * scale, 1), round((NORTH - lat) * scale, 1)


def ring(coords: list[tuple[float, float]]) -> str:
    pts = [xy(x, y) for x, y in coords]
    return "M" + "L".join(f"{x:g},{y:g}" for x, y in pts) + "Z"


def main(admin1: str) -> None:
    frame = box(WEST, SOUTH, EAST, NORTH)
    shapes = []
    for f in json.loads(Path(admin1).read_text())["features"]:
        geom = shape(f["geometry"])
        if geom.intersects(frame):
            shapes.append(geom.buffer(0).simplify(0.05))
    # a hair's buffer closes the seams between provinces the simplification opened
    land = shapely.unary_union(shapes).buffer(0.08).buffer(-0.08)
    land = land.intersection(frame).simplify(SIMPLIFY)
    polys = list(land.geoms) if isinstance(land, MultiPolygon) else [land]
    shells = [(p, Polygon(p.exterior)) for p in polys if isinstance(p, Polygon)]
    paths = []
    for p in polys:
        if not isinstance(p, Polygon) or (p.area < MIN_AREA and not p.intersects(KEEP)):
            continue
        if any(p.within(shell) for q, shell in shells if q is not p and q.area > p.area):
            continue  # a sliver left inside a continent
        paths.append(ring(list(p.exterior.coords)))
    height = round((NORTH - SOUTH) * WIDTH / (EAST - WEST), 1)
    out = {
        "width": WIDTH,
        "height": height,
        "land": "".join(paths),
        "home": xy(*HOME),
        "regions": {r: xy(*ll) for r, ll in REGIONS.items()},
        "routes": {
            r: [xy(*HOME), *(xy(*w) for w in way), xy(*REGIONS[r])] for r, way in ROUTES.items()
        },
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"{OUT.name}: {len(paths)} coasts, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(sys.argv[1])
