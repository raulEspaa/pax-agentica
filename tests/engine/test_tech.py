"""The technology tree: five branches, requirements across them, and a doctrine at every level."""

from collections.abc import Callable

import pytest

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import Research
from pax_agentica.engine.mechanics import morale, siege_modifiers
from pax_agentica.engine.model import Resources, TechBranch, UnitKind
from pax_agentica.engine.realm import modifiers

type Play = Callable[..., GameState]

RICH = Resources(ducats=999, iron=99, timber=99)


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_every_level_of_every_branch_offers_a_choice(state: GameState) -> None:
    tree = state.rules.tech_tree
    assert set(tree) == set(TechBranch)
    for levels in tree.values():
        assert len(levels) == state.rules.max_tech_level
        for step in levels:
            assert len(step.options) == 2
    assert state.nations["spain"].technology[TechBranch.NAVAL] == 0


def test_a_doctrine_is_chosen_for_good_and_takes_effect(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    before = morale(state, "france")
    new = play(state, france=[Research(branch=TechBranch.MILITARY, choice=0)])  # Swiss drill
    assert new.nations["france"].technology[TechBranch.MILITARY] == 1
    assert new.nations["france"].doctrines[TechBranch.MILITARY] == [0]
    assert morale(new, "france") == pytest.approx(before + 0.05)
    other = play(state, france=[Research(branch=TechBranch.MILITARY, choice=1)])  # volleys
    power = modifiers(other, "france").battle_power - modifiers(state, "france").battle_power
    assert power > 0.04  # the level's own +5% and the doctrine's +4%
    assert view_for(new, "england").nations[1].doctrines is not None


def test_some_levels_need_another_branch_first(state: GameState, play: Play) -> None:
    me = state.nations["france"]
    me.resources = RICH
    me.technology[TechBranch.NAVAL] = 1
    new = play(state, france=[Research(branch=TechBranch.NAVAL)])
    assert "Carracks needs engineering technology 1 first" in reasons(new)
    me.technology[TechBranch.ENGINEERING] = 1
    new = play(state, france=[Research(branch=TechBranch.NAVAL)])
    assert new.nations["france"].technology[TechBranch.NAVAL] == 2


def test_doctrines_reach_the_sieges_the_ships_and_the_infamy(state: GameState) -> None:
    me = state.nations["france"]
    me.technology[TechBranch.MILITARY] = 2
    me.doctrines[TechBranch.MILITARY] = [0, 0]  # Swiss drill, siege trains
    p = state.provinces["milan"]
    p.siege_by, p.besiegers = "france", {UnitKind.INFANTRY: 10}
    assert ("siege doctrine", 1) in siege_modifiers(state, "milan")
    me.technology[TechBranch.NAVAL] = 2
    me.doctrines[TechBranch.NAVAL] = [0, 0]  # charts, shipwrights
    assert modifiers(state, "france").ship_discount == pytest.approx(0.25)
    me.technology[TechBranch.ADMINISTRATION] = 3
    assert modifiers(state, "france").infamy_relief == pytest.approx(0.20)


def test_a_realm_saved_with_three_branches_still_loads(state: GameState) -> None:
    old = state.model_dump(mode="json")
    for n in old["nations"].values():
        n["technology"] = {"military": 1, "economy": 0, "engineering": 2}
        n.pop("doctrines")
    for branch in ("naval", "administration"):
        old["rules"]["tech_tree"].pop(branch)
        old["rules"]["tech_costs"].pop(branch)
    for levels in old["rules"]["tech_tree"].values():
        for level in levels:
            for key in ("options", "effects", "requires"):
                level.pop(key)
    loaded = GameState.model_validate(old)
    assert loaded.nations["spain"].technology[TechBranch.ADMINISTRATION] == 0
    assert loaded.nations["spain"].technology[TechBranch.ENGINEERING] == 2
    assert len(loaded.rules.tech_tree[TechBranch.MILITARY][0].options) == 2
    assert TechBranch.NAVAL in loaded.rules.tech_costs
