"""A ruler's tools: the briefing and the calculators, checked against the engine itself."""

import random
from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import Attack
from pax_agentica.engine.mechanics import output_with
from pax_agentica.engine.model import BuildingKind
from pax_agentica.tools import (
    TOOL_SPECS,
    battle_odds,
    best_tactic,
    briefing,
    call_tool,
    win_chance,
    work_gain,
)

type Play = Callable[..., GameState]


def test_the_win_chance_is_exact() -> None:
    rng = random.Random(1)
    for attack, defence in ((10, 10), (10, 13), (13, 10), (5, 9), (9, 5)):
        trials = 40_000
        wins = sum(
            attack * rng.uniform(0.75, 1.25) > defence * rng.uniform(0.75, 1.25)
            for _ in range(trials)
        )
        assert abs(win_chance(attack, defence, 0.75, 1.25) - wins / trials) < 0.01


def test_battle_odds_match_the_engine(state: GameState, play: Play) -> None:
    state.provinces["aragon"].units = {}
    state.provinces["aragon"].troops = 6  # pikemen
    state.provinces["navarre"].troops = 4
    view = view_for(state, "spain")
    tactic = best_tactic(view, "aragon", "navarre")
    odds = battle_odds(view, "aragon", "navarre")
    assert odds is not None
    assert 0.05 < odds < 0.95
    wins = 0
    games = 120
    for seed in range(games):
        trial = state.model_copy(deep=True)
        trial.seed = seed
        new = play(
            trial, spain=[Attack(origin="aragon", target="navarre", regiments=6, tactic=tactic)]
        )
        battles = [e for e in new.last_events if e.kind == EventKind.BATTLE]
        wins += new.provinces["navarre"].owner == "spain" or bool(
            battles and battles[0].data.get("attacker_won")
        )
    assert abs(odds - wins / games) < 0.15


def test_hidden_garrisons_have_no_odds(state: GameState) -> None:
    view = view_for(state, "england")
    assert battle_odds(view, "london", "moscow") is None  # beyond the fog of war


def test_work_gain_agrees_with_the_engine(state: GameState) -> None:
    view = view_for(state, "france")
    develop = work_gain(view, "paris", "develop")["gain"]
    dev = state.provinces["paris"].development
    expected = output_with(state, "paris", development=dev + 1) - output_with(state, "paris")
    assert develop == {k: v for k, v in expected.amounts().items() if v}
    market = work_gain(view, "paris", "marketplace")
    assert market["gain"]["ducats"] > 0
    assert market["consumes_a_year"]["goods"] == 1
    assert "error" in work_gain(view, "paris", "stables")  # Paris has stables already


def test_the_briefing_tells_what_the_ruler_needs_and_no_more(state: GameState) -> None:
    state.nations["spain"].resources = Resources(ducats=777)
    text = briefing(view_for(state, "france"))
    assert text.startswith("# France, 1500")
    for section in ("## Your provinces", "## Missions", "## Courts", "Market"):
        assert section in text
    assert "Paris (capital)" in text
    assert "777" not in text  # Spain's treasury is Spain's business


def test_tools_answer_calls_and_explain_mistakes(state: GameState) -> None:
    view = view_for(state, "france")
    assert {spec["name"] for spec in TOOL_SPECS} == {
        "battle_odds",
        "targets",
        "work_gain",
        "market_quote",
    }
    quote = call_tool(view, "market_quote", {"resource": "iron", "amount": 10})
    assert quote["buy_for"] > quote["sell_for"]
    assert "error" in call_tool(view, "summon_dragons", {})
    assert "error" in call_tool(view, "work_gain", {"province": "atlantis", "work": "develop"})
    found = call_tool(view, "targets", {"origin": "languedoc"})["targets"]
    assert any(t["action"] == "move" for t in found)
    assert BuildingKind.MARKETPLACE.value == "marketplace"
