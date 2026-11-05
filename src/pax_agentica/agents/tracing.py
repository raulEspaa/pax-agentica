"""Tracing to Langfuse: one trace for each plan a crown asks for, with each call to the model in it.

    plan france 1502                    the trace: nation, year, prompt version, session
    └── plan        (agent)             why it was asked, the plan that came back, what was dropped
        ├── gemini  (generation)        the prompt, the answer, the model, tokens and cost
        └── gemini  (generation)        the retry, if the first try failed

Without LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY nothing is sent and the SDK is never imported,
so a game plays the same with tracing or without it (spec 002, criterion 9). Langfuse is built on
OpenTelemetry: the calls find their plan through the context of the asyncio task, without being
handed it, and each crown's task keeps its own.
"""

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Protocol

from pax_agentica.agents.prompts import PROMPT_VERSION, PlanRequest
from pax_agentica.engine import NationView

if TYPE_CHECKING:
    from langfuse import Langfuse


class Step(Protocol):
    """What can be said about a step once it is under way: a Langfuse observation, or nothing."""

    def update(self, **fields: Any) -> object: ...


class _Nothing:
    def update(self, **fields: Any) -> object:
        return self


class Tracer:
    """Sends traces to one Langfuse project, or does nothing at all when it has none.

    `session` groups the traces of one game, so a game can be read in Langfuse as a whole."""

    def __init__(self, langfuse: "Langfuse | None" = None, session: str = "") -> None:
        self._langfuse = langfuse
        self._session = session

    @classmethod
    def from_env(cls, session: str = "") -> "Tracer":
        """A tracer to the project whose keys are in the environment, or one that does nothing."""
        if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
            return cls(session=session)
        from langfuse import Langfuse  # only now: the multiplayer tables go without the SDK

        # It reads the keys and the address itself, sends in batches in the background, and sends
        # what is left when the program exits.
        return cls(Langfuse(), session)

    @property
    def on(self) -> bool:
        return self._langfuse is not None

    @contextmanager
    def plan(self, view: NationView, why: str) -> Iterator[Step]:
        """The root of a trace: one crown asking for one plan."""
        if self._langfuse is None:
            yield _Nothing()
            return
        from langfuse import propagate_attributes

        nation = view.me.id
        with (
            self._langfuse.start_as_current_observation(
                name="plan", as_type="agent", input={"why": why}
            ) as step,
            propagate_attributes(
                trace_name=f"plan {nation} {view.year}",
                session_id=self._session or None,
                version=PROMPT_VERSION,
                tags=[nation],
                metadata={"nation": nation, "year": view.year, "turn": view.turn},
            ),
        ):
            yield step

    @contextmanager
    def call(
        self, model: str, request: PlanRequest, parameters: Mapping[str, str | int]
    ) -> Iterator[Step]:
        """One call to a model, inside the plan it belongs to."""
        if self._langfuse is None:
            yield _Nothing()
            return
        with self._langfuse.start_as_current_observation(
            name="gemini",
            as_type="generation",
            model=model,
            model_parameters=dict(parameters),
            input=[
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
        ) as step:
            yield step
