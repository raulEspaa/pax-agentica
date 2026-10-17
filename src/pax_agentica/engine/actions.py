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
    Focus,
    NationId,
    Posture,
    ProvinceId,
    Resources,
    Stance,
    Tactic,
    TechBranch,
    UnitKind,
)

MAX_ACTIONS_PER_TURN = 50
MAX_MESSAGE_CHARS = 500
MAX_NOTE_CHARS = 300
MAX_PROCLAMATION_CHARS = 400
MAX_THOUGHTS_CHARS = 2000
MAX_COUNSEL_CHARS = 600

Regiments = Annotated[int, Field(gt=0, le=500, description="Number of regiments (1 or more).")]


class _Action(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------- economy


Composition = Annotated[
    dict[UnitKind, Annotated[int, Field(ge=0, le=500)]],
    Field(description='Regiments of each kind, e.g. {"infantry": 6, "cavalry": 2}.'),
]


class Recruit(_Action):
    """Raise new regiments of one kind in one of your provinces. Pikemen (infantry) can be
    raised anywhere; cavalry needs stables in the province and artillery a cannon foundry. See
    `rules.units` for what each kind costs and how it fights."""

    type: Literal["recruit"] = "recruit"
    province: ProvinceId
    regiments: Regiments
    unit: UnitKind = UnitKind.INFANTRY


class HireMercenaries(_Action):
    """Hire mercenary pikemen (Landsknechte, Swiss) in one of your provinces for ducats alone:
    no manpower and no iron, at the rules' mercenary_cost a regiment, up to mercenary_limit
    regiments a year. Once hired they serve, eat and are paid like any infantry."""

    type: Literal["hire_mercenaries"] = "hire_mercenaries"
    province: ProvinceId
    regiments: Regiments


class Develop(_Action):
    """Invest ducats to raise a province's development by 1 (more output, more score)."""

    type: Literal["develop"] = "develop"
    province: ProvinceId


class Build(_Action):
    """Construct a building in one of your provinces. Each costs and does what the rules'
    `buildings` catalogue says. Every province has `rules.building_slots` slots, holds each
    building once, and a citadel needs a fort first."""

    type: Literal["build"] = "build"
    province: ProvinceId
    building: BuildingKind


class UpgradeBuilding(_Action):
    """Raise a building standing in one of your provinces to its next level: it does more (and
    eats more), by `rules.building_level_factors`, up to its `max_level`. It costs its own
    cost times `rules.building_upgrade_costs` for the new level. Once a year per building."""

    type: Literal["upgrade_building"] = "upgrade_building"
    province: ProvinceId
    building: BuildingKind


class Disband(_Action):
    """Send regiments home: they stop costing grain and ducats, and their men return to the
    manpower pool (up to its cap)."""

    type: Literal["disband"] = "disband"
    province: ProvinceId
    regiments: Regiments
    unit: UnitKind | None = Field(
        default=None, description="Only this kind; leave out for a proportional mix."
    )


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


class SetTaxes(_Action):
    """Set the realm's taxes from -2 (very low) to +2 (very high). Each level up brings
    rules.tax_income_step more ducat income and rules.tax_manpower_step less manpower, makes
    raising stability dearer, and above 0 risks a point of stability every year; below 0 the
    people may grow content and stability rise. The level stays until changed."""

    type: Literal["set_taxes"] = "set_taxes"
    level: int = Field(ge=-2, le=2)


class Patronize(_Action):
    """Patronise painters, churches and feasts: once a year, spend patronage_base ducats plus
    patronage_per_prestige for every point of prestige you hold, for patronage_prestige more
    prestige. Prestige raises income and counts in the final score."""

    type: Literal["patronize"] = "patronize"


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
    units: Composition | None = Field(
        default=None,
        description="Exactly which regiments go, by kind, adding up to `regiments`. Leave out "
        "to send a proportional mix of what stands in `origin`.",
    )


class Attack(_Action):
    """Attack an adjacent province owned by a nation you are at war with, or an independent one.

    If you win, your surviving regiments take the province. Behind walls they lay a siege
    instead: they camp before the walls, which fall once the siege reaches 100% (see
    `siege_modifiers` on the province). Attacking a province you besiege sends reinforcements
    to the siege lines; attacking a province of yours (or an ally's) under siege fights the
    besiegers to relieve it.
    """

    type: Literal["attack"] = "attack"
    origin: ProvinceId
    target: ProvinceId
    regiments: Regiments
    general: int | None = Field(
        default=None, description="Id of one of your generals in `origin` to lead them."
    )
    units: Composition | None = Field(
        default=None,
        description="Exactly which regiments attack, by kind, adding up to `regiments`. Leave "
        "out to send a proportional mix. Cavalry charges best on plains; every tenth of the "
        "army in artillery knocks a fort level off.",
    )
    tactic: Tactic = Field(
        default=Tactic.ASSAULT,
        description="How to fight it, against the garrison's posture (see the province's "
        "`posture`). assault (carried by infantry) beats a garrison that skirmishes and breaks "
        "on one that holds the line; flank (cavalry; gains half as much in forest, hills, marsh "
        "and mountains) turns a held line and is caught by a sally; bombard (artillery) "
        "shatters a sally and is picked off by skirmishers. Worth rules.tactic_edge either way, "
        "as far as the regiments that carry it can; a tactic your army cannot carry (a flank "
        "without horse) costs as much as one outguessed. `targets` tells the best one.",
    )


class LiftSiege(_Action):
    """Raise a siege you lay: the besiegers march back to one of your provinces next to it."""

    type: Literal["lift_siege"] = "lift_siege"
    province: ProvinceId


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
    note: str = Field(default="", max_length=300)  # a word to go with it


class ProposeNonAggression(_Action):
    """Offer a non-aggression pact for a fixed number of turns."""

    type: Literal["propose_non_aggression"] = "propose_non_aggression"
    target: NationId
    note: str = Field(default="", max_length=300)


class ProposeMarriage(_Action):
    """Offer a royal marriage between the two houses. It lasts until war breaks it: both courts
    warm to each other by rules.opinion_marriage_yearly every year. At most rules.max_marriages
    for a realm."""

    type: Literal["propose_marriage"] = "propose_marriage"
    target: NationId
    note: str = Field(default="", max_length=300)


class ProposeCoalition(_Action):
    """Invite `target` into a defensive league against `against`, a power whose infamy has
    reached rules.coalition_infamy. Once signed, if `against` declares war on either of you, the
    other (and every other court leagued against it) goes to war at once, without being asked.
    The league dissolves when the conqueror's infamy falls below rules.coalition_dissolves."""

    type: Literal["propose_coalition"] = "propose_coalition"
    target: NationId
    against: NationId
    note: str = Field(default="", max_length=300)


Note = Annotated[
    str,
    Field(
        max_length=MAX_NOTE_CHARS,
        description="Your words to go with the offer: arguments, threats, promises. They bind "
        "nobody.",
    ),
]


class Terms(BaseModel):
    """What a peace (or a counter-offer) settles. Everything is optional: no terms at all is a
    white peace. Lump sums are capped by what the payer has; provinces must belong to the side
    that hands them over, cannot be a capital, and must border the realm that receives them (or
    another province it receives in the same peace)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    give: Resources = Field(default_factory=Resources, description="A lump sum you pay.")
    receive: Resources = Field(default_factory=Resources, description="A lump sum you demand.")
    cede: list[ProvinceId] = Field(
        default_factory=list, max_length=8, description="Your provinces you hand over."
    )
    demand: list[ProvinceId] = Field(
        default_factory=list, max_length=8, description="Their provinces you ask for."
    )
    pay_tribute: int = Field(
        default=0, ge=0, le=500, description="Ducats a year you pay them, for 10 years."
    )
    ask_tribute: int = Field(
        default=0, ge=0, le=500, description="Ducats a year they pay you, for 10 years."
    )
    limit_army: int | None = Field(
        default=None,
        ge=0,
        description="Their army may not grow beyond this many regiments while the truce lasts.",
    )
    note: Note = ""


class ProposePeace(Terms, _Action):
    """Offer peace to a nation you are at war with. Accepted peace starts a five-year truce and
    carries out the terms. The recipient may accept, reject, or answer with a counter-offer."""

    type: Literal["propose_peace"] = "propose_peace"
    target: NationId


class ProposeTrade(_Action):
    """Offer an exchange: you give `give` and receive `receive` if the target accepts.

    Asking for something while giving nothing is a demand for tribute."""

    type: Literal["propose_trade"] = "propose_trade"
    target: NationId
    give: Resources = Field(default_factory=Resources, description="What you hand over.")
    receive: Resources = Field(default_factory=Resources, description="What you ask for.")
    note: Note = ""


class RequestCallToArms(_Action):
    """Ask an ally to join your war against `enemy`. An ally who refuses or ignores the call
    dissolves the alliance, in public."""

    type: Literal["call_to_arms"] = "call_to_arms"
    target: NationId
    enemy: NationId
    note: str = Field(default="", max_length=300)


class Respond(_Action):
    """Accept or reject a proposal addressed to you. Unanswered proposals expire; ignoring a call
    to arms from an ally dissolves the alliance.

    To haggle over a peace or a trade, reject it with a `counter`: your own terms, written from
    your side (`give` is what you would pay). It reaches them as a new proposal next turn, and
    they can accept, reject or counter again. A trade's counter may only use `give`, `receive`
    and `note`."""

    type: Literal["respond"] = "respond"
    proposal_id: int
    accept: bool
    counter: Terms | None = None
    note: str = Field(default="", max_length=300)  # your answer in words, delivered as a letter


class CancelTreaty(_Action):
    """End an alliance, a non-aggression pact, a marriage or every coalition with `target`
    openly. No stability cost."""

    type: Literal["cancel_treaty"] = "cancel_treaty"
    target: NationId
    kind: Literal["alliance", "non_aggression", "marriage", "coalition"]


class Convert(_Action):
    """Send preachers to one of your provinces whose people keep another faith: it takes yours at
    once, ending its discontent (a province of another faith yields rules.faith_mismatch_output
    less). Costs rules.convert_cost plus convert_cost_per_development ducats a level; one a year."""

    type: Literal["convert"] = "convert"
    province: ProvinceId


class Improve(_Action):
    """Improve the workings of one of your provinces by a level (up to 3): its mine,
    vineyard, fishery or looms, by what it is known for. Each level adds half of what its good
    yields; it takes no building slot. The next level costs the rules' improve_cost times it."""

    type: Literal["improve"] = "improve"
    province: ProvinceId


class SetFocus(_Action):
    """Turn one of your provinces to a focus: trade (more ducats), farming (more grain), mining
    (more iron and timber), garrison (more manpower, defended harder) or learning (cheaper to
    develop; each province of learning makes the realm's research cheaper). The bonus is
    rules.focus_base plus focus_per_settlement for each step its town has grown above a hamlet.
    Costs rules.focus_cost; a province keeps its focus at least rules.focus_years years."""

    type: Literal["set_focus"] = "set_focus"
    province: ProvinceId
    focus: Focus


class SetPosture(_Action):
    """Tell the garrison of one of your provinces how to wait for an attack: hold (the line of
    pikes, carried by infantry), skirmish (shot and bows thrown forward, carried by archers) or
    sally (horse kept back to charge, carried by cavalry). Each beats one attacking tactic and
    loses to another (see Attack.tactic). Free; whoever can see the garrison sees its posture."""

    type: Literal["set_posture"] = "set_posture"
    province: ProvinceId
    posture: Posture


class UpgradeMonument(_Action):
    """Raise the monument of one of your provinces by a level (from a bare site to level 1, up
    to the rules' maximum). Its bonus grows with every level and serves whoever holds it."""

    type: Literal["upgrade_monument"] = "upgrade_monument"
    province: ProvinceId


class SetStance(_Action):
    """Declare a court your friend or your rival, or neutral again. Stances are public: every
    court sees them. A friend warms to you every year, a rival cools, and your regiments fight 5%
    harder against a declared rival. At most three friends and three rivals."""

    type: Literal["set_stance"] = "set_stance"
    target: NationId
    stance: Stance


class Proclaim(_Action):
    """Speak to all Europe: a public proclamation every court reads next turn. Like letters, it
    binds nobody."""

    type: Literal["proclaim"] = "proclaim"
    text: str = Field(min_length=1, max_length=MAX_PROCLAMATION_CHARS)


Traded = Literal["grain", "iron", "timber", "goods"]


class Buy(_Action):
    """Buy from the European market at today's price plus the merchants' cut (see
    `market`). What all Europe buys and sells this year moves next year's prices."""

    type: Literal["buy"] = "buy"
    resource: Traded
    amount: int = Field(gt=0, le=200)


class Sell(_Action):
    """Sell to the European market at today's price minus the merchants' cut."""

    type: Literal["sell"] = "sell"
    resource: Traded
    amount: int = Field(gt=0, le=200)


class ChooseOption(_Action):
    """Answer one of your pending events (see `me.pending_events`) with one of its options, by
    index. Unanswered by the end of the next year, an event takes its first option."""

    type: Literal["choose_option"] = "choose_option"
    event_id: int
    option: int = Field(ge=0)


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
    | HireMercenaries
    | Patronize
    | SetTaxes
    | Develop
    | Disband
    | Build
    | UpgradeBuilding
    | UpgradeMonument
    | Improve
    | SetFocus
    | SetPosture
    | Convert
    | BoostStability
    | Research
    | HireGeneral
    | AssignGeneral
    | HireAdvisor
    | DismissAdvisor
    | Move
    | Attack
    | LiftSiege
    | DeclareWar
    | ProposeAlliance
    | ProposeNonAggression
    | ProposeMarriage
    | ProposeCoalition
    | ProposePeace
    | ProposeTrade
    | RequestCallToArms
    | Respond
    | CancelTreaty
    | Gift
    | SendMessage
    | SetStance
    | Proclaim
    | ChooseOption
    | Buy
    | Sell,
    Field(discriminator="type"),
]


class Orders(BaseModel):
    """Everything a nation wants to do this turn, in the order it wants it done."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actions: list[Action] = Field(default_factory=list, max_length=MAX_ACTIONS_PER_TURN)
    thoughts: str = Field(
        default="",
        max_length=MAX_THOUGHTS_CHARS,
        description="The ruler's private reasoning this year. No other court sees it; it is kept "
        "in the record, for the chronicle of the game.",
    )
    counsel: dict[AdvisorRole, Annotated[str, Field(max_length=MAX_COUNSEL_CHARS)]] = Field(
        default_factory=dict,
        description="What each advisor counselled this year, by seat. Private, like `thoughts`.",
    )
