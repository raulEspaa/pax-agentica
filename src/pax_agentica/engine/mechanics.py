"""Pure formulas: production, costs and combat. No state changes happen here."""

import math
import random
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from pax_agentica.engine.colonies import COLONIAL_SPIRITS
from pax_agentica.engine.model import (
    BuildingKind,
    ColonialGood,
    Colony,
    ColonyKind,
    Focus,
    GameState,
    Good,
    NationId,
    Posture,
    ProvinceId,
    Region,
    Resources,
    Rules,
    SeaId,
    Settlement,
    Ship,
    Tactic,
    TechBranch,
    Terrain,
    UnitKind,
    Water,
)
from pax_agentica.engine.realm import advisor_salaries, designation, modifiers

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
    Focus.SHIPYARD: ("timber",),
}


def settlement(rules: Rules, development: int) -> Settlement:
    """What a province's development makes of its chief town: hamlet, village, market town,
    city or great city."""
    reached = [s for s in rules.settlements if development >= s.min_development]
    return max(reached, key=lambda s: s.min_development) if reached else rules.settlements[0]


def building_slots(rules: Rules, development: int = 0, extra: int = 0) -> int:
    """Room for works: a hamlet has four, a great city eight; some realms find one more."""
    return settlement(rules, development).building_slots + extra


def province_slots(state: GameState, province: ProvinceId) -> int:
    """A province's room for works: its town's, its realm's extra, and one more once its
    designation reaches tier 2."""
    p = state.provinces[province]
    held = designation(state, province)
    extra = modifiers(state, p.owner).extra_building_slots + (1 if held and held[1] >= 2 else 0)
    return building_slots(state.rules, p.development, extra)


def neighbour_shares(state: GameState, province: ProvinceId) -> dict[str, float]:
    """What the great designations of the realm's provinces next door add to this one."""
    p = state.provinces[province]
    out: dict[str, float] = {}
    if p.owner is None:
        return out
    for q in state.map.provinces[province].neighbors:
        held = designation(state, q)
        if held is None or held[1] < 3 or state.provinces[q].owner != p.owner:
            continue
        for k, v in state.rules.designations[held[0]].neighbours.items():
            out[k] = out.get(k, 0.0) + v
    return out


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
            least = 2 if building == BuildingKind.LUMBER_MILL else 1  # its saws earn their iron
            extra[field] += max(least, math.floor(amounts[field] * share))
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
    near = {k: v for k, v in neighbour_shares(state, province).items() if hasattr(out, k)}
    if near:
        out = out.model_copy(
            update={k: math.floor(getattr(out, k) * (1 + v)) for k, v in near.items()}
        )
    return _keep(out, faith_penalty(state, province))


def naval_power(state: GameState, nation: NationId | None, sea: SeaId) -> float:
    """What a realm's ships in a sea zone are worth: each kind by its strength in that kind of
    water, times the realm's own seamanship."""
    zone = state.map.seas.get(sea)
    if nation is None or zone is None:
        return 0.0
    rules = state.rules
    ships = state.nations[nation].ships(sea)
    base = sum(n * rules.ships[k].strength[zone.water] for k, n in ships.items())
    return base * (1 + modifiers(state, nation).navy) if base else 0.0


def ocean_power(
    state: GameState, nation: NationId, waters: Collection[Water] = (Water.ATLANTIC,)
) -> float:
    """A realm's fleets on every zone of these waters together: its sway on the ocean."""
    return sum(
        naval_power(state, nation, z)
        for z, zone in state.map.seas.items()
        if zone.water in waters and z in state.nations[nation].fleets
    )


def carries(rules: Rules, ships: Mapping[Ship, int]) -> int:
    """How many regiments these ships can carry to a landing."""
    return sum(n * rules.ships[k].carries for k, n in ships.items())


