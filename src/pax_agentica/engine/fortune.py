"""Fortune: the events of the age, each a decision for the crown.

Every year a nation may meet one event: the Reformation, a plague, a loan from the Fuggers, a
great artist seeking a patron. The event waits in the nation's view until it answers with
`choose_option`; a nation that does not answer by the end of the next year takes the first
option. The choices are orders like any other, so an AI ruler weighs them too.
"""

import random
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from pax_agentica.engine.model import (
    Faith,
    GameState,
    Good,
    NationId,
    ProvinceId,
)

type Check = Callable[[GameState, NationId], bool]


class Option(BaseModel):
    """One answer to an event and what it does. Numbers are added to the nation (or the event's
    province); a cost the treasury cannot meet is paid as far as it can."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    ducats: int = 0
    grain: int = 0
    iron: int = 0
    timber: int = 0
    manpower: int = 0
    stability: int = 0
    prestige: int = 0
    war_exhaustion: float = 0.0
    development: int = 0  # in the event's province
    unrest: int = 0  # years, in the event's province
    regiments: int = 0  # lost (negative) in the event's province
    opinion: int = 0  # of every other court
    faith: Faith | None = None  # the realm turns to this faith
    loan: tuple[int, int] | None = None  # (ducats a year, years) to repay
    general_skill: int = 0  # for the realm's best general, up to 3
    flag: str | None = None  # a choice that lasts while the crisis does (e.g. "quarantine")
    note: str = ""  # what the flag does, in words


class EventSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    id: str
    title: str
    text: str  # may name {nation}, {province}, {ruler}, {artist}
    options: tuple[Option, ...]
    weight: float = 1.0
    once: bool = False  # at most once per nation per game
    needs_province: bool = False  # happens in one of the nation's provinces
    check: Check = Field(default=lambda _s, _n: True, exclude=True)


def _year(state: GameState) -> int:
    return state.year


ARTISTS = {
    "france": "Leonardo da Vinci",
    "england": "Hans Holbein",
    "spain": "Titian",
    "austria": "Albrecht Dürer",
    "ottomans": "Mimar Sinan",
    "sweden": "Urban Målare",
    "russia": "Aristotele Fioravanti",
    "poland": "Veit Stoss",
    "brandenburg": "Lucas Cranach",
}

EVENTS: tuple[EventSpec, ...] = (
    EventSpec(
        id="reformation",
        title="The Reformation",
        text="An Augustinian monk named Luther has nailed ninety-five theses to a church door, and "
        "the printers carry them everywhere. Preachers in {nation} ask whether the Church's lands "
        "and tithes belong to Rome at all.",
        options=(
            Option(label="Defend the old faith", stability=1, prestige=5),
            Option(
                label="Embrace reform and take the Church's lands",
                ducats=150,
                stability=-1,
                prestige=-2,
                faith=Faith.PROTESTANT,
            ),
        ),
        weight=4.0,
        once=True,
        check=lambda s, n: s.year >= 1517 and s.nations[n].faith == Faith.CATHOLIC,
    ),
    EventSpec(
        id="plague",
        title="Plague",
        text="The sweating sickness has come to {province}. The physicians want the gates shut "
        "and the sick walled up; the priests want processions.",
        options=(
            Option(label="Quarantine the town, whatever it costs", ducats=-40),
            Option(label="Pray, and let God decide", development=-1, manpower=-5, stability=-1),
        ),
        needs_province=True,
        check=lambda s, n: any(
            s.provinces[p].development >= 3
            for p in s.provinces_of(n)
            if not s.provinces[p].controller
        ),
    ),
    EventSpec(
        id="harvest",
        title="A great harvest",
        text="The barns of {nation} are full to the rafters, and merchants are already asking "
        "what the surplus will cost.",
        options=(
            Option(label="Fill the granaries", grain=30),
            Option(label="Sell the surplus abroad", ducats=35),
        ),
    ),
    EventSpec(
        id="fuggers",
        title="The Fuggers offer a loan",
        text="An agent of the house of Fugger, of Augsburg, is at court. His master lends to "
        "emperors; he would lend to {ruler} too, at a price.",
        options=(
            Option(
                label="Take 120 ducats now, repay 16 a year for ten years",
                ducats=120,
                loan=(16, 10),
            ),
            Option(label="We pay our way"),
        ),
        weight=0.8,
    ),
    EventSpec(
        id="artist",
        title="A master seeks a patron",
        text="{artist} asks for a commission at the court of {nation}: a portrait, a chapel, a "
        "palace. Europe will talk of it for a century.",
        options=(
            Option(label="Commission the work", ducats=-70, prestige=8, stability=1),
            Option(label="We cannot spare the money"),
        ),
        once=True,
    ),
    EventSpec(
        id="revolt",
        title="The peasants rise",
        text="Taxes and bad years have driven the peasants of {province} to burn the manor "
        "rolls. They march with pitchforks and a list of grievances.",
        options=(
            Option(label="Hear their grievances", ducats=-50, stability=1),
            Option(label="Send the soldiers", regiments=-3, unrest=2, prestige=-2),
        ),
        weight=2.0,
        needs_province=True,
        check=lambda s, n: s.nations[n].stability <= -1,
    ),
    EventSpec(
        id="silver",
        title="Silver from the Indies",
        text="The fleets bring silver from the mines of the New World by the shipload. Money "
        "has never been so plentiful; prices rise with it.",
        options=(
            Option(label="Mint it all", ducats=200, stability=-1),
            Option(label="Hoard it, and spend with care", ducats=90),
        ),
        weight=3.0,
        once=True,
        check=lambda s, n: n == "spain" and s.year >= 1545,
    ),
    EventSpec(
        id="comet",
        title="A comet in the sky",
        text="A great comet hangs over {nation} for forty nights. The people whisper of the end "
        "of kings; the astronomers ask for instruments.",
        options=(
            Option(label="Pay the astronomers to explain it", ducats=-30, prestige=3),
            Option(label="It is an omen: let the priests calm the people", stability=-1),
        ),
        weight=0.6,
    ),
    EventSpec(
        id="reformer",
        title="A captain with new ideas",
        text="A veteran captain proposes a new drill: ranks that fire in turn, pikes that move as "
        "one. He wants money and the ear of the generals.",
        options=(
            Option(label="Fund his drill", ducats=-60, general_skill=1, prestige=2),
            Option(label="The old ways have served us"),
        ),
        check=lambda s, n: bool(s.generals_of(n)),
    ),
    EventSpec(
        id="nobles",
        title="The nobles grumble",
        text="The great lords of {nation} want their old privileges confirmed: their courts, "
        "their tolls, their seats at council.",
        options=(
            Option(label="Confirm their privileges", stability=1, ducats=-20, prestige=-3),
            Option(label="The crown is above them", stability=-1, prestige=4),
        ),
        check=lambda s, n: s.nations[n].stability >= 0,
    ),
    EventSpec(
        id="fair",
        title="A great fair",
        text="Merchants from half of Europe ask leave to hold a fair at {province}: cloth, wine, "
        "spices and news.",
        options=(
            Option(label="Grant the charter", ducats=40, opinion=3),
            Option(label="Tax them hard", ducats=70, opinion=-3),
        ),
        needs_province=True,
    ),
    EventSpec(
        id="mine",
        title="A new vein",
        text="Miners in {province} have struck a rich vein of ore deep in the hills.",
        options=(
            Option(label="Open a new mine", ducats=-40, development=1),
            Option(label="Sell the rights", ducats=40),
        ),
        weight=0.8,
        needs_province=True,
        check=lambda s, n: any(
            s.map.provinces[p].good in (Good.IRON, Good.COPPER, Good.SILVER, Good.GOLD, Good.SALT)
            for p in s.provinces_of(n)
        ),
    ),
)


# The great troubles of the age: one falls on all Europe once a game, and every crown must
# answer it (the answers are events like the others, never drawn by chance).
class CrisisSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    text: str
    years: int
    event: str  # the decision every crown faces when it begins


CRISES: dict[str, CrisisSpec] = {
    "plague": CrisisSpec(
        id="plague",
        title="The Great Plague",
        text="The pestilence is back, worse than any since the Black Death: for three years "
        "every town of Europe may lose its people.",
        years=3,
        event="great_plague",
    ),
    "ice_age": CrisisSpec(
        id="ice_age",
        title="The Little Ice Age",
        text="Rivers freeze in May and the harvests fail: for five years every field yields "
        "a third less, and bread is dear across Europe.",
        years=5,
        event="frozen_harvests",
    ),
    "price_revolution": CrisisSpec(
        id="price_revolution",
        title="The Price Revolution",
        text="Silver from the Indies floods Europe: for six years everything bought on the "
        "market costs two fifths more, works cost a fifth more, and coin comes easier.",
        years=6,
        event="silver_flood",
    ),
}

CRISIS_EVENTS: tuple[EventSpec, ...] = (
    EventSpec(
        id="great_plague",
        title="The plague is at the gates",
        text="Carts of the dead in the ports, bells tolling in every parish. {ruler} must "
        "choose: close the towns and starve the trade, or keep the markets open and pray.",
        options=(
            Option(
                label="Close the towns and the ports",
                ducats=-30,
                stability=-1,
                flag="quarantine",
                note="towns are a third as likely to lose people; ducats -15% while it lasts",
            ),
            Option(label="Keep the markets open, and pray"),
        ),
        weight=0,
    ),
    EventSpec(
        id="frozen_harvests",
        title="The harvest has failed",
        text="Frost in June, rain in August: the granaries of {nation} are half empty and the "
        "price of bread doubles in the towns.",
        options=(
            Option(label="Open the royal granaries to the people", grain=-30, stability=1),
            Option(label="Requisition grain for the army", grain=25, stability=-1),
        ),
        weight=0,
    ),
    EventSpec(
        id="silver_flood",
        title="The silver of the Indies",
        text="Every merchant of {nation} counts more coin and buys less with it. The mint "
        "masters ask {ruler} whether to strike new money.",
        options=(
            Option(label="Strike new coin", ducats=80, stability=-1),
            Option(label="Hold the currency sound", stability=1, prestige=2),
        ),
        weight=0,
    ),
)

# ---------------------------------------------------------------- the great events of the age
# Each happens once a game, in its years, when Europe is as it needs to be: the crowns it falls
# to decide, and what they decide goes beyond the numbers (see resolve._history_effects).


class HistorySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    event: EventSpec
    first: int  # the years it may happen in
    last: int
    ready: Check = Field(exclude=True)  # Europe is as it needs to be (the nation is unused)
    who: Callable[[GameState], list[NationId]] = Field(exclude=True)  # the crowns that decide


def _alive(state: GameState, *nations: NationId) -> bool:
    return all(n in state.nations and state.nations[n].alive for n in nations)


def _free(state: GameState, *provinces: ProvinceId) -> bool:
    return any(state.provinces[p].owner is None for p in provinces if p in state.provinces)


def _sultans_sea(state: GameState) -> float:
    from pax_agentica.engine.mechanics import naval_power  # here: mechanics imports this module

    return sum(
        naval_power(state, "ottomans", z)
        for z, zone in state.map.seas.items()
        if zone.water.value == "mediterranean"
    ) if _alive(state, "ottomans") else 0.0  # fmt: skip


def _league_crowns(state: GameState) -> list[NationId]:
    return [
        n
        for n, ns in state.nations.items()
        if ns.alive
        and n != "ottomans"
        and ns.faith == Faith.CATHOLIC
        and any(
            state.map.seas[z].water.value == "mediterranean"
            for p in state.provinces_of(n)
            for z in state.map.provinces[p].seas
        )
    ]


def _sultan_borders_austria(state: GameState) -> bool:
    if not _alive(state, "ottomans", "austria") or state.at_war("ottomans", "austria"):
        return False
    austrian = set(state.provinces_of("austria"))
    return any(
        q in austrian
        for p in state.provinces_of("ottomans")
        for q in state.map.provinces[p].neighbors
    )


HISTORY: tuple[HistorySpec, ...] = (
    HistorySpec(
        event=EventSpec(
            id="burgundy",
            title="The Burgundian inheritance",
            text=(
                "Philip the Handsome, lord of the Low Countries, is dead, and his heirs are "
                "Habsburgs. Flanders and Holland, the richest towns north of the Alps, look to "
                "{ruler} for their next lord."
            ),
            weight=0,
            options=(
                Option(label="Claim the Low Countries for the house of Habsburg", prestige=5,
                       note="Flanders and Holland, if still free, become yours; France will not "
                       "forget it"),
                Option(label="Let the Spanish branch have them", prestige=2,
                       note="Flanders and Holland, if still free, pass to Spain, who will be "
                       "grateful"),
                Option(label="Leave the Estates to rule themselves", stability=1),
            ),
        ),
        first=1504,
        last=1512,
        ready=lambda st, _n: _alive(st, "austria") and _free(st, "flanders", "holland"),
        who=lambda _st: ["austria"],
    ),
    HistorySpec(
        event=EventSpec(
            id="cloth_of_gold",
            title="The Field of the Cloth of Gold",
            text=(
                "Near Calais the King of France pitches tents of gold brocade, and asks {ruler} "
                "to meet him there: jousts, banquets and a peace to astonish Europe."
            ),
            weight=0,
            options=(
                Option(label="Meet the French king in all splendour", ducats=-60, prestige=5,
                       note="France and England think better of each other (+25)"),
                Option(label="Send an ambassador instead"),
            ),
        ),
        first=1518,
        last=1522,
        ready=lambda st, _n: _alive(st, "england", "france") and not st.at_war("england", "france"),
        who=lambda _st: ["england"],
    ),
    HistorySpec(
        event=EventSpec(
            id="vienna",
            title="The road to Vienna",
            text=(
                "Hungary lies open, and the Sultan's council speaks of the golden apple: "
                "Vienna. The janissaries are ready to march if {ruler} commands it."
            ),
            weight=0,
            options=(
                Option(label="March on Vienna", war_exhaustion=1.0,
                       note="war with Austria, and 8 veteran janissaries on its border"),
                Option(label="Not this year: consolidate the conquests", stability=1),
            ),
        ),
        first=1526,
        last=1535,
        ready=lambda st, _n: _sultan_borders_austria(st),
        who=lambda _st: ["ottomans"],
    ),
    HistorySpec(
        event=EventSpec(
            id="holy_league",
            title="The Holy League",
            text=(
                "The Sultan's galleys rule the inland sea. The Pope calls the Catholic crowns to "
                "a Holy League: Venice and the Papal States will send their galleys to whoever "
                "joins, and next year the League's fleets will seek the Sultan's as one."
            ),
            weight=0,
            options=(
                Option(label="Join the Holy League", ducats=-40, prestige=3,
                       note="6 papal and Venetian galleys join your fleet; war with the "
                       "Sultan; next year a great battle of the League"),
                Option(label="Stay out of it", prestige=-2),
            ),
        ),
        first=1530,
        last=1549,
        ready=lambda st, _n: _sultans_sea(st) >= 12 and bool(_league_crowns(st)),
        who=_league_crowns,
    ),
)  # fmt: skip

EVENTS_BY_ID = {e.id: e for e in (*EVENTS, *CRISIS_EVENTS, *(h.event for h in HISTORY))}


def roll(
    state: GameState, nation: NationId, rng: random.Random, chance: float
) -> tuple[EventSpec, ProvinceId | None] | None:
    """Maybe an event for this nation this year, and the province it falls on."""
    if rng.random() >= chance:
        return None
    me = state.nations[nation]
    pool = [
        e
        for e in EVENTS
        if e.weight > 0 and not (e.once and e.id in me.events_seen) and e.check(state, nation)
    ]
    if not pool:
        return None
    event = rng.choices(pool, weights=[e.weight for e in pool])[0]
    province = None
    if event.needs_province:
        land = [p for p in state.provinces_of(nation) if not state.provinces[p].controller]
        if event.id == "mine":
            land = [
                p
                for p in land
                if state.map.provinces[p].good
                in (Good.IRON, Good.COPPER, Good.SILVER, Good.GOLD, Good.SALT)
            ]
        if event.id == "plague":
            land = [p for p in land if state.provinces[p].development >= 3]
        if not land:
            return None
        province = rng.choice(sorted(land))
    return event, province


def describe(
    event: EventSpec, state: GameState, nation: NationId, province: ProvinceId | None
) -> str:
    me = state.nations[nation]
    ruler = f"{me.ruler.title} {me.ruler.name}" if me.ruler else "the crown"
    return event.text.format(
        nation=me.name,
        province=state.map.provinces[province].name if province else "",
        ruler=ruler,
        artist=ARTISTS.get(nation, "A Florentine master"),
    )


def effects_text(option: Option) -> str:
    """What an option does, in a few words."""
    parts = []
    for field in ("ducats", "grain", "iron", "timber", "manpower"):
        value = getattr(option, field)
        if value:
            parts.append(f"{value:+d} {field}")
    for field, word in (
        ("stability", "stability"),
        ("prestige", "prestige"),
        ("development", "development here"),
        ("opinion", "opinion of every court"),
        ("general_skill", "skill for your best general"),
    ):
        value = getattr(option, field)
        if value:
            parts.append(f"{value:+d} {word}")
    if option.unrest:
        parts.append(f"{option.unrest} years of unrest here")
    if option.regiments:
        parts.append(f"{-option.regiments} regiments lost here")
    if option.faith:
        parts.append(f"turn {option.faith.value}")
    if option.loan:
        yearly, years = option.loan
        parts.append(f"repay {yearly} ducats a year for {years} years")
    if option.note:
        parts.append(option.note)
    return ", ".join(parts) or "nothing changes"
