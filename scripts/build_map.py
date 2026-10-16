"""Build the Europe 1500 map asset from Natural Earth data.

Real administrative regions (Natural Earth 1:10m admin-1, public domain) are merged into the 69
game provinces; land that belongs to no province becomes wasteland. The result is
projected (Lambert azimuthal equal-area, centred on Europe), simplified as a coverage so that
neighbours keep sharing exactly the same border, and written as SVG path data.

    make map    # downloads the Natural Earth inputs once (~48 MB) and runs this script

The output, `src/pax_agentica/data/europe_1500.json`, is committed, so the game never needs
the input data or shapely. Run this only to change the map.
"""

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import shapely
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box, shape
from shapely.ops import polylabel, unary_union

from pax_agentica.engine.scenario import europe_map

OUT = Path(__file__).resolve().parents[1] / "src/pax_agentica/data/europe_1500.json"

FRAME = box(-30.0, 20.0, 70.0, 75.0)  # lon/lat data window, wider than what is shown
LON0, LAT0 = 15.0, 52.0  # projection centre
WIDTH = 2000.0  # SVG units across
SIMPLIFY = 1.0  # coverage simplification tolerance, in SVG units
RIVER_RANK = 7  # Natural Earth scalerank: keep rivers up to this rank (1 = greatest)

# Seas and oceans to letter on the map: name, lon, lat, size (1 ocean, 2 sea, 3 strait), angle.
SEAS: list[tuple[str, float, float, int, float]] = [
    ("Atlantic Ocean", -12.0, 49.0, 1, -8),
    ("North Sea", 3.4, 56.2, 2, 0),
    ("Norwegian Sea", 2.0, 66.0, 2, 0),
    ("Baltic Sea", 18.6, 56.4, 2, -55),
    ("Gulf of Bothnia", 20.4, 62.6, 3, -62),
    ("Bay of Biscay", -5.5, 45.6, 2, 0),
    ("English Channel", -2.9, 50.0, 3, -12),
    ("Irish Sea", -5.0, 53.7, 3, -60),
    ("Mediterranean Sea", 4.5, 38.6, 2, 0),
    ("Tyrrhenian Sea", 11.9, 40.2, 3, -40),
    ("Adriatic Sea", 15.6, 42.9, 3, -38),
    ("Ionian Sea", 18.6, 37.2, 3, 0),
    ("Aegean Sea", 25.0, 38.6, 3, -70),
    ("Black Sea", 34.0, 43.4, 2, 0),
    ("Caspian Sea", 50.6, 42.6, 3, -70),
    ("White Sea", 37.3, 65.6, 3, 0),
    ("Barents Sea", 40.0, 70.4, 2, 0),
]
WASTE = "_wasteland"

