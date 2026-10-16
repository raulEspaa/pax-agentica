"""Fog of war: what one nation is allowed to know.

A player never receives the `GameState`; it receives a `NationView` built here. The view holds:

- Everything about your own nation: treasury, stability, income, treaties, wars.
- The whole map's geography and political borders (owners and development are public).
- Troop counts only where you can see: your provinces, your allies' provinces, and every
  province bordering yours (land or sea). Elsewhere `troops` is None.
- Public facts about other nations (size, score, wars, alliances) but not their treasuries.
- Last turn's events that you could witness: public news plus anything addressed to you,
  including messages, proposals and the reasons your own orders were rejected.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pax_agentica.engine import fortune, missions
from pax_agentica.engine.events import Event
from pax_agentica.engine.mechanics import (
    army_of,
    army_upkeep,
    base_output,
    building_cost,
    building_output,
    building_slots,
    convert_cost,
    develop_cost,
    faith_penalty,
    inputs_upkeep,
    manpower_cap,
    market_cut,
    market_price,
    nation_income,
    nation_upkeep,
    province_output,
    recruit_cost,
    research_cost,
    siege_modifiers,
    war_score,
    workings_yield,
)
from pax_agentica.engine.missions import Goal
from pax_agentica.engine.model import (
    TRADED,
    Advisor,
    AdvisorRole,
    BuildingKind,
    Faith,
    GameState,
    Good,
    Loan,
    NationId,
    PendingEvent,
    Personality,
    ProposalKind,
    ProvinceId,
    Resources,
    Ruler,
    Rules,
    Stance,
    TechBranch,
    Terrain,
    TreatyKind,
    UnitKind,
)
from pax_agentica.engine.realm import Modifiers, advisor_candidates, advisor_hire_cost, modifiers


class _View(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GeneralView(_View):
    id: int
    name: str
    nation: NationId
    skill: int  # 1 to 3: +10% battle power per point
    province: ProvinceId


class ProvinceView(_View):
    id: ProvinceId
    name: str
    owner: NationId | None  # None: independent
    controller: NationId | None  # an enemy occupying it in a war (it yields nothing meanwhile)
    siege_by: NationId | None  # who besieges its walls
    siege_years: int  # years the siege has lasted
    siege_progress: int  # 0 to 100: at 100 the walls fall
    besiegers: int | None  # regiments in the siege lines (None: hidden by the fog of war)
    # what is added to the besiegers' die next year (1 to 6), line by line; see rules.siege_results
    siege_modifiers: tuple[tuple[str, int], ...]
    terrain: Terrain
    good: Good
    development: int
    fort: int  # fortification level: 1 with a fort, 2 with a citadel too
    buildings: tuple[BuildingKind, ...]
    building_levels: dict[BuildingKind, int]  # the level of every building standing (1 to 3)
    idle: tuple[
        BuildingKind, ...
    ]  # buildings whose inputs went unpaid last year: they yield nothing
    building_slots: int  # rules.building_slots, and one more with Cameralism
    output_per_turn: Resources  # what it yields its owner each turn (nothing during unrest)
    building_output_per_turn: Resources  # the part of that output its buildings add
    unrest: int  # turns before a recently conquered province produces again
    is_capital: bool
    troops: int | None  # None: hidden by the fog of war
    army: dict[UnitKind, int] | None  # the same regiments by kind; None when hidden
    general: GeneralView | None  # the general here, if you can see this province
    develop_cost: Resources  # for its owner, after universities and engineering
    recruit_cost: Resources  # per pikeman, for its owner, after an armory
    recruit_costs: dict[UnitKind, Resources]  # yours only: per regiment of each kind raisable here
    workings: int  # level of its mine, vineyard, fishery... (0 to rules.max_workings)
    faith: Faith | None  # what its people believe; another faith than its ruler's yields less
    convert_cost: (
        Resources | None
    )  # yours only, if its people keep another faith: what `convert` costs
    improve_cost: Resources | None  # yours only: what the next level of workings costs
    monument: int | None  # level of its monument (see rules.monuments); None if it has none
    neighbors: tuple[ProvinceId, ...]
    sea_neighbors: tuple[ProvinceId, ...]


class TreatyView(_View):
    kind: TreatyKind
    partner: NationId
    until_turn: int | None
    payer: NationId | None = None  # tribute and army limit: the side bound by it
    against: NationId | None = None  # coalition: the conqueror the league stands against
    amount: int = 0  # tribute: ducats a year; army limit: regiments


class WarView(_View):
    enemy: NationId
    since_turn: int
    attacks_allowed_from_turn: int  # armies mobilise for a while after a war starts
    war_score: int  # -100 to 100, your side: what a peace may demand of them
    battles_won: int
    battles_lost: int


class CandidateView(_View):
    id: int
    name: str
    role: AdvisorRole
    skill: int
    personality: Personality
    hire_cost: int  # ducats, once
    salary: int  # ducats, every year


class PriceView(_View):
    price: float  # ducats a unit, before the merchants' cut
    buy: float  # what a unit costs you, the cut included
    sell: float  # what a unit brings you


class OptionView(_View):
    label: str
    effects: str  # what it does, in words


class EventView(_View):
    id: int  # answer with choose_option(event_id=id, option=index)
    event: str
    title: str
    text: str
    province: ProvinceId | None
    options: tuple[OptionView, ...]
    deadline_turn: int  # unanswered by the end of this turn, the first option is taken


class GoalView(_View):
    text: str  # what is asked, in words
    have: int
    need: int
    goal: Goal  # the same goal as data


class MissionView(_View):
    id: str
    title: str
    lore: str
    goals: tuple[GoalView, ...]
    reward: str  # what it pays, in words
    status: Literal["done", "open", "locked"]  # locked: its earlier mission is not done
    after: str | None


class LedgerLine(_View):
    kind: Literal["income", "expense"]
    source: str  # land, buildings, workings, the crown's modifiers, the army, the council...
    amount: dict[str, int]  # by resource; a modifier line can be negative


class MyNation(_View):
    id: NationId
    name: str
    capital: ProvinceId
    resources: Resources
    stability: int
    income_per_turn: Resources  # production, already including the stability modifier
    army_upkeep_per_turn: Resources  # what the army eats and is paid, plus advisors' salaries
    inputs_per_turn: Resources  # what your buildings consume a year, if all of them work
    manpower_cap: int  # the pool never grows beyond this; barracks raise it
    regiments: int
    army: dict[UnitKind, int]  # every regiment you have, by kind
    provinces: tuple[ProvinceId, ...]  # the provinces you own
    held: tuple[
        ProvinceId, ...
    ]  # where your armies stand: your own unoccupied land and what you occupy
    war_exhaustion: float  # 0 to 20: costs ducats, and stability from 10
    prestige: int  # 0 to 100: ducats, cheaper stability, and half of it counts towards victory
    standing: int  # development plus half the prestige: what wins when time runs out
    faith: Faith
    pending_events: tuple[EventView, ...]  # decisions awaiting the crown
    loans: tuple[Loan, ...]
    missions: tuple[MissionView, ...]  # your ambitions: done at the end of a year all goals hold
    patronage_cost: int  # ducats for patronize (+rules.patronage_prestige prestige), once a year
    tax: int  # -2 very low ... +2 very high; change it with set_taxes
    infamy: float  # your conquests' weight on Europe; past rules.coalition_infamy, leagues form
    ledger: tuple[LedgerLine, ...]  # where this year's resources come from and go, line by line
    score: int
    at_war_with: tuple[NationId, ...]
    wars: tuple[WarView, ...]
    treaties: tuple[TreatyView, ...]
    technology: dict[TechBranch, int]
    research_costs: dict[TechBranch, Resources | None]  # None: already at the top
    building_costs: dict[BuildingKind, Resources]  # after engineering
    generals: tuple[GeneralView, ...]
    modifiers: Modifiers  # every bonus you enjoy, with its source spelled out
    ruler: Ruler | None
    advisors: dict[AdvisorRole, Advisor]
    advisor_candidates: tuple[CandidateView, ...]  # who you can hire right now
    opinions: dict[NationId, int]  # what you think of each court, from -100 to 100
    stances: dict[NationId, Stance]  # the friends and rivals you have declared (public)


class NationSummary(_View):
    id: NationId
    name: str
    alive: bool
    capital: ProvinceId
    provinces: int
    score: int
    at_war_with: tuple[NationId, ...]
    allies: tuple[NationId, ...]
    technology: dict[TechBranch, int]  # public, as in any court of Europe
    generals: int
    ruler: Ruler | None  # public too: every court knows who reigns where
    opinion_of_you: int  # what this court thinks of you, from -100 to 100
    war_exhaustion: float
    prestige: int
    standing: int
    faith: Faith
    stances: dict[NationId, Stance]  # the friends and rivals this court has declared (public)
    infamy: float  # its conquests' weight on Europe; from rules.coalition_infamy, a league may form
    leagued_against: tuple[NationId, ...]  # the conquerors this court has leagued against
    correspondence: tuple[Event, ...]  # what last passed between this court and you, oldest first


class ProposalView(_View):
    id: int
    kind: ProposalKind
    sender: NationId
    recipient: NationId
    turn: int
    give: Resources  # trade and peace: what the sender gives
    receive: Resources  # trade and peace: what the sender asks for
    enemy: NationId | None  # call to arms: who the sender is fighting
    cede: list[ProvinceId]  # peace: provinces the sender hands over
    demand: list[ProvinceId]  # peace: provinces the sender asks for
    pay_tribute: int  # peace: ducats a year the sender pays, for rules.tribute_years
    ask_tribute: int  # peace: ducats a year the sender asks for
    limit_army: int | None  # peace: the recipient's army may not grow beyond this
    note: str  # the sender's words
    reply_to: int | None  # the proposal of yours this one counters


class NationView(_View):
    turn: int
    year: int
    max_turns: int
    me: MyNation
    provinces: tuple[ProvinceView, ...]
    nations: tuple[NationSummary, ...]
    proposals_to_answer: tuple[ProposalView, ...]  # answer them this turn or they expire
    proposals_sent: tuple[ProposalView, ...]
    last_turn_events: tuple[Event, ...]
    market: dict[str, PriceView]  # the European market today: trade with `buy` and `sell`
    rules: Rules


def visible_provinces(state: GameState, nation: NationId) -> set[ProvinceId]:
    """Where `nation` can count troops: its own and its allies' land, and every border."""
    allies = set(state.partners(nation, TreatyKind.ALLIANCE))
    seen = {p for p, s in state.provinces.items() if s.holder == nation or s.holder in allies}
    for province in state.held_by(nation):
        seen.update(state.map.all_neighbors(province))
    return seen


