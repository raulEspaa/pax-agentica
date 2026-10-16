"""The court: what a nation's ruler, advisors and technology add up to.

`modifiers` gathers every bonus a nation enjoys into one object, with a line of text per source,
so the engine, the view and a curious ruler (human or LLM) all read the same numbers.
"""

import random

from pydantic import BaseModel, ConfigDict

from pax_agentica.engine.missions import lasting_bonuses
from pax_agentica.engine.model import (
    Advisor,
    AdvisorRole,
    BuildingKind,
    GameState,
    NationId,
    Personality,
    Ruler,
    Rules,
    TechBranch,
    Trait,
)

# Thresholds of the technology milestones (see default_tech_tree).
FIELD_ARTILLERY = (TechBranch.MILITARY, 4)
MILITARY_REVOLUTION = (TechBranch.MILITARY, 5)
MERCANTILISM = (TechBranch.ECONOMY, 3)
CAMERALISM = (TechBranch.ECONOMY, 5)
WATER_MILLS = (TechBranch.ENGINEERING, 2)
ROADS_AND_CANALS = (TechBranch.ENGINEERING, 3)
STAR_FORTS = (TechBranch.ENGINEERING, 4)
GRAND_ARCHITECTURE = (TechBranch.ENGINEERING, 5)


class Modifiers(BaseModel):
    """Everything that makes this nation different from a blank one."""

    model_config = ConfigDict(frozen=True)

    ducat_income: float = 0.0  # added to the income multiplier (stability is separate)
    grain_income: float = 0.0
    battle_power: float = 0.0  # added to 1, attacking and defending, before generals
    research_discount: float = 0.0
    building_discount: float = 0.0  # ducats and timber of buildings and development
    stability_discount: float = 0.0
    treaty_break_penalty: int = 2
    extra_building_slots: int = 0
    max_development: int = 12
    grain_upkeep_factor: float = 1.0
    fort_bonus_per_level: float = 0.25
    ignores_fort_levels: int = 0
    max_generals: int = 3
    marketplace_share: float = 0.5
    mill_share: float = 0.5  # farm estates and lumber mills
    arms_manufactory: bool = False  # levies need half the iron and no goods
    sources: tuple[str, ...] = ()  # one line per bonus, for humans and prompts


def _has(state: GameState, nation: NationId, milestone: tuple[TechBranch, int]) -> bool:
    branch, level = milestone
    return state.nations[nation].technology[branch] >= level


GREAT_WORKS = (
    BuildingKind.MILITARY_ACADEMY,
    BuildingKind.ARMS_MANUFACTORY,
    BuildingKind.POWDER_MILL,
    BuildingKind.ROYAL_EXCHANGE,
    BuildingKind.OBSERVATORY,
)


def holdings(
    state: GameState, nation: NationId
) -> tuple[tuple[BuildingKind, ...], tuple[tuple[str, int], ...]]:
    """The great works and the monuments (province, level) a nation holds."""
    works: set[BuildingKind] = set()
    monuments = []
    for pid, p in state.provinces.items():
        if p.owner != nation:
            continue
        works.update(b for b in p.buildings if b in GREAT_WORKS)
        if pid in state.rules.monuments and p.monument:
            monuments.append((pid, p.monument))
    return tuple(sorted(works)), tuple(sorted(monuments))


_CACHE: dict[tuple[object, ...], tuple[Rules, Modifiers]] = {}


def modifiers(state: GameState, nation: NationId | None) -> Modifiers:
    """The sum of a nation's technology, ruler and advisors. Independents get the defaults.

    Called for every province many times a turn, so results are cached by their inputs."""
    me = state.nations[nation] if nation is not None else None
    key: tuple[object, ...] = (id(state.rules), nation)
    if me is not None:
        ruler = me.ruler
        key += (
            tuple(me.technology.values()),
            (
                ruler.title,
                ruler.name,
                ruler.administration,
                ruler.diplomacy,
                ruler.military,
                tuple(ruler.traits),
            )
            if ruler
            else None,
            tuple((r, a.name, a.skill) for r, a in sorted(me.advisors.items())),
            holdings(state, nation),  # type: ignore[arg-type]
            round(me.war_exhaustion, 1),
            me.prestige,
            tuple(me.missions_done),
        )
    cached = _CACHE.get(key)
    if cached is not None and cached[0] is state.rules:
        return cached[1]
    if len(_CACHE) > 4096:
        _CACHE.clear()
    result = _modifiers(state, nation)
    _CACHE[key] = (state.rules, result)
    return result


