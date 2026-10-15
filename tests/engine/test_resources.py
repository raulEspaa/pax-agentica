import pytest
from pydantic import ValidationError

from pax_agentica.engine import Resources


def test_resources_add_subtract_and_multiply() -> None:
    a = Resources(ducats=10, iron=2)
    b = Resources(ducats=3, grain=5)
    assert a + b == Resources(ducats=13, iron=2, grain=5)
    assert a - Resources(ducats=4) == Resources(ducats=6, iron=2)
    assert b.times(3) == Resources(ducats=9, grain=15)


def test_resources_can_never_go_negative() -> None:
    with pytest.raises(ValidationError):
        Resources(ducats=1) - Resources(ducats=2)
    with pytest.raises(ValidationError):
        Resources(iron=-1)


def test_covers_checks_every_resource() -> None:
    purse = Resources(ducats=10, manpower=1)
    assert purse.covers(Resources(ducats=10))
    assert not purse.covers(Resources(ducats=5, iron=1))


def test_resources_read_like_a_sentence() -> None:
    assert str(Resources(ducats=5, iron=2)) == "5 ducats, 2 iron"
    assert str(Resources()) == "nothing"
