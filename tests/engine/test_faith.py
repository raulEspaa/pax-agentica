"""Faith in the provinces: what another faith costs a ruler, and how a realm converts."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import ChooseOption, Convert
from pax_agentica.engine.mechanics import faith_penalty, province_output
from pax_agentica.engine.model import Faith, PendingEvent

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_the_peoples_of_1500_keep_their_faiths(state: GameState) -> None:
    assert state.provinces["kiev"].faith == Faith.ORTHODOX  # Ruthenians under the Polish crown
    assert state.provinces["krakow"].faith == Faith.CATHOLIC
    assert state.provinces["greece"].faith == Faith.ORTHODOX
    assert state.provinces["morocco"].faith == Faith.SUNNI


def test_a_province_of_another_faith_yields_less(state: GameState) -> None:
    assert faith_penalty(state, "kiev") == state.rules.faith_mismatch_output
    assert faith_penalty(state, "krakow") == 0
    # the Sultan's millet system halves it
    assert faith_penalty(state, "greece") == state.rules.faith_mismatch_output / 2
    before = province_output(state, "kiev")
    state.provinces["kiev"].faith = Faith.CATHOLIC
    assert province_output(state, "kiev").ducats > before.ducats


def test_preachers_convert_a_province_once_a_year(state: GameState, play: Play) -> None:
    state.nations["poland"].resources = Resources(ducats=500)
    view = view_for(state, "poland")
    kiev = next(p for p in view.provinces if p.id == "kiev")
    assert kiev.convert_cost is not None
    state.provinces["lithuania"].faith = Faith.ORTHODOX
    new = play(
        state,
        poland=[
            Convert(province="kiev"),
            Convert(province="lithuania"),
            Convert(province="krakow"),
        ],
    )
    assert new.provinces["kiev"].faith == Faith.CATHOLIC
    assert reasons(new) == [
        "your preachers can convert one province a year",
        "Kraków already shares your faith",
    ]


def test_land_of_another_faith_is_harder_to_hold(state: GameState, play: Play) -> None:
    from pax_agentica.engine.actions import Attack

    state.provinces["anatolia"].owner = None  # a Muslim minor, for the test
    state.provinces["constantinople"].troops = 60
    state.provinces["anatolia"].troops = 1
    new = play(state, ottomans=[Attack(origin="constantinople", target="anatolia", regiments=60)])
    assert new.provinces["anatolia"].unrest == state.rules.unrest_turns - 1  # same faith: no extra
    state.provinces["serbia"].owner = None
    state.provinces["serbia"].troops = 1
    state.provinces["bulgaria"].troops = 60
    taken = play(state, ottomans=[Attack(origin="bulgaria", target="serbia", regiments=60)])
    extra = state.rules.faith_conquest_unrest
    assert taken.provinces["serbia"].unrest == state.rules.unrest_turns + extra - 1


def test_a_crown_that_turns_takes_its_capital_with_it(state: GameState, play: Play) -> None:
    state.nations["england"].pending_events.append(
        PendingEvent(id=99, event="reformation", turn=state.turn)
    )
    new = play(state, england=[ChooseOption(event_id=99, option=1)])
    assert new.nations["england"].faith == Faith.PROTESTANT
    assert new.provinces["london"].faith == Faith.PROTESTANT


def test_christian_and_muslim_courts_grow_apart(state: GameState, play: Play) -> None:
    later = play(play(state))
    assert later.opinion("ottomans", "austria") < 0
    assert later.opinion("spain", "austria") > 0
