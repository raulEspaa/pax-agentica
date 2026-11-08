"""A hard limit on what a run may spend on language models.

The money for a call is set aside before the call is made, because several crowns ask at once and
the real cost is known only afterwards. A call the budget cannot cover is never made.
"""

import json
from datetime import UTC, datetime
from pathlib import Path


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


class DailyBudget(Budget):
    """A budget that starts again every day (UTC), for a server open to anyone.

    What is spent is written to `path` after every call, so a restart (the server scales to zero
    when nobody plays) does not hand out the day's money a second time."""

    def __init__(self, limit_usd: float, path: Path | None = None) -> None:
        super().__init__(limit_usd)
        self.path = path
        self.day = _today()
        if path is not None:
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                if saved.get("day") == self.day:
                    self.spent_usd = float(saved["spent_usd"])
            except (OSError, ValueError, KeyError, TypeError):
                pass  # no record yet, or one we cannot read: the day starts at zero

    @property
    def left_usd(self) -> float:
        self._roll()
        return max(0.0, self.limit_usd - self.committed_usd)

    def reserve(self, usd: float) -> None:
        self._roll()
        super().reserve(usd)

    def settle(self, reserved_usd: float, spent_usd: float) -> None:
        super().settle(reserved_usd, spent_usd)
        self._roll()
        if self.path is not None:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"day": self.day, "spent_usd": self.spent_usd}))
            tmp.replace(self.path)

    def _roll(self) -> None:
        """A new day: what was spent goes back to zero (calls still in flight stay held)."""
        today = _today()
        if today != self.day:
            self.day, self.spent_usd = today, 0.0


def _today() -> str:
    return datetime.now(UTC).date().isoformat()
