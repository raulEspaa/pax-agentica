"""What one decision cost, when many are being made at once.

At the public tables every council spends from one daily budget, and several think at the same
time, so "what the budget spent between the start and the end of a decision" would mix their
calls. Instead each decision opens a `Meter` in a context variable. asyncio gives every task a
copy of the context it was started from, so the meter follows the decision into the tasks it
starts (LangGraph's nodes) and into no one else's; `Budget.settle`, where the real cost of every
call becomes known, adds it to the meter of whoever made the call.

    with metered() as meter:
        orders = await council.decide(view)
    meter.cost_usd, meter.calls
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

TIMEOUTS = frozenset({"CancelledError", "TimeoutError"})  # how a node's timeout shows itself


@dataclass
class Meter:
    """The calls made, and what they cost, inside one `metered()` block."""

    cost_usd: float = 0.0
    calls: int = 0  # model calls settled by the budget, each try counted
    asked: set[str] = field(default_factory=set)  # "plan", "diplomacy": what was asked for
    written: set[str] = field(default_factory=set)  # and what came back
    letters: int = 0  # letters the diplomat wrote
    failures: list[str] = field(default_factory=list)  # "plan:TimeoutError", one per failed try

    def charge(self, usd: float) -> None:
        self.cost_usd += usd
        self.calls += 1

    @property
    def timed_out(self) -> bool:
        return any(f.split(":", 1)[-1] in TIMEOUTS for f in self.failures)

    @property
    def fallback(self) -> bool:
        """Something was asked for and never came: the last plan, or the bot, stood in."""
        return bool(self.asked - self.written)


_current: ContextVar[Meter | None] = ContextVar("pax_meter", default=None)


def current() -> Meter | None:
    """The meter of the decision this code runs in, if it is measured."""
    return _current.get()


@contextmanager
def metered() -> Iterator[Meter]:
    """Measure the model calls made inside this block (and the tasks it starts)."""
    meter = Meter()
    token = _current.set(meter)
    try:
        yield meter
    finally:
        _current.reset(token)
