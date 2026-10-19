"""The data model: the map, the nations, the treaties and the whole game state.

Everything is a Pydantic model so it serialises to JSON for free: replays, the web viewer and
LLM prompts all reuse the same types.

Immutability contract: the engine never mutates a state it receives. `resolve_turn` deep-copies
its input and only touches the copy, so from the outside every engine call is a pure function.
Small value objects (resources, map definitions, rules) are frozen outright.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator

from pax_agentica.engine.events import Event

type ProvinceId = str
type SeaId = str  # a zone of the sea
type NationId = str


def pair(a: NationId, b: NationId) -> tuple[NationId, NationId]:
    """The canonical (sorted) key for a relation between two nations."""
    return (a, b) if a <= b else (b, a)


class Terrain(StrEnum):
    PLAINS = "plains"
    FOREST = "forest"
    HILLS = "hills"
    MARSH = "marsh"
    MOUNTAINS = "mountains"


class Good(StrEnum):
    """What a province is known for, on top of its base output. Each yields its own mix of
    resources by development (see `Rules.good_yields`): gold far more than grain."""

    GRAIN = "grain"
    FISH = "fish"
    HORSES = "horses"
    WINE = "wine"
    SALT = "salt"
    WOOL = "wool"
    CLOTH = "cloth"  # the looms of Flanders, the silk of Lyon
    TIMBER = "timber"
    IRON = "iron"
    COPPER = "copper"
    FURS = "furs"
    SILVER = "silver"
    GOLD = "gold"
    SPICES = "spices"  # the trade of the Indies and the Levant


RESOURCE_NAMES = ("ducats", "manpower", "iron", "grain", "timber", "goods")
TRADED = ("grain", "iron", "timber", "goods")  # what the European market buys and sells


class Resources(BaseModel):
    """A bundle of the six national resources. Never negative."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ducats: NonNegativeInt = 0
    manpower: NonNegativeInt = 0
    iron: NonNegativeInt = 0
    grain: NonNegativeInt = 0
    timber: NonNegativeInt = 0
    goods: NonNegativeInt = 0  # cloth, glass, arms: made by workshops, wanted by markets

    def amounts(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in RESOURCE_NAMES}

    def __add__(self, other: Resources) -> Resources:
        return Resources(**{k: v + getattr(other, k) for k, v in self.amounts().items()})

    def __sub__(self, other: Resources) -> Resources:
        """Subtract, failing loudly (ValidationError) if any amount would go negative."""
        return Resources(**{k: v - getattr(other, k) for k, v in self.amounts().items()})

    def times(self, n: int) -> Resources:
        return Resources(**{k: v * n for k, v in self.amounts().items()})

    def capped_by(self, other: Resources) -> Resources:
        """The part of this bundle that `other` can actually pay."""
        return Resources(**{k: min(v, getattr(other, k)) for k, v in self.amounts().items()})

    def covers(self, cost: Resources) -> bool:
        return all(v >= getattr(cost, k) for k, v in self.amounts().items())

    def is_empty(self) -> bool:
        return self == Resources()

    def __str__(self) -> str:
        parts = [f"{v} {k}" for k, v in self.amounts().items() if v]
        return ", ".join(parts) if parts else "nothing"


# ---------------------------------------------------------------- buildings


class BuildingKind(StrEnum):
    # civil
    MARKETPLACE = "marketplace"
    FARM_ESTATES = "farm_estates"
    IRONWORKS = "ironworks"
    LUMBER_MILL = "lumber_mill"
    UNIVERSITY = "university"
    BANK = "bank"
    CATHEDRAL = "cathedral"
    # military
    BARRACKS = "barracks"
    ARMORY = "armory"
    TRAINING_GROUNDS = "training_grounds"
    FORT = "fort"
    CITADEL = "citadel"
    WORKSHOP = "workshop"
    STABLES = "stables"
    CANNON_FOUNDRY = "cannon_foundry"
    # great works: one per realm, felt across all of it
    MILITARY_ACADEMY = "military_academy"
    ARMS_MANUFACTORY = "arms_manufactory"
    POWDER_MILL = "powder_mill"
    ROYAL_EXCHANGE = "royal_exchange"
    OBSERVATORY = "observatory"


class TechBranch(StrEnum):
    MILITARY = "military"  # stronger armies
    ECONOMY = "economy"  # richer provinces
    ENGINEERING = "engineering"  # cheaper building and development
    NAVAL = "naval"  # stronger fleets, cheaper ships, the way to the New World
    ADMINISTRATION = "administration"  # a steadier realm, cheaper research, less infamy


class TechOption(BaseModel):
    """One of the doctrines a level offers: choosing it shuts the others out for good."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    effect: str  # what it does, in a few words
    effects: dict[str, float]  # see realm.EFFECTS for the keys
    lore: str = ""


class TechLevel(BaseModel):
    """One step of a technology branch: what it is called, what it brings, what it needs from
    another branch, and the doctrines to choose between when it is reached."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    unlocks: str  # what it brings, in one sentence
    lore: str = ""  # what it was, in history
    effects: dict[str, float] = Field(default_factory=dict)  # what it brings, as effects
    requires: tuple[TechBranch, int] | None = None  # a level of another branch first
    options: tuple[TechOption, ...] = ()


def _o(name: str, effect: str, effects: dict[str, float], lore: str = "") -> TechOption:
    return TechOption(name=name, effect=effect, effects=effects, lore=lore)


def default_tech_tree() -> dict[TechBranch, list[TechLevel]]:
    """Every branch also gives its per-level bonus (see Rules); these are the milestones, and at
    each the two doctrines a realm chooses between."""
    t = TechLevel
    return {
        TechBranch.MILITARY: [
            t(
                name="Pike and Shot",
                unlocks="the armory",
                lore=(
                    "Pikemen guard the arquebusiers while they reload: the square"
                    " that will rule the field."
                ),
                options=(
                    _o(
                        "Swiss pike drill",
                        "+5% morale",
                        {"morale": 0.05},
                        "The Swiss square that broke the knights of Burgundy.",
                    ),
                    _o(
                        "Arquebus volleys",
                        "+4% battle power",
                        {"battle_power": 0.04},
                        "Ranks of shot firing in turn, as at Cerignola.",
                    ),
                ),
            ),
            t(
                name="Bastions",
                unlocks="the citadel and the cannon foundry",
                lore=(
                    "Low, angled walls that shot glances off, the trace "
                    "italienne, and foundries to cast the guns that test them."
                ),
                options=(
                    _o(
                        "Siege trains",
                        "+1 to every siege roll of yours",
                        {"siege": 1},
                        "Oxen, gabions and great guns that follow the army to the walls.",
                    ),
                    _o(
                        "Garrison companies",
                        "forts +5%",
                        {"fort": 0.05},
                        "Paid companies kept in every fortress, all year round.",
                    ),
                ),
            ),
            t(
                name="Tercios",
                unlocks="training grounds and the military academy",
                lore=(
                    "Spain's regiments of pike, sword and shot, drilled to fight "
                    "as one, and schools to train their captains."
                ),
                options=(
                    _o(
                        "Old soldiers",
                        "victories season regiments half again as fast",
                        {"veterancy": 0.5},
                        "Veterans kept under the colours, war after war.",
                    ),
                    _o(
                        "Mass levies",
                        "+15% manpower",
                        {"manpower": 0.15},
                        "Every parish sends its men: numbers before drill.",
                    ),
                ),
            ),
            t(
                name="Field Artillery",
                unlocks="your attacks ignore one level of enemy forts",
                lore=(
                    "Lighter guns on wheeled carriages that keep pace with the "
                    "army and breach walls in days."
                ),
                requires=(TechBranch.ENGINEERING, 2),
                options=(
                    _o(
                        "Horse artillery",
                        "+5% battle power",
                        {"battle_power": 0.05},
                        "Light pieces that gallop with the cavalry.",
                    ),
                    _o(
                        "Siege engineers",
                        "+1 to every siege roll of yours",
                        {"siege": 1},
                        "Sappers and mines under the bastions.",
                    ),
                ),
            ),
            t(
                name="Military Revolution",
                unlocks="one more general",
                lore="Standing armies, drill and supply: war becomes the business of states.",
                options=(
                    _o(
                        "Standing army",
                        "+5% morale, and the army eats 10% less grain",
                        {"morale": 0.05, "grain_upkeep": -0.10},
                        "Regiments paid in peace as in war, in barracks and magazines.",
                    ),
                    _o(
                        "Drill and discipline",
                        "+6% battle power",
                        {"battle_power": 0.06},
                        "Maurice of Nassau's drill: every man a part of a machine.",
                    ),
                ),
            ),
        ],
        TechBranch.ECONOMY: [
            t(
                name="Banking",
                unlocks="the bank",
                lore=(
                    "The Fuggers and the Medici lend to kings, and bills of exchange cross Europe."
                ),
                options=(
                    _o(
                        "Bills of exchange",
                        "the merchants' cut 10% lower",
                        {"trade": 0.10},
                        "Paper that pays in Antwerp what was lent in Genoa.",
                    ),
                    _o(
                        "Crown monopolies",
                        "+5% ducats",
                        {"ducat_income": 0.05},
                        "Salt, alum and pepper sold by the crown alone.",
                    ),
                ),
            ),
            t(
                name="Printing Press",
                unlocks="the university and the observatory",
                lore="Gutenberg's press prints books by the thousand: learning becomes cheap.",
                options=(
                    _o(
                        "Academies",
                        "research 5% cheaper",
                        {"research": 0.05},
                        "Learned societies under royal patronage.",
                    ),
                    _o(
                        "Royal printers",
                        "stability 10% cheaper",
                        {"stability": 0.10},
                        "The crown's edicts, printed and read in every parish.",
                    ),
                ),
            ),
            t(
                name="Mercantilism",
                unlocks="marketplaces yield +150% instead of +100%, and the royal exchange",
                lore=(
                    "Gold is power: protect your own trades, tax the foreigner's,"
                    " and build an exchange."
                ),
                options=(
                    _o(
                        "Navigation acts",
                        "the merchants' cut 15% lower",
                        {"trade": 0.15},
                        "Your goods in your own ships, and the foreigner's taxed.",
                    ),
                    _o(
                        "Royal manufactories",
                        "+5% ducats",
                        {"ducat_income": 0.05},
                        "Tapestries, glass and mirrors made at the king's expense.",
                    ),
                ),
            ),
            t(
                name="Humanism",
                unlocks="the cathedral",
                lore="The scholars of the Renaissance return to the ancients, and to man.",
                options=(
                    _o(
                        "Tolerance",
                        "provinces of another faith lose a quarter less",
                        {"tolerance": 0.25},
                        "Erasmus' peace: the faiths may live side by side.",
                    ),
                    _o(
                        "Reform of the Church",
                        "stability 15% cheaper",
                        {"stability": 0.15},
                        "Councils and seminaries renew the faith, and its obedience.",
                    ),
                ),
            ),
            t(
                name="Cameralism",
                unlocks="one more building slot in every province",
                lore="The science of administration: counting, taxing and planning a realm.",
                options=(
                    _o(
                        "Excise",
                        "+7% ducats",
                        {"ducat_income": 0.07},
                        "A tax on every barrel of beer and every pound of salt.",
                    ),
                    _o(
                        "Granaries",
                        "+10% grain",
                        {"grain_income": 0.10},
                        "Public granaries against the lean years.",
                    ),
                ),
            ),
        ],
        TechBranch.ENGINEERING: [
            t(
                name="Blast Furnace",
                unlocks="ironworks",
                lore="Furnaces fed by water-driven bellows pour iron by the ton.",
                options=(
                    _o(
                        "Master masons",
                        "buildings and development 5% cheaper",
                        {"building": 0.05},
                        "Guilds of builders that move from site to site.",
                    ),
                    _o(
                        "Gunpowder mills",
                        "+1 to every siege roll of yours",
                        {"siege": 1},
                        "Saltpetre, sulphur and charcoal, ground by water.",
                    ),
                ),
            ),
            t(
                name="Water Mills",
                unlocks="farm estates and lumber mills yield +150% instead of +100%",
                lore="Wheels on every stream grind grain and saw timber.",
                options=(
                    _o(
                        "Polders",
                        "+5% grain",
                        {"grain_income": 0.05},
                        "Dikes and windmills win fields from the sea.",
                    ),
                    _o(
                        "Sawmills",
                        "buildings and development 5% cheaper",
                        {"building": 0.05},
                        "Timber cut by water, for ships and roofs.",
                    ),
                ),
            ),
            t(
                name="Roads and Canals",
                unlocks="armies eat 20% less grain",
                lore="Paved roads and locks move grain and soldiers faster.",
                options=(
                    _o(
                        "Post roads",
                        "+4% morale",
                        {"morale": 0.04},
                        "Couriers and magazines along the roads of war.",
                    ),
                    _o(
                        "Canals",
                        "the merchants' cut 10% lower",
                        {"trade": 0.10},
                        "Barges carry what carts cannot.",
                    ),
                ),
            ),
            t(
                name="Star Forts",
                unlocks="your forts and citadels give +35% instead of +25%",
                lore="Fortresses shaped like stars, every wall covered by another's fire.",
                requires=(TechBranch.MILITARY, 2),
                options=(
                    _o(
                        "Trace italienne",
                        "forts +5%",
                        {"fort": 0.05},
                        "Every bastion covering its neighbours.",
                    ),
                    _o(
                        "Corps of engineers",
                        "+1 to every siege roll of yours",
                        {"siege": 1},
                        "Vauban's science, turned on the enemy's walls.",
                    ),
                ),
            ),
            t(
                name="Grand Architecture",
                unlocks="provinces can grow to development 15",
                lore="Palladio and Bramante: domes and squares for cities that keep growing.",
                options=(
                    _o(
                        "Palaces",
                        "stability 10% cheaper",
                        {"stability": 0.10},
                        "A court that dazzles keeps the nobles near and quiet.",
                    ),
                    _o(
                        "Urban planning",
                        "buildings and development 10% cheaper",
                        {"building": 0.10},
                        "Straight streets, squares and fountains.",
                    ),
                ),
            ),
        ],
        TechBranch.NAVAL: [
            t(
                name="Caravels",
                unlocks="expeditions 5 more progress a year",
                lore="Lateen sails that beat into the wind: the ships of the discoveries.",
                effects={"colonial": 5},
                options=(
                    _o(
                        "Portolan charts",
                        "expeditions 5 more progress a year",
                        {"colonial": 5},
                        "Every cape and harbour drawn by the pilots of Sagres.",
                    ),
                    _o(
                        "Galley oarsmen",
                        "fleets +10%",
                        {"navy": 0.10},
                        "Convicts and slaves at the oars of the war galleys.",
                    ),
                ),
            ),
            t(
                name="Carracks",
                unlocks="ships 10% cheaper",
                lore="Great round ships, castled fore and aft, that carry an army's stores.",
                effects={"ship_cost": 0.10},
                requires=(TechBranch.ENGINEERING, 1),
                options=(
                    _o(
                        "Shipwrights' guilds",
                        "ships 15% cheaper more",
                        {"ship_cost": 0.15},
                        "Arsenals that launch a galley a day.",
                    ),
                    _o(
                        "Marines",
                        "a landing's beach 10% less of an advantage",
                        {"landing": 0.10},
                        "Soldiers who fight from ships and from boats.",
                    ),
                ),
            ),
            t(
                name="Galleons",
                unlocks="fleets +10%",
                lore="Lower, faster and heavier-gunned: the ship that crossed every ocean.",
                effects={"navy": 0.10},
                requires=(TechBranch.ENGINEERING, 2),
                options=(
                    _o(
                        "Broadside gunnery",
                        "fleets +10% more",
                        {"navy": 0.10},
                        "Guns along the sides, fired at once.",
                    ),
                    _o(
                        "Treasure fleets",
                        "the colonies send 25% more",
                        {"colonial_dues": 0.25},
                        "Convoys of galleons bring the silver home.",
                    ),
                ),
            ),
            t(
                name="Admiralty",
                unlocks="every port launches two more ships a year",
                lore="A board of the navy, its yards, its stores and its captains.",
                effects={"yards": 2},
                requires=(TechBranch.ECONOMY, 3),
                options=(
                    _o(
                        "Convoys",
                        "your blockaded ports lose half as much",
                        {"convoys": 0.5},
                        "Merchantmen sail together under escort.",
                    ),
                    _o(
                        "Privateers",
                        "takes colonies with a fleet only 1.5 times the enemy's",
                        {"privateers": 1.0},
                        "Letters of marque to every captain bold enough.",
                    ),
                ),
            ),
            t(
                name="Line of Battle",
                unlocks="fleets +15%",
                lore="Ships in a line, each firing its broadside in turn.",
                effects={"navy": 0.15},
                options=(
                    _o(
                        "Fighting instructions",
                        "fleets +10% more",
                        {"navy": 0.10},
                        "Every captain knows his place in the line.",
                    ),
                    _o(
                        "Amphibious warfare",
                        "a landing's beach 15% less of an advantage",
                        {"landing": 0.15},
                        "Flat boats, and men drilled to wade ashore.",
                    ),
                ),
            ),
        ],
        TechBranch.ADMINISTRATION: [
            t(
                name="Chancery",
                unlocks="stability 5% cheaper",
                lore="Secretaries, seals and registers: the king's will on paper.",
                effects={"stability": 0.05},
                options=(
                    _o(
                        "Secretaries of state",
                        "research 5% cheaper",
                        {"research": 0.05},
                        "Ministers who read every report.",
                    ),
                    _o(
                        "Royal council",
                        "stability 10% cheaper more",
                        {"stability": 0.10},
                        "The great lords bound to the crown's decisions.",
                    ),
                ),
            ),
            t(
                name="Tax registers",
                unlocks="+3% ducats",
                lore="Every hearth counted and every field assessed.",
                effects={"ducat_income": 0.03},
                options=(
                    _o(
                        "Tax farming",
                        "+5% ducats",
                        {"ducat_income": 0.05},
                        "Bankers buy the right to collect, and pay in advance.",
                    ),
                    _o(
                        "Cadastre",
                        "+10% manpower",
                        {"manpower": 0.10},
                        "Every village surveyed: the recruiters know where the men are.",
                    ),
                ),
            ),
            t(
                name="Intendants",
                unlocks="conquests breed 20% less infamy",
                lore="Royal officers in every province, answerable to the king alone.",
                effects={"infamy": 0.20},
                requires=(TechBranch.ECONOMY, 2),
                options=(
                    _o(
                        "Absolutism",
                        "stability 10% cheaper, and +3% battle power",
                        {"stability": 0.10, "battle_power": 0.03},
                        "L'État, c'est moi: no estates between the king and his subjects.",
                    ),
                    _o(
                        "Estates' consent",
                        "+5% ducats",
                        {"ducat_income": 0.05},
                        "Taxes voted by the estates are taxes paid.",
                    ),
                ),
            ),
            t(
                name="Diplomatic service",
                unlocks="conquests breed 10% less infamy",
                lore="Resident ambassadors in every court, and ciphers for their letters.",
                effects={"infamy": 0.10},
                options=(
                    _o(
                        "Balance of power",
                        "conquests breed 25% less infamy more",
                        {"infamy": 0.25},
                        "No crown may grow too great: so says every treaty.",
                    ),
                    _o(
                        "Court patronage",
                        "research 5% cheaper, stability 5% cheaper",
                        {"research": 0.05, "stability": 0.05},
                        "Painters, poets and scholars at the court's expense.",
                    ),
                ),
            ),
            t(
                name="Bureaucracy",
                unlocks="research 5% cheaper",
                lore="Offices, careers and archives: the state that outlives its kings.",
                effects={"research": 0.05},
                requires=(TechBranch.ECONOMY, 4),
                options=(
                    _o(
                        "Enlightened ministers",
                        "research 5% cheaper more",
                        {"research": 0.05},
                        "Reform from above, by reason and by decree.",
                    ),
                    _o(
                        "Standing bureaucracy",
                        "+5% ducats",
                        {"ducat_income": 0.05},
                        "Officials paid by salary, not by what they can take.",
                    ),
                ),
            ),
        ],
    }