def _modifiers(state: GameState, nation: NationId | None) -> Modifiers:
    rules = state.rules
    if nation is None:
        return Modifiers(
            treaty_break_penalty=rules.treaty_break_stability_penalty,
            max_development=rules.max_development,
            fort_bonus_per_level=rules.fort_bonus_per_level,
            max_generals=rules.max_generals,
            marketplace_share=rules.building_output_bonus,
            mill_share=rules.building_output_bonus,
        )
    me = state.nations[nation]
    tech = me.technology
    lines: list[str] = []
    ducats = rules.economy_tech_bonus * tech[TechBranch.ECONOMY]
    grain = rules.economy_tech_bonus * tech[TechBranch.ECONOMY]
    power = rules.military_tech_bonus * tech[TechBranch.MILITARY]
    research = 0.0
    stability = 0.0
    trait_research = 0.0
    trait_forts = 0.0
    penalty = rules.treaty_break_stability_penalty
    if tech[TechBranch.ECONOMY]:
        lines.append(f"economy technology: +{ducats:.0%} ducats and grain")
    if tech[TechBranch.MILITARY]:
        lines.append(f"military technology: +{power:.0%} battle power")
    building = min(0.8, rules.engineering_tech_discount * tech[TechBranch.ENGINEERING])
    if building:
        lines.append(f"engineering technology: buildings and development {building:.0%} cheaper")

    ruler = me.ruler
    if ruler is not None:
        ducats += rules.ruler_income_bonus * ruler.administration
        power += rules.ruler_battle_bonus * ruler.military
        stability = min(0.8, rules.ruler_stability_discount * ruler.diplomacy)
        lines.append(
            f"{ruler.title} {ruler.name}: +{rules.ruler_income_bonus * ruler.administration:.0%} "
            f"ducats, +{rules.ruler_battle_bonus * ruler.military:.0%} battle power, "
            f"stability {stability:.0%} cheaper"
        )
        if ruler.diplomacy >= 5:
            penalty -= 1
            lines.append(f"{ruler.title} {ruler.name}'s diplomacy: betrayal costs 1 less stability")
        if Trait.CUNNING in ruler.traits:
            penalty -= 1
            lines.append(f"{ruler.name} is cunning: betrayal costs 1 less stability")
        for trait in ruler.traits:
            if trait not in TRAIT_EFFECTS:
                continue
            field, amount, words = TRAIT_EFFECTS[trait]
            match field:
                case "battle_power":
                    power += amount
                case "ducat_income":
                    ducats += amount
                case "stability_discount":
                    stability = min(0.8, stability + amount)
                case "building_discount":
                    building = min(0.8, building + amount)
                case "research_discount":
                    trait_research += amount
                case "fort_bonus_per_level":
                    trait_forts += amount
            lines.append(f"{ruler.name} is {trait.value}: {words}")

    for role, advisor in sorted(me.advisors.items()):
        if role == AdvisorRole.TREASURER:
            bonus = rules.treasurer_income_bonus * advisor.skill
            ducats += bonus
            lines.append(f"treasurer {advisor.name}: +{bonus:.0%} ducats")
        elif role == AdvisorRole.CHANCELLOR:
            research = rules.chancellor_research_discount * advisor.skill
            lines.append(f"chancellor {advisor.name}: research {research:.0%} cheaper")
        elif role == AdvisorRole.MARSHAL:
            bonus = rules.marshal_battle_bonus * advisor.skill
            power += bonus
            lines.append(f"marshal {advisor.name}: +{bonus:.0%} battle power")

    research += trait_research
    if me.prestige:
        ducats += rules.prestige_income_bonus * me.prestige
        stability = min(0.8, stability + rules.prestige_stability_discount * me.prestige)
        lines.append(
            f"prestige {me.prestige}: +{rules.prestige_income_bonus * me.prestige:.0%} ducats, "
            f"stability {rules.prestige_stability_discount * me.prestige:.0%} cheaper"
        )
    if me.war_exhaustion:
        weary = rules.exhaustion_income_penalty * me.war_exhaustion
        ducats -= weary
        lines.append(f"war exhaustion {me.war_exhaustion:.1f}: -{weary:.0%} ducats")
    works, monuments = holdings(state, nation)
    fort_extra = trait_forts
    extra_generals = 0
    if BuildingKind.ROYAL_EXCHANGE in works:
        ducats += rules.royal_exchange_income_bonus
        lines.append(f"royal exchange: +{rules.royal_exchange_income_bonus:.0%} ducats")
    if BuildingKind.OBSERVATORY in works:
        research += rules.observatory_research_discount
        lines.append(f"observatory: research {rules.observatory_research_discount:.0%} cheaper")
    if BuildingKind.MILITARY_ACADEMY in works:
        extra_generals += 1
        lines.append("military academy: one more general")
    arms = BuildingKind.ARMS_MANUFACTORY in works
    if arms:
        lines.append("arms manufactory: levies need half the iron and no goods")
    powder = BuildingKind.POWDER_MILL in works
    if powder:
        power += 0.05
        lines.append("powder mill: +5% battle power, assaults knock one more fort level off")
    bonuses = [
        (spec.bonus, spec.per_level * level, f"{spec.name} (level {level}): {spec.effect} a level")
        for pid, level in monuments
        for spec in [rules.monuments[pid]]
    ] + [
        (m.bonus or "", m.bonus_amount, f"{m.title}: {m.bonus_text}")
        for m in lasting_bonuses(tuple(me.missions_done), nation)
    ]
    for kind, amount, line in bonuses:
        match kind:
            case "ducat_income":
                ducats += amount
            case "grain_income":
                grain += amount
            case "battle_power":
                power += amount
            case "research_discount":
                research += amount
            case "building_discount":
                building = min(0.8, building + amount)
            case "stability_discount":
                stability = min(0.8, stability + amount)
            case "fort_bonus_per_level":
                fort_extra += amount
        lines.append(line)

    milestones = {
        name: _has(state, nation, milestone)
        for name, milestone in (
            ("artillery", FIELD_ARTILLERY),
            ("revolution", MILITARY_REVOLUTION),
            ("mercantilism", MERCANTILISM),
            ("cameralism", CAMERALISM),
            ("mills", WATER_MILLS),
            ("canals", ROADS_AND_CANALS),
            ("star", STAR_FORTS),
            ("grand", GRAND_ARCHITECTURE),
        )
    }
    for branch, levels in rules.tech_tree.items():
        for level, step in enumerate(levels[: tech[branch]], start=1):
            lines.append(f"{step.name} ({branch.value} {level}): {step.unlocks}")
    return Modifiers(
        ducat_income=ducats,
        grain_income=grain,
        battle_power=power,
        research_discount=min(0.8, research),
        building_discount=building,
        stability_discount=stability,
        treaty_break_penalty=max(0, penalty),
        extra_building_slots=1 if milestones["cameralism"] else 0,
        max_development=rules.max_development + (3 if milestones["grand"] else 0),
        grain_upkeep_factor=0.8 if milestones["canals"] else 1.0,
        fort_bonus_per_level=(0.35 if milestones["star"] else rules.fort_bonus_per_level)
        + fort_extra,
        ignores_fort_levels=(1 if milestones["artillery"] else 0) + (1 if powder else 0),
        arms_manufactory=arms,
        max_generals=rules.max_generals + (1 if milestones["revolution"] else 0) + extra_generals,
        marketplace_share=rules.building_output_bonus + (0.5 if milestones["mercantilism"] else 0),
        mill_share=rules.building_output_bonus + (0.5 if milestones["mills"] else 0),
        sources=tuple(lines),
    )


