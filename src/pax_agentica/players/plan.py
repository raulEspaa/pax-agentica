"""A plan: what a ruler wants for the coming years, for the greedy bot to carry out.

An AI ruler need not give every order every year. It can write a short plan (how to spend, how
to use the army, what to take, whom to fight, befriend or leave in peace, what to study) and let
`GreedyBot(plan=...)` turn it into orders each year, until a new plan replaces it. The plan is
small on purpose: a cheap model writes it in a few hundred tokens, against a tiny schema.

The bot follows the plan within the rules and its own judgement of the odds: it still never
breaks a treaty, never attacks without the regiments to win, and answers what the plan does not
mention as it always has.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