def fleet_upkeep(rules: Rules, fleets: Mapping[SeaId, Mapping[Ship, int]]) -> int:
    """What a realm's ships cost in ducats a year."""
    pay = sum(n * rules.ships[k].pay for ships in fleets.values() for k, n in ships.items())
    return math.ceil(pay - 1e-9)


def sea_command(
    state: GameState, attacker: NationId | None, defender: NationId | None, sea: SeaId
) -> str:
    """Who holds a sea zone for a crossing: "closed" when the defender's fleet is
    rules.fleet_command times the attacker's (no army crosses), "ours" when the attacker's is
    the stronger (the strait favours no one), else "contested" (it favours the defender)."""
    mine, theirs = sea_reach(state, attacker, sea), sea_reach(state, defender, sea)
    if theirs > 0 and theirs >= state.rules.fleet_command * mine:
        return "closed"
    return "ours" if mine > theirs else "contested"


def sea_reach(state: GameState, nation: NationId | None, sea: SeaId) -> float:
    """A realm's sway over a strait's sea: its fleet there, and half of its fleets in the
    zones next to it, that can sail in when an army crosses."""
    zone = state.map.seas.get(sea)
    if nation is None or zone is None:
        return 0.0
    near = sum(naval_power(state, nation, z) for z in zone.neighbors)
    return naval_power(state, nation, sea) + state.rules.fleet_reach * near


def blockaded(state: GameState, nation: NationId) -> set[SeaId]:
    """The sea zones an enemy at war holds against this realm: a fleet of at least
    rules.blockade_min there, and rules.fleet_command times its own."""
    rules = state.rules
    out: set[SeaId] = set()
    enemies = state.enemies_of(nation)
    if not enemies:
        return out
    for sea in state.map.seas:
        mine = naval_power(state, nation, sea)
        for enemy in enemies:
            theirs = naval_power(state, enemy, sea)
            if theirs >= rules.blockade_min and theirs >= rules.fleet_command * mine:
                out.add(sea)
    return out


def blockaded_ports(state: GameState, nation: NationId) -> list[ProvinceId]:
    """The realm's provinces whose every sea an enemy fleet holds: their trade is choked."""
    shut = blockaded(state, nation) if state.wars else set()
    if not shut:
        return []
    return [
        pid
        for pid in state.provinces_of(nation)
        if (seas := state.map.provinces[pid].seas) and set(seas) <= shut
    ]


def ocean_blockaded(state: GameState, nation: NationId) -> bool:
    """Whether every ocean zone the realm's ports open onto is held by an enemy fleet: then
    no treasure fleet comes home."""
    shut = blockaded(state, nation) if state.wars else set()
    if not shut:
        return False
    ocean = {
        z
        for pid in state.provinces_of(nation)
        for z in state.map.provinces[pid].seas
        if state.map.seas[z].water == Water.ATLANTIC
    }
    return bool(ocean) and ocean <= shut


def landing_sea(
    state: GameState, nation: NationId, origin: ProvinceId, target: ProvinceId
) -> SeaId | None:
    """The sea zone an army could be carried over from `origin` to `target`: one both look
    onto, where the realm's fleet outmatches whoever holds `target` (best: the most it can
    carry). None when there is none."""
    there = state.provinces[target]
    enemy = there.siege_by if there.siege_by not in (None, nation) else there.holder
    best, room = None, 0
    for sea in state.map.shared_seas(origin, target):
        if enemy not in (None, nation) and sea_command(state, nation, enemy, sea) != "ours":
            continue
        if enemy in (None, nation) and any(
            sea_command(state, nation, e, sea) == "closed" for e in state.enemies_of(nation)
        ):
            continue
        cap = carries(state.rules, state.nations[nation].ships(sea))
        if cap > room:
            best, room = sea, cap
    return best


