"""Build the Europe 1500 map asset from Natural Earth data.

Real administrative regions (Natural Earth 1:10m admin-1, public domain) are merged into the 70
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

# The sea zones fleets sail: id, name, and seed points (lon, lat). The water is cut among the
# zones by the nearest seed (a Voronoi diagram), so the seeds shape the borders between them.
# Seeds of None are water no fleet sails (the Caspian).
ZONES: list[tuple[str | None, str, list[tuple[float, float]]]] = [
    ("atlantic", "Atlantic Ocean",
     [(-20, 55), (-15, 48), (-14, 40), (-12, 34), (-25, 62), (-14, 60), (-11, 44), (-10, 37.5),
      (-8, 34.5), (-7.5, 36.4)]),
    ("biscay", "Bay of Biscay", [(-5, 46), (-3, 44.6), (-7, 45), (-2, 45.7)]),
    ("channel", "English Channel", [(-2.5, 50.1), (0.5, 50.3), (-4.5, 49.7), (1.5, 50.8)]),
    ("irish_sea", "Irish Sea", [(-5, 53.7), (-4.9, 52.2), (-5.6, 55)]),
    ("north_sea", "North Sea", [(3, 56), (2.5, 53.5), (6, 58), (1, 58.5), (4, 54), (9, 58)]),
    ("norwegian_sea", "Norwegian Sea", [(2, 66), (10, 69), (30, 72), (37, 66), (0, 62), (20, 71)]),
    ("baltic", "Baltic Sea",
     [(18, 56), (15, 55), (20, 58), (23, 59.6), (12.5, 54.6), (11.5, 57), (12.6, 55.6)]),
    ("bothnia", "Gulf of Bothnia", [(20, 62.5), (22, 64.5), (19.5, 61), (24, 65.3)]),
    ("western_med", "Mediterranean Sea",
     [(4.5, 38.6), (0, 37.5), (-3, 36.2), (6, 41), (3, 42.5), (8, 37.5), (-4.6, 36.0)]),
    ("tyrrhenian", "Tyrrhenian Sea", [(12, 40), (10.5, 42.5), (13.5, 39), (10.5, 43.5)]),
    ("adriatic", "Adriatic Sea", [(15.6, 43), (13, 44.5), (18, 41.6), (19, 40.6)]),
    ("ionian", "Ionian Sea",
     [(18.6, 37.2), (17, 35), (20, 38.5), (14, 34), (21, 33.5), (12, 36.5)]),
    ("aegean", "Aegean Sea", [(25, 38.6), (24.5, 40.5), (26, 36), (28, 35), (30, 34.5), (33, 35)]),
    ("black_sea", "Black Sea", [(34, 43.4), (31, 44), (37, 44), (29, 42), (36, 46), (28.2, 40.7)]),
    (None, "Caspian Sea", [(50, 42), (50, 45), (52, 40), (49, 38), (51, 46.5)]),
]  # fmt: skip

# Which game provinces may claim the regions of each country (ISO 3166 alpha-3), and how far
# (km) a region's centre may lie from the province seat. Farther regions become wasteland.
COUNTRIES: dict[str, tuple[tuple[str, ...], float]] = {
    "GBR": (
        (
            "london",
            "york",
            "wales",
            "scotland",
            "ireland",
            "ulster",
            "highlands",
            "east_anglia",
            "devon",
        ),
        600,
    ),
    "IRL": (("ireland", "ulster"), 600),
    "IMN": (("york",), 600),
    "JEY": (("normandy",), 300),
    "GGY": (("normandy",), 300),
    "PRT": (("lisbon", "porto"), 600),
    "ESP": (
        (
            "galicia",
            "madrid",
            "seville",
            "andalusia",
            "valencia",
            "aragon",
            "navarre",
            "castile",
            "catalonia",
        ),
        700,
    ),
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
            "burgundy",
        ),
        700,
    ),
    "MCO": (("provence",), 300),
    "BEL": (("flanders",), 300),
    "LUX": (("flanders", "rhineland"), 300),
    "NLD": (("holland",), 400),
    "DEU": (
        (
            "rhineland",
            "hamburg",
            "brandenburg",
            "pomerania",
            "saxony",
            "bavaria",
            "westphalia",
            "hesse",
            "thuringia",
            "swabia",
            "brunswick",
        ),
        600,
    ),
    "CHE": (("switzerland",), 400),
    "LIE": (("switzerland",), 300),
    "AUT": (("vienna", "tyrol", "styria"), 400),
    "CZE": (("bohemia",), 500),
    "SVK": (("upper_hungary", "buda"), 500),
    "HUN": (("buda", "upper_hungary"), 500),
    "SVN": (("styria",), 300),
    "HRV": (("croatia", "bosnia", "buda"), 500),
    "BIH": (("bosnia",), 400),
    "MNE": (("bosnia", "albania"), 400),
    "SRB": (("serbia",), 400),
    "KOS": (("serbia",), 400),
    "MKD": (("serbia", "bulgaria", "greece"), 400),
    "ALB": (("albania",), 500),
    "GRC": (("greece", "constantinople", "morea"), 700),
    "BGR": (("bulgaria",), 400),
    "TUR": (("constantinople", "anatolia", "karaman"), 420),
    "ROU": (("transylvania", "wallachia", "moldavia"), 450),
    "MDA": (("moldavia",), 450),
    "ITA": (
        (
            "milan",
            "venice",
            "florence",
            "rome",
            "naples",
            "sicily",
            "tyrol",
            "genoa",
            "savoy",
            "apulia",
            "sardinia",
            "bologna",
        ),
        600,
    ),
    "SMR": (("florence",), 300),
    "VAT": (("rome",), 300),
    "MLT": (("sicily",), 300),
    "POL": (
        (
            "krakow",
            "masovia",
            "prussia",
            "brandenburg",
            "bohemia",
            "greater_poland",
            "silesia",
            "red_ruthenia",
        ),
        500,
    ),
    "LTU": (("lithuania",), 400),
    "LVA": (("livonia",), 400),
    "EST": (("livonia",), 400),
    "BLR": (("lithuania", "smolensk", "kiev", "polotsk"), 500),
    "UKR": (("kiev", "krakow", "buda", "wallachia", "red_ruthenia", "moldavia", "crimea"), 380),
    "RUS": (
        (
            "novgorod",
            "moscow",
            "smolensk",
            "ryazan",
            "prussia",
            "pskov",
            "tver",
            "nizhny",
            "karelia",
            "crimea",
        ),
        430,
    ),
    "FIN": (("finland", "karelia"), 900),
    "ALD": (("finland",), 300),
    "SWE": (("stockholm", "gotaland", "norrland", "scania"), 900),
    "NOR": (("norway", "trondelag"), 1200),
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
    ("FRA", "region:Bourgogne-Franche-Comté"): "burgundy",
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
    ("GBR", "region:Northern Ireland"): "ulster",
    ("GBR", "region:Greater London"): "london",
    ("GBR", "region:South East"): "london",
    ("GBR", "region:South West"): "devon",
    ("GBR", "region:East"): "east_anglia",
    ("GBR", "region:West Wales and the Valleys"): "wales",
    ("GBR", "region:East Wales"): "wales",
    ("GBR", "region:North East"): "york",
    ("GBR", "region:North West"): "york",
    ("GBR", "region:Yorkshire and the Humber"): "york",
    ("GBR", "region:Highlands and Islands"): "highlands",
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
    ("ESP", "region:Castilla y León"): "castile",
    ("ESP", "region:Madrid"): "madrid",
    ("ESP", "region:Castilla-La Mancha"): "madrid",
    ("ESP", "region:Aragón"): "aragon",
    ("ESP", "region:Cataluña"): "catalonia",
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
    ("ITA", "region:Piemonte"): "savoy",
    ("ITA", "region:Valle d'Aosta"): "savoy",
    ("ITA", "region:Liguria"): "genoa",
    ("ITA", "region:Lombardia"): "milan",
    ("ITA", "region:Trentino-Alto Adige"): "tyrol",
    ("ITA", "region:Veneto"): "venice",
    ("ITA", "region:Friuli-Venezia Giulia"): "venice",
    ("ITA", "region:Toscana"): "florence",
    ("ITA", "region:Emilia-Romagna"): "bologna",
    ("ITA", "region:Umbria"): "rome",
    ("ITA", "region:Lazio"): "rome",
    ("ITA", "region:Marche"): "rome",
    ("ITA", "region:Abruzzo"): "naples",
    ("ITA", "region:Molise"): "naples",
    ("ITA", "region:Campania"): "naples",
    ("ITA", "region:Apulia"): "apulia",
    ("ITA", "region:Basilicata"): "apulia",
    ("ITA", "region:Calabria"): "naples",
    ("ITA", "region:Sicily"): "sicily",
    ("ITA", "region:Sardegna"): "sardinia",
    # The Empire
    ("DEU", "Schleswig-Holstein"): "hamburg",
    ("DEU", "Hamburg"): "hamburg",
    ("DEU", "Bremen"): "hamburg",
    ("DEU", "Niedersachsen"): "brunswick",
    ("DEU", "Mecklenburg-Vorpommern"): "pomerania",
    ("DEU", "Berlin"): "brandenburg",
    ("DEU", "Brandenburg"): "brandenburg",
    ("DEU", "Sachsen"): "saxony",
    ("DEU", "Sachsen-Anhalt"): "saxony",
    ("DEU", "Thüringen"): "thuringia",
    ("DEU", "Bayern"): "bavaria",
    ("DEU", "Baden-Württemberg"): "swabia",
    ("DEU", "Nordrhein-Westfalen"): "westphalia",
    ("DEU", "Rheinland-Pfalz"): "rhineland",
    ("DEU", "Saarland"): "rhineland",
    ("DEU", "Hessen"): "hesse",
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
    ("POL", "Kuyavian-Pomeranian"): "greater_poland",
    ("POL", "West Pomeranian"): "pomerania",
    ("POL", "Lubusz"): "greater_poland",
    ("POL", "Lower Silesian"): "silesia",
    ("POL", "Opole"): "silesia",
    ("POL", "Greater Poland"): "greater_poland",
    ("POL", "Łódź"): "masovia",
    ("POL", "Masovian"): "masovia",
    ("POL", "Podlachian"): "masovia",
    ("POL", "Lublin"): "masovia",
    ("POL", "Silesian"): "krakow",
    ("POL", "Lesser Poland"): "krakow",
    ("POL", "Subcarpathian"): "red_ruthenia",
    ("POL", "Świętokrzyskie"): "krakow",
    ("RUS", "Kaliningrad"): "prussia",
    # Russia and its neighbours
    ("RUS", "Pskov"): "pskov",
    ("RUS", "Novgorod"): "novgorod",
    ("RUS", "Leningrad"): "novgorod",
    ("RUS", "City of St. Petersburg"): "novgorod",
    ("RUS", "Tver'"): "tver",
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
    ("UKR", "L'viv"): "red_ruthenia",
    ("UKR", "Transcarpathia"): "buda",
    ("UKR", "Chernivtsi"): "moldavia",
    ("UKR", "Crimea"): "crimea",
    ("UKR", "Sevastopol"): "crimea",
    ("RUS", "Crimea"): "crimea",
    ("RUS", "Sevastopol"): "crimea",
    ("RUS", "Nizhegorod"): "nizhny",
    ("RUS", "Kostroma"): "nizhny",
    ("RUS", "Mordovia"): "nizhny",
    ("RUS", "Vologda"): None,
    ("RUS", "Ul'yanovsk"): None,
    ("RUS", "Chuvash"): None,  # the khanate of Kazan
    ("RUS", "Mariy-El"): None,
    ("RUS", "Krasnodar"): None,  # Circassia
    ("FIN", "Lapland"): "finland",
    ("FIN", "Northern Ostrobothnia"): "finland",
    ("FIN", "Kainuu"): "finland",
    ("FIN", "Northern Savonia"): "finland",
    ("RUS", "Karelia"): "karelia",
    ("UKR", "Ivano-Frankivs'k"): "red_ruthenia",
    ("UKR", "Ternopil'"): "red_ruthenia",
    ("BLR", "Vitebsk"): "polotsk",
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
    ("GRC", "region:Peloponnisos"): "morea",
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


def sea_zones(view, land, shapes, scale: float, ox: float, oy: float):  # type: ignore[no-untyped-def]
    """Cut the sea into the zones fleets sail: the water nearest each zone's seeds, without the
    lakes (water no seed lies in). Returns the drawn zones, the pairs of zones that border, and
    the provinces each zone washes."""
    from shapely.geometry import MultiPoint, Point

    water = view.difference(land)
    seeds = [(zid, Point(project(lon, lat))) for zid, _name, pts in ZONES for lon, lat in pts]
    parts = list(water.geoms) if hasattr(water, "geoms") else [water]
    sea = unary_union([w for w in parts if any(w.contains(pt) for _z, pt in seeds)])
    cells = shapely.voronoi_polygons(MultiPoint([pt for _z, pt in seeds]), extend_to=view)
    owned: dict[str, list] = defaultdict(list)  # type: ignore[type-arg]
    for cell in cells.geoms:
        zid = next(z for z, pt in seeds if cell.contains(pt))
        if zid is not None:
            owned[zid].append(cell)
    geoms = {zid: areal(unary_union(cs).intersection(sea)) for zid, cs in owned.items()}
    names = {zid: name for zid, name, _pts in ZONES if zid}
    out = []
    for zid, geom in geoms.items():
        biggest = max(geom.geoms, key=lambda g: g.area) if isinstance(geom, MultiPolygon) else geom
        label = polylabel(biggest, tolerance=1.0)
        out.append(
            {
                "id": zid,
                "name": names[zid],
                "d": svg_path(geom, scale, ox, oy),
                "x": round((label.x - ox) * scale, 1),
                "y": round((label.y - oy) * scale, 1),
            }
        )
    near = 1.5 / scale  # within a pixel and a half: they touch
    links = set()
    ids = sorted(geoms)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            shared = geoms[a].buffer(near).intersection(geoms[b].buffer(near))
            if not shared.is_empty and shared.area * scale * scale > 30:
                links.add((a, b))
    coasts: dict[str, set[str]] = defaultdict(set)
    for zid, geom in geoms.items():
        reach = geom.buffer(near)
        for pid, shape_ in shapes.items():
            if pid != WASTE and reach.intersection(shape_).area * scale * scale > 4:
                coasts[zid].add(pid)
    return out, links, coasts


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
    zones, zone_links, coasts = sea_zones(view, land, shapes, scale, minx, miny)
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
        "zones": zones,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KiB)")

    sea_links = {tuple(sorted((a, z))) for a, sea in game_map.seas.items() for z in sea.neighbors}
    print("sea links drawn but not in the game:", sorted(zone_links - sea_links))
    print("sea links in the game but not drawn:", sorted(sea_links - zone_links))
    for zid, sea in sorted(game_map.seas.items()):
        if set(sea.coasts) != coasts.get(zid, set()):
            drawn, game = coasts.get(zid, set()), set(sea.coasts)
            only = f"drawn only {sorted(drawn - game)}, game only {sorted(game - drawn)}"
            print(f"coasts of {zid}: {only}")
    game = {tuple(sorted((a, b))) for a, p in game_map.provinces.items() for b in p.neighbors}
    print("borders on the map but not in the game:", sorted(geographic - game))
    print("borders in the game but not on the map:", sorted(game - geographic))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None)