# ---------------------------------------------------------------- rulers

# Who would sit on each throne, in order, as the historical line ran from 1500.
RULERS: dict[str, list[tuple[str, str, str]]] = {
    "england": [
        (
            "King",
            "Henry VII",
            (
                "The first Tudor, who won his crown on Bosworth Field in 1485"
                " and fills his treasury by thrift and fines."
            ),
        ),
        (
            "King",
            "Henry VIII",
            (
                "Scholar, jouster and builder of warships, who will break "
                "with Rome to remarry and dissolve the monasteries."
            ),
        ),
        (
            "King",
            "Edward VI",
            (
                "Henry's only son, crowned at nine, a fervent Protestant "
                "ruling through his uncles' council."
            ),
        ),
        (
            "Queen",
            "Mary I",
            (
                "Catherine of Aragon's daughter, who restores the old faith "
                "and marries Philip of Spain."
            ),
        ),
        (
            "Queen",
            "Elizabeth I",
            (
                "The Virgin Queen, careful with money and bold at sea; under "
                "her the Armada is beaten in 1588."
            ),
        ),
        (
            "King",
            "James I",
            (
                "Already King of Scots, the first to rule both kingdoms, and "
                "author of books on kingship and witchcraft."
            ),
        ),
    ],
    "france": [
        (
            "King",
            "Louis XII",
            "The 'Father of the People', who claims Milan and Naples by blood and keeps taxes low.",
        ),
        (
            "King",
            "Francis I",
            (
                "The Renaissance king of Marignano and Chambord, patron of "
                "Leonardo and rival of Charles V."
            ),
        ),
        (
            "King",
            "Henry II",
            (
                "Francis's son, who takes Calais from the English in 1558 and"
                " dies of a wound taken in a tournament."
            ),
        ),
        (
            "King",
            "Francis II",
            "A sickly king of fifteen, husband of Mary, Queen of Scots; he reigns barely a year.",
        ),
        (
            "King",
            "Charles IX",
            (
                "Crowned at ten under his mother Catherine de' Medici, in the"
                " years of the Wars of Religion."
            ),
        ),
        (
            "King",
            "Henry III",
            (
                "The last Valois, elected King of Poland before inheriting "
                "France, struck down by a monk in 1589."
            ),
        ),
    ],
    "spain": [
        (
            "King",
            "Ferdinand II",
            (
                "Ferdinand of Aragon, who took Granada with Isabella in 1492 "
                "and sent Columbus west; Machiavelli's model prince."
            ),
        ),
        (
            "Queen",
            "Joanna",
            (
                "Joanna of Castile, called 'the Mad', heiress of half the "
                "world, kept from power by her father and her son."
            ),
        ),
        (
            "King",
            "Charles I",
            (
                "Charles of Ghent, King of Spain and, as Charles V, Holy "
                "Roman Emperor: the sun never sets on his lands."
            ),
        ),
        (
            "King",
            "Philip II",
            (
                "The prudent king of the Escorial, master of American silver,"
                " of Portugal and of the Armada."
            ),
        ),
        (
            "King",
            "Philip III",
            (
                "A pious king who leaves the realm to his favourite, the Duke"
                " of Lerma, and expels the Moriscos."
            ),
        ),
        (
            "King",
            "Philip IV",
            "The 'Planet King', patron of Velázquez, in whose reign Spain's long decline begins.",
        ),
    ],
    "austria": [
        (
            "Emperor",
            "Maximilian I",
            (
                "'The last knight', who married his house to Burgundy, Spain "
                "and Hungary: let others wage war, happy Austria, marry."
            ),
        ),
        (
            "Emperor",
            "Charles V",
            (
                "Heir of Habsburg, Burgundy and Spain, who faces Luther at "
                "Worms and the Turk at Vienna."
            ),
        ),
        (
            "Emperor",
            "Ferdinand I",
            (
                "Charles's brother, King of Bohemia and Hungary, who holds "
                "Vienna against Suleiman in 1529."
            ),
        ),
        (
            "Emperor",
            "Maximilian II",
            "A tolerant emperor who keeps the peace between Catholic and Protestant.",
        ),
        (
            "Emperor",
            "Rudolf II",
            (
                "The melancholy emperor of Prague, collector of wonders and "
                "patron of Kepler and Tycho Brahe."
            ),
        ),
        (
            "Emperor",
            "Matthias",
            "Rudolf's brother, who pushes him from power and sees the Thirty Years' War draw near.",
        ),
    ],
    "ottomans": [
        (
            "Sultan",
            "Bayezid II",
            (
                "The pious son of the Conqueror, who welcomes the Jews "
                "expelled from Spain and builds across the empire."
            ),
        ),
        (
            "Sultan",
            "Selim I",
            "'The Grim', who in eight years conquers Syria, Egypt and the holy cities of Arabia.",
        ),
        (
            "Sultan",
            "Suleiman I",
            "The Magnificent, the Lawgiver: Belgrade, Rhodes, Mohács and the siege of Vienna.",
        ),
        (
            "Sultan",
            "Selim II",
            "Suleiman's son, whose fleet is broken at Lepanto in 1571 and rebuilt within a year.",
        ),
        (
            "Sultan",
            "Murad III",
            "A sultan of the palace rather than the field, under whom the harem gains great power.",
        ),
        (
            "Sultan",
            "Mehmed III",
            "Victor at Keresztes in 1596, the last sultan to have governed a province as a prince.",
        ),
    ],
    "sweden": [
        (
            "Regent",
            "Sten Sture",
            "Sten Sture the Elder, Regent of Sweden, who beat the Danes at Brunkeberg in 1471.",
        ),
        (
            "Regent",
            "Svante Nilsson",
            "A regent fighting to keep Sweden out of the Danish grip of the Kalmar Union.",
        ),
        (
            "King",
            "Gustav I",
            (
                "Gustav Vasa, who breaks the Kalmar Union in 1523, founds a "
                "dynasty and takes the Church's lands."
            ),
        ),
        (
            "King",
            "Eric XIV",
            "Learned and suspicious, suitor of Elizabeth of England, deposed by his own brother.",
        ),
        (
            "King",
            "John III",
            "Eric's brother and jailer, a lover of architecture who leans towards the old faith.",
        ),
        (
            "King",
            "Sigismund",
            "King of Poland and of Sweden at once, a Catholic his Lutheran subjects will not keep.",
        ),
    ],
    "russia": [
        (
            "Grand Prince",
            "Ivan III",
            (
                "Ivan the Great, who threw off the Tatar yoke in 1480 and "
                "took Novgorod; Moscow calls itself the Third Rome."
            ),
        ),
        (
            "Grand Prince",
            "Vasili III",
            "Ivan's son, who gathers Pskov, Smolensk and Ryazan into the Muscovite state.",
        ),
        (
            "Tsar",
            "Ivan IV",
            (
                "Ivan the Terrible, the first crowned Tsar, conqueror of "
                "Kazan, and of his own nobles by terror."
            ),
        ),
        (
            "Tsar",
            "Feodor I",
            "A gentle, devout tsar, ruled in fact by his brother-in-law Boris Godunov.",
        ),
        (
            "Tsar",
            "Boris Godunov",
            (
                "The regent who becomes Tsar in 1598, clever and suspected; "
                "his death opens the Time of Troubles."
            ),
        ),
        (
            "Tsar",
            "Michael I",
            "The first Romanov, elected Tsar by the land in 1613 after the Time of Troubles.",
        ),
    ],
    "poland": [
        (
            "King",
            "John I Albert",
            "John Olbracht, scholar-king, who leads a disastrous crusade into Moldavia in 1497.",
        ),
        (
            "King",
            "Alexander",
            "Grand Duke of Lithuania, then king: under him the Sejm wins the Nihil Novi in 1505.",
        ),
        (
            "King",
            "Sigismund I",
            (
                "Sigismund the Old, who brings the Italian Renaissance to "
                "Wawel and takes Prussia's homage."
            ),
        ),
        (
            "King",
            "Sigismund II",
            (
                "Sigismund Augustus, the last Jagiellon, who binds Poland and"
                " Lithuania at Lublin in 1569."
            ),
        ),
        (
            "King",
            "Stephen Báthory",
            "A Transylvanian prince elected king, who beats Ivan the Terrible in the Livonian War.",
        ),
        (
            "King",
            "Sigismund III",
            "A Vasa elected king, Catholic heir to Sweden too, who moves the capital to Warsaw.",
        ),
    ],
    "hungary": [
        (
            "King",
            "Vladislaus II",
            (
                "'King Dobže', who says yes to everything: the barons rule "
                "while he reigns in Buda and Prague."
            ),
        ),
        ("King", "Louis II", "A boy-king who falls at Mohács in 1526, and Hungary with him."),
        (
            "King",
            "John Zápolya",
            "The great magnate crowned king against the Habsburgs, with the Sultan's leave.",
        ),
        (
            "King",
            "John Sigismund",
            "Zápolya's son, the first Prince of Transylvania and its tolerant founder.",
        ),
        ("Prince", "Stephen Báthory", "Prince of Transylvania, soon to be elected King of Poland."),
        (
            "Prince",
            "Sigismund Báthory",
            "A restless prince who changes sides in the Long Turkish War.",
        ),
    ],
}


