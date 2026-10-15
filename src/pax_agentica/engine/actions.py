"""Actions: the only way a player (bot, LLM or human) can affect the game.

A player returns `Orders`, a list of actions. Pydantic validates the *shape* (types, ranges,
lengths); the engine validates the *legality* (do you own that province? can you afford it?)
when it resolves the turn, and records an `order_rejected` event with the reason for every
illegal action. Nothing an agent writes can change the state any other way.

`Orders.model_json_schema()` is a ready-made structured-output schema for an LLM. The class
docstrings and field descriptions below end up in that schema, so they are written for the model.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from pax_agentica.engine.model import (
    AdvisorRole,
    BuildingKind,
    NationId,
    ProvinceId,
    Resources,
    TechBranch,
)

MAX_ACTIONS_PER_TURN = 50
MAX_MESSAGE_CHARS = 500

Regiments = Annotated[int, Field(gt=0, le=500, description="Number of regiments (1 or more).")]


class _Action(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------- economy


class Recruit(_Action):
    """Raise new regiments in one of your provinces. Each costs the rules' recruit_cost."""

    type: Literal["recruit"] = "recruit"
    province: ProvinceId
    regiments: Regiments


class Develop(_Action):
    """Invest ducats to raise a province's development by 1 (more output, more score)."""

    type: Literal["develop"] = "develop"
    province: ProvinceId


class Build(_Action):
    """Construct a building in one of your provinces. Each costs and does what the rules'
    `buildings` catalogue says. A province has 1 + development // 4 building slots, holds each
    building once, and a citadel needs a fort first."""

    type: Literal["build"] = "build"
    province: ProvinceId
    building: BuildingKind


class Disband(_Action):
    """Send regiments home: they stop costing grain and ducats, and their men return to the
    manpower pool (up to its cap)."""

    type: Literal["disband"] = "disband"
    province: ProvinceId
    regiments: Regiments


class Research(_Action):
    """Advance one technology branch by a level: military (stronger armies), economy (richer
    provinces) or engineering (cheaper building and development). One research a year."""

    type: Literal["research"] = "research"
    branch: TechBranch


class HireGeneral(_Action):
    """Appoint a new general in one of your provinces. His skill (1 to 3) is up to fortune."""

    type: Literal["hire_general"] = "hire_general"
    province: ProvinceId


class AssignGeneral(_Action):
    """Send one of your generals to take command in another of your provinces."""

    type: Literal["assign_general"] = "assign_general"
    general: int
    province: ProvinceId


class HireAdvisor(_Action):
    """Bring one of the candidates at your court onto your council (see
    `advisor_candidates` in your view). Replaces whoever holds that seat."""

    type: Literal["hire_advisor"] = "hire_advisor"
    candidate: int


class DismissAdvisor(_Action):
    """Send an advisor away: no more salary, no more bonus."""

    type: Literal["dismiss_advisor"] = "dismiss_advisor"
    role: AdvisorRole


class BoostStability(_Action):
    """Spend ducats to raise your stability by 1 (stability boosts ducat income)."""

    type: Literal["boost_stability"] = "boost_stability"


# ---------------------------------------------------------------- military


class Move(_Action):
    """Move regiments between two adjacent provinces that you own. Happens before battles."""

    type: Literal["move"] = "move"
    origin: ProvinceId
    target: ProvinceId
    regiments: Regiments
    general: int | None = Field(
        default=None, description="Id of one of your generals in `origin` to lead them."
    )


class Attack(_Action):
    """Attack an adjacent province owned by a nation you are at war with, or an independent one.

    If you win, your surviving regiments take the province.
    """

    type: Literal["attack"] = "attack"
    origin: ProvinceId
    target: ProvinceId
    regiments: Regiments
    general: int | None = Field(
        default=None, description="Id of one of your generals in `origin` to lead them."
    )


# ---------------------------------------------------------------- diplomacy


class DeclareWar(_Action):
    """Declare war. Breaks any alliance, non-aggression pact or truce with the target, which costs
    stability and is seen by everyone. The target's allies are called to arms against you."""

    type: Literal["declare_war"] = "declare_war"
    target: NationId


class ProposeAlliance(_Action):
    """Offer an alliance. Allies share vision and are called to arms when one is attacked."""

    type: Literal["propose_alliance"] = "propose_alliance"
    target: NationId


class ProposeNonAggression(_Action):
    """Offer a non-aggression pact for a fixed number of turns."""

    type: Literal["propose_non_aggression"] = "propose_non_aggression"
    target: NationId


class ProposePeace(_Action):
    """Offer peace to a nation you are at war with. Accepted peace starts a truce.

    Leave both bundles empty for a white peace, offer reparations with `give`, or demand them
    with `receive`. Whoever cannot pay everything pays what they have."""

    type: Literal["propose_peace"] = "propose_peace"
    target: NationId
    give: Resources = Field(default_factory=Resources, description="Reparations you pay.")
    receive: Resources = Field(default_factory=Resources, description="Reparations you demand.")


class ProposeTrade(_Action):
    """Offer an exchange: you give `give` and receive `receive` if the target accepts.

    Asking for something while giving nothing is a demand for tribute."""

    type: Literal["propose_trade"] = "propose_trade"
    target: NationId
    give: Resources = Field(default_factory=Resources, description="What you hand over.")
    receive: Resources = Field(default_factory=Resources, description="What you ask for.")


class RequestCallToArms(_Action):
    """Ask an ally to join your war against `enemy`. An ally who refuses or ignores the call
    dissolves the alliance, in public."""

    type: Literal["call_to_arms"] = "call_to_arms"
    target: NationId
    enemy: NationId


class Respond(_Action):
    """Accept or reject a proposal addressed to you. Unanswered proposals expire; ignoring a call
    to arms from an ally dissolves the alliance."""

    type: Literal["respond"] = "respond"
    proposal_id: int
    accept: bool


class CancelTreaty(_Action):
    """End an alliance or non-aggression pact openly. No stability cost."""

    type: Literal["cancel_treaty"] = "cancel_treaty"
    target: NationId
    kind: Literal["alliance", "non_aggression"]


class Gift(_Action):
    """Give resources to another nation, no strings attached."""

    type: Literal["gift"] = "gift"
    target: NationId
    resources: Resources


class SendMessage(_Action):
    """Send a private diplomatic message. The target reads it next turn. It has no effect on
    the rules: words are only words."""

    type: Literal["send_message"] = "send_message"
    target: NationId
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


type Action = Annotated[
    Recruit
    | Develop
    | Disband
    | Build
    | BoostStability
    | Research
    | HireGeneral
    | AssignGeneral
    | HireAdvisor
    | DismissAdvisor
    | Move
    | Attack
    | DeclareWar
    | ProposeAlliance
    | ProposeNonAggression
    | ProposePeace
    | ProposeTrade
    | RequestCallToArms
    | Respond
    | CancelTreaty
    | Gift
    | SendMessage,
    Field(discriminator="type"),
]


class Orders(BaseModel):
    """Everything a nation wants to do this turn, in the order it wants it done."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actions: list[Action] = Field(default_factory=list, max_length=MAX_ACTIONS_PER_TURN)
