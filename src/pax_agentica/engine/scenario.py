"""The Europe 1500 scenario: 68 provinces, seven great powers and a sea of independent minors.

The map is arcade, not history: borders are simplified, and each great power starts with a
similar amount of development so that no seat is hopeless. Straits (the Channel, the Øresund,
the Strait of Messina...) are `sea_neighbors`: you can cross them, but attacking across water
gives the defender a bonus.
"""

import random

from pax_agentica.engine.colonies import STARTING_COLONIES
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
    Ship,
    Terrain,
    UnitKind,
    Water,
)
from pax_agentica.engine.realm import make_ruler

P, F, H, M, X = Terrain.PLAINS, Terrain.FOREST, Terrain.HILLS, Terrain.MARSH, Terrain.MOUNTAINS
GR, IR, TI, GO, CL = Good.GRAIN, Good.IRON, Good.TIMBER, Good.GOLD, Good.CLOTH

# id, name, terrain, good, development, owner (None: independent), lon, lat
_PROVINCES: list[tuple[str, str, Terrain, Good, int, str | None, float, float]] = [
    # British Isles
    ("london", "London", P, GO, 6, "england", -0.1, 51.5),
    ("york", "York", P, CL, 4, "england", -1.1, 53.9),  # the wool trade
    ("wales", "Wales", H, IR, 3, "england", -3.6, 52.3),
    ("scotland", "Scotland", H, GR, 3, None, -3.8, 56.5),
    ("ireland", "Ireland", P, GR, 2, None, -7.8, 53.0),
    ("ulster", "Ulster", H, GR, 2, None, -6.9, 54.6),
    ("highlands", "Highlands", X, GR, 1, None, -4.8, 57.4),
    ("east_anglia", "East Anglia", P, CL, 3, "england", 1.0, 52.4),  # the Norwich worsteds
    ("devon", "Devon and Cornwall", H, IR, 2, "england", -4.2, 50.6),  # the stannaries
    # Iberia
    ("lisbon", "Lisbon", P, GO, 5, None, -8.6, 39.0),
    ("porto", "Porto", H, GR, 2, None, -8.3, 41.4),
    ("galicia", "Galicia", H, GR, 2, "spain", -7.6, 42.6),
    ("madrid", "Madrid", P, GR, 4, "spain", -3.7, 40.0),
    ("castile", "Castile", P, GR, 2, "spain", -4.7, 41.7),  # Valladolid, Burgos, the Mesta
    # Seville: the Casa de Contratación (1503) will take in all the gold of the Indies
    ("seville", "Seville", P, GO, 5, "spain", -6.0, 37.4),
    ("andalusia", "Granada", H, CL, 3, "spain", -3.6, 37.2),  # the silk of the Nasrids
    ("valencia", "Valencia", P, GR, 3, "spain", -0.8, 39.3),
    ("aragon", "Aragon", X, IR, 2, "spain", -0.9, 41.6),
    ("catalonia", "Catalonia", H, CL, 3, "spain", 1.9, 41.8),
    ("navarre", "Navarre", X, GR, 2, None, -1.9, 42.9),
    # North Africa
    ("morocco", "Morocco", H, GR, 3, None, -6.0, 34.5),
    ("algiers", "Algiers", H, GO, 3, None, 3.0, 36.3),
    ("tunis", "Tunis", P, GO, 3, None, 10.2, 36.4),
    # France
    ("paris", "Paris", P, GR, 7, "france", 2.4, 48.8),
    ("normandy", "Normandy", P, GR, 3, "france", 0.2, 49.3),
    ("brittany", "Brittany", F, GO, 2, "france", -2.9, 48.1),
    ("champagne", "Champagne", P, GR, 2, "france", 4.4, 49.0),
    ("lyon", "Lyon", H, CL, 3, "france", 4.8, 45.6),  # the silk looms
    ("burgundy", "Burgundy", H, GR, 3, "france", 5.0, 47.3),
    ("gascony", "Gascony", P, GO, 3, "france", -0.4, 44.6),
    ("languedoc", "Languedoc", P, GR, 3, "france", 2.2, 43.6),
    ("provence", "Provence", H, GR, 3, None, 6.0, 43.7),
    # Low Countries and the Empire
    ("flanders", "Flanders", P, CL, 6, None, 3.6, 50.8),  # the cloth towns
    ("holland", "Holland", M, CL, 4, None, 5.0, 52.3),
    ("rhineland", "Rhineland", H, IR, 4, None, 7.4, 50.0),
    ("westphalia", "Westphalia", P, CL, 3, None, 7.6, 51.9),
    ("hesse", "Hesse", H, TI, 3, None, 9.2, 50.7),
    ("hamburg", "Hamburg", P, GO, 4, None, 9.9, 53.8),
    ("brunswick", "Brunswick", H, IR, 3, None, 10.0, 52.4),  # the Harz silver
    ("thuringia", "Thuringia", H, CL, 3, None, 11.0, 50.9),  # the woad of Erfurt
    ("swabia", "Swabia", H, CL, 4, None, 9.4, 48.5),  # Augsburg of the Fuggers
    ("brandenburg", "Brandenburg", F, TI, 4, "brandenburg", 13.4, 52.5),
    ("pomerania", "Pomerania", P, GR, 5, "brandenburg", 14.2, 53.8),
    ("saxony", "Saxony", H, IR, 4, None, 12.6, 51.0),
    ("bavaria", "Bavaria", P, GR, 4, None, 11.2, 48.6),
    ("switzerland", "Switzerland", X, IR, 3, None, 8.2, 46.8),
    ("prussia", "Prussia", P, GR, 5, "brandenburg", 19.4, 54.3),
    # Austria
    ("vienna", "Vienna", P, GO, 6, "austria", 16.4, 48.2),
    ("tyrol", "Tyrol", X, IR, 3, "austria", 11.4, 47.2),
    ("bohemia", "Bohemia", H, GO, 4, "austria", 14.6, 49.9),
    ("silesia", "Silesia", P, CL, 3, "austria", 17.0, 51.0),
    ("styria", "Styria", X, IR, 3, "austria", 15.2, 46.9),
    # Italy
    ("milan", "Milan", P, GO, 6, None, 9.6, 45.5),
    ("savoy", "Savoy", X, GR, 3, None, 7.5, 45.2),
    ("genoa", "Genoa", H, GO, 5, None, 8.9, 44.4),
    ("venice", "Venice", M, GO, 6, None, 12.3, 45.6),
    ("florence", "Florence", H, CL, 5, None, 11.2, 43.5),  # the Arte della Lana
    ("bologna", "Bologna", P, CL, 3, None, 11.4, 44.5),
    ("rome", "Rome", H, GR, 4, None, 12.8, 42.2),
    ("naples", "Naples", H, GR, 6, None, 14.6, 40.9),
    ("apulia", "Apulia", P, GR, 3, None, 16.7, 40.9),
    ("sardinia", "Sardinia", H, GO, 2, None, 9.0, 40.0),
    ("sicily", "Sicily", H, GR, 3, None, 14.2, 37.5),
    # Scandinavia
    ("stockholm", "Stockholm", F, IR, 4, "sweden", 18.0, 59.4),
    ("gotaland", "Götaland", P, GR, 4, "sweden", 14.0, 57.8),
    ("finland", "Finland", F, TI, 3, "sweden", 24.0, 61.5),
    ("karelia", "Karelia", F, TI, 2, "sweden", 29.5, 62.0),  # Viborg's castle on the border
    ("norrland", "Norrland", F, IR, 2, "sweden", 17.0, 63.2),
    ("norway", "Norway", X, TI, 2, None, 9.5, 60.0),
    ("trondelag", "Trøndelag", X, TI, 1, None, 11.5, 64.0),
    ("scania", "Scania", P, GR, 3, None, 13.6, 55.9),
    ("zealand", "Zealand", P, GO, 4, None, 12.0, 55.4),
    ("jutland", "Jutland", P, GR, 3, None, 9.2, 56.0),
    # Poland, Lithuania and Russia
    ("krakow", "Kraków", H, GR, 4, None, 20.0, 50.1),
    ("masovia", "Masovia", P, GR, 3, None, 21.5, 52.3),
    ("greater_poland", "Greater Poland", P, GR, 3, None, 17.3, 52.5),
    ("red_ruthenia", "Red Ruthenia", H, GR, 2, None, 24.0, 49.6),  # Lwów and its salt
    ("polotsk", "Polotsk", F, TI, 2, None, 28.7, 55.4),
    ("lithuania", "Lithuania", F, TI, 3, None, 25.3, 54.8),
    ("livonia", "Livonia", F, TI, 3, None, 24.6, 57.2),
    ("kiev", "Kiev", P, GR, 3, None, 30.5, 50.5),
    ("moscow", "Moscow", F, GR, 6, "russia", 37.6, 55.6),
    ("tver", "Tver", F, GR, 2, "russia", 35.3, 57.0),
    ("nizhny", "Nizhny Novgorod", F, TI, 2, "russia", 43.5, 56.2),  # the Volga trade
    ("pskov", "Pskov", F, GR, 2, None, 28.8, 57.6),  # a free republic, for now
    ("novgorod", "Novgorod", F, GO, 4, "russia", 31.3, 58.5),
    ("smolensk", "Smolensk", F, TI, 3, "russia", 32.0, 54.8),
    ("ryazan", "Ryazan", P, GR, 2, "russia", 39.7, 54.0),
    # Hungary and the Balkans
    ("buda", "Buda", P, GR, 4, "austria", 19.0, 47.3),
    ("upper_hungary", "Upper Hungary", X, GO, 2, "austria", 19.8, 48.7),  # the mining towns
    ("croatia", "Croatia", H, TI, 2, None, 15.9, 45.6),  # a banate of its own, for the game
    ("transylvania", "Transylvania", X, GO, 3, None, 24.0, 46.6),
    ("wallachia", "Wallachia", P, GR, 3, None, 25.6, 44.6),
    ("moldavia", "Moldavia", P, GR, 3, None, 27.2, 47.2),  # Stephen the Great's
    ("crimea", "Crimea", P, GR, 2, None, 34.2, 45.0),  # the Giray khans
    ("serbia", "Serbia", H, IR, 2, "ottomans", 20.6, 44.0),
    ("bosnia", "Bosnia", X, IR, 2, None, 17.9, 44.1),
    ("bulgaria", "Bulgaria", H, GR, 2, "ottomans", 24.4, 42.7),
    ("greece", "Greece", H, GO, 3, "ottomans", 22.3, 39.6),
    ("morea", "Morea", H, GO, 2, "ottomans", 22.3, 37.6),
    ("albania", "Albania", X, GR, 2, "ottomans", 20.0, 41.0),
    ("constantinople", "Constantinople", P, GO, 8, "ottomans", 29.0, 41.1),
    ("anatolia", "Anatolia", H, GR, 3, "ottomans", 31.0, 39.9),
    ("karaman", "Karaman", H, GR, 2, "ottomans", 33.0, 37.8),
]