W, CA, TH, PI, SC, BU, CU, CH, CR, AM, ME = (
    Trait.WARLIKE, Trait.CAUTIOUS, Trait.THRIFTY, Trait.PIOUS, Trait.SCHOLAR, Trait.BUILDER,
    Trait.CUNNING, Trait.CHARMING, Trait.CRUEL, Trait.AMBITIOUS, Trait.MELANCHOLIC,
)  # fmt: skip
# The character history gave each of them.
HISTORICAL_TRAITS: dict[str, list[Trait]] = {
    "Henry VII": [TH, CA], "Henry VIII": [AM, CH], "Edward VI": [PI, SC], "Mary I": [PI, CR],
    "Elizabeth I": [CH, CA], "James I": [SC, CA],
    "Louis XII": [TH, CH], "Francis I": [AM, BU], "Henry II": [W, AM], "Francis II": [ME],
    "Charles IX": [CR, ME], "Henry III": [SC, PI],
    "Ferdinand II": [AM, CU], "Joanna": [ME], "Charles I": [AM, PI], "Philip II": [PI, CA],
    "Philip III": [PI], "Philip IV": [BU, ME],
    "Maximilian I": [CH, AM], "Charles V": [AM, PI], "Ferdinand I": [CA, PI],
    "Maximilian II": [CH, SC], "Rudolf II": [SC, ME], "Matthias": [AM],
    "Bayezid II": [PI, BU], "Selim I": [W, CR], "Suleiman I": [W, BU], "Selim II": [ME],
    "Murad III": [ME, PI], "Mehmed III": [W, CR],
    "Sten Sture": [W, CA], "Svante Nilsson": [W], "Gustav I": [TH, AM], "Eric XIV": [SC, ME],
    "John III": [BU, PI], "Sigismund": [PI],
    "Ivan III": [AM, CU], "Vasili III": [AM, CA], "Ivan IV": [CR, W], "Feodor I": [PI, ME],
    "Boris Godunov": [CU, BU], "Michael I": [CA],
    "John I Albert": [SC, AM], "Alexander": [CA], "Sigismund I": [BU, CA], "Sigismund II": [CH, SC],
    "Stephen Báthory": [W, CU], "Sigismund III": [PI, AM],
    "Vladislaus II": [ME, PI], "Louis II": [W], "John Zápolya": [AM, CU], "John Sigismund": [SC],
    "Sigismund Báthory": [AM, ME],
}  # fmt: skip