def nation_income(state: GameState, nation: NationId, inflated: bool = True) -> Resources:
    """Total production per turn, with stability and the realm's modifiers (technology, ruler,
    treasurer) applied to ducats, and economy technology to grain. A blockaded port loses
    rules.blockade_share of its ducats; inflation takes its share of the land's ducats."""
    rules = state.rules
    total = Resources()
    shut = set(blockaded_ports(state, nation))
    for province in state.provinces_of(nation):
        out = province_output(state, province)
        if province in shut:
            loss = rules.blockade_share * (1 - modifiers(state, nation).convoys)
            out = out.model_copy(update={"ducats": math.floor(out.ducats * (1 - loss))})
        total = total + out
    mods = modifiers(state, nation)
    stability = rules.stability_income_bonus * state.nations[nation].stability
    ducats = total.ducats * (1 + stability + mods.ducat_income)
    if inflated:
        ducats *= 1 - min(rules.inflation_max, state.nations[nation].inflation)
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
    ) + colonial_dues(state, nation)


# ---------------------------------------------------------------- the New World


def inflation_loss(state: GameState, nation: NationId) -> int:
    """The ducats inflation takes from the land this year."""
    if not state.nations[nation].inflation:
        return 0
    return nation_income(state, nation, inflated=False).ducats - nation_income(state, nation).ducats


def colony_share(rules: Rules, colony: Colony, turn: int) -> float:
    """A colony's share of its region's cargo: by its kind, and a settlement's by its years."""
    spec = rules.colony_kinds[colony.kind]
    return min(spec.most, spec.cargo + spec.growth * max(0, turn - colony.founded))


def colonial_cargo(state: GameState, nation: NationId) -> dict[Region, float]:
    """The cargoes a crown's colonies ship home a year, by region (a viceroy adds to them)."""
    rules, me = state.rules, state.nations[nation]
    out: dict[Region, float] = {}
    for region, held in me.colonies.items():
        vice = me.viceroys.get(region)
        more = 1 + (rules.viceroy_cargo * vice.skill if vice else 0.0)
        out[region] = (
            rules.regions[region].cargo
            * more
            * sum(colony_share(rules, c, state.turn) for c in held)
        )
    return out


def good_supply(state: GameState) -> dict[ColonialGood, float]:
    """The cargoes of each colonial good every crown together ships a year."""
    supply = dict.fromkeys(ColonialGood, 0.0)
    for nid, n in state.nations.items():
        if n.alive and n.colonies:
            for region, cargo in colonial_cargo(state, nid).items():
                supply[state.rules.regions[region].good] += cargo
    return supply


def good_price(
    state: GameState, good: ColonialGood, supply: dict[ColonialGood, float] | None = None
) -> float:
    """A cargo's price in ducats: the good's base, less for every cargo past what Europe wants."""
    rules = state.rules
    spec = rules.goods[good]
    shipped = (supply or good_supply(state))[good]
    glut = rules.good_price_drop * max(0.0, shipped - spec.glut)
    return spec.price * max(rules.good_price_floor, 1 - glut)


@dataclass(frozen=True)
class GoodTrade:
    """A crown's trade in one colonial good this year."""

    good: ColonialGood
    cargo: float  # its cargoes
    price: float  # ducats each, monopoly included
    ducats: float  # what it brings, before the crown's own bonuses
    shipped: float  # every crown's cargoes of it
    monopoly: bool  # the crown ships most of it, and names its price


def colonial_trade(state: GameState, nation: NationId) -> list[GoodTrade]:
    """What each of the crown's colonial goods brings home, at today's prices."""
    rules = state.rules
    supply = good_supply(state)
    mine = dict.fromkeys(ColonialGood, 0.0)
    for region, cargo in colonial_cargo(state, nation).items():
        mine[rules.regions[region].good] += cargo
    out = []
    for good, cargo in mine.items():
        if cargo <= 0:
            continue
        # the master of a good ships most of it, and at least half what Europe wants of it
        master = (
            cargo >= rules.monopoly_share * supply[good] and cargo >= rules.goods[good].glut / 2
        )
        price = good_price(state, good, supply) * (1 + (rules.monopoly_bonus if master else 0.0))
        out.append(GoodTrade(good, cargo, price, cargo * price, supply[good], master))
    return out