# Which game provinces may claim the regions of each country (ISO 3166 alpha-3), and how far
# (km) a region's centre may lie from the province seat. Farther regions become wasteland.
COUNTRIES: dict[str, tuple[tuple[str, ...], float]] = {
    "GBR": (("london", "york", "wales", "scotland", "ireland"), 600),
    "IRL": (("ireland",), 600),
    "IMN": (("york",), 600),
    "JEY": (("normandy",), 300),
    "GGY": (("normandy",), 300),
    "PRT": (("lisbon",), 600),
    "ESP": (("galicia", "madrid", "seville", "andalusia", "valencia", "aragon", "navarre"), 700),
    "AND": (("aragon",), 300),
    "GIB": (("seville",), 300),
    "FRA": (
        (
            "paris",
            "normandy",
            "brittany",
            "champagne",
            "lyon",
            "gascony",
            "languedoc",
            "provence",
            "flanders",
            "rhineland",
        ),
        700,
    ),
    "MCO": (("provence",), 300),
    "BEL": (("flanders",), 300),
    "LUX": (("flanders", "rhineland"), 300),
    "NLD": (("holland",), 400),
    "DEU": (("rhineland", "hamburg", "brandenburg", "saxony", "bavaria"), 600),
    "CHE": (("switzerland",), 400),
    "LIE": (("switzerland",), 300),
    "AUT": (("vienna", "tyrol", "styria"), 400),
    "CZE": (("bohemia",), 500),
    "SVK": (("buda",), 500),
    "HUN": (("buda",), 500),
    "SVN": (("styria",), 300),
    "HRV": (("styria", "bosnia", "buda"), 500),
    "BIH": (("bosnia",), 400),
    "MNE": (("bosnia",), 400),
    "SRB": (("serbia",), 400),
    "KOS": (("serbia",), 400),
    "MKD": (("serbia", "bulgaria", "greece"), 400),
    "ALB": (("greece", "bosnia", "serbia"), 500),
    "GRC": (("greece", "constantinople"), 700),
    "BGR": (("bulgaria",), 400),
    "TUR": (("constantinople", "anatolia"), 420),
    "ROU": (("transylvania", "wallachia"), 450),
    "MDA": (("wallachia",), 450),
    "ITA": (("milan", "venice", "florence", "rome", "naples", "sicily", "tyrol"), 600),
    "SMR": (("florence",), 300),
    "VAT": (("rome",), 300),
    "MLT": (("sicily",), 300),
    "POL": (("krakow", "masovia", "prussia", "brandenburg", "bohemia"), 500),
    "LTU": (("lithuania",), 400),
    "LVA": (("livonia",), 400),
    "EST": (("livonia",), 400),
    "BLR": (("lithuania", "smolensk", "kiev"), 500),
    "UKR": (("kiev", "krakow", "buda", "wallachia"), 380),
    "RUS": (("novgorod", "moscow", "smolensk", "ryazan", "prussia"), 430),
    "FIN": (("finland",), 900),
    "ALD": (("finland",), 300),
    "SWE": (("stockholm", "gotaland", "norrland", "scania"), 900),
    "NOR": (("norway",), 1200),
    "DNK": (("zealand", "jutland"), 300),
    "MAR": (("morocco",), 380),
    "ESB": (("morocco",), 300),  # Ceuta
    "DZA": (("algiers", "tunis", "morocco"), 460),
    "TUN": (("tunis",), 330),
}

