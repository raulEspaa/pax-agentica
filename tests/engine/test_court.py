"""The character of rulers, declared friends and rivals, proclamations and private thoughts."""

import asyncio
from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Orders, new_game, view_for
from pax_agentica.engine.actions import Proclaim, SetStance
from pax_agentica.engine.model import AdvisorRole, Stance, Trait
from pax_agentica.engine.realm import advisor_candidates, modifiers
from pax_agentica.runner import play_turn

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


# ---------------------------------------------------------------- character


def test_rulers_have_the_character_history_gave_them() -> None:
    game = new_game(seed=1)
    suleiman_line = game.nations["ottomans"].ruler
    assert suleiman_line is not None
    assert suleiman_line.traits == [Trait.PIOUS, Trait.BUILDER]  # Bayezid II
    assert game.nations["france"].ruler.traits == [Trait.THRIFTY, Trait.CHARMING]  # type: ignore[union-attr]


def test_a_trait_moves_the_numbers(state: GameState) -> None:
    ruler = state.nations["france"].ruler
    assert ruler is not None
    ruler.traits = []
    plain = modifiers(state, "france")
    ruler.traits = [Trait.WARLIKE, Trait.SCHOLAR]
    shaped = modifiers(state, "france")
    assert shaped.battle_power > plain.battle_power
    assert shaped.research_discount > plain.research_discount
    assert any("warlike" in line for line in shaped.sources)


def test_a_charming_ruler_wins_hearts_every_year(state: GameState, play: Play) -> None:
    state.nations["france"].ruler.traits = [Trait.CHARMING]  # type: ignore[union-attr]
    later = play(state)
    assert later.opinion("spain", "france") > 0


def test_advisors_have_a_temper(state: GameState) -> None:
    tempers = {c.personality for c in advisor_candidates(state, "france")}
    assert tempers
    view = view_for(state, "france")
    assert all(c.personality for c in view.me.advisor_candidates)
    assert {c.role for c in view.me.advisor_candidates} == set(AdvisorRole)


# ---------------------------------------------------------------- stances


def test_a_stance_is_public_and_moves_opinion(state: GameState, play: Play) -> None:
    new = play(state, spain=[SetStance(target="france", stance=Stance.RIVAL)])
    assert EventKind.STANCE_CHANGED in [e.kind for e in new.last_events]
    england = view_for(new, "england")
    spain = next(n for n in england.nations if n.id == "spain")
    assert spain.stances == {"france": Stance.RIVAL}
    assert new.opinion("france", "spain") < 0


def test_rivals_are_limited_and_neutral_undoes(state: GameState, play: Play) -> None:
    rivals = [SetStance(target=n, stance=Stance.RIVAL) for n in ("france", "austria", "england")]
    new = play(state, spain=[*rivals, SetStance(target="sweden", stance=Stance.RIVAL)])
    assert reasons(new) == ["you already have 3 rivals"]
    calm = play(new, spain=[SetStance(target="france", stance=Stance.NEUTRAL)])
    assert "france" not in calm.nations["spain"].stances


# ---------------------------------------------------------------- words


def test_a_proclamation_reaches_every_court(state: GameState, play: Play) -> None:
    new = play(state, spain=[Proclaim(text="Navarre is ours by right.")])
    for nation in ("france", "russia"):
        heard = [
            e for e in view_for(new, nation).last_turn_events if e.kind == EventKind.PROCLAMATION
        ]
        assert heard
        assert heard[0].data["text"] == "Navarre is ours by right."


def test_thoughts_and_counsel_are_kept_but_never_shown(state: GameState) -> None:
    class Thinker:
        name = "thinker"

        async def decide(self, view: object) -> Orders:
            return Orders(
                thoughts="Spain grows; befriend England.",
                counsel={AdvisorRole.MARSHAL: "Fortify Gascony."},
            )

    _new, record = asyncio.run(play_turn(state, {"france": Thinker()}))
    assert record.orders["france"].thoughts == "Spain grows; befriend England."
    assert record.orders["france"].counsel[AdvisorRole.MARSHAL] == "Fortify Gascony."
    assert "befriend England" not in view_for(_new, "spain").model_dump_json()


def test_some_powers_carry_a_tradition(state: GameState) -> None:
    from pax_agentica.engine.mechanics import defense_multiplier

    assert modifiers(state, "brandenburg").battle_power > modifiers(state, "poland").battle_power
    assert modifiers(state, "england").navy
    assert not modifiers(state, "france").navy
    state.provinces["london"].owner = "england"
    # the Channel favours Normandy's defenders against France's fleetless levies, not England's
    state.provinces["brittany"].owner = "england"
    assert state.map.is_sea_crossing("london", "normandy")
    by_sea = defense_multiplier(state, "london", "normandy")
    by_land = defense_multiplier(state, "brittany", "normandy")
    assert by_sea == by_land
