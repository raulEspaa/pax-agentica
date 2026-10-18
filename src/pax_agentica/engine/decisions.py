"""National decisions: the great choices each crown of 1500 could make once its time had come.

A decision is taken by order (`take_decision`), once, when its goals hold (the same goals the
missions use: provinces held, a year reached, stability, technology, colonies...) and its cost
in authority and ducats can be paid. It pays at once (prestige, stability, ducats) and leaves a
lasting effect on the realm, with the same keys as the doctrines and policies; some give the
realm a new name, as the Union of Lublin made Poland and Lithuania a Commonwealth.
"""

from pydantic import BaseModel, ConfigDict, Field

from pax_agentica.engine.missions import Goal, done, goal_text, own
from pax_agentica.engine.model import GameState, NationId, TechBranch


def year(y: int) -> Goal:
    return Goal(kind="year", amount=y)


def stable(n: int) -> Goal:
    return Goal(kind="stability", amount=n)


def tech(branch: TechBranch, level: int) -> Goal:
    return Goal(kind="tech", branch=branch, amount=level)


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    lore: str
    goals: tuple[Goal, ...]
    authority: int = 0  # spent when it is taken
    ducats: int = 0  # spent when it is taken
    rename: str | None = None  # the realm's new name
    prestige: int = 0
    stability: int = 0
    gain_ducats: int = 0  # paid at once (church lands, a dowry...)
    effects: dict[str, float] = Field(default_factory=dict)  # lasting, as doctrines' effects
    effect_text: str = ""


M, N, A, E = TechBranch.MILITARY, TechBranch.NAVAL, TechBranch.ADMINISTRATION, TechBranch.ECONOMY