# Regions that history (not distance) assigns. Keys: (country, admin-1 name) or
# (country, "region:" + Natural Earth region). None means wasteland.
OVERRIDES: dict[tuple[str, str], str | None] = {
    # France
    ("FRA", "region:Bretagne"): "brittany",
    ("FRA", "region:Pays de la Loire"): "brittany",
    ("FRA", "region:Normandie"): "normandy",
    ("FRA", "region:Île-de-France"): "paris",
    ("FRA", "region:Centre-Val de Loire"): "paris",
    ("FRA", "region:Grand Est"): "champagne",
    ("FRA", "region:Bourgogne-Franche-Comté"): "lyon",
    ("FRA", "region:Auvergne-Rhône-Alpes"): "lyon",
    ("FRA", "region:Nouvelle-Aquitaine"): "gascony",
    ("FRA", "region:Occitanie"): "languedoc",
    ("FRA", "region:Provence-Alpes-Côte-d'Azur"): "provence",
    ("FRA", "region:Corse"): None,
    ("FRA", "Nord"): "flanders",
    ("FRA", "Pas-de-Calais"): "flanders",
    ("FRA", "Bas-Rhin"): "rhineland",
    ("FRA", "Haut-Rhin"): "rhineland",
    # Britain
    ("GBR", "region:Northern Ireland"): "ireland",
    ("GBR", "region:Greater London"): "london",
    ("GBR", "region:South East"): "london",
    ("GBR", "region:South West"): "london",
    ("GBR", "region:East"): "london",
    ("GBR", "region:West Wales and the Valleys"): "wales",
    ("GBR", "region:East Wales"): "wales",
    ("GBR", "region:North East"): "york",
    ("GBR", "region:North West"): "york",
    ("GBR", "region:Yorkshire and the Humber"): "york",
    ("GBR", "region:Highlands and Islands"): "scotland",
    ("GBR", "region:North Eastern"): "scotland",
    ("GBR", "region:South Western"): "scotland",
    ("GBR", "region:Eastern"): "scotland",
    # Iberia
    ("ESP", "region:Galicia"): "galicia",
    ("ESP", "region:Asturias"): "galicia",
    ("ESP", "region:Cantabria"): "navarre",
    ("ESP", "region:País Vasco"): "navarre",
    ("ESP", "region:Foral de Navarra"): "navarre",
    ("ESP", "region:La Rioja"): "navarre",
    ("ESP", "region:Castilla y León"): "madrid",
    ("ESP", "region:Madrid"): "madrid",
    ("ESP", "region:Castilla-La Mancha"): "madrid",
    ("ESP", "region:Aragón"): "aragon",
    ("ESP", "region:Cataluña"): "aragon",
    ("ESP", "region:Valenciana"): "valencia",
    ("ESP", "region:Murcia"): "valencia",
    ("ESP", "region:Islas Baleares"): "valencia",
    ("ESP", "region:Andalucía"): "andalusia",  # the old kingdom of Granada
    ("ESP", "Sevilla"): "seville",  # the Guadalquivir, Cádiz and the road to the Indies
    ("ESP", "Huelva"): "seville",
    ("ESP", "Cádiz"): "seville",
    ("ESP", "Córdoba"): "seville",
    ("ESP", "region:Extremadura"): "seville",
    ("ESP", "region:Melilla"): "morocco",
    # Italy
    ("ITA", "region:Piemonte"): "milan",
    ("ITA", "region:Valle d'Aosta"): "milan",
    ("ITA", "region:Liguria"): "milan",
    ("ITA", "region:Lombardia"): "milan",
    ("ITA", "region:Trentino-Alto Adige"): "tyrol",
    ("ITA", "region:Veneto"): "venice",
    ("ITA", "region:Friuli-Venezia Giulia"): "venice",
    ("ITA", "region:Toscana"): "florence",
    ("ITA", "region:Emilia-Romagna"): "florence",
    ("ITA", "region:Umbria"): "rome",
    ("ITA", "region:Lazio"): "rome",
    ("ITA", "region:Marche"): "rome",
    ("ITA", "region:Abruzzo"): "naples",
    ("ITA", "region:Molise"): "naples",
    ("ITA", "region:Campania"): "naples",
    ("ITA", "region:Apulia"): "naples",
    ("ITA", "region:Basilicata"): "naples",
    ("ITA", "region:Calabria"): "naples",
    ("ITA", "region:Sicily"): "sicily",
    ("ITA", "region:Sardegna"): None,
    # The Empire
    ("DEU", "Schleswig-Holstein"): "hamburg",
    ("DEU", "Hamburg"): "hamburg",
    ("DEU", "Bremen"): "hamburg",
    ("DEU", "Niedersachsen"): "hamburg",
    ("DEU", "Mecklenburg-Vorpommern"): "brandenburg",
    ("DEU", "Berlin"): "brandenburg",
    ("DEU", "Brandenburg"): "brandenburg",
    ("DEU", "Sachsen"): "saxony",
    ("DEU", "Sachsen-Anhalt"): "saxony",
    ("DEU", "Thüringen"): "saxony",
    ("DEU", "Bayern"): "bavaria",
    ("DEU", "Baden-Württemberg"): "bavaria",
    ("DEU", "Nordrhein-Westfalen"): "rhineland",
    ("DEU", "Rheinland-Pfalz"): "rhineland",
    ("DEU", "Saarland"): "rhineland",
    ("DEU", "Hessen"): "rhineland",
    # Austria
    ("AUT", "Wien"): "vienna",
    ("AUT", "Niederösterreich"): "vienna",
    ("AUT", "Oberösterreich"): "vienna",
    ("AUT", "Burgenland"): "vienna",
    ("AUT", "Tirol"): "tyrol",
    ("AUT", "Vorarlberg"): "tyrol",
    ("AUT", "Salzburg"): "tyrol",
    ("AUT", "Steiermark"): "styria",
    ("AUT", "Kärnten"): "styria",
    # Poland and Prussia
    ("POL", "Pomeranian"): "prussia",
    ("POL", "Warmian-Masurian"): "prussia",
    ("POL", "Kuyavian-Pomeranian"): "prussia",
    ("POL", "West Pomeranian"): "brandenburg",
    ("POL", "Lubusz"): "brandenburg",
    ("POL", "Lower Silesian"): "bohemia",
    ("POL", "Opole"): "bohemia",
    ("POL", "Greater Poland"): "masovia",
    ("POL", "Łódź"): "masovia",
    ("POL", "Masovian"): "masovia",
    ("POL", "Podlachian"): "masovia",
    ("POL", "Lublin"): "masovia",
    ("POL", "Silesian"): "krakow",
    ("POL", "Lesser Poland"): "krakow",
    ("POL", "Subcarpathian"): "krakow",
    ("POL", "Świętokrzyskie"): "krakow",
    ("RUS", "Kaliningrad"): "prussia",
    # Russia and its neighbours
    ("RUS", "Pskov"): "novgorod",
    ("RUS", "Novgorod"): "novgorod",
    ("RUS", "Leningrad"): "novgorod",
    ("RUS", "City of St. Petersburg"): "novgorod",
    ("RUS", "Tver'"): "moscow",
    ("RUS", "Smolensk"): "smolensk",
    ("RUS", "Bryansk"): "smolensk",
    ("RUS", "Kaluga"): "smolensk",
    ("RUS", "Moskva"): "moscow",
    ("RUS", "Moskovskaya"): "moscow",
    ("RUS", "Vladimir"): "moscow",
    ("RUS", "Yaroslavl'"): "moscow",
    ("RUS", "Ivanovo"): "moscow",
    ("RUS", "Tula"): "ryazan",
    ("RUS", "Ryazan'"): "ryazan",
    ("RUS", "Lipetsk"): "ryazan",
    ("RUS", "Orel"): "ryazan",
    ("RUS", "Tambov"): "ryazan",
    ("UKR", "L'viv"): "krakow",
    ("UKR", "Transcarpathia"): "buda",
    ("UKR", "Chernivtsi"): "wallachia",
    ("UKR", "Crimea"): None,
    # Scandinavia
    ("SWE", "Skåne"): "scania",
    ("SWE", "Blekinge"): "scania",
    ("SWE", "Halland"): "scania",
    ("SWE", "Stockholm"): "stockholm",
    ("SWE", "Uppsala"): "stockholm",
    ("SWE", "Södermanland"): "stockholm",
    ("SWE", "Västmanland"): "stockholm",
    ("SWE", "Orebro"): "stockholm",
    ("SWE", "Gotland"): "stockholm",
    ("SWE", "Östergötland"): "stockholm",
    ("SWE", "Dalarna"): "norrland",
    ("SWE", "Gävleborg"): "norrland",
    ("SWE", "Jämtland"): "norrland",
    ("SWE", "Västernorrland"): "norrland",
    ("SWE", "Västerbotten"): "norrland",
    ("SWE", "Norrbotten"): "norrland",
    ("SWE", "Västra Götaland"): "gotaland",
    ("SWE", "Värmland"): "gotaland",
    ("SWE", "Jönköping"): "gotaland",
    ("SWE", "Kronoberg"): "gotaland",
    ("SWE", "Kalmar"): "gotaland",
    ("DNK", "Hovedstaden"): "zealand",
    ("DNK", "Sjælland"): "zealand",
    ("DNK", "Syddanmark"): "jutland",
    ("DNK", "Midtjylland"): "jutland",
    ("DNK", "Nordjylland"): "jutland",
    # The Balkans and Anatolia
    ("GRC", "Anatoliki Makedonia kai Thraki"): "constantinople",
    ("GRC", "Kriti"): "greece",
    ("TUR", "Istanbul"): "constantinople",
    ("TUR", "Edirne"): "constantinople",
    ("TUR", "Kirklareli"): "constantinople",
    ("TUR", "Tekirdag"): "constantinople",
}