def view_for(state: GameState, nation: NationId) -> NationView:
    """Build the fog-of-war view of `state` for `nation`."""
    me = state.nations[nation]
    mods = modifiers(state, nation)
    seen = visible_provinces(state, nation)
    capitals = {n.capital for n in state.nations.values() if n.alive}

    provinces = tuple(
        ProvinceView(
            id=pid,
            name=definition.name,
            owner=ps.owner,
            controller=ps.controller,
            siege_by=ps.siege_by,
            siege_years=ps.siege_years,
            siege_progress=ps.siege_progress,
            besiegers=sum(ps.besiegers.values()) if pid in seen or ps.siege_by == nation else None,
            siege_modifiers=tuple(siege_modifiers(state, pid)),
            terrain=definition.terrain,
            good=definition.good,
            development=ps.development,
            fort=ps.fort,
            buildings=tuple(ps.buildings),
            building_levels={b: ps.level(b) for b in ps.buildings},
            idle=tuple(ps.idle),
            building_slots=building_slots(
                state.rules, ps.development, _mods(state, ps.owner).extra_building_slots
            ),
            output_per_turn=province_output(state, pid),
            building_output_per_turn=Resources() if ps.unrest else building_output(state, pid),
            unrest=ps.unrest,
            is_capital=pid in capitals and ps.owner is not None,
            troops=ps.troops if pid in seen else None,
            army=ps.army() if pid in seen else None,
            general=_general(state, pid) if pid in seen else None,
            develop_cost=develop_cost(
                state.rules,
                ps.development,
                ps.buildings,
                _mods(state, ps.owner).building_discount,
                definition.terrain,
            ),
            recruit_cost=recruit_cost(
                state.rules, 1, ps.buildings, arms=_mods(state, ps.owner).arms_manufactory
            ),
            recruit_costs={
                kind: recruit_cost(state.rules, 1, ps.buildings, kind, mods.arms_manufactory)
                for kind, spec in state.rules.units.items()
                if spec.requires is None or spec.requires in ps.buildings
            }
            if ps.owner == nation and not ps.controller
            else {},
            monument=ps.monument if pid in state.rules.monuments else None,
            workings=ps.workings,
            faith=ps.faith,
            convert_cost=convert_cost(state.rules, ps.development)
            if ps.owner == nation and ps.faith is not None and ps.faith != me.faith
            else None,
            improve_cost=state.rules.improve_cost.times(ps.workings + 1)
            if ps.owner == nation and ps.workings < state.rules.max_workings
            else None,
            neighbors=definition.neighbors,
            sea_neighbors=definition.sea_neighbors,
        )
        for pid, definition in state.map.provinces.items()
        for ps in [state.provinces[pid]]
    )

    treaties = tuple(
        TreatyView(
            kind=t.kind,
            partner=t.parties[1] if t.parties[0] == nation else t.parties[0],
            until_turn=t.until,
            payer=t.payer,
            against=t.against,
            amount=t.amount,
        )
        for t in state.treaties
        if nation in t.parties
    )

    my_nation = MyNation(
        id=nation,
        name=me.name,
        capital=me.capital,
        resources=me.resources,
        stability=me.stability,
        income_per_turn=nation_income(state, nation),
        army_upkeep_per_turn=nation_upkeep(state, nation),
        inputs_per_turn=inputs_upkeep(state, nation),
        manpower_cap=manpower_cap(state, nation),
        regiments=state.troops_of(nation),
        army=army_of(state, nation),
        provinces=tuple(state.provinces_of(nation)),
        held=tuple(state.held_by(nation)),
        war_exhaustion=me.war_exhaustion,
        prestige=me.prestige,
        standing=state.standing(nation),
        faith=me.faith,
        pending_events=tuple(_event_view(state, nation, e) for e in me.pending_events),
        loans=tuple(me.loans),
        missions=_missions(state, nation),
        tax=me.tax,
        infamy=round(me.infamy, 1),
        ledger=_ledger(state, nation),
        patronage_cost=state.rules.patronage_base
        + state.rules.patronage_per_prestige * me.prestige,
        score=state.score(nation),
        at_war_with=tuple(state.enemies_of(nation)),
        wars=tuple(
            WarView(
                enemy=enemy,
                since_turn=w.since,
                attacks_allowed_from_turn=w.since + state.rules.mobilization_turns,
                war_score=war_score(state, nation, enemy),
                battles_won=w.battles.get(nation, 0),
                battles_lost=w.battles.get(enemy, 0),
            )
            for w in state.wars
            if nation in w.parties
            for enemy in [w.parties[1] if w.parties[0] == nation else w.parties[0]]
        ),
        treaties=treaties,
        technology=dict(me.technology),
        research_costs={
            b: research_cost(state.rules, b, level, mods.research_discount)
            for b, level in me.technology.items()
        },
        building_costs={
            kind: building_cost(state.rules, kind, mods.building_discount)
            for kind in state.rules.buildings
        },
        modifiers=mods,
        ruler=me.ruler,
        advisors=dict(me.advisors),
        advisor_candidates=tuple(
            CandidateView(
                **c.model_dump(),
                hire_cost=advisor_hire_cost(state.rules, c),
                salary=state.rules.advisor_salary_ducats * c.skill,
            )
            for c in advisor_candidates(state, nation)
            if c.name not in {a.name for a in me.advisors.values()}
        ),
        opinions={n: state.opinion(nation, n) for n in state.nations if n != nation},
        stances=dict(me.stances),
        generals=tuple(
            GeneralView.model_validate(g.model_dump()) for g in state.generals_of(nation)
        ),
    )

    nations = tuple(
        NationSummary(
            id=nid,
            name=ns.name,
            alive=ns.alive,
            capital=ns.capital,
            provinces=len(state.provinces_of(nid)),
            score=state.score(nid),
            at_war_with=tuple(state.enemies_of(nid)),
            allies=tuple(state.partners(nid, TreatyKind.ALLIANCE)),
            technology=dict(ns.technology),
            generals=len(state.generals_of(nid)),
            ruler=ns.ruler,
            opinion_of_you=state.opinion(nid, nation),
            stances=dict(ns.stances),
            war_exhaustion=ns.war_exhaustion,
            prestige=ns.prestige,
            standing=state.standing(nid),
            faith=ns.faith,
            infamy=round(ns.infamy, 1),
            leagued_against=tuple(
                sorted(
                    {
                        t.against
                        for t in state.treaties
                        if t.kind == TreatyKind.COALITION and nid in t.parties and t.against
                    }
                )
            ),
            correspondence=_correspondence(state, nation, nid),
        )
        for nid, ns in state.nations.items()
        if nid != nation
    )

    return NationView(
        turn=state.turn,
        year=state.year,
        max_turns=state.max_turns,
        me=my_nation,
        provinces=provinces,
        nations=nations,
        proposals_to_answer=tuple(
            ProposalView.model_validate(p.model_dump())
            for p in state.proposals
            if p.recipient == nation
        ),
        proposals_sent=tuple(
            ProposalView.model_validate(p.model_dump())
            for p in state.proposals
            if p.sender == nation
        ),
        last_turn_events=tuple(e for e in state.last_events if e.visible_to(nation)),
        market={
            res: PriceView(
                price=round(price, 2),
                buy=round(price * (1 + cut), 2),
                sell=round(price * (1 - cut), 2),
            )
            for res in TRADED
            for price in [market_price(state, res)]
            for cut in [market_cut(state, nation)]
        },
        rules=state.rules,
    )