_LAND_BORDERS: list[tuple[str, str]] = [  # as the real map draws them (scripts/build_map.py)
    ("albania", "bosnia"),
    ("albania", "greece"),
    ("albania", "serbia"),
    ("algiers", "morocco"),
    ("algiers", "tunis"),
    ("anatolia", "constantinople"),
    ("anatolia", "karaman"),
    ("andalusia", "madrid"),
    ("andalusia", "seville"),
    ("andalusia", "valencia"),
    ("apulia", "naples"),
    ("aragon", "castile"),
    ("aragon", "catalonia"),
    ("aragon", "gascony"),
    ("aragon", "languedoc"),
    ("aragon", "madrid"),
    ("aragon", "navarre"),
    ("aragon", "valencia"),
    ("bavaria", "bohemia"),
    ("bavaria", "hesse"),
    ("bavaria", "saxony"),
    ("bavaria", "swabia"),
    ("bavaria", "thuringia"),
    ("bavaria", "tyrol"),
    ("bavaria", "vienna"),
    ("bohemia", "buda"),
    ("bohemia", "krakow"),
    ("bohemia", "saxony"),
    ("bohemia", "silesia"),
    ("bohemia", "upper_hungary"),
    ("bohemia", "vienna"),
    ("bologna", "florence"),
    ("bologna", "genoa"),
    ("bologna", "milan"),
    ("bologna", "rome"),
    ("bologna", "venice"),
    ("bosnia", "buda"),
    ("bosnia", "croatia"),
    ("bosnia", "serbia"),
    ("brandenburg", "brunswick"),
    ("brandenburg", "greater_poland"),
    ("brandenburg", "pomerania"),
    ("brandenburg", "saxony"),
    ("brittany", "gascony"),
    ("brittany", "normandy"),
    ("brittany", "paris"),
    ("brunswick", "hamburg"),
    ("brunswick", "hesse"),
    ("brunswick", "holland"),
    ("brunswick", "pomerania"),
    ("brunswick", "saxony"),
    ("brunswick", "thuringia"),
    ("brunswick", "westphalia"),
    ("buda", "croatia"),
    ("buda", "red_ruthenia"),
    ("buda", "serbia"),
    ("buda", "styria"),
    ("buda", "transylvania"),
    ("buda", "upper_hungary"),
    ("buda", "vienna"),
    ("bulgaria", "constantinople"),
    ("bulgaria", "greece"),
    ("bulgaria", "serbia"),
    ("bulgaria", "wallachia"),
    ("burgundy", "champagne"),
    ("burgundy", "lyon"),
    ("burgundy", "paris"),
    ("burgundy", "switzerland"),
    ("castile", "galicia"),
    ("castile", "madrid"),
    ("castile", "navarre"),
    ("castile", "porto"),
    ("castile", "seville"),
    ("catalonia", "languedoc"),
    ("catalonia", "valencia"),
    ("champagne", "flanders"),
    ("champagne", "paris"),
    ("champagne", "rhineland"),
    ("champagne", "swabia"),
    ("champagne", "switzerland"),
    ("constantinople", "greece"),
    ("crimea", "kiev"),
    ("crimea", "moldavia"),
    ("croatia", "styria"),
    ("devon", "london"),
    ("devon", "wales"),
    ("east_anglia", "london"),
    ("east_anglia", "york"),
    ("finland", "karelia"),
    ("finland", "norrland"),
    ("finland", "novgorod"),
    ("finland", "trondelag"),
    ("flanders", "holland"),
    ("flanders", "paris"),
    ("flanders", "rhineland"),
    ("flanders", "westphalia"),
    ("florence", "genoa"),
    ("florence", "rome"),
    ("galicia", "navarre"),
    ("galicia", "porto"),
    ("gascony", "languedoc"),
    ("gascony", "lyon"),
    ("gascony", "navarre"),
    ("gascony", "paris"),
    ("genoa", "provence"),
    ("genoa", "savoy"),
    ("gotaland", "norrland"),
    ("gotaland", "norway"),
    ("gotaland", "scania"),
    ("gotaland", "stockholm"),
    ("greater_poland", "masovia"),
    ("greater_poland", "pomerania"),
    ("greater_poland", "prussia"),
    ("greater_poland", "saxony"),
    ("greater_poland", "silesia"),
    ("greece", "morea"),
    ("greece", "serbia"),
    ("hamburg", "jutland"),
    ("hamburg", "pomerania"),
    ("hesse", "rhineland"),
    ("hesse", "swabia"),
    ("hesse", "thuringia"),
    ("hesse", "westphalia"),
    ("highlands", "scotland"),
    ("holland", "westphalia"),
    ("ireland", "ulster"),
    ("karelia", "novgorod"),
    ("kiev", "lithuania"),
    ("kiev", "moldavia"),
    ("kiev", "red_ruthenia"),
    ("kiev", "ryazan"),
    ("kiev", "smolensk"),
    ("krakow", "masovia"),
    ("krakow", "red_ruthenia"),
    ("krakow", "silesia"),
    ("krakow", "upper_hungary"),
    ("languedoc", "lyon"),
    ("languedoc", "provence"),
    ("lisbon", "porto"),
    ("lisbon", "seville"),
    ("lithuania", "livonia"),
    ("lithuania", "masovia"),
    ("lithuania", "polotsk"),
    ("lithuania", "prussia"),
    ("lithuania", "red_ruthenia"),
    ("lithuania", "smolensk"),
    ("livonia", "novgorod"),
    ("livonia", "polotsk"),
    ("livonia", "pskov"),
    ("london", "wales"),
    ("london", "york"),
    ("lyon", "paris"),
    ("lyon", "provence"),
    ("lyon", "savoy"),
    ("lyon", "switzerland"),
    ("madrid", "seville"),
    ("madrid", "valencia"),
    ("masovia", "prussia"),
    ("masovia", "red_ruthenia"),
    ("masovia", "silesia"),
    ("milan", "savoy"),
    ("milan", "switzerland"),
    ("milan", "tyrol"),
    ("milan", "venice"),
    ("moldavia", "red_ruthenia"),
    ("moldavia", "transylvania"),
    ("moldavia", "wallachia"),
    ("moscow", "nizhny"),
    ("moscow", "ryazan"),
    ("moscow", "smolensk"),
    ("moscow", "tver"),
    ("naples", "rome"),
    ("nizhny", "ryazan"),
    ("normandy", "paris"),
    ("norrland", "norway"),
    ("norrland", "stockholm"),
    ("norrland", "trondelag"),
    ("norway", "trondelag"),
    ("novgorod", "pskov"),
    ("novgorod", "tver"),
    ("polotsk", "pskov"),
    ("polotsk", "smolensk"),
    ("pomerania", "prussia"),
    ("provence", "savoy"),
    ("pskov", "smolensk"),
    ("pskov", "tver"),
    ("red_ruthenia", "transylvania"),
    ("red_ruthenia", "upper_hungary"),
    ("rhineland", "swabia"),
    ("rhineland", "westphalia"),
    ("ryazan", "smolensk"),
    ("savoy", "switzerland"),
    ("saxony", "silesia"),
    ("saxony", "thuringia"),
    ("scotland", "york"),
    ("serbia", "transylvania"),
    ("serbia", "wallachia"),
    ("smolensk", "tver"),
    ("styria", "tyrol"),
    ("styria", "venice"),
    ("styria", "vienna"),
    ("swabia", "switzerland"),
    ("switzerland", "tyrol"),
    ("transylvania", "upper_hungary"),
    ("transylvania", "wallachia"),
    ("tyrol", "venice"),
    ("tyrol", "vienna"),
    ("wales", "york"),
]

