"""The Europe 1500 scenario: 68 provinces, seven great powers and a sea of independent minors.

The map is arcade, not history: borders are simplified, and each great power starts with a
similar amount of development so that no seat is hopeless. Straits (the Channel, the Øresund,
the Strait of Messina...) are `sea_neighbors`: you can cross them, but attacking across water
gives the defender a bonus.
"""

import random

from pax_agentica.engine.model import (
    BuildingKind,
    Faith,
    GameState,
    General,
    Good,
    MapDef,
    NationState,
    ProvinceDef,
    ProvinceState,
    Resources,
    Rules,
    Terrain,
    UnitKind,
)
from pax_agentica.engine.realm import make_ruler

P, F, H, M, X = Terrain.PLAINS, Terrain.FOREST, Terrain.HILLS, Terrain.MARSH, Terrain.MOUNTAINS
GR, IR, TI, GO, CL = Good.GRAIN, Good.IRON, Good.TIMBER, Good.GOLD, Good.CLOTH

# id, name, terrain, good, development, owner (None: independent), lon, lat
_PROVINCES: list[tuple[str, str, Terrain, Good, int, str | None, float, float]] = [
    # British Isles
    ("london", "London", P, GO, 7, "england", -0.1, 51.5),
    ("york", "York", P, CL, 4, "england", -1.1, 53.9),  # the wool trade
    ("wales", "Wales", H, IR, 3, "england", -3.6, 52.3),
    ("scotland", "Scotland", H, GR, 3, None, -3.8, 56.5),
    ("ireland", "Ireland", P, GR, 2, None, -7.8, 53.2),
    # Iberia
    ("lisbon", "Lisbon", P, GO, 4, None, -8.6, 39.0),
    ("galicia", "Galicia", H, GR, 2, "spain", -7.6, 42.6),
    ("madrid", "Madrid", P, GR, 5, "spain", -3.7, 40.4),
    ("andalusia", "Andalusia", P, GO, 3, "spain", -4.8, 37.5),
    ("valencia", "Valencia", P, GR, 3, "spain", -0.8, 39.3),
    ("aragon", "Aragon", X, IR, 3, "spain", 0.4, 41.7),
    ("navarre", "Navarre", X, GR, 2, None, -1.9, 42.9),
    # North Africa
    ("morocco", "Morocco", H, GR, 3, None, -6.0, 34.5),
    ("algiers", "Algiers", H, GO, 3, None, 3.0, 36.3),
    ("tunis", "Tunis", P, GO, 3, None, 10.2, 36.4),
    # France
    ("paris", "Paris", P, GR, 6, "france", 2.4, 48.8),
    ("normandy", "Normandy", P, GR, 3, "france", 0.2, 49.3),
    ("brittany", "Brittany", F, GO, 3, "france", -2.9, 48.1),
    ("champagne", "Champagne", P, GR, 3, "france", 4.4, 49.0),
    ("lyon", "Lyon", H, CL, 4, "france", 4.8, 45.8),  # the silk looms
    ("gascony", "Gascony", P, GO, 3, "france", -0.4, 44.6),
    ("languedoc", "Languedoc", P, GR, 3, "france", 2.2, 43.6),
    ("provence", "Provence", H, GR, 3, None, 6.0, 43.7),
    # Low Countries and the Empire
    ("flanders", "Flanders", P, CL, 5, None, 3.6, 50.8),  # the cloth towns
    ("holland", "Holland", M, CL, 4, None, 5.0, 52.3),
    ("rhineland", "Rhineland", H, IR, 4, None, 7.4, 50.4),
    ("hamburg", "Hamburg", P, GO, 4, None, 9.9, 53.5),
    ("brandenburg", "Brandenburg", F, TI, 3, None, 13.4, 52.5),
    ("saxony", "Saxony", H, IR, 4, None, 12.6, 51.0),
    ("bavaria", "Bavaria", P, GR, 4, None, 11.2, 48.6),
    ("switzerland", "Switzerland", X, IR, 3, None, 8.2, 46.8),
    ("prussia", "Prussia", P, GR, 3, None, 19.4, 54.3),
    # Austria
    ("vienna", "Vienna", P, GO, 6, "austria", 16.4, 48.2),
    ("tyrol", "Tyrol", X, IR, 3, "austria", 11.4, 47.2),
    ("bohemia", "Bohemia", H, GO, 5, "austria", 14.6, 49.9),
    ("styria", "Styria", X, IR, 3, "austria", 15.2, 46.9),
    # Italy
    ("milan", "Milan", P, GO, 5, None, 9.2, 45.4),
    ("venice", "Venice", M, GO, 5, None, 12.3, 45.6),
    ("florence", "Florence", H, CL, 4, None, 11.2, 43.8),  # the Arte della Lana
    ("rome", "Rome", H, GR, 4, None, 12.8, 42.2),
    ("naples", "Naples", H, GR, 4, None, 15.2, 40.9),
    ("sicily", "Sicily", H, GR, 3, None, 14.2, 37.5),
    # Scandinavia
    ("stockholm", "Stockholm", F, IR, 5, "sweden", 18.0, 59.4),
    ("gotaland", "Götaland", P, GR, 3, "sweden", 14.0, 57.8),
    ("finland", "Finland", F, TI, 3, "sweden", 24.5, 61.0),
    ("norrland", "Norrland", F, IR, 2, "sweden", 17.0, 63.2),
    ("norway", "Norway", X, TI, 2, None, 10.0, 60.5),
    ("scania", "Scania", P, GR, 3, None, 13.6, 55.9),
    ("zealand", "Zealand", P, GO, 4, None, 12.0, 55.4),
    ("jutland", "Jutland", P, GR, 3, None, 9.2, 56.0),
    # Poland, Lithuania and Russia
    ("krakow", "Kraków", H, GR, 4, None, 20.0, 50.1),
    ("masovia", "Masovia", P, GR, 3, None, 21.0, 52.3),
    ("lithuania", "Lithuania", F, TI, 3, None, 25.3, 54.8),
    ("livonia", "Livonia", F, TI, 3, None, 24.6, 57.2),
    ("kiev", "Kiev", P, GR, 3, None, 30.5, 50.5),
    ("moscow", "Moscow", F, GR, 6, "russia", 37.6, 55.8),
    ("novgorod", "Novgorod", F, GO, 4, "russia", 31.3, 58.5),
    ("smolensk", "Smolensk", F, TI, 3, "russia", 32.0, 54.8),
    ("ryazan", "Ryazan", P, GR, 2, "russia", 39.7, 54.0),
    # Hungary and the Balkans
    ("buda", "Buda", P, GR, 5, "austria", 19.0, 47.5),
    ("transylvania", "Transylvania", X, GO, 3, None, 24.0, 46.6),
    ("wallachia", "Wallachia", P, GR, 3, None, 26.1, 44.6),
    ("serbia", "Serbia", H, IR, 3, "ottomans", 20.6, 44.0),
    ("bosnia", "Bosnia", X, IR, 2, None, 17.9, 44.1),
    ("bulgaria", "Bulgaria", H, GR, 3, "ottomans", 24.4, 42.7),
    ("greece", "Greece", H, GO, 3, "ottomans", 22.4, 39.2),
    ("constantinople", "Constantinople", P, GO, 6, "ottomans", 29.0, 41.1),
    ("anatolia", "Anatolia", H, GR, 3, "ottomans", 31.5, 39.6),
]