def _event_view(state: GameState, nation: NationId, e: PendingEvent) -> EventView:
    spec = fortune.EVENTS_BY_ID[e.event]
    return EventView(
        id=e.id,
        event=e.event,
        title=spec.title,
        text=fortune.describe(spec, state, nation, e.province),
        province=e.province,
        options=tuple(
            OptionView(label=o.label, effects=fortune.effects_text(o)) for o in spec.options
        ),
        deadline_turn=e.turn + 1,
    )


def _general(state: GameState, province: ProvinceId) -> GeneralView | None:
    general = state.general_in(province)
    return GeneralView.model_validate(general.model_dump()) if general else None


def _mods(state: GameState, owner: NationId | None) -> Modifiers:
    return modifiers(state, owner)


def _missions(state: GameState, nation: NationId) -> tuple[MissionView, ...]:
    me = state.nations[nation]
    opened = {m.id for m in missions.open_missions(state, nation)}
    views = []
    for m in missions.missions_of(nation):
        status: Literal["done", "open", "locked"] = (
            "done" if m.id in me.missions_done else "open" if m.id in opened else "locked"
        )
        goals = tuple(
            GoalView(
                text=missions.goal_text(state, g),
                have=min(have, need),
                need=need,
                goal=g,
            )
            for g in m.goals
            for have, need in [missions.progress(state, nation, g)]
        )
        views.append(
            MissionView(
                id=m.id,
                title=m.title,
                lore=m.lore,
                goals=goals,
                reward=missions.reward_text(m),
                status=status,
                after=m.after,
            )
        )
    return tuple(views)


