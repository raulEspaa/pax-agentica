"""A hard limit on what a run may spend on language models.

The money for a call is set aside before the call is made, because several crowns ask at once and
the real cost is known only afterwards. A call the budget cannot cover is never made.
"""


class BudgetExceeded(Exception):
    """A call was refused: it could cost more than what is left."""


class Budget:
    def __init__(self, limit_usd: float) -> None:
        if limit_usd <= 0:
            raise ValueError("a budget must be positive")
        self.limit_usd = limit_usd
        self.spent_usd = 0.0
        self._held_usd = 0.0

    @property
    def committed_usd(self) -> float:
        """What is spent, and what is set aside for the calls in flight."""
        return self.spent_usd + self._held_usd

    def reserve(self, usd: float) -> None:
        """Set this much aside, or raise `BudgetExceeded` and change nothing."""
        if self.committed_usd + usd > self.limit_usd:
            raise BudgetExceeded(
                f"${usd:.4f} more would pass the limit of ${self.limit_usd:.2f} "
                f"(${self.committed_usd:.4f} committed)"
            )
        self._held_usd += usd

    def settle(self, reserved_usd: float, spent_usd: float) -> None:
        """A call has ended: release what was set aside and record what it cost."""
        self._held_usd -= reserved_usd
        self.spent_usd += spent_usd
