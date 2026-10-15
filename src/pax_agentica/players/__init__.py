"""Players: anything that can look at a `NationView` and return `Orders`.

Rule-based bots live here. The AI rulers (in `pax_agentica.agents`, from milestone 2) implement
the same `Player` protocol, so the runner, the CLI and the tournaments never need to know which
kind of mind sits on a throne.
"""

from typing import Protocol

from pax_agentica.engine import NationView, Orders


class Player(Protocol):
    """A ruler. `decide` is async so that slow players (LLMs) can think in parallel."""

    @property
    def name(self) -> str:
        """A short label for logs, e.g. 'greedy' or 'gemini-flash'."""
        ...

    async def decide(self, view: NationView) -> Orders: ...
