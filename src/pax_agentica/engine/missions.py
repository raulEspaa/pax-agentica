"""Missions: the ambitions history gave each crown in 1500.

Every great power has five missions. A mission is a list of goals (own these provinces, reach
this development, raise this building, ally with that court...) written as data, so a ruler,
bot or language model can read exactly what is asked and how far it has come. Some missions
open only once an earlier one is done. A mission completes by itself at the end of the year in
which all its goals hold; it pays at once (ducats, prestige, stability) and the last of each
chain leaves a lasting bonus to the realm.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pax_agentica.engine.model import (
    BuildingKind,
    GameState,
    NationId,
    ProvinceId,
    TechBranch,
    TreatyKind,
)

GoalKind = Literal[
    "own",  # hold every province listed (or any one of them, with `any_of`)
    "development",  # total development of the realm at least `amount`
    "province_development",  # development of `province` at least `amount`
    "building",  # a `building` standing in `province`, or anywhere in the realm
    "workings",  # the workings of `province` at level `amount` or more
    "tech",  # `branch` technology at level `amount` or more
    "alliance",  # an alliance with any of `nations`
    "prestige",  # prestige at least `amount`
    "regiments",  # an army of at least `amount` regiments
]

# what a lasting bonus can raise: the same kinds of bonus as the monuments give
Bonus = Literal[
    "ducat_income",
    "research_discount",
    "battle_power",
    "building_discount",
    "stability_discount",
    "fort_bonus_per_level",
]


class Goal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: GoalKind
    provinces: tuple[ProvinceId, ...] = ()
    any_of: bool = False
    province: ProvinceId | None = None
    building: BuildingKind | None = None
    branch: TechBranch | None = None
    nations: tuple[NationId, ...] = ()
    amount: int = 0


class Mission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    lore: str
    goals: tuple[Goal, ...]
    after: str | None = None  # opens once this mission of the same nation is done
    ducats: int = 0
    prestige: int = 0
    stability: int = 0
    bonus: Bonus | None = None  # a lasting bonus to the realm
    bonus_amount: float = 0.0
    bonus_text: str = ""


def own(*provinces: str, any_of: bool = False) -> Goal:
    return Goal(kind="own", provinces=provinces, any_of=any_of)


def building(kind: BuildingKind, province: str | None = None) -> Goal:
    return Goal(kind="building", building=kind, province=province)


MISSIONS: dict[NationId, tuple[Mission, ...]] = {
    "england": (
        Mission(
            id="wool_staple",
            title="The wool staple",
            lore="England grows the finest wool in Europe and sells it raw to Flemish looms. "
            "Weave it at home and keep the profit.",
            goals=(building(BuildingKind.WORKSHOP), building(BuildingKind.MARKETPLACE, "london")),
            ducats=80,
            prestige=5,
        ),
        Mission(
            id="union_of_crowns",
            title="One crown for the island",
            lore="James IV of Scotland is a dangerous neighbour and an ally of France. Bring "
            "the North under the English crown, by marriage or by the sword.",
            goals=(own("scotland"),),
            ducats=60,
            prestige=10,
        ),
        Mission(
            id="lordship_of_ireland",
            title="The Lordship of Ireland",
            lore="Beyond the Pale, the Irish lords rule as they please. Make the king's "
            "lordship real.",
            goals=(own("ireland"),),
            after="union_of_crowns",
            prestige=10,
            stability=1,
        ),
        Mission(
            id="against_france",
            title="The enemy of my enemy",
            lore="France is twice as large and twice as rich. England's safety lies in an "
            "alliance with the Habsburgs.",
            goals=(Goal(kind="alliance", nations=("spain", "austria")),),
            ducats=50,
            prestige=5,
        ),
        Mission(
            id="the_old_claim",
            title="King of France in name",
            lore="Every English king still styles himself King of France. Take back Normandy, "
            "the duchy of the Conqueror.",
            goals=(own("normandy"),),
            after="against_france",
            prestige=15,
            bonus="battle_power",
            bonus_amount=0.05,
            bonus_text="+5% battle power",
        ),
    ),
    "france": (
        Mission(
            id="italian_claim",
            title="The Milanese inheritance",
            lore="Louis XII claims Milan through his grandmother Valentina Visconti. The "
            "Sforza must go.",
            goals=(own("milan"),),
            ducats=80,
            prestige=10,
        ),
        Mission(
            id="naples",
            title="The kingdom of Naples",
            lore="Charles VIII rode into Naples in 1495 and lost it within the year. Finish "
            "what he began.",
            goals=(own("naples"),),
            after="italian_claim",
            prestige=15,
            bonus="ducat_income",
            bonus_amount=0.05,
            bonus_text="+5% ducats",
        ),
        Mission(
            id="the_rhine",
            title="The road to the Rhine",
            lore="Between France and the Empire lie Lorraine, Alsace and the rich cities of "
            "the Rhine.",
            goals=(own("rhineland"),),
            ducats=60,
            prestige=10,
        ),
        Mission(
            id="fontainebleau",
            title="A Renaissance court",
            lore="Italy has taught France the arts of peace. Bring the painters and the "
            "scholars to the Loire.",
            goals=(
                Goal(kind="tech", branch=TechBranch.ECONOMY, amount=2),
                Goal(kind="development", amount=45),
            ),
            ducats=60,
            stability=1,
        ),
        Mission(
            id="most_christian_king",
            title="The Most Christian King",
            lore="The King of France is the first monarch of Christendom, or should be.",
            goals=(Goal(kind="prestige", amount=50),),
            after="fontainebleau",
            ducats=100,
            bonus="stability_discount",
            bonus_amount=0.10,
            bonus_text="stability 10% cheaper",
        ),
    ),
    "spain": (
        Mission(
            id="gold_of_the_indies",
            title="The gold of the Indies",
            lore="Columbus has found a new world, and its gold comes up the Guadalquivir. "
            "Organise the trade in Seville.",
            goals=(Goal(kind="workings", province="seville", amount=2),),
            ducats=100,
            prestige=5,
        ),
        Mission(
            id="navarre",
            title="The Pyrenees",
            lore="Navarre straddles the mountains, ruled from France. Ferdinand wants it.",
            goals=(own("navarre"),),
            prestige=10,
            stability=1,
        ),
        Mission(
            id="two_sicilies",
            title="The two Sicilies",
            lore="Aragon has held Sicily for two centuries. Naples, across the strait, is "
            "Aragon's by right.",
            goals=(own("sicily", "naples"),),
            after="navarre",
            prestige=15,
            bonus="ducat_income",
            bonus_amount=0.05,
            bonus_text="+5% ducats",
        ),
        Mission(
            id="habsburg_match",
            title="The Habsburg match",
            lore="Juana married Philip the Handsome, Juan married Margaret of Austria. Hold "
            "the alliance that the marriages made.",
            goals=(Goal(kind="alliance", nations=("austria",)),),
            ducats=60,
            prestige=5,
        ),
        Mission(
            id="barbary_coast",
            title="The Barbary coast",
            lore="Corsairs from Algiers and Tunis raid the coasts of Valencia. Carry the "
            "Reconquista across the sea.",
            goals=(own("algiers", "tunis", any_of=True),),
            after="habsburg_match",
            prestige=10,
            bonus="battle_power",
            bonus_amount=0.05,
            bonus_text="+5% battle power",
        ),
    ),
    "austria": (
        Mission(
            id="tu_felix_austria",
            title="Let others wage war",
            lore="Bella gerant alii, tu felix Austria nube: the house of Austria wins "
            "kingdoms by marriage. Find a royal ally.",
            goals=(Goal(kind="alliance", nations=("spain", "poland", "england", "brandenburg")),),
            ducats=60,
            prestige=5,
        ),
        Mission(
            id="burgundian_inheritance",
            title="The Burgundian inheritance",
            lore="The Low Countries are Philip the Handsome's by right: the richest towns "
            "north of the Alps. Bring them under the house of Austria.",
            goals=(own("flanders", "holland", any_of=True),),
            after="tu_felix_austria",
            prestige=15,
            bonus="ducat_income",
            bonus_amount=0.06,
            bonus_text="+6% ducats",
        ),
        Mission(
            id="black_army",
            title="The Black Army",
            lore="King Matthias of Hungary kept a standing army of mercenaries in black "
            "armour. The Danubian monarchy needs one again.",
            goals=(Goal(kind="regiments", amount=40),),
            ducats=60,
            prestige=5,
        ),
        Mission(
            id="bulwark_vienna",
            title="Bulwark of the West",
            lore="If the Turk comes up the Danube, Buda and Vienna are the gates. Wall them well.",
            goals=(
                building(BuildingKind.FORT, "buda"),
                building(BuildingKind.FORT, "vienna"),
                building(BuildingKind.CITADEL, "vienna"),
            ),
            after="black_army",
            prestige=10,
            bonus="fort_bonus_per_level",
            bonus_amount=0.10,
            bonus_text="forts +10% stronger",
        ),
        Mission(
            id="imperial_diets",
            title="The Imperial reforms",
            lore="Maximilian wants a common penny and an imperial army from the diets. Show "
            "them a realm worth following.",
            goals=(Goal(kind="development", amount=50),),
            stability=1,
            prestige=10,
        ),
    ),
    "ottomans": (
        Mission(
            id="bosnia",
            title="The Bosnian frontier",
            lore="The last Bosnian king was beheaded in 1463, but the hill forts still hold "
            "out. Finish the conquest.",
            goals=(own("bosnia"),),
            ducats=60,
            prestige=5,
        ),
        Mission(
            id="mohacs",
            title="The field of Mohács",
            lore="Buda is the shield of Christendom. Break it, and the road up the Danube "
            "lies open.",
            goals=(own("buda"),),
            after="bosnia",
            prestige=15,
            ducats=100,
        ),
        Mission(
            id="golden_apple",
            title="The golden apple",
            lore="Vienna, the golden apple, the city of the Caesar of the West.",
            goals=(own("vienna"),),
            after="mohacs",
            prestige=20,
            bonus="battle_power",
            bonus_amount=0.08,
            bonus_text="+8% battle power",
        ),
        Mission(
            id="corsairs",
            title="The corsair beys",
            lore="The Barbarossa brothers offer the Sultan the coast of Africa. Take it.",
            goals=(own("algiers", "tunis", any_of=True),),
            ducats=80,
            prestige=10,
        ),
        Mission(
            id="sinan",
            title="An age of builders",
            lore="The Sultan's architects will raise mosques to rival Hagia Sophia.",
            goals=(Goal(kind="province_development", province="constantinople", amount=10),),
            after="corsairs",
            prestige=10,
            bonus="building_discount",
            bonus_amount=0.08,
            bonus_text="buildings and development 8% cheaper",
        ),
    ),
    "sweden": (
        Mission(
            id="out_of_the_union",
            title="Out of the Kalmar Union",
            lore="The Danish king claims all three northern crowns. Take Zealand and the "
            "Sound, and the union is over.",
            goals=(own("zealand"),),
            prestige=15,
            stability=1,
        ),
        Mission(
            id="copper_mountain",
            title="The Great Copper Mountain",
            lore="Falun's copper is the wealth of Sweden. Dig deeper.",
            goals=(Goal(kind="workings", province="stockholm", amount=2),),
            ducats=80,
        ),
        Mission(
            id="baltic_dominion",
            title="Dominium maris Baltici",
            lore="Riga and the Livonian ports carry the grain and furs of the East. Make the "
            "Baltic a Swedish lake.",
            goals=(own("livonia"),),
            after="out_of_the_union",
            prestige=15,
            bonus="ducat_income",
            bonus_amount=0.06,
            bonus_text="+6% ducats",
        ),
        Mission(
            id="finnish_shield",
            title="The eastern shield",
            lore="Muscovy covets Karelia. Fortify Finland.",
            goals=(building(BuildingKind.FORT, "finland"),),
            ducats=40,
            prestige=5,
        ),
        Mission(
            id="new_model_army",
            title="A new model army",
            lore="Drilled peasant soldiers, light guns, officers who read: Sweden can field "
            "the best army in Europe.",
            goals=(Goal(kind="tech", branch=TechBranch.MILITARY, amount=3),),
            after="finnish_shield",
            prestige=10,
            bonus="battle_power",
            bonus_amount=0.06,
            bonus_text="+6% battle power",
        ),
    ),
    "russia": (
        Mission(
            id="third_rome",
            title="The Third Rome",
            lore="Constantinople has fallen; Moscow is its heir. Build a capital worthy of "
            "the claim.",
            goals=(Goal(kind="province_development", province="moscow", amount=8),),
            prestige=10,
            ducats=60,
        ),
        Mission(
            id="lands_of_rus",
            title="Gather the lands of Rus'",
            lore="Kiev, the mother of Russian cities, is in Lithuanian hands.",
            goals=(own("kiev"),),
            prestige=15,
            ducats=60,
        ),
        Mission(
            id="livonian_war",
            title="A window on the Baltic",
            lore="The Livonian Order bars Muscovy from the sea. Break through to Riga.",
            goals=(own("livonia"),),
            after="lands_of_rus",
            prestige=15,
            bonus="ducat_income",
            bonus_amount=0.06,
            bonus_text="+6% ducats",
        ),
        Mission(
            id="streltsy",
            title="The streltsy",
            lore="A standing army of musketeers, paid by the Tsar and loyal to him alone.",
            goals=(Goal(kind="regiments", amount=40),),
            ducats=50,
            prestige=5,
        ),
        Mission(
            id="tsar_of_all_rus",
            title="Tsar of all Rus'",
            lore="Ivan III calls himself sovereign of all Rus'. Make the title true.",
            goals=(Goal(kind="development", amount=40),),
            after="third_rome",
            stability=1,
            bonus="stability_discount",
            bonus_amount=0.10,
            bonus_text="stability 10% cheaper",
        ),
    ),
    "poland": (
        Mission(
            id="granary_of_europe",
            title="The granary of Europe",
            lore="Polish grain goes down the Vistula to Danzig and feeds Amsterdam. Improve "
            "the great estates of Masovia.",
            goals=(Goal(kind="workings", province="masovia", amount=2),),
            ducats=80,
        ),
        Mission(
            id="prussian_homage",
            title="The Prussian homage",
            lore="The Teutonic Order owes homage to the King of Poland since 1466. Make the "
            "Grand Master kneel, or take his land.",
            goals=(own("prussia"),),
            prestige=15,
            ducats=60,
        ),
        Mission(
            id="wild_fields",
            title="The Wild Fields",
            lore="Tatar raids burn the steppe every summer. Fortify Kiev.",
            goals=(building(BuildingKind.FORT, "kiev"),),
            ducats=40,
            prestige=5,
        ),
        Mission(
            id="congress_of_vienna",
            title="The Congress of Vienna",
            lore="Sigismund and Maximilian will marry their houses in 1515 and divide the "
            "East between them. Make the bargain.",
            goals=(Goal(kind="alliance", nations=("austria",)),),
            ducats=50,
            prestige=5,
        ),
        Mission(
            id="commonwealth",
            title="The Commonwealth",
            lore="A crown and a grand duchy, one parliament, one king: the largest state in "
            "Europe.",
            goals=(Goal(kind="development", amount=35),),
            after="prussian_homage",
            stability=1,
            prestige=10,
            bonus="ducat_income",
            bonus_amount=0.08,
            bonus_text="+8% ducats",
        ),
    ),
    "brandenburg": (
        Mission(
            id="viadrina",
            title="The Viadrina",
            lore="Joachim I founds a university at Frankfurt on the Oder in 1506. A small "
            "electorate must be a learned one.",
            goals=(Goal(kind="tech", branch=TechBranch.ECONOMY, amount=2),),
            ducats=60,
            prestige=5,
        ),
        Mission(
            id="saxon_rival",
            title="The Saxon rival",
            lore="The Wettins of Saxony have the silver of the Erzgebirge and Luther's "
            "Wittenberg. Brandenburg wants both.",
            goals=(own("saxony"),),
            prestige=10,
            ducats=60,
        ),
        Mission(
            id="hanseatic_trade",
            title="The Hanseatic trade",
            lore="Hamburg and the Baltic ports carry the grain of Prussia to the world. Hold "
            "the mouth of the Elbe.",
            goals=(own("hamburg"),),
            after="saxon_rival",
            prestige=15,
            bonus="ducat_income",
            bonus_amount=0.06,
            bonus_text="+6% ducats",
        ),
        Mission(
            id="army_with_a_state",
            title="An army with a state",
            lore="Sand, pine and a few towns: Brandenburg will only matter if its army does.",
            goals=(Goal(kind="regiments", amount=25),),
            ducats=50,
            prestige=5,
        ),
        Mission(
            id="great_elector",
            title="The Great Elector",
            lore="Drill, magazines, officers from the nobility: the army that will make "
            "Prussia a kingdom.",
            goals=(Goal(kind="tech", branch=TechBranch.MILITARY, amount=3),),
            after="army_with_a_state",
            prestige=10,
            bonus="battle_power",
            bonus_amount=0.08,
            bonus_text="+8% battle power",
        ),
    ),
}


def missions_of(nation: NationId) -> tuple[Mission, ...]:
    return MISSIONS.get(nation, ())


def progress(state: GameState, nation: NationId, goal: Goal) -> tuple[int, int]:
    """How far a goal has come: (have, need)."""
    held = set(state.provinces_of(nation))
    match goal.kind:
        case "own":
            have = sum(p in held for p in goal.provinces)
            return (min(have, 1), 1) if goal.any_of else (have, len(goal.provinces))
        case "development":
            return sum(state.provinces[p].development for p in held), goal.amount
        case "province_development":
            p = state.provinces[goal.province or ""]
            return (p.development if p.owner == nation else 0), goal.amount
        case "building":
            places = [goal.province] if goal.province else sorted(held)
            have = any(p in held and goal.building in state.provinces[p].buildings for p in places)
            return int(have), 1
        case "workings":
            p = state.provinces[goal.province or ""]
            return (p.workings if p.owner == nation else 0), goal.amount
        case "tech":
            level = state.nations[nation].technology[goal.branch] if goal.branch else 0
            return level, goal.amount
        case "alliance":
            allied = any(state.treaty(nation, n, TreatyKind.ALLIANCE) for n in goal.nations)
            return int(allied), 1
        case "prestige":
            return state.nations[nation].prestige, goal.amount
        case "regiments":
            return state.troops_of(nation), goal.amount


def done(state: GameState, nation: NationId, goal: Goal) -> bool:
    have, need = progress(state, nation, goal)
    return have >= need


def goal_text(state: GameState, goal: Goal) -> str:
    def names(ids: tuple[str, ...]) -> str:
        words = [state.map.provinces[p].name if p in state.map.provinces else p for p in ids]
        return " or ".join(words) if goal.any_of else " and ".join(words)

    match goal.kind:
        case "own":
            return f"hold {names(goal.provinces)}"
        case "development":
            return f"a realm of {goal.amount} development"
        case "province_development":
            return f"develop {names((goal.province or '',))} to {goal.amount}"
        case "building":
            spec = state.rules.buildings[goal.building] if goal.building else None
            where = f" in {names((goal.province,))}" if goal.province else ""
            return f"{spec.name.lower() if spec else 'a building'}{where}"
        case "workings":
            good = state.map.provinces[goal.province or ""].good
            work = state.rules.workings[good].lower()
            return f"the {work} of {names((goal.province or '',))} at level {goal.amount}"
        case "tech":
            return f"{goal.branch.value if goal.branch else ''} technology {goal.amount}"
        case "alliance":
            courts = [state.nations[n].name for n in goal.nations if n in state.nations]
            return f"an alliance with {' or '.join(courts)}"
        case "prestige":
            return f"{goal.amount} prestige"
        case "regiments":
            return f"an army of {goal.amount} regiments"


def reward_text(m: Mission) -> str:
    parts = []
    if m.ducats:
        parts.append(f"{m.ducats} ducats")
    if m.prestige:
        parts.append(f"+{m.prestige} prestige")
    if m.stability:
        parts.append(f"+{m.stability} stability")
    if m.bonus:
        parts.append(f"for good: {m.bonus_text}")
    return ", ".join(parts) or "nothing"


def open_missions(state: GameState, nation: NationId) -> list[Mission]:
    """Missions not yet done whose earlier mission, if any, is."""
    finished = set(state.nations[nation].missions_done)
    return [
        m
        for m in missions_of(nation)
        if m.id not in finished and (m.after is None or m.after in finished)
    ]


def lasting_bonuses(nation_missions_done: tuple[str, ...], nation: NationId) -> list[Mission]:
    done_ids = set(nation_missions_done)
    return [m for m in missions_of(nation) if m.id in done_ids and m.bonus]
