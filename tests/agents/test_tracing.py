"""Each plan is one trace in Langfuse, and without keys there is no tracing at all (criterion 9)."""

import asyncio
import json
from collections.abc import Callable

import pytest
from opentelemetry.sdk.trace import ReadableSpan

from pax_agentica.agents.prompts import PROMPT_VERSION, PlanRequest
from pax_agentica.agents.strategist import Strategist
from pax_agentica.agents.tracing import Tracer
from pax_agentica.engine import NationView, new_game, view_for
from pax_agentica.players.plan import Plan

type Spans = Callable[[], list[ReadableSpan]]  # the `spans` fixture, in conftest.py

PLAN = Plan(economy="grow", army="build_up", note="Grow.")


class TracedModel:
    """A fake model that traces its calls as the Gemini client does, and fails when told to."""

    def __init__(self, tracer: Tracer, failures: int = 0) -> None:
        self.tracer = tracer
        self.failures = failures

    async def write_plan(self, request: PlanRequest) -> Plan:
        with self.tracer.call("fake", request, {"thinking_level": "low"}) as step:
            if self.failures:
                self.failures -= 1
                raise ConnectionError("the model is down")
            step.update(usage_details={"input": 10, "output": 5}, cost_details={"total": 0.001})
            return PLAN


@pytest.fixture
def france() -> NationView:
    return view_for(new_game(seed=1), "france")


def named(spans: list[ReadableSpan], name: str) -> list[ReadableSpan]:
    return [s for s in spans if s.name == name]


def attribute(span: ReadableSpan, key: str) -> object:
    assert span.attributes is not None
    return span.attributes.get(key)


def test_without_keys_there_is_no_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    assert not Tracer.from_env().on


def test_a_traced_ruler_plays_exactly_as_one_without(
    tracer: Tracer, spans: Spans, france: NationView
) -> None:
    traced = asyncio.run(Strategist(TracedModel(tracer), seed=1, tracer=tracer).decide(france))
    plain = asyncio.run(Strategist(TracedModel(Tracer()), seed=1).decide(france))

    assert traced == plain
    assert spans()  # and only the traced one reported anything


def test_a_plan_is_one_trace_with_the_nation_the_year_and_the_prompt_version(
    tracer: Tracer, spans: Spans, france: NationView
) -> None:
    asyncio.run(Strategist(TracedModel(tracer), seed=1, tracer=tracer).decide(france))

    done = spans()
    [plan], [call] = named(done, "plan"), named(done, "gemini")
    assert call.context.trace_id == plan.context.trace_id
    assert call.parent is not None
    assert call.parent.span_id == plan.context.span_id
    for span in (plan, call):
        assert attribute(span, "langfuse.trace.name") == "plan france 1500"
        assert attribute(span, "session.id") == "test-seed1"
        assert attribute(span, "langfuse.version") == PROMPT_VERSION
        assert attribute(span, "langfuse.trace.metadata.nation") == '"france"'
        assert attribute(span, "langfuse.trace.metadata.year") == "1500"


def test_the_plan_says_why_it_was_asked_for_and_what_came_back(
    tracer: Tracer, spans: Spans, france: NationView
) -> None:
    asyncio.run(Strategist(TracedModel(tracer), seed=1, tracer=tracer).decide(france))

    [plan] = named(spans(), "plan")
    assert json.loads(str(attribute(plan, "langfuse.observation.input"))) == {"why": "no plan yet"}
    output = json.loads(str(attribute(plan, "langfuse.observation.output")))
    assert output["plan"]["note"] == "Grow."
    assert output["dropped"] == []


def test_the_call_carries_the_prompt_the_model_the_tokens_and_the_cost(
    tracer: Tracer, spans: Spans, france: NationView
) -> None:
    asyncio.run(Strategist(TracedModel(tracer), seed=1, tracer=tracer).decide(france))

    [call] = named(spans(), "gemini")
    assert attribute(call, "langfuse.observation.type") == "generation"
    assert attribute(call, "langfuse.observation.model.name") == "fake"
    prompt = json.loads(str(attribute(call, "langfuse.observation.input")))
    assert [m["role"] for m in prompt] == ["system", "user"]
    assert attribute(call, "langfuse.observation.usage_details") == '{"input": 10, "output": 5}'
    assert attribute(call, "langfuse.observation.cost_details") == '{"total": 0.001}'


def test_a_retry_is_a_second_call_in_the_same_trace_and_a_warning(
    tracer: Tracer, spans: Spans, france: NationView
) -> None:
    model = TracedModel(tracer, failures=1)
    asyncio.run(Strategist(model, seed=1, tracer=tracer).decide(france))

    done = spans()
    [plan], calls = named(done, "plan"), named(done, "gemini")
    assert len(calls) == 2
    assert {c.context.trace_id for c in calls} == {plan.context.trace_id}
    assert attribute(plan, "langfuse.observation.level") == "WARNING"
    assert "ConnectionError" in str(attribute(plan, "langfuse.observation.status_message"))


def test_a_year_without_a_plan_is_an_error(
    tracer: Tracer, spans: Spans, france: NationView
) -> None:
    model = TracedModel(tracer, failures=2)
    asyncio.run(Strategist(model, seed=1, tracer=tracer).decide(france))

    [plan] = named(spans(), "plan")
    assert attribute(plan, "langfuse.observation.level") == "ERROR"
    assert "No new plan this year" in str(attribute(plan, "langfuse.observation.status_message"))


def test_a_year_that_needs_no_new_plan_sends_nothing(
    tracer: Tracer, spans: Spans, france: NationView
) -> None:
    ruler = Strategist(TracedModel(tracer), seed=1, tracer=tracer)
    asyncio.run(ruler.decide(france))
    before = len(spans())

    asyncio.run(ruler.decide(france.model_copy(update={"turn": 2})))

    assert len(spans()) == before
