"""The Gemini client, with the real SDK talking to a local server: no key, no network, no cost."""

import asyncio
import json
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any

import pytest
from google.genai import Client
from opentelemetry.sdk.trace import ReadableSpan
from pydantic import ValidationError

from pax_agentica.agents import gemini
from pax_agentica.agents.budget import Budget, BudgetExceeded
from pax_agentica.agents.gemini import DEFAULT_MODEL, GeminiModel, IncompleteAnswer, Price
from pax_agentica.agents.prompts import PlanRequest
from pax_agentica.agents.strategist import Strategist
from pax_agentica.agents.tracing import Tracer
from pax_agentica.cli import main
from pax_agentica.engine import new_game, view_for
from pax_agentica.players.plan import Plan

REQUEST = PlanRequest(system="You are a king.", user="The report.")
PRICE = gemini.PRICES[DEFAULT_MODEL]
NEW_CLIENT = gemini.new_client  # the real one, for when a test replaces it


class Stub:
    """A local stand-in for the Gemini API: answers as told and remembers what it received."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.status = 200
        self.reply: dict[str, Any] = answer('{"economy": "grow", "note": "Grow."}')
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                size = int(self.headers["content-length"])
                stub.bodies.append(json.loads(self.rfile.read(size)))
                out = json.dumps(stub.reply).encode()
                self.send_response(stub.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        Thread(target=self.server.serve_forever, daemon=True).start()

    def client(self) -> Client:
        return NEW_CLIENT(f"http://127.0.0.1:{self.server.server_port}")


def answer(text: str, status: str = "completed") -> dict[str, Any]:
    return {
        "id": "v1_x",
        "status": status,
        "model": DEFAULT_MODEL,
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}],
        "usage": {
            "total_tokens": 1600,
            "total_input_tokens": 1000,
            "total_output_tokens": 100,
            "total_thought_tokens": 500,
        },
    }


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stub]:
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    server = Stub()
    yield server
    server.server.shutdown()


def ask(stub: Stub, budget: Budget) -> Plan:
    return asyncio.run(GeminiModel(stub.client(), budget).write_plan(REQUEST))


def test_returns_the_plan_the_model_wrote(stub: Stub) -> None:
    assert ask(stub, Budget(1.0)) == Plan(economy="grow", note="Grow.")


def test_sends_who_and_what_and_the_schema_and_asks_not_to_be_stored(stub: Stub) -> None:
    ask(stub, Budget(1.0))

    body = stub.bodies[0]
    assert body["model"] == DEFAULT_MODEL
    assert body["system_instruction"] == REQUEST.system
    assert body["input"] == REQUEST.user
    assert body["store"] is False
    assert body["response_format"]["schema"] == Plan.model_json_schema()
    assert body["generation_config"]["thinking_level"] == "low"
    assert body["generation_config"]["max_output_tokens"] == gemini.MAX_OUTPUT_TOKENS


def test_charges_what_the_call_really_cost_counting_the_thinking(stub: Stub) -> None:
    budget = Budget(1.0)

    ask(stub, budget)

    expected = (1000 * PRICE.input_per_million + 600 * PRICE.output_per_million) / 1_000_000
    assert budget.spent_usd == pytest.approx(expected)
    assert budget.committed_usd == pytest.approx(expected)


def test_a_call_the_budget_cannot_cover_never_leaves_the_machine(stub: Stub) -> None:
    with pytest.raises(BudgetExceeded):
        ask(stub, Budget(0.000001))

    assert stub.bodies == []


def test_an_answer_that_is_not_a_plan_is_an_error_and_is_still_charged(stub: Stub) -> None:
    stub.reply = answer('{"army": "raze"}')
    budget = Budget(1.0)

    with pytest.raises(ValidationError):
        ask(stub, budget)

    assert budget.spent_usd > 0


def test_an_answer_cut_short_is_an_error(stub: Stub) -> None:
    stub.reply = answer('{"economy": "gr', status="incomplete")

    with pytest.raises(IncompleteAnswer):
        ask(stub, Budget(1.0))


def test_when_the_cost_is_unknown_the_worst_is_assumed(stub: Stub) -> None:
    stub.status = 400
    stub.reply = {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}}
    budget = Budget(1.0)

    with pytest.raises(Exception, match="bad request"):
        ask(stub, budget)

    assert budget.spent_usd == pytest.approx(gemini.worst_cost(REQUEST, PRICE))


def test_the_sdk_sends_twice_at_most_as_the_worst_cost_assumes(stub: Stub) -> None:
    """If an upgrade of the SDK retries more, the budget would no longer hold: this must fail."""
    stub.status = 500
    stub.reply = {"error": {"code": 500, "message": "down", "status": "INTERNAL"}}
    budget = Budget(1.0)

    with pytest.raises(Exception, match="down"):
        ask(stub, budget)

    assert len(stub.bodies) == 2
    assert budget.spent_usd == pytest.approx(gemini.worst_cost(REQUEST, PRICE))


def test_the_trace_counts_the_thinking_and_prices_it_as_output(
    stub: Stub, tracer: Tracer, spans: Callable[[], list[ReadableSpan]]
) -> None:
    asyncio.run(GeminiModel(stub.client(), Budget(1.0), tracer=tracer).write_plan(REQUEST))

    [call] = spans()
    attributes = call.attributes or {}
    tokens = json.loads(str(attributes["langfuse.observation.usage_details"]))
    costs = json.loads(str(attributes["langfuse.observation.cost_details"]))
    assert tokens == {"input": 1000, "output": 100, "output_reasoning": 500}
    assert costs["output_reasoning"] == pytest.approx(500 * PRICE.output_per_million / 1_000_000)
    assert attributes["langfuse.observation.model.name"] == DEFAULT_MODEL


def test_a_failed_call_is_an_error_in_its_trace_and_costs_the_worst(
    stub: Stub, tracer: Tracer, spans: Callable[[], list[ReadableSpan]]
) -> None:
    stub.status = 400
    stub.reply = {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}}

    with pytest.raises(Exception, match="bad request"):
        asyncio.run(GeminiModel(stub.client(), Budget(1.0), tracer=tracer).write_plan(REQUEST))

    [call] = spans()
    attributes = call.attributes or {}
    assert attributes["langfuse.observation.level"] == "ERROR"
    costs = json.loads(str(attributes["langfuse.observation.cost_details"]))
    assert costs == {"total": pytest.approx(gemini.worst_cost(REQUEST, PRICE))}


def test_no_more_calls_start_in_a_minute_than_allowed(
    stub: Stub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gemini, "_WINDOW_SECONDS", 0.3)  # a short minute, for the test
    model = GeminiModel(stub.client(), Budget(1.0), calls_per_minute=2)

    async def three() -> list[float]:
        loop = asyncio.get_running_loop()
        start = loop.time()

        async def one() -> float:
            await model.write_plan(REQUEST)
            return loop.time() - start

        return sorted(await asyncio.gather(one(), one(), one()))

    _, second, third = asyncio.run(three())

    assert second < 0.3  # two at once
    assert third >= 0.3  # the third waits for the window


def test_a_model_without_a_known_price_is_refused(stub: Stub) -> None:
    with pytest.raises(ValueError, match="no price"):
        GeminiModel(stub.client(), Budget(1.0), model="gemini-unheard-of")


def test_every_price_is_per_million_tokens() -> None:
    assert Price(1.0, 2.0).cost(input_tokens=1_000_000, output_tokens=500_000) == pytest.approx(2.0)


def test_a_spent_budget_leaves_the_last_plan_standing_and_the_game_going(stub: Stub) -> None:
    budget = Budget(gemini.worst_cost(REQUEST, PRICE) * 0.5)
    view = view_for(new_game(seed=1), "france")

    orders = asyncio.run(Strategist(GeminiModel(stub.client(), budget), seed=1).decide(view))

    assert stub.bodies == []
    assert "BudgetExceeded" in orders.thoughts


def test_a_tournament_shares_one_budget_across_its_games(
    stub: Stub, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(gemini, "new_client", stub.client)

    both = "--player france=strategist --player spain=strategist"
    code = main(f"tournament --games 2 --turns 3 {both} --budget 1".split())

    assert code == 0
    assert len(stub.bodies) >= 4  # two crowns, two games
    assert "spent $" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["tournament --games 1 --turns 1", "play --turns 1"])
def test_no_model_is_called_without_a_budget(command: str) -> None:
    with pytest.raises(SystemExit, match="--budget"):
        main([*command.split(), "--player", "france=strategist"])