def colonial_dues(state: GameState, nation: NationId) -> Resources:
    """What a crown's colonies send home a year: their cargoes sold at the goods' prices, and
    each region's other dues by its colonies' shares; more for the crowns that know how to work
    them, and much less while an enemy blockades the Atlantic (the treasure fleets cannot sail)."""
    me = state.nations[nation]
    if not me.colonies:
        return Resources()
    rules = state.rules
    spirit = COLONIAL_SPIRITS.get(nation)
    learnt = modifiers(state, nation).colonial_dues
    total = {k: 0.0 for k in Resources.model_fields}
    prices = {t.good: t.price for t in colonial_trade(state, nation)}
    cargo = colonial_cargo(state, nation)
    for region, held in me.colonies.items():
        spec = rules.regions[region]
        bonus = 1 + (spirit.dues.get(region, 0.0) if spirit else 0.0) + learnt
        kept = 1 - native_resistance(state, nation, region)
        total["ducats"] += cargo.get(region, 0.0) * prices.get(spec.good, 0.0) * bonus * kept
        share = sum(colony_share(rules, c, state.turn) for c in held)
        for k, v in spec.yields.amounts().items():
            total[k] += v * share * bonus * kept
    if ocean_blockaded(state, nation):
        total = {k: v * (1 - rules.colonial_blockade) for k, v in total.items()}
    return Resources(**{k: math.floor(v) for k, v in total.items()})


def natives_left(state: GameState, region: Region) -> int:
    """The regiments a region's peoples can still field."""
    return state.natives.get(region, state.rules.regions[region].natives)


def colonial_defenders(state: GameState, nation: NationId, region: Region) -> int:
    """The regiments that hold a crown's colonies in a region: its garrison and its settlers."""
    me, rules = state.nations[nation], state.rules
    militia = sum(rules.colony_kinds[c.kind].militia for c in me.colonies.get(region, []))
    return me.garrisons.get(region, 0) + militia


def colonial_defence(state: GameState, nation: NationId, region: Region) -> float:
    """What a crown's colonies in a region hold out with: their defenders, behind palisades
    and forts, the better where a viceroy rules."""
    me, rules = state.nations[nation], state.rules
    fort = 1 + rules.colonial_fort_defence * me.colonial_forts.get(region, 0)
    viceroy = 1 + (rules.viceroy_defence if region in me.viceroys else 0.0)
    held = colonial_defenders(state, nation, region)
    return held * fort * viceroy * rules.colonial_defender * morale(state, nation)


def overseas_power(state: GameState, nation: NationId, regiments: int) -> float:
    """What regiments carried overseas fight with: the realm's battle power and morale."""
    return regiments * (1 + modifiers(state, nation).battle_power) * morale(state, nation)


def natives_defence(state: GameState, region: Region) -> float:
    """What a region's peoples fight with, on their own ground."""
    rules = state.rules
    return natives_left(state, region) * (1 + rules.native_terrain * rules.regions[region].hardness)


def native_resistance(state: GameState, nation: NationId, region: Region) -> float:
    """The share of a crown's dues in a region its peoples deny it: the more of them and the
    angrier its colonies make them, the less where soldiers and settlers hold the land."""
    rules, me = state.rules, state.nations[nation]
    left = natives_left(state, region)
    if not left or not me.colonies.get(region):
        return 0.0
    anger = sum(rules.colony_kinds[c.kind].anger for c in me.colonies[region])
    raw = min(rules.native_resistance_max, left * anger * rules.native_anger)
    held = colonial_defenders(state, nation, region) + (2 if region in me.viceroys else 0)
    return raw * rules.native_calm / (rules.native_calm + held)


