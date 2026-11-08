"""The AI council at the public tables: anyone who opens a table may set it against a crown.

One model and one daily budget are shared by every table on the server, so the whole bill of a
day is capped however many people play. When the day's money is spent, the council's calls are
refused before they are made; the council keeps its last plan and its bot plays on, so a game is
never stopped by the budget.

    GEMINI_API_KEY=...          # the key; without it the tables have no AI
    PAX_AI_DAILY_USD=1          # the most the server spends on models in a day (UTC)

Imported only by a server that has both: the image for tables without AI goes without LangGraph.
"""

import os
from pathlib import Path

from pax_agentica.agents.budget import DailyBudget
from pax_agentica.agents.council import Council, CouncilModel
from pax_agentica.engine import NationId
from pax_agentica.players import Player

BUDGET_FILE = "ai-budget.json"  # beside the tables' saves, so a restart remembers the day


class TableAI:
    """Makes a council for any crown at any table, all spending from one budget."""

    def __init__(self, model: CouncilModel, budget: DailyBudget) -> None:
        self.model = model
        self.budget = budget

    @classmethod
    def from_env(cls, saves: Path) -> "TableAI | None":
        """The council with Gemini, if this server has a key and a daily limit; else None."""
        limit = os.environ.get("PAX_AI_DAILY_USD", "")
        if not os.environ.get("GEMINI_API_KEY") or not limit:
            return None
        from pax_agentica.agents import gemini  # the SDK only on a server that uses it

        saves.mkdir(parents=True, exist_ok=True)
        budget = DailyBudget(float(limit), saves / BUDGET_FILE)
        return cls(gemini.GeminiModel(gemini.new_client(), budget), budget)

    def ruler(self, seed: int, table: str, nation: NationId) -> Player:
        """A council of its own for this crown at this table (its memory is its thread)."""
        return Council(self.model, seed, thread=f"{table}:{nation}")

    def status(self) -> dict[str, float | bool]:
        left = self.budget.left_usd
        return {"available": left >= 0.01, "left_usd": round(left, 2)}
