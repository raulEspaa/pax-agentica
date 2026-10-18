"""The New World: colonies in regions beyond the sea, founded by expeditions and held by fleets.

The regions are not on the map: a crown with a port on the Atlantic (or the Baltic, the long
way round) sends expeditions from the menu of the New World. Each year an expedition makes
progress by a die, its crown's seamanship and the region's hardness; at 100% it founds a
colony, which pays its crown a yearly due. Every region holds only so many colonies among all
the crowns together, and at war a crown whose Atlantic fleet far outmatches an enemy's may take
that enemy's colonies. The three crowns that led the age each sail in their own way.
"""

from dataclasses import dataclass, field

from pax_agentica.engine.model import NationId, Region


@dataclass(frozen=True)
class ColonialSpirit:
    """How a crown goes about empire beyond the sea."""

    title: str
    words: str
    progress: dict[Region, int] = field(default_factory=dict)  # more each year, by region
    dues: dict[Region, float] = field(default_factory=dict)  # more of each colony's due
    seize: float | None = None  # the Atlantic fleet, times the enemy's, it takes colonies with


ALL = tuple(Region)

COLONIAL_SPIRITS: dict[NationId, ColonialSpirit] = {
    "spain": ColonialSpirit(
        "The Casa de Contratación",
        "every expedition 5 more progress a year; the silver of New Spain and Peru half again",
        progress=dict.fromkeys(ALL, 5),
        dues={Region.NEW_SPAIN: 0.5, Region.PERU: 0.5},
    ),
    "england": ColonialSpirit(
        "The Sea Dogs",
        "takes an enemy's colonies with a fleet only half again as strong as its own; 10 more "
        "progress a year in North America",
        progress={Region.NORTH_AMERICA: 10},
        seize=1.5,
    ),
    "france": ColonialSpirit(
        "New France",
        "the furs of North America half again, and 10 more progress a year there, where the "
        "nations of the woods are its allies",
        progress={Region.NORTH_AMERICA: 10},
        dues={Region.NORTH_AMERICA: 0.5},
    ),
}

# Viceroys and governors of the age, by crown; the others name governors of their own.
VICEROYS: dict[NationId, tuple[str, ...]] = {
    "spain": ("Antonio de Mendoza", "Francisco de Toledo", "Luis de Velasco", "Martín Enríquez",
              "Andrés Hurtado de Mendoza", "Blasco Núñez Vela"),
    "england": ("Walter Raleigh", "Humphrey Gilbert", "Ralph Lane", "Thomas Gates",
                "George Somers", "Richard Grenville"),
    "france": ("Jean-François de Roberval", "Samuel de Champlain", "Pierre Dugua de Mons",
               "Charles de Montmagny", "Nicolas Durand de Villegaignon", "Jacques Cartier"),
}  # fmt: skip
GOVERNORS = ("Gerhard Mercator", "Olof Larsson", "Ivan Kurbsky", "Jan Zamoyski", "Ahmed Reis",
             "Georg Fugger", "Lorenzo Tiepolo", "Heinrich Ehinger")  # fmt: skip

# The colonies of 1500: Hispaniola, eight years after Columbus.
STARTING_COLONIES: dict[NationId, dict[Region, int]] = {"spain": {Region.CARIBBEAN: 1}}