def ocean_carry(state: GameState, nation: NationId) -> int:
    """How many regiments the crown's ships on the ocean and the Baltic carry overseas."""
    me = state.nations[nation]
    return sum(
        carries(state.rules, me.ships(z))
        for z, zone in state.map.seas.items()
        if zone.water in (Water.ATLANTIC, Water.BALTIC)
    )


def overseas_error(
    state: GameState, nation: NationId, port: ProvinceId, regiments: int
) -> str | None:
    """Why regiments cannot sail overseas from this port now (None: they can)."""
    if port not in colonial_ports(state, nation):
        where = state.map.provinces[port].name if port in state.map.provinces else port
        return f"{where} is no port of yours on the ocean or the Baltic"
    if regiments <= 0:
        return "send at least one regiment"
    if state.provinces[port].troops < regiments:
        return f"only {state.provinces[port].troops} regiments in {state.map.provinces[port].name}"
    room = ocean_carry(state, nation)
    if regiments > room:
        return f"your ships on the ocean carry only {room} regiments"
    mine = ocean_fleet(state, nation)
    for enemy in sorted(state.enemies_of(nation)):
        theirs = ocean_fleet(state, enemy)
        if theirs >= state.rules.fleet_command * max(mine, 0.1) and theirs > 0:
            return f"{state.nations[enemy].name}'s fleets command the ocean"
    return None


def silver_shipped(state: GameState, nation: NationId) -> float:
    """The ducats of silver a crown ships home a year, which feed its inflation."""
    return sum(
        t.ducats for t in colonial_trade(state, nation) if state.rules.goods[t.good].inflation
    )


def colonial_ports(state: GameState, nation: NationId) -> list[ProvinceId]:
    """The crown's own ports an expedition can sail from: on the Atlantic or the Baltic."""
    return [
        pid
        for pid in state.provinces_of(nation)
        if not state.provinces[pid].controller
        and {Water.ATLANTIC, Water.BALTIC} & set(state.map.provinces[pid].coasts)
    ]


def colonies_in(state: GameState, region: Region) -> int:
    """The colonies every crown together holds in a region."""
    return sum(n.colony_count(region) for n in state.nations.values() if n.alive)


def ocean_fleet(state: GameState, nation: NationId) -> float:
    """The fleet that escorts expeditions: the crown's ships on the Atlantic and the Baltic."""
    return ocean_power(state, nation, (Water.ATLANTIC, Water.BALTIC))


def expedition_cost(rules: Rules, kind: ColonyKind) -> Resources:
    """What an expedition to found a colony of this kind costs."""
    share = rules.colony_kinds[kind].cost
    return Resources(
        **{k: math.ceil(v * share) for k, v in rules.expedition_cost.amounts().items()}
    )


def expedition_progress(
    state: GameState, nation: NationId, region: Region, kind: ColonyKind = ColonyKind.PLANTATION
) -> int:
    """An expedition's progress a year before the die (which adds 5 to 30): the base, the
    escorting fleet, the crown's own way and the kind of colony, less the region's hardness,
    and less again sailing the long way round from the Baltic."""
    rules = state.rules
    spirit = COLONIAL_SPIRITS.get(nation)
    fleet = min(
        rules.expedition_fleet_cap, int(ocean_fleet(state, nation) * rules.expedition_per_strength)
    )
    atlantic = any(
        Water.ATLANTIC in state.map.provinces[p].coasts for p in colonial_ports(state, nation)
    )
    return (
        rules.expedition_base
        + fleet
        + (spirit.progress.get(region, 0) if spirit else 0)
        + modifiers(state, nation).colonial
        + rules.colony_kinds[kind].progress
        - rules.regions[region].hardness
        - (0 if atlantic else rules.expedition_baltic)
    )