class Trait(StrEnum):
    """A ruler's character. Some move the numbers a little; all of them tell an AI ruler (and a
    reader) who this person is."""

    WARLIKE = "warlike"  # +5% battle power
    CAUTIOUS = "cautious"  # forts +5%
    THRIFTY = "thrifty"  # +5% ducats
    PIOUS = "pious"  # stability 10% cheaper
    SCHOLAR = "scholar"  # research 10% cheaper
    BUILDER = "builder"  # buildings and development 8% cheaper
    CUNNING = "cunning"  # breaking a treaty costs 1 less stability
    CHARMING = "charming"  # every court warms to them: +2 opinion a year
    CRUEL = "cruel"  # +3% battle power, but every court cools: -1 opinion a year
    AMBITIOUS = "ambitious"  # hungry for land and glory
    MELANCHOLIC = "melancholic"  # withdrawn, brooding, hard to read


class Personality(StrEnum):
    """How an advisor leans when counselling the crown."""

    HAWK = "hawk"  # war is the answer
    DOVE = "dove"  # peace is cheaper
    SCHEMER = "schemer"  # serves themself first
    LOYAL = "loyal"  # serves the crown first
    FRUGAL = "frugal"  # counts every ducat
    VISIONARY = "visionary"  # thinks in generations


class Tactic(StrEnum):
    """How an attack is fought. Each wins against one posture and loses against another, and
    is only as good as the regiments that carry it."""

    ASSAULT = "assault"  # the pikes push straight in: beats skirmishers, breaks on a held line
    FLANK = "flank"  # the horse rides round: turns a held line, is caught by a sally
    BOMBARD = "bombard"  # the guns open first: shatters a sally, is picked off by skirmishers


class Posture(StrEnum):
    """How a province's garrison waits for an attack."""

    HOLD = "hold"  # a line of pikes behind what cover there is
    SKIRMISH = "skirmish"  # shot and bows thrown forward to harry
    SALLY = "sally"  # horse kept back to charge whoever comes


class Water(StrEnum):
    """The three waters a fleet can hold. Every coastal province looks onto one or two."""

    ATLANTIC = "atlantic"  # the ocean, the Channel, the North Sea
    BALTIC = "baltic"  # the Baltic and the Gulf of Bothnia
    MEDITERRANEAN = "mediterranean"  # with the Adriatic and the Black Sea


class Ship(StrEnum):
    GALLEY = "galley"  # oars: cheap, quick in calm inland seas, lost on the ocean
    GALLEON = "galleon"  # sail and guns: dear, the master of the ocean


class ShipSpec(BaseModel):
    """What a kind of ship costs and is worth in each water."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    cost: Resources
    pay: float  # ducats a year at war (0: the crews are pressed when needed)
    carries: int  # regiments it can land on an enemy shore
    strength: dict[Water, float]
    role: str


def default_ships() -> dict[Ship, ShipSpec]:
    return {
        Ship.GALLEY: ShipSpec(
            name="Galleys",
            cost=Resources(ducats=12, timber=3, manpower=1),
            pay=0.0,
            carries=1,
            strength={Water.MEDITERRANEAN: 1.5, Water.BALTIC: 1.0, Water.ATLANTIC: 0.5},
            role="oared war galleys: cheap, and masters of the calm inland seas",
        ),
        Ship.GALLEON: ShipSpec(
            name="Galleons",
            cost=Resources(ducats=30, timber=6, iron=2, goods=1),
            pay=0.0,
            carries=2,
            strength={Water.ATLANTIC: 2.5, Water.BALTIC: 2.0, Water.MEDITERRANEAN: 1.5},
            role="tall ships with broadsides of guns: dear, and the only masters of the ocean",
        ),
    }


class Region(StrEnum):
    """The lands beyond the sea that crowns may colonise: not on the map, but in the menu of
    the New World."""

    CARIBBEAN = "caribbean"
    BRAZIL = "brazil"
    GUINEA = "guinea"
    NEW_SPAIN = "new_spain"
    EAST_INDIES = "east_indies"
    PERU = "peru"
    NORTH_AMERICA = "north_america"


class ColonialGood(StrEnum):
    """What the colonies ship home, sold on Europe's markets at a price of its own."""

    SUGAR = "sugar"
    SILVER = "silver"
    SPICES = "spices"
    FURS = "furs"
    GOLD = "gold"


class GoodSpec(BaseModel):
    """A colonial good's price: its base, falling as the crowns ship more of it than Europe
    wants (its glut), never below a floor; silver also feeds the inflation of whoever ships it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    price: float  # ducats a cargo, when Europe wants all that comes
    glut: int  # cargoes a year Europe takes at full price, among all the crowns
    inflation: float = 0.0  # inflation for each ducat of it shipped home
    lore: str = ""


def default_goods() -> dict[ColonialGood, GoodSpec]:
    return {
        ColonialGood.SUGAR: GoodSpec(
            name="Sugar",
            price=2.0,
            glut=8,
            lore="White gold of the islands, sweetening every table in Christendom.",
        ),
        ColonialGood.SILVER: GoodSpec(
            name="Silver",
            price=3.0,
            glut=6,
            inflation=0.002,
            lore="Pieces of eight by the shipload: riches that make every price rise.",
        ),
        ColonialGood.SPICES: GoodSpec(
            name="Spices",
            price=3.0,
            glut=5,
            lore="Pepper, cloves and nutmeg, worth their weight in gold at Antwerp.",
        ),
        ColonialGood.FURS: GoodSpec(
            name="Furs", price=1.5, glut=8, lore="Beaver for the hats of every gentleman in Europe."
        ),
        ColonialGood.GOLD: GoodSpec(
            name="Gold",
            price=2.0,
            glut=6,
            lore="Gold dust and ivory from the forts of the Gold Coast.",
        ),
    }


class ColonyKind(StrEnum):
    """How a colony is founded and worked."""

    PLANTATION = (
        "plantation"  # fields and mines worked hard: the full cargo, and the natives' anger
    )
    POST = "post"  # a trading post: cheap and quick, a little cargo, little anger
    SETTLEMENT = "settlement"  # settlers who stay: slow to pay, growing, defending themselves


class ColonyKindSpec(BaseModel):
    """What each kind of colony costs, how fast it is founded and what it ships."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    cost: float  # times rules.expedition_cost
    progress: int  # more (or less) progress a year for its expedition
    cargo: float  # its share of the region's cargo when founded
    growth: float = 0.0  # more of it each year, up to `most`
    most: float = 1.0
    militia: int = 0  # regiments its own people raise to defend it
    anger: float = 1.0  # how much it angers the peoples of the land
    effect: str = ""


def default_colony_kinds() -> dict[ColonyKind, ColonyKindSpec]:
    return {
        ColonyKind.PLANTATION: ColonyKindSpec(
            name="Plantation",
            cost=1.0,
            progress=0,
            cargo=1.0,
            anger=1.5,
            effect="the full cargo of the region; angers the peoples of the land the most",
        ),
        ColonyKind.POST: ColonyKindSpec(
            name="Trading post",
            cost=0.5,
            progress=10,
            cargo=0.6,
            anger=0.5,
            effect="half the cost and a quicker voyage; 60% of the cargo; little anger",
        ),
        ColonyKind.SETTLEMENT: ColonyKindSpec(
            name="Settlement",
            cost=1.25,
            progress=-5,
            cargo=0.5,
            growth=0.08,
            most=1.5,
            militia=1,
            effect="half the cargo at first, growing to half again as much in twelve "
            "years; its settlers defend it",
        ),
    }


