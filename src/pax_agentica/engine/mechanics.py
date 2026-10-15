"""Pure formulas: production, costs and combat. No state changes happen here."""

import math
import random
from collections.abc import Collection
from dataclasses import dataclass

from pax_agentica.engine.model import (
    BuildingKind,
    GameState,
    Good,
    NationId,
    ProvinceId,
    Resources,
    Rules,
    TechBranch,
)
from pax_agentica.engine.realm import advisor_salaries, modifiers

# Buildings that add a share of one of the province's outputs.
OUTPUT_BUILDINGS = {
    BuildingKind.MARKETPLACE: "ducats",
    BuildingKind.FARM_ESTATES: "grain",
    BuildingKind.IRONWORKS: "iron",
    BuildingKind.LUMBER_MILL: "timber",
    BuildingKind.BARRACKS: "manpower",
}

# ---------------------------------------------------------------- economy


def building_slots(rules: Rules, development: int, extra: int = 0) -> int:
    """More developed provinces have room for more buildings."""
    return 1 + development // rules.development_per_building_slot + extra


def land_yield(rules: Rules, good: Good, development: int) -> Resources:
    """What land of this development and good yields, before buildings."""
    extra = development * rules.good_yield_per_development
    return Resources(
        ducats=development + (extra if good is Good.GOLD else 0),
        manpower=max(1, development // 2),
        iron=rules.base_iron_per_province + (extra if good is Good.IRON else 0),
        grain=rules.base_grain_per_province + (extra if good is Good.GRAIN else 0),
        timber=rules.base_timber_per_province + (extra if good is Good.TIMBER else 0),
    )


def buildings_yield(
    rules: Rules,
    base: Resources,
    buildings: Collection[BuildingKind],
    marketplace_share: float | None = None,
    mill_share: float | None = None,
) -> Resources:
    """The extra yield of the buildings: mostly a share of the base yield, so the same building
    pays off more in a more developed province. Technology can raise some shares."""
    amounts = base.amounts()
    extra = dict.fromkeys(amounts, 0)
    shares = {
        BuildingKind.MARKETPLACE: marketplace_share,
        BuildingKind.FARM_ESTATES: mill_share,
        BuildingKind.LUMBER_MILL: mill_share,
    }
    for building in buildings:
        if field := OUTPUT_BUILDINGS.get(building):
            share = shares.get(building) or rules.building_output_bonus
            extra[field] += max(1, math.floor(amounts[field] * share))
        elif building == BuildingKind.BANK:
            extra["ducats"] += 3 + math.floor(amounts["ducats"] * 0.5)
        elif building == BuildingKind.CATHEDRAL:
            extra["manpower"] += 1
            extra["ducats"] += math.floor(amounts["ducats"] * 0.25)
    return Resources(**extra)


def base_output(state: GameState, province: ProvinceId) -> Resources:
    """The province's yield from its development and its good alone."""
    return land_yield(
        state.rules, state.map.provinces[province].good, state.provinces[province].development
    )


def building_output(state: GameState, province: ProvinceId) -> Resources:
    """The extra yield of the province's buildings, with its owner's technology."""
    mods = modifiers(state, state.provinces[province].owner)
    return buildings_yield(
        state.rules,
        base_output(state, province),
        state.provinces[province].buildings,
        mods.marketplace_share,
        mods.mill_share,
    )


def output_with(
    state: GameState,
    province: ProvinceId,
    *,
    development: int | None = None,
    extra: Collection[BuildingKind] = (),
) -> Resources:
    """What the province would yield at another development or with more buildings, unrest
    aside: the "what if" behind every preview of a work."""
    p = state.provinces[province]
    base = land_yield(state.rules, state.map.provinces[province].good, development or p.development)
    mods = modifiers(state, p.owner)
    return base + buildings_yield(
        state.rules, base, [*p.buildings, *extra], mods.marketplace_share, mods.mill_share
    )


def province_output(state: GameState, province: ProvinceId) -> Resources:
    """What one province yields per turn, before the stability modifier. Nothing in unrest."""
    if state.provinces[province].unrest:
        return Resources()
    return base_output(state, province) + building_output(state, province)


def nation_income(state: GameState, nation: NationId) -> Resources:
    """Total production per turn, with stability and the realm's modifiers (technology, ruler,
    treasurer) applied to ducats, and economy technology to grain."""
    rules = state.rules
    total = Resources()
    for province in state.provinces_of(nation):
        total = total + province_output(state, province)
    mods = modifiers(state, nation)
    stability = rules.stability_income_bonus * state.nations[nation].stability
    ducats = total.ducats * (1 + stability + mods.ducat_income)
    grain = total.grain * (1 + mods.grain_income)
    return total.model_copy(
        update={"ducats": max(0, math.floor(ducats)), "grain": math.floor(grain)}
    )


def discounted(cost: Resources, discount: float) -> Resources:
    """Engineering makes ducats and timber go further; iron and men cost what they cost."""
    if not discount:
        return cost
    return cost.model_copy(
        update={
            "ducats": math.ceil(cost.ducats * (1 - discount)),
            "timber": math.ceil(cost.timber * (1 - discount)),
        }
    )


def building_cost(rules: Rules, kind: BuildingKind, discount: float = 0.0) -> Resources:
    return discounted(rules.buildings[kind].cost, discount)


def research_cost(
    rules: Rules, branch: TechBranch, level: int, discount: float = 0.0
) -> Resources | None:
    """The cost of reaching `level + 1`, or None at the top: the branch's base cost, half a step
    dearer per level (1, 1.5, 2... times). A chancellor makes it cheaper."""
    if level >= rules.max_tech_level:
        return None
    scale = (1 + rules.research_cost_growth * level) * (1 - discount)
    return Resources(
        **{k: math.ceil(v * scale) for k, v in rules.tech_costs[branch].amounts().items()}
    )


def battle_factor(state: GameState, nation: NationId | None, general_skill: int = 0) -> float:
    """How much harder an army fights thanks to its nation's military technology and its
    general. Independent levies have neither."""
    mods = modifiers(state, nation)
    return (1 + mods.battle_power) * (1 + state.rules.general_bonus_per_skill * general_skill)


def army_upkeep(rules: Rules, regiments: int, grain_factor: float = 1.0) -> Resources:
    """What an army eats and is paid each year."""
    return Resources(
        grain=math.ceil(regiments * rules.grain_upkeep_per_regiment * grain_factor),
        ducats=math.ceil(regiments * rules.ducat_upkeep_per_regiment),
    )


def nation_upkeep(state: GameState, nation: NationId) -> Resources:
    """The army's food and pay, plus the advisors' salaries."""
    mods = modifiers(state, nation)
    army = army_upkeep(state.rules, state.troops_of(nation), mods.grain_upkeep_factor)
    salaries = advisor_salaries(state.rules, state.nations[nation].advisors)
    return army + Resources(ducats=salaries)


def grain_upkeep(state: GameState, nation: NationId) -> int:
    return nation_upkeep(state, nation).grain


def manpower_cap(state: GameState, nation: NationId) -> int:
    """Men of fighting age are finite: the pool fills up to a few years of recruits."""
    rules = state.rules
    yearly = sum(
        base_output(state, p).manpower + building_output(state, p).manpower
        for p in state.provinces_of(nation)
    )
    return rules.manpower_cap_base + rules.manpower_cap_years * yearly


def develop_cost(
    rules: Rules,
    development: int,
    buildings: Collection[BuildingKind] = (),
    discount: float = 0.0,
) -> Resources:
    ducats = rules.develop_base_ducats + rules.develop_ducats_per_level * development
    if BuildingKind.UNIVERSITY in buildings:
        ducats = math.ceil(ducats * (1 - rules.university_develop_discount))
    timber = rules.develop_timber_base + rules.develop_timber_per_two_levels * (development // 2)
    return discounted(Resources(ducats=ducats, timber=timber), discount)


def recruit_cost(
    rules: Rules, regiments: int, buildings: Collection[BuildingKind] = ()
) -> Resources:
    cost = rules.recruit_cost.times(regiments)
    if BuildingKind.ARMORY in buildings:
        iron = math.ceil(cost.iron * (1 - rules.armory_iron_discount))
        cost = cost.model_copy(update={"iron": iron})
    return cost


def stability_cost(rules: Rules, discount: float = 0.0) -> Resources:
    return Resources(ducats=math.ceil(rules.stability_boost_ducats * (1 - discount)))


# ---------------------------------------------------------------- combat


def defense_multiplier(state: GameState, origin: ProvinceId, target: ProvinceId) -> float:
    """How much harder the defenders of `target` fight against an attack from `origin`."""
    rules = state.rules
    target_state = state.provinces[target]
    terrain = rules.terrain_defense[state.map.provinces[target].terrain]
    owner = target_state.owner
    attacker = modifiers(state, state.provinces[origin].owner)
    forts = max(0, target_state.fort - attacker.ignores_fort_levels)
    bonus = modifiers(state, owner).fort_bonus_per_level * forts
    if BuildingKind.TRAINING_GROUNDS in target_state.buildings:
        bonus += 0.2
    if owner is not None and state.nations[owner].capital == target:
        bonus += rules.capital_bonus
    if state.map.is_sea_crossing(origin, target):
        bonus += rules.sea_crossing_bonus
    return rules.defender_advantage * terrain * (1 + bonus)


@dataclass(frozen=True)
class BattleResult:
    attacker_won: bool
    attacker_power: float
    defender_power: float
    attacker_losses: int
    defender_losses: int


def fight(
    rules: Rules,
    attackers: int,
    defenders: int,
    multiplier: float,
    rng: random.Random,
    attack_factor: float = 1.0,
    defence_factor: float = 1.0,
) -> BattleResult:
    """Resolve one battle. The loser's committed regiments are destroyed; the winner loses a share
    proportional to how close the fight was, but always keeps at least one regiment.

    `multiplier` is the ground (terrain, forts, capital, strait); the factors are technology and
    generals on each side."""
    att = attackers * attack_factor * rng.uniform(rules.roll_min, rules.roll_max)
    dfn = defenders * multiplier * defence_factor * rng.uniform(rules.roll_min, rules.roll_max)
    if att > dfn:
        losses = min(attackers - 1, math.ceil(attackers * rules.winner_loss_factor * dfn / att))
        return BattleResult(True, att, dfn, losses, defenders)
    losses = min(defenders - 1, math.ceil(defenders * rules.winner_loss_factor * att / dfn))
    return BattleResult(False, att, dfn, attackers, losses)