def expedition_error(state: GameState, nation: NationId, region: Region) -> str | None:
    """Why a crown cannot send an expedition to a region now (None: it can)."""
    rules, me = state.rules, state.nations[nation]
    spec = rules.regions[region]
    if state.year < spec.opens:
        return f"the way to {spec.name} is not known before {spec.opens}"
    if not colonial_ports(state, nation):
        return "you hold no port on the Atlantic or the Baltic"
    if ocean_fleet(state, nation) < rules.expedition_ships:
        need = f"{rules.expedition_ships:g}"
        return f"an expedition needs an escort: a fleet of {need} on the Atlantic or the Baltic"
    if any(e.region == region for e in me.expeditions):
        return f"an expedition of yours is already on its way to {spec.name}"
    if len(me.expeditions) >= rules.expeditions_at_once:
        return f"no more than {rules.expeditions_at_once} expeditions at once"
    if colonies_in(state, region) >= spec.slots:
        return f"{spec.name} is full: every place there is taken"
    if me.colony_count(region) >= region_cap(rules, region):
        return f"you hold all of {spec.name} one crown may: the other crowns will not suffer more"
    return None


def viceroyalty_error(state: GameState, nation: NationId, region: Region) -> str | None:
    """Why a crown cannot make a region a viceroyalty now (None: it can)."""
    rules, me = state.rules, state.nations[nation]
    name = rules.regions[region].name
    if region in me.viceroys:
        return f"{name} is already a viceroyalty of yours"
    if me.colony_count(region) < rules.viceroyalty_colonies:
        return f"a viceroyalty needs {rules.viceroyalty_colonies} colonies of yours in {name}"
    if me.authority < rules.viceroyalty_authority:
        return f"a viceroyalty needs {rules.viceroyalty_authority} authority"
    return None


def region_cap(rules: Rules, region: Region) -> int:
    """The most colonies one crown may hold in a region: its share of the places."""
    return max(1, math.ceil(rules.regions[region].slots * rules.region_share))


def seize_factor(state: GameState, nation: NationId) -> float:
    """The ocean fleet, times the enemy's, a crown needs to take one of its colonies."""
    spirit = COLONIAL_SPIRITS.get(nation)
    factor = spirit.seize if spirit and spirit.seize is not None else state.rules.seize_command
    return min(factor, 1.5) if modifiers(state, nation).privateers else factor


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
    if siege := modifiers(state, p.siege_by).siege:
        out.append(("siege doctrine", siege))
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
        + modifiers(state, nation).morale
        + (rules.presence_morale if "royal_presence" in me.flags else 0.0)
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
    me = state.nations[nation]
    salaries = advisor_salaries(state.rules, me.advisors)
    overseas = state.rules.garrison_pay * sum(me.garrisons.values())
    return army + Resources(ducats=salaries + fleet_pay(state, nation) + overseas)


def fleet_pay(state: GameState, nation: NationId) -> int:
    """What the crews cost this year: in peace the ships lie up in port and cost nothing; at
    war they are manned and paid."""
    if not state.enemies_of(nation):
        return 0
    return fleet_upkeep(state.rules, state.nations[nation].fleets)


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


def hegemon(state: GameState) -> NationId | None:
    """The crown all Europe fears: the first in standing, by rules.hegemon_ratio over the
    second, with at least rules.hegemon_standing."""
    rules = state.rules
    ranked = sorted((state.standing(n), n) for n in state.alive_nations())
    if len(ranked) < 2:
        return None
    (second, _), (first, top) = ranked[-2], ranked[-1]
    if first >= rules.hegemon_standing and first >= rules.hegemon_ratio * max(1, second):
        return top
    return None


def revanche(state: GameState, nation: NationId | None, province: ProvinceId) -> bool:
    """Whether `province` was taken from `nation` within rules.revanche_years, and is held by
    another: its lost land, to win back."""
    if nation is None:
        return False
    since = state.nations[nation].lost.get(province)
    held = state.provinces[province].owner
    return since is not None and held != nation and state.turn - since < state.rules.revanche_years


