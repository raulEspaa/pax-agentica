"""A plan: what a ruler wants for the coming years, for the greedy bot to carry out.

An AI ruler need not give every order every year. It can write a short plan (how to spend, how
to use the army, what to take, whom to fight, befriend or leave in peace, what to study) and let
`GreedyBot(plan=...)` turn it into orders each year, until a new plan replaces it; `combine`
lays the ruler's own orders (its letters, its answers) over the bot's. The plan is
small on purpose: a cheap model writes it in a few hundred tokens, against a tiny schema.

The bot follows the plan within the rules and its own judgement of the odds: it still never
breaks a treaty, never attacks without the regiments to win, and answers what the plan does not
mention as it always has.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pax_agentica.engine.actions import MAX_ACTIONS_PER_TURN, MAX_THOUGHTS_CHARS, Action, Orders
from pax_agentica.engine.model import NationId, ProvinceId, TechBranch

Economy = Literal["grow", "balanced", "save"]
Army = Literal["defend", "build_up", "conquer"]


class Plan(BaseModel):
    """What the ruler wants for the coming years. Every field has a safe default: an empty plan
    is a realm that grows and defends itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    economy: Economy = Field(
        default="balanced",
        description="grow: spend on development and works; balanced: as the bot judges; "
        "save: keep a war chest of about 150 ducats and spend little",
    )
    army: Army = Field(
        default="defend",
        description="defend: no new wars on other courts; take only independent land and "
        "win back what was taken; build_up: raise more regiments, and take the provinces in "
        "`conquer` too; conquer: take what can be taken, and make war on `war_on`, seeking "
        "peace on every other front",
    )
    conquer: list[ProvinceId] = Field(
        default_factory=list,
        max_length=5,
        description="provinces to take first, best first",
    )
    war_on: NationId | None = Field(
        default=None,
        description="a court to make war on as soon as the army is ready (with army=conquer); "
        "never one the realm has a treaty with",
    )
    peace_with: list[NationId] = Field(
        default_factory=list,
        max_length=8,
        description="courts to make peace with if at war, and never to attack",
    )
    befriend: list[NationId] = Field(
        default_factory=list,
        max_length=3,
        description="courts to seek an alliance (then a marriage) with",
    )
    research: list[TechBranch] = Field(
        default_factory=list,
        max_length=5,
        description="technology branches in the order to study them",
    )
    note: str = Field(
        default="",
        max_length=300,
        description="why, in a line: kept in the ruler's private thoughts",
    )


# The field that says what an order is about: its proposal, court, province, region or sea.
_SUBJECTS = ("proposal_id", "target", "province", "region", "sea")


def _subject(action: Action) -> tuple[str, object]:
    for field in _SUBJECTS:
        if (value := getattr(action, field, None)) is not None:
            return action.type, value
    return action.type, None


def combine(bot: Orders, ruler: Orders) -> Orders:
    """The bot's orders for the year with a ruler's own on top: the ruler's word wins.

    A ruler that plans may still act itself (write letters, answer a proposal with its own
    terms, offer a peace). Each of its orders replaces the bot's of the same kind about the same
    thing: its `respond` to a proposal replaces the bot's answer to it, its `propose_peace` to a
    court the bot's, its `develop` of a province the bot's. An order about nothing in particular
    (`research`, `set_taxes`) replaces every bot order of its kind. The ruler's orders come
    first, its thoughts before the bot's, and its counsel is kept."""
    ruled = {_subject(a) for a in ruler.actions}
    kinds = {kind for kind, subject in ruled if subject is None}
    kept = [a for a in bot.actions if _subject(a) not in ruled and a.type not in kinds]
    thoughts = "\n".join(t for t in (ruler.thoughts, bot.thoughts) if t)
    return Orders(
        actions=[*ruler.actions, *kept][:MAX_ACTIONS_PER_TURN],
        thoughts=thoughts[:MAX_THOUGHTS_CHARS],
        counsel=ruler.counsel or bot.counsel,
    )