_SEA_CROSSINGS: list[tuple[str, str, Water]] = [
    ("london", "flanders", Water.ATLANTIC),  # the Narrow Sea
    ("london", "normandy", Water.ATLANTIC),  # the Channel
    ("wales", "ireland", Water.ATLANTIC),  # the Irish Sea
    ("scotland", "ulster", Water.ATLANTIC),  # the North Channel
    ("sardinia", "genoa", Water.MEDITERRANEAN),  # the Ligurian Sea
    ("sardinia", "rome", Water.MEDITERRANEAN),  # the Tyrrhenian
    ("sardinia", "tunis", Water.MEDITERRANEAN),  # the Sardinia channel
    ("devon", "brittany", Water.ATLANTIC),  # the western Channel
    ("crimea", "anatolia", Water.MEDITERRANEAN),  # across the Black Sea, the Sultan's lake
    ("naples", "sicily", Water.MEDITERRANEAN),  # the Strait of Messina
    ("seville", "morocco", Water.MEDITERRANEAN),  # the Strait of Gibraltar
    ("andalusia", "morocco", Water.MEDITERRANEAN),  # the Alborán crossing
    ("scania", "zealand", Water.BALTIC),  # the Øresund
    ("zealand", "jutland", Water.BALTIC),  # the Great Belt
    ("stockholm", "finland", Water.BALTIC),  # the Åland crossing
    ("stockholm", "livonia", Water.BALTIC),  # across the Baltic
    ("gotaland", "jutland", Water.ATLANTIC),  # the Kattegat
    ("bosnia", "venice", Water.MEDITERRANEAN),  # the Adriatic
]