# What a trait does to the numbers: (Modifiers field, amount, in words).
TRAIT_EFFECTS: dict[Trait, tuple[str, float, str]] = {
    Trait.WARLIKE: ("battle_power", 0.05, "+5% battle power"),
    Trait.CAUTIOUS: ("fort_bonus_per_level", 0.05, "forts 5% stronger"),
    Trait.THRIFTY: ("ducat_income", 0.05, "+5% ducats"),
    Trait.PIOUS: ("stability_discount", 0.1, "stability 10% cheaper"),
    Trait.SCHOLAR: ("research_discount", 0.1, "research 10% cheaper"),
    Trait.BUILDER: ("building_discount", 0.08, "buildings and development 8% cheaper"),
    Trait.CRUEL: ("battle_power", 0.03, "+3% battle power"),
}


def make_ruler(nation: NationId, reign: int, turn: int, rng: random.Random, *, age: int) -> Ruler:
    line = RULERS.get(nation, [])
    title, name, bio = (
        line[reign] if reign < len(line) else ("Ruler", f"the {reign + 1}th of the line", "")
    )

    def stat() -> int:
        return rng.choice([1, 2, 2, 3, 3, 3, 4, 4, 5, 6])

    traits = HISTORICAL_TRAITS.get(name)
    if traits is None:  # an heir history never knew: fortune deals the character
        traits = rng.sample(list(Trait), rng.choice([1, 2]))

    return Ruler(
        title=title,
        name=name,
        age=age,
        administration=stat(),
        diplomacy=stat(),
        military=stat(),
        since=turn,
        reign=reign,
        bio=bio,
        traits=list(traits),
    )