_LAND_BORDERS: list[tuple[str, str]] = [
    # British Isles
    ("london", "york"),
    ("london", "wales"),
    ("york", "wales"),
    ("york", "scotland"),
    # Iberia
    ("lisbon", "galicia"),
    ("lisbon", "madrid"),
    ("lisbon", "andalusia"),
    ("galicia", "madrid"),
    ("madrid", "andalusia"),
    ("madrid", "valencia"),
    ("madrid", "aragon"),
    ("andalusia", "valencia"),
    ("valencia", "aragon"),
    ("aragon", "navarre"),
    ("galicia", "navarre"),
    ("madrid", "navarre"),
    ("navarre", "gascony"),
    ("aragon", "languedoc"),
    # North Africa
    ("morocco", "algiers"),
    ("algiers", "tunis"),
    # France
    ("paris", "normandy"),
    ("paris", "champagne"),
    ("paris", "lyon"),
    ("paris", "gascony"),
    ("normandy", "brittany"),
    ("brittany", "gascony"),
    ("champagne", "flanders"),
    ("champagne", "rhineland"),
    ("champagne", "lyon"),
    ("lyon", "switzerland"),
    ("lyon", "provence"),
    ("lyon", "languedoc"),
    ("lyon", "gascony"),
    ("gascony", "languedoc"),
    ("languedoc", "provence"),
    ("provence", "milan"),
    # Low Countries and the Empire
    ("flanders", "holland"),
    ("flanders", "rhineland"),
    ("holland", "rhineland"),
    ("holland", "hamburg"),
    ("rhineland", "hamburg"),
    ("rhineland", "saxony"),
    ("rhineland", "bavaria"),
    ("hamburg", "brandenburg"),
    ("hamburg", "saxony"),
    ("hamburg", "jutland"),
    ("brandenburg", "saxony"),
    ("brandenburg", "prussia"),
    ("brandenburg", "masovia"),
    ("saxony", "bohemia"),
    ("saxony", "bavaria"),
    ("bavaria", "bohemia"),
    ("bavaria", "vienna"),
    ("bavaria", "tyrol"),
    ("bavaria", "switzerland"),
    ("switzerland", "milan"),
    ("switzerland", "tyrol"),
    ("prussia", "masovia"),
    ("prussia", "lithuania"),
    # Austria
    ("vienna", "bohemia"),
    ("vienna", "styria"),
    ("vienna", "buda"),
    ("tyrol", "styria"),
    ("tyrol", "venice"),
    ("tyrol", "milan"),
    ("bohemia", "krakow"),
    ("styria", "venice"),
    ("styria", "buda"),
    ("styria", "bosnia"),
    # Italy
    ("milan", "venice"),
    ("milan", "florence"),
    ("venice", "florence"),
    ("florence", "rome"),
    ("rome", "naples"),
    # Scandinavia
    ("stockholm", "gotaland"),
    ("stockholm", "norrland"),
    ("norrland", "finland"),
    ("norrland", "norway"),
    ("gotaland", "norway"),
    ("gotaland", "scania"),
    # Poland, Lithuania and Russia
    ("krakow", "masovia"),
    ("krakow", "buda"),
    ("krakow", "kiev"),
    ("masovia", "lithuania"),
    ("lithuania", "livonia"),
    ("lithuania", "smolensk"),
    ("lithuania", "kiev"),
    ("livonia", "novgorod"),
    ("finland", "novgorod"),
    ("novgorod", "moscow"),
    ("novgorod", "smolensk"),
    ("smolensk", "moscow"),
    ("smolensk", "kiev"),
    ("moscow", "ryazan"),
    ("ryazan", "kiev"),
    ("kiev", "wallachia"),
    # Hungary and the Balkans
    ("buda", "transylvania"),
    ("buda", "serbia"),
    ("buda", "bosnia"),
    ("transylvania", "wallachia"),
    ("wallachia", "bulgaria"),
    ("serbia", "bosnia"),
    ("serbia", "bulgaria"),
    ("bulgaria", "greece"),
    ("bulgaria", "constantinople"),
    ("greece", "constantinople"),
    ("constantinople", "anatolia"),
    # borders drawn by the real map (see scripts/build_map.py)
    ("aragon", "gascony"),
    ("bavaria", "champagne"),
    ("bohemia", "brandenburg"),
    ("bohemia", "buda"),
    ("bohemia", "masovia"),
    ("brittany", "paris"),
    ("bulgaria", "transylvania"),
    ("champagne", "switzerland"),
    ("finland", "norway"),
    ("flanders", "paris"),
    ("gotaland", "norrland"),
    ("greece", "serbia"),
    ("krakow", "lithuania"),
    ("krakow", "transylvania"),
    ("krakow", "wallachia"),
    ("livonia", "smolensk"),
    ("lyon", "milan"),
    ("ryazan", "smolensk"),
    ("serbia", "transylvania"),
    ("tyrol", "vienna"),
]