# The waters each coastal province looks onto (the Atlantic takes in the Channel and the North
# Sea; the Mediterranean the Adriatic and the Black Sea).
_A, _B, _M = Water.ATLANTIC, Water.BALTIC, Water.MEDITERRANEAN
_ATLANTIC_COASTS = (
    "london", "york", "wales", "scotland", "ireland", "ulster", "highlands", "east_anglia",
    "devon", "lisbon", "porto", "galicia", "normandy", "brittany", "gascony", "flanders",
    "holland", "norway", "trondelag",
)  # fmt: skip
_BALTIC_COASTS = (
    "stockholm", "finland", "karelia", "norrland", "scania", "zealand", "pomerania", "prussia",
    "livonia", "lithuania", "novgorod",
)  # fmt: skip
_MEDITERRANEAN_COASTS = (
    "andalusia", "valencia", "catalonia", "algiers", "tunis", "languedoc", "provence", "genoa",
    "florence", "rome", "naples", "apulia", "sardinia", "sicily", "venice", "styria", "croatia",
    "bosnia", "albania", "greece", "morea", "constantinople", "anatolia", "karaman", "bulgaria",
    "moldavia", "crimea",
)  # fmt: skip
COASTS: dict[str, tuple[Water, ...]] = {
    **dict.fromkeys(_ATLANTIC_COASTS, (_A,)),
    **dict.fromkeys(_BALTIC_COASTS, (_B,)),
    **dict.fromkeys(_MEDITERRANEAN_COASTS, (_M,)),
    "seville": (_A, _M),  # Cádiz on the ocean, and the strait
    "morocco": (_A, _M),
    "hamburg": (_A, _B),  # Hamburg on the North Sea, Lübeck on the Baltic
    "jutland": (_A, _B),
    "gotaland": (_A, _B),  # Älvsborg on the Kattegat, Kalmar on the Baltic
}
# The fleets of 1500, by water: the Sultan's galleys, the Catholic Kings' two seas, the Tudor
# ships royal, the Swedish and Hanseatic Baltic.
STARTING_FLEETS: dict[str, dict[Water, dict[Ship, int]]] = {
    "ottomans": {_M: {Ship.GALLEY: 10, Ship.GALLEON: 1}},
    "spain": {_M: {Ship.GALLEY: 6}, _A: {Ship.GALLEON: 3}},
    "france": {_M: {Ship.GALLEY: 4}, _A: {Ship.GALLEON: 2}},
    "england": {_A: {Ship.GALLEON: 4, Ship.GALLEY: 1}},
    "sweden": {_B: {Ship.GALLEY: 3, Ship.GALLEON: 2}},
    "brandenburg": {_B: {Ship.GALLEY: 1}},
    "austria": {_M: {Ship.GALLEY: 1}},
}

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
    ("brandenburg", "Brandenburg-Prussia", "#5f6670", "brandenburg"),
]