def death_chance(ruler: Ruler) -> float:
    """Rulers past forty grow mortal: about 1% more each year."""
    return max(0.0, (ruler.age - 40) * 0.012)


# ---------------------------------------------------------------- advisors

ADVISOR_NAMES: dict[str, list[str]] = {
    "england": [
        "Thomas Wolsey",
        "Thomas More",
        "Thomas Cromwell",
        "Richard Fox",
        "William Warham",
        "Edmund Dudley",
        "Reginald Bray",
        "Thomas Lovell",
    ],
    "france": [
        "Georges d'Amboise",
        "Florimond Robertet",
        "Antoine Duprat",
        "Jacques de Beaune",
        "Guillaume Budé",
        "Louise of Savoy",
        "Guillaume Briçonnet",
        "Jean de Selve",
    ],
    "spain": [
        "Francisco Jiménez de Cisneros",
        "Francisco de los Cobos",
        "Mercurino Gattinara",
        "Hernando de Talavera",
        "Antonio de Nebrija",
        "Juan de Zúñiga",
        "Pedro de Toledo",
        "Bartolomé de las Casas",
    ],
    "austria": [
        "Matthäus Lang",
        "Cyprian von Serntein",
        "Jakob Fugger",
        "Konrad Peutinger",
        "Gabriel von Salamanca",
        "Johannes Cuspinian",
        "Niklas Ziegler",
        "Paul von Liechtenstein",
    ],
    "ottomans": [
        "Hersekzade Ahmed Pasha",
        "Piri Mehmed Pasha",
        "Kemalpasazade",
        "Ebussuud Efendi",
        "Rustem Pasha",
        "Lutfi Pasha",
        "Celalzade Mustafa",
        "Matrakci Nasuh",
    ],
    "sweden": [
        "Hemming Gadh",
        "Laurentius Andreae",
        "Olaus Petri",
        "Laurentius Petri",
        "Ture Jönsson",
        "Peder Jakobsson",
        "Conrad von Pyhy",
        "Georg Norman",
    ],
    "russia": [
        "Fyodor Kuritsyn",
        "Ivan Patrikeyev",
        "Daniil Kholmsky",
        "Maksim the Greek",
        "Ivan Shigona",
        "Fyodor Karpov",
        "Vasily Tuchkov",
        "Mikhail Tuchkov",
    ],
    "poland": [
        "Jan Łaski",
        "Krzysztof Szydłowiecki",
        "Piotr Tomicki",
        "Jan Zamoyski",
        "Mikołaj Radziwiłł",
        "Andrzej Frycz Modrzewski",
        "Piotr Kmita",
        "Jan Dantyszek",
    ],
    "hungary": [
        "Tamás Bakócz",
        "István Werbőczy",
        "Pál Várdai",
        "George Martinuzzi",
        "Péter Perényi",
        "Imre Perényi",
        "Ferenc Batthyány",
        "János Corvinus",
    ],
}