_SEA_CROSSINGS: list[tuple[str, str]] = [
    ("london", "flanders"),  # the Narrow Sea
    ("london", "normandy"),  # the Channel
    ("wales", "ireland"),  # the Irish Sea
    ("scotland", "ireland"),  # the North Channel
    ("naples", "sicily"),  # the Strait of Messina
    ("andalusia", "morocco"),  # the Strait of Gibraltar
    ("scania", "zealand"),  # the Øresund
    ("zealand", "jutland"),  # the Great Belt
    ("stockholm", "finland"),  # the Åland crossing
    ("stockholm", "livonia"),  # across the Baltic
    ("gotaland", "jutland"),  # the Kattegat
    ("bosnia", "venice"),  # the Adriatic
]

# id, name, colour (for the viewer), capital
_NATIONS: list[tuple[str, str, str, str]] = [
    ("england", "England", "#b5372f", "london"),
    ("france", "France", "#2f55a4", "paris"),
    ("spain", "Spain", "#d9b13c", "madrid"),
    ("austria", "Austria", "#ebe6d8", "vienna"),
    ("ottomans", "Ottoman Empire", "#4e8a4a", "constantinople"),
    ("sweden", "Sweden", "#4a9fd2", "stockholm"),
    ("russia", "Russia", "#7a4b9a", "moscow"),
    ("poland", "Poland-Lithuania", "#c0486b", "krakow"),
    ("hungary", "Hungary", "#8f5a2e", "buda"),
]