# Who held what in 1500 where the table above is coarser. Poland and Lithuania share their king.
# Two unions come early: the Danubian monarchy (Bohemia and Hungary passed to the Habsburgs in
# 1526) and Brandenburg-Prussia (the Hohenzollerns inherited Prussia in 1618 and Pomerania in
# 1648), so that the middle of Europe has great powers of its own from the first year. The Low
# Countries are left to Philip the Handsome's own Burgundian court, outside the game's powers.
OWNERS_1500: dict[str, str | None] = {
    "krakow": "poland",
    "masovia": "poland",
    "lithuania": "poland",
    "kiev": "poland",
    "greater_poland": "poland",
    "red_ruthenia": "poland",
    "polotsk": "poland",
    "buda": "austria",
    "transylvania": "austria",
    "bohemia": "austria",
    "flanders": None,
    "holland": None,
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
        "Pál Tomori",
        "Miklós Zrínyi",
        "István Dobó",
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
    "brandenburg": [
        "Joachim von Bredow",
        "Hans von Küstrin",
        "Kaspar von Klitzing",
        "Otto von Sparr",
        "Georg von Derfflinger",
    ],
}


def general_name(nation: str, taken: int) -> str:
    names = GENERAL_NAMES.get(nation, [])
    return names[taken] if taken < len(names) else f"General no. {taken + 1}"


