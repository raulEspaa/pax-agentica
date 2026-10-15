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
    """What a province produces on top of its base output."""

    GRAIN = "grain"
    IRON = "iron"
    TIMBER = "timber"
    GOLD = "gold"  # extra ducats: trade cities, mines of precious metal


RESOURCE_NAMES = ("ducats", "manpower", "iron", "grain", "timber")


class Resources(BaseModel):
    """A bundle of the five national resources. Never negative."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ducats: NonNegativeInt = 0
    manpower: NonNegativeInt = 0
    iron: NonNegativeInt = 0
    grain: NonNegativeInt = 0
    timber: NonNegativeInt = 0

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
    STABLES = "stables"
    CANNON_FOUNDRY = "cannon_foundry"
    # great works: one per realm, felt across all of it
    MILITARY_ACADEMY = "military_academy"
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


def default_tech_tree() -> dict[TechBranch, list[TechLevel]]:
    """Every branch also gives its per-level bonus (see Rules); these are the milestones."""
    t = TechLevel
    return {
        TechBranch.MILITARY: [
            t(name="Pike and Shot", unlocks="the armory"),
            t(name="Bastions", unlocks="the citadel and the cannon foundry"),
            t(name="Tercios", unlocks="training grounds and the military academy"),
            t(name="Field Artillery", unlocks="your attacks ignore one level of enemy forts"),
            t(name="Military Revolution", unlocks="one more general"),
        ],
        TechBranch.ECONOMY: [
            t(name="Banking", unlocks="the bank"),
            t(name="Printing Press", unlocks="the university and the observatory"),
            t(
                name="Mercantilism",
                unlocks="marketplaces yield +150% instead of +100%, and the royal exchange",
            ),
            t(name="Humanism", unlocks="the cathedral"),
            t(name="Cameralism", unlocks="one more building slot in every province"),
        ],
        TechBranch.ENGINEERING: [
            t(name="Blast Furnace", unlocks="ironworks"),
            t(
                name="Water Mills",
                unlocks="farm estates and lumber mills yield +150% instead of +100%",
            ),
            t(name="Roads and Canals", unlocks="armies eat 20% less grain"),
            t(name="Star Forts", unlocks="your forts and citadels give +35% instead of +25%"),
            t(name="Grand Architecture", unlocks="provinces can grow to development 15"),
        ],
    }


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


class Advisor(BaseModel):
    """A councillor: hired once, paid every year, and effective by skill (1 to 3)."""

    id: int
    name: str
    role: AdvisorRole
    skill: int = Field(ge=1, le=3)


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


def default_buildings() -> dict[BuildingKind, BuildingSpec]:
    civil, military = BuildingCategory.CIVIL, BuildingCategory.MILITARY
    return {
        BuildingKind.MARKETPLACE: BuildingSpec(
            name="Marketplace",
            category=civil,
            cost=Resources(ducats=50, timber=6),
            effect="doubles the province's ducats (at least +1)",
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
            effect="doubles the province's iron (at least +1)",
            requires_tech=(TechBranch.ENGINEERING, 1),
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
            effect="developing this province costs 30% fewer ducats",
            requires_tech=(TechBranch.ECONOMY, 2),
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
            effect="doubles the province's manpower (at least +1), which also raises the cap",
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
            effect="lets this province cast artillery",
            requires_tech=(TechBranch.MILITARY, 2),
        ),
        BuildingKind.MILITARY_ACADEMY: BuildingSpec(
            name="Military academy",
            category=military,
            cost=Resources(ducats=140, iron=6, timber=12),
            effect="one more general for the realm; generals appointed here start a star higher",
            requires_tech=(TechBranch.MILITARY, 3),
            unique=True,
        ),
        BuildingKind.ROYAL_EXCHANGE: BuildingSpec(
            name="Royal exchange",
            category=civil,
            cost=Resources(ducats=160, iron=4, timber=14),
            effect="+10% ducat income across the realm",
            requires_tech=(TechBranch.ECONOMY, 3),
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
            cost=Resources(ducats=7, manpower=2, iron=1, timber=2),
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
            cost=Resources(ducats=20, manpower=1, iron=6, timber=2),
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
    good_yield_per_development: int = 1
    stability_income_bonus: float = 0.1  # ducat income x (1 + bonus * stability)
    recruit_cost: Resources = Resources(ducats=6, manpower=2, iron=2)
    disband_refund: Resources = Resources(manpower=2)  # per regiment sent home
    grain_upkeep_per_regiment: int = 1
    ducat_upkeep_per_regiment: float = 0.5  # pay, rounded up for the whole army
    manpower_cap_base: int = 10  # manpower cap = base + years x yearly manpower
    manpower_cap_years: int = 6
    develop_base_ducats: int = 25
    develop_ducats_per_level: int = 5
    develop_timber_base: int = 2  # timber for new roads, mills and houses
    develop_timber_per_two_levels: int = 1
    max_development: int = 12
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


class Treaty(BaseModel):
    kind: TreatyKind
    parties: tuple[NationId, NationId]  # sorted, see `pair`
    since: int
    until: int | None = None  # last turn it is in force; None: until cancelled


class War(BaseModel):
    parties: tuple[NationId, NationId]  # sorted
    since: int


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
    give: Resources = Resources()  # trade: what the sender gives
    receive: Resources = Resources()  # trade: what the sender asks for
    enemy: NationId | None = None  # call to arms: who the sender is fighting


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

    def troops_of(self, nation: NationId) -> int:
        return sum(s.troops for s in self.provinces.values() if s.owner == nation)

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
