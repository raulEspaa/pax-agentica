"""The dynasty: heirs and their tutors, regencies, and the claims of a failed line."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import EducateHeir, PressClaim
from pax_agentica.engine.model import Resources, Treaty, TreatyKind, pair

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def dying(state: GameState, nation: str) -> None:
    ruler = state.nations[nation].ruler
    assert ruler is not None
    ruler.age = 200  # death is certain


def test_every_crown_starts_with_an_heir(state: GameState) -> None:
    for nation in state.nations.values():
        assert nation.heir is not None
    assert view_for(state, "france").me.heir is not None


def test_the_heir_takes_the_throne(state: GameState, play: Play) -> None:
    heir = state.nations["france"].heir
    assert heir is not None
    heir.age = 25
    dying(state, "france")
    new = play(state)
    ruler = new.nations["france"].ruler
    assert ruler is not None
    assert ruler.name == heir.name
    assert not new.nations["france"].regency


def test_a_child_reigns_under_a_regency(state: GameState, play: Play) -> None:
    heir = state.nations["france"].heir
    assert heir is not None
    heir.age = 8
    dying(state, "france")
    stability = state.nations["france"].stability
    new = play(state)
    assert new.nations["france"].regency
    assert new.nations["france"].stability <= stability - 2  # a new reign, and a regency
    authority = new.nations["france"].authority
    after = play(new)
    assert after.nations["france"].authority - authority < 9  # half the pace


def test_a_failed_line_gives_a_claim_to_the_crowns_married_into_it(
    state: GameState, play: Play
) -> None:
    state.nations["france"].heir = None
    state.treaties.append(
        Treaty(kind=TreatyKind.MARRIAGE, parties=pair("france", "spain"), since=1)
    )
    dying(state, "france")
    state.rules = state.rules.model_copy(update={"heir_birth_chance": 0.0})
    new = play(state)
    assert "france" in new.nations["spain"].claims
    assert any(e.data.get("crisis") for e in new.last_events if e.kind == EventKind.SUCCESSION)
    pressed = play(new, spain=[PressClaim(nation="france", press=True)])
    assert pressed.at_war("spain", "france")
    assert "france" not in pressed.nations["spain"].claims


def test_tutors_teach_the_heir(state: GameState, play: Play) -> None:
    me = state.nations["france"]
    me.authority, me.resources = 50, Resources(ducats=200)
    heir = me.heir
    assert heir is not None
    before = heir.diplomacy
    new = play(state, france=[EducateHeir(skill="diplomacy")])
    taught = new.nations["france"].heir
    assert taught is not None
    assert taught.diplomacy == min(6, before + 1)
    twice = play(state, france=[EducateHeir(skill="diplomacy"), EducateHeir(skill="military")])
    assert "the heir has tutors enough this year" in reasons(twice)