def advisor_candidates(state: GameState, nation: NationId) -> list[Advisor]:
    """Who seeks a place at this court right now: two candidates for each seat. The list changes
    every few years and is the same for everyone who asks (seeded)."""
    period = (state.turn - 1) // state.rules.advisor_pool_years
    rng = random.Random(f"{state.seed}:{nation}:advisors:{period}")  # noqa: S311 (game dice)
    names = list(ADVISOR_NAMES.get(nation, []))
    rng.shuffle(names)
    nation_no = sorted(state.nations).index(nation)
    taken = {a.name for a in state.nations[nation].advisors.values()}
    pool: list[Advisor] = []
    for r, role in enumerate(AdvisorRole):
        for k in range(2):
            name = names.pop() if names else f"Councillor {r}{k}"
            if name in taken:
                name = names.pop() if names else f"Councillor {r}{k}b"
            pool.append(
                Advisor(
                    id=(period * 10 + nation_no) * 100 + r * 10 + k,
                    name=name,
                    role=role,
                    skill=rng.choice([1, 1, 2, 2, 3]),
                    personality=rng.choice(list(Personality)),
                )
            )
    return pool


def advisor_hire_cost(rules: Rules, advisor: Advisor) -> int:
    return rules.advisor_hire_ducats * advisor.skill


def advisor_salaries(rules: Rules, advisors: dict[AdvisorRole, Advisor]) -> int:
    return sum(rules.advisor_salary_ducats * a.skill for a in advisors.values())
