"""Missions, patronage and mercenaries: what a crown wants, and what its money can buy."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import HireMercenaries, Patronize, SetTaxes
from pax_agentica.engine.missions import MISSIONS, done, goal_text, open_missions
from pax_agentica.engine.model import BuildingKind, Treaty, TreatyKind
from pax_agentica.engine.realm import modifiers

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


# ---------------------------------------------------------------- missions


def test_every_great_power_has_five_missions_that_read_well(state: GameState) -> None:
    assert set(MISSIONS) == set(state.nations)
    for nation, chain in MISSIONS.items():
        assert len(chain) == 5
        ids = {m.id for m in chain}
        for m in chain:
            assert m.after is None or m.after in ids
            for goal in m.goals:
                assert goal_text(state, goal)
                for pid in (*goal.provinces, goal.province):
                    assert pid is None or pid in state.provinces, (nation, m.id, pid)


def test_a_mission_completes_and_pays(state: GameState, play: Play) -> None:
    state.provinces["scotland"].owner = "england"
    before = state.nations["england"].resources.ducats
    new = play(state)
    england = new.nations["england"]
    assert "union_of_crowns" in england.missions_done
    assert england.prestige >= 10
    assert england.resources.ducats > before + 50
    done_events = [e for e in new.last_events if e.kind == EventKind.MISSION_COMPLETED]
    assert done_events
    assert done_events[0].data["mission"] == "union_of_crowns"


def test_a_later_mission_waits_for_the_earlier_one(state: GameState) -> None:
    ids = [m.id for m in open_missions(state, "england")]
    assert "lordship_of_ireland" not in ids
    state.nations["england"].missions_done.append("union_of_crowns")
    assert "lordship_of_ireland" in [m.id for m in open_missions(state, "england")]


def test_the_view_shows_each_mission_and_how_far_it_has_come(state: GameState) -> None:
    view = view_for(state, "england")
    staple = next(m for m in view.me.missions if m.id == "wool_staple")
    assert staple.status == "open"
    assert [(g.have, g.need) for g in staple.goals] == [(0, 1), (0, 1)]
    assert next(m for m in view.me.missions if m.id == "lordship_of_ireland").status == "locked"


def test_an_alliance_goal(state: GameState) -> None:
    goal = next(m for m in MISSIONS["spain"] if m.id == "habsburg_match").goals[0]
    assert not done(state, "spain", goal)
    state.treaties.append(Treaty(kind=TreatyKind.ALLIANCE, parties=("austria", "spain"), since=1))
    assert done(state, "spain", goal)


def test_the_last_mission_of_a_chain_leaves_a_lasting_bonus(state: GameState) -> None:
    plain = modifiers(state, "france").ducat_income
    state.nations["france"].missions_done += ["italian_claim", "naples"]
    assert modifiers(state, "france").ducat_income > plain


def test_a_building_goal_counts_where_it_stands(state: GameState) -> None:
    goal = next(m for m in MISSIONS["austria"] if m.id == "bulwark_vienna").goals[2]
    assert not done(state, "austria", goal)
    state.provinces["vienna"].buildings.append(BuildingKind.CITADEL)
    assert done(state, "austria", goal)


# ---------------------------------------------------------------- what money buys


def test_patronage_buys_prestige_once_a_year(state: GameState, play: Play) -> None:
    state.nations["spain"].resources = Resources(ducats=500)
    prestige = state.nations["spain"].prestige
    cost = view_for(state, "spain").me.patronage_cost
    new = play(state, spain=[Patronize(), Patronize()])
    spain = new.nations["spain"]
    assert spain.prestige == prestige + state.rules.patronage_prestige - state.rules.prestige_decay
    assert reasons(new) == ["the court has already patronised the arts this year"]
    assert spain.resources.ducats < 500 - cost + 200  # paid, before the year's income
    assert view_for(new, "spain").me.patronage_cost > cost  # dearer as prestige grows


def test_mercenaries_cost_only_ducats(state: GameState, play: Play) -> None:
    state.nations["spain"].resources = Resources(ducats=500)
    troops = state.provinces["madrid"].troops
    new = play(state, spain=[HireMercenaries(province="madrid", regiments=6)])
    assert new.provinces["madrid"].troops == troops + 6
    spain = new.nations["spain"]
    assert spain.resources.manpower >= 0
    assert [e for e in new.last_events if e.kind == EventKind.MERCENARIES_HIRED]


def test_the_captains_for_hire_are_few(state: GameState, play: Play) -> None:
    state.nations["spain"].resources = Resources(ducats=1000)
    limit = state.rules.mercenary_limit
    new = play(
        state,
        spain=[
            HireMercenaries(province="madrid", regiments=limit),
            HireMercenaries(province="madrid", regiments=1),
        ],
    )
    assert reasons(new) == ["only 0 more mercenary regiments are for hire this year"]


# ---------------------------------------------------------------- taxes and the ledger


def test_taxes_trade_men_and_content_for_ducats(state: GameState, play: Play) -> None:
    normal = view_for(state, "france").me.income_per_turn
    taxed = play(state, france=[SetTaxes(level=2)])
    assert taxed.nations["france"].tax == 2
    high = view_for(taxed, "france").me
    assert high.income_per_turn.ducats > normal.ducats
    assert high.income_per_turn.manpower < normal.manpower
    assert (
        modifiers(taxed, "france").stability_discount
        < modifiers(state, "france").stability_discount
    )


def test_very_high_taxes_wear_stability_down(state: GameState, play: Play) -> None:
    state.nations["france"].tax = 2
    state.nations["france"].stability = 3
    for _ in range(12):
        state = play(state)
    assert state.nations["france"].stability < 3


def test_the_ledger_adds_up_to_the_year(state: GameState) -> None:
    state.provinces["paris"].buildings.append(BuildingKind.MARKETPLACE)
    state.provinces["paris"].workings = 1
    me = view_for(state, "france").me
    income = {k: 0 for k in me.income_per_turn.amounts()}
    expense = dict(income)
    for line in me.ledger:
        side = income if line.kind == "income" else expense
        for k, v in line.amount.items():
            side[k] += v
    assert income == me.income_per_turn.amounts()
    assert {s.source for s in me.ledger} >= {"land", "buildings", "workings", "the army"}
    assert expense["grain"] >= me.army_upkeep_per_turn.grain