def project(lon: float, lat: float) -> tuple[float, float]:
    """Spherical Lambert azimuthal equal-area, in km."""
    r = 6371.0
    lam, phi = math.radians(lon - LON0), math.radians(lat)
    phi0 = math.radians(LAT0)
    k = math.sqrt(
        2 / (1 + math.sin(phi0) * math.sin(phi) + math.cos(phi0) * math.cos(phi) * math.cos(lam))
    )
    x = r * k * math.cos(phi) * math.sin(lam)
    y = r * k * (math.cos(phi0) * math.sin(phi) - math.sin(phi0) * math.cos(phi) * math.cos(lam))
    return x, -y


def projected(geom):  # type: ignore[no-untyped-def]
    return shapely.transform(geom, lambda pts: [list(project(lon, lat)) for lon, lat in pts])


def areal(geom):  # type: ignore[no-untyped-def]
    """Only the polygons of a geometry (repairs can leave stray lines and points)."""
    parts = shapely.get_parts(shapely.make_valid(geom))
    polygons = [g for p in parts for g in shapely.get_parts(p) if isinstance(g, Polygon)]
    return MultiPolygon(polygons) if len(polygons) != 1 else polygons[0]


def assign(
    country: str,
    name: str,
    region: str | None,
    centre: tuple[float, float],
    seats: dict[str, tuple[float, float]],
) -> str:
    for key in ((country, name), (country, f"region:{region}")):
        if key in OVERRIDES:
            return OVERRIDES[key] or WASTE
    if country not in COUNTRIES:
        return WASTE
    candidates, limit = COUNTRIES[country]
    best = min(candidates, key=lambda p: math.dist(centre, seats[p]))
    return best if math.dist(centre, seats[best]) <= limit else WASTE


