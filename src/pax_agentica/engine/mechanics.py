"""Pure formulas: production, costs and combat. No state changes happen here."""

import math
import random
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from pax_agentica.engine.model import (
    BuildingKind,
    Focus,
    GameState,
    Good,
    NationId,
    Posture,
    ProvinceId,
    Resources,
    Rules,
    Settlement,
    Tactic,
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


def focus_bonus(state: GameState, province: ProvinceId) -> float:
    """What a province's focus adds to its side of the output: rules.focus_base in a hamlet,
    focus_per_settlement more for each step its town has grown since."""
    p = state.provinces[province]
    if p.focus is None:
        return 0.0
    rules = state.rules
    here = settlement(rules, p.development)
    step = sorted(s.min_development for s in rules.settlements).index(here.min_development)
    return rules.focus_base + rules.focus_per_settlement * step


FOCUS_YIELDS: dict[Focus, tuple[str, ...]] = {
    Focus.TRADE: ("ducats",),
    Focus.FARMING: ("grain",),
    Focus.MINING: ("iron", "timber"),
    Focus.GARRISON: ("manpower",),
    Focus.LEARNING: (),
}


def settlement(rules: Rules, development: int) -> Settlement:
    """What a province's development makes of its chief town: hamlet, village, market town,
    city or great city."""
    reached = [s for s in rules.settlements if development >= s.min_development]
    return max(reached, key=lambda s: s.min_development) if reached else rules.settlements[0]


def building_slots(rules: Rules, development: int = 0, extra: int = 0) -> int:
    """Room for works: a hamlet has four, a great city eight; some realms find one more."""
    return settlement(rules, development).building_slots + extra


def level_factor(rules: Rules, level: int) -> float:
    """What a building does (and eats) at this level, times its first level's."""
    if level <= 0:
        return 0.0
    return rules.building_level_factors[min(level, len(rules.building_level_factors)) - 1]


def building_consumes(rules: Rules, kind: BuildingKind, level: int = 1) -> Resources:
    """What a building eats a year at its level."""
    f = level_factor(rules, level)
    return Resources(
        **{k: math.ceil(v * f - 1e-9) for k, v in rules.buildings[kind].consumes.amounts().items()}
    )


def upgrade_cost(rules: Rules, kind: BuildingKind, level: int, discount: float = 0.0) -> Resources:
    """What raising a building to `level` costs."""
    scale = rules.building_upgrade_costs[min(level, len(rules.building_upgrade_costs)) - 1]
    base = rules.buildings[kind].cost
    return discounted(
        Resources(**{k: math.ceil(v * scale) for k, v in base.amounts().items()}), discount
    )


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
    levels: Mapping[BuildingKind, int] | None = None,
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
        f = level_factor(rules, (levels or {}).get(building, 1))
        if field := OUTPUT_BUILDINGS.get(building):
            share = (shares.get(building) or rules.building_output_bonus) * f
            extra[field] += max(1, math.floor(amounts[field] * share))
        elif building == BuildingKind.BANK:
            extra["ducats"] += math.floor((3 + amounts["ducats"] * 0.5) * f)
        elif building == BuildingKind.CATHEDRAL:
            extra["manpower"] += math.floor(1 * f)
            extra["ducats"] += math.floor(amounts["ducats"] * 0.25 * f)
        elif building == BuildingKind.WORKSHOP:
            made = rules.workshop_base_goods + development // rules.workshop_goods_per_development
            extra["goods"] += math.floor(made * f)
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
        p.levels,
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
    upgrade: BuildingKind | None = None,
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
    levels = dict(p.levels)
    if upgrade is not None:
        levels[upgrade] = p.level(upgrade) + 1
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
            levels,
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
    if p.focus is not None and (fields := FOCUS_YIELDS[p.focus]):
        # a garrison town doubles its focus in men: soldiering is what it does
        share = focus_bonus(state, province) * (2 if p.focus == Focus.GARRISON else 1)
        out = out.model_copy(update={f: math.floor(getattr(out, f) * (1 + share)) for f in fields})
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
    men = (
        total.manpower
        * (1 - rules.tax_manpower_step * state.nations[nation].tax)
        * (1 + mods.manpower_income)
    )
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


def unit_cost(rules: Rules, kind: UnitKind, nation: NationId | None = None) -> Resources:
    """What one regiment of a kind costs; a crown's own regiments may cost it less."""
    cost = rules.units[kind].cost or rules.recruit_cost
    own = rules.national_units.get(nation or "")
    if own is None or own.kind != kind or own.cost == 1.0:
        return cost
    return Resources(**{k: math.ceil(v * own.cost) for k, v in cost.amounts().items()})


def unit_strength(
    rules: Rules,
    kind: UnitKind,
    terrain: Terrain,
    *,
    attacking: bool,
    nation: NationId | None = None,
) -> float:
    """One regiment of a kind on this ground, as its crown fields it."""
    spec = rules.units[kind]
    base = spec.attack if attacking else spec.defence
    ground = spec.terrain.get(terrain, 1.0)
    own = rules.national_units.get(nation or "")
    if own is not None and own.kind == kind:
        base *= own.attack if attacking else own.defence
        ground = own.terrain.get(terrain, ground)
    return base * ground


def army_strength(
    rules: Rules,
    army: Mapping[UnitKind, int],
    terrain: Terrain,
    *,
    attacking: bool,
    nation: NationId | None = None,
) -> float:
    """What a mix of regiments is worth in battle on this ground, combined arms and the crown's
    own regiments included. A pikeman on plains is worth 1."""
    total = sum(army.values())
    if total == 0:
        return 0.0
    power = 0.0
    for kind, n in army.items():
        power += n * unit_strength(rules, kind, terrain, attacking=attacking, nation=nation)
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


TACTIC_BEATS: dict[Tactic, Posture] = {
    Tactic.ASSAULT: Posture.SKIRMISH,
    Tactic.FLANK: Posture.HOLD,
    Tactic.BOMBARD: Posture.SALLY,
}
TACTIC_LOSES: dict[Tactic, Posture] = {
    Tactic.ASSAULT: Posture.HOLD,
    Tactic.FLANK: Posture.SALLY,
    Tactic.BOMBARD: Posture.SKIRMISH,
}
CARRIED_BY: dict[Tactic | Posture, UnitKind] = {
    Tactic.ASSAULT: UnitKind.INFANTRY,
    Tactic.FLANK: UnitKind.CAVALRY,
    Tactic.BOMBARD: UnitKind.ARTILLERY,
    Posture.HOLD: UnitKind.INFANTRY,
    Posture.SKIRMISH: UnitKind.ARCHERS,
    Posture.SALLY: UnitKind.CAVALRY,
}
BROKEN_GROUND = frozenset({Terrain.FOREST, Terrain.HILLS, Terrain.MARSH, Terrain.MOUNTAINS})


def carried(rules: Rules, how: Tactic | Posture, army: Mapping[UnitKind, int]) -> float:
    """How well an army can fight this way: 1 once the kind that carries it is a large enough
    share of it (rules.tactic_share), less below."""
    total = sum(army.values())
    if not total:
        return 0.0
    kind = CARRIED_BY[how]
    return min(1.0, army.get(kind, 0) / total / rules.tactic_share[kind])


def tactic_factor(
    rules: Rules,
    tactic: Tactic,
    posture: Posture,
    attackers: Mapping[UnitKind, int],
    defenders: Mapping[UnitKind, int],
    terrain: Terrain,
) -> float:
    """What the attacker's tactic is worth against the garrison's posture, as a factor on the
    attack. A tactic that beats the posture adds rules.tactic_edge, as far as the attackers can
    carry it; a posture that beats the tactic takes it off, as far as the garrison can carry
    its own. A side that fights in a way its regiments cannot carry is caught out as badly as
    one outguessed: a sally with no horse, a bombardment with no guns. Never more than the edge
    either way. Horse cannot ride round an enemy in broken ground: there a flank gains half as
    much (and loses as much as anywhere)."""
    ours, theirs = carried(rules, tactic, attackers), carried(rules, posture, defenders)
    swing = (1 - theirs) - (1 - ours)
    if TACTIC_BEATS[tactic] == posture:
        swing += ours
    elif TACTIC_LOSES[tactic] == posture:
        swing -= theirs
    swing = max(-1.0, min(1.0, swing))
    if tactic == Tactic.FLANK and terrain in BROKEN_GROUND and swing > 0:
        swing /= 2
    return 1 + rules.tactic_edge * swing


def morale(state: GameState, nation: NationId | None) -> float:
    """A realm's morale in battle: its stability steadies its men, its war exhaustion tires
    them. Independent levies fight as they always have."""
    if nation is None:
        return 1.0
    me, rules = state.nations[nation], state.rules
    return (
        1
        + rules.morale_per_stability * me.stability
        - rules.morale_per_exhaustion * me.war_exhaustion
    )


def veteran(rules: Rules, veterancy: float) -> float:
    """What a veteran army is worth: up to rules.veterancy_bonus more at full veterancy."""
    return 1 + rules.veterancy_bonus * veterancy


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
    wear = sum(n * (3 if k == UnitKind.ARTILLERY else 1) for k, n in army.items())
    return Resources(
        grain=math.ceil(rations * rules.grain_upkeep_per_regiment * grain_factor - 1e-9),
        ducats=math.ceil(pay * rules.ducat_upkeep_per_regiment - 1e-9),
        iron=wear // rules.iron_upkeep_per_regiments,  # shot, powder, horseshoes and repairs
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
    for pid, b in building_inputs(state, nation):
        total = total + building_consumes(state.rules, b, state.provinces[pid].level(b))
    return total


def market_price(state: GameState, resource: str) -> float:
    """A unit's price on the European market today, before the merchants' cut."""
    return state.market.get(resource, state.rules.market_prices[resource])


def market_cut(state: GameState, nation: NationId | None = None) -> float:
    """The merchants' cut a nation pays on the market, buying and selling, after its bonuses."""
    return state.rules.market_spread * (1 - modifiers(state, nation).trade_bonus)


def market_total(
    state: GameState, resource: str, amount: int, *, buying: bool, nation: NationId | None = None
) -> int:
    """What buying (or selling) `amount` units costs (or brings), the merchants' cut included."""
    price = market_price(state, resource)
    spread = market_cut(state, nation)
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
    # a province costs its share of the payer's land, at least 5, unless it is already
    # occupied: then exactly its share, which is what holding it adds to the war score
    cost = sum(
        share if state.provinces[p].controller else max(5, share)
        for p in provinces
        for share in [round(100 * state.provinces[p].development / total)]
    )
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
    focus: float = 0.0,
) -> Resources:
    """What one more level of development costs. `focus`: a province of learning's bonus, which
    takes that share off its ducats and timber."""
    ground = rules.terrain_develop_cost.get(terrain, 1.0) if terrain else 1.0
    discount = min(0.8, discount + focus)
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
    iron = max(0, development - rules.develop_iron_from + 1)
    return discounted(Resources(ducats=ducats, timber=timber), discount) + Resources(
        goods=goods, grain=grain, iron=iron
    )


def recruit_cost(
    rules: Rules,
    regiments: int,
    buildings: Collection[BuildingKind] = (),
    kind: UnitKind = UnitKind.INFANTRY,
    arms: bool = False,
    nation: NationId | None = None,
) -> Resources:
    """What raising regiments costs here: an armory in the province halves the iron, and an
    arms manufactory in the realm (`arms`) halves it too and spares the goods."""
    cost = unit_cost(rules, kind, nation).times(regiments)
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
    owner, holder = target_state.owner, target_state.holder
    attacker = modifiers(state, state.provinces[origin].holder)
    forts = max(0, target_state.fort - attacker.ignores_fort_levels - siege)
    # the walls fight for whoever holds them, with that realm's art of fortification
    bonus = modifiers(state, holder).fort_bonus_per_level * forts
    if target_state.focus == Focus.GARRISON and holder == owner:  # its own people man the walls
        bonus += focus_bonus(state, target) / 2
    if BuildingKind.TRAINING_GROUNDS in target_state.buildings:
        bonus += 0.2 * level_factor(rules, target_state.level(BuildingKind.TRAINING_GROUNDS))
    if owner is not None and holder == owner and state.nations[owner].capital == target:
        bonus += rules.capital_bonus  # a capital's own people defend it, not its occupiers
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
