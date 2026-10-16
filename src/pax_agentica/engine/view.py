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

from pydantic import BaseModel, ConfigDict

from pax_agentica.engine.events import Event
from pax_agentica.engine.mechanics import (
    army_of,
    building_cost,
    building_output,
    building_slots,
    develop_cost,
    manpower_cap,
    nation_income,
    nation_upkeep,
    province_output,
    recruit_cost,
    research_cost,
    war_score,
)
from pax_agentica.engine.model import (
    Advisor,
    AdvisorRole,
    BuildingKind,
    GameState,
    Good,
    NationId,
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
    siege_years: int  # years of siege won against it so far
    terrain: Terrain
    good: Good
    development: int
    fort: int  # fortification level: 1 with a fort, 2 with a citadel too
    buildings: tuple[BuildingKind, ...]
    building_slots: int  # 1 + development // 4
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
    monument: int | None  # level of its monument (see rules.monuments); None if it has none
    neighbors: tuple[ProvinceId, ...]
    sea_neighbors: tuple[ProvinceId, ...]


class TreatyView(_View):
    kind: TreatyKind
    partner: NationId
    until_turn: int | None
    payer: NationId | None = None  # tribute and army limit: the side bound by it
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


class MyNation(_View):
    id: NationId
    name: str
    capital: ProvinceId
    resources: Resources
    stability: int
    income_per_turn: Resources  # production, already including the stability modifier
    army_upkeep_per_turn: Resources  # what the army eats and is paid, plus advisors' salaries
    manpower_cap: int  # the pool never grows beyond this; barracks raise it
    regiments: int
    army: dict[UnitKind, int]  # every regiment you have, by kind
    provinces: tuple[ProvinceId, ...]  # the provinces you own
    held: tuple[
        ProvinceId, ...
    ]  # where your armies stand: your own unoccupied land and what you occupy
    war_exhaustion: float  # 0 to 20: costs ducats, and stability from 10
    prestige: int
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
    stances: dict[NationId, Stance]  # the friends and rivals this court has declared (public)


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
            terrain=definition.terrain,
            good=definition.good,
            development=ps.development,
            fort=ps.fort,
            buildings=tuple(ps.buildings),
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
            recruit_cost=recruit_cost(state.rules, 1, ps.buildings),
            recruit_costs={
                kind: recruit_cost(state.rules, 1, ps.buildings, kind)
                for kind, spec in state.rules.units.items()
                if spec.requires is None or spec.requires in ps.buildings
            }
            if ps.owner == nation and not ps.controller
            else {},
            monument=ps.monument if pid in state.rules.monuments else None,
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
        manpower_cap=manpower_cap(state, nation),
        regiments=state.troops_of(nation),
        army=army_of(state, nation),
        provinces=tuple(state.provinces_of(nation)),
        held=tuple(state.held_by(nation)),
        war_exhaustion=me.war_exhaustion,
        prestige=me.prestige,
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
        rules=state.rules,
    )


def _general(state: GameState, province: ProvinceId) -> GeneralView | None:
    general = state.general_in(province)
    return GeneralView.model_validate(general.model_dump()) if general else None


def _mods(state: GameState, owner: NationId | None) -> Modifiers:
    return modifiers(state, owner)