def _ledger(state: GameState, nation: NationId) -> tuple[LedgerLine, ...]:
    """This year's income and expenses by source. The income lines add up to
    `income_per_turn`, and the expenses to the army, council, inputs, loans and tribute."""
    land = buildings = workings = Resources()
    discontent = dict.fromkeys(Resources().amounts(), 0)
    for pid in state.provinces_of(nation):
        p = state.provinces[pid]
        if p.unrest or p.controller:
            continue
        land = land + base_output(state, pid)
        works = workings_yield(state, pid)
        workings = workings + works
        buildings = buildings + building_output(state, pid) - works
        if faith_penalty(state, pid):
            full = base_output(state, pid) + building_output(state, pid)
            kept = province_output(state, pid)
            for k, v in full.amounts().items():
                discontent[k] -= v - kept.amounts()[k]
    income = nation_income(state, nation).amounts()
    crown = {  # stability, technology, ruler, prestige, taxes, exhaustion...
        k: v - land.amounts()[k] - buildings.amounts()[k] - workings.amounts()[k] - discontent[k]
        for k, v in income.items()
    }
    factor = modifiers(state, nation).grain_upkeep_factor
    army = army_upkeep(state.rules, army_of(state, nation), factor)
    council = nation_upkeep(state, nation) - army
    me = state.nations[nation]
    lines = [
        LedgerLine(kind="income", source="land", amount=land.amounts()),
        LedgerLine(kind="income", source="buildings", amount=buildings.amounts()),
        LedgerLine(kind="income", source="workings", amount=workings.amounts()),
        LedgerLine(kind="income", source="provinces of another faith", amount=discontent),
        LedgerLine(kind="income", source="the crown's modifiers", amount=crown),
        LedgerLine(kind="expense", source="the army", amount=army.amounts()),
        LedgerLine(kind="expense", source="the council", amount=council.amounts()),
        LedgerLine(
            kind="expense", source="building inputs", amount=inputs_upkeep(state, nation).amounts()
        ),
    ]
    if me.loans:
        repay = sum(loan.yearly for loan in me.loans)
        lines.append(LedgerLine(kind="expense", source="loans", amount={"ducats": repay}))
    for t in state.treaties:
        if t.kind != TreatyKind.TRIBUTE or nation not in t.parties:
            continue
        other = t.parties[1] if t.parties[0] == nation else t.parties[0]
        paying = t.payer == nation
        lines.append(
            LedgerLine(
                kind="expense" if paying else "income",
                source=f"tribute {'to' if paying else 'from'} {state.nations[other].name}",
                amount={"ducats": t.amount},
            )
        )
    return tuple(
        LedgerLine(
            kind=line.kind, source=line.source, amount={k: v for k, v in line.amount.items() if v}
        )
        for line in lines
        if any(line.amount.values())
    )


CORRESPONDENCE = 14  # exchanges remembered per court in the view


def _correspondence(state: GameState, nation: NationId, other: NationId) -> tuple[Event, ...]:
    """The last exchanges between two courts that `nation` witnessed: letters, proposals and
    their answers, treaties, wars, gifts. Oldest first, like a letter book."""
    between = [
        e
        for e in state.diplomacy
        if nation in e.nations and other in e.nations and e.visible_to(nation)
    ]
    return tuple(between[-CORRESPONDENCE:])
