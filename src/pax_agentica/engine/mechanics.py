"""Pure formulas: production, costs and combat. No state changes happen here."""

import math
import random
from collections.abc import Collection, Mapping
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
    Terrain,
    UnitKind,
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


def land_yield(
    rules: Rules, good: Good, development: int, terrain: Terrain | None = None
) -> Resources:
    """What land of this development, good and terrain yields, before buildings."""
    ground = rules.terrain_yield.get(terrain, {}) if terrain else {}
    base = {
        "ducats": development,
        "manpower": max(1, development // 2),
        "iron": rules.base_iron_per_province,
        "grain": rules.base_grain_per_province,
        "timber": rules.base_timber_per_province,
        "goods": 0,
    }
    for k, v in good_yield(rules, good, development).amounts().items():
        base[k] += v
    return Resources(**{k: max(0, v + ground.get(k, 0)) for k, v in base.items()})


def good_yield(rules: Rules, good: Good, development: int, share: float = 1.0) -> Resources:
    """What a province's good adds at this development (a share of it, for its workings)."""
    rates = rules.good_yields.get(good, {})
    return Resources(**{k: math.floor(development * rate * share) for k, rate in rates.items()})


def buildings_yield(
    rules: Rules,
    base: Resources,
    buildings: Collection[BuildingKind],
    marketplace_share: float | None = None,
    mill_share: float | None = None,
    development: int = 0,
    good: Good | None = None,
) -> Resources:
    """The extra yield of the buildings: mostly a share of the base yield, so the same building
    pays off more in a more developed province. Technology can raise some shares. Marketplaces,
    banks and cathedrals tax the town, not the mines: the ducats of the province's trade good
    are left out of their share (workings deepen those instead)."""
    amounts = base.amounts()
    if good is not None:
        amounts["ducats"] -= good_yield(rules, good, development).ducats
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
        elif building == BuildingKind.WORKSHOP:
            extra["goods"] += rules.workshop_base_goods + (
                development // rules.workshop_goods_per_development
            )
    return Resources(**extra)


def base_output(state: GameState, province: ProvinceId) -> Resources:
    """The province's yield from its development and its good alone."""
    definition = state.map.provinces[province]
    return land_yield(
        state.rules, definition.good, state.provinces[province].development, definition.terrain
    )


def building_output(state: GameState, province: ProvinceId) -> Resources:
    """The extra yield of the province's buildings, with its owner's technology."""
    p = state.provinces[province]
    mods = modifiers(state, p.owner)
    built = buildings_yield(
        state.rules,
        base_output(state, province),
        [b for b in p.buildings if b not in p.idle],  # an idle building yields nothing
        mods.marketplace_share,
        mods.mill_share,
        p.development,
        state.map.provinces[province].good,
    )
    return built + workings_yield(state, province)


def workings_yield(
    state: GameState,
    province: ProvinceId,
    level: int | None = None,
    development: int | None = None,
) -> Resources:
    """What a province's workings (mine, vineyard, fishery...) add at their level."""
    p = state.provinces[province]
    level = p.workings if level is None else level
    if not level:
        return Resources()
    good = state.map.provinces[province].good
    return good_yield(
        state.rules, good, development or p.development, state.rules.workings_bonus * level
    )


def output_with(
    state: GameState,
    province: ProvinceId,
    *,
    development: int | None = None,
    extra: Collection[BuildingKind] = (),
    without: Collection[BuildingKind] = (),
    workings: int | None = None,
) -> Resources:
    """What the province would yield at another development, with more buildings or deeper
    workings, unrest aside: the "what if" behind every preview of a work."""
    p = state.provinces[province]
    definition = state.map.provinces[province]
    base = land_yield(
        state.rules, definition.good, development or p.development, definition.terrain
    )
    mods = modifiers(state, p.owner)
    standing = [b for b in p.buildings if b not in without]
    return _keep(
        base
        + buildings_yield(
            state.rules,
            base,
            [*standing, *extra],
            mods.marketplace_share,
            mods.mill_share,
            development or p.development,
            definition.good,
        )
        + workings_yield(state, province, workings, development),
        faith_penalty(state, province),
    )


def faith_penalty(state: GameState, province: ProvinceId) -> float:
    """The share of its yield a province loses because its people keep another faith than their
    ruler's (less for a tolerant realm)."""
    p = state.provinces[province]
    if p.owner is None or p.faith is None or p.faith == state.nations[p.owner].faith:
        return 0.0
    return state.rules.faith_mismatch_output * (1 - modifiers(state, p.owner).faith_tolerance)


def _keep(out: Resources, penalty: float) -> Resources:
    if not penalty:
        return out
    return Resources(**{k: math.floor(v * (1 - penalty)) for k, v in out.amounts().items()})


def convert_cost(rules: Rules, development: int) -> Resources:
    return rules.convert_cost + Resources(ducats=rules.convert_cost_per_development * development)


def province_output(state: GameState, province: ProvinceId) -> Resources:
    """What one province yields per turn, before the stability modifier. Nothing in unrest,
    nothing while an enemy occupies it, and less while its people keep another faith."""
    p = state.provinces[province]
    if p.unrest or p.controller:
        return Resources()
    out = base_output(state, province) + building_output(state, province)
    return _keep(out, faith_penalty(state, province))


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
    men = total.manpower * (1 - rules.tax_manpower_step * state.nations[nation].tax)
    return total.model_copy(
        update={
            "ducats": max(0, math.floor(ducats)),
            "grain": math.floor(grain),
            "manpower": max(0, math.floor(men)),
        }
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


def unit_cost(rules: Rules, kind: UnitKind) -> Resources:
    return rules.units[kind].cost or rules.recruit_cost


def army_strength(
    rules: Rules, army: Mapping[UnitKind, int], terrain: Terrain, *, attacking: bool
) -> float:
    """What a mix of regiments is worth in battle on this ground, combined arms included. A
    pikeman on plains is worth 1."""
    total = sum(army.values())
    if total == 0:
        return 0.0
    power = 0.0
    for kind, n in army.items():
        spec = rules.units[kind]
        power += n * (spec.attack if attacking else spec.defence) * spec.terrain.get(terrain, 1.0)
    kinds = sum(1 for n in army.values() if n and n / total >= rules.combined_arms_share)
    bonus = max((b for k, b in rules.combined_arms_bonus.items() if kinds >= k), default=0.0)
    return power * (1 + bonus)


def siege_levels(rules: Rules, army: Mapping[UnitKind, int]) -> int:
    """How many fort levels an attacking army's guns knock off."""
    total = sum(army.values())
    if not total:
        return 0
    share = army.get(UnitKind.ARTILLERY, 0) / total
    return math.floor(share / rules.artillery_share_per_fort_level + 1e-9)


def siege_walls(
    state: GameState, nation: NationId, province: ProvinceId, army: Mapping[UnitKind, int]
) -> int:
    """Fort levels still standing against this army: what its guns and its nation's
    technology do not knock off."""
    ignored = modifiers(state, nation).ignores_fort_levels
    return max(0, state.provinces[province].fort - ignored - siege_levels(state.rules, army))


def siege_modifiers(state: GameState, province: ProvinceId) -> list[tuple[str, int]]:
    """What is added to the besiegers' die this year, line by line."""
    rules = state.rules
    p = state.provinces[province]
    if p.siege_by is None:
        return []
    army = p.siege_army()
    walls = siege_walls(state, p.siege_by, province, army)
    out = [("walls", -walls)]
    if army[UnitKind.ARTILLERY]:
        out.append(("cannon", 1))
    if p.siege_years:
        out.append(("the garrison starves", p.siege_years))
    if sum(army.values()) < rules.siege_ring_per_wall * walls:
        out.append(("too few to close the ring", -2))
    if p.owner is not None:
        if modifiers(state, p.owner).fort_bonus_per_level >= rules.fort_bonus_per_level + 0.1:
            out.append(("star forts", -1))
        if state.nations[p.owner].capital == province:
            out.append(("a capital's defenders", -1))
    return [(label, value) for label, value in out if value]


def siege_result(rules: Rules, score: int) -> tuple[int, str]:
    """The progress a siege score buys, and what it is called."""
    gain, name = rules.siege_results[0][1:]
    for least, progress, called in rules.siege_results:
        if score >= least:
            gain, name = progress, called
    return gain, name


def battle_factor(state: GameState, nation: NationId | None, general_skill: int = 0) -> float:
    """How much harder an army fights thanks to its nation's military technology and its
    general. Independent levies have neither."""
    mods = modifiers(state, nation)
    return (1 + mods.battle_power) * (1 + state.rules.general_bonus_per_skill * general_skill)


def army_upkeep(
    rules: Rules, regiments: int | Mapping[UnitKind, int], grain_factor: float = 1.0
) -> Resources:
    """What an army eats and is paid each year. A plain number is that many pikemen."""
    army = {UnitKind.INFANTRY: regiments} if isinstance(regiments, int) else regiments
    pay = sum(n * rules.units[k].pay for k, n in army.items())
    rations = sum(n * rules.units[k].rations for k, n in army.items())
    return Resources(
        grain=math.ceil(rations * rules.grain_upkeep_per_regiment * grain_factor - 1e-9),
        ducats=math.ceil(pay * rules.ducat_upkeep_per_regiment - 1e-9),
    )


def army_of(state: GameState, nation: NationId) -> dict[UnitKind, int]:
    """Every regiment of a nation, by kind."""
    total = dict.fromkeys(UnitKind, 0)
    for p in state.provinces.values():
        if p.holder == nation:
            for kind, n in p.army().items():
                total[kind] += n
        if p.siege_by == nation:
            for kind, n in p.siege_army().items():
                total[kind] += n
    return total


def nation_upkeep(state: GameState, nation: NationId) -> Resources:
    """The army's food and pay, plus the advisors' salaries."""
    mods = modifiers(state, nation)
    army = army_upkeep(state.rules, army_of(state, nation), mods.grain_upkeep_factor)
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
        if not state.provinces[p].controller
    )
    return rules.manpower_cap_base + rules.manpower_cap_years * yearly


# ---------------------------------------------------------------- inputs and the market


def building_inputs(state: GameState, nation: NationId) -> list[tuple[ProvinceId, BuildingKind]]:
    """Every building of a nation that consumes something, in the order inputs are paid."""
    rules = state.rules
    return [
        (pid, b)
        for pid in state.provinces_of(nation)
        if not state.provinces[pid].controller
        for b in state.provinces[pid].buildings
        if not rules.buildings[b].consumes.is_empty()
    ]


def inputs_upkeep(state: GameState, nation: NationId) -> Resources:
    """What a nation's buildings consume in a year, if all of them work."""
    total = Resources()
    for _pid, b in building_inputs(state, nation):
        total = total + state.rules.buildings[b].consumes
    return total


def market_price(state: GameState, resource: str) -> float:
    """A unit's price on the European market today, before the merchants' cut."""
    return state.market.get(resource, state.rules.market_prices[resource])


def market_total(state: GameState, resource: str, amount: int, *, buying: bool) -> int:
    """What buying (or selling) `amount` units costs (or brings), the merchants' cut included."""
    price = market_price(state, resource)
    spread = state.rules.market_spread
    if buying:
        return math.ceil(amount * price * (1 + spread))
    return math.floor(amount * price * (1 - spread))


# ---------------------------------------------------------------- war score


def war_score(state: GameState, me: NationId, enemy: NationId) -> int:
    """How the war between `me` and `enemy` stands, from my side, from -100 to 100: the share
    of each side's land (by development) the other occupies, its capital, and battles won."""
    war = state.war(me, enemy)
    if war is None:
        return 0
    return min(100, _won(state, me, enemy, war.battles)) - min(
        100, _won(state, enemy, me, war.battles)
    )


def _won(state: GameState, side: NationId, against: NationId, battles: Mapping[str, int]) -> int:
    rules = state.rules
    theirs = [p for p, s in state.provinces.items() if s.owner == against]
    total = sum(state.provinces[p].development for p in theirs) or 1
    held = sum(
        state.provinces[p].development for p in theirs if state.provinces[p].controller == side
    )
    capital = state.nations[against].capital
    score = round(100 * held / total)
    if state.provinces[capital].controller == side:
        score += rules.war_score_capital
    score += min(rules.war_score_battles_max, battles.get(side, 0) * rules.war_score_per_battle)
    return score


def peace_cost(
    state: GameState,
    payer: NationId,
    *,
    provinces: Collection[ProvinceId] = (),
    lump: Resources | None = None,
    tribute: int = 0,
    army_limit: bool = False,
) -> int:
    """What demands on `payer` cost in war score: a province its share of the payer's land, a
    lump sum by years of the payer's income, a tribute by half that, an army limit a flat price."""
    rules = state.rules
    owned = [p for p, s in state.provinces.items() if s.owner == payer]
    total = sum(state.provinces[p].development for p in owned) or 1
    cost = sum(max(5, round(100 * state.provinces[p].development / total)) for p in provinces)
    income = max(10, nation_income(state, payer).ducats)
    if lump is not None:
        worth = lump.ducats + 2 * (lump.iron + lump.timber) + 3 * lump.manpower + lump.grain
        cost += round(rules.peace_cost_per_year_of_income * worth / income)
    if tribute:
        cost += round(
            rules.peace_cost_per_year_of_income * tribute * rules.tribute_years / income / 2
        )
    if army_limit:
        cost += rules.peace_cost_army_limit
    return cost


def develop_cost(
    rules: Rules,
    development: int,
    buildings: Collection[BuildingKind] = (),
    discount: float = 0.0,
    terrain: Terrain | None = None,
) -> Resources:
    ground = rules.terrain_develop_cost.get(terrain, 1.0) if terrain else 1.0
    ducats = math.ceil(
        (rules.develop_base_ducats + rules.develop_ducats_per_level * development) * ground
    )
    if BuildingKind.UNIVERSITY in buildings:
        ducats = math.ceil(ducats * (1 - rules.university_develop_discount))
    timber = math.ceil(
        (rules.develop_timber_base + rules.develop_timber_per_two_levels * (development // 2))
        * ground
    )
    goods = development // 3 if development >= rules.develop_goods_from else 0
    grain = rules.develop_grain_base + rules.develop_grain_per_level * development
    return discounted(Resources(ducats=ducats, timber=timber), discount) + Resources(
        goods=goods, grain=grain
    )


def recruit_cost(
    rules: Rules,
    regiments: int,
    buildings: Collection[BuildingKind] = (),
    kind: UnitKind = UnitKind.INFANTRY,
    arms: bool = False,
) -> Resources:
    """What raising regiments costs here: an armory in the province halves the iron, and an
    arms manufactory in the realm (`arms`) halves it too and spares the goods."""
    cost = unit_cost(rules, kind).times(regiments)
    if arms:
        cost = cost.model_copy(update={"iron": math.ceil(cost.iron / 2), "goods": 0})
    if BuildingKind.ARMORY in buildings:
        iron = math.ceil(cost.iron * (1 - rules.armory_iron_discount))
        cost = cost.model_copy(update={"iron": iron})
    return cost


def stability_cost(rules: Rules, discount: float = 0.0) -> Resources:
    return Resources(ducats=math.ceil(rules.stability_boost_ducats * (1 - discount)))


# ---------------------------------------------------------------- combat


def defense_multiplier(
    state: GameState, origin: ProvinceId, target: ProvinceId, siege: int = 0
) -> float:
    """How much harder the defenders of `target` fight against an attack from `origin`.
    `siege`: fort levels the attackers' guns knock off."""
    rules = state.rules
    target_state = state.provinces[target]
    terrain = rules.terrain_defense[state.map.provinces[target].terrain]
    owner = target_state.owner
    attacker = modifiers(state, state.provinces[origin].owner)
    forts = max(0, target_state.fort - attacker.ignores_fort_levels - siege)
    bonus = modifiers(state, owner).fort_bonus_per_level * forts
    if BuildingKind.TRAINING_GROUNDS in target_state.buildings:
        bonus += 0.2
    if owner is not None and state.nations[owner].capital == target:
        bonus += rules.capital_bonus
    if state.map.is_sea_crossing(origin, target) and not attacker.navy:
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
    attack_quality: float = 1.0,
    defence_quality: float = 1.0,
) -> BattleResult:
    """Resolve one battle. The loser's committed regiments are destroyed; the winner loses a share
    proportional to how close the fight was, but always keeps at least one regiment.

    `multiplier` is the ground (terrain, forts, capital, strait); the factors are technology and
    generals on each side; the qualities are what an average regiment of each army is worth
    (its mix of kinds on this ground, see `army_strength`)."""
    att = attackers * attack_quality * attack_factor * rng.uniform(rules.roll_min, rules.roll_max)
    dfn = (
        defenders
        * defence_quality
        * multiplier
        * defence_factor
        * rng.uniform(rules.roll_min, rules.roll_max)
    )
    if att > dfn:
        losses = min(attackers - 1, math.ceil(attackers * rules.winner_loss_factor * dfn / att))
        return BattleResult(True, att, dfn, losses, defenders)
    losses = min(defenders - 1, math.ceil(defenders * rules.winner_loss_factor * att / dfn))
    return BattleResult(False, att, dfn, attackers, losses)
