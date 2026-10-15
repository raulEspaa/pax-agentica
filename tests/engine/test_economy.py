"""Production, upkeep and spending."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources
from pax_agentica.engine.actions import Attack, BoostStability, Build, Develop, Disband, Recruit
from pax_agentica.engine.mechanics import (
    army_upkeep,
    building_slots,
    develop_cost,
    manpower_cap,
    nation_income,
    province_output,
    recruit_cost,
)
from pax_agentica.engine.model import BuildingKind

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_a_gold_province_yields_extra_ducats(state: GameState) -> None:
    # London: development 7, gold
    assert province_output(state, "london") == Resources(
        ducats=14, manpower=3, iron=1, grain=3, timber=1
    )


def test_an_iron_province_yields_extra_iron(state: GameState) -> None:
    # Wales: development 3, iron
    assert province_output(state, "wales") == Resources(
        ducats=3, manpower=1, iron=4, grain=3, timber=1
    )


def test_a_province_in_unrest_yields_nothing(state: GameState) -> None:
    state.provinces["london"].unrest = 2
    assert province_output(state, "london") == Resources()


def test_stability_scales_ducat_income(state: GameState) -> None:
    state.nations["england"].stability = 0
    base = nation_income(state, "england").ducats
    state.nations["england"].stability = 3
    assert nation_income(state, "england").ducats == int(base * 1.3)


def test_the_end_of_turn_pays_income_feeds_and_pays_the_army(state: GameState, play: Play) -> None:
    before = state.nations["england"].resources
    income = nation_income(state, "england")
    upkeep = army_upkeep(state.rules, state.troops_of("england"))  # 10 regiments
    assert upkeep == Resources(grain=10, ducats=5)
    after = play(state).nations["england"].resources
    assert after == before + income - upkeep


def test_recruiting_costs_resources_and_adds_regiments(state: GameState, play: Play) -> None:
    new = play(state, england=[Recruit(province="york", regiments=3)])
    assert new.provinces["york"].troops == state.provinces["york"].troops + 3
    spent = state.rules.recruit_cost.times(3)
    expected = state.nations["england"].resources - spent + nation_income(state, "england")
    upkeep = army_upkeep(state.rules, new.troops_of("england"))
    assert new.nations["england"].resources == expected - upkeep


def test_recruiting_more_than_you_can_afford_is_rejected(state: GameState, play: Play) -> None:
    new = play(state, england=[Recruit(province="york", regiments=100)])
    assert new.provinces["york"].troops == state.provinces["york"].troops
    assert reasons(new)
    assert reasons(new)[0].startswith("it costs")


def test_you_cannot_recruit_in_someone_elses_province(state: GameState, play: Play) -> None:
    new = play(state, england=[Recruit(province="paris", regiments=1)])
    assert reasons(new) == ["you do not own Paris"]


def test_development_raises_output_and_score(state: GameState, play: Play) -> None:
    new = play(state, england=[Develop(province="york")])
    assert new.provinces["york"].development == 5
    assert new.score("england") == state.score("england") + 1


def test_more_development_means_more_building_slots(state: GameState) -> None:
    assert building_slots(state.rules, 3) == 1
    assert building_slots(state.rules, 4) == 2
    assert building_slots(state.rules, 12) == 4


def test_a_marketplace_doubles_the_province_ducats(state: GameState, play: Play) -> None:
    before = province_output(state, "london")  # development 7, gold: 14 ducats
    new = play(state, england=[Build(province="london", building=BuildingKind.MARKETPLACE)])
    assert new.provinces["london"].buildings == [BuildingKind.MARKETPLACE]
    assert province_output(new, "london").ducats == before.ducats + 14
    spent = state.rules.buildings[BuildingKind.MARKETPLACE].cost
    expected = (
        state.nations["england"].resources
        - spent
        + nation_income(new, "england")
        - army_upkeep(state.rules, state.troops_of("england"))
    )
    assert new.nations["england"].resources == expected


def test_a_small_bonus_still_adds_one(state: GameState) -> None:
    state.provinces["york"].buildings = [BuildingKind.IRONWORKS]  # base iron 1
    assert province_output(state, "york").iron == 2


def test_slots_requirements_and_duplicates_are_enforced(state: GameState, play: Play) -> None:
    state.nations["england"].resources = Resources(
        ducats=999, manpower=99, iron=99, grain=99, timber=99
    )
    new = play(
        state,
        england=[
            Build(province="wales", building=BuildingKind.CITADEL),  # needs a fort
            Build(province="wales", building=BuildingKind.FORT),
            Build(province="wales", building=BuildingKind.FORT),  # already there
            Build(province="wales", building=BuildingKind.BARRACKS),  # wales has 1 slot
        ],
    )
    assert new.provinces["wales"].buildings == [BuildingKind.FORT]
    assert reasons(new) == [
        "a citadel needs a fort",
        "Wales already has a fort",
        "all 1 building slots of Wales are taken; develop it to 4 for another",
    ]


def test_a_university_makes_development_cheaper(state: GameState) -> None:
    plain = develop_cost(state.rules, 6)
    assert develop_cost(state.rules, 6, [BuildingKind.UNIVERSITY]).ducats == 39
    assert plain.ducats == 55


def test_an_armory_halves_the_iron_of_new_regiments(state: GameState) -> None:
    assert recruit_cost(state.rules, 4).iron == 8
    assert recruit_cost(state.rules, 4, [BuildingKind.ARMORY]).iron == 4


def test_conquerors_keep_the_buildings(state: GameState, play: Play) -> None:
    state.provinces["lisbon"].buildings = [BuildingKind.MARKETPLACE]
    state.provinces["madrid"].troops = 40
    new = play(state, spain=[Attack(origin="madrid", target="lisbon", regiments=40)])
    assert new.provinces["lisbon"].owner == "spain"
    assert new.provinces["lisbon"].buildings == [BuildingKind.MARKETPLACE]


def test_stability_can_be_bought_up_to_the_maximum(state: GameState, play: Play) -> None:
    state.nations["england"].resources = Resources(ducats=500)
    state.nations["england"].stability = 2
    new = play(state, england=[BoostStability(), BoostStability()])
    assert new.nations["england"].stability == 3
    assert reasons(new) == ["stability is already at its maximum"]


def test_the_manpower_pool_has_a_cap(state: GameState, play: Play) -> None:
    cap = manpower_cap(state, "england")
    state.nations["england"].resources = Resources(ducats=50, manpower=cap + 40, grain=50)
    assert play(state).nations["england"].resources.manpower == cap


def test_barracks_raise_the_manpower_cap(state: GameState) -> None:
    before = manpower_cap(state, "england")
    state.provinces["london"].buildings = [BuildingKind.BARRACKS]
    assert manpower_cap(state, "england") > before


def test_disbanding_sends_the_men_home(state: GameState, play: Play) -> None:
    new = play(state, england=[Disband(province="london", regiments=4)])
    assert new.provinces["london"].troops == state.provinces["london"].troops - 4
    expected = (
        state.nations["england"].resources
        + state.rules.disband_refund.times(4)
        + nation_income(state, "england")
        - army_upkeep(state.rules, new.troops_of("england"))
    )
    assert new.nations["england"].resources == expected


def test_an_unpaid_army_deserts(state: GameState, play: Play) -> None:
    state.provinces["london"].troops = 200  # pay: 50 ducats a year, income: about 23
    state.nations["england"].resources = Resources(grain=500)
    new = play(state)
    assert new.nations["england"].resources.ducats == 0
    desertion = next(e for e in new.last_events if e.kind == EventKind.DESERTION)
    assert "pay" in desertion.summary
    assert new.troops_of("england") < 204


def test_a_lumber_mill_adds_timber(state: GameState) -> None:
    state.provinces["finland"].buildings = [BuildingKind.LUMBER_MILL]
    base = 1 + state.provinces["finland"].development  # finland's good is timber
    assert province_output(state, "finland").timber == 2 * base


def test_an_army_without_grain_deserts(state: GameState, play: Play) -> None:
    state.provinces["london"].troops = 60
    state.nations["england"].resources = Resources(ducats=100)
    new = play(state)
    income_grain = nation_income(state, "england").grain
    assert new.troops_of("england") == income_grain  # only what the harvest feeds stays
    assert new.nations["england"].resources.grain == 0
    assert EventKind.DESERTION in [e.kind for e in new.last_events]