# Who held what in 1500 where the table above is coarser: the Jagiellonian kingdoms (Vladislaus
# II was king of Hungary and of Bohemia at once; Poland and Lithuania shared their king) and the
# Habsburgs' Burgundian lands.
OWNERS_1500: dict[str, str | None] = {
    "krakow": "poland",
    "masovia": "poland",
    "lithuania": "poland",
    "kiev": "poland",
    "buda": "hungary",
    "transylvania": "hungary",
    "bohemia": "hungary",
    # The Burgundian inheritance: Maximilian's son Philip the Handsome rules the Low Countries.
    "flanders": "austria",
    "holland": "austria",
}

# Commanders of the age, handed out in order as each nation appoints generals.
GENERAL_NAMES: dict[str, list[str]] = {
    "england": [
        "John Talbot",
        "Thomas Howard",
        "Edward Stanley",
        "Charles Brandon",
        "John Russell",
    ],
    "france": [
        "Louis de La Trémoille",
        "Gaston de Foix",
        "Pierre Bayard",
        "Odet de Lautrec",
        "Jacques de La Palice",
    ],
    "spain": [
        "Gonzalo de Córdoba",
        "Pedro Navarro",
        "Antonio de Leyva",
        "Diego García de Paredes",
        "Hernando de Alarcón",
    ],
    "austria": [
        "Georg von Frundsberg",
        "Niklas Salm",
        "Marx Sittich",
        "Kaspar Winzerer",
        "Hans Katzianer",
    ],
    "ottomans": [
        "Hadım Sinan Pasha",  # noqa: RUF001 (the Turkish dotless i)
        "Ayas Mehmed Pasha",
        "Bali Bey",
        "Mustafa Pasha",
        "Hüsrev Pasha",
    ],
    "sweden": ["Sten Sture", "Gustav Vasa", "Ivar Fleming", "Måns Bryntesson", "Lars Siggesson"],
    "russia": [
        "Daniil Shchenya",
        "Vasily Shuisky",
        "Ivan Chelyadnin",
        "Mikhail Glinsky",
        "Dmitry Belsky",
    ],
    "poland": [
        "Konstanty Ostrogski",
        "Jan Tarnowski",
        "Mikołaj Firlej",
        "Stanisław Żółkiewski",
        "Jan Karol Chodkiewicz",
    ],
    "hungary": [
        "Pál Kinizsi",
        "Pál Tomori",
        "István Dobó",
        "Bálint Török",
        "Miklós Zrínyi",
    ],
}


def general_name(nation: str, taken: int) -> str:
    names = GENERAL_NAMES.get(nation, [])
    return names[taken] if taken < len(names) else f"General no. {taken + 1}"


