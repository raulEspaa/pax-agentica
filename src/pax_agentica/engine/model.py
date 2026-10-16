"""The data model: the map, the nations, the treaties and the whole game state.

Everything is a Pydantic model so it serialises to JSON for free: replays, the web viewer and
LLM prompts all reuse the same types.

Immutability contract: the engine never mutates a state it receives. `resolve_turn` deep-copies
its input and only touches the copy, so from the outside every engine call is a pure function.
Small value objects (resources, map definitions, rules) are frozen outright.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt

from pax_agentica.engine.events import Event

type ProvinceId = str
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


class TechLevel(BaseModel):
    """One step of a technology branch: what it is called and what it brings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    unlocks: str  # what it brings, in one sentence
    lore: str = ""  # what it was, in history


def default_tech_tree() -> dict[TechBranch, list[TechLevel]]:
    """Every branch also gives its per-level bonus (see Rules); these are the milestones."""
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
            ),
            t(
                name="Bastions",
                unlocks="the citadel and the cannon foundry",
                lore=(
                    "Low, angled walls that shot glances off, the trace "
                    "italienne, and foundries to cast the guns that test them."
                ),
            ),
            t(
                name="Tercios",
                unlocks="training grounds and the military academy",
                lore=(
                    "Spain's regiments of pike, sword and shot, drilled to fight "
                    "as one, and schools to train their captains."
                ),
            ),
            t(
                name="Field Artillery",
                unlocks="your attacks ignore one level of enemy forts",
                lore=(
                    "Lighter guns on wheeled carriages that keep pace with the "
                    "army and breach walls in days."
                ),
            ),
            t(
                name="Military Revolution",
                unlocks="one more general",
                lore="Standing armies, drill and supply: war becomes the business of states.",
            ),
        ],
        TechBranch.ECONOMY: [
            t(
                name="Banking",
                unlocks="the bank",
                lore=(
                    "The Fuggers and the Medici lend to kings, and bills of exchange cross Europe."
                ),
            ),
            t(
                name="Printing Press",
                unlocks="the university and the observatory",
                lore="Gutenberg's press prints books by the thousand: learning becomes cheap.",
            ),
            t(
                name="Mercantilism",
                unlocks="marketplaces yield +150% instead of +100%, and the royal exchange",
                lore=(
                    "Gold is power: protect your own trades, tax the foreigner's,"
                    " and build an exchange."
                ),
            ),
            t(
                name="Humanism",
                unlocks="the cathedral",
                lore="The scholars of the Renaissance return to the ancients, and to man.",
            ),
            t(
                name="Cameralism",
                unlocks="one more building slot in every province",
                lore="The science of administration: counting, taxing and planning a realm.",
            ),
        ],
        TechBranch.ENGINEERING: [
            t(
                name="Blast Furnace",
                unlocks="ironworks",
                lore="Furnaces fed by water-driven bellows pour iron by the ton.",
            ),
            t(
                name="Water Mills",
                unlocks="farm estates and lumber mills yield +150% instead of +100%",
                lore="Wheels on every stream grind grain and saw timber.",
            ),
            t(
                name="Roads and Canals",
                unlocks="armies eat 20% less grain",
                lore="Paved roads and locks move grain and soldiers faster.",
            ),
            t(
                name="Star Forts",
                unlocks="your forts and citadels give +35% instead of +25%",
                lore="Fortresses shaped like stars, every wall covered by another's fire.",
            ),
            t(
                name="Grand Architecture",
                unlocks="provinces can grow to development 15",
                lore="Palladio and Bramante: domes and squares for cities that keep growing.",
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


def default_buildings() -> dict[BuildingKind, BuildingSpec]:
    civil, military = BuildingCategory.CIVIL, BuildingCategory.MILITARY
    return {
        BuildingKind.MARKETPLACE: BuildingSpec(
            name="Marketplace",
            category=civil,
            cost=Resources(ducats=50, timber=6),
            effect="doubles the province's ducats (at least +1), selling a bale of goods a year",
            consumes=Resources(goods=1),
        ),
        BuildingKind.FARM_ESTATES: BuildingSpec(
            name="Farm estates",
            category=civil,
            cost=Resources(ducats=40, timber=5),
            effect="doubles the province's grain (at least +1)",
        ),
        BuildingKind.IRONWORKS: BuildingSpec(
            name="Ironworks",
            category=civil,
            cost=Resources(ducats=60, timber=8),
            effect="doubles the province's iron (at least +1), burning 2 timber a year as charcoal",
            requires_tech=(TechBranch.ENGINEERING, 1),
            consumes=Resources(timber=2),
        ),
        BuildingKind.LUMBER_MILL: BuildingSpec(
            name="Lumber mill",
            category=civil,
            cost=Resources(ducats=45, iron=4),
            effect="doubles the province's timber (at least +1)",
        ),
        BuildingKind.UNIVERSITY: BuildingSpec(
            name="University",
            category=civil,
            cost=Resources(ducats=90, timber=12),
            effect="developing this province costs 30% fewer ducats; it buys a bale of goods "
            "(books) a year",
            requires_tech=(TechBranch.ECONOMY, 2),
            consumes=Resources(goods=1),
        ),
        BuildingKind.BANK: BuildingSpec(
            name="Bank",
            category=civil,
            cost=Resources(ducats=80, iron=4, timber=6),
            effect="+3 ducats and +50% of the province's ducats",
            requires_tech=(TechBranch.ECONOMY, 1),
        ),
        BuildingKind.CATHEDRAL: BuildingSpec(
            name="Cathedral",
            category=civil,
            cost=Resources(ducats=110, manpower=2, timber=20),
            effect="+1 manpower and +25% of the province's ducats; a conquered province settles "
            "twice as fast",
            requires_tech=(TechBranch.ECONOMY, 4),
        ),
        BuildingKind.BARRACKS: BuildingSpec(
            name="Barracks",
            category=military,
            cost=Resources(ducats=50, iron=3, timber=6),
            effect="doubles the province's manpower (at least +1), which also raises the cap; "
            "the garrison eats 2 grain a year",
            consumes=Resources(grain=2),
        ),
        BuildingKind.ARMORY: BuildingSpec(
            name="Armory",
            category=military,
            cost=Resources(ducats=60, iron=8, timber=4),
            effect="regiments recruited here need half the iron",
            requires_tech=(TechBranch.MILITARY, 1),
        ),
        BuildingKind.TRAINING_GROUNDS: BuildingSpec(
            name="Training grounds",
            category=military,
            cost=Resources(ducats=70, manpower=2, timber=8),
            effect="the garrison here fights 20% harder",
            requires_tech=(TechBranch.MILITARY, 3),
        ),
        BuildingKind.FORT: BuildingSpec(
            name="Fort",
            category=military,
            cost=Resources(ducats=60, iron=6, timber=10),
            effect="defenders here fight 25% harder",
        ),
        BuildingKind.CITADEL: BuildingSpec(
            name="Citadel",
            category=military,
            cost=Resources(ducats=100, manpower=2, iron=12, timber=15),
            effect="defenders here fight another 25% harder",
            requires=BuildingKind.FORT,
            requires_tech=(TechBranch.MILITARY, 2),
        ),
        BuildingKind.WORKSHOP: BuildingSpec(
            name="Workshops",
            category=civil,
            cost=Resources(ducats=55, timber=6),
            effect="turn iron and timber into goods: 2 + development / 3 bales a year",
            consumes=Resources(iron=1, timber=1),
        ),
        BuildingKind.STABLES: BuildingSpec(
            name="Stables",
            category=military,
            cost=Resources(ducats=45, timber=8),
            effect="lets this province raise cavalry",
        ),
        BuildingKind.CANNON_FOUNDRY: BuildingSpec(
            name="Cannon foundry",
            category=military,
            cost=Resources(ducats=90, iron=10, timber=6),
            effect="lets this province cast artillery; it melts 2 iron a year",
            requires_tech=(TechBranch.MILITARY, 2),
            consumes=Resources(iron=2),
        ),
        BuildingKind.MILITARY_ACADEMY: BuildingSpec(
            name="Military academy",
            category=military,
            cost=Resources(ducats=140, iron=6, timber=12),
            effect="one more general for the realm; generals appointed here start a star higher",
            requires_tech=(TechBranch.MILITARY, 3),
            unique=True,
        ),
        BuildingKind.ARMS_MANUFACTORY: BuildingSpec(
            name="Arms manufactory",
            category=military,
            cost=Resources(ducats=130, iron=10, timber=10),
            effect="regiments raised anywhere in the realm need half the iron and no goods; "
            "it works 3 iron a year",
            requires_tech=(TechBranch.MILITARY, 1),
            unique=True,
            consumes=Resources(iron=3),
        ),
        BuildingKind.POWDER_MILL: BuildingSpec(
            name="Powder mill",
            category=military,
            cost=Resources(ducats=120, iron=6, timber=12),
            effect="+5% battle power, and your assaults knock one more fort level off; it burns "
            "2 timber a year",
            requires_tech=(TechBranch.MILITARY, 2),
            unique=True,
            consumes=Resources(timber=2),
        ),
        BuildingKind.ROYAL_EXCHANGE: BuildingSpec(
            name="Royal exchange",
            category=civil,
            cost=Resources(ducats=160, iron=4, timber=14),
            effect="+10% ducat income across the realm; it trades 2 bales of goods a year",
            requires_tech=(TechBranch.ECONOMY, 3),
            consumes=Resources(goods=2),
            unique=True,
        ),
        BuildingKind.OBSERVATORY: BuildingSpec(
            name="Observatory",
            category=civil,
            cost=Resources(ducats=120, iron=4, timber=10),
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


class MapDef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    provinces: dict[ProvinceId, ProvinceDef]

    def adjacent(self, a: ProvinceId, b: ProvinceId) -> bool:
        p = self.provinces[a]
        return b in p.neighbors or b in p.sea_neighbors

    def is_sea_crossing(self, a: ProvinceId, b: ProvinceId) -> bool:
        return b in self.provinces[a].sea_neighbors

    def all_neighbors(self, a: ProvinceId) -> tuple[ProvinceId, ...]:
        p = self.provinces[a]
        return p.neighbors + p.sea_neighbors


# ---------------------------------------------------------------- the rules (tunable)


class Rules(BaseModel):
    """Every number the engine uses. Part of the state so a tournament can vary them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

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
    ducat_upkeep_per_regiment: float = 0.5  # pay, rounded up for the whole army
    manpower_cap_base: int = 10  # manpower cap = base + years x yearly manpower
    manpower_cap_years: int = 6
    develop_base_ducats: int = 12  # cheap to start, dear to finish
    develop_ducats_per_level: int = 8
    develop_timber_base: int = 2  # timber for new roads, mills and houses
    develop_timber_per_two_levels: int = 1
    develop_grain_base: int = 4  # grain to feed the new townsfolk: base + the development
    develop_grain_per_level: int = 1
    max_development: int = 12
    develop_goods_from: int = 6  # from this development, developing also takes goods
    workshop_base_goods: int = 2
    workshop_goods_per_development: int = 3  # +1 bale for every this many levels
    # the European market: what a unit of each traded resource costs in ducats, before the
    # merchants' cut; prices move with what all Europe buys and sells
    market_prices: dict[str, float] = Field(
        default_factory=lambda: {"grain": 1.0, "iron": 2.0, "timber": 1.5, "goods": 3.0}
    )
    market_spread: float = 0.15  # the merchants' cut, on buying and selling
    market_depth: int = 60  # units of net demand that move a price by the elasticity
    market_elasticity: float = 0.25
    market_reversion: float = 0.1  # a year, back towards the base price
    market_floor: float = 0.4  # times the base price
    market_ceiling: float = 3.0
    max_trade_per_order: int = 200
    buildings: dict[BuildingKind, BuildingSpec] = Field(default_factory=default_buildings)
    development_per_building_slot: int = 4  # slots = 1 + development // this
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
    roll_min: float = 0.8
    roll_max: float = 1.2
    winner_loss_factor: float = 0.5  # winner loses factor * (loser power / winner power)

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
        default_factory=lambda: {"alliance": 20, "non_aggression": 10, "peace": 5}
    )
    opinion_war_declared: int = -40  # the victim's opinion of the aggressor
    opinion_betrayal: int = -10  # everyone else's opinion of a treaty breaker
    opinion_province_taken: int = -10
    opinion_call_answered: int = 20
    opinion_call_ignored: int = -30
    opinion_shared_enemy: int = 3  # a year, fighting the same enemy
    opinion_decay: float = 0.1  # a year, towards zero
    opinion_same_faith: int = 1  # a year
    opinion_other_faith: int = -1  # a year

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

    # victory
    domination_share: float = 0.5  # own this share of all provinces to win outright
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
    siege_years: NonNegativeInt = 0  # years of siege won so far

    @property
    def holder(self) -> NationId | None:
        """Whoever holds the province now: its occupier in a war, else its owner."""
        return self.controller or self.owner

    @property
    def fort(self) -> int:
        """Fort level: how many fortifications (fort, citadel) stand here."""
        return sum(b in (BuildingKind.FORT, BuildingKind.CITADEL) for b in self.buildings)

    def army(self) -> dict[UnitKind, int]:
        """The garrison by kind, every kind listed."""
        left = self.troops
        out = dict.fromkeys(UnitKind, 0)
        for kind in (UnitKind.ARTILLERY, UnitKind.CAVALRY, UnitKind.ARCHERS):
            out[kind] = min(self.units.get(kind, 0), left)
            left -= out[kind]
        out[UnitKind.INFANTRY] = left
        return out

    def set_army(self, army: dict[UnitKind, int]) -> None:
        self.troops = sum(army.values())
        self.units = {k: n for k, n in army.items() if k != UnitKind.INFANTRY and n}

    def add(self, army: dict[UnitKind, int]) -> None:
        mine = self.army()
        self.set_army({k: mine[k] + army.get(k, 0) for k in UnitKind})

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


class NationState(BaseModel):
    id: NationId
    name: str
    color: str  # hex, for the viewer
    capital: ProvinceId
    resources: Resources
    stability: int = 0
    alive: bool = True
    technology: dict[TechBranch, int] = Field(default_factory=lambda: dict.fromkeys(TechBranch, 0))
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
    tax: int = Field(default=0, ge=-2, le=2)  # -2 very low ... +2 very high, see Rules.tax_*


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


class Treaty(BaseModel):
    kind: TreatyKind
    parties: tuple[NationId, NationId]  # sorted, see `pair`
    since: int
    until: int | None = None  # last turn it is in force; None: until cancelled
    payer: NationId | None = None  # tribute and army limit: the side bound by it
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
    finished: bool = False
    winner: NationId | None = None

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
        """Every regiment of a nation, in its own provinces and in those it occupies."""
        return sum(s.troops for s in self.provinces.values() if s.holder == nation)

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