def svg_path(geom, scale: float, ox: float, oy: float) -> str:  # type: ignore[no-untyped-def]
    def ring(coords) -> str:  # type: ignore[no-untyped-def]
        pts = [f"{(x - ox) * scale:.1f},{(y - oy) * scale:.1f}" for x, y in coords[:-1]]
        return "M" + "L".join(pts) + "Z"

    polygons = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    parts = []
    for poly in polygons:
        if isinstance(poly, Polygon) and not poly.is_empty:
            parts.append(ring(poly.exterior.coords))
            parts.extend(ring(i.coords) for i in poly.interiors)
    return "".join(parts)


def line_path(geom, scale: float, ox: float, oy: float) -> str:  # type: ignore[no-untyped-def]
    lines = shapely.line_merge(geom) if not isinstance(geom, LineString) else geom
    items = lines.geoms if isinstance(lines, MultiLineString) else [lines]
    out = []
    for line in items:
        if isinstance(line, LineString) and len(line.coords) > 1:
            pts = [f"{(x - ox) * scale:.1f},{(y - oy) * scale:.1f}" for x, y in line.coords]
            out.append("M" + "L".join(pts))
    return "".join(out)


def rivers(source: Path, view, scale: float, ox: float, oy: float) -> list[list[object]]:  # type: ignore[no-untyped-def]
    """Major rivers as [path, rank], rank 1 (great) to 3 (minor), for stroke widths."""
    out: list[list[object]] = []
    for feature in json.loads(source.read_text())["features"]:
        rank = feature["properties"].get("scalerank") or 99
        if rank > RIVER_RANK or feature["properties"].get("featurecla") != "River":
            continue
        geom = shape(feature["geometry"])
        if not geom.intersects(FRAME):
            continue
        line = projected(geom.intersection(FRAME)).intersection(view)
        line = line.simplify(SIMPLIFY / scale)
        if line.is_empty or line.length * scale < 12:
            continue
        d = line_path(line, scale, ox, oy)
        if d:
            out.append([d, 1 if rank <= 4 else 2 if rank <= 6 else 3])
    return out