class Colony(BaseModel):
    """One colony of a crown: how it was founded, and when."""

    kind: ColonyKind = ColonyKind.PLANTATION
    founded: int = 1  # the turn


class Viceroy(BaseModel):
    """The crown's viceroy over a region where it holds a viceroyalty."""

    name: str
    skill: int = Field(ge=1, le=3)  # more cargo, and the colonies better held
    since: int  # the turn


class RegionSpec(BaseModel):
    """What a region beyond the sea offers, and how hard it is to hold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    opens: int  # the year the way there is known
    slots: int  # colonies it can hold, among all the crowns together
    yields: Resources  # each colony's yearly due to its crown, besides its cargo
    hardness: int  # taken off each year's progress: distance, fevers, those who live there
    goods: str  # what it sends home, in words
    lore: str
    good: ColonialGood = ColonialGood.SUGAR  # its cargo, sold at the good's price
    cargo: int = 2  # cargoes a plantation there ships a year
    people: str = ""  # who lives there
    natives: int = 0  # the regiments its peoples can field
    plunder: int = 0  # ducats for whoever breaks them


def default_regions() -> dict[Region, RegionSpec]:
    return {
        Region.CARIBBEAN: RegionSpec(
            name="The Caribbean",
            opens=1500,
            slots=4,
            yields=Resources(goods=1),
            hardness=0,
            goods="sugar and logwood",
            lore="Hispaniola, Cuba, the Antilles: the first landfall of the Indies.",
            good=ColonialGood.SUGAR,
            cargo=2,
            people="the Taíno and the Caribs",
            natives=4,
            plunder=20,
        ),
        Region.BRAZIL: RegionSpec(
            name="Brazil",
            opens=1500,
            slots=3,
            yields=Resources(timber=2),
            hardness=5,
            goods="brazilwood and sugar",
            lore="The coast Cabral sighted in 1500, red with the dyewood that gave it a name.",
            good=ColonialGood.SUGAR,
            cargo=2,
            people="the Tupi",
            natives=6,
            plunder=20,
        ),
        Region.GUINEA: RegionSpec(
            name="The Guinea coast",
            opens=1500,
            slots=3,
            yields=Resources(),
            hardness=5,
            goods="gold dust and ivory",
            lore="Forts on the Gold Coast, traded for by the castle of Elmina.",
            good=ColonialGood.GOLD,
            cargo=2,
            people="the kingdoms of the Akan and of Benin",
            natives=10,
            plunder=40,
        ),
        Region.EAST_INDIES: RegionSpec(
            name="The East Indies",
            opens=1511,
            slots=3,
            yields=Resources(goods=1),
            hardness=15,
            goods="pepper, cloves and nutmeg",
            lore="Malacca and the Spice Islands, round the Cape and across the Indian Ocean.",
            good=ColonialGood.SPICES,
            cargo=2,
            people="the sultanates of the Spice Islands",
            natives=12,
            plunder=60,
        ),
        Region.NEW_SPAIN: RegionSpec(
            name="New Spain",
            opens=1519,
            slots=2,
            yields=Resources(),
            hardness=10,
            goods="the silver of Zacatecas",
            lore="The empire of the Mexica, and the silver mines beyond it.",
            good=ColonialGood.SILVER,
            cargo=3,
            people="the Mexica empire of Moctezuma",
            natives=16,
            plunder=150,
        ),
        Region.PERU: RegionSpec(
            name="Peru",
            opens=1532,
            slots=2,
            yields=Resources(),
            hardness=15,
            goods="the silver mountain of Potosí",
            lore="The realm of the Inca, high in the Andes, and the mountain of silver.",
            good=ColonialGood.SILVER,
            cargo=4,
            people="the Inca empire of Atahualpa",
            natives=14,
            plunder=200,
        ),
        Region.NORTH_AMERICA: RegionSpec(
            name="North America",
            opens=1534,
            slots=5,
            yields=Resources(timber=2, grain=2),
            hardness=5,
            goods="furs, cod and timber",
            lore="The St Lawrence, the Chesapeake and the cold banks of cod.",
            good=ColonialGood.FURS,
            cargo=2,
            people="the Haudenosaunee and the Algonquian nations",
            natives=8,
            plunder=10,
        ),
    }


class Focus(StrEnum):
    """What a province's people turn their hands to. A focus strengthens one side of its
    output, the more the larger its town."""

    TRADE = "trade"  # more ducats
    FARMING = "farming"  # more grain
    MINING = "mining"  # more iron and timber
    GARRISON = "garrison"  # more manpower, defended harder
    LEARNING = "learning"  # cheaper to develop, and the realm's research cheaper
    SHIPYARD = "shipyard"  # more timber, and its yards launch more ships (a port only)


class DesignationSpec(BaseModel):
    """What a focused province becomes as it builds what its focus needs: a designation in
    three tiers. The focus alone is tier 1; one of its key works makes tier 2 (one more building
    slot); two make tier 3, with a landmark of its own, a bonus to the realm's provinces next to
    it and an effect felt across the realm (from no more than rules.designation_realm_cap of a
    kind)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    port_name: str | None = None  # its name in a port, if another
    keys: tuple[BuildingKind, ...]
    landmark: str
    neighbours: dict[str, float]  # output fields (or "defence") its neighbours gain, as shares
    neighbours_text: str
    realm: dict[str, float]  # effects on the realm (realm.py keys)
    realm_text: str
    lore: str = ""


def default_designations() -> dict[Focus, DesignationSpec]:
    b = BuildingKind
    return {
        Focus.TRADE: DesignationSpec(
            name="Trade town", port_name="Trade port",
            keys=(b.MARKETPLACE, b.BANK, b.WORKSHOP), landmark="the Exchange",
            neighbours={"ducats": 0.05}, neighbours_text="+5% ducats",
            realm={"trade": 0.05}, realm_text="the merchants' cut 5% lower",
            lore="Merchants' halls, counting houses and the bourse under arcades.",
        ),
        Focus.FARMING: DesignationSpec(
            name="Granary",
            keys=(b.FARM_ESTATES, b.LUMBER_MILL, b.MARKETPLACE), landmark="the royal granary",
            neighbours={"grain": 0.05}, neighbours_text="+5% grain",
            realm={"grain_upkeep": -0.05}, realm_text="armies eat 5% less grain",
            lore="Wheat for half a kingdom, stored against the lean years.",
        ),
        Focus.MINING: DesignationSpec(
            name="Arsenal",
            keys=(b.IRONWORKS, b.ARMORY, b.CANNON_FOUNDRY), landmark="the royal armoury",
            neighbours={"iron": 0.10}, neighbours_text="+10% iron",
            realm={"battle_power": 0.02}, realm_text="+2% battle power",
            lore="Forges, powder and the guns of the king.",
        ),
        Focus.GARRISON: DesignationSpec(
            name="Fortress",
            keys=(b.FORT, b.CITADEL, b.TRAINING_GROUNDS, b.BARRACKS), landmark="the great fortress",
            neighbours={"defence": 0.10}, neighbours_text="defended 10% harder",
            realm={"fort": 0.03}, realm_text="forts +3%",
            lore="A town that is a camp, behind walls that are a school of war.",
        ),
        Focus.LEARNING: DesignationSpec(
            name="University town",
            keys=(b.UNIVERSITY, b.CATHEDRAL, b.OBSERVATORY), landmark="the studium generale",
            neighbours={"ducats": 0.03}, neighbours_text="+3% ducats",
            realm={"research": 0.05}, realm_text="research 5% cheaper",
            lore="Colleges, presses and the lecture halls of a famous faculty.",
        ),
        Focus.SHIPYARD: DesignationSpec(
            name="Shipyard",
            keys=(b.LUMBER_MILL, b.WORKSHOP, b.IRONWORKS), landmark="the arsenal of ships",
            neighbours={"timber": 0.10}, neighbours_text="+10% timber",
            realm={"ship_cost": 0.10}, realm_text="ships 10% cheaper",
            lore="Slipways, ropewalks and the smell of pitch.",
        ),
    }  # fmt: skip


class PolicyAxis(StrEnum):
    """A great choice of how the realm is run: one side or the other, or neither."""

    ARMY = "army"
    ECONOMY = "economy"
    STATE = "state"


