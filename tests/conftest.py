"""Shared fixtures. `play` resolves one turn from keyword orders: play(state, france=[...]).

`tracer` and `spans`: Langfuse with its traces kept in memory (the real SDK, no server, no network).
"""

import uuid
from collections.abc import Callable, Iterator

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
