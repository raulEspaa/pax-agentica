"""Technology and generals."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import (
    AssignGeneral,
    Attack,
    Build,
    DeclareWar,
    HireGeneral,
    Move,
    Research,
)
from pax_agentica.engine.mechanics import (
    battle_factor,
    building_cost,
    nation_income,
    research_cost,
)
from pax_agentica.engine.model import BuildingKind, TechBranch

type Play = Callable[..., GameState]

RICH = Resources(ducats=2000, manpower=200, iron=200, grain=500, timber=500)


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_research_raises_a_branch_once_a_year(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    new = play(
        state, france=[Research(branch=TechBranch.MILITARY), Research(branch=TechBranch.ECONOMY)]
    )
    assert new.nations["france"].technology[TechBranch.MILITARY] == 1
    assert new.nations["france"].technology[TechBranch.ECONOMY] == 0
    assert reasons(new) == ["you can research only once a year"]


def test_some_buildings_need_technology(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    locked = play(state, france=[Build(province="paris", building=BuildingKind.ARMORY)])
    assert reasons(locked) == ["an armory needs military technology 1"]
    state.nations["france"].technology[TechBranch.MILITARY] = 1
    built = play(state, france=[Build(province="paris", building=BuildingKind.ARMORY)])
    assert BuildingKind.ARMORY in built.provinces["paris"].buildings


def test_economy_technology_raises_income(state: GameState) -> None:
    before = nation_income(state, "france")
    state.nations["france"].technology[TechBranch.ECONOMY] = 2
    after = nation_income(state, "france")
    assert after.ducats > before.ducats
    assert after.grain > before.grain


def test_engineering_makes_building_cheaper(state: GameState) -> None:
    plain = building_cost(state.rules, BuildingKind.MARKETPLACE)
    skilled = building_cost(state.rules, BuildingKind.MARKETPLACE, discount=0.24)
    assert skilled.ducats < plain.ducats
    assert skilled.timber < plain.timber


def test_military_technology_and_generals_strengthen_armies(state: GameState) -> None:
    assert battle_factor(state, "france", general_skill=3) > battle_factor(state, "france")
    state.nations["france"].technology[TechBranch.MILITARY] = 2
    assert battle_factor(state, "france") > battle_factor(state, "spain")
    assert battle_factor(state, None) == 1.0  # independent levies


def test_every_nation_starts_with_a_general_in_its_capital(state: GameState) -> None:
    for nation in state.nations.values():
        (general,) = state.generals_of(nation.id)
        assert general.province == nation.capital
        assert general.skill == 2


def test_hiring_generals_costs_ducats_and_has_a_limit(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    new = play(
        state,
        france=[
            HireGeneral(province="lyon"),
            HireGeneral(province="normandy"),
            HireGeneral(province="brittany"),
            HireGeneral(province="gascony"),
        ],
    )
    assert len(new.generals_of("france")) == state.rules.max_generals
    assert reasons(new) == [f"you already have {state.rules.max_generals} generals"]
    assert all(1 <= g.skill <= 3 for g in new.generals_of("france"))


def test_a_general_can_be_sent_anywhere_in_the_realm(state: GameState, play: Play) -> None:
    (general,) = state.generals_of("france")
    new = play(state, france=[AssignGeneral(general=general.id, province="languedoc")])
    assert new.general(general.id).province == "languedoc"  # type: ignore[union-attr]


def test_a_general_marches_and_conquers_with_his_regiments(state: GameState, play: Play) -> None:
    (general,) = state.generals_of("spain")
    state.provinces["madrid"].troops = 40
    moved = play(
        state, spain=[Move(origin="madrid", target="aragon", regiments=30, general=general.id)]
    )
    assert moved.general(general.id).province == "aragon"  # type: ignore[union-attr]
    war = play(moved, spain=[DeclareWar(target="france")])
    war.provinces["languedoc"].troops = 1
    won = play(
        war, spain=[Attack(origin="aragon", target="languedoc", regiments=30, general=general.id)]
    )
    assert won.provinces["languedoc"].owner == "spain"
    assert won.general(general.id).province == "languedoc"  # type: ignore[union-attr]


def test_a_general_falls_with_his_province(state: GameState, play: Play) -> None:
    (french,) = state.generals_of("france")
    war = play(state, spain=[DeclareWar(target="france")])
    war.provinces["gascony"].troops = 1
    war.provinces["aragon"].troops = 60
    war.generals[[g.id for g in war.generals].index(french.id)].province = "gascony"
    new = play(war, spain=[Attack(origin="aragon", target="gascony", regiments=60)])
    assert new.general(french.id) is None
    assert EventKind.GENERAL_FELL in [e.kind for e in new.last_events]


def test_a_general_must_be_where_his_order_starts(state: GameState, play: Play) -> None:
    (general,) = state.generals_of("spain")
    new = play(
        state, spain=[Move(origin="galicia", target="madrid", regiments=1, general=general.id)]
    )
    assert reasons(new) == [f"{general.name} is not in Galicia"]


def test_you_see_your_generals_and_only_the_enemies_in_sight(state: GameState) -> None:
    view = view_for(state, "france")
    assert [g.nation for g in view.me.generals] == ["france"]
    paris = next(p for p in view.provinces if p.id == "paris")
    moscow = next(p for p in view.provinces if p.id == "moscow")
    assert paris.general is not None
    assert moscow.general is None  # Moscow is behind the fog
    assert next(n for n in view.nations if n.id == "russia").generals == 1


def test_each_level_of_learning_costs_half_a_step_more(state: GameState) -> None:
    base = state.rules.tech_costs[TechBranch.ECONOMY].ducats
    costs = [research_cost(state.rules, TechBranch.ECONOMY, level) for level in range(6)]
    assert [c.ducats for c in costs if c] == [base, base * 1.5, base * 2, base * 2.5, base * 3]
    assert costs[5] is None  # the top of the tree