DECISIONS: dict[NationId, tuple[Decision, ...]] = {
    "england": (
        Decision(
            id="great_britain",
            title="The Kingdom of Great Britain",
            lore="One king from Cornwall to Caithness: the island under one crown, and one "
            "name for it.",
            goals=(own("scotland", "highlands"), stable(1)),
            authority=30,
            rename="Great Britain",
            prestige=10,
            effects={"navy": 0.10, "manpower": 0.10},
            effect_text="fleets +10%, manpower +10%",
        ),
        Decision(
            id="act_of_supremacy",
            title="The Act of Supremacy",
            lore="The king, not the pope, is supreme head of the Church of England; the "
            "monasteries' lands go to the crown.",
            goals=(year(1534),),
            authority=25,
            stability=-1,
            gain_ducats=120,
            effects={"ducat_income": 0.05},
            effect_text="+5% ducats",
        ),
        Decision(
            id="navy_royal",
            title="The Navy Royal",
            lore="Dockyards at Deptford and Woolwich, a Navy Board, and ships built for the "
            "king's wars, not hired for them.",
            goals=(tech(N, 2),),
            authority=20,
            ducats=60,
            effects={"navy": 0.10, "ship_cost": 0.10},
            effect_text="fleets +10%, ships 10% cheaper",
        ),
    ),
    "france": (
        Decision(
            id="concordat_of_bologna",
            title="The Concordat of Bologna",
            lore="The pope grants the king of France the naming of every bishop and abbot in "
            "the realm: the Church's wealth serves the crown.",
            goals=(year(1516), stable(1)),
            authority=25,
            stability=1,
            effects={"ducat_income": 0.05},
            effect_text="+5% ducats",
        ),
        Decision(
            id="italian_wars",
            title="The crown of the Italian wars",
            lore="Milan by Orléans blood, Naples by Anjou's: a French king in Italy is a "
            "king of Europe.",
            goals=(own("milan", "naples", any_of=True), Goal(kind="prestige", amount=30)),
            authority=30,
            prestige=10,
            effects={"battle_power": 0.05},
            effect_text="+5% battle power",
        ),
        Decision(
            id="college_royal",
            title="The Collège royal",
            lore="Lecteurs royaux in Greek, Hebrew and mathematics, paid by the king, free to "
            "all: learning outside the Sorbonne's walls.",
            goals=(tech(A, 2),),
            authority=20,
            ducats=50,
            effects={"research": 0.10},
            effect_text="research 10% cheaper",
        ),
    ),
    "spain": (
        Decision(
            id="council_of_the_indies",
            title="The Council of the Indies",
            lore="A council of its own to govern the lands beyond the sea, from Seville and "
            "the court.",
            goals=(Goal(kind="colonies", amount=3),),
            authority=25,
            effects={"colonial_dues": 0.15, "colonial": 5},
            effect_text="the colonies send 15% more; expeditions 5 more progress a year",
        ),
        Decision(
            id="iberian_union",
            title="The Iberian Union",
            lore="Portugal's throne is empty and Spain's king is its heir: one crown over all "
            "the Peninsula and both Indies.",
            goals=(own("lisbon", "porto"),),
            authority=35,
            rename="The Iberian Union",
            prestige=10,
            effects={"colonial_dues": 0.20, "navy": 0.05},
            effect_text="the colonies send 20% more, fleets +5%",
        ),
        Decision(
            id="tercios",
            title="The Tercios",
            lore="Pike, shot and sword in one square, the old soldiers of Italy at its "
            "corners: the ordinance of 1534.",
            goals=(tech(M, 2),),
            authority=20,
            effects={"battle_power": 0.05, "morale": 0.05},
            effect_text="+5% battle power, +5% morale",
        ),
    ),
    "austria": (
        Decision(
            id="habsburg_monarchy",
            title="The Habsburg Monarchy",
            lore="Austria, Bohemia and Hungary under one house: not an empire of one people, "
            "but a monarchy of many crowns.",
            goals=(own("bohemia", "buda", "upper_hungary", "croatia"), stable(1)),
            authority=30,
            rename="The Habsburg Monarchy",
            prestige=10,
            effects={"manpower": 0.15},
            effect_text="+15% manpower",
        ),
        Decision(
            id="military_frontier",
            title="The Military Frontier",
            lore="Free soldier-peasants settled along the Turkish border, holding their land "
            "for the service of their arms.",
            goals=(own("croatia"),),
            authority=20,
            effects={"fort": 0.10, "manpower": 0.10},
            effect_text="forts 10% stronger a level, +10% manpower",
        ),
        Decision(
            id="imperial_reform",
            title="The Imperial Reform",
            lore="An Imperial Chamber Court, ten Circles to keep the peace, and a common "
            "penny for the Empire's wars.",
            goals=(own("bavaria", "swabia", any_of=True), stable(2)),
            authority=30,
            effects={"ducat_income": 0.05, "stability": 0.10},
            effect_text="+5% ducats, stability 10% cheaper",
        ),
    ),
    "ottomans": (
        Decision(
            id="kanun",
            title="The Kanun of Suleiman",
            lore="The sultan's laws gathered into one code beside the sharia: the Lawgiver's "
            "order over three continents.",
            goals=(year(1520), stable(1)),
            authority=25,
            effects={"stability": 0.15, "ducat_income": 0.05},
            effect_text="stability 15% cheaper, +5% ducats",
        ),
        Decision(
            id="two_seas",
            title="The Sultan of the Two Seas",
            lore="The Black Sea an Ottoman lake: the khan of the Crimea a vassal, the "
            "Danubian princes tributaries.",
            goals=(own("crimea", "wallachia", "moldavia"),),
            authority=30,
            prestige=10,
            effects={"grain_income": 0.10, "trade": 0.05},
            effect_text="+10% grain, the merchants' cut 5% lower",
        ),
        Decision(
            id="kapudan_pasha",
            title="The Kapudan Pasha",
            lore="Barbarossa, corsair of Algiers, made admiral of the sultan's fleet: the "
            "Mediterranean is the sultan's to contest.",
            goals=(own("algiers", "tunis", any_of=True), tech(N, 1)),
            authority=20,
            effects={"navy": 0.15},
            effect_text="fleets +15%",
        ),
    ),
    "sweden": (
        Decision(
            id="hereditary_crown",
            title="The hereditary crown",
            lore="The Riksdag of Västerås makes the crown of Sweden hereditary in the house of "
            "Vasa: no more elections, no more Kalmar.",
            goals=(year(1544), stable(1)),
            authority=25,
            stability=1,
            effects={"stability": 0.10},
            effect_text="stability 10% cheaper",
        ),
        Decision(
            id="swedish_empire",
            title="The Swedish Empire",
            lore="The Baltic a Swedish sea: Livonia, Scania, the Sound itself under the "
            "Vasa crown.",
            goals=(own("livonia", "scania"),),
            authority=35,
            rename="The Swedish Empire",
            prestige=10,
            effects={"battle_power": 0.05, "trade": 0.05},
            effect_text="+5% battle power, the merchants' cut 5% lower",
        ),
    ),
    "russia": (
        Decision(
            id="tsardom",
            title="The Tsardom of Russia",
            lore="The grand prince crowned tsar of all the Russias in the Dormition "
            "Cathedral: heir of Rome and of Byzantium.",
            goals=(year(1547), own("novgorod", "pskov")),
            authority=30,
            rename="The Tsardom of Russia",
            prestige=10,
            stability=1,
            effects={"manpower": 0.10},
            effect_text="+10% manpower",
        ),
        Decision(
            id="streltsy",
            title="The Streltsy",
            lore="Musketeers paid by the tsar, living in their own quarters of Moscow: Russia's "
            "first standing infantry.",
            goals=(tech(M, 2),),
            authority=20,
            effects={"battle_power": 0.05, "manpower": 0.10},
            effect_text="+5% battle power, +10% manpower",
        ),
        Decision(
            id="window_on_the_baltic",
            title="A window on the Baltic",
            lore="Narva and the Livonian ports: Russia's furs and hemp sail west without a "
            "Hanseatic middleman.",
            goals=(own("livonia"),),
            authority=25,
            effects={"trade": 0.10, "ducat_income": 0.05},
            effect_text="the merchants' cut 10% lower, +5% ducats",
        ),
    ),
    "poland": (
        Decision(
            id="union_of_lublin",
            title="The Union of Lublin",
            lore="One Commonwealth of two nations, one king and one Sejm: the largest realm in "
            "Christendom.",
            goals=(
                own("lithuania", "kiev", "polotsk"),
                Goal(kind="development", amount=28),
                stable(1),
            ),
            authority=30,
            rename="The Polish-Lithuanian Commonwealth",
            prestige=10,
            effects={"ducat_income": 0.10, "manpower": 0.10},
            effect_text="+10% ducats, +10% manpower",
        ),
        Decision(
            id="warsaw_confederation",
            title="The Warsaw Confederation",
            lore="The nobles swear to keep the peace among those who differ in religion: no "
            "stake, no exile, for any faith.",
            goals=(stable(2),),
            authority=20,
            stability=1,
            effects={"tolerance": 0.30},
            effect_text="provinces of another faith 30% less discontent",
        ),
        Decision(
            id="winged_hussars",
            title="The Winged Hussars",
            lore="The heavy lancers of the Commonwealth, the feathers on their backs: the "
            "charge that broke every army in the East.",
            goals=(tech(M, 2),),
            authority=20,
            effects={"battle_power": 0.05, "morale": 0.05},
            effect_text="+5% battle power, +5% morale",
        ),
    ),
    "brandenburg": (
        Decision(
            id="reformation_in_brandenburg",
            title="The Reformation in Brandenburg",
            lore="The elector takes the Lutheran communion, and the monasteries' lands with it.",
            goals=(year(1539),),
            authority=20,
            gain_ducats=80,
            stability=1,
        ),
        Decision(
            id="kingdom_of_prussia",
            title="The Kingdom in Prussia",
            lore="Beyond the Empire's border a duke may call himself king: Brandenburg's "
            "electors crowned at Königsberg.",
            goals=(own("prussia", "pomerania", "saxony"), Goal(kind="prestige", amount=30)),
            authority=35,
            rename="The Kingdom of Prussia",
            prestige=10,
            effects={"battle_power": 0.05, "manpower": 0.10},
            effect_text="+5% battle power, +10% manpower",
        ),
        Decision(
            id="cantonal_system",
            title="The cantonal system",
            lore="Every regiment its own canton to recruit from, the peasants drilled at home "
            "and called up each spring.",
            goals=(Goal(kind="regiments", amount=20),),
            authority=25,
            effects={"manpower": 0.20},
            effect_text="+20% manpower",
        ),
    ),
}


def decisions_of(nation: NationId) -> tuple[Decision, ...]:
    return DECISIONS.get(nation, ())


def decision(nation: NationId, decision_id: str) -> Decision | None:
    return next((d for d in decisions_of(nation) if d.id == decision_id), None)


def missing(state: GameState, nation: NationId, d: Decision) -> list[str]:
    """What a decision still lacks: its goals not met, then the authority and ducats."""
    me = state.nations[nation]
    out = [goal_text(state, g) for g in d.goals if not done(state, nation, g)]
    if me.authority < d.authority:
        out.append(f"{d.authority} authority")
    if me.resources.ducats < d.ducats:
        out.append(f"{d.ducats} ducats")
    return out


def taken_effects(nation: NationId, taken: tuple[str, ...]) -> list[Decision]:
    """The decisions a crown has taken, whose effects it keeps."""
    return [d for d in decisions_of(nation) if d.id in taken]
