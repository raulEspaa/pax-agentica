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

    def __init__(
        self, langfuse: "Langfuse | None" = None, session: str = "", public_key: str | None = None
    ) -> None:
        self._langfuse = langfuse
        self._session = session
        self._public_key = public_key  # names the client to callbacks that look it up

    @classmethod
    def from_env(cls, session: str = "") -> "Tracer":
        """A tracer to the project whose keys are in the environment, or one that does nothing."""
        if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
            return cls(session=session)
        from langfuse import Langfuse  # only now: the multiplayer tables go without the SDK

        # It reads the keys and the address itself, sends in batches in the background, and sends
        # what is left when the program exits.
        return cls(Langfuse(), session, os.environ["LANGFUSE_PUBLIC_KEY"])

    @property
    def on(self) -> bool:
        return self._langfuse is not None

    @property
    def langfuse(self) -> "Langfuse | None":
        """The client, for what goes beyond traces: datasets, experiments, scores."""
        return self._langfuse

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
    def council(self, view: NationView) -> Iterator[dict[str, Any]]:
        """The root of a trace for one year of a LangGraph council, and the run's config.

        Langfuse's LangChain callback turns each node into a span, but does not make it the
        current OpenTelemetry span, so the model calls inside a node would start traces of their
        own. Opening the root here, around the run, keeps the nodes and the calls in one trace."""
        if self._langfuse is None:
            yield {}
            return
        from langfuse import propagate_attributes
        from langfuse.langchain import CallbackHandler

        nation = view.me.id
        with (
            self._langfuse.start_as_current_observation(name="council", as_type="agent"),
            propagate_attributes(
                trace_name=f"council {nation} {view.year}",
                session_id=self._session or None,
                version=PROMPT_VERSION,
                tags=[nation, "council"],
                metadata={"nation": nation, "year": view.year, "turn": view.turn},
            ),
        ):
            yield {"callbacks": [CallbackHandler(public_key=self._public_key)]}

    @contextmanager
    def call(
        self, model: str, request: PlanRequest, parameters: Mapping[str, str | int]
    ) -> Iterator[Step]:
        """One call to a model, inside the plan it belongs to."""
        messages = [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.user},
        ]
        with self.generation("gemini", model, messages, parameters) as step:
            yield step

    @contextmanager
    def generation(
        self,
        name: str,
        model: str,
        messages: list[dict[str, Any]],
        parameters: Mapping[str, str | int],
    ) -> Iterator[Step]:
        """One call to a model, inside whatever step is current."""
        if self._langfuse is None:
            yield _Nothing()
            return
        with self._langfuse.start_as_current_observation(
            name=name,
            as_type="generation",
            model=model,
            model_parameters=dict(parameters),
            input=messages,
        ) as step:
            yield step

    @contextmanager
    def archivist(self, question: str, session: str, version: str) -> Iterator[Step]:
        """The root of a trace: one question to the Archivist. A conversation is a session."""
        if self._langfuse is None:
            yield _Nothing()
            return
        from langfuse import propagate_attributes

        with (
            self._langfuse.start_as_current_observation(
                name="archivist", as_type="agent", input={"question": question}
            ) as step,
            propagate_attributes(
                trace_name="archivist",
                session_id=session,
                version=version,
                tags=["archivist"],
            ),
        ):
            yield step
