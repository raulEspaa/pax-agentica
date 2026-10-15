"""The crown, its council and the milestones of the tree of learning."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import Build, DismissAdvisor, HireAdvisor
from pax_agentica.engine.mechanics import (
    building_output,
    defense_multiplier,
    nation_income,
    nation_upkeep,
    research_cost,
)
from pax_agentica.engine.model import AdvisorRole, BuildingKind, TechBranch
from pax_agentica.engine.realm import (
    advisor_candidates,
    advisor_hire_cost,
    death_chance,
    modifiers,
)

type Play = Callable[..., GameState]

RICH = Resources(ducats=2000, manpower=200, iron=200, grain=500, timber=500)


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def kinds(state: GameState) -> list[EventKind]:
    return [e.kind for e in state.last_events]


# ---------------------------------------------------------------- the ruler


def test_every_nation_starts_with_a_ruler_of_its_historical_line(state: GameState) -> None:
    france = state.nations["france"].ruler
    assert france is not None
    assert (france.title, france.name, france.reign) == ("King", "Louis XII", 0)
    for nation in state.nations.values():
        assert nation.ruler is not None
        assert 1 <= nation.ruler.administration <= 6


def test_a_better_ruler_brings_more_ducats(state: GameState) -> None:
    before = nation_income(state, "france").ducats
    state.nations["france"].ruler.administration = 6  # type: ignore[union-attr]
    assert nation_income(state, "france").ducats > before


def test_young_rulers_never_die_and_old_ones_may(state: GameState) -> None:
    ruler = state.nations["france"].ruler
    assert ruler is not None
    assert death_chance(ruler) == 0
    ruler.age = 70
    assert death_chance(ruler) > 0.3


def test_an_old_ruler_dies_and_his_heir_takes_the_throne(state: GameState, play: Play) -> None:
    old = state.nations["france"].ruler
    assert old is not None
    old.age = 200  # certain death
    stability = state.nations["france"].stability
    new = play(state)
    heir = new.nations["france"].ruler
    assert heir is not None
    assert (heir.name, heir.reign) == ("Francis I", 1)
    assert new.nations["france"].stability == stability - 1
    assert EventKind.SUCCESSION in kinds(new)


# ---------------------------------------------------------------- the council


def candidate(state: GameState, role: AdvisorRole) -> int:
    return next(c.id for c in advisor_candidates(state, "france") if c.role == role)


def test_two_candidates_seek_each_seat(state: GameState) -> None:
    pool = advisor_candidates(state, "france")
    assert sorted(c.role for c in pool) == sorted(list(AdvisorRole) * 2)
    assert pool == advisor_candidates(state, "france")  # seeded: the same for everyone


def test_hiring_an_advisor_costs_ducats_and_fills_the_seat(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    hired = next(c for c in advisor_candidates(state, "france") if c.role == AdvisorRole.TREASURER)
    new = play(state, france=[HireAdvisor(candidate=hired.id)])
    assert new.nations["france"].advisors[AdvisorRole.TREASURER].name == hired.name
    assert EventKind.ADVISOR_HIRED in kinds(new)
    assert advisor_hire_cost(state.rules, hired) == state.rules.advisor_hire_ducats * hired.skill


def test_unknown_candidates_are_refused(state: GameState, play: Play) -> None:
    new = play(state, france=[HireAdvisor(candidate=999_999)])
    assert reasons(new) == ["no candidate #999999 seeks a place at your court"]


def test_each_seat_has_its_power(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    plain = modifiers(state, "france")
    new = play(
        state,
        france=[
            HireAdvisor(candidate=candidate(state, role))
            for role in (AdvisorRole.TREASURER, AdvisorRole.CHANCELLOR, AdvisorRole.MARSHAL)
        ],
    )
    council = modifiers(new, "france")
    assert council.ducat_income > plain.ducat_income
    assert council.battle_power > plain.battle_power
    assert council.research_discount > 0
    cheap = research_cost(new.rules, TechBranch.ECONOMY, 1, council.research_discount)
    full = research_cost(new.rules, TechBranch.ECONOMY, 1)
    assert cheap is not None
    assert full is not None
    assert cheap.ducats < full.ducats
    assert len(council.sources) > len(plain.sources)


def test_advisors_draw_a_salary_and_leave_unpaid(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    hired = play(state, france=[HireAdvisor(candidate=candidate(state, AdvisorRole.MARSHAL))])
    with_council = nation_upkeep(hired, "france").ducats
    assert with_council > nation_upkeep(state, "france").ducats
    hired.rules = hired.rules.model_copy(update={"advisor_salary_ducats": 10_000})
    hired.nations["france"].resources = Resources()
    broke = play(hired)
    assert broke.nations["france"].advisors == {}
    assert EventKind.ADVISOR_LEFT in kinds(broke)


def test_an_advisor_can_be_dismissed(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    hired = play(state, france=[HireAdvisor(candidate=candidate(state, AdvisorRole.MARSHAL))])
    gone = play(hired, france=[DismissAdvisor(role=AdvisorRole.MARSHAL)])
    assert AdvisorRole.MARSHAL not in gone.nations["france"].advisors
    again = play(gone, france=[DismissAdvisor(role=AdvisorRole.MARSHAL)])
    assert reasons(again) == ["you have no marshal"]


def test_you_see_your_council_and_who_would_join_it(state: GameState) -> None:
    view = view_for(state, "france")
    assert view.me.ruler is not None
    assert len(view.me.advisor_candidates) == 2 * len(AdvisorRole)
    assert all(c.hire_cost > 0 and c.salary > 0 for c in view.me.advisor_candidates)


# ---------------------------------------------------------------- milestones


def reach(state: GameState, branch: TechBranch, level: int) -> None:
    state.nations["france"].technology[branch] = level


def test_banking_unlocks_a_bank_that_pays(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    locked = play(state, france=[Build(province="paris", building=BuildingKind.BANK)])
    assert reasons(locked) == ["a bank needs economy technology 1"]
    reach(state, TechBranch.ECONOMY, 1)
    built = play(state, france=[Build(province="paris", building=BuildingKind.BANK)])
    assert building_output(built, "paris").ducats > building_output(state, "paris").ducats


def test_cameralism_adds_a_building_slot(state: GameState) -> None:
    assert modifiers(state, "france").extra_building_slots == 0
    reach(state, TechBranch.ECONOMY, 5)
    assert modifiers(state, "france").extra_building_slots == 1


def test_mercantilism_and_water_mills_raise_the_share_of_trade_buildings(
    state: GameState,
) -> None:
    plain = modifiers(state, "france")
    reach(state, TechBranch.ECONOMY, 3)
    reach(state, TechBranch.ENGINEERING, 2)
    rich = modifiers(state, "france")
    assert rich.marketplace_share > plain.marketplace_share
    assert rich.mill_share > plain.mill_share


def test_roads_and_canals_feed_the_army_for_less(state: GameState) -> None:
    state.provinces["paris"].troops = 40
    before = nation_upkeep(state, "france").grain
    reach(state, TechBranch.ENGINEERING, 3)
    assert nation_upkeep(state, "france").grain < before


def test_grand_architecture_raises_the_development_ceiling(state: GameState) -> None:
    plain = modifiers(state, "france").max_development
    reach(state, TechBranch.ENGINEERING, 5)
    assert modifiers(state, "france").max_development == plain + 3


def test_star_forts_and_field_artillery_change_sieges(state: GameState) -> None:
    state.provinces["languedoc"].buildings.append(BuildingKind.FORT)
    plain = defense_multiplier(state, "aragon", "languedoc")
    reach(state, TechBranch.ENGINEERING, 4)  # France's forts hold better
    assert defense_multiplier(state, "aragon", "languedoc") > plain
    state.nations["spain"].technology[TechBranch.MILITARY] = 4  # Spain's guns ignore one level
    assert defense_multiplier(state, "aragon", "languedoc") < plain


def test_military_revolution_allows_a_fourth_general(state: GameState) -> None:
    reach(state, TechBranch.MILITARY, 5)
    assert modifiers(state, "france").max_generals == state.rules.max_generals + 1