FAITHS = {"ottomans": Faith.SUNNI, "russia": Faith.ORTHODOX}
# What the courts of 1500 think of each other, both ways. Grudges and friendships fade over the
# years like any other opinion, so these set the opening and not the whole game.
STARTING_OPINIONS: dict[tuple[str, str], int] = {
    ("france", "england"): -25,  # a hundred years of war, ended only in 1453
    ("france", "austria"): -30,  # the Burgundian succession
    ("france", "spain"): -15,  # rival claims to Naples
    ("spain", "austria"): 35,  # the double Habsburg marriage of 1496
    ("spain", "england"): 25,  # the Treaty of Medina del Campo; Catherine of Aragon's betrothal
    ("england", "austria"): 10,  # the enemy of my enemy
    ("ottomans", "hungary"): -40,  # the frontier of Christendom
    ("ottomans", "austria"): -20,
    ("ottomans", "poland"): -15,
    ("poland", "russia"): -35,  # Muscovy wants the lands of Rus' that Lithuania holds
    ("poland", "hungary"): 25,  # Jagiellonian brothers on both thrones
    ("hungary", "austria"): -10,  # Habsburg claims to the crown of St Stephen
    ("sweden", "russia"): -15,  # the war of 1495 over Karelia
}
STARTING_PRESTIGE = {"france": 15, "spain": 15, "austria": 15, "ottomans": 20}  # the great crowns
STARTING_RESOURCES = Resources(ducats=60, manpower=10, iron=10, grain=20, timber=15)
CAPITAL_GARRISON = 6
PROVINCE_GARRISON = 2
# Balance, measured over many bot games: without these the Ottomans walk through the east and
# France, surrounded, is torn apart.
EXTRA_GARRISON = {
    # The Danube principalities raise real armies.
    **dict.fromkeys(("wallachia", "bosnia"), 3),
    # The Jagiellonian marches against Tatar and Turk.
    **dict.fromkeys(("kiev", "transylvania"), 1),
    # France has the longest border in Europe and garrisons to match.
    **dict.fromkeys(("normandy", "brittany", "champagne", "lyon", "gascony", "languedoc"), 1),
    # The Habsburg march.
    "styria": 1,
}
# What each province was known for around 1500. The table above gives a coarse good; this
# gives the trade that made its name.
GOODS_1500: dict[str, Good] = {
    "london": Good.CLOTH, "york": Good.WOOL, "wales": Good.IRON, "scotland": Good.FISH,
    "ireland": Good.WOOL, "lisbon": Good.SPICES, "galicia": Good.FISH, "madrid": Good.WOOL,
    "andalusia": Good.WINE, "valencia": Good.WINE, "aragon": Good.WOOL, "navarre": Good.IRON,
    "morocco": Good.GOLD, "algiers": Good.SALT, "tunis": Good.GRAIN,
    "paris": Good.GRAIN, "normandy": Good.GRAIN, "brittany": Good.SALT, "champagne": Good.WINE,
    "lyon": Good.CLOTH, "gascony": Good.WINE, "languedoc": Good.WINE, "provence": Good.SALT,
    "flanders": Good.CLOTH, "holland": Good.FISH, "rhineland": Good.WINE, "hamburg": Good.SALT,
    "brandenburg": Good.GRAIN, "saxony": Good.SILVER, "bavaria": Good.SALT,
    "switzerland": Good.HORSES, "prussia": Good.GRAIN,
    "vienna": Good.WINE, "tyrol": Good.SILVER, "bohemia": Good.SILVER, "styria": Good.IRON,
    "milan": Good.CLOTH, "venice": Good.SPICES, "florence": Good.CLOTH, "rome": Good.WINE,
    "naples": Good.WINE, "sicily": Good.GRAIN,
    "stockholm": Good.COPPER, "gotaland": Good.GRAIN, "finland": Good.TIMBER,
    "norrland": Good.IRON, "norway": Good.FISH, "scania": Good.FISH, "zealand": Good.FISH,
    "jutland": Good.HORSES,
    "krakow": Good.SALT, "masovia": Good.GRAIN, "lithuania": Good.TIMBER, "livonia": Good.GRAIN,
    "kiev": Good.HORSES, "moscow": Good.FURS, "novgorod": Good.FURS, "smolensk": Good.TIMBER,
    "ryazan": Good.GRAIN,
    "buda": Good.WINE, "transylvania": Good.GOLD, "wallachia": Good.HORSES,
    "serbia": Good.SILVER, "bosnia": Good.IRON, "bulgaria": Good.GRAIN, "greece": Good.WINE,
    "constantinople": Good.SPICES, "anatolia": Good.CLOTH,
}  # fmt: skip

