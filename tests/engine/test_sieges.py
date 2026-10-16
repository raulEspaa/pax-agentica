"""Sieges: an army camps before the walls, and every year a die says how far it gets."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import Attack, DeclareWar, LiftSiege, Move, Recruit
from pax_agentica.engine.mechanics import army_of, siege_modifiers, siege_result
from pax_agentica.engine.model import UnitKind

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def besieged(state: GameState, play: Play, regiments: int = 30) -> GameState:
    """France at war with Austria lays siege to Vienna (a fort) from Bavaria."""
    war = play(state, france=[DeclareWar(target="austria")])
    war.provinces["bavaria"].owner, war.provinces["bavaria"].troops = "france", regiments
    war.provinces["vienna"].troops = 0
    return play(war, france=[Attack(origin="bavaria", target="vienna", regiments=regiments)])


def test_an_army_digs_in_before_the_walls(state: GameState, play: Play) -> None:
    siege = besieged(state, play)
    vienna = siege.provinces["vienna"]
    assert vienna.holder == "austria"
    assert vienna.siege_by == "france"
    assert siege.provinces["bavaria"].troops == 0  # the army stays in the siege lines
    assert 0 < sum(vienna.besiegers.values()) <= 30
    assert vienna.siege_years == 1
    assert 10 <= vienna.siege_progress < 100
    kinds = [e.data for e in siege.last_events if e.kind == EventKind.SIEGE]
    assert kinds[0]["started"] is True
    assert "rolled" in next(e.summary for e in siege.last_events if "rolled" in e.summary)
    # the besiegers still count, and still eat
    assert army_of(siege, "france")[UnitKind.INFANTRY] >= sum(vienna.besiegers.values())
    view = view_for(siege, "austria")
    seen = next(p for p in view.provinces if p.id == "vienna")
    assert seen.siege_progress == vienna.siege_progress
    assert seen.besiegers == sum(vienna.besiegers.values())
    assert ("walls", -1) in seen.siege_modifiers


def test_the_walls_fall_at_a_hundred(state: GameState, play: Play) -> None:
    siege = besieged(state, play)
    siege.provinces["vienna"].siege_progress = 95  # every roll buys at least 10
    fallen = play(siege)
    assert fallen.provinces["vienna"].controller == "france"
    assert fallen.provinces["vienna"].troops > 0
    assert fallen.provinces["vienna"].siege_by is None


def test_the_modifiers_add_up(state: GameState, play: Play) -> None:
    siege = besieged(state, play, regiments=3)  # too few for a ring round one wall
    vienna = siege.provinces["vienna"]
    vienna.siege_years = 2
    vienna.besiegers = {UnitKind.INFANTRY: 3, UnitKind.ARTILLERY: 0}
    mods = dict(siege_modifiers(siege, "vienna"))
    assert mods["walls"] == -1
    assert mods["the garrison starves"] == 2
    assert mods["too few to close the ring"] == -2
    assert mods["a capital's defenders"] == -1
    assert "cannon" not in mods
    rules = siege.rules
    assert siege_result(rules, -5)[0] == rules.siege_results[0][1]
    assert siege_result(rules, 9) == (100, "a breach in the walls")


def test_a_relief_army_breaks_the_siege(state: GameState, play: Play) -> None:
    siege = besieged(state, play, regiments=5)
    near = next(
        p
        for p in siege.map.all_neighbors("vienna")
        if siege.provinces[p].holder == "austria" and p != "vienna"
    )
    siege.provinces[near].troops = 80
    relieved = play(siege, austria=[Attack(origin=near, target="vienna", regiments=80)])
    vienna = relieved.provinces["vienna"]
    assert vienna.siege_by is None
    assert vienna.troops > 0  # the relief army marches into the town it saved
    battle = next(e for e in relieved.last_events if e.kind == EventKind.BATTLE)
    assert battle.data["attacker"] == "austria"
    assert battle.data["then"] == "the siege is broken"


def test_no_march_or_levy_into_a_besieged_town(state: GameState, play: Play) -> None:
    siege = besieged(state, play)
    near = next(
        p
        for p in siege.map.all_neighbors("vienna")
        if siege.provinces[p].holder == "austria" and p != "vienna"
    )
    siege.provinces[near].troops = 10
    new = play(
        siege,
        austria=[
            Move(origin=near, target="vienna", regiments=5),
            Recruit(province="vienna", regiments=2),
        ],
    )
    assert any("besieged by France" in r for r in reasons(new))
    assert len(reasons(new)) == 2


def test_lifting_a_siege_brings_the_army_home(state: GameState, play: Play) -> None:
    siege = besieged(state, play)
    lines = sum(siege.provinces["vienna"].besiegers.values())
    home = play(siege, france=[LiftSiege(province="vienna")])
    assert home.provinces["vienna"].siege_by is None
    assert home.provinces["bavaria"].troops == lines
    assert reasons(play(home, france=[LiftSiege(province="vienna")])) == [
        "you are not besieging it"
    ]


def test_reinforcements_join_the_lines(state: GameState, play: Play) -> None:
    siege = besieged(state, play)
    before = sum(siege.provinces["vienna"].besiegers.values())
    siege.provinces["bavaria"].troops = 10
    siege.provinces["vienna"].siege_progress = 0
    more = play(siege, france=[Attack(origin="bavaria", target="vienna", regiments=10)])
    vienna = more.provinces["vienna"]
    if vienna.siege_by == "france":  # unless the dice took the town meanwhile
        assert sum(vienna.besiegers.values()) >= before + 10 - 4
    assert more.provinces["bavaria"].troops == 0


def test_peace_sends_the_besiegers_home(state: GameState, play: Play) -> None:
    siege = besieged(state, play)
    siege.wars = []  # a peace, signed somewhere
    calm = play(siege)
    assert calm.provinces["vienna"].siege_by is None
    assert calm.provinces["bavaria"].troops > 0


def test_walls_fight_for_whoever_holds_them(state: GameState) -> None:
    from pax_agentica.engine.mechanics import defense_multiplier

    held = defense_multiplier(state, "bavaria", "vienna")  # Austria's own capital, with a fort
    state.provinces["vienna"].controller = "france"  # France has taken it
    taken = defense_multiplier(state, "bavaria", "vienna")
    assert taken < held  # the occupiers have the walls, but not the capital's defenders


def test_an_unpaid_fort_stands_unmanned(state: GameState) -> None:
    from pax_agentica.engine.model import BuildingKind

    vienna = state.provinces["vienna"]
    assert vienna.fort == 1
    vienna.idle = [BuildingKind.FORT]  # its garrison went unpaid last year
    assert vienna.fort == 0
