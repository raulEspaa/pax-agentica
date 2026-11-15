"""Shared fixtures. `play` resolves one turn from keyword orders: play(state, france=[...]).

`tracer` and `spans`: Langfuse with its traces kept in memory (the real SDK, no server, no network).
"""

import json
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from pax_agentica.agents.tracing import Tracer
from pax_agentica.engine import Action, GameState, Orders, new_game, resolve_turn

type Play = Callable[..., GameState]


@pytest.fixture
def state() -> GameState:
    """A fresh game whose rulers are young and middling, where fortune sends no events and the
    courts start with no feelings, so no death, plague or old grudge surprises a test."""
    game = new_game(seed=7)
    game.rules = game.rules.model_copy(update={"event_chance": 0.0})  # fortune only on request
    game.opinions = {}  # the scenario's grudges of 1500 are tested on their own
    for nation in game.nations.values():
        assert nation.ruler is not None
        nation.ruler.age = 20
        nation.ruler.administration = nation.ruler.diplomacy = nation.ruler.military = 3
    return game


@pytest.fixture
def play() -> Play:
    def _play(state: GameState, **orders: list[Action]) -> GameState:
        return resolve_turn(state, {n: Orders(actions=a) for n, a in orders.items()})

    return _play


@pytest.fixture
def _langfuse() -> Iterator[tuple[Langfuse, InMemorySpanExporter, str]]:
    exporter = InMemorySpanExporter()
    key = f"pk-test-{uuid.uuid4()}"
    langfuse = Langfuse(
        public_key=key,  # the SDK keeps one client per key
        secret_key="sk-test",  # noqa: S106 - a test key, never sent
        base_url="http://127.0.0.1:9",  # nothing listens there, and nothing is sent to it
        span_exporter=exporter,
        tracer_provider=TracerProvider(),
    )
    yield langfuse, exporter, key
    langfuse.shutdown()


@pytest.fixture
def tracer(_langfuse: tuple[Langfuse, InMemorySpanExporter, str]) -> Tracer:
    return Tracer(_langfuse[0], session="test-seed1", public_key=_langfuse[2])


@pytest.fixture
def spans(
    _langfuse: tuple[Langfuse, InMemorySpanExporter, str],
) -> Callable[[], list[ReadableSpan]]:
    """Every span finished so far, oldest first."""
    langfuse, exporter, _ = _langfuse

    def finished() -> list[ReadableSpan]:
        langfuse.flush()
        return list(exporter.get_finished_spans())

    return finished


# ---------------------------------------------------------------- analytics (spec 009)

SCHEMAS = Path(__file__).parent.parent / "scripts" / "bigquery"


def _schema(kind: str) -> list[dict[str, Any]]:
    return json.loads((SCHEMAS / f"{kind}.json").read_text())  # type: ignore[no-any-return]


def _fits_scalar(value: Any, kind: str) -> bool:
    if value is None:
        return True
    match kind:
        case "STRING":
            return isinstance(value, str)
        case "INTEGER":
            return isinstance(value, int) and not isinstance(value, bool)
        case "FLOAT":
            return isinstance(value, int | float) and not isinstance(value, bool)
        case "BOOLEAN":
            return isinstance(value, bool)
        case "TIMESTAMP":
            return isinstance(value, str) and datetime.fromisoformat(value).tzinfo is not None
    raise AssertionError(f"a type the test does not know: {kind}")


def _check_row(row: dict[str, Any], fields: list[dict[str, Any]], where: str = "") -> None:
    """Every key of the row is declared, with a type BigQuery's JSON loader accepts."""
    declared = {f["name"]: f for f in fields}
    assert "dt" not in row, "dt is the partition column: it lives in the path, not the row"
    for key, value in row.items():
        assert key in declared, f"{where}{key} is not in the schema"
        field = declared[key]
        values = value if field.get("mode") == "REPEATED" else [value]
        if field.get("mode") == "REPEATED":
            assert isinstance(value, list), f"{where}{key} should be a list"
        for item in values:
            if field["type"] == "RECORD":
                assert isinstance(item, dict), f"{where}{key} should be an object"
                _check_row(item, field["fields"], f"{where}{key}.")
            else:
                assert _fits_scalar(item, field["type"]), f"{where}{key}={item!r}: {field['type']}"


def _rows_in(root: Path, kind: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for path in sorted((root / kind).glob("dt=*/*.ndjson"))
        for line in path.read_text().splitlines()
    ]


type FitsSchema = Callable[[dict[str, Any], str], None]
type NdjsonRows = Callable[[Path, str], list[dict[str, Any]]]


@pytest.fixture
def fits_schema() -> FitsSchema:
    """Assert that an analytics row fits scripts/bigquery/<kind>.json: every key declared, with a
    type BigQuery's JSON loader accepts."""
    return lambda row, kind: _check_row(row, _schema(kind))


@pytest.fixture
def ndjson_rows() -> NdjsonRows:
    """Every row of a kind written under an analytics root, file by file."""
    return _rows_in
