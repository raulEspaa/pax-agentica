"""Kinds of regiments, great works and monuments."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import (
    Attack,
    Build,
    DeclareWar,
    Disband,
    HireGeneral,
    Move,
    Recruit,
    UpgradeMonument,
)
from pax_agentica.engine.mechanics import (
    army_strength,
    army_upkeep,
    defense_multiplier,
    nation_income,
    research_cost,
    siege_levels,
)
from pax_agentica.engine.model import BuildingKind, TechBranch, Terrain, UnitKind, share
from pax_agentica.engine.realm import modifiers

type Play = Callable[..., GameState]

RICH = Resources(ducats=3000, manpower=300, iron=300, grain=500, timber=500)
P, A, C, G = UnitKind.INFANTRY, UnitKind.ARCHERS, UnitKind.CAVALRY, UnitKind.ARTILLERY


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


# ---------------------------------------------------------------- the garrison by kind


def test_a_garrison_is_pikemen_unless_told_otherwise(state: GameState) -> None:
    lyon = state.provinces["lyon"]
    assert lyon.army() == {P: lyon.troops, A: 0, C: 0, G: 0}
    paris = state.provinces["paris"]
    assert paris.army()[C] == 2  # the gendarmerie
    assert sum(paris.army().values()) == paris.troops


def test_setting_troops_by_hand_keeps_the_garrison_consistent(state: GameState) -> None:
    paris = state.provinces["paris"]
    paris.troops = 1  # fewer than the cavalry it held
    assert sum(paris.army().values()) == 1


def test_a_share_is_proportional_and_exact() -> None:
    army = {P: 6, A: 3, C: 1, G: 0}
    taken = share(army, 5)
    assert sum(taken.values()) == 5
    assert taken[P] == 3
    assert all(taken[k] <= army[k] for k in army)


# ---------------------------------------------------------------- recruiting


def test_cavalry_needs_stables_and_artillery_a_foundry(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    new = play(
        state,
        france=[
            Recruit(province="lyon", regiments=2, unit=C),
            Recruit(province="paris", regiments=2, unit=C),  # Paris has stables
            Recruit(province="paris", regiments=1, unit=G),
        ],
    )
    assert reasons(new) == [
        "cavalry need stables in the province",
        "artillery need a cannon foundry in the province",
    ]
    assert new.provinces["paris"].army()[C] == 4


def test_each_kind_has_its_price_and_its_upkeep(state: GameState) -> None:
    rules = state.rules
    assert army_upkeep(rules, {C: 2}).grain == 2 * army_upkeep(rules, {P: 2}).grain
    assert army_upkeep(rules, {G: 2}).ducats > army_upkeep(rules, {P: 2}).ducats
    view = view_for(state, "france")
    paris = next(p for p in view.provinces if p.id == "paris")
    assert set(paris.recruit_costs) == {P, A, C}  # no foundry, no guns
    assert paris.recruit_costs[C].ducats > paris.recruit_costs[P].ducats


def test_disbanding_one_kind(state: GameState, play: Play) -> None:
    new = play(state, france=[Disband(province="paris", regiments=2, unit=C)])
    assert new.provinces["paris"].army()[C] == 0
    again = play(new, france=[Disband(province="paris", regiments=1, unit=C)])
    assert reasons(again) == ["only 0 cavalry regiments in Paris"]


def test_a_march_can_choose_its_regiments(state: GameState, play: Play) -> None:
    new = play(state, france=[Move(origin="paris", target="lyon", regiments=2, units={C: 2})])
    assert new.provinces["lyon"].army()[C] == 2
    assert new.provinces["paris"].army()[C] == 0
    wrong = play(state, france=[Move(origin="paris", target="lyon", regiments=3, units={C: 2})])
    assert reasons(wrong) == ["the regiments by kind add up to 2, not 3"]


# ---------------------------------------------------------------- battle


def test_cavalry_charges_on_plains_and_bogs_down_in_mountains(state: GameState) -> None:
    rules = state.rules
    plains = army_strength(rules, {C: 10}, Terrain.PLAINS, attacking=True)
    mountains = army_strength(rules, {C: 10}, Terrain.MOUNTAINS, attacking=True)
    pikes = army_strength(rules, {P: 10}, Terrain.PLAINS, attacking=True)
    assert plains > pikes > mountains


def test_archers_hold_the_line(state: GameState) -> None:
    rules = state.rules
    archers = army_strength(rules, {A: 10}, Terrain.HILLS, attacking=False)
    pikes = army_strength(rules, {P: 10}, Terrain.HILLS, attacking=False)
    assert archers > pikes


def test_combined_arms_beat_one_kind(state: GameState) -> None:
    rules = state.rules
    mixed = army_strength(rules, {P: 4, A: 3, C: 3}, Terrain.FOREST, attacking=True)
    plain = sum(
        army_strength(rules, {k: n}, Terrain.FOREST, attacking=True)
        for k, n in {P: 4, A: 3, C: 3}.items()
    )
    assert mixed > plain


def test_guns_knock_forts_down(state: GameState) -> None:
    assert siege_levels(state.rules, {P: 9, G: 1}) == 1
    assert siege_levels(state.rules, {P: 8, G: 2}) == 2
    assert siege_levels(state.rules, {P: 10}) == 0
    walls = defense_multiplier(state, "bavaria", "vienna")
    breached = defense_multiplier(state, "bavaria", "vienna", siege=1)
    assert breached < walls


def test_the_survivors_keep_their_kinds(state: GameState, play: Play) -> None:
    state.provinces["paris"].set_army({P: 0, A: 0, C: 20, G: 0})
    new = play(state, france=[Attack(origin="paris", target="flanders", regiments=20)])
    flanders = new.provinces["flanders"]
    assert flanders.owner == "france"
    assert flanders.army()[C] == flanders.troops > 0


# ---------------------------------------------------------------- great works


def test_a_great_work_stands_once_in_a_realm(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    state.nations["france"].technology[TechBranch.ECONOMY] = 3
    new = play(
        state,
        france=[
            Build(province="paris", building=BuildingKind.ROYAL_EXCHANGE),
            Build(province="lyon", building=BuildingKind.ROYAL_EXCHANGE),
        ],
    )
    assert reasons(new) == ["your realm already has a royal exchange: there can be only one"]
    assert nation_income(new, "france").ducats > nation_income(state, "france").ducats


def test_the_observatory_cheapens_learning(state: GameState) -> None:
    before = research_cost(
        state.rules, TechBranch.ECONOMY, 1, modifiers(state, "france").research_discount
    )
    state.provinces["lyon"].buildings.append(BuildingKind.OBSERVATORY)
    after = research_cost(
        state.rules, TechBranch.ECONOMY, 1, modifiers(state, "france").research_discount
    )
    assert before is not None
    assert after is not None
    assert after.ducats < before.ducats


def test_a_military_academy_trains_one_more_and_better_general(
    state: GameState, play: Play
) -> None:
    base = modifiers(state, "france").max_generals
    state.provinces["lyon"].buildings.append(BuildingKind.MILITARY_ACADEMY)
    assert modifiers(state, "france").max_generals == base + 1
    state.nations["france"].resources = RICH
    new = play(state, france=[HireGeneral(province="lyon")])
    assert new.general_in("lyon").skill >= 2  # type: ignore[union-attr]


# ---------------------------------------------------------------- monuments


def test_monuments_stand_where_history_put_them(state: GameState) -> None:
    assert state.provinces["constantinople"].monument == 3  # Hagia Sophia
    assert state.provinces["madrid"].monument == 0  # El Escorial is still a hillside
    view = view_for(state, "france")
    paris = next(p for p in view.provinces if p.id == "paris")
    assert paris.monument == 2
    assert any("Notre-Dame" in line for line in view.me.modifiers.sources)


def test_raising_a_monument_costs_more_each_level(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    before = state.nations["france"].resources.ducats
    new = play(state, france=[UpgradeMonument(province="paris")])
    assert new.provinces["paris"].monument == 3
    assert EventKind.MONUMENT_RAISED in [e.kind for e in new.last_events]
    spent = before - new.nations["france"].resources.ducats + nation_income(state, "france").ducats
    assert spent >= state.rules.monument_cost.ducats * 3 - 50  # minus pay and salaries
    top = play(new, france=[UpgradeMonument(province="paris")])
    assert reasons(top) == ["Notre-Dame de Paris is already at its greatest"]
    none = play(state, france=[UpgradeMonument(province="lyon")])
    assert reasons(none) == ["Lyon has no monument"]


def test_a_monument_serves_whoever_holds_it(state: GameState, play: Play) -> None:
    war = play(state, spain=[DeclareWar(target="france")])
    paris_bonus = modifiers(war, "france").research_discount
    war.provinces["paris"].owner = "spain"
    assert modifiers(war, "spain").research_discount >= paris_bonus
    assert modifiers(war, "france").research_discount < paris_bonus


def test_an_empty_choice_of_regiments_is_refused(state: GameState, play: Play) -> None:
    new = play(state, france=[Attack(origin="paris", target="flanders", regiments=3, units={})])
    assert reasons(new) == ["the regiments by kind add up to 0, not 3"]
