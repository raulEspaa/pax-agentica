"""The Gemini client: a `PlanModel` that asks Google's models for a plan, and keeps to a budget.

It uses the Interactions API of `google-genai`, with the plan's schema as structured output. Only
this module knows about the provider, and nothing imports it unless a model is really wanted, so
that the game can run without the SDK installed.
"""

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import cast

from google import genai
from google.genai.interactions import Interaction, Usage
from google.genai.types import HttpOptions, HttpRetryOptions
from pydantic import BaseModel

from pax_agentica.agents.budget import Budget
from pax_agentica.agents.diplomat import Diplomacy
from pax_agentica.agents.prompts import PlanRequest
from pax_agentica.agents.tracing import Step, Tracer
from pax_agentica.players.plan import Plan


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens. Thinking is billed as output."""

    input_per_million: float
    output_per_million: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        billed = input_tokens * self.input_per_million + output_tokens * self.output_per_million
        return billed / 1_000_000


# Paid tier, standard, from ai.google.dev/gemini-api/docs/pricing on 2026-11-01. Update by hand:
# gemini-3.8-flash doubles on 2027-01-01, and gemini-3.1-flash-lite shuts down on 2027-05-07.
PRICES = {
    "gemini-3.1-flash-lite": Price(0.25, 1.50),
    "gemini-3.5-flash-lite": Price(0.30, 2.50),
    "gemini-3.8-flash": Price(0.75, 3.75),
}
DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_THINKING = "low"

# A hard stop on the answer, thinking included. A plan needs under 200 tokens: the rest is thinking.
MAX_OUTPUT_TOKENS = 4096
MAX_CONCURRENT_CALLS = 4
# The free tier allows 15 requests a minute per model, and the SDK's hidden retry is one more:
# 12 calls in any minute leaves room for it. The first real evaluations lost 6 calls of 60 to 429s.
CALLS_PER_MINUTE = 12
_WINDOW_SECONDS = 60.0
_SENDS_PER_CALL = 2  # see new_client
_CHARACTERS_PER_TOKEN_AT_LEAST = 2  # tokens run nearer 4 characters: this errs on the safe side


class IncompleteAnswer(Exception):
    """The model stopped before finishing, usually for running out of output tokens."""


def new_client(base_url: str | None = None) -> genai.Client:
    """A client with the key in GEMINI_API_KEY, or another server's address for the tests.

    The Interactions API reads `attempts` as retries, and turns 0 into 1, so this is the fewest
    there can be: one send and one retry (a test holds the SDK to it). `worst_cost` counts both."""
    one_retry = HttpRetryOptions(attempts=1)
    return genai.Client(http_options=HttpOptions(base_url=base_url, retry_options=one_retry))


def worst_cost(request: PlanRequest, price: Price, schema: type[BaseModel] = Plan) -> float:
    """The most a call can cost, before it is made: both sends, each with its longest answer."""
    characters = len(request.system) + len(request.user) + len(str(schema.model_json_schema()))
    input_tokens = characters // _CHARACTERS_PER_TOKEN_AT_LEAST
    return _SENDS_PER_CALL * price.cost(input_tokens, MAX_OUTPUT_TOKENS)


class GeminiModel:
    """Writes plans and letters with a Gemini model. Make one per game: its limits belong to an
    event loop, and they are shared by every crown and every kind of answer."""

    def __init__(
        self,
        client: genai.Client,
        budget: Budget,
        model: str = DEFAULT_MODEL,
        thinking: str = DEFAULT_THINKING,
        tracer: Tracer | None = None,
        calls_per_minute: int = CALLS_PER_MINUTE,
    ) -> None:
        if model not in PRICES:
            raise ValueError(f"no price for {model!r}: add it to PRICES first")
        self._client = client
        self._tracer = tracer or Tracer()
        self._budget = budget
        self._model = model
        self._price = PRICES[model]
        self._thinking = thinking
        self._slots = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
        self._calls_per_minute = calls_per_minute
        self._recent: deque[float] = deque()  # when the calls of the last minute started
        self._pacing = asyncio.Lock()

    async def _wait_for_a_turn(self) -> None:
        """Wait until fewer than `calls_per_minute` calls started in the last minute.

        A window and not a fixed gap: nine crowns asking at once in the first year go at once."""
        async with self._pacing:
            loop = asyncio.get_running_loop()
            while len(self._recent) >= self._calls_per_minute:
                wait = self._recent[0] + _WINDOW_SECONDS - loop.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._recent.popleft()
            self._recent.append(loop.time())

    async def write_plan(self, request: PlanRequest) -> Plan:
        return await self.write(request, Plan)

    async def write_diplomacy(self, request: PlanRequest) -> Diplomacy:
        return await self.write(request, Diplomacy)

    async def write[T: BaseModel](self, request: PlanRequest, schema: type[T]) -> T:
        """An answer in the shape of `schema`, which the provider is asked to keep to."""
        settings: dict[str, str | int] = {
            "thinking_level": self._thinking,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        }
        async with self._slots:
            await self._wait_for_a_turn()
            worst = worst_cost(request, self._price, schema)
            self._budget.reserve(worst)
            with self._tracer.call(self._model, request, settings) as step:
                spent = worst  # a call that fails or is cancelled may still have been billed
                try:
                    answer = await self._client.aio.interactions.create(
                        model=self._model,
                        input=request.user,
                        system_instruction=request.system,
                        store=False,
                        response_format={
                            "type": "text",
                            "mime_type": "application/json",
                            "schema": schema.model_json_schema(),
                        },
                        generation_config=settings,
                    )
                    interaction = cast(Interaction, answer)  # a stream only if we ask for one
                    step.update(
                        output=interaction.output_text, metadata={"status": interaction.status}
                    )
                    usage = interaction.usage
                    if usage is not None:
                        spent = self._charge(step, usage)
                except BaseException as exc:  # a timeout cancels the call: it fails here too
                    step.update(level="ERROR", status_message=f"{type(exc).__name__} {exc}"[:300])
                    raise
                finally:
                    self._budget.settle(worst, spent)
                    if spent == worst:
                        step.update(
                            cost_details={"total": worst}, metadata={"cost": "worst assumed"}
                        )
        if interaction.status != "completed":
            raise IncompleteAnswer(f"the model's answer ended as {interaction.status}")
        return schema.model_validate_json(interaction.output_text or "")

    def _charge(self, step: Step, usage: Usage) -> float:
        """The cost of a call from its tokens, also written into its trace. Returns the cost."""
        tokens = {
            "input": usage.total_input_tokens or 0,
            "output": usage.total_output_tokens or 0,
            "output_reasoning": usage.total_thought_tokens or 0,  # billed as output
        }
        costs = {
            "input": self._price.cost(tokens["input"], 0),
            "output": self._price.cost(0, tokens["output"]),
            "output_reasoning": self._price.cost(0, tokens["output_reasoning"]),
        }
        step.update(usage_details=tokens, cost_details=costs)
        return sum(costs.values())