FAITHS = {"ottomans": Faith.SUNNI, "russia": Faith.ORTHODOX}
# What the people believed in 1500 where it is not their ruler's faith, or where no great power
# rules: the Maghreb and Anatolia are Muslim; the Balkans under the Sultan and the Ruthenian
# lands under Poland-Lithuania stay Orthodox.
PEOPLE_FAITH: dict[str, Faith] = {
    **dict.fromkeys(
        ("morocco", "algiers", "tunis", "anatolia", "constantinople", "karaman", "crimea"),
        Faith.SUNNI,
    ),
    **dict.fromkeys(
        (
            "greece",
            "bulgaria",
            "serbia",
            "wallachia",
            "kiev",
            "smolensk",
            "novgorod",
            "morea",
            "albania",
            "moldavia",
            "red_ruthenia",
            "polotsk",
            "pskov",
            "karelia",
        ),
        Faith.ORTHODOX,
    ),
}


def province_faith(pid: str, owner: str | None) -> Faith:
    if pid in PEOPLE_FAITH:
        return PEOPLE_FAITH[pid]
    return FAITHS.get(owner, Faith.CATHOLIC) if owner else Faith.CATHOLIC


# What the courts of 1500 think of each other, both ways. Grudges and friendships fade over the
# years like any other opinion, so these set the opening and not the whole game.
STARTING_OPINIONS: dict[tuple[str, str], int] = {
    ("france", "england"): -25,  # a hundred years of war, ended only in 1453
    ("france", "austria"): -30,  # the Burgundian succession
    ("france", "spain"): -15,  # rival claims to Naples
    ("spain", "austria"): 35,  # the double Habsburg marriage of 1496
    ("spain", "england"): 25,  # the Treaty of Medina del Campo; Catherine of Aragon's betrothal
    ("england", "austria"): 10,  # the enemy of my enemy
    ("ottomans", "austria"): -40,  # the frontier of Christendom, from Belgrade to Vienna
    ("ottomans", "poland"): -15,
    ("poland", "russia"): -35,  # Muscovy wants the lands of Rus' that Lithuania holds
    ("poland", "austria"): 10,  # the Congress of Vienna will marry the dynasties in 1515
    ("poland", "brandenburg"): -15,  # rival claims to Pomerania and the Teutonic lands
    ("brandenburg", "austria"): 15,  # an Elector loyal to the Emperor, for now
    ("sweden", "russia"): -15,  # the war of 1495 over Karelia
}
STARTING_PRESTIGE = {"france": 15, "spain": 15, "austria": 15, "ottomans": 20}  # the great crowns
STARTING_RESOURCES = Resources(ducats=60, manpower=10, iron=10, grain=20, timber=15, goods=8)
CAPITAL_GARRISON = 6
PROVINCE_GARRISON = 2
# Balance, measured over many bot games: without these the Ottomans walk through the east and
# France, surrounded, is torn apart.
EXTRA_GARRISON = {
    # Portugal of the spice fleets, the Wattasid sultans of Fez and the corsair coast.
    "lisbon": 4,
    "morocco": 2,
    **dict.fromkeys(("algiers", "tunis", "navarre"), 1),
    # The Danube principalities raise real armies.
    **dict.fromkeys(("wallachia", "bosnia"), 3),
    # The marches against Tatar and Turk.
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
    "ireland": Good.WOOL, "lisbon": Good.SPICES, "galicia": Good.FISH, "madrid": Good.GRAIN,
    "andalusia": Good.CLOTH, "seville": Good.GOLD, "valencia": Good.WINE, "aragon": Good.WOOL,
    "navarre": Good.IRON,
    "morocco": Good.GOLD, "algiers": Good.SALT, "tunis": Good.GRAIN,
    "paris": Good.GRAIN, "normandy": Good.GRAIN, "brittany": Good.SALT, "champagne": Good.WINE,
    "lyon": Good.CLOTH, "gascony": Good.WINE, "languedoc": Good.WINE, "provence": Good.SALT,
    "flanders": Good.CLOTH, "holland": Good.FISH, "rhineland": Good.WINE, "hamburg": Good.SALT,
    "brandenburg": Good.TIMBER, "pomerania": Good.SALT, "saxony": Good.SILVER, "bavaria": Good.SALT,
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
    # the provinces added later
    "ulster": Good.FISH, "highlands": Good.WOOL, "east_anglia": Good.WOOL, "devon": Good.COPPER,
    "porto": Good.WINE, "castile": Good.WOOL, "catalonia": Good.CLOTH, "burgundy": Good.WINE,
    "westphalia": Good.CLOTH, "hesse": Good.TIMBER, "brunswick": Good.SILVER,
    "thuringia": Good.CLOTH, "swabia": Good.CLOTH, "silesia": Good.CLOTH, "savoy": Good.HORSES,
    "genoa": Good.SPICES, "bologna": Good.CLOTH, "apulia": Good.WOOL, "sardinia": Good.SILVER,
    "trondelag": Good.FISH, "karelia": Good.FURS, "greater_poland": Good.GRAIN,
    "red_ruthenia": Good.SALT, "polotsk": Good.TIMBER, "tver": Good.GRAIN, "nizhny": Good.FURS,
    "pskov": Good.CLOTH, "upper_hungary": Good.SILVER, "croatia": Good.TIMBER,
    "moldavia": Good.HORSES, "crimea": Good.SALT, "morea": Good.WINE, "albania": Good.WOOL,
    "karaman": Good.HORSES,
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
    "brandenburg": {UnitKind.CAVALRY: 1, UnitKind.ARCHERS: 1},
}


def europe_map() -> MapDef:
    land: dict[str, list[str]] = {p[0]: [] for p in _PROVINCES}
    sea: dict[str, list[str]] = {p[0]: [] for p in _PROVINCES}
    for a, b in _LAND_BORDERS:
        land[a].append(b)
        land[b].append(a)
    for a, b, _water in _SEA_CROSSINGS:
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
            coasts=COASTS.get(pid, ()),
        )
        for pid, name, terrain, good, _dev, _owner, lon, lat in _PROVINCES
    }
    straits = {"|".join(sorted((a, b))): water for a, b, water in _SEA_CROSSINGS}
    return MapDef(name="Europe 1500", provinces=provinces, straits=straits)


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
            faith=province_faith(pid, OWNERS_1500.get(pid, owner)),
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
            fleets={w: dict(ships) for w, ships in STARTING_FLEETS.get(nid, {}).items()},
            colonies=dict(STARTING_COLONIES.get(nid, {})),
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