def lost_land(state: GameState, nation: NationId) -> list[ProvinceId]:
    """The provinces a crown may still win back."""
    return sorted(p for p in state.nations[nation].lost if revanche(state, nation, p))


def peace_cost(
    state: GameState,
    payer: NationId,
    *,
    claimant: NationId | None = None,
    provinces: Collection[ProvinceId] = (),
    lump: Resources | None = None,
    tribute: int = 0,
    army_limit: bool = False,
) -> int:
    """What demands on `payer` cost in war score: a province its share of the payer's land (less
    when it is the claimant's lost land), a lump sum by years of the payer's income, a tribute by
    half that, an army limit a flat price."""
    rules = state.rules
    owned = [p for p, s in state.provinces.items() if s.owner == payer]
    total = sum(state.provinces[p].development for p in owned) or 1
    # a province costs its share of the payer's land, at least 5, unless it is already
    # occupied: then exactly its share, which is what holding it adds to the war score
    cost = sum(
        round(price * (rules.revanche_price if revanche(state, claimant, p) else 1))
        for p in provinces
        for share in [round(100 * state.provinces[p].development / total)]
        for price in [share if state.provinces[p].controller else max(5, share)]
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


def defense_factors(
    state: GameState, origin: ProvinceId, target: ProvinceId, siege: int = 0
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Why the defenders of `target` fight harder against an attack from `origin`: the factors
    that multiply (the defender's advantage, the ground) and the bonuses that add up (walls, a
    capital, a strait...), each with what it is. `siege`: fort levels the attackers' guns knock
    off."""
    rules = state.rules
    target_state = state.provinces[target]
    ground = state.map.provinces[target].terrain
    owner, holder = target_state.owner, target_state.holder
    attacker = modifiers(state, state.provinces[origin].holder)
    times = [("defenders' advantage", rules.defender_advantage)]
    times.append((ground.value, rules.terrain_defense[ground]))
    bonuses: list[tuple[str, float]] = []
    forts = max(0, target_state.fort - attacker.ignores_fort_levels - siege)
    # the walls fight for whoever holds them, with that realm's art of fortification
    if forts:
        bonuses.append(("walls", modifiers(state, holder).fort_bonus_per_level * forts))
    if target_state.focus == Focus.GARRISON and holder == owner:  # its own people man the walls
        bonuses.append(("a garrison province", focus_bonus(state, target) / 2))
    if holder == owner and (help := neighbour_shares(state, target).get("defence", 0.0)):
        bonuses.append(("a great fortress next door", help))
    if BuildingKind.TRAINING_GROUNDS in target_state.buildings:
        drill = 0.2 * level_factor(rules, target_state.level(BuildingKind.TRAINING_GROUNDS))
        bonuses.append(("training grounds", drill))
    if owner is not None and holder == owner and state.nations[owner].capital == target:
        bonuses.append(("the capital", rules.capital_bonus))  # its own people defend it
    if state.map.is_sea_crossing(origin, target):  # unless the attacker holds the water
        sea = state.map.strait_sea(origin, target)
        crosser = state.provinces[origin].holder
        if sea is None or sea_command(state, crosser, holder, sea) != "ours":
            bonuses.append(("a strait", rules.sea_crossing_bonus))
    elif not state.map.adjacent(origin, target):  # a landing from the boats
        beach = max(0.0, rules.sea_crossing_bonus + rules.landing_bonus - attacker.landing)
        if beach:
            bonuses.append(("a landing", beach))
    return times, bonuses


def defense_multiplier(
    state: GameState, origin: ProvinceId, target: ProvinceId, siege: int = 0
) -> float:
    """How much harder the defenders of `target` fight against an attack from `origin`.
    `siege`: fort levels the attackers' guns knock off."""
    times, bonuses = defense_factors(state, origin, target, siege)
    return math.prod(v for _, v in times) * (1 + sum(v for _, v in bonuses))


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
