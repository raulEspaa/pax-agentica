"""A plan is only a proposal: what names nothing real is dropped, and the rest stands."""

import pytest

from pax_agentica.agents.checks import clean_plan
from pax_agentica.engine import NationView, new_game, view_for
from pax_agentica.players.plan import Plan


@pytest.fixture
def france() -> NationView:
    return view_for(new_game(seed=1), "france")


def test_a_sound_plan_passes_untouched(france: NationView) -> None:
    plan = Plan(
        army="conquer",
        conquer=["flanders", "milan"],
        war_on="spain",
        peace_with=["england"],
        befriend=["austria"],
        note="Flanders, then Milan.",
    )

    assert clean_plan(plan, france) == (plan, [])


def test_drops_provinces_that_do_not_exist_and_keeps_the_rest(france: NationView) -> None:
    cleaned, dropped = clean_plan(Plan(economy="grow", conquer=["atlantis", "flanders"]), france)

    assert cleaned.conquer == ["flanders"]
    assert cleaned.economy == "grow"
    assert dropped == ["conquer atlantis"]


def test_drops_courts_that_do_not_exist(france: NationView) -> None:
    plan = Plan(war_on="narnia", peace_with=["gondor", "spain"], befriend=["mordor", "austria"])

    cleaned, dropped = clean_plan(plan, france)

    assert cleaned.war_on is None
    assert cleaned.peace_with == ["spain"]
    assert cleaned.befriend == ["austria"]
    assert dropped == ["war_on narnia", "peace_with gondor", "befriend mordor"]


def test_the_realm_cannot_be_its_own_enemy_nor_its_own_friend(france: NationView) -> None:
    plan = Plan(war_on="france", peace_with=["france"], befriend=["france"])

    cleaned, dropped = clean_plan(plan, france)

    assert (cleaned.war_on, cleaned.peace_with, cleaned.befriend) == (None, [], [])
    assert dropped == ["war_on france", "peace_with france", "befriend france"]


def test_a_court_gone_from_the_map_is_gone_from_the_plan(france: NationView) -> None:
    fallen = tuple(
        n.model_copy(update={"alive": False}) if n.id == "spain" else n for n in france.nations
    )
    view = france.model_copy(update={"nations": fallen})

    cleaned, dropped = clean_plan(Plan(war_on="spain"), view)

    assert cleaned.war_on is None
    assert dropped == ["war_on spain"]
