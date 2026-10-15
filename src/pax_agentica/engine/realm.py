"""The court: what a nation's ruler, advisors and technology add up to.

`modifiers` gathers every bonus a nation enjoys into one object, with a line of text per source,
so the engine, the view and a curious ruler (human or LLM) all read the same numbers.
"""

import random

from pydantic import BaseModel, ConfigDict

from pax_agentica.engine.model import (
    Advisor,
    AdvisorRole,
    GameState,
    NationId,
    Ruler,
    Rules,
    TechBranch,
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
    sources: tuple[str, ...] = ()  # one line per bonus, for humans and prompts


def _has(state: GameState, nation: NationId, milestone: tuple[TechBranch, int]) -> bool:
    branch, level = milestone
    return state.nations[nation].technology[branch] >= level


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
            (ruler.title, ruler.name, ruler.administration, ruler.diplomacy, ruler.military)
            if ruler
            else None,
            tuple((r, a.name, a.skill) for r, a in sorted(me.advisors.items())),
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
        fort_bonus_per_level=0.35 if milestones["star"] else rules.fort_bonus_per_level,
        ignores_fort_levels=1 if milestones["artillery"] else 0,
        max_generals=rules.max_generals + (1 if milestones["revolution"] else 0),
        marketplace_share=rules.building_output_bonus + (0.5 if milestones["mercantilism"] else 0),
        mill_share=rules.building_output_bonus + (0.5 if milestones["mills"] else 0),
        sources=tuple(lines),
    )


# ---------------------------------------------------------------- rulers

# Who would sit on each throne, in order, as the historical line ran from 1500.
RULERS: dict[str, list[tuple[str, str]]] = {
    "england": [
        ("King", "Henry VII"),
        ("King", "Henry VIII"),
        ("King", "Edward VI"),
        ("Queen", "Mary I"),
        ("Queen", "Elizabeth I"),
        ("King", "James I"),
    ],
    "france": [
        ("King", "Louis XII"),
        ("King", "Francis I"),
        ("King", "Henry II"),
        ("King", "Francis II"),
        ("King", "Charles IX"),
        ("King", "Henry III"),
    ],
    "spain": [
        ("King", "Ferdinand II"),
        ("Queen", "Joanna"),
        ("King", "Charles I"),
        ("King", "Philip II"),
        ("King", "Philip III"),
        ("King", "Philip IV"),
    ],
    "austria": [
        ("Emperor", "Maximilian I"),
        ("Emperor", "Charles V"),
        ("Emperor", "Ferdinand I"),
        ("Emperor", "Maximilian II"),
        ("Emperor", "Rudolf II"),
        ("Emperor", "Matthias"),
    ],
    "ottomans": [
        ("Sultan", "Bayezid II"),
        ("Sultan", "Selim I"),
        ("Sultan", "Suleiman I"),
        ("Sultan", "Selim II"),
        ("Sultan", "Murad III"),
        ("Sultan", "Mehmed III"),
    ],
    "sweden": [
        ("Regent", "Sten Sture"),
        ("Regent", "Svante Nilsson"),
        ("King", "Gustav I"),
        ("King", "Eric XIV"),
        ("King", "John III"),
        ("King", "Sigismund"),
    ],
    "russia": [
        ("Grand Prince", "Ivan III"),
        ("Grand Prince", "Vasili III"),
        ("Tsar", "Ivan IV"),
        ("Tsar", "Feodor I"),
        ("Tsar", "Boris Godunov"),
        ("Tsar", "Michael I"),
    ],
}


def make_ruler(nation: NationId, reign: int, turn: int, rng: random.Random, *, age: int) -> Ruler:
    line = RULERS.get(nation, [])
    title, name = line[reign] if reign < len(line) else ("Ruler", f"the {reign + 1}th of the line")

    def stat() -> int:
        return rng.choice([1, 2, 2, 3, 3, 3, 4, 4, 5, 6])

    return Ruler(
        title=title,
        name=name,
        age=age,
        administration=stat(),
        diplomacy=stat(),
        military=stat(),
        since=turn,
        reign=reign,
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
                )
            )
    return pool


def advisor_hire_cost(rules: Rules, advisor: Advisor) -> int:
    return rules.advisor_hire_ducats * advisor.skill


def advisor_salaries(rules: Rules, advisors: dict[AdvisorRole, Advisor]) -> int:
    return sum(rules.advisor_salary_ducats * a.skill for a in advisors.values())