class PolicySide(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    effect: str
    effects: dict[str, float]
    lore: str = ""


def default_policies() -> dict[PolicyAxis, tuple[PolicySide, PolicySide]]:
    s = PolicySide
    return {
        PolicyAxis.ARMY: (
            s(name="Professional army",
              effect="+5% battle power, victories season a quarter faster, -10% manpower",
              effects={"battle_power": 0.05, "veterancy": 0.25, "manpower": -0.10},
              lore="Fewer men, paid, drilled and kept."),
            s(name="Militia levies", effect="+20% manpower, -4% morale",
              effects={"manpower": 0.20, "morale": -0.04},
              lore="Every village owes the king its young men."),
        ),
        PolicyAxis.ECONOMY: (
            s(name="Agrarian", effect="+10% grain, +5% manpower",
              effects={"grain_income": 0.10, "manpower": 0.05},
              lore="The land and those who work it come first."),
            s(name="Mercantile", effect="+5% ducats, the merchants' cut 10% lower",
              effects={"ducat_income": 0.05, "trade": 0.10},
              lore="Trade is the sinew of the state."),
        ),
        PolicyAxis.STATE: (
            s(name="Centralism", effect="+4% ducats, research 5% cheaper, stability 10% dearer",
              effects={"ducat_income": 0.04, "research": 0.05, "stability": -0.10},
              lore="One law, one tax, one court for the whole realm."),
            s(name="Fueros", effect="stability 15% cheaper, -3% ducats",
              effects={"stability": 0.15, "ducat_income": -0.03},
              lore="Every province keeps its old laws, and is the quieter for it."),
        ),
    }  # fmt: skip


class Faith(StrEnum):
    CATHOLIC = "catholic"
    PROTESTANT = "protestant"
    ORTHODOX = "orthodox"
    SUNNI = "sunni"


class Stance(StrEnum):
    """A court's declared attitude towards another, public to all Europe."""

    FRIEND = "friend"
    NEUTRAL = "neutral"
    RIVAL = "rival"


class AdvisorRole(StrEnum):
    TREASURER = "treasurer"  # the economy
    CHANCELLOR = "chancellor"  # learning and envoys
    MARSHAL = "marshal"  # the army


class Ruler(BaseModel):
    """The crowned head of a nation. Ages one year a turn, and one day dies."""

    title: str  # King, Queen, Emperor, Sultan, Tsar, Regent...
    name: str
    age: int
    administration: int = Field(ge=1, le=6)  # +2% ducat income per point
    diplomacy: int = Field(ge=1, le=6)  # cheaper stability; at 5+, betrayal costs less
    military: int = Field(ge=1, le=6)  # +2% battle power per point
    since: int  # the turn of the coronation
    reign: int = 0  # how many rulers came before in this game
    bio: str = ""  # who they were, as history remembers them
    traits: list[Trait] = Field(default_factory=list)  # their character
    agenda: str | None = None  # the reign's ambition (Rules.agendas)
    agenda_start: int = 0  # the deed's count when the agenda was taken
    agendas_done: int = 0  # ambitions fulfilled this reign


class RoyalAct(StrEnum):
    """What a crown can do by its own authority (see Rules.royal_acts)."""

    LEVY = "levy"  # an extraordinary levy: ducats
    PROGRESS = "progress"  # a royal progress through the provinces: stability
    BANNERS = "banners"  # call the banners: manpower
    PARDON = "pardon"  # a general pardon: unrest ends everywhere
    EMBASSY = "embassy"  # a royal embassy: a court thinks better of the realm
    PRESENCE = "presence"  # the ruler at the head of the army: morale this year
    CHURCH = "church"  # patronage of the Church: prestige


class RoyalActSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    cost: int  # authority
    effect: str
    lore: str = ""


def default_royal_acts() -> dict[RoyalAct, RoyalActSpec]:
    a = RoyalActSpec
    return {
        RoyalAct.LEVY: a(name="An extraordinary levy", cost=30,
                         effect="30 ducats, and 10 more for every point of administration",
                         lore="The Cortes are summoned, and grant the crown a servicio."),
        RoyalAct.PROGRESS: a(name="A royal progress", cost=40, effect="+1 stability",
                             lore="The court travels the realm, and every town sees its king."),
        RoyalAct.BANNERS: a(name="Call the banners", cost=25,
                            effect="2 manpower, and 1 more for every point of military skill",
                            lore="The nobles bring their men, as their oath demands."),
        RoyalAct.PARDON: a(name="A general pardon", cost=30,
                           effect="unrest ends in every province",
                           lore="Rebels forgiven are subjects regained."),
        RoyalAct.EMBASSY: a(name="A royal embassy", cost=15,
                            effect="a court of your choice thinks 25 better of you",
                            lore="A prince of the blood, gifts and a long letter."),
        RoyalAct.PRESENCE: a(name="The ruler leads the army", cost=30,
                             effect="+8% morale this year",
                             lore="The king rides with his soldiers, and they fight for him."),
        RoyalAct.CHURCH: a(name="Patronage of the Church", cost=25, effect="+5 prestige",
                           lore="Chapels, relics and bishops who preach the crown's cause."),
    }  # fmt: skip


class AgendaSpec(BaseModel):
    """A reign's ambition: a deed to do so many times while the ruler reigns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    deed: str  # the counter in NationState.deeds it measures
    target: int
    text: str
    skill: str  # the ruler's skill that makes it likelier to be offered


def default_agendas() -> dict[str, AgendaSpec]:
    g = AgendaSpec
    return {
        "expand": g(name="Enlarge the realm", deed="provinces", target=2,
                    text="win two provinces", skill="military"),
        "victory": g(name="A warrior's glory", deed="battles", target=4,
                     text="win four battles", skill="military"),
        "build": g(name="A builder's reign", deed="works", target=3,
                   text="raise three works or levels of them", skill="administration"),
        "develop": g(name="A prosperous realm", deed="development", target=5,
                     text="develop the provinces five levels", skill="administration"),
        "faith": g(name="Defender of the faith", deed="conversions", target=2,
                   text="bring two provinces to the realm's faith", skill="diplomacy"),
        "alliances": g(name="The peacemaker", deed="treaties", target=2,
                       text="sign two alliances, pacts or marriages", skill="diplomacy"),
    }  # fmt: skip


class Advisor(BaseModel):
    """A councillor: hired once, paid every year, and effective by skill (1 to 3)."""

    id: int
    name: str
    role: AdvisorRole
    skill: int = Field(ge=1, le=3)
    personality: Personality = Personality.LOYAL


class BuildingCategory(StrEnum):
    CIVIL = "civil"
    MILITARY = "military"


class Settlement(BaseModel):
    """What a province's chief town has grown into: from a hamlet to a great city. Development
    decides it, and it decides how many works the province has room for."""

    model_config = ConfigDict(frozen=True)

    name: str  # "Market town"
    min_development: int
    building_slots: int


def default_settlements() -> tuple[Settlement, ...]:
    return (
        Settlement(name="Hamlet", min_development=1, building_slots=4),
        Settlement(name="Village", min_development=2, building_slots=5),
        Settlement(name="Market town", min_development=4, building_slots=6),
        Settlement(name="City", min_development=6, building_slots=7),
        Settlement(name="Great city", min_development=9, building_slots=8),
    )


class BuildingSpec(BaseModel):
    """What a building costs and does. The effect text is for humans and prompts; the numbers
    behind it live in `Rules` and `mechanics.py`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    category: BuildingCategory
    cost: Resources
    effect: str
    requires: BuildingKind | None = None
    requires_tech: tuple[TechBranch, int] | None = None  # a technology level to unlock it
    unique: bool = False  # a great work: one per realm, its effect felt across all of it
    consumes: Resources = Resources()  # a year; a building whose inputs cannot be paid stands idle
    max_level: int = 1  # how far it can be upgraded: each level does (and eats) more


def default_buildings() -> dict[BuildingKind, BuildingSpec]:
    civil, military = BuildingCategory.CIVIL, BuildingCategory.MILITARY
    return {
        BuildingKind.MARKETPLACE: BuildingSpec(
            name="Marketplace",
            category=civil,
            cost=Resources(ducats=40, iron=2, timber=12),
            effect="doubles the province's ducats (at least +1), selling a bale of goods a year",
            consumes=Resources(goods=1),
            max_level=3,
        ),
        BuildingKind.FARM_ESTATES: BuildingSpec(
            name="Farm estates",
            category=civil,
            cost=Resources(ducats=30, iron=2, timber=10),
            effect="doubles the province's grain (at least +1); its ploughs wear a timber a year",
            consumes=Resources(timber=1),
            max_level=3,
        ),
        BuildingKind.IRONWORKS: BuildingSpec(
            name="Ironworks",
            category=civil,
            cost=Resources(ducats=45, iron=4, timber=12),
            effect="doubles the province's iron (at least +1), burning 2 timber a year as charcoal",
            requires_tech=(TechBranch.ENGINEERING, 1),
            consumes=Resources(timber=2),
            max_level=3,
        ),
        BuildingKind.LUMBER_MILL: BuildingSpec(
            name="Lumber mill",
            category=civil,
            cost=Resources(ducats=35, iron=6, timber=4),
            effect="doubles the province's timber (at least +2); its saws wear an iron a year",
            consumes=Resources(iron=1),
            max_level=3,
        ),
        BuildingKind.UNIVERSITY: BuildingSpec(
            name="University",
            category=civil,
            cost=Resources(ducats=75, iron=4, timber=20),
            effect="developing this province costs 30% fewer ducats; it buys a bale of goods "
            "(books) a year",
            requires_tech=(TechBranch.ECONOMY, 2),
            consumes=Resources(goods=1),
        ),
        BuildingKind.BANK: BuildingSpec(
            name="Bank",
            category=civil,
            cost=Resources(ducats=65, iron=6, timber=12),
            effect="+3 ducats and +50% of the province's ducats; its bankers take a bale of goods "
            "(plate and silks) a year",
            consumes=Resources(goods=1),
            requires_tech=(TechBranch.ECONOMY, 1),
            max_level=3,
        ),
        BuildingKind.CATHEDRAL: BuildingSpec(
            name="Cathedral",
            category=civil,
            cost=Resources(ducats=90, manpower=2, iron=6, timber=30),
            effect="+1 manpower and +25% of the province's ducats; a conquered province settles "
            "twice as fast; candles and vestments take a bale of goods a year",
            consumes=Resources(goods=1),
            requires_tech=(TechBranch.ECONOMY, 4),
            max_level=2,
        ),
        BuildingKind.BARRACKS: BuildingSpec(
            name="Barracks",
            category=military,
            cost=Resources(ducats=40, iron=6, timber=10),
            effect="doubles the province's manpower (at least +1), which also raises the cap; "
            "the garrison eats 2 grain and wears an iron a year",
            consumes=Resources(grain=2, iron=1),
            max_level=3,
        ),
        BuildingKind.ARMORY: BuildingSpec(
            name="Armory",
            category=military,
            cost=Resources(ducats=45, iron=12, timber=8),
            effect="regiments recruited here need half the iron",
            requires_tech=(TechBranch.MILITARY, 1),
        ),
        BuildingKind.TRAINING_GROUNDS: BuildingSpec(
            name="Training grounds",
            category=military,
            cost=Resources(ducats=55, manpower=2, iron=4, timber=12),
            effect="the garrison here fights 20% harder",
            requires_tech=(TechBranch.MILITARY, 3),
            max_level=3,
        ),
        BuildingKind.FORT: BuildingSpec(
            name="Fort",
            category=military,
            cost=Resources(ducats=45, iron=12, timber=18),
            effect="defenders here fight 25% harder, and an attacker must besiege its walls; its "
            "garrison costs a ducat a year, unpaid it stands unmanned",
            consumes=Resources(ducats=1),
            max_level=2,
        ),
        BuildingKind.CITADEL: BuildingSpec(
            name="Citadel",
            category=military,
            cost=Resources(ducats=80, manpower=2, iron=20, timber=25),
            effect="defenders here fight another 25% harder, and its walls add a level to the "
            "siege; it costs 2 ducats a year, unpaid it stands unmanned",
            consumes=Resources(ducats=2),
            requires=BuildingKind.FORT,
            requires_tech=(TechBranch.MILITARY, 2),
            max_level=2,
        ),
        BuildingKind.WORKSHOP: BuildingSpec(
            name="Workshops",
            category=civil,
            cost=Resources(ducats=40, iron=6, timber=12),
            effect="turn 2 iron and 2 timber into goods: 2 + development / 3 bales a year",
            consumes=Resources(iron=2, timber=2),
            max_level=3,
        ),
        BuildingKind.STABLES: BuildingSpec(
            name="Stables",
            category=military,
            cost=Resources(ducats=35, iron=2, timber=12),
            effect="lets this province raise cavalry",
        ),
        BuildingKind.CANNON_FOUNDRY: BuildingSpec(
            name="Cannon foundry",
            category=military,
            cost=Resources(ducats=70, iron=16, timber=10),
            effect="lets this province cast artillery; it melts 2 iron a year",
            requires_tech=(TechBranch.MILITARY, 2),
            consumes=Resources(iron=2),
        ),
        BuildingKind.MILITARY_ACADEMY: BuildingSpec(
            name="Military academy",
            category=military,
            cost=Resources(ducats=115, iron=10, timber=20),
            effect="one more general for the realm; generals appointed here start a star higher",
            requires_tech=(TechBranch.MILITARY, 3),
            unique=True,
        ),
        BuildingKind.ARMS_MANUFACTORY: BuildingSpec(
            name="Arms manufactory",
            category=military,
            cost=Resources(ducats=105, iron=16, timber=16),
            effect="regiments raised anywhere in the realm need half the iron and no goods; "
            "it works 3 iron a year",
            requires_tech=(TechBranch.MILITARY, 1),
            unique=True,
            consumes=Resources(iron=3),
        ),
        BuildingKind.POWDER_MILL: BuildingSpec(
            name="Powder mill",
            category=military,
            cost=Resources(ducats=95, iron=10, timber=18),
            effect="+5% battle power, and your assaults knock one more fort level off; it burns "
            "2 timber a year",
            requires_tech=(TechBranch.MILITARY, 2),
            unique=True,
            consumes=Resources(timber=2),
        ),
        BuildingKind.ROYAL_EXCHANGE: BuildingSpec(
            name="Royal exchange",
            category=civil,
            cost=Resources(ducats=130, iron=6, timber=22),
            effect="+10% ducat income across the realm; it trades 2 bales of goods a year",
            requires_tech=(TechBranch.ECONOMY, 3),
            consumes=Resources(goods=2),
            unique=True,
        ),
        BuildingKind.OBSERVATORY: BuildingSpec(
            name="Observatory",
            category=civil,
            cost=Resources(ducats=95, iron=8, timber=16),
            effect="research 15% cheaper",
            requires_tech=(TechBranch.ECONOMY, 2),
            unique=True,
        ),
    }


# ---------------------------------------------------------------- regiments


class UnitKind(StrEnum):
    INFANTRY = "infantry"
    ARCHERS = "archers"
    CAVALRY = "cavalry"
    ARTILLERY = "artillery"


class UnitSpec(BaseModel):
    """One kind of regiment: what it costs, what it eats and how it fights. A regiment's strength
    is its attack (or defence) times the terrain it fights on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    cost: Resources | None = None  # None: the rules' recruit_cost, the price of a pikeman
    pay: float = 1.0  # times the rules' yearly pay per regiment
    rations: float = 1.0  # times the rules' yearly grain per regiment
    attack: float
    defence: float
    terrain: dict[Terrain, float] = Field(default_factory=dict)  # strength on that ground
    requires: BuildingKind | None = None  # in the province that raises it
    role: str  # one line, for humans and prompts


class NationalUnit(BaseModel):
    """The regiments a crown was famed for: one kind of its army fights under its own name, and
    better (and sometimes for less) than anyone else's of that kind."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: UnitKind
    name: str  # "Tercios"
    attack: float = 1.0  # times the kind's
    defence: float = 1.0
    terrain: dict[Terrain, float] = Field(
        default_factory=dict
    )  # replaces the kind's on that ground
    cost: float = 1.0  # times the kind's price
    lore: str


def default_national_units() -> dict[str, NationalUnit]:
    return {
        "spain": NationalUnit(
            kind=UnitKind.INFANTRY,
            name="Tercios",
            attack=1.15,
            defence=1.15,
            lore=(
                "Pike, sword and shot in one square: for a century no field army could break them."
            ),
        ),
        "austria": NationalUnit(
            kind=UnitKind.INFANTRY,
            name="Landsknechte",
            attack=1.15,
            cost=0.85,
            lore=(
                "Maximilian's hired pikemen in slashed doublets, paid by the month and feared "
                "everywhere."
            ),
        ),
        "france": NationalUnit(
            kind=UnitKind.CAVALRY,
            name="Gendarmes",
            attack=1.3,
            defence=1.15,
            lore="The heavy lances of the French nobility, the best armoured horse in Christendom.",
        ),
        "england": NationalUnit(
            kind=UnitKind.ARCHERS,
            name="Longbowmen",
            defence=1.25,
            cost=0.8,
            lore=(
                "Yeomen who have practised at the butts since boyhood, cheap to raise and deadly "
                "in line."
            ),
        ),
        "ottomans": NationalUnit(
            kind=UnitKind.ARCHERS,
            name="Janissaries",
            attack=1.35,
            defence=1.15,
            lore=(
                "The Sultan's standing infantry, raised from childhood, the first in Europe to "
                "fight with guns."
            ),
        ),
        "poland": NationalUnit(
            kind=UnitKind.CAVALRY,
            name="Winged Hussars",
            attack=1.35,
            terrain={Terrain.PLAINS: 1.45},
            lore="Lances and feathered wings: on open ground nothing stands before their charge.",
        ),
        "russia": NationalUnit(
            kind=UnitKind.ARCHERS,
            name="Streltsy",
            defence=1.2,
            cost=0.85,
            lore=(
                "Musketeers with bardiches, settled in their own quarters of every town, loyal to"
                " the Tsar."
            ),
        ),
        "sweden": NationalUnit(
            kind=UnitKind.INFANTRY,
            name="Dalecarlians",
            defence=1.2,
            terrain={Terrain.FOREST: 1.15, Terrain.HILLS: 1.15},
            lore="Peasant pikemen of the mining valleys, who made and unmade the kings of Sweden.",
        ),
        "brandenburg": NationalUnit(
            kind=UnitKind.CAVALRY,
            name="Reiters",
            attack=1.2,
            terrain={Terrain.FOREST: 1.0},
            lore=(
                "German horse with wheel-lock pistols, who fire in ranks and turn away: at home "
                "in any ground."
            ),
        ),
    }


def default_units() -> dict[UnitKind, UnitSpec]:
    return {
        UnitKind.INFANTRY: UnitSpec(
            name="Pikemen",
            attack=1.0,
            defence=1.0,
            role="the backbone of every army: cheap and steady on any ground",
        ),
        UnitKind.ARCHERS: UnitSpec(
            name="Archers and arquebusiers",
            cost=Resources(ducats=7, manpower=2, iron=1, timber=2, goods=1),
            attack=0.8,
            defence=1.3,
            terrain={Terrain.FOREST: 1.2, Terrain.HILLS: 1.2},
            role="hold the line: strong in defence, best in forests and hills",
        ),
        UnitKind.CAVALRY: UnitSpec(
            name="Cavalry",
            cost=Resources(ducats=14, manpower=2, iron=3),
            pay=2.0,
            rations=2.0,
            attack=1.5,
            defence=0.9,
            terrain={
                Terrain.PLAINS: 1.25,
                Terrain.FOREST: 0.75,
                Terrain.MARSH: 0.6,
                Terrain.MOUNTAINS: 0.6,
            },
            requires=BuildingKind.STABLES,
            role="the charge: the strongest attack, deadly on open plains, lost in marsh and "
            "mountains",
        ),
        UnitKind.ARTILLERY: UnitSpec(
            name="Artillery",
            cost=Resources(ducats=20, manpower=1, iron=6, timber=2, goods=2),
            pay=2.0,
            attack=1.1,
            defence=1.2,
            requires=BuildingKind.CANNON_FOUNDRY,
            role="breaks walls: every tenth of an attacking army in guns knocks one fort level off",
        ),
    }


# ---------------------------------------------------------------- monuments


class MonumentSpec(BaseModel):
    """A great building of its age, standing in one province: whoever holds the province enjoys
    it, and can raise it level by level (0 is a site where it is not yet built)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    bonus: str  # the `Modifiers` field it raises
    per_level: float
    effect: str  # per level, in words
    lore: str
    level_1500: int = Field(ge=0, le=3)


def default_monuments() -> dict[str, MonumentSpec]:
    m = MonumentSpec
    return {
        "london": m(
            name="Westminster Abbey",
            bonus="stability_discount",
            per_level=0.08,
            effect="stability 8% cheaper",
            level_1500=2,
            lore="Where every English monarch since the Conqueror has been crowned; a crown "
            "blessed here sits easier.",
        ),
        "paris": m(
            name="Notre-Dame de Paris",
            bonus="research_discount",
            per_level=0.05,
            effect="research 5% cheaper",
            level_1500=2,
            lore="The cathedral on the Île de la Cité, beside the schools that made Paris the "
            "lecture hall of Christendom.",
        ),
        "constantinople": m(
            name="Hagia Sophia",
            bonus="ducat_income",
            per_level=0.03,
            effect="+3% ducats",
            level_1500=3,
            lore="Justinian's dome, a mosque since 1453: the jewel of the city that sits "
            "astride two continents and their trade.",
        ),
        "andalusia": m(
            name="The Alhambra",
            bonus="ducat_income",
            per_level=0.04,
            effect="+4% ducats",
            level_1500=2,
            lore="The red palace of the Nasrid sultans, surrendered to Ferdinand and Isabella "
            "in 1492 with all the silk trade of Granada.",
        ),
        "seville": m(
            name="The Giralda",
            bonus="ducat_income",
            per_level=0.03,
            effect="+3% ducats",
            level_1500=1,
            lore="The minaret of the Almohads, now the bell tower of the largest cathedral in "
            "Christendom, finished in 1506. Below it, the Casa de Contratación will weigh every "
            "ounce of the gold of the Indies.",
        ),
        "madrid": m(
            name="El Escorial",
            bonus="building_discount",
            per_level=0.06,
            effect="buildings and development 6% cheaper",
            level_1500=0,
            lore="Philip II will raise it in the 1560s: monastery, palace and library in grey "
            "granite. In 1500 it is only a hillside.",
        ),
        "vienna": m(
            name="St. Stephen's Cathedral",
            bonus="fort_bonus_per_level",
            per_level=0.05,
            effect="forts +5% stronger",
            level_1500=2,
            lore="Its south tower watches the Danube road; when the Turk comes, the city's "
            "defence is directed from its height.",
        ),
        "moscow": m(
            name="The Kremlin",
            bonus="battle_power",
            per_level=0.03,
            effect="+3% battle power",
            level_1500=2,
            lore="Ivan III has just rebuilt its red walls with Italian masons: the fortress "
            "heart of a Russia that calls itself the Third Rome.",
        ),
        "stockholm": m(
            name="Tre Kronor",
            bonus="fort_bonus_per_level",
            per_level=0.05,
            effect="forts +5% stronger",
            level_1500=1,
            lore="The castle of the Three Crowns on the islet of Stockholm, keep of whoever "
            "rules Sweden.",
        ),
        "venice": m(
            name="The Arsenal of Venice",
            bonus="battle_power",
            per_level=0.03,
            effect="+3% battle power",
            level_1500=2,
            lore="The greatest workshop in Europe: sixteen thousand men can fit out a galley "
            "in a day.",
        ),
        "florence": m(
            name="Santa Maria del Fiore",
            bonus="research_discount",
            per_level=0.05,
            effect="research 5% cheaper",
            level_1500=3,
            lore="Brunelleschi's dome, the largest since antiquity, over the city of the "
            "Medici, of Leonardo and of Machiavelli.",
        ),
        "rome": m(
            name="St. Peter's Basilica",
            bonus="stability_discount",
            per_level=0.08,
            effect="stability 8% cheaper",
            level_1500=0,
            lore="Old St. Peter's is crumbling; in 1506 Pope Julius II will lay the first "
            "stone of a new basilica, and it will take a century.",
        ),
        "krakow": m(
            name="Wawel Castle",
            bonus="fort_bonus_per_level",
            per_level=0.05,
            effect="forts +5% stronger",
            level_1500=2,
            lore="The Jagiellonian seat on its rock over the Vistula, crowning a kingdom that "
            "stretches to the Black Sea.",
        ),
        "buda": m(
            name="The Corvinian Library",
            bonus="research_discount",
            per_level=0.05,
            effect="research 5% cheaper",
            level_1500=2,
            lore="King Matthias Corvinus gathered two thousand illuminated codices in his palace "
            "on Castle Hill, the greatest library north of the Alps after the Vatican's.",
        ),
        "bohemia": m(
            name="St. Vitus Cathedral",
            bonus="stability_discount",
            per_level=0.06,
            effect="stability 6% cheaper",
            level_1500=1,
            lore="Peter Parler's Gothic choir above Prague, left unfinished by the Hussite wars; "
            "the crown of St. Wenceslas waits in its chapel.",
        ),
        "lithuania": m(
            name="Trakai Island Castle",
            bonus="fort_bonus_per_level",
            per_level=0.05,
            effect="forts +5% stronger",
            level_1500=1,
            lore="The red-brick castle of Grand Duke Vytautas on its lake, from which Lithuania "
            "once ruled from the Baltic to the Black Sea.",
        ),
        "rhineland": m(
            name="Cologne Cathedral",
            bonus="building_discount",
            per_level=0.05,
            effect="buildings and development 5% cheaper",
            level_1500=1,
            lore="Begun in 1248 and still unfinished, a crane standing on its south tower for "
            "centuries.",
        ),
        "prussia": m(
            name="Marienburg",
            bonus="battle_power",
            per_level=0.03,
            effect="+3% battle power",
            level_1500=2,
            lore="The brick castle of the Teutonic Knights, the largest in the world, lost to "
            "Poland and still a soldier's school.",
        ),
        "zealand": m(
            name="Kronborg",
            bonus="ducat_income",
            per_level=0.03,
            effect="+3% ducats",
            level_1500=0,
            lore="Where the Øresund narrows to a cannon shot, every ship pays the Sound Dues; "
            "the great castle comes in 1574.",
        ),
        "galicia": m(
            name="Santiago de Compostela",
            bonus="stability_discount",
            per_level=0.06,
            effect="stability 6% cheaper",
            level_1500=2,
            lore="The end of the Way of St. James, where pilgrims from all of Europe come to "
            "the apostle's tomb.",
        ),
    }


# ---------------------------------------------------------------- the map (static)


class ProvinceDef(BaseModel):
    """The fixed geography of a province. Never changes during a game."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ProvinceId
    name: str
    terrain: Terrain
    good: Good
    lon: float  # position, for the viewer
    lat: float
    neighbors: tuple[ProvinceId, ...]  # land borders
    sea_neighbors: tuple[ProvinceId, ...] = ()  # straits: crossings that favour the defender
    coasts: tuple[Water, ...] = ()  # the waters it looks onto (of its sea zones)
    seas: tuple[SeaId, ...] = ()  # the sea zones it looks onto: its ports, and where it is landed


class SeaZoneDef(BaseModel):
    """A zone of the sea: fleets sail from zone to zone as armies march between provinces."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: SeaId
    name: str
    water: Water  # what kind of sea it is: what galleys and galleons are worth there
    neighbors: tuple[SeaId, ...]
    coasts: tuple[ProvinceId, ...]  # the provinces it washes


class MapDef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    provinces: dict[ProvinceId, ProvinceDef]
    seas: dict[SeaId, SeaZoneDef] = Field(default_factory=dict)
    straits: dict[str, SeaId] = Field(default_factory=dict)  # "a|b" (sorted): the zone crossed

    def strait_sea(self, a: ProvinceId, b: ProvinceId) -> SeaId | None:
        """The sea zone a crossing between two provinces goes over (None: a land border)."""
        return self.straits.get("|".join(sorted((a, b))))

    def strait_water(self, a: ProvinceId, b: ProvinceId) -> Water | None:
        sea = self.strait_sea(a, b)
        return self.seas[sea].water if sea in self.seas else None

    def coastal(self, water: Water) -> tuple[ProvinceId, ...]:
        return tuple(pid for pid, p in self.provinces.items() if water in p.coasts)

    def shared_seas(self, a: ProvinceId, b: ProvinceId) -> tuple[SeaId, ...]:
        """The sea zones both provinces look onto: where an army may be carried from one to
        the other."""
        there = set(self.provinces[b].seas)
        return tuple(z for z in self.provinces[a].seas if z in there)

    def adjacent(self, a: ProvinceId, b: ProvinceId) -> bool:
        p = self.provinces[a]
        return b in p.neighbors or b in p.sea_neighbors

    def is_sea_crossing(self, a: ProvinceId, b: ProvinceId) -> bool:
        return b in self.provinces[a].sea_neighbors

    def all_neighbors(self, a: ProvinceId) -> tuple[ProvinceId, ...]:
        p = self.provinces[a]
        return p.neighbors + p.sea_neighbors


# ---------------------------------------------------------------- the rules (tunable)


# rules that games saved by older versions still carry, and that no longer mean anything
RETIRED_RULES = ("building_slots", "development_per_building_slot")


class Rules(BaseModel):
    """Every number the engine uses. Part of the state so a tournament can vary them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _forget_retired(cls, data: Any) -> Any:
        """A game saved before a rule was retired still loads: the rule is dropped (the
        settlements took the fixed building slots' place)."""
        if isinstance(data, dict) and any(k in data for k in RETIRED_RULES):
            data = {k: v for k, v in data.items() if k not in RETIRED_RULES}
        if isinstance(data, dict) and isinstance(data.get("tech_tree"), dict):
            # a tree saved before the doctrines and the naval and administrative branches: the
            # game takes today's tree, and the costs of the branches it lacked
            tree = data["tech_tree"]
            if set(tree) != {b.value for b in TechBranch} or not any(
                isinstance(level, dict) and level.get("options")
                for levels in tree.values()
                for level in levels
            ):
                data = {k: v for k, v in data.items() if k != "tech_tree"}
            costs = data.get("tech_costs")
            if isinstance(costs, dict) and set(costs) != {b.value for b in TechBranch}:
                data = {k: v for k, v in data.items() if k != "tech_costs"}
        regions = data.get("regions") if isinstance(data, dict) else None
        if isinstance(regions, dict) and any(
            isinstance(r, dict) and "good" not in r for r in regions.values()
        ):  # regions saved before the colonial goods: the game takes today's regions
            data = {k: v for k, v in data.items() if k != "regions"}
        if isinstance(data, dict) and isinstance(data.get("ships"), dict):
            # ships saved before a field was added take it from the ship of the same kind
            defaults = default_ships()
            data = {
                **data,
                "ships": {
                    kind: {**defaults[Ship(kind)].model_dump(), **spec}
                    if isinstance(spec, dict) and kind in Ship._value2member_map_
                    else spec
                    for kind, spec in data["ships"].items()
                },
            }
        return data

    # economy
    base_grain_per_province: int = 3
    base_iron_per_province: int = 1  # every province has a smithy; iron provinces have mines
    base_timber_per_province: int = 1  # every province has woodland; timber provinces forests
    good_yield_per_development: int = 1  # kept for older rules; `good_yields` decides
    # what each good adds, per level of development
    good_yields: dict[Good, dict[str, float]] = Field(
        default_factory=lambda: {
            Good.GRAIN: {"grain": 1.5},
            Good.FISH: {"grain": 1.0, "ducats": 0.5},
            Good.HORSES: {"grain": 0.5, "manpower": 0.5},
            Good.WINE: {"ducats": 1.5},
            Good.SALT: {"ducats": 1.5},
            Good.WOOL: {"goods": 0.5, "ducats": 1.0},
            Good.CLOTH: {"goods": 1.0, "ducats": 0.5},
            Good.TIMBER: {"timber": 1.5},
            Good.IRON: {"iron": 1.25},
            Good.COPPER: {"iron": 0.5, "ducats": 1.25},
            Good.FURS: {"ducats": 1.25, "goods": 0.5},
            Good.SILVER: {"ducats": 2.0},
            Good.GOLD: {"ducats": 2.5},
            Good.SPICES: {"ducats": 2.0, "goods": 0.5},
        }
    )
    # a province's workings (its mine, vineyard, fishery...): each level adds half its good again
    workings: dict[Good, str] = Field(
        default_factory=lambda: {
            Good.GRAIN: "Great estates",
            Good.FISH: "Fisheries",
            Good.HORSES: "Stud farms",
            Good.WINE: "Vineyards",
            Good.SALT: "Salt works",
            Good.WOOL: "Sheepwalks",
            Good.CLOTH: "Looms",
            Good.TIMBER: "Woodcutters",
            Good.IRON: "Iron mines",
            Good.COPPER: "Copper mines",
            Good.FURS: "Trading posts",
            Good.SILVER: "Silver mines",
            Good.GOLD: "Gold mines",
            Good.SPICES: "Warehouses",
        }
    )
    workings_bonus: float = 0.5  # of the good's yield, per level
    max_workings: int = 3
    improve_cost: Resources = Resources(ducats=35, timber=6)  # times the new level
    stability_income_bonus: float = 0.1  # ducat income x (1 + bonus * stability)
    # what the land itself adds to (or takes from) a province's yield, whatever its development
    terrain_yield: dict[Terrain, dict[str, int]] = Field(
        default_factory=lambda: {
            Terrain.PLAINS: {"grain": 2},
            Terrain.FOREST: {"timber": 2, "grain": -1},
            Terrain.HILLS: {"iron": 1, "manpower": 1},
            Terrain.MARSH: {"timber": 1, "grain": -1},
            Terrain.MOUNTAINS: {"iron": 2, "manpower": 1, "grain": -2},
        }
    )
    # developing is cheap where fields can spread, dear where they must be won from the land
    terrain_develop_cost: dict[Terrain, float] = Field(
        default_factory=lambda: {
            Terrain.PLAINS: 0.9,
            Terrain.FOREST: 1.1,
            Terrain.HILLS: 1.2,
            Terrain.MARSH: 1.3,
            Terrain.MOUNTAINS: 1.5,
        }
    )
    recruit_cost: Resources = Resources(ducats=6, manpower=2, iron=2)
    disband_refund: Resources = Resources(manpower=2)  # per regiment sent home
    grain_upkeep_per_regiment: int = 1
    iron_upkeep_per_regiments: int = 10  # an iron a year for this many regiments (guns: 3 each)
    ducat_upkeep_per_regiment: float = 0.5  # pay, rounded up for the whole army
    manpower_cap_base: int = 10  # manpower cap = base + years x yearly manpower
    manpower_cap_years: int = 6
    develop_base_ducats: int = 10  # cheap to start, dear to finish
    develop_ducats_per_level: int = 7
    develop_timber_base: int = 3  # timber for new roads, mills and houses
    develop_timber_per_two_levels: int = 2
    develop_iron_from: int = 4  # from this development, tools and nails: 1 iron a level above
    develop_grain_base: int = 4  # grain to feed the new townsfolk: base + the development
    develop_grain_per_level: int = 1
    max_development: int = 12
    # a province's focus: a share of its output, from a hamlet's to a great city's
    focus_base: float = 0.15
    focus_per_settlement: float = 0.05  # each step up from a hamlet
    focus_cost: Resources = Resources(ducats=30)
    focus_years: int = 5  # before a province can turn to another focus
    designations: dict[Focus, DesignationSpec] = Field(default_factory=default_designations)
    designation_realm_cap: int = 2  # tier 3 designations of a kind that count for the realm
    shipyard_yards: int = 2  # more ships a tier 2 shipyard launches a year
    policies: dict[PolicyAxis, tuple[PolicySide, PolicySide]] = Field(
        default_factory=default_policies
    )
    policy_stability: int = 1  # stability a change of policy costs (the first choice is free)
    policy_years: int = 10  # before a policy can change again
    league_galleys: int = 6  # papal and Venetian galleys for each crown of the Holy League
    # kings: authority gathered from the ruler's skills, spent on royal acts; a reign's agenda
    authority_max: int = 100
    authority_start: int = 20
    royal_acts: dict[RoyalAct, RoyalActSpec] = Field(default_factory=default_royal_acts)
    presence_morale: float = 0.08
    agendas: dict[str, AgendaSpec] = Field(default_factory=default_agendas)
    agenda_offers: int = 3
    agenda_prestige: int = 10
    agenda_authority: int = 30
    # the dynasty
    heir_birth_chance: float = 0.2  # a year, while a crown has no heir
    majority: int = 16  # the age a ruler rules alone; younger, a regency
    education_cost: Resources = Resources(ducats=30)
    education_authority: int = 15
    regency_stability: int = 1  # lost when a regency begins
    crisis_stability: int = 2  # lost when the line fails and a cousin takes the throne
    learning_research_discount: float = 0.03  # each province of learning, up to the cap
    learning_research_cap: float = 0.15
    develop_goods_from: int = 5  # from this development, developing also takes goods
    workshop_base_goods: int = 2
    workshop_goods_per_development: int = 3  # +1 bale for every this many levels
    # the European market: what a unit of each traded resource costs in ducats, before the
    # merchants' cut; prices move with what all Europe buys and sells
    market_prices: dict[str, float] = Field(
        default_factory=lambda: {"grain": 1.0, "iron": 2.0, "timber": 1.5, "goods": 3.0}
    )
    market_spread: float = 0.15  # the merchants' cut, on buying and selling
    # what lowers a nation's cut (shares of it waived), up to trade_bonus_max in all
    trade_bonus_per_economy_level: float = 0.04
    trade_bonus_per_treasurer_skill: float = 0.03
    trade_bonus_per_marketplace: float = 0.02  # for each level of each marketplace owned
    trade_bonus_marketplaces_max: float = 0.2
    royal_exchange_trade_bonus: float = 0.25
    trade_bonus_max: float = 0.8
    market_depth: int = 100  # units of net demand that move a price by the elasticity
    market_elasticity: float = 0.25
    market_reversion: float = 0.2  # a year, back towards the base price
    market_floor: float = 0.6  # times the base price
    market_ceiling: float = 3.0
    max_trade_per_order: int = 200
    buildings: dict[BuildingKind, BuildingSpec] = Field(default_factory=default_buildings)
    # the regiments each crown was famed for: one kind of its army, under its own name
    national_units: dict[str, NationalUnit] = Field(default_factory=default_national_units)
    # fleets
    ships: dict[Ship, ShipSpec] = Field(default_factory=default_ships)
    ships_per_port: int = 3  # ships a port can launch in a year, and one more per 3 development
    fleet_command: float = 2.0  # a fleet this many times the enemy's closes its straits to it
    fleet_reach: float = 0.5  # of a fleet's strength, what it lends a strait next door
    blockade_share: float = 0.25  # ducats a blockaded port loses
    blockade_min: float = 8.0  # the least fleet strength that can blockade a coast
    naval_loser_loss: float = 0.5  # share of the beaten fleet sunk or taken
    naval_winner_loss: float = 0.3  # times the ratio of the loser's strength to the winner's
    naval_battle_counts: int = 3  # ships the loser must lose for a sea battle to count in the war
    great_sea_battle: int = 30  # ships on both sides: a battle all Europe talks of
    # colonies
    regions: dict[Region, RegionSpec] = Field(default_factory=default_regions)
    expedition_cost: Resources = Resources(ducats=40, manpower=3)
    expedition_ships: float = 2.5  # Atlantic fleet strength an expedition needs (a galleon)
    expedition_base: int = 20  # progress a year, plus 5 per pip of a die
    expedition_per_strength: float = 1.0  # progress for each point of Atlantic fleet strength
    expedition_fleet_cap: int = 10
    expedition_baltic: int = 10  # progress lost each year by an expedition from a Baltic port
    expeditions_at_once: int = 2
    region_share: float = 0.5  # of a region's places, the most one crown may hold
    prestige_colony: int = 3
    colonial_blockade: float = 0.5  # share of colonial dues lost while the Atlantic is blockaded
    seize_command: float = 2.0  # Atlantic fleet times the enemy's needed to take a colony
    goods: dict[ColonialGood, GoodSpec] = Field(default_factory=default_goods)
    colony_kinds: dict[ColonyKind, ColonyKindSpec] = Field(default_factory=default_colony_kinds)
    good_price_drop: float = 0.04  # of a good's price lost for each cargo a year past its glut
    good_price_floor: float = 0.5  # the lowest share of its price a good falls to
    monopoly_share: float = 0.6  # of a good's cargoes, the share that makes a crown its master
    monopoly_bonus: float = 0.25  # more for the master's cargoes of it
    inflation_decay: float = 0.01  # inflation lost each year
    inflation_max: float = 0.3  # the most: income in ducats falls by the inflation
    viceroyalty_colonies: int = 3  # colonies in a region a viceroyalty needs
    viceroyalty_cost: Resources = Resources(ducats=80)
    viceroyalty_authority: int = 20
    viceroy_cargo: float = 0.1  # more cargo in the region per point of the viceroy's skill
    # war beyond the sea
    garrison_pay: int = 1  # ducats a year for each regiment kept overseas
    colonial_fort_cost: Resources = Resources(ducats=60, iron=5)
    colonial_fort_max: int = 2
    colonial_fort_defence: float = 0.5  # the colonies' defence, more for each level of fort
    viceroy_defence: float = 0.25  # more defence where a viceroy rules
    colonial_defender: float = 1.25  # defenders' advantage overseas, behind palisades
    native_anger: float = 0.01  # dues lost, per regiment of the peoples and point of anger
    native_resistance_max: float = 0.5  # the most of a region's dues its peoples deny
    native_calm: float = 4.0  # defenders that halve the peoples' resistance
    native_terrain: float = 0.05  # more for the peoples per point of the region's hardness
    raid_min: float = 8.0  # the ocean fleet an enemy needs to raid the treasure fleets
    raid_chance: float = 0.35  # the most a raid succeeds, by the fleets on the ocean
    raid_privateers: float = 0.1  # more for privateers, and for the Sea Dogs
    raid_share: float = 0.5  # of the year's cargoes a raid takes
    prestige_natives: int = 5  # for breaking a people
    infamy_natives: float = 1.0  # for every victory over a people
    # from a hamlet to a great city, by development: each step up gives room for one more work
    settlements: tuple[Settlement, ...] = Field(default_factory=default_settlements)
    # what a building does and eats at each level, times its first level's
    building_level_factors: tuple[float, ...] = (1.0, 1.6, 2.2)
    # what reaching each level costs, times the building's own cost (level 1: building it)
    building_upgrade_costs: tuple[float, ...] = (1.0, 1.0, 1.5)
    building_output_bonus: float = 1.0  # marketplace, farm estates, ironworks, mill, barracks
    university_develop_discount: float = 0.3
    armory_iron_discount: float = 0.5
    unrest_turns: int = 5  # a conquered province produces nothing while it settles
    stability_boost_ducats: int = 50
    min_stability: int = -3
    max_stability: int = 3

    # technology: one research a year, each level costs its base cost times the new level
    max_tech_level: int = 5
    tech_tree: dict[TechBranch, list[TechLevel]] = Field(default_factory=default_tech_tree)
    tech_costs: dict[TechBranch, Resources] = Field(
        default_factory=lambda: {
            TechBranch.MILITARY: Resources(ducats=60, iron=5),
            TechBranch.ECONOMY: Resources(ducats=70),
            TechBranch.ENGINEERING: Resources(ducats=50, timber=6),
            TechBranch.NAVAL: Resources(ducats=55, timber=8),
            TechBranch.ADMINISTRATION: Resources(ducats=65),
        }
    )
    research_cost_growth: float = 0.5  # each level costs half the base cost more than the last
    military_tech_bonus: float = 0.06  # battle power per level, attacking and defending
    economy_tech_bonus: float = 0.05  # ducat and grain income per level
    engineering_tech_discount: float = 0.08  # ducats and timber of buildings and development

    # government: the ruler's three abilities and three advisors
    ruler_income_bonus: float = 0.02  # ducat income per point of administration
    ruler_battle_bonus: float = 0.02  # battle power per point of military
    ruler_stability_discount: float = 0.08  # cheaper stability per point of diplomacy
    advisor_hire_ducats: int = 40  # times the advisor's skill
    advisor_salary_ducats: int = 2  # a year, times the advisor's skill
    treasurer_income_bonus: float = 0.04  # ducat income per point of skill
    chancellor_research_discount: float = 0.08  # per point of skill
    marshal_battle_bonus: float = 0.03  # battle power per point of skill
    advisor_pool_years: int = 5  # new candidates come to court this often

    # regiments
    units: dict[UnitKind, UnitSpec] = Field(default_factory=default_units)
    combined_arms_share: float = 0.1  # a kind counts towards combined arms from this share
    combined_arms_bonus: dict[int, float] = Field(
        default_factory=lambda: {3: 0.1, 4: 0.15}  # kinds present -> battle power
    )
    artillery_share_per_fort_level: float = 0.1  # this share of guns ignores one fort level
    # sieges: each year the besiegers roll a die, add the modifiers, and the score buys progress
    # (lowest score first: from this score on, this much progress, so called)
    siege_results: tuple[tuple[int, int, str], ...] = (
        (-99, 10, "disease in the camp"),
        (1, 30, "the walls hold"),
        (2, 45, "the trenches creep closer"),
        (4, 65, "hunger in the town"),
        (6, 100, "a breach in the walls"),
    )
    siege_disease: float = 0.1  # share of the besiegers disease carries off on the worst roll
    siege_ring_per_wall: int = 5  # regiments a level of wall needs to close the ring around it

    # monuments: raising one to level n costs n times these
    monuments: dict[str, MonumentSpec] = Field(default_factory=default_monuments)
    monument_cost: Resources = Resources(ducats=90, timber=10)
    max_monument_level: int = 3

    # great works
    royal_exchange_income_bonus: float = 0.1
    observatory_research_discount: float = 0.15

    # generals
    general_cost: Resources = Resources(ducats=50)
    max_generals: int = 4
    general_bonus_per_skill: float = 0.1  # battle power per point of skill (1 to 3)

    # combat
    terrain_defense: dict[Terrain, float] = Field(
        default_factory=lambda: {
            Terrain.PLAINS: 1.0,
            Terrain.FOREST: 1.1,
            Terrain.HILLS: 1.25,
            Terrain.MARSH: 1.25,
            Terrain.MOUNTAINS: 1.5,
        }
    )
    defender_advantage: float = 1.2  # dug in, on home ground: applies to every defence
    fort_bonus_per_level: float = 0.25  # per fort building (fort, citadel)
    capital_bonus: float = 0.25
    sea_crossing_bonus: float = 0.25
    landing_bonus: float = 0.25  # on top of it: defenders on the beach against men off boats
    roll_min: float = 0.8
    roll_max: float = 1.2
    winner_loss_factor: float = 0.5  # winner loses factor * (loser power / winner power)
    # tactics: the edge of a tactic over the posture it beats (and the loss to the one that beats
    # it), at full strength once the kind that carries it is this share of the army
    tactic_edge: float = 0.15
    tactic_share: dict[UnitKind, float] = Field(
        default_factory=lambda: {
            UnitKind.INFANTRY: 0.4,
            UnitKind.ARCHERS: 0.3,
            UnitKind.CAVALRY: 0.3,
            UnitKind.ARTILLERY: 0.15,
        }
    )
    # veterancy: what a regiment learns in a victory (0 to 1), and what a veteran army is worth
    veterancy_per_victory: float = 0.2
    veterancy_bonus: float = 0.25  # battle power at full veterancy
    mercenary_veterancy: float = 0.5  # hired soldiers come seasoned
    # morale: a steady realm fights better, a tired one worse
    morale_per_stability: float = 0.02
    morale_per_exhaustion: float = 0.0075
    veterancy_decay: float = 0.02  # a year: the veterans grow old and go home

    # diplomacy
    mobilization_turns: int = 1  # after a war starts, armies wait this long before attacking
    treaty_break_stability_penalty: int = 2
    non_aggression_turns: int = 10
    truce_turns: int = 5
    tribute_years: int = 10  # a peace's yearly tribute is paid this long
    # war score: what each side has won, from its enemy's land, capital and battles (0 to 100)
    war_score_capital: int = 15
    war_score_per_battle: int = 2
    war_score_battles_max: int = 20
    # what a demand in a peace costs, in war score
    peace_cost_army_limit: int = 15
    peace_cost_per_year_of_income: int = 10  # a lump sum worth a year of the payer's ducats
    # war exhaustion
    exhaustion_per_war_year: float = 1.0
    exhaustion_per_battle_lost: float = 0.5
    exhaustion_per_province_occupied: float = 0.5  # a year, for each of your provinces held
    exhaustion_recovery: float = 2.0  # a year at peace
    exhaustion_max: float = 20.0
    exhaustion_income_penalty: float = 0.01  # ducat income per point
    exhaustion_unrest_threshold: float = 10.0  # from here, -1 stability a year
    ceded_unrest_turns: int = 2  # a province handed over by treaty settles faster than a conquest

    # opinion: what each court thinks of each other, from -100 to 100
    opinion_gift_per_ducats: int = 4  # +1 for every this many ducats' worth
    opinion_gift_max: int = 25
    opinion_trade: int = 5
    opinion_treaty: dict[str, int] = Field(
        default_factory=lambda: {"alliance": 20, "non_aggression": 10, "peace": 5, "marriage": 15}
    )
    opinion_marriage_yearly: int = 2  # both courts warm by this every year of a marriage
    max_marriages: int = 3
    # aggressive expansion: each province taken (from a minor, or by treaty) adds this much
    # infamy per level of its development; neighbours of the land think worse of the taker
    infamy_per_development: float = 1.0
    infamy_decay: float = 1.0  # a year
    infamy_opinion: int = -2  # per point of infamy added, for every court bordering the land
    coalition_infamy: float = 12.0  # from here, courts may league against the conqueror
    coalition_dissolves: float = 5.0  # below this, the league has nothing left to fear
    opinion_coalition: int = 10
    diplomacy_log: int = 1000  # diplomatic events kept for the courts' memories
    opinion_war_declared: int = -40  # the victim's opinion of the aggressor
    opinion_betrayal: int = -10  # everyone else's opinion of a treaty breaker
    opinion_province_taken: int = -10
    opinion_call_answered: int = 20
    opinion_call_ignored: int = -30
    opinion_shared_enemy: int = 3  # a year, fighting the same enemy
    opinion_decay: float = 0.1  # a year, towards zero
    opinion_same_faith: int = 2  # a year
    opinion_other_faith: int = -1  # a year
    opinion_infidel: int = -3  # a year, between Christian and Muslim courts
    # a province whose people keep another faith than its ruler's yields this much less
    faith_mismatch_output: float = 0.25
    faith_conquest_unrest: int = 2  # more years of unrest when taking land of another faith
    convert_cost: Resources = Resources(ducats=40)  # plus convert_cost_per_development ducats
    convert_cost_per_development: int = 10
    faith_conversion_chance: float = 0.05  # a year, for a province to take its ruler's faith
    faith_follow_crown: float = 0.5  # share of provinces that follow when the crown changes faith

    # prestige: 0 to 100
    prestige_max: int = 100
    prestige_decay: int = 1  # a year
    prestige_battle: int = 1  # won against a great power (the loser loses as much)
    prestige_province: int = 3  # gained by treaty (the giver loses as much)
    prestige_monument_level: int = 2  # times the new level
    prestige_great_work: int = 5
    prestige_treaty_broken: int = -10
    prestige_call_ignored: int = -5
    prestige_income_bonus: float = 0.001  # ducat income per point
    prestige_stability_discount: float = 0.002  # per point
    prestige_in_score: float = 0.5  # what a point of prestige is worth in the final score
    # taxes, from -2 (very low) to +2 (very high): more ducats, fewer volunteers, angrier subjects
    tax_income_step: float = 0.15  # ducat income per level
    tax_manpower_step: float = 0.10  # manpower per level, the other way
    tax_stability_cost_step: float = 0.20  # raising stability dearer per level of tax
    tax_stability_chance: dict[int, float] = Field(
        default_factory=lambda: {1: 0.1, 2: 0.25}  # a year, of losing (high) or gaining (low) 1
    )
    # patronage: painters, chapels, feasts and alms buy prestige, dearer the more you have
    patronage_base: int = 40  # ducats, plus patronage_per_prestige times your prestige
    patronage_per_prestige: int = 2
    patronage_prestige: int = 4
    # mercenaries: Landsknechte and Swiss pikes for ducats alone, no manpower and no iron
    mercenary_cost: int = 15  # ducats a regiment
    mercenary_limit: int = 10  # regiments a year: the captains for hire are few

    # fortune: a chance each year of an event for each nation
    event_chance: float = 0.3
    opinion_stance: dict[str, int] = Field(
        default_factory=lambda: {"friend": 2, "rival": -3}  # a year, towards the declarer
    )
    opinion_charming: int = 2  # a year, from every court
    opinion_cruel: int = -1  # a year, from every court
    max_rivals: int = 3
    max_friends: int = 3
    rival_battle_bonus: float = 0.05  # against a declared rival
    # grudges: (years, opinion lost each year) for each wrong a court remembers
    grudge_land: tuple[int, int] = (20, 2)  # a province taken from it by treaty
    grudge_betrayal: tuple[int, int] = (30, 3)  # a treaty broken to make war on it
    grudge_war: tuple[int, int] = (10, 1)  # war declared on it
    grudge_abandoned: tuple[int, int] = (15, 2)  # an ally that left it alone in a war
    grudge_refuses: int = 2  # from this weight of grudges, no alliance, pact or marriage
    joint_attack_penalty: float = 0.1  # battle power lost for each army that joins another
    joint_attack_penalty_max: float = 0.2

    # victory
    domination_share: float = 0.5  # own this share of all provinces to win outright
    crisis_window: tuple[int, int] = (18, 28)  # turns between which the age's crisis begins
    ambition_victory: bool = True  # fulfilling every mission of one's crown wins the game
    start_year: int = 1500


# ---------------------------------------------------------------- dynamic state


class ProvinceState(BaseModel):
    owner: NationId | None  # None: an independent minor, defended by its own garrison
    troops: NonNegativeInt  # regiments stationed here, of every kind
    development: int = Field(ge=1)
    buildings: list[BuildingKind] = Field(default_factory=list)
    unrest: NonNegativeInt = 0  # turns left before a conquered province produces anything
    # Regiments of each kind other than infantry; whatever else `troops` counts is infantry.
    units: dict[UnitKind, NonNegativeInt] = Field(default_factory=dict)
    monument: NonNegativeInt = 0  # level of the province's monument, if it has one (0: a site)
    controller: NationId | None = None  # an enemy occupying it in a war; None: its owner holds it
    idle: list[BuildingKind] = Field(default_factory=list)  # buildings whose inputs went unpaid
    workings: NonNegativeInt = 0  # level of its mine, vineyard, fishery... (0 to 3)
    siege_by: NationId | None = None  # who besieges its walls
    siege_years: NonNegativeInt = 0  # years the siege has lasted
    siege_progress: NonNegativeInt = 0  # 0 to 100: at 100 the walls fall
    # the besieging army, camped in the siege lines: regiments by kind
    besiegers: dict[UnitKind, NonNegativeInt] = Field(default_factory=dict)
    siege_from: ProvinceId | None = None  # where the besiegers came from, and go back to
    # buildings upgraded beyond their first level (a building not listed is at level 1)
    levels: dict[BuildingKind, NonNegativeInt] = Field(default_factory=dict)
    faith: Faith | None = None  # what its people believe; set for every province by the scenario
    focus: Focus | None = None  # what its people turn their hands to
    posture: Posture = Posture.HOLD  # how its garrison waits for an attack
    veterancy: float = Field(default=0.0, ge=0.0, le=1.0)  # of its garrison: 0 raw, 1 veteran
    siege_veterancy: float = Field(default=0.0, ge=0.0, le=1.0)  # of the besiegers
    focus_since: int | None = None  # the turn the focus was set

    @property
    def holder(self) -> NationId | None:
        """Whoever holds the province now: its occupier in a war, else its owner."""
        return self.controller or self.owner

    def level(self, building: BuildingKind) -> int:
        """The level of a building standing here (0 if it does not)."""
        return self.levels.get(building, 1) if building in self.buildings else 0

    @property
    def fort(self) -> int:
        """Fort level: the levels of the fortifications (fort, citadel) standing and kept up
        here. A fortification whose upkeep went unpaid is left unmanned: it does not count."""
        return sum(
            self.level(b) for b in (BuildingKind.FORT, BuildingKind.CITADEL) if b not in self.idle
        )

    def army(self) -> dict[UnitKind, int]:
        """The garrison by kind, every kind listed."""
        left = self.troops
        out = dict.fromkeys(UnitKind, 0)
        for kind in (UnitKind.ARTILLERY, UnitKind.CAVALRY, UnitKind.ARCHERS):
            out[kind] = min(self.units.get(kind, 0), left)
            left -= out[kind]
        out[UnitKind.INFANTRY] = left
        return out

    def siege_army(self) -> dict[UnitKind, int]:
        """The besiegers by kind, every kind listed."""
        return {k: self.besiegers.get(k, 0) for k in UnitKind}

    def end_siege(self) -> dict[UnitKind, int]:
        """Clear the siege; returns the besiegers, for the caller to send somewhere."""
        army = self.siege_army()
        self.siege_by, self.siege_years, self.siege_progress = None, 0, 0
        self.besiegers, self.siege_from = {}, None
        self.siege_veterancy = 0.0
        return army

    def set_army(self, army: dict[UnitKind, int], veterancy: float | None = None) -> None:
        """Put this army in the province, as seasoned as `veterancy` if given. An empty
        province keeps no veterans."""
        self.troops = sum(army.values())
        self.units = {k: n for k, n in army.items() if k != UnitKind.INFANTRY and n}
        if veterancy is not None:
            self.veterancy = min(1.0, max(0.0, veterancy))
        if not self.troops:
            self.veterancy = 0.0

    def add(self, army: dict[UnitKind, int], veterancy: float | None = None) -> None:
        """Bring regiments in. With their `veterancy`, the garrison's becomes the average of
        both; without it, they are taken to be as seasoned as the garrison."""
        mine = self.army()
        before, coming = self.troops, sum(army.values())
        seasoned = None
        if veterancy is not None and before + coming:
            seasoned = (self.veterancy * before + veterancy * coming) / (before + coming)
        self.set_army({k: mine[k] + army.get(k, 0) for k in UnitKind}, seasoned)

    def take(
        self, regiments: int, wanted: dict[UnitKind, int] | None = None
    ) -> dict[UnitKind, int]:
        """Remove regiments: exactly `wanted` if given (the caller checked it is here), else a
        proportional mix. Returns what left."""
        mine = self.army()
        out = dict(wanted) if wanted is not None else share(mine, regiments)
        self.set_army({k: mine[k] - out.get(k, 0) for k in UnitKind})
        return {k: out.get(k, 0) for k in UnitKind}


def share(army: dict[UnitKind, int], regiments: int) -> dict[UnitKind, int]:
    """`regiments` drawn from `army` in proportion (largest remainders), never more than it has."""
    total = sum(army.values())
    regiments = min(regiments, total)
    if total == 0 or regiments == 0:
        return dict.fromkeys(UnitKind, 0)
    exact = {k: army.get(k, 0) * regiments / total for k in UnitKind}
    out = {k: int(v) for k, v in exact.items()}
    rest = regiments - sum(out.values())
    for k in sorted(UnitKind, key=lambda k: (-(exact[k] - out[k]), list(UnitKind).index(k)))[:rest]:
        out[k] += 1
    return out


class Crisis(BaseModel):
    """A great trouble of the age that falls on all Europe for some years, once a game: drawn
    by the seed when the game begins (see `Rules.crisis_window` and `fortune.CRISES`)."""

    kind: str  # "plague", "ice_age", "price_revolution"
    start: int  # the turn it begins
    end: int  # the turn it is over


class Grudge(BaseModel):
    """A wrong a court will not forget: it weighs on its opinion of the wrongdoer every year
    until it fades, and while it is heavy the court will not bind itself to them."""

    against: NationId
    reason: str  # what they did, as the court tells it: "took Navarre"
    since: int  # the turn of the wrong
    until: int  # the turn it fades
    weight: NonNegativeInt  # opinion lost each year while it lasts


class NationState(BaseModel):
    id: NationId
    name: str
    color: str  # hex, for the viewer
    capital: ProvinceId
    resources: Resources
    stability: int = 0
    alive: bool = True
    technology: dict[TechBranch, int] = Field(default_factory=lambda: dict.fromkeys(TechBranch, 0))
    doctrines: dict[TechBranch, list[int]] = Field(default_factory=dict)  # chosen, by level

    @model_validator(mode="after")
    def _every_branch(self) -> Self:
        """A realm saved before a branch existed knows it at level 0."""
        for branch in TechBranch:
            self.technology.setdefault(branch, 0)
        return self

    ruler: Ruler | None = None
    advisors: dict[AdvisorRole, Advisor] = Field(default_factory=dict)
    stances: dict[NationId, Stance] = Field(default_factory=dict)  # declared friends and rivals
    war_exhaustion: float = 0.0  # 0 to 20: years of war, defeats and occupation weigh on the realm
    prestige: int = 0  # 0 to 100: glory won in war, works and wise choices
    faith: Faith = Faith.CATHOLIC
    pending_events: list[PendingEvent] = Field(default_factory=list)  # decisions awaiting the crown
    events_seen: list[str] = Field(default_factory=list)  # once-only events already met
    loans: list[Loan] = Field(default_factory=list)
    missions_done: list[str] = Field(default_factory=list)  # see engine/missions.py
    decisions: list[str] = Field(default_factory=list)  # taken; see engine/decisions.py
    tax: int = Field(default=0, ge=-2, le=2)  # -2 very low ... +2 very high, see Rules.tax_*
    infamy: float = 0.0  # aggressive expansion: grows with every province taken, fades yearly
    grudges: list[Grudge] = Field(default_factory=list)  # wrongs it will not forget
    flags: list[str] = Field(default_factory=list)  # choices that last, e.g. "quarantine"
    policies: dict[PolicyAxis, int] = Field(default_factory=dict)  # the side taken on each axis
    policy_since: dict[PolicyAxis, int] = Field(default_factory=dict)  # the turn it was taken
    authority: int = Field(default=20, ge=0)  # the crown's to spend on royal acts
    heir: Ruler | None = None  # who takes the throne next (public, as heirs are)
    regency: bool = False  # the ruler is a minor: a council rules for them
    claims: list[NationId] = Field(default_factory=list)  # thrones this crown may press a claim to
    deeds: dict[str, int] = Field(default_factory=dict)  # counts of what the realm has done
    fleets: dict[SeaId, dict[Ship, int]] = Field(default_factory=dict)  # by sea zone; public
    colonies: dict[Region, list[Colony]] = Field(default_factory=dict)  # public: every empire
    expeditions: list[Expedition] = Field(default_factory=list)  # under way
    inflation: float = 0.0  # 0 to rules.inflation_max: the silver that made every price rise
    viceroys: dict[Region, Viceroy] = Field(default_factory=dict)  # public
    garrisons: dict[Region, int] = Field(default_factory=dict)  # regiments overseas; public
    colonial_forts: dict[Region, int] = Field(default_factory=dict)  # fort levels; public

    @model_validator(mode="before")
    @classmethod
    def _colonies_one_by_one(cls, data: Any) -> Any:
        """A realm saved when colonies were counted: each becomes a plantation."""
        if isinstance(data, dict) and isinstance(data.get("colonies"), dict):
            data = {
                **data,
                "colonies": {
                    r: [{"kind": "plantation"} for _ in range(v)] if isinstance(v, int) else v
                    for r, v in data["colonies"].items()
                },
            }
        return data

    def colony_count(self, region: Region) -> int:
        return len(self.colonies.get(region, []))

    def colony_total(self) -> int:
        return sum(len(c) for c in self.colonies.values())

    def add_colony(self, region: Region, colony: Colony) -> None:
        self.colonies.setdefault(region, []).append(colony)

    def lose_colony(self, region: Region) -> Colony | None:
        """The newest colony in a region goes (the oldest are held hardest)."""
        held = self.colonies.get(region, [])
        if not held:
            return None
        lost = held.pop()
        if not held:
            del self.colonies[region]
            self.viceroys.pop(region, None)
            self.colonial_forts.pop(region, None)
        return lost

    def ships(self, sea: SeaId) -> dict[Ship, int]:
        """The ships in a sea zone, every kind listed."""
        here = self.fleets.get(sea, {})
        return {k: here.get(k, 0) for k in Ship}

    def set_ships(self, sea: SeaId, ships: Mapping[Ship, int]) -> None:
        kept = {k: n for k, n in ships.items() if n > 0}
        if kept:
            self.fleets[sea] = kept
        else:
            self.fleets.pop(sea, None)


class Expedition(BaseModel):
    """Settlers and soldiers on their way to found a colony."""

    region: Region
    since: int  # the turn it sailed
    progress: int = Field(default=0, ge=0)  # out of 100
    kind: ColonyKind = ColonyKind.PLANTATION  # the colony it will found


class PendingEvent(BaseModel):
    """An event waiting for the crown's answer (see `fortune.py`)."""

    id: int
    event: str
    turn: int  # when it happened; unanswered by the end of the next turn, option 0 is taken
    province: ProvinceId | None = None


class Loan(BaseModel):
    yearly: int  # ducats repaid every year
    until: int  # last turn of repayment


class General(BaseModel):
    """A commander: makes the regiments he leads fight harder, by 10% per point of skill."""

    id: int
    name: str
    nation: NationId
    skill: int = Field(ge=1, le=3)
    province: ProvinceId


class TreatyKind(StrEnum):
    ALLIANCE = "alliance"
    NON_AGGRESSION = "non_aggression"
    TRUCE = "truce"
    TRIBUTE = "tribute"  # a peace term: `payer` pays `amount` ducats a year
    ARMY_LIMIT = "army_limit"  # a peace term: `payer` may not recruit beyond `amount` regiments
    MARRIAGE = "marriage"  # a royal marriage: the courts warm to each other every year
    COALITION = "coalition"  # a defensive league against `against`: attack one, fight both


class Treaty(BaseModel):
    kind: TreatyKind
    parties: tuple[NationId, NationId]  # sorted, see `pair`
    since: int
    until: int | None = None  # last turn it is in force; None: until cancelled
    payer: NationId | None = None  # tribute and army limit: the side bound by it
    against: NationId | None = None  # coalition: the power the league stands against
    amount: int = 0


class War(BaseModel):
    parties: tuple[NationId, NationId]  # sorted
    since: int
    battles: dict[NationId, int] = Field(default_factory=dict)  # battles won by each side


class ProposalKind(StrEnum):
    ALLIANCE = "alliance"
    NON_AGGRESSION = "non_aggression"
    PEACE = "peace"
    TRADE = "trade"
    CALL_TO_ARMS = "call_to_arms"
    MARRIAGE = "marriage"
    COALITION = "coalition"  # `enemy`: the power the league would stand against


class Proposal(BaseModel):
    """An offer waiting for an answer. It must be answered on the recipient's next turn."""

    id: int
    kind: ProposalKind
    sender: NationId
    recipient: NationId
    turn: int  # when it was made
    give: Resources = Resources()  # trade and peace: what the sender gives
    receive: Resources = Resources()  # trade and peace: what the sender asks for
    enemy: NationId | None = None  # call to arms: who the sender is fighting
    cede: list[ProvinceId] = Field(default_factory=list)  # peace: provinces the sender hands over
    demand: list[ProvinceId] = Field(default_factory=list)  # peace: provinces it asks for
    pay_tribute: int = 0  # peace: ducats a year the sender pays
    ask_tribute: int = 0  # peace: ducats a year the sender asks for
    limit_army: int | None = None  # peace: the recipient's army may not grow beyond this
    note: str = ""  # the sender's words, for the recipient to weigh
    reply_to: int | None = None  # the proposal this one counters


class GameState(BaseModel):
    seed: int
    turn: int = 1
    max_turns: int
    rules: Rules
    map: MapDef
    provinces: dict[ProvinceId, ProvinceState]
    nations: dict[NationId, NationState]
    treaties: list[Treaty] = Field(default_factory=list)
    wars: list[War] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    next_proposal_id: int = 1
    generals: list[General] = Field(default_factory=list)
    next_general_id: int = 1
    next_event_id: int = 1
    market: dict[str, float] = Field(default_factory=dict)  # current prices; empty: the base
    opinions: dict[NationId, dict[NationId, int]] = Field(default_factory=dict)  # a's of b
    last_events: list[Event] = Field(default_factory=list)  # what happened last turn
    # every diplomatic exchange of the game (letters, proposals, answers, treaties, wars), so
    # each court can be reminded of what passed between it and the others; the oldest drop off
    diplomacy: list[Event] = Field(default_factory=list)
    finished: bool = False
    winner: NationId | None = None
    crisis: Crisis | None = None  # the age's great trouble, drawn on the first turn
    history: list[str] = Field(default_factory=list)  # the great events already met
    natives: dict[Region, int] = Field(default_factory=dict)  # peoples' strength, once fought

    @model_validator(mode="after")
    def _chart_the_seas(self) -> Self:
        """A game saved before the sea zones: its map gets them, and each crown's ships (kept
        by water then, or not at all before the fleets) move to the zone of that water where
        most of its ports lie; a game saved before the fleets gets the fleets of 1500."""
        if self.map.seas or not any(p.sea_neighbors for p in self.map.provinces.values()):
            return self
        from pax_agentica.engine import scenario  # here: the scenario is built on this module

        charted = scenario.europe_map()
        if charted.name != self.map.name or set(charted.provinces) != set(self.map.provinces):
            return self
        self.map = charted
        if not any(n.fleets for n in self.nations.values()):
            for nid, fleets in scenario.STARTING_FLEETS.items():
                if nid in self.nations and self.nations[nid].alive:
                    self.nations[nid].fleets = {z: dict(ships) for z, ships in fleets.items()}
            return self
        for nid, nation in self.nations.items():
            ports = [pid for pid, p in self.provinces.items() if p.owner == nid]
            moved: dict[SeaId, dict[Ship, int]] = {}
            for water, ships in nation.fleets.items():
                zones = [z for z, zone in charted.seas.items() if zone.water == water]
                if not zones:
                    continue
                home = max(
                    zones, key=lambda z: (sum(z in charted.provinces[p].seas for p in ports), z)
                )
                for kind, n in ships.items():
                    moved.setdefault(home, {})[kind] = moved.get(home, {}).get(kind, 0) + n
            nation.fleets = moved
        return self

    def crisis_now(self) -> str | None:
        """The crisis raging this turn, if any."""
        c = self.crisis
        return c.kind if c is not None and c.start <= self.turn < c.end else None

    # ------------------------------------------------------------ queries

    @property
    def year(self) -> int:
        return self.rules.start_year + self.turn - 1

    def alive_nations(self) -> list[NationId]:
        return sorted(n for n, s in self.nations.items() if s.alive)

    def provinces_of(self, nation: NationId) -> list[ProvinceId]:
        return sorted(p for p, s in self.provinces.items() if s.owner == nation)

    def war(self, a: NationId, b: NationId) -> War | None:
        key = pair(a, b)
        return next((w for w in self.wars if w.parties == key), None)

    def at_war(self, a: NationId, b: NationId) -> bool:
        return self.war(a, b) is not None

    def enemies_of(self, nation: NationId) -> list[NationId]:
        return sorted(_other(w.parties, nation) for w in self.wars if nation in w.parties)

    def treaty(self, a: NationId, b: NationId, kind: TreatyKind) -> Treaty | None:
        key = pair(a, b)
        return next((t for t in self.treaties if t.parties == key and t.kind == kind), None)

    def partners(self, nation: NationId, kind: TreatyKind) -> list[NationId]:
        return sorted(
            _other(t.parties, nation)
            for t in self.treaties
            if t.kind == kind and nation in t.parties
        )

    def score(self, nation: NationId) -> int:
        """Total development owned: the tie-breaking score when time runs out."""
        return sum(s.development for s in self.provinces.values() if s.owner == nation)

    def standing(self, nation: NationId) -> int:
        """What wins the game when time runs out: development, and half the prestige."""
        prestige = self.nations[nation].prestige * self.rules.prestige_in_score
        return self.score(nation) + int(prestige)

    def troops_of(self, nation: NationId) -> int:
        """Every regiment of a nation, in its own provinces, in those it occupies and in its
        siege lines."""
        held = sum(s.troops for s in self.provinces.values() if s.holder == nation)
        return held + sum(
            sum(s.besiegers.values()) for s in self.provinces.values() if s.siege_by == nation
        )

    def held_by(self, nation: NationId) -> list[ProvinceId]:
        """Provinces a nation holds: its own not occupied by an enemy, and those it occupies."""
        return sorted(p for p, s in self.provinces.items() if s.holder == nation)

    def occupied_from(self, owner: NationId, by: NationId | None = None) -> list[ProvinceId]:
        """`owner`'s provinces occupied by an enemy (by `by`, if given)."""
        return sorted(
            p
            for p, s in self.provinces.items()
            if s.owner == owner and s.controller and (by is None or s.controller == by)
        )

    def opinion(self, of: NationId, about: NationId) -> int:
        """What `of` thinks of `about`, from -100 to 100."""
        return self.opinions.get(of, {}).get(about, 0)

    def general(self, general_id: int) -> General | None:
        return next((g for g in self.generals if g.id == general_id), None)

    def general_in(self, province: ProvinceId) -> General | None:
        return next((g for g in self.generals if g.province == province), None)

    def generals_of(self, nation: NationId) -> list[General]:
        return [g for g in self.generals if g.nation == nation]

    def copy_for_update(self) -> Self:
        return self.model_copy(deep=True)


def _other(parties: tuple[NationId, NationId], me: NationId) -> NationId:
    return parties[1] if parties[0] == me else parties[0]