def main(source: Path, river_source: Path | None = None) -> None:
    game_map = europe_map()
    seats = {pid: project(p.lon, p.lat) for pid, p in game_map.provinces.items()}

    groups: dict[str, list] = defaultdict(list)  # type: ignore[type-arg]
    for feature in json.loads(source.read_text())["features"]:
        geom = shape(feature["geometry"])
        if not geom.intersects(FRAME):
            continue
        geom = geom.intersection(FRAME).buffer(0)
        if geom.is_empty:
            continue
        props = feature["properties"]
        country = props["adm0_a3"]
        lon, lat = props.get("longitude"), props.get("latitude")
        if lon is None or lat is None:
            point = geom.representative_point()
            lon, lat = point.x, point.y
        owner = assign(country, props["name"] or "", props.get("region"), project(lon, lat), seats)
        groups[owner].append(areal(projected(geom)).buffer(0))

    missing = set(game_map.provinces) - set(groups)
    if missing:
        raise SystemExit(f"provinces without land: {sorted(missing)}")

    # What is shown: a rectangle in projected space, from Iceland to the Urals, Lapland to Africa.
    west = min(project(-22.0, 58.0)[0], project(-10.0, 36.0)[0])
    east = project(56.0, 52.0)[0]
    north = min(project(lon, 71.3)[1] for lon in (5.0, 15.0, 27.0))
    south = project(15.0, 31.0)[1]
    view = box(west, north, east, south)

    ids = sorted(groups)
    merged = [areal(unary_union(groups[i]).intersection(view)) for i in ids]
    minx, miny, maxx, maxy = view.bounds
    scale = WIDTH / (maxx - minx)
    simple = [areal(g) for g in shapely.coverage_simplify(merged, SIMPLIFY / scale)]
    shapes = dict(zip(ids, simple, strict=True))

    provinces = {}
    for pid in game_map.provinces:
        geom = shapes[pid]
        if geom.is_empty:
            raise SystemExit(f"{pid} vanished: merged area {merged[ids.index(pid)].area:.0f}")
        biggest = max(geom.geoms, key=lambda g: g.area) if isinstance(geom, MultiPolygon) else geom
        label = polylabel(biggest, tolerance=1.0)
        provinces[pid] = {
            "d": svg_path(geom, scale, minx, miny),
            "x": round((label.x - minx) * scale, 1),
            "y": round((label.y - miny) * scale, 1),
            "area": round(geom.area * scale * scale),
        }

    borders = []
    geographic: set[tuple[str, str]] = set()
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if not shapes[a].intersects(shapes[b]):
                continue
            shared = shapes[a].boundary.intersection(shapes[b].boundary)
            if shared.length * scale < 4:  # a corner, not a border
                continue
            borders.append([a, b, line_path(shared, scale, minx, miny)])
            if WASTE not in (a, b) and b not in game_map.provinces[a].sea_neighbors:
                geographic.add((a, b))

    land = unary_union(simple)
    seas = [
        {
            "name": name,
            "x": round((project(lon, lat)[0] - minx) * scale, 1),
            "y": round((project(lon, lat)[1] - miny) * scale, 1),
            "size": size,
            "angle": angle,
        }
        for name, lon, lat, size, angle in SEAS
    ]
    data = {
        "source": "Natural Earth 1:10m admin-1 (public domain), merged into game provinces",
        "width": round((maxx - minx) * scale),
        "height": round((maxy - miny) * scale),
        "provinces": provinces,
        "wasteland": svg_path(shapes[WASTE], scale, minx, miny),
        "coast": line_path(land.boundary.difference(view.exterior.buffer(1e-6)), scale, minx, miny),
        "borders": borders,
        "rivers": rivers(river_source, view, scale, minx, miny) if river_source else [],
        "seas": seas,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KiB)")

    game = {tuple(sorted((a, b))) for a, p in game_map.provinces.items() for b in p.neighbors}
    print("borders on the map but not in the game:", sorted(geographic - game))
    print("borders in the game but not on the map:", sorted(game - geographic))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None)