STARTING_BUILDINGS: dict[str, list[BuildingKind]] = {
    "vienna": [BuildingKind.FORT],  # the walls the Turk will test in 1529
    "buda": [BuildingKind.FORT],
    "paris": [BuildingKind.STABLES],  # the gendarmerie, Europe's finest heavy horse
    "krakow": [BuildingKind.STABLES],  # the hussar banners
    "anatolia": [BuildingKind.STABLES],  # the timariot sipahis
    "moscow": [BuildingKind.STABLES],  # the cavalry host of the steppe frontier
}
# Each capital garrison as its army was famed for: the rest of every garrison is pikemen.
STARTING_UNITS: dict[str, dict[UnitKind, int]] = {
    "london": {UnitKind.ARCHERS: 3},  # the longbow
    "paris": {UnitKind.CAVALRY: 2},
    "madrid": {UnitKind.ARCHERS: 2},  # arquebusiers of the Granada war
    "vienna": {UnitKind.CAVALRY: 1, UnitKind.ARCHERS: 1},
    "constantinople": {UnitKind.CAVALRY: 2, UnitKind.ARCHERS: 1},  # sipahis and janissaries
    "stockholm": {UnitKind.ARCHERS: 2},
    "moscow": {UnitKind.CAVALRY: 3},
    "krakow": {UnitKind.CAVALRY: 3},  # the winged hussars' forebears
    "buda": {UnitKind.CAVALRY: 2, UnitKind.ARCHERS: 1},  # hussars and the Black Army's gunmen
}


def europe_map() -> MapDef:
    land: dict[str, list[str]] = {p[0]: [] for p in _PROVINCES}
    sea: dict[str, list[str]] = {p[0]: [] for p in _PROVINCES}
    for a, b in _LAND_BORDERS:
        land[a].append(b)
        land[b].append(a)
    for a, b in _SEA_CROSSINGS:
        sea[a].append(b)
        sea[b].append(a)
    provinces = {
        pid: ProvinceDef(
            id=pid,
            name=name,
            terrain=terrain,
            good=GOODS_1500.get(pid, good),
            lon=lon,
            lat=lat,
            neighbors=tuple(sorted(land[pid])),
            sea_neighbors=tuple(sorted(sea[pid])),
        )
        for pid, name, terrain, good, _dev, _owner, lon, lat in _PROVINCES
    }
    return MapDef(name="Europe 1500", provinces=provinces)


def new_game(seed: int, max_turns: int = 50, rules: Rules | None = None) -> GameState:
    """The opening position of the Europe 1500 scenario."""
    capitals = {capital for _id, _name, _color, capital in _NATIONS}
    rules_ = rules or Rules()
    provinces = {
        pid: ProvinceState(
            owner=OWNERS_1500.get(pid, owner),
            development=dev,
            troops=_garrison(pid, dev, OWNERS_1500.get(pid, owner), capitals)
            + EXTRA_GARRISON.get(pid, 0),
            buildings=list(STARTING_BUILDINGS.get(pid, [])),
            units=dict(STARTING_UNITS.get(pid, {})),
            monument=rules_.monuments[pid].level_1500 if pid in rules_.monuments else 0,
        )
        for pid, _name, _terrain, _good, dev, owner, _lon, _lat in _PROVINCES
    }
    nations = {
        nid: NationState(
            id=nid,
            name=name,
            color=color,
            capital=capital,
            resources=STARTING_RESOURCES,
            stability=1,
            faith=FAITHS.get(nid, Faith.CATHOLIC),
            prestige=STARTING_PRESTIGE.get(nid, 10),
        )
        for nid, name, color, capital in _NATIONS
    }
    rng = random.Random(f"{seed}:rulers")  # noqa: S311 (game dice)
    for nation in nations.values():
        nation.ruler = make_ruler(nation.id, 0, 1, rng, age=rng.randint(28, 48))
    generals = [
        General(id=k + 1, name=general_name(nid, 0), nation=nid, skill=2, province=capital)
        for k, (nid, _name, _color, capital) in enumerate(_NATIONS)
    ]
    return GameState(
        seed=seed,
        max_turns=max_turns,
        rules=rules_,
        map=europe_map(),
        provinces=provinces,
        nations=nations,
        generals=generals,
        next_general_id=len(generals) + 1,
        opinions=_opinions(),
    )


def _opinions() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for (a, b), value in STARTING_OPINIONS.items():
        out.setdefault(a, {})[b] = value
        out.setdefault(b, {})[a] = value
    return out


def _garrison(pid: str, dev: int, owner: str | None, capitals: set[str]) -> int:
    if owner is None:
        return dev  # independent minors defend themselves with their own levies
    return CAPITAL_GARRISON if pid in capitals else PROVINCE_GARRISON
