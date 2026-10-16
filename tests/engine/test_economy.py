"""Production, upkeep and spending."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import (
    Attack,
    BoostStability,
    Build,
    Develop,
    Disband,
    Improve,
    Recruit,
)
from pax_agentica.engine.mechanics import (
    army_upkeep,
    building_slots,
    develop_cost,
    land_yield,
    manpower_cap,
    nation_income,
    province_output,
    recruit_cost,
)
from pax_agentica.engine.model import BuildingKind, Good, Terrain, UnitKind
from pax_agentica.engine.realm import modifiers

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_each_good_yields_by_its_worth(state: GameState) -> None:
    rules = state.rules
    gold = land_yield(rules, Good.GOLD, 4)
    grain = land_yield(rules, Good.GRAIN, 4)
    assert gold.ducats == 4 + 10  # gold: two and a half ducats a level
    assert grain.grain == 3 + 6  # grain: a level and a half of bread
    assert gold.ducats - 4 > grain.grain - 3  # a ducat is worth more than a sack of grain too
    # London: development 7, cloth, on plains (+2 grain)
    assert province_output(state, "london") == Resources(
        ducats=7 + 3, manpower=3, iron=1, grain=5, timber=1, goods=7
    )


def test_an_iron_province_yields_extra_iron(state: GameState) -> None:
    # Wales: development 3, iron, in the hills (+1 iron, +1 manpower)
    assert province_output(state, "wales") == Resources(
        ducats=3, manpower=2, iron=5, grain=3, timber=1
    )


def test_a_province_in_unrest_yields_nothing(state: GameState) -> None:
    state.provinces["london"].unrest = 2
    assert province_output(state, "london") == Resources()


def test_stability_scales_ducat_income(state: GameState) -> None:
    raw = sum(province_output(state, p).ducats for p in state.provinces_of("england"))
    bonus = modifiers(state, "england").ducat_income
    state.nations["england"].stability = 3
    assert nation_income(state, "england").ducats == int(raw * (1 + 0.3 + bonus))


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


def test_a_marketplace_doubles_the_town_s_ducats(state: GameState, play: Play) -> None:
    before = province_output(state, "london")  # development 7, and 3 ducats from its cloth
    new = play(state, england=[Build(province="london", building=BuildingKind.MARKETPLACE)])
    assert new.provinces["london"].buildings == [BuildingKind.MARKETPLACE]
    assert province_output(new, "london").ducats == before.ducats + 7  # the cloth is not taxed
    spent = state.rules.buildings[BuildingKind.MARKETPLACE].cost
    expected = (
        state.nations["england"].resources
        - spent
        + nation_income(new, "england")
        - army_upkeep(state.rules, state.troops_of("england"))
        - state.rules.buildings[BuildingKind.MARKETPLACE].consumes  # a bale of York's cloth sold
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
    assert develop_cost(state.rules, 6, [BuildingKind.UNIVERSITY]).ducats == 42
    assert plain.ducats == 60  # 12 + 8 a level


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
    base = province_output(state, "finland").timber  # timber, in forests
    state.provinces["finland"].buildings = [BuildingKind.LUMBER_MILL]
    assert province_output(state, "finland").timber == 2 * base


def test_the_land_shapes_what_a_province_yields(state: GameState) -> None:
    rules = state.rules
    plains = land_yield(rules, Good.GOLD, 4, Terrain.PLAINS)
    mountains = land_yield(rules, Good.GOLD, 4, Terrain.MOUNTAINS)
    assert plains.grain > mountains.grain
    assert mountains.iron > plains.iron
    assert mountains.manpower > plains.manpower
    assert land_yield(rules, Good.GOLD, 4, Terrain.MOUNTAINS).grain >= 0


def test_developing_is_dear_in_mountains_and_cheap_on_plains(state: GameState) -> None:
    rules = state.rules
    plains = develop_cost(rules, 5, terrain=Terrain.PLAINS)
    mountains = develop_cost(rules, 5, terrain=Terrain.MOUNTAINS)
    assert plains.ducats < develop_cost(rules, 5).ducats < mountains.ducats


def test_an_army_without_grain_deserts(state: GameState, play: Play) -> None:
    state.provinces["london"].troops = 60
    state.nations["england"].resources = Resources(ducats=100)
    new = play(state)
    income_grain = nation_income(state, "england").grain
    assert new.troops_of("england") == income_grain  # only what the harvest feeds stays
    assert new.nations["england"].resources.grain == 0
    assert EventKind.DESERTION in [e.kind for e in new.last_events]


def test_workings_deepen_what_a_province_is_known_for(state: GameState, play: Play) -> None:
    state.nations["austria"].resources = Resources(ducats=500, timber=100)
    before = province_output(state, "bohemia").ducats  # silver
    new = play(state, austria=[Improve(province="bohemia")])
    assert new.provinces["bohemia"].workings == 1
    assert province_output(new, "bohemia").ducats > before
    view = view_for(new, "austria")
    bohemia = next(p for p in view.provinces if p.id == "bohemia")
    assert bohemia.improve_cost == state.rules.improve_cost.times(2)


def test_an_arms_manufactory_equips_every_levy(state: GameState) -> None:
    plain = recruit_cost(state.rules, 1, kind=UnitKind.ARCHERS)
    armed = recruit_cost(state.rules, 1, kind=UnitKind.ARCHERS, arms=True)
    assert armed.goods == 0 < plain.goods
    assert armed.iron <= plain.iron
