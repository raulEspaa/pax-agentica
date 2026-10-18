"""The chart of the New World the page draws: every region on it, with its sea road."""

from pax_agentica.engine.model import Region
from pax_agentica.viewer import atlantic_chart


def test_every_region_lies_on_the_chart_with_a_road_from_europe() -> None:
    chart = atlantic_chart()
    w, h = chart["width"], chart["height"]
    assert set(chart["regions"]) == {r.value for r in Region}
    assert set(chart["routes"]) == {r.value for r in Region}
    for region, (x, y) in chart["regions"].items():
        assert 0 <= x <= w
        assert 0 <= y <= h
        road = chart["routes"][region]
        assert road[0] == chart["home"]
        assert road[-1] == [x, y]
    assert chart["land"].startswith("M")
