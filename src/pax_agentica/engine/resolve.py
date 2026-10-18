"""Turn resolution: everyone's orders in, the next state out.

All nations decide on the same snapshot (simultaneous turns, see ADR 0001); then the engine
resolves the orders in fixed phases:

1. Answers to proposals made last turn (alliances, pacts, peace, trades, calls to arms).
   Unanswered proposals expire.
2. Diplomacy: wars, cancellations, new proposals, gifts, messages.
3. Economy: recruiting, development, buildings, stability.
4. Movement between your own provinces.
5. Battles, interleaved one attack per nation at a time.
6. End of turn: income, grain upkeep (desertion if short), expiring treaties, victory.

Inside a phase, nations act in an order shuffled by the seeded RNG, so nobody always goes first,
and the same seed always produces the same game.
"""

import math
import random
from collections.abc import Iterator, Mapping

from pax_agentica.engine import fortune, missions
from pax_agentica.engine.actions import (
    Action,
    AssignGeneral,
    Attack,
    BoostStability,
    Build,
    BuildShips,
    Buy,
    CancelTreaty,
    ChooseOption,
    Convert,
    DeclareWar,
    Develop,
    Disband,
    DismissAdvisor,
    Gift,
    HireAdvisor,
    HireGeneral,
    HireMercenaries,
    Improve,
    LiftSiege,
    Move,
    Orders,
    Patronize,
    Proclaim,
    ProposeAlliance,
    ProposeCoalition,
    ProposeMarriage,
    ProposeNonAggression,
    ProposePeace,
    ProposeTrade,
    Recruit,
    RequestCallToArms,
    Research,
    Respond,
    SailFleet,
    ScrapShips,
    SeekBattle,
    SeizeColony,
    Sell,
    SendExpedition,
    SendMessage,
    SetFocus,
    SetPolicy,
    SetPosture,
    SetStance,
    SetTaxes,
    Terms,
    UpgradeBuilding,
    UpgradeMonument,
)
from pax_agentica.engine.events import Event, EventKind, EventValue
from pax_agentica.engine.mechanics import (
    BattleResult,
    army_of,
    army_strength,
    army_upkeep,
    battle_factor,
    building_consumes,
    building_cost,
    building_inputs,
    carries,
    colonies_in,
    convert_cost,
    defense_multiplier,
    develop_cost,
    discounted,
    expedition_error,
    expedition_progress,
    fight,
    fleet_pay,
    fleet_upkeep,
    focus_bonus,
    landing_sea,
    manpower_cap,
    market_price,
    market_total,
    morale,
    nation_income,
    naval_power,
    ocean_power,
    peace_cost,
    province_slots,
    recruit_cost,
    research_cost,
    sea_command,
    seize_factor,
    settlement,
    siege_levels,
    siege_modifiers,
    siege_result,
    siege_walls,
    stability_cost,
    tactic_factor,
    upgrade_cost,
    veteran,
    war_score,
)
from pax_agentica.engine.model import (
    RESOURCE_NAMES,
    TRADED,
    BuildingKind,
    Crisis,
    Expedition,
    Faith,
    Focus,
    GameState,
    General,
    Grudge,
    Loan,
    NationId,
    PendingEvent,
    Posture,
    Proposal,
    ProposalKind,
    ProvinceId,
    ProvinceState,
    Resources,
    SeaId,
    Ship,
    Stance,
    Trait,
    Treaty,
    TreatyKind,
    UnitKind,
    War,
    pair,
    share,
)
from pax_agentica.engine.realm import (
    advisor_candidates,
    advisor_hire_cost,
    advisor_salaries,
    death_chance,
    designation,
    make_ruler,
    modifiers,
)


class GameOverError(Exception):
    """Raised when asked to resolve a turn of a finished game."""


# Diplomatic events the courts remember (see GameState.diplomacy).
DIPLOMATIC = frozenset(
    {
        EventKind.MESSAGE,
        EventKind.PROPOSAL_MADE,
        EventKind.PROPOSAL_REJECTED,
        EventKind.PROPOSAL_EXPIRED,
        EventKind.PROPOSAL_COUNTERED,
        EventKind.TREATY_SIGNED,
        EventKind.TREATY_BROKEN,
        EventKind.TREATY_CANCELLED,
        EventKind.TREATY_EXPIRED,
        EventKind.WAR_DECLARED,
        EventKind.JOINED_WAR,
        EventKind.CALL_TO_ARMS_IGNORED,
        EventKind.GRUDGE,
        EventKind.PEACE_SIGNED,
        EventKind.GIFT,
        EventKind.TRADE_COMPLETED,
        EventKind.TRADE_FAILED,
        EventKind.PROVINCE_CEDED,
        EventKind.COALITION_JOINED,
        EventKind.COALITION_DISSOLVED,
    }
)


def resolve_turn(state: GameState, orders: Mapping[NationId, Orders]) -> GameState:
    """Resolve one turn. Pure: `state` is not modified; a new state is returned.

    Nations missing from `orders` simply do nothing. The new state's `last_events` holds
    everything that happened, including every rejected order and why.
    """
    if state.finished:
        raise GameOverError(f"the game is over: {state.winner} won")
    return _Resolver(state, orders).run()


class _Resolver:
    def __init__(self, state: GameState, orders: Mapping[NationId, Orders]) -> None:
        self.s = state.copy_for_update()
        self.turn = self.s.turn
        self.rng = random.Random(f"{self.s.seed}:{self.turn}")  # noqa: S311 (game dice)
        self.events: list[Event] = []
        alive = self.s.alive_nations()
        self.orders: dict[NationId, list[Action]] = {
            n: list(orders[n].actions) if n in orders else [] for n in alive
        }
        self.order = list(alive)
        self.rng.shuffle(self.order)
        self.researched: set[NationId] = set()
        self.upgraded: set[tuple[ProvinceId, BuildingKind]] = set()  # one level a year each
        # joint attacks: the provinces each one's armies came from, for the battle's tale
        self.joined: dict[tuple[NationId, ProvinceId], list[ProvinceId]] = {}
        self.flow: dict[str, int] = dict.fromkeys(TRADED, 0)  # net market purchases this year
        self.fallen: dict[NationId, int] = dict.fromkeys(self.s.nations, 0)
        self.mercenaries: dict[NationId, int] = dict.fromkeys(self.s.nations, 0)  # hired this year
        self.launched: dict[ProvinceId, int] = {}  # ships launched from each port this year
        self.patrons: set[NationId] = set()  # nations that patronised the arts this year
        self.preached: set[NationId] = set()  # nations that converted a province this year

    def run(self) -> GameState:
        self._answers()
        self._expire_proposals()
        self._diplomacy()
        self._economy()
        self._movement()
        self._combat()
        self._end_of_turn()
        self.s.last_events = self.events
        return self.s

    # ------------------------------------------------------------ helpers

    def _emit(
        self,
        kind: EventKind,
        summary: str,
        *,
        nations: tuple[NationId, ...] = (),
        province: ProvinceId | None = None,
        audience: tuple[NationId, ...] | None = None,
        extra: Mapping[str, EventValue] | None = None,
        **data: EventValue,
    ) -> None:
        event = Event(
            turn=self.turn,
            kind=kind,
            summary=summary,
            nations=nations,
            province=province,
            audience=audience,
            data={**data, **(extra or {})},
        )
        self.events.append(event)
        if kind in DIPLOMATIC and len(nations) >= 2:  # remembered between the courts
            self.s.diplomacy.append(event)
            del self.s.diplomacy[: -self.s.rules.diplomacy_log]

    def _reject(self, nation: NationId, action: Action, reason: str) -> None:
        what = action.type.replace("_", " ")
        for field in ("province", "target", "branch", "building", "resource"):
            value = getattr(action, field, None)
            if isinstance(value, str):
                name = (
                    self._pname(value)
                    if field == "province"
                    else self._name(value)
                    if field == "target" and value in self.s.nations
                    else value.replace("_", " ")
                )
                what += f" ({name})"
                break
        self._emit(
            EventKind.ORDER_REJECTED,
            f"{what} rejected: {reason}",
            nations=(nation,),
            audience=(nation,),
            action=action.model_dump_json(),
            reason=reason,
        )

    def _actions[T](self, nation: NationId, kind: type[T]) -> Iterator[T]:
        for action in self.orders[nation]:
            if isinstance(action, kind):
                yield action

    def _name(self, nation: NationId) -> str:
        return self.s.nations[nation].name

    def _pname(self, province: ProvinceId) -> str:
        return self.s.map.provinces[province].name

    def _target_error(self, me: NationId, target: NationId) -> str | None:
        if target not in self.s.nations:
            return f"there is no nation '{target}'"
        if target == me:
            return "you cannot target yourself"
        if not self.s.nations[target].alive:
            return f"{self._name(target)} no longer exists"
        return None

    def _own_error(self, me: NationId, province: ProvinceId) -> str | None:
        """For works and levies: the province must be yours, and not under occupation."""
        if province not in self.s.provinces:
            return f"there is no province '{province}'"
        p = self.s.provinces[province]
        if p.owner != me:
            return f"you do not own {self._pname(province)}"
        if p.controller:
            return f"{self._pname(province)} is occupied by {self._name(p.controller)}"
        if p.siege_by:
            return f"{self._pname(province)} is besieged by {self._name(p.siege_by)}"
        return None

    def _hold_error(self, me: NationId, province: ProvinceId) -> str | None:
        """For armies: the province must be held by you, as owner or occupier."""
        if province not in self.s.provinces:
            return f"there is no province '{province}'"
        if self.s.provinces[province].holder != me:
            return f"you do not hold {self._pname(province)}"
        return None

    def _pay(self, nation: NationId, cost: Resources) -> str | None:
        state = self.s.nations[nation]
        if not state.resources.covers(cost):
            return f"it costs {cost} and you have {state.resources}"
        state.resources = state.resources - cost
        return None

    def _change_stability(self, nation: NationId, delta: int, reason: str) -> None:
        state = self.s.nations[nation]
        rules = self.s.rules
        new = max(rules.min_stability, min(rules.max_stability, state.stability + delta))
        if new == state.stability:
            return
        state.stability = new
        self._emit(
            EventKind.STABILITY_CHANGED,
            f"{self._name(nation)}'s stability is now {new:+d} ({reason})",
            nations=(nation,),
            stability=new,
            delta=delta,
        )

    def _remember(
        self, holder: NationId, against: NationId, reason: str, grudge: tuple[int, int]
    ) -> None:
        """`holder` will not forget what `against` did, for `grudge` = (years, weight)."""
        if holder == against or not self.s.nations[holder].alive:
            return
        years, weight = grudge
        self.s.nations[holder].grudges.append(
            Grudge(against=against, reason=reason, since=self.turn, until=self.turn + years,
                   weight=weight)
        )  # fmt: skip
        self._emit(
            EventKind.GRUDGE,
            f"{self._name(holder)} will not forget that {self._name(against)} {reason}",
            nations=(holder, against),
            reason=reason,
            years=years,
        )

    def _opine(self, of: NationId, about: NationId, delta: int) -> None:
        """Change what `of` thinks of `about`, within -100 and 100."""
        if of == about or not delta:
            return
        opinions = self.s.opinions.setdefault(of, {})
        opinions[about] = max(-100, min(100, opinions.get(about, 0) + delta))

    def _terms_error(self, sender: NationId, recipient: NationId, t: Terms) -> str | None:
        """Why a peace's provinces cannot change hands, if they cannot."""
        moving = t.cede + t.demand
        if len(set(moving)) != len(moving):
            return "a province appears twice in the terms"
        capitals = {n.capital for n in self.s.nations.values() if n.alive}
        for pids, owner, receiver in ((t.cede, sender, recipient), (t.demand, recipient, sender)):
            for pid in pids:
                if pid not in self.s.provinces:
                    return f"there is no province '{pid}'"
                if self.s.provinces[pid].owner != owner:
                    return f"{self._pname(pid)} does not belong to {self._name(owner)}"
                if pid in capitals and self.s.provinces[pid].controller != receiver:
                    return (
                        f"{self._pname(pid)} is a capital: it changes hands only if "
                        f"{self._name(receiver)} occupies it"
                    )
        for pids, receiver in ((t.cede, recipient), (t.demand, sender)):
            held = set(self.s.held_by(receiver))
            waiting = set(pids)
            while waiting:
                joined = {
                    p
                    for p in waiting
                    if self.s.provinces[p].controller == receiver
                    or any(self.s.map.adjacent(p, h) for h in held)
                }
                if not joined:
                    lost = ", ".join(self._pname(p) for p in sorted(waiting))
                    return f"{lost} does not border {self._name(receiver)}"
                held |= joined
                waiting -= joined
        return None

    def _score_error(self, sender: NationId, recipient: NationId, t: Terms) -> str | None:
        """A peace may only demand what the sender's war score covers."""
        cost = peace_cost(
            self.s,
            recipient,
            provinces=t.demand,
            lump=t.receive,
            tribute=t.ask_tribute,
            army_limit=t.limit_army is not None,
        )
        if not cost:
            return None
        score = war_score(self.s, sender, recipient)
        if cost > max(0, score):
            return f"your war score ({score}) does not cover these demands (they cost {cost})"
        return None

    def _describe_terms(self, p: Proposal) -> str:
        s, r = self._name(p.sender), self._name(p.recipient)
        parts = []
        if not p.give.is_empty():
            parts.append(f"{s} pays {p.give}")
        if not p.receive.is_empty():
            parts.append(f"{r} pays {p.receive}")
        if p.cede:
            parts.append(f"{s} cedes {', '.join(self._pname(x) for x in p.cede)}")
        if p.demand:
            parts.append(f"{r} cedes {', '.join(self._pname(x) for x in p.demand)}")
        years = self.s.rules.tribute_years
        if p.pay_tribute:
            parts.append(f"{s} pays {p.pay_tribute} ducats a year for {years} years")
        if p.ask_tribute:
            parts.append(f"{r} pays {p.ask_tribute} ducats a year for {years} years")
        if p.limit_army is not None:
            parts.append(f"{r} keeps no more than {p.limit_army} regiments during the truce")
        return "; ".join(parts) if parts else "white peace"

    def _pending(self, kind: ProposalKind, sender: NationId, recipient: NationId) -> bool:
        return any(
            p.kind == kind and p.sender == sender and p.recipient == recipient
            for p in self.s.proposals
        )

    def _propose(
        self, kind: ProposalKind, sender: NationId, recipient: NationId, **terms: object
    ) -> None:
        proposal = Proposal.model_validate(
            {
                "id": self.s.next_proposal_id,
                "kind": kind,
                "sender": sender,
                "recipient": recipient,
                "turn": self.turn,
                **terms,
            }
        )
        self.s.next_proposal_id += 1
        self.s.proposals.append(proposal)
        terms_text = ""
        if kind == ProposalKind.TRADE:
            terms_text = f": gives {proposal.give}, asks for {proposal.receive}"
        elif kind == ProposalKind.PEACE:
            terms_text = f": {self._describe_terms(proposal)}"
        elif kind == ProposalKind.CALL_TO_ARMS and proposal.enemy:
            terms_text = f" against {self._name(proposal.enemy)}"
        extra: dict[str, EventValue] = {"note": proposal.note} if proposal.note else {}
        self._emit(
            EventKind.PROPOSAL_MADE,
            f"{self._name(sender)} proposes {kind.value.replace('_', ' ')} to "
            f"{self._name(recipient)}{terms_text} (proposal #{proposal.id})",
            nations=(sender, recipient),
            audience=(sender, recipient),
            proposal_id=proposal.id,
            proposal_kind=kind.value,
            extra=extra,
        )

    # ------------------------------------------------------------ phase 1: answers

    def _answers(self) -> None:
        for nation in self.order:
            for choice in self._actions(nation, ChooseOption):
                self._choose(nation, choice)
        for nation in self.order:
            for action in self._actions(nation, Respond):
                proposal = next((p for p in self.s.proposals if p.id == action.proposal_id), None)
                if proposal is None or proposal.recipient != nation:
                    self._reject(
                        nation, action, f"no pending proposal #{action.proposal_id} for you"
                    )
                    continue
                self.s.proposals.remove(proposal)
                if action.note:  # the answer in words travels as a letter
                    self._emit(
                        EventKind.MESSAGE,
                        f"Message from {self._name(nation)} to {self._name(proposal.sender)}",
                        nations=(nation, proposal.sender),
                        audience=(nation, proposal.sender),
                        sender=nation,
                        text=action.note,
                        proposal_id=proposal.id,
                    )
                if action.accept:
                    self._accept(proposal)
                elif action.counter is not None:
                    self._counter(nation, proposal, action, action.counter)
                else:
                    self._decline(proposal)

    def _choose(self, nation: NationId, a: ChooseOption) -> None:
        me = self.s.nations[nation]
        pending = next((e for e in me.pending_events if e.id == a.event_id), None)
        if pending is None:
            self._reject(nation, a, f"no pending event #{a.event_id}")
            return
        spec = fortune.EVENTS_BY_ID[pending.event]
        if a.option >= len(spec.options):
            self._reject(nation, a, f"{spec.title} has {len(spec.options)} options")
            return
        self._decide(nation, pending, a.option)

    def _decide(self, nation: NationId, pending: PendingEvent, option: int) -> None:
        """Carry out the crown's answer to an event."""
        me = self.s.nations[nation]
        me.pending_events.remove(pending)
        spec = fortune.EVENTS_BY_ID[pending.event]
        o = spec.options[option]
        gain = Resources(**{k: max(0, getattr(o, k, 0)) for k in RESOURCE_NAMES})
        cost = Resources(**{k: max(0, -getattr(o, k, 0)) for k in RESOURCE_NAMES})
        me.resources = me.resources + gain - cost.capped_by(me.resources)
        if o.stability:
            self._change_stability(nation, o.stability, spec.title.lower())
        if o.prestige:
            self._prestige(nation, o.prestige, spec.title.lower())
        if o.war_exhaustion:
            self._exhaust(nation, o.war_exhaustion)
        here = self.s.provinces.get(pending.province) if pending.province else None
        if here is not None and here.owner == nation:
            if o.development:
                here.development = max(1, here.development + o.development)
            if o.unrest:
                here.unrest = max(here.unrest, o.unrest)
            if o.regiments:
                here.take(min(here.troops, -o.regiments))
        if o.opinion:
            for other in self.s.alive_nations():
                self._opine(other, nation, o.opinion)
        if o.faith:
            old, me.faith = me.faith, o.faith
            for pid in self.s.provinces_of(nation):  # the capital and part of the realm follow
                p = self.s.provinces[pid]
                if p.faith == old and (
                    pid == me.capital or self.rng.random() < self.s.rules.faith_follow_crown
                ):
                    self._turn_faith(pid, o.faith, "it follows the crown")
        if o.loan:
            yearly, years = o.loan
            me.loans.append(Loan(yearly=yearly, until=self.turn + years))
        if o.flag and o.flag not in me.flags:
            me.flags.append(o.flag)
        if o.general_skill and (generals := self.s.generals_of(nation)):
            best = max(generals, key=lambda g: (g.skill, -g.id))
            best.skill = min(3, best.skill + o.general_skill)
        self._history_effects(nation, spec.id, option)
        self._emit(
            EventKind.EVENT_DECIDED,
            f"{me.name}, {spec.title.lower()}: {o.label.lower()}",
            nations=(nation,),
            event=spec.id,
            option=option,
        )

    # ------------------------------------------------------------ the great events of the age

    def _history(self) -> None:
        """The age's great events: each once a game, in its years, when Europe is ready; the
        crowns it falls to must decide by the end of next year. A year after the Holy League
        gathers, its fleets fight the Sultan's as one."""
        year = self.s.year
        for h in fortune.HISTORY:
            spec = h.event
            if spec.id in self.s.history or not h.first <= year <= h.last:
                continue
            if not h.ready(self.s, ""):
                continue
            crowns = [n for n in h.who(self.s) if self.s.nations[n].alive]
            if not crowns:
                continue
            self.s.history.append(spec.id)
            for nation in crowns:
                self.s.nations[nation].pending_events.append(
                    PendingEvent(id=self.s.next_event_id, event=spec.id, turn=self.turn)
                )
                self.s.next_event_id += 1
            self._emit(
                EventKind.EVENT_HAPPENED,
                f"{spec.title}: {', '.join(self._name(n) for n in crowns)} must decide",
                nations=tuple(crowns),
                event=spec.id,
                great=True,
            )
        if "holy_league" in self.s.history and "holy_league_battle" not in self.s.history:
            self._league_battle()

    def _history_effects(self, nation: NationId, event: str, option: int) -> None:
        """What a great event's answer does beyond the numbers."""
        rules = self.s.rules
        if event == "burgundy" and option in (0, 1):
            heir = nation if option == 0 else "spain"
            if not self.s.nations.get(heir) or not self.s.nations[heir].alive:
                return
            for pid in ("flanders", "holland"):
                p = self.s.provinces.get(pid)
                if p is None or p.owner is not None:
                    continue
                p.owner = heir
                self._emit(
                    EventKind.PROVINCE_CAPTURED,
                    f"{self._name(heir)} inherits {self._pname(pid)}: the Burgundian inheritance",
                    nations=(heir,),
                    province=pid,
                    inherited=True,
                )
            if option == 0 and self.s.nations.get("france") and self.s.nations["france"].alive:
                self._opine("france", nation, -25)
                self._remember("france", nation, "took the Burgundian inheritance", (15, 2))
            if option == 1:
                self._opine("spain", nation, 20)
        elif event == "cloth_of_gold" and option == 0:
            self._opine("france", "england", 25)
            self._opine("england", "france", 25)
        elif event == "vienna" and option == 0:
            if self.s.at_war(nation, "austria") or not self.s.nations["austria"].alive:
                return
            self._start_war(nation, "austria")
            self._emit(
                EventKind.WAR_DECLARED,
                f"{self._name(nation)} marches on Vienna: war with {self._name('austria')}",
                nations=(nation, "austria"),
            )
            austrian = set(self.s.provinces_of("austria"))
            vienna = self.s.map.provinces.get("vienna")
            border = sorted(
                (
                    p
                    for p in self.s.held_by(nation)
                    if austrian & set(self.s.map.provinces[p].neighbors)
                ),
                key=lambda p: (
                    (self.s.map.provinces[p].lon - vienna.lon) ** 2
                    + (self.s.map.provinces[p].lat - vienna.lat) ** 2
                    if vienna
                    else 0,
                    p,
                ),
            )
            if border:
                self.s.provinces[border[0]].add({UnitKind.ARCHERS: 8}, veterancy=0.5)
            if "vienna" in austrian:  # the city calls its burghers to the walls
                self.s.provinces["vienna"].add({UnitKind.INFANTRY: 4}, veterancy=0.0)
        elif event == "holy_league" and option == 0:
            me = self.s.nations[nation]
            if "holy_league" not in me.flags:
                me.flags.append("holy_league")
            med = [z for z, zone in self.s.map.seas.items() if zone.water.value == "mediterranean"]
            ports = [z for p in self.s.provinces_of(nation) for z in self.s.map.provinces[p].seas]
            home = max(med, key=lambda z: (ports.count(z), z))
            ships = me.ships(home)
            ships[Ship.GALLEY] += rules.league_galleys
            me.set_ships(home, ships)
            if not self.s.at_war(nation, "ottomans") and self.s.nations["ottomans"].alive:
                self._start_war(nation, "ottomans", joined_for=None)
                self._emit(
                    EventKind.WAR_DECLARED,
                    f"{self._name(nation)} joins the Holy League against {self._name('ottomans')}",
                    nations=(nation, "ottomans"),
                )

    def _league_battle(self) -> None:
        """The League's fleets in the inland sea against the Sultan's, all of them at once."""
        rules = self.s.rules
        members = [
            n
            for n, ns in self.s.nations.items()
            if ns.alive
            and "holy_league" in ns.flags
            and (war := self.s.war(n, "ottomans")) is not None
            and war.since < self.turn  # the League sails the year after it gathers
        ]
        med = [z for z, zone in self.s.map.seas.items() if zone.water.value == "mediterranean"]

        def fleet(nation: NationId) -> float:
            return sum(naval_power(self.s, nation, z) for z in med)

        league = sum(fleet(n) for n in members)
        sultan = fleet("ottomans") if self.s.nations["ottomans"].alive else 0.0
        if not members or not league or not sultan:
            return  # no League at sea this year, or no Sultan's fleet to fight
        self.s.history.append("holy_league_battle")
        lo, hi = rules.roll_min, rules.roll_max
        att = league * self.rng.uniform(lo, hi)
        dfn = sultan * morale(self.s, "ottomans") * self.rng.uniform(lo, hi)
        won = att > dfn
        ratio = min(att, dfn) / max(att, dfn)

        def sink(nation: NationId, share: float) -> int:
            me, gone = self.s.nations[nation], 0
            for z in med:
                ships = me.ships(z)
                lost = {
                    k: math.ceil(n * share) if share >= 0.5 else round(n * share)
                    for k, n in ships.items()
                }
                gone += sum(lost.values())
                me.set_ships(z, {k: ships[k] - lost[k] for k in Ship})
            return gone

        winners, losers = (members, ["ottomans"]) if won else (["ottomans"], members)
        lost_w = sum(sink(n, rules.naval_winner_loss * ratio) for n in winners)
        lost_l = sum(sink(n, rules.naval_loser_loss) for n in losers)
        for n in members:
            self._battle_counts(n, "ottomans", won=won)
        for n in winners:
            self._prestige(n, 3 * rules.prestige_battle * 2, "the battle of the Holy League")
        for n in losers:
            self._prestige(n, -3 * rules.prestige_battle * 2, "the battle of the Holy League")
        names = ", ".join(self._name(n) for n in members)
        self._emit(
            EventKind.NAVAL_BATTLE,
            f"The battle of the Holy League: the galleys of {names} against the "
            f"{self._name('ottomans')}'s. "
            f"{'The League' if won else self._name('ottomans')} wins. Ships lost: "
            f"{lost_w} to {lost_l}",
            nations=(*members, "ottomans"),
            sea="ionian",
            attacker=members[0],
            defender="ottomans",
            attacker_fleet=f"the League ({names})",
            defender_fleet="the Sultan's galleys",
            attacker_power=round(att, 1),
            defender_power=round(dfn, 1),
            attacker_won=won,
            winner_lost=lost_w,
            loser_lost=lost_l,
            great=True,
            league=True,
        )

    def _accept(self, p: Proposal) -> None:
        s, r = p.sender, p.recipient
        names = f"{self._name(s)} and {self._name(r)}"
        if not self.s.nations[s].alive:
            self._expired(p, f"{self._name(s)} no longer exists")
            return
        match p.kind:
            case ProposalKind.ALLIANCE | ProposalKind.NON_AGGRESSION:
                kind = TreatyKind(p.kind.value)
                if self.s.at_war(s, r) or self.s.treaty(s, r, kind):
                    self._expired(p, "no longer applicable")
                    return
                until = None
                if kind == TreatyKind.NON_AGGRESSION:
                    until = self.turn + self.s.rules.non_aggression_turns
                self.s.treaties.append(
                    Treaty(kind=kind, parties=pair(s, r), since=self.turn, until=until)
                )
                label = "an alliance" if kind == TreatyKind.ALLIANCE else "a non-aggression pact"
                self._opine(s, r, self.s.rules.opinion_treaty[kind.value])
                self._opine(r, s, self.s.rules.opinion_treaty[kind.value])
                self._emit(
                    EventKind.TREATY_SIGNED,
                    f"{names} sign {label}",
                    nations=(s, r),
                    treaty=kind.value,
                )
            case ProposalKind.PEACE:
                if not self.s.at_war(s, r):
                    self._expired(p, "they are no longer at war")
                    return
                if error := self._terms_error(s, r, _as_terms(p)):
                    self._expired(p, error)
                    return
                self._make_peace(s, r, p)
            case ProposalKind.TRADE:
                self._trade(p)
            case ProposalKind.MARRIAGE:
                error = self._marriage_error(s, r) or self._marriage_error(r, s)
                if error:
                    self._expired(p, error)
                    return
                self.s.treaties.append(
                    Treaty(kind=TreatyKind.MARRIAGE, parties=pair(s, r), since=self.turn)
                )
                self._opine(s, r, self.s.rules.opinion_treaty["marriage"])
                self._opine(r, s, self.s.rules.opinion_treaty["marriage"])
                self._emit(
                    EventKind.TREATY_SIGNED,
                    f"The houses of {names} are joined by a royal marriage",
                    nations=(s, r),
                    treaty=TreatyKind.MARRIAGE.value,
                )
            case ProposalKind.COALITION:
                against = p.enemy
                error = (
                    self._coalition_error(s, r, against) if against else "no one to league against"
                )
                if error or against is None:
                    self._expired(p, error or "no one to league against")
                    return
                self._join_coalition(s, r, against)
            case ProposalKind.CALL_TO_ARMS:
                enemy = p.enemy
                if enemy is None or not self.s.nations[enemy].alive or not self.s.at_war(s, enemy):
                    self._expired(p, "that war is over")
                    return
                if not self.s.at_war(r, enemy):
                    self._start_war(r, enemy, joined_for=s)

    def _marriage_error(self, nation: NationId, other: NationId) -> str | None:
        if error := self._target_error(nation, other):
            return error
        if self.s.at_war(nation, other):
            return f"you are at war with {self._name(other)}"
        if self.s.treaty(nation, other, TreatyKind.MARRIAGE):
            return "the houses are already joined"
        if len(self.s.partners(nation, TreatyKind.MARRIAGE)) >= self.s.rules.max_marriages:
            return f"{self._name(nation)} has no more heirs to marry"
        return None

    def _coalition_error(self, nation: NationId, other: NationId, against: NationId) -> str | None:
        if error := self._target_error(nation, other) or self._target_error(nation, against):
            return error
        if against in (nation, other):
            return "a league cannot stand against one of its own members"
        if self.s.at_war(nation, other):
            return f"you are at war with {self._name(other)}"
        infamy = self.s.nations[against].infamy
        if infamy < self.s.rules.coalition_infamy:
            return (
                f"{self._name(against)}'s infamy ({infamy:.0f}) does not frighten Europe yet: "
                f"a league needs {self.s.rules.coalition_infamy:.0f}"
            )
        if any(
            t.kind == TreatyKind.COALITION
            and t.against == against
            and t.parties == pair(nation, other)
            for t in self.s.treaties
        ):
            return f"you are already leagued with {self._name(other)} against {self._name(against)}"
        return None

    def _join_coalition(self, a: NationId, b: NationId, against: NationId) -> None:
        self.s.treaties.append(
            Treaty(kind=TreatyKind.COALITION, parties=pair(a, b), since=self.turn, against=against)
        )
        self._opine(a, b, self.s.rules.opinion_coalition)
        self._opine(b, a, self.s.rules.opinion_coalition)
        self._opine(against, a, -self.s.rules.opinion_coalition)
        self._opine(against, b, -self.s.rules.opinion_coalition)
        self._emit(
            EventKind.COALITION_JOINED,
            f"{self._name(a)} and {self._name(b)} league together against {self._name(against)}",
            nations=(a, b, against),
            against=against,
        )

    def league(self, against: NationId) -> set[NationId]:
        """Every court in a coalition against `against`."""
        return {
            n
            for t in self.s.treaties
            if t.kind == TreatyKind.COALITION and t.against == against
            for n in t.parties
        }

    def _expand(self, taker: NationId, province: ProvinceId) -> None:
        """Land taken from a minor or by treaty: infamy for the taker, alarm next door."""
        rules = self.s.rules
        me = self.s.nations[taker]
        added = rules.infamy_per_development * self.s.provinces[province].development
        added *= 1 - modifiers(self.s, taker).infamy_relief
        before = me.infamy
        me.infamy += added
        worried = {
            self.s.provinces[n].owner
            for n in self.s.map.all_neighbors(province)
            if self.s.provinces[n].owner not in (None, taker)
        }
        for other in sorted(o for o in worried if o is not None):
            self._opine(other, taker, round(rules.infamy_opinion * added))
        if before < rules.coalition_infamy <= me.infamy:
            self._emit(
                EventKind.INFAMY,
                f"Europe grows wary of {me.name}: its conquests (infamy {me.infamy:.0f}) may "
                f"draw a coalition against it",
                nations=(taker,),
                infamy=round(me.infamy, 1),
            )

    def _infamy_fades(self) -> None:
        rules = self.s.rules
        for nation in self.s.nations.values():
            nation.infamy = max(0.0, nation.infamy - rules.infamy_decay)
        for treaty in [t for t in self.s.treaties if t.kind == TreatyKind.COALITION]:
            target = treaty.against
            if target is None:
                continue
            gone = not self.s.nations[target].alive
            if gone or self.s.nations[target].infamy < rules.coalition_dissolves:
                self.s.treaties.remove(treaty)
                a, b = treaty.parties
                self._emit(
                    EventKind.COALITION_DISSOLVED,
                    f"The league of {self._name(a)} and {self._name(b)} against "
                    f"{self._name(target)} dissolves: there is nothing left to fear",
                    nations=(a, b, target),
                    against=target,
                )

    def _counter(self, nation: NationId, p: Proposal, a: Respond, t: Terms) -> None:
        """Reject `p` and send its sender our own terms `t` instead."""
        other = p.sender
        error = None
        if p.kind == ProposalKind.PEACE:
            if not self.s.at_war(nation, other):
                error = "you are no longer at war"
            else:
                error = self._terms_error(nation, other, t) or self._score_error(nation, other, t)
        elif p.kind == ProposalKind.TRADE:
            if t.cede or t.demand or t.pay_tribute or t.ask_tribute or t.limit_army is not None:
                error = "a trade's counter-offer can only give and receive"
            elif t.give.is_empty() and t.receive.is_empty():
                error = "an empty trade"
        else:
            error = f"a {p.kind.value.replace('_', ' ')} proposal cannot be countered"
        if not error and not self.s.nations[nation].resources.covers(t.give):
            error = f"you cannot pay {t.give}"
        if error:
            self._reject(nation, a, error)
            self._decline(p)
            return
        self._emit(
            EventKind.PROPOSAL_COUNTERED,
            f"{self._name(nation)} answers {self._name(other)}'s "
            f"{p.kind.value.replace('_', ' ')} proposal (#{p.id}) with a counter-offer",
            nations=(nation, other),
            audience=(nation, other),
            proposal_id=p.id,
            proposal_kind=p.kind.value,
        )
        self._propose(p.kind, nation, other, **_terms(t, p.kind), reply_to=p.id)

    def _decline(self, p: Proposal) -> None:
        if p.kind == ProposalKind.CALL_TO_ARMS:
            self._abandon(p)
            return
        self._emit(
            EventKind.PROPOSAL_REJECTED,
            f"{self._name(p.recipient)} rejects {self._name(p.sender)}'s "
            f"{p.kind.value.replace('_', ' ')} proposal (#{p.id})",
            nations=(p.recipient, p.sender),
            audience=(p.sender, p.recipient),
            proposal_id=p.id,
            proposal_kind=p.kind.value,
        )

    def _expired(self, p: Proposal, reason: str) -> None:
        self._emit(
            EventKind.PROPOSAL_EXPIRED,
            f"{p.kind.value.replace('_', ' ')} proposal #{p.id} from {self._name(p.sender)} to "
            f"{self._name(p.recipient)} expired: {reason}",
            nations=(p.sender, p.recipient),
            audience=(p.sender, p.recipient),
            proposal_id=p.id,
            proposal_kind=p.kind.value,
        )

    def _abandon(self, p: Proposal) -> None:
        """An ally ignored or refused a call to arms: the alliance is dissolved, publicly."""
        enemy = p.enemy
        if enemy is None or not self.s.at_war(p.sender, enemy):
            return
        alliance = self.s.treaty(p.sender, p.recipient, TreatyKind.ALLIANCE)
        if alliance is None:
            return
        self.s.treaties.remove(alliance)
        self._opine(p.sender, p.recipient, self.s.rules.opinion_call_ignored)
        self._remember(
            p.sender, p.recipient, "left it alone in a war", self.s.rules.grudge_abandoned
        )
        self._prestige(p.recipient, self.s.rules.prestige_call_ignored, "abandoned an ally")
        self._emit(
            EventKind.CALL_TO_ARMS_IGNORED,
            f"{self._name(p.recipient)} abandons its ally {self._name(p.sender)} in the war "
            f"against {self._name(enemy)}; the alliance is dissolved",
            nations=(p.recipient, p.sender, enemy),
        )

    def _expire_proposals(self) -> None:
        for p in [p for p in self.s.proposals if p.turn < self.turn]:
            self.s.proposals.remove(p)
            if p.kind == ProposalKind.CALL_TO_ARMS:
                self._abandon(p)
            else:
                self._expired(p, "no answer")

    def _make_peace(self, a: NationId, b: NationId, terms: Proposal | None = None) -> None:
        key = pair(a, b)
        self.s.wars = [w for w in self.s.wars if w.parties != key]
        until = self.turn + self.s.rules.truce_turns
        self.s.treaties.append(
            Treaty(kind=TreatyKind.TRUCE, parties=key, since=self.turn, until=until)
        )
        paid = ""
        if terms is not None:
            sender, recipient = self.s.nations[a], self.s.nations[b]
            give = terms.give.capped_by(sender.resources)
            receive = terms.receive.capped_by(recipient.resources)
            sender.resources = sender.resources - give + receive
            recipient.resources = recipient.resources - receive + give
            if not give.is_empty():
                paid += f"; {sender.name} pays {give}"
            if not receive.is_empty():
                paid += f"; {recipient.name} pays {receive}"
            for pid in terms.cede:
                self._cede(pid, a, b)
            for pid in terms.demand:
                self._cede(pid, b, a)
            if terms.cede or terms.demand:
                moved = ", ".join(self._pname(x) for x in terms.cede + terms.demand)
                paid += f"; {moved} change hands"
            years = self.s.rules.tribute_years
            for payer, amount in ((a, terms.pay_tribute), (b, terms.ask_tribute)):
                if amount:
                    self.s.treaties.append(
                        Treaty(
                            kind=TreatyKind.TRIBUTE,
                            parties=key,
                            since=self.turn,
                            until=self.turn + years,
                            payer=payer,
                            amount=amount,
                        )
                    )
                    paid += f"; {self._name(payer)} pays {amount} ducats a year for {years} years"
            if terms.limit_army is not None:
                self.s.treaties.append(
                    Treaty(
                        kind=TreatyKind.ARMY_LIMIT,
                        parties=key,
                        since=self.turn,
                        until=until,
                        payer=b,
                        amount=terms.limit_army,
                    )
                )
                paid += f"; {self._name(b)} keeps at most {terms.limit_army} regiments"
        self._return_occupied(a, b)
        for x, y in ((a, b), (b, a)):
            self._opine(x, y, self.s.rules.opinion_treaty["peace"])
        self._emit(
            EventKind.PEACE_SIGNED,
            f"{self._name(a)} and {self._name(b)} make peace{paid}; "
            f"truce until {self._year(until)}",
            nations=(a, b),
        )

    def _return_occupied(self, a: NationId, b: NationId) -> None:
        """At peace, what each side still occupies of the other goes back, and its garrison
        goes home."""
        for pid, p in self.s.provinces.items():
            if p.controller and {p.owner, p.controller} == {a, b}:
                occupier = self.s.nations[p.controller]
                occupier.resources = occupier.resources + self.s.rules.disband_refund.times(
                    p.troops
                )
                general = self.s.general_in(pid)
                if general is not None and general.nation == p.controller:
                    self._send_home(general, p.controller, pid)
                p.set_army({})
                p.controller = None

    def _send_home(self, general: General, nation: NationId, leaving: ProvinceId) -> None:
        free = [x for x in self.s.held_by(nation) if x != leaving and not self.s.general_in(x)]
        capital = self.s.nations[nation].capital
        home = capital if capital in free else (free[0] if free else None)
        if home is None:
            self.s.generals.remove(general)
        else:
            general.province = home

    def _cede(self, province: ProvinceId, frm: NationId, to: NationId) -> None:
        """Hand a province over by treaty. If the receiver occupies it, its garrison stays;
        otherwise the old garrison goes home and its general rides back."""
        state = self.s.provinces[province]
        if state.controller != to:
            giver = self.s.nations[frm]
            giver.resources = giver.resources + self.s.rules.disband_refund.times(state.troops)
            state.set_army({})
            general = self.s.general_in(province)
            if general is not None:
                self._send_home(general, frm, province)
        state.owner = to
        state.controller = None
        self._expand(to, province)
        state.unrest = self.s.rules.ceded_unrest_turns
        if state.faith is not None and state.faith != self.s.nations[to].faith:
            state.unrest += self.s.rules.faith_conquest_unrest
        self._opine(frm, to, self.s.rules.opinion_province_taken // 2)
        self._remember(frm, to, f"took {self._pname(province)}", self.s.rules.grudge_land)
        self._emit(
            EventKind.PROVINCE_CEDED,
            f"{self._name(frm)} cedes {self._pname(province)} to {self._name(to)}",
            nations=(frm, to),
            province=province,
        )
        self._prestige(to, self.s.rules.prestige_province, "land won by treaty")
        self._prestige(frm, -self.s.rules.prestige_province, "land lost by treaty")
        self._after_loss(frm, province, to)

    def _trade(self, p: Proposal) -> None:
        s, r = self.s.nations[p.sender], self.s.nations[p.recipient]
        reason = None
        if self.s.at_war(p.sender, p.recipient):
            reason = "they are at war"
        elif not s.resources.covers(p.give):
            reason = f"{s.name} can no longer pay {p.give}"
        elif not r.resources.covers(p.receive):
            reason = f"{r.name} cannot pay {p.receive}"
        if reason:
            self._emit(
                EventKind.TRADE_FAILED,
                f"Trade #{p.id} between {s.name} and {r.name} failed: {reason}",
                nations=(p.sender, p.recipient),
                audience=(p.sender, p.recipient),
            )
            return
        s.resources = s.resources - p.give + p.receive
        r.resources = r.resources - p.receive + p.give
        self._opine(p.sender, p.recipient, self.s.rules.opinion_trade)
        self._opine(p.recipient, p.sender, self.s.rules.opinion_trade)
        self._emit(
            EventKind.TRADE_COMPLETED,
            f"{s.name} trades {p.give} to {r.name} for {p.receive}",
            nations=(p.sender, p.recipient),
            extra=_flat("give", p.give) | _flat("receive", p.receive),
        )

    def _start_war(
        self, attacker: NationId, defender: NationId, *, joined_for: NationId | None = None
    ) -> None:
        key = pair(attacker, defender)
        broken = [t for t in self.s.treaties if t.parties == key]
        for treaty in broken:
            self.s.treaties.remove(treaty)
            self._emit(
                EventKind.TREATY_BROKEN,
                f"{self._name(attacker)} breaks its {treaty.kind.value.replace('_', ' ')} "
                f"with {self._name(defender)}",
                nations=(attacker, defender),
                treaty=treaty.kind.value,
            )
        rules = self.s.rules
        if broken:
            kinds = " and the ".join(t.kind.value.replace("_", " ") for t in broken)
            self._remember(
                defender, attacker, f"broke the {kinds} to make war", rules.grudge_betrayal
            )
        elif joined_for is None:
            self._remember(defender, attacker, "declared war on it", rules.grudge_war)
        if broken:
            penalty = modifiers(self.s, attacker).treaty_break_penalty
            self._change_stability(attacker, -penalty, "broke a treaty")
            self._prestige(attacker, self.s.rules.prestige_treaty_broken, "broke a treaty")
            for other in self.s.alive_nations():
                if other not in key:
                    self._opine(other, attacker, rules.opinion_betrayal)
            self._opine(defender, attacker, rules.opinion_betrayal * 2)
        self._opine(defender, attacker, rules.opinion_war_declared)
        self._opine(attacker, defender, rules.opinion_war_declared // 2)  # an enemy is no friend
        if joined_for is not None:
            self._opine(joined_for, attacker, rules.opinion_call_answered)
        self.s.wars.append(War(parties=key, since=self.turn))
        if joined_for is not None:
            self._emit(
                EventKind.JOINED_WAR,
                f"{self._name(attacker)} honours its alliance with {self._name(joined_for)} "
                f"and declares war on {self._name(defender)}",
                nations=(attacker, defender, joined_for),
            )
            return
        self._emit(
            EventKind.WAR_DECLARED,
            f"{self._name(attacker)} declares war on {self._name(defender)}",
            nations=(attacker, defender),
        )
        if attacker in self.league(defender):  # a member strikes: the others are invited along
            for member in sorted(self.league(defender) - {attacker}):
                if self.s.nations[member].alive and not self.s.at_war(member, defender):
                    self._propose(
                        ProposalKind.CALL_TO_ARMS,
                        attacker,
                        member,
                        enemy=defender,
                        note="The league marches. Join us.",
                    )
        league = self.league(attacker)
        if defender in league:  # the coalition answers at once, without being asked
            for member in sorted(league - {defender}):
                if self.s.nations[member].alive and not self.s.at_war(member, attacker):
                    self._start_war(member, attacker, joined_for=defender)
        for ally in self.s.partners(defender, TreatyKind.ALLIANCE):
            if ally != attacker and not self.s.at_war(ally, attacker):
                self._propose(ProposalKind.CALL_TO_ARMS, defender, ally, enemy=attacker)

    # ------------------------------------------------------------ phase 2: diplomacy

    def _diplomacy(self) -> None:
        for nation in self.order:
            for action in self.orders[nation]:
                match action:
                    case DeclareWar():
                        self._declare_war(nation, action)
                    case CancelTreaty():
                        self._cancel(nation, action)
                    case (
                        ProposeAlliance()
                        | ProposeNonAggression()
                        | ProposePeace()
                        | ProposeMarriage()
                        | ProposeCoalition()
                    ):
                        self._propose_treaty(nation, action)
                    case ProposeTrade():
                        self._propose_trade(nation, action)
                    case RequestCallToArms():
                        self._request_call(nation, action)
                    case Gift():
                        self._gift(nation, action)
                    case SendMessage():
                        self._message(nation, action)
                    case SetStance():
                        self._stance(nation, action)
                    case Proclaim():
                        self._emit(
                            EventKind.PROCLAMATION,
                            f"{self._name(nation)} proclaims to all Europe",
                            nations=(nation,),
                            sender=nation,
                            text=action.text,
                        )
                    case _:
                        pass

    def _declare_war(self, nation: NationId, a: DeclareWar) -> None:
        if error := self._target_error(nation, a.target):
            self._reject(nation, a, error)
        elif self.s.at_war(nation, a.target):
            self._reject(nation, a, f"already at war with {self._name(a.target)}")
        else:
            self._start_war(nation, a.target)

    def _cancel(self, nation: NationId, a: CancelTreaty) -> None:
        if error := self._target_error(nation, a.target):
            self._reject(nation, a, error)
            return
        key = pair(nation, a.target)
        ending = [t for t in self.s.treaties if t.parties == key and t.kind == TreatyKind(a.kind)]
        if not ending:
            self._reject(nation, a, f"no {a.kind.replace('_', ' ')} with {self._name(a.target)}")
            return
        for treaty in ending:
            self.s.treaties.remove(treaty)
        self._emit(
            EventKind.TREATY_CANCELLED,
            f"{self._name(nation)} ends its {a.kind.replace('_', ' ')} with {self._name(a.target)}",
            nations=(nation, a.target),
            treaty=a.kind,
        )

    def _propose_treaty(
        self,
        nation: NationId,
        a: ProposeAlliance
        | ProposeNonAggression
        | ProposePeace
        | ProposeMarriage
        | ProposeCoalition,
    ) -> None:
        if error := self._target_error(nation, a.target):
            self._reject(nation, a, error)
            return
        at_war = self.s.at_war(nation, a.target)
        match a:
            case ProposePeace():
                kind = ProposalKind.PEACE
                if not at_war:
                    self._reject(nation, a, f"you are not at war with {self._name(a.target)}")
                    return
            case ProposeAlliance():
                kind = ProposalKind.ALLIANCE
            case ProposeNonAggression():
                kind = ProposalKind.NON_AGGRESSION
            case ProposeMarriage():
                kind = ProposalKind.MARRIAGE
                if error := self._marriage_error(nation, a.target):
                    self._reject(nation, a, error)
                    return
            case ProposeCoalition():
                kind = ProposalKind.COALITION
                if error := self._coalition_error(nation, a.target, a.against):
                    self._reject(nation, a, error)
                    return
                if self._pending(kind, nation, a.target):
                    self._reject(nation, a, "you already have that proposal pending")
                    return
                self._propose(kind, nation, a.target, enemy=a.against, note=a.note)
                return
        if kind != ProposalKind.PEACE:
            if at_war:
                self._reject(nation, a, f"you are at war with {self._name(a.target)}")
                return
            if self.s.treaty(nation, a.target, TreatyKind(kind.value)):
                self._reject(nation, a, "that treaty is already in force")
                return
        if self._pending(kind, nation, a.target):
            self._reject(nation, a, "you already have that proposal pending")
            return
        if isinstance(a, ProposePeace):
            if not self.s.nations[nation].resources.covers(a.give):
                self._reject(nation, a, f"you cannot pay {a.give}")
                return
            if error := self._terms_error(nation, a.target, a) or self._score_error(
                nation, a.target, a
            ):
                self._reject(nation, a, error)
                return
            self._propose(kind, nation, a.target, **_terms(a, kind))
            return
        self._propose(kind, nation, a.target, note=a.note)

    def _request_call(self, nation: NationId, a: RequestCallToArms) -> None:
        error = self._target_error(nation, a.target) or self._target_error(nation, a.enemy)
        if not error and not self.s.treaty(nation, a.target, TreatyKind.ALLIANCE):
            error = f"{self._name(a.target)} is not your ally"
        if not error and not self.s.at_war(nation, a.enemy):
            error = f"you are not at war with {self._name(a.enemy)}"
        if not error and self.s.at_war(a.target, a.enemy):
            error = f"{self._name(a.target)} is already at war with {self._name(a.enemy)}"
        if not error and self._pending(ProposalKind.CALL_TO_ARMS, nation, a.target):
            error = "you already have a call to arms pending"
        if error:
            self._reject(nation, a, error)
            return
        self._propose(ProposalKind.CALL_TO_ARMS, nation, a.target, enemy=a.enemy, note=a.note)

    def _propose_trade(self, nation: NationId, a: ProposeTrade) -> None:
        if error := self._target_error(nation, a.target):
            self._reject(nation, a, error)
        elif self.s.at_war(nation, a.target):
            self._reject(nation, a, f"you are at war with {self._name(a.target)}")
        elif a.give.is_empty() and a.receive.is_empty():
            self._reject(nation, a, "an empty trade")
        elif not self.s.nations[nation].resources.covers(a.give):
            self._reject(nation, a, f"you cannot pay {a.give}")
        else:
            self._propose(
                ProposalKind.TRADE, nation, a.target, give=a.give, receive=a.receive, note=a.note
            )

    def _gift(self, nation: NationId, a: Gift) -> None:
        if error := self._target_error(nation, a.target):
            self._reject(nation, a, error)
            return
        if a.resources.is_empty():
            self._reject(nation, a, "an empty gift")
            return
        if error := self._pay(nation, a.resources):
            self._reject(nation, a, error)
            return
        target = self.s.nations[a.target]
        target.resources = target.resources + a.resources
        rules = self.s.rules
        worth = sum(
            n * w for n, w in zip(a.resources.amounts().values(), (1, 3, 2, 1, 2, 3), strict=True)
        )
        self._opine(
            a.target, nation, min(rules.opinion_gift_max, worth // rules.opinion_gift_per_ducats)
        )
        self._emit(
            EventKind.GIFT,
            f"{self._name(nation)} sends {a.resources} to {target.name}",
            nations=(nation, a.target),
            extra=_flat("gift", a.resources),
        )

    def _stance(self, nation: NationId, a: SetStance) -> None:
        if error := self._target_error(nation, a.target):
            self._reject(nation, a, error)
            return
        stances = self.s.nations[nation].stances
        if stances.get(a.target, Stance.NEUTRAL) == a.stance:
            self._reject(nation, a, f"{self._name(a.target)} is already your {a.stance.value}")
            return
        rules = self.s.rules
        limit = {Stance.RIVAL: rules.max_rivals, Stance.FRIEND: rules.max_friends}.get(a.stance)
        if limit is not None and sum(1 for v in stances.values() if v == a.stance) >= limit:
            self._reject(nation, a, f"you already have {limit} {a.stance.value}s")
            return
        if a.stance == Stance.NEUTRAL:
            del stances[a.target]
            words = f"no longer counts {self._name(a.target)} friend or rival"
        else:
            stances[a.target] = a.stance
            words = f"names {self._name(a.target)} its {a.stance.value}"
        self._emit(
            EventKind.STANCE_CHANGED,
            f"{self._name(nation)} {words}",
            nations=(nation, a.target),
            stance=a.stance.value,
        )

    def _message(self, nation: NationId, a: SendMessage) -> None:
        if error := self._target_error(nation, a.target):
            self._reject(nation, a, error)
            return
        self._emit(
            EventKind.MESSAGE,
            f"Message from {self._name(nation)} to {self._name(a.target)}",
            nations=(nation, a.target),
            audience=(nation, a.target),
            sender=nation,
            text=a.text,
        )

    # ------------------------------------------------------------ phase 3: economy

    def _economy(self) -> None:
        rules = self.s.rules
        for nation in self.order:  # the market opens first: what is bought can be spent
            for action in self.orders[nation]:
                if isinstance(action, Buy | Sell):
                    self._market(nation, action)
        for nation in self.order:
            for action in self.orders[nation]:
                match action:
                    case Recruit():
                        self._recruit(nation, action)
                    case HireMercenaries():
                        self._hire_mercenaries(nation, action)
                    case Patronize():
                        self._patronize(nation, action)
                    case SetTaxes():
                        self._set_taxes(nation, action)
                    case Develop():
                        self._develop(nation, action)
                    case Disband():
                        self._disband(nation, action)
                    case Build():
                        self._build(nation, action)
                    case UpgradeBuilding():
                        self._upgrade_building(nation, action)
                    case UpgradeMonument():
                        self._upgrade_monument(nation, action)
                    case Improve():
                        self._improve(nation, action)
                    case SetFocus():
                        self._set_focus(nation, action)
                    case SetPolicy():
                        self._set_policy(nation, action)
                    case BuildShips():
                        self._build_ships(nation, action)
                    case SendExpedition():
                        self._send_expedition(nation, action)
                    case SeizeColony():
                        self._seize_colony(nation, action)
                    case ScrapShips():
                        here = self.s.nations[nation].ships(action.sea)
                        if here[action.ship] < action.count:
                            have, sea = here[action.ship], self._sea(action.sea)
                            self._reject(
                                nation, action, f"only {have} {self._ships(action.ship)} in {sea}"
                            )
                        else:
                            here[action.ship] -= action.count
                            self.s.nations[nation].set_ships(action.sea, here)
                    case SetPosture():
                        if error := self._hold_error(nation, action.province):
                            self._reject(nation, action, error)
                        else:
                            self.s.provinces[action.province].posture = action.posture
                    case Convert():
                        self._convert(nation, action)
                    case Research():
                        self._research(nation, action)
                    case HireGeneral():
                        self._hire(nation, action)
                    case AssignGeneral():
                        self._assign(nation, action)
                    case HireAdvisor():
                        self._hire_advisor(nation, action)
                    case DismissAdvisor():
                        self._dismiss_advisor(nation, action)
                    case BoostStability():
                        if self.s.nations[nation].stability >= rules.max_stability:
                            self._reject(nation, action, "stability is already at its maximum")
                        elif error := self._pay(
                            nation,
                            stability_cost(rules, modifiers(self.s, nation).stability_discount),
                        ):
                            self._reject(nation, action, error)
                        else:
                            self._change_stability(nation, 1, "investment")
                    case _:
                        pass

    def _market(self, nation: NationId, a: Buy | Sell) -> None:
        me = self.s.nations[nation]
        buying = isinstance(a, Buy)
        total = market_total(self.s, a.resource, a.amount, buying=buying, nation=nation)
        goods = Resources(**{a.resource: a.amount})
        if buying:
            if error := self._pay(nation, Resources(ducats=total)):
                self._reject(nation, a, error)
                return
            me.resources = me.resources + goods
            self.flow[a.resource] += a.amount
        else:
            if not me.resources.covers(goods):
                held = getattr(me.resources, a.resource)
                self._reject(nation, a, f"you have only {held} {a.resource}")
                return
            me.resources = me.resources - goods + Resources(ducats=total)
            self.flow[a.resource] -= a.amount
        self._emit(
            EventKind.MARKET_TRADE,
            f"{me.name} {'buys' if buying else 'sells'} {a.amount} {a.resource} for {total} ducats",
            nations=(nation,),
            audience=(nation,),
            resource=a.resource,
            amount=a.amount,
            ducats=total,
        )

    def _move_prices(self) -> None:
        """What all Europe bought and sold this year moves the prices; they drift back
        towards their usual level."""
        rules = self.s.rules
        dearer = {"ice_age": {"grain": 1.6}, "price_revolution": dict.fromkeys(TRADED, 1.4)}
        for res in TRADED:
            base = rules.market_prices[res] * dearer.get(self.s.crisis_now() or "", {}).get(res, 1)
            price = market_price(self.s, res)
            price *= 1 + rules.market_elasticity * self.flow[res] / rules.market_depth
            price += (base - price) * rules.market_reversion
            price = max(base * rules.market_floor, min(base * rules.market_ceiling, price))
            self.s.market[res] = round(price, 3)

    def _army_limit_error(self, nation: NationId, regiments: int) -> str | None:
        for limit in self.s.treaties:
            bound = limit.kind == TreatyKind.ARMY_LIMIT and limit.payer == nation
            if bound and self.s.troops_of(nation) + regiments > limit.amount:
                other = limit.parties[1] if limit.parties[0] == nation else limit.parties[0]
                return (
                    f"the peace with {self._name(other)} limits your army to "
                    f"{limit.amount} regiments"
                )
        return None

    def _recruit(self, nation: NationId, a: Recruit) -> None:
        rules = self.s.rules
        if error := self._own_error(nation, a.province):
            self._reject(nation, a, error)
            return
        province = self.s.provinces[a.province]
        spec = rules.units[a.unit]
        if spec.requires and spec.requires not in province.buildings:
            needed = rules.buildings[spec.requires].name.lower()
            self._reject(nation, a, f"{spec.name.lower()} need {_article(needed)} in the province")
            return
        if error := self._army_limit_error(nation, a.regiments):
            self._reject(nation, a, error)
            return
        arms = modifiers(self.s, nation).arms_manufactory
        cost = recruit_cost(rules, a.regiments, province.buildings, a.unit, arms, nation)
        if error := self._pay(nation, cost):
            self._reject(nation, a, error)
            return
        province.add({a.unit: a.regiments}, veterancy=0.0)  # raw recruits
        self._emit(
            EventKind.RECRUITED,
            f"{self._name(nation)} recruits {a.regiments} {spec.name.lower()} in "
            f"{self._pname(a.province)}",
            nations=(nation,),
            province=a.province,
            audience=(nation,),
            regiments=a.regiments,
            unit=a.unit.value,
        )

    def _hire_mercenaries(self, nation: NationId, a: HireMercenaries) -> None:
        rules = self.s.rules
        if error := self._own_error(nation, a.province):
            self._reject(nation, a, error)
            return
        left = rules.mercenary_limit - self.mercenaries[nation]
        if a.regiments > left:
            self._reject(nation, a, f"only {left} more mercenary regiments are for hire this year")
            return
        if error := self._army_limit_error(nation, a.regiments):
            self._reject(nation, a, error)
            return
        if error := self._pay(nation, Resources(ducats=rules.mercenary_cost * a.regiments)):
            self._reject(nation, a, error)
            return
        self.mercenaries[nation] += a.regiments
        self.s.provinces[a.province].add(
            {UnitKind.INFANTRY: a.regiments}, veterancy=rules.mercenary_veterancy
        )
        self._emit(
            EventKind.MERCENARIES_HIRED,
            f"{self._name(nation)} hires {a.regiments} regiments of mercenaries in "
            f"{self._pname(a.province)}",
            nations=(nation,),
            province=a.province,
            audience=(nation,),
            regiments=a.regiments,
        )

    def _patronize(self, nation: NationId, a: Patronize) -> None:
        rules = self.s.rules
        me = self.s.nations[nation]
        if nation in self.patrons:
            self._reject(nation, a, "the court has already patronised the arts this year")
            return
        if me.prestige >= rules.prestige_max:
            self._reject(nation, a, "prestige is already at its height")
            return
        cost = rules.patronage_base + rules.patronage_per_prestige * me.prestige
        if error := self._pay(nation, Resources(ducats=cost)):
            self._reject(nation, a, error)
            return
        self.patrons.add(nation)
        self._emit(
            EventKind.PATRONAGE,
            f"{me.name} spends {cost} ducats on painters, chapels and feasts",
            nations=(nation,),
            audience=(nation,),
            ducats=cost,
        )
        self._prestige(nation, rules.patronage_prestige, "patronage of the arts")

    def _set_taxes(self, nation: NationId, a: SetTaxes) -> None:
        me = self.s.nations[nation]
        if a.level == me.tax:
            return
        me.tax = a.level
        word = {-2: "very low", -1: "low", 0: "normal", 1: "high", 2: "very high"}[a.level]
        self._emit(
            EventKind.TAXES_SET,
            f"{me.name} sets its taxes {word}",
            nations=(nation,),
            audience=(nation,),
            level=a.level,
        )

    def _taxes(self) -> None:
        """High taxes may cost a point of stability a year; low ones may win one."""
        rules = self.s.rules
        for nation in self.s.alive_nations():
            tax = self.s.nations[nation].tax
            if not tax or self.rng.random() >= rules.tax_stability_chance.get(abs(tax), 0.0):
                continue
            if tax > 0:
                self._change_stability(nation, -1, "the people resent their taxes")
            else:
                self._change_stability(nation, 1, "light taxes content the people")

    def _missions(self) -> None:
        """A mission completes at the end of the year in which all its goals hold."""
        for nation in self.s.alive_nations():
            me = self.s.nations[nation]
            for m in missions.open_missions(self.s, nation):
                if not all(missions.done(self.s, nation, g) for g in m.goals):
                    continue
                me.missions_done.append(m.id)
                me.resources = me.resources + Resources(ducats=m.ducats)
                self._emit(
                    EventKind.MISSION_COMPLETED,
                    f"{me.name} fulfils an ambition: {m.title}",
                    nations=(nation,),
                    mission=m.id,
                    reward=missions.reward_text(m),
                )
                if m.prestige:
                    self._prestige(nation, m.prestige, m.title)
                if m.stability:
                    self._change_stability(nation, m.stability, m.title)

    def _convert(self, nation: NationId, a: Convert) -> None:
        if error := self._own_error(nation, a.province):
            self._reject(nation, a, error)
            return
        p = self.s.provinces[a.province]
        faith = self.s.nations[nation].faith
        if p.faith == faith:
            self._reject(nation, a, f"{self._pname(a.province)} already shares your faith")
            return
        if nation in self.preached:
            self._reject(nation, a, "your preachers can convert one province a year")
            return
        if error := self._pay(nation, convert_cost(self.s.rules, p.development)):
            self._reject(nation, a, error)
            return
        self.preached.add(nation)
        self._turn_faith(a.province, faith, "preachers")

    def _turn_faith(self, province: ProvinceId, faith: Faith, why: str) -> None:
        p = self.s.provinces[province]
        p.faith = faith
        self._emit(
            EventKind.PROVINCE_CONVERTED,
            f"{self._pname(province)} turns {faith.value} ({why})",
            nations=(p.owner,) if p.owner else (),
            province=province,
            audience=(p.owner,) if p.owner else None,
            faith=faith.value,
        )

    def _faiths(self) -> None:
        """Year by year, the people of a province may come round to their ruler's faith."""
        chance = self.s.rules.faith_conversion_chance
        for pid in sorted(self.s.provinces):
            p = self.s.provinces[pid]
            if p.owner is None or p.controller or p.faith is None:
                continue
            faith = self.s.nations[p.owner].faith
            if p.faith != faith and self.rng.random() < chance:
                self._turn_faith(pid, faith, "the people come round")

    def _improve(self, nation: NationId, a: Improve) -> None:
        rules = self.s.rules
        if error := self._own_error(nation, a.province):
            self._reject(nation, a, error)
            return
        province = self.s.provinces[a.province]
        good = self.s.map.provinces[a.province].good
        name = rules.workings[good]
        if province.workings >= rules.max_workings:
            self._reject(
                nation, a, f"the {name.lower()} of {self._pname(a.province)} are at their best"
            )
            return
        level = province.workings + 1
        if error := self._pay(nation, rules.improve_cost.times(level)):
            self._reject(nation, a, error)
            return
        province.workings = level
        self._emit(
            EventKind.IMPROVED,
            f"{self._name(nation)} improves the {name.lower()} of {self._pname(a.province)} to "
            f"level {level}",
            nations=(nation,),
            province=a.province,
            audience=(nation,),
            level=level,
        )

    def _send_expedition(self, nation: NationId, a: SendExpedition) -> None:
        if error := expedition_error(self.s, nation, a.region):
            self._reject(nation, a, error)
            return
        if error := self._pay(nation, self.s.rules.expedition_cost):
            self._reject(nation, a, error)
            return
        self.s.nations[nation].expeditions.append(Expedition(region=a.region, since=self.turn))
        name = self.s.rules.regions[a.region].name
        self._emit(
            EventKind.EXPEDITION_SENT,
            f"{self._name(nation)} sends an expedition to {name}",
            nations=(nation,),
            region=a.region.value,
        )

    def _seize_colony(self, nation: NationId, a: SeizeColony) -> None:
        rules = self.s.rules
        name = rules.regions[a.region].name
        if a.enemy not in self.s.nations:
            self._reject(nation, a, f"there is no realm '{a.enemy}'")
            return
        war = self.s.war(nation, a.enemy)
        if war is None:
            self._reject(nation, a, f"you are not at war with {self._name(a.enemy)}")
            return
        enemy = self.s.nations[a.enemy]
        if not enemy.colonies.get(a.region):
            self._reject(nation, a, f"{self._name(a.enemy)} holds no colony in {name}")
            return
        if any(
            e.kind == EventKind.COLONY_SEIZED
            and e.data.get("from") == a.enemy
            and nation in e.nations
            for e in self.events
        ):
            self._reject(nation, a, "one colony a year from each enemy")
            return
        mine = ocean_power(self.s, nation)
        theirs = ocean_power(self.s, a.enemy)
        need = seize_factor(self.s, nation)
        if mine < rules.expedition_ships or mine < need * theirs:
            self._reject(
                nation,
                a,
                f"your Atlantic fleet ({mine:.1f}) must be {need:g} times {self._name(a.enemy)}'s "
                f"({theirs:.1f}) to take its colonies",
            )
            return
        enemy.colonies[a.region] -= 1
        if not enemy.colonies[a.region]:
            del enemy.colonies[a.region]
        me = self.s.nations[nation]
        me.colonies[a.region] = me.colonies.get(a.region, 0) + 1
        self._prestige(nation, rules.prestige_colony, f"a colony in {name} taken")
        self._prestige(a.enemy, -rules.prestige_colony, f"a colony in {name} lost")
        self._emit(
            EventKind.COLONY_SEIZED,
            f"{self._name(nation)} takes a colony in {name} from {self._name(a.enemy)}",
            nations=(nation, a.enemy),
            region=a.region.value,
            extra={"from": a.enemy},
        )

    def _expeditions(self) -> None:
        """Every expedition rolls its year: a die, the crown's ships and its way, the region's
        hardness. At 100% a colony is founded, if a place is left."""
        rules = self.s.rules
        for nation in self.order:
            me = self.s.nations[nation]
            if not me.alive:
                continue
            for exp in list(me.expeditions):
                spec = rules.regions[exp.region]
                if colonies_in(self.s, exp.region) >= spec.slots:
                    me.expeditions.remove(exp)
                    self._emit(
                        EventKind.EXPEDITION_LOST,
                        f"{self._name(nation)}'s expedition to {spec.name} finds every place "
                        "taken and comes home with nothing",
                        nations=(nation,),
                        region=exp.region.value,
                    )
                    continue
                die = self.rng.randint(1, 6)
                gain = max(5, expedition_progress(self.s, nation, exp.region) + 5 * die)
                exp.progress = min(100, exp.progress + gain)
                if exp.progress < 100:
                    continue
                me.expeditions.remove(exp)
                me.colonies[exp.region] = me.colonies.get(exp.region, 0) + 1
                self._prestige(nation, rules.prestige_colony, f"a colony founded in {spec.name}")
                self._emit(
                    EventKind.COLONY_FOUNDED,
                    f"{self._name(nation)} founds a colony in {spec.name}: {spec.goods} will "
                    "sail home",
                    nations=(nation,),
                    region=exp.region.value,
                    colonies=me.colonies[exp.region],
                )

    def _ships(self, kind: Ship) -> str:
        return self.s.rules.ships[kind].name.lower()

    def _build_ships(self, nation: NationId, a: BuildShips) -> None:
        rules = self.s.rules
        if error := self._own_error(nation, a.province):
            self._reject(nation, a, error)
            return
        where = self._pname(a.province)
        seas = self.s.map.provinces[a.province].seas
        sea = a.sea or (seas[0] if seas else None)
        if sea is None or sea not in seas:
            self._reject(nation, a, f"{where} has no port on {self._sea(sea)}")
            return
        province = self.s.provinces[a.province]
        if province.siege_by is not None:
            self._reject(nation, a, f"{where} is besieged")
            return
        mods = modifiers(self.s, nation)
        room = rules.ships_per_port + mods.yards + province.development // 3
        if (held := designation(self.s, a.province)) and held == (Focus.SHIPYARD, held[1]):
            room += rules.shipyard_yards if held[1] >= 2 else 0
        room -= self.launched.get(a.province, 0)
        if a.count > room:
            self._reject(
                nation,
                a,
                f"the yards of {where} can launch only {max(0, room)} more ships this year",
            )
            return
        spec = rules.ships[a.ship]
        if error := self._pay(nation, discounted(spec.cost, mods.ship_discount).times(a.count)):
            self._reject(nation, a, error)
            return
        self.launched[a.province] = self.launched.get(a.province, 0) + a.count
        me = self.s.nations[nation]
        fleet = me.ships(sea)
        fleet[a.ship] += a.count
        me.set_ships(sea, fleet)
        self._emit(
            EventKind.SHIPS_BUILT,
            f"{self._name(nation)} launches {a.count} {spec.name.lower()} from {where} into "
            f"{self._sea(sea)}",
            nations=(nation,),
            province=a.province,
            sea=sea,
            ship=a.ship.value,
            count=a.count,
        )

    def _set_policy(self, nation: NationId, a: SetPolicy) -> None:
        rules, me = self.s.rules, self.s.nations[nation]
        sides = rules.policies[a.axis]
        now = me.policies.get(a.axis)
        if now == a.side:
            self._reject(nation, a, f"{sides[a.side].name} is already the realm's policy")
            return
        since = me.policy_since.get(a.axis)
        if since is not None and self.turn < since + rules.policy_years:
            until = rules.start_year + since + rules.policy_years - 1
            self._reject(nation, a, f"{sides[now or 0].name} stands until {until}")
            return
        me.policies[a.axis] = a.side
        me.policy_since[a.axis] = self.turn
        if now is not None:  # a change of course unsettles the realm
            self._change_stability(nation, -rules.policy_stability, "a change of policy")
        self._emit(
            EventKind.POLICY_SET,
            f"{self._name(nation)} adopts {sides[a.side].name}",
            nations=(nation,),
            axis=a.axis.value,
            policy=sides[a.side].name,
        )

    def _set_focus(self, nation: NationId, a: SetFocus) -> None:
        rules = self.s.rules
        if error := self._own_error(nation, a.province):
            self._reject(nation, a, error)
            return
        province = self.s.provinces[a.province]
        where = self._pname(a.province)
        if a.focus == Focus.SHIPYARD and not self.s.map.provinces[a.province].seas:
            self._reject(nation, a, f"{where} has no coast for a shipyard")
            return
        if province.focus == a.focus:
            self._reject(nation, a, f"{where} is already given to {a.focus.value}")
            return
        since = province.focus_since
        if since is not None and self.turn < since + rules.focus_years:
            until = rules.start_year + since + rules.focus_years - 1
            self._reject(nation, a, f"{where} keeps its focus on {province.focus} until {until}")
            return
        if error := self._pay(nation, rules.focus_cost):
            self._reject(nation, a, error)
            return
        province.focus, province.focus_since = a.focus, self.turn
        self._emit(
            EventKind.FOCUS_SET,
            f"{self._name(nation)} turns {where} to {a.focus.value}",
            nations=(nation,),
            province=a.province,
            audience=(nation,),
            focus=a.focus.value,
        )

    def _upgrade_monument(self, nation: NationId, a: UpgradeMonument) -> None:
        rules = self.s.rules
        if error := self._own_error(nation, a.province):
            self._reject(nation, a, error)
            return
        spec = rules.monuments.get(a.province)
        if spec is None:
            self._reject(nation, a, f"{self._pname(a.province)} has no monument")
            return
        province = self.s.provinces[a.province]
        if province.monument >= rules.max_monument_level:
            self._reject(nation, a, f"{spec.name} is already at its greatest")
            return
        if province.unrest:
            self._reject(nation, a, f"{self._pname(a.province)} is in unrest")
            return
        level = province.monument + 1
        if error := self._pay(nation, rules.monument_cost.times(level)):
            self._reject(nation, a, error)
            return
        province.monument = level
        self._prestige(nation, rules.prestige_monument_level * level, spec.name)
        self._emit(
            EventKind.MONUMENT_RAISED,
            f"{self._name(nation)} raises {spec.name} to level {level}",
            nations=(nation,),
            province=a.province,
            level=level,
        )

    def _research(self, nation: NationId, a: Research) -> None:
        me = self.s.nations[nation]
        if nation in self.researched:
            self._reject(nation, a, "you can research only once a year")
            return
        level = me.technology[a.branch]
        discount = modifiers(self.s, nation).research_discount
        cost = research_cost(self.s.rules, a.branch, level, discount)
        if cost is None:
            self._reject(nation, a, f"{a.branch.value} technology is at its maximum")
            return
        step = self.s.rules.tech_tree[a.branch][level]
        if step.requires is not None and me.technology[step.requires[0]] < step.requires[1]:
            need, at = step.requires
            self._reject(nation, a, f"{step.name} needs {need.value} technology {at} first")
            return
        if step.options and a.choice >= len(step.options):
            self._reject(nation, a, f"{step.name} offers only {len(step.options)} doctrines")
            return
        if error := self._pay(nation, cost):
            self._reject(nation, a, error)
            return
        self.researched.add(nation)
        me.technology[a.branch] = level + 1
        chosen = me.doctrines.setdefault(a.branch, [])
        del chosen[level:]  # the doctrines of the levels reached, in order
        chosen.extend([0] * (level - len(chosen)))
        chosen.append(a.choice if step.options else 0)
        doctrine = step.options[a.choice].name if step.options else None
        self._emit(
            EventKind.RESEARCHED,
            f"{me.name} reaches {a.branch.value} technology {level + 1}: {step.name}"
            + (f", choosing {doctrine}" if doctrine else ""),
            nations=(nation,),
            branch=a.branch.value,
            level=level + 1,
            doctrine=doctrine or "",
        )

    def _hire(self, nation: NationId, a: HireGeneral) -> None:
        from pax_agentica.engine.scenario import general_name

        if error := self._own_error(nation, a.province):
            self._reject(nation, a, error)
            return
        rules = self.s.rules
        most = modifiers(self.s, nation).max_generals
        if len(self.s.generals_of(nation)) >= most:
            self._reject(nation, a, f"you already have {most} generals")
            return
        if self.s.general_in(a.province):
            self._reject(nation, a, f"{self._pname(a.province)} already has a general")
            return
        if error := self._pay(nation, rules.general_cost):
            self._reject(nation, a, error)
            return
        appointed = sum(1 for g in self.s.generals if g.nation == nation) + self.fallen[nation]
        skill = self.rng.choice([1, 1, 2, 2, 3])
        if BuildingKind.MILITARY_ACADEMY in self.s.provinces[a.province].buildings:
            skill = min(3, skill + 1)
        general = General(
            id=self.s.next_general_id,
            name=general_name(nation, appointed),
            nation=nation,
            skill=skill,
            province=a.province,
        )
        self.s.next_general_id += 1
        self.s.generals.append(general)
        self._emit(
            EventKind.GENERAL_APPOINTED,
            f"{self._name(nation)} appoints {general.name} (skill {general.skill}) in "
            f"{self._pname(a.province)}",
            nations=(nation,),
            province=a.province,
            general=general.id,
            skill=general.skill,
        )

    def _assign(self, nation: NationId, a: AssignGeneral) -> None:
        general = self.s.general(a.general)
        if general is None or general.nation != nation:
            self._reject(nation, a, f"you have no general #{a.general}")
            return
        if error := self._hold_error(nation, a.province):
            self._reject(nation, a, error)
            return
        other = self.s.general_in(a.province)
        if other is not None and other.id != general.id:
            self._reject(nation, a, f"{other.name} already commands in {self._pname(a.province)}")
            return
        general.province = a.province

    def _hire_advisor(self, nation: NationId, a: HireAdvisor) -> None:
        me = self.s.nations[nation]
        candidate = next(
            (c for c in advisor_candidates(self.s, nation) if c.id == a.candidate), None
        )
        if candidate is None:
            self._reject(nation, a, f"no candidate #{a.candidate} seeks a place at your court")
            return
        current = me.advisors.get(candidate.role)
        if current is not None and current.name == candidate.name:
            self._reject(nation, a, f"{candidate.name} already serves you")
            return
        if error := self._pay(nation, Resources(ducats=advisor_hire_cost(self.s.rules, candidate))):
            self._reject(nation, a, error)
            return
        me.advisors[candidate.role] = candidate
        replaced = f", replacing {current.name}" if current else ""
        self._emit(
            EventKind.ADVISOR_HIRED,
            f"{me.name} names {candidate.name} {candidate.role.value} (skill {candidate.skill})"
            f"{replaced}",
            nations=(nation,),
            role=candidate.role.value,
            skill=candidate.skill,
        )

    def _dismiss_advisor(self, nation: NationId, a: DismissAdvisor) -> None:
        me = self.s.nations[nation]
        advisor = me.advisors.pop(a.role, None)
        if advisor is None:
            self._reject(nation, a, f"you have no {a.role.value}")
            return
        self._emit(
            EventKind.ADVISOR_LEFT,
            f"{advisor.name} leaves the court of {me.name}",
            nations=(nation,),
            audience=(nation,),
            role=a.role.value,
        )

    def _pay_fleet(self, nation: NationId) -> None:
        """At war the crews are paid before the army; unpaid, they leave, and the dearest ships
        are laid up until the rest can be paid."""
        me, rules = self.s.nations[nation], self.s.rules
        pay = fleet_pay(self.s, nation)
        if pay <= me.resources.ducats:
            me.resources = me.resources - Resources(ducats=pay)
            return
        laid_up = 0
        while me.fleets and fleet_upkeep(rules, me.fleets) > me.resources.ducats:
            water = max(me.fleets, key=lambda w: (sum(me.fleets[w].values()), w))
            ships = me.ships(water)
            kind = max((k for k in Ship if ships[k]), key=lambda k: rules.ships[k].pay)
            ships[kind] -= 1
            me.set_ships(water, ships)
            laid_up += 1
        me.resources = me.resources - Resources(ducats=fleet_upkeep(rules, me.fleets))
        self._emit(
            EventKind.DESERTION,
            f"{laid_up} of {me.name}'s ships are laid up: their crews went unpaid",
            nations=(nation,),
            audience=(nation,),
            ships=laid_up,
        )

    def _pay_council(self, nation: NationId) -> None:
        """Advisors are paid before the army; unpaid, they leave."""
        me = self.s.nations[nation]
        salaries = advisor_salaries(self.s.rules, me.advisors)
        if not salaries:
            return
        if me.resources.ducats >= salaries:
            me.resources = me.resources - Resources(ducats=salaries)
            return
        for role, advisor in sorted(me.advisors.items()):
            self._emit(
                EventKind.ADVISOR_LEFT,
                f"{advisor.name} leaves the court of {me.name}: the salary went unpaid",
                nations=(nation,),
                role=role.value,
            )
        me.advisors.clear()

    def _age_rulers(self) -> None:
        """Every ruler grows a year older; the oldest may die and pass the crown on."""
        for nation in self.s.alive_nations():
            me = self.s.nations[nation]
            ruler = me.ruler
            if ruler is None:
                continue
            ruler.age += 1
            if self.rng.random() >= death_chance(ruler):
                continue
            heir = make_ruler(
                nation, ruler.reign + 1, self.turn + 1, self.rng, age=self.rng.randint(16, 32)
            )
            me.ruler = heir
            self._emit(
                EventKind.SUCCESSION,
                f"{ruler.title} {ruler.name} of {me.name} dies at {ruler.age}; "
                f"{heir.title} {heir.name} takes the throne",
                nations=(nation,),
                administration=heir.administration,
                diplomacy=heir.diplomacy,
                military=heir.military,
            )
            self._change_stability(nation, -1, "a new reign")

    def _leader(self, nation: NationId, action: Move | Attack) -> tuple[General | None, str | None]:
        """The general an order asks for, if he can lead it."""
        if action.general is None:
            return None, None
        general = self.s.general(action.general)
        if general is None or general.nation != nation:
            return None, f"you have no general #{action.general}"
        if general.province != action.origin:
            return None, f"{general.name} is not in {self._pname(action.origin)}"
        return general, None

    def _disband(self, nation: NationId, a: Disband) -> None:
        if error := self._hold_error(nation, a.province):
            self._reject(nation, a, error)
            return
        province = self.s.provinces[a.province]
        here = province.army()[a.unit] if a.unit else province.troops
        if here < a.regiments:
            what = f"{a.unit.value} " if a.unit else ""
            self._reject(nation, a, f"only {here} {what}regiments in {self._pname(a.province)}")
            return
        province.take(a.regiments, {a.unit: a.regiments} if a.unit else None)
        state = self.s.nations[nation]
        state.resources = state.resources + self.s.rules.disband_refund.times(a.regiments)
        self._emit(
            EventKind.DISBANDED,
            f"{state.name} disbands {a.regiments} regiments in {self._pname(a.province)}",
            nations=(nation,),
            province=a.province,
            audience=(nation,),
            regiments=a.regiments,
        )

    def _develop(self, nation: NationId, a: Develop) -> None:
        if error := self._own_error(nation, a.province):
            self._reject(nation, a, error)
            return
        province = self.s.provinces[a.province]
        mods = modifiers(self.s, nation)
        if province.development >= mods.max_development:
            self._reject(nation, a, "development is already at its maximum")
            return
        if error := self._pay(
            nation,
            develop_cost(
                self.s.rules,
                province.development,
                province.buildings,
                mods.building_discount,
                self.s.map.provinces[a.province].terrain,
                focus_bonus(self.s, a.province) if province.focus == Focus.LEARNING else 0.0,
            ),
        ):
            self._reject(nation, a, error)
            return
        province.development += 1
        self._emit(
            EventKind.DEVELOPED,
            f"{self._name(nation)} develops {self._pname(a.province)} to {province.development}",
            nations=(nation,),
            province=a.province,
            development=province.development,
        )

    def _build(self, nation: NationId, a: Build) -> None:
        if error := self._own_error(nation, a.province):
            self._reject(nation, a, error)
            return
        rules = self.s.rules
        province = self.s.provinces[a.province]
        spec = rules.buildings[a.building]
        mods = modifiers(self.s, nation)
        slots = province_slots(self.s, a.province)
        where = self._pname(a.province)
        if a.building in province.buildings:
            error = f"{where} already has {_article(spec.name)}"
        elif spec.requires and spec.requires not in province.buildings:
            needed = rules.buildings[spec.requires].name
            error = f"{_article(spec.name)} needs {_article(needed)}"
        elif spec.requires_tech and (
            self.s.nations[nation].technology[spec.requires_tech[0]] < spec.requires_tech[1]
        ):
            branch, level = spec.requires_tech
            error = f"{_article(spec.name)} needs {branch.value} technology {level}"
        elif spec.unique and any(
            a.building in self.s.provinces[p].buildings for p in self.s.provinces_of(nation)
        ):
            error = f"your realm already has {_article(spec.name)}: there can be only one"
        elif len(province.buildings) >= slots:
            town = settlement(rules, province.development).name.lower()
            error = (
                f"{where} is a {town} with room for {slots} work{'s' if slots != 1 else ''} "
                "and all are taken: "
                "upgrade what stands there, or develop it into a larger town"
            )

        else:
            error = self._pay(nation, building_cost(rules, a.building, mods.building_discount))
        if error:
            self._reject(nation, a, error)
            return
        province.buildings.append(a.building)
        if spec.unique:
            self._prestige(nation, rules.prestige_great_work, spec.name)
        self._emit(
            EventKind.BUILT,
            f"{self._name(nation)} builds {_article(spec.name)} in {where}",
            nations=(nation,),
            province=a.province,
            building=a.building.value,
        )

    def _upgrade_building(self, nation: NationId, a: UpgradeBuilding) -> None:
        if error := self._own_error(nation, a.province):
            self._reject(nation, a, error)
            return
        rules = self.s.rules
        province = self.s.provinces[a.province]
        spec = rules.buildings[a.building]
        where = self._pname(a.province)
        level = province.level(a.building)
        if not level:
            error = f"{where} has no {spec.name.lower()} to upgrade"
        elif level >= spec.max_level:
            error = f"the {spec.name.lower()} of {where} is at its highest level ({level})"
        elif (a.province, a.building) in self.upgraded:
            error = f"the {spec.name.lower()} of {where} is already being upgraded this year"
        else:
            mods = modifiers(self.s, nation)
            error = self._pay(
                nation, upgrade_cost(rules, a.building, level + 1, mods.building_discount)
            )
        if error:
            self._reject(nation, a, error)
            return
        self.upgraded.add((a.province, a.building))
        province.levels[a.building] = level + 1
        self._emit(
            EventKind.BUILT,
            f"{self._name(nation)} raises the {spec.name.lower()} of {where} to level {level + 1}",
            nations=(nation,),
            province=a.province,
            building=a.building.value,
            level=level + 1,
        )

    # ------------------------------------------------------------ phase 4: movement

    def _movement(self) -> None:
        for nation in self.order:
            for sail in self._actions(nation, SailFleet):
                self._sail(nation, sail)
        for nation in self.order:
            for lift in self._actions(nation, LiftSiege):
                p = self.s.provinces.get(lift.province)
                if p is None or p.siege_by != nation:
                    self._reject(nation, lift, "you are not besieging it")
                else:
                    self._lift(lift.province, "by order")
        for nation in self.order:
            for a in self._actions(nation, Move):
                error = self._hold_error(nation, a.origin) or self._hold_error(nation, a.target)
                if not error and (by := self.s.provinces[a.target].siege_by):
                    error = (
                        f"{self._pname(a.target)} is besieged by {self._name(by)}: attack the "
                        "siege lines to relieve it"
                    )
                if not error:
                    error = self._reach_error(nation, a.origin, a.target, a.regiments)
                if not error:
                    error = self._composition_error(a.origin, a.regiments, a.units)
                general = None
                if not error:
                    general, error = self._leader(nation, a)
                if not error and general and self.s.general_in(a.target):
                    error = f"another general already commands in {self._pname(a.target)}"
                if error:
                    self._reject(nation, a, error)
                    continue
                source = self.s.provinces[a.origin]
                seasoned = source.veterancy  # before they leave: an empty province has none
                moved = source.take(a.regiments, a.units)
                self.s.provinces[a.target].add(moved, veterancy=seasoned)
                if general:
                    general.province = a.target
                self._emit(
                    EventKind.MOVED,
                    f"{self._name(nation)} moves {a.regiments} regiments from "
                    f"{self._pname(a.origin)} to {self._pname(a.target)}",
                    nations=(nation,),
                    province=a.target,
                    audience=(nation,),
                    regiments=a.regiments,
                    origin=a.origin,
                )

    def _sea(self, sea: SeaId | None) -> str:
        """A sea zone by name: "the North Sea"."""
        zone = self.s.map.seas.get(sea or "")
        return f"the {zone.name}" if zone else "the sea"

    def _sail(self, nation: NationId, a: SailFleet) -> None:
        me = self.s.nations[nation]
        if a.origin not in self.s.map.seas or a.target not in self.s.map.seas:
            self._reject(nation, a, "there is no such sea")
            return
        if a.target not in self.s.map.seas[a.origin].neighbors:
            self._reject(
                nation, a, f"{self._sea(a.origin)} does not open onto {self._sea(a.target)}"
            )
            return
        here = me.ships(a.origin)
        for kind, n in a.ships.items():
            if n < 0 or here[kind] < n:
                self._reject(
                    nation, a, f"only {here[kind]} {self._ships(kind)} in {self._sea(a.origin)}"
                )
                return
        going = {k: n for k, n in a.ships.items() if n}
        if not going:
            self._reject(nation, a, "no ships named")
            return
        me.set_ships(a.origin, {k: here[k] - going.get(k, 0) for k in Ship})
        there = me.ships(a.target)
        me.set_ships(a.target, {k: there[k] + going.get(k, 0) for k in Ship})
        count = sum(going.values())
        self._emit(
            EventKind.FLEET_SAILED,
            f"{self._name(nation)} sails {count} ships from {self._sea(a.origin)} into "
            f"{self._sea(a.target)}",
            nations=(nation,),
            origin=a.origin,
            sea=a.target,
            count=count,
        )

    def _sea_battles(self) -> None:
        """Fleets that seek each other out fight before the armies march: one battle a year
        for each pair of realms in each sea zone."""
        fought: set[tuple[SeaId, tuple[NationId, ...]]] = set()
        for nation in self.order:
            for a in self._actions(nation, SeekBattle):
                key = (a.sea, tuple(sorted((nation, a.enemy))))
                if key in fought:
                    continue
                if error := self._sea_battle_error(nation, a):
                    self._reject(nation, a, error)
                    continue
                fought.add(key)
                self._sea_battle(nation, a.enemy, a.sea)

    def _sea_battle_error(self, nation: NationId, a: SeekBattle) -> str | None:
        if a.enemy not in self.s.nations or not self.s.nations[a.enemy].alive:
            return f"there is no realm '{a.enemy}'"
        if a.sea not in self.s.map.seas:
            return "there is no such sea"
        war = self.s.war(nation, a.enemy)
        if war is None:
            return f"you are not at war with {self._name(a.enemy)}: declare war first"
        if self.turn < war.since + self.s.rules.mobilization_turns:
            return "your fleet is still fitting out: it can sail out next year"
        if not naval_power(self.s, nation, a.sea):
            return f"you have no ships in {self._sea(a.sea)}"
        if not naval_power(self.s, a.enemy, a.sea):
            return f"{self._name(a.enemy)} has no fleet in {self._sea(a.sea)} to fight"
        return None

    def _sea_battle(self, nation: NationId, enemy: NationId, sea: SeaId) -> None:
        rules = self.s.rules
        mine, theirs = self.s.nations[nation].ships(sea), self.s.nations[enemy].ships(sea)
        lo, hi = rules.roll_min, rules.roll_max
        att = naval_power(self.s, nation, sea) * morale(self.s, nation) * self.rng.uniform(lo, hi)
        dfn = naval_power(self.s, enemy, sea) * morale(self.s, enemy) * self.rng.uniform(lo, hi)
        won = att > dfn
        winner, loser = (nation, enemy) if won else (enemy, nation)
        win_ships, lose_ships = (mine, theirs) if won else (theirs, mine)
        ratio = min(att, dfn) / max(att, dfn)
        sunk = {k: math.ceil(n * rules.naval_loser_loss) for k, n in lose_ships.items()}
        lost = {k: round(n * rules.naval_winner_loss * ratio) for k, n in win_ships.items()}
        self.s.nations[loser].set_ships(sea, {k: lose_ships[k] - sunk[k] for k in Ship})
        self.s.nations[winner].set_ships(sea, {k: win_ships[k] - lost[k] for k in Ship})
        if sum(sunk.values()) >= rules.naval_battle_counts:  # a skirmish of boats is no battle
            self._battle_counts(nation, enemy, won=won)
        total = sum(mine.values()) + sum(theirs.values())
        great = total >= rules.great_sea_battle
        if great:  # a battle all Europe talks of for a generation
            self._prestige(winner, 2 * rules.prestige_battle, "a great sea battle won")
            self._prestige(loser, -2 * rules.prestige_battle, "a great sea battle lost")

        def ships(fleet: dict[Ship, int]) -> str:
            return ", ".join(f"{n} {k.value}s" for k, n in fleet.items() if n) or "no ships"

        self._emit(
            EventKind.NAVAL_BATTLE,
            f"{'A great sea battle' if great else 'Sea battle'} in {self._sea(sea)}: "
            f"{self._name(nation)} ({ships(mine)}) against {self._name(enemy)} ({ships(theirs)}). "
            f"{self._name(winner)} wins. Ships lost: {sum(lost.values())} to "
            f"{sum(sunk.values())}",
            nations=(nation, enemy),
            sea=sea,
            attacker=nation,
            defender=enemy,
            attacker_fleet=ships(mine),
            defender_fleet=ships(theirs),
            attacker_power=round(att, 1),
            defender_power=round(dfn, 1),
            attacker_won=won,
            winner_lost=sum(lost.values()),
            loser_lost=sum(sunk.values()),
            great=great,
        )

    def _composition_error(
        self, origin: ProvinceId, regiments: int, units: Mapping[UnitKind, int] | None
    ) -> str | None:
        here = self.s.provinces[origin].army()
        if units is None:
            total = sum(here.values())
            return f"only {total} regiments in {self._pname(origin)}" if total < regiments else None
        if sum(units.values()) != regiments:
            return f"the regiments by kind add up to {sum(units.values())}, not {regiments}"
        for kind, n in units.items():
            if here[kind] < n:
                return f"only {here[kind]} {kind.value} regiments in {self._pname(origin)}"
        return None

    # ------------------------------------------------------------ phase 5: battles

    def _combat(self) -> None:
        self._sea_battles()
        queues = {n: self._joined(n, list(self._actions(n, Attack))) for n in self.order}
        while any(queues.values()):
            for nation in self.order:
                if queues[nation] and self.s.nations[nation].alive:
                    self._attack(nation, queues[nation].pop(0))
                elif queues[nation]:
                    queues[nation].clear()

    def _joined(self, nation: NationId, attacks: list[Attack]) -> list[Attack]:
        """A realm's armies that fall on the same province in the same year fight it as one:
        one battle, their regiments together, led by their best general. The others march
        into the province the attack starts from (the best general's, else the largest)."""
        by_target: dict[ProvinceId, list[Attack]] = {}
        for a in attacks:
            by_target.setdefault(a.target, []).append(a)
        out = []
        for target, group in by_target.items():
            if len(group) == 1:
                out.append(group[0])
                continue
            ready = []
            for a in group:
                if error := self._join_error(nation, a):
                    self._reject(nation, a, error)
                else:
                    ready.append(a)
            if len(ready) <= 1:
                out.extend(ready)
                continue

            def rank(a: Attack) -> tuple[int, int]:
                general = self.s.general(a.general) if a.general is not None else None
                return (general.skill if general else 0, a.regiments)

            lead = max(ready, key=rank)
            base = self.s.provinces[lead.origin]
            units = dict.fromkeys(UnitKind, 0)
            for a in ready:
                origin = self.s.provinces[a.origin]
                force = (
                    {k: a.units.get(k, 0) for k in UnitKind}
                    if a.units is not None
                    else share(origin.army(), min(a.regiments, origin.troops))
                )
                for k in UnitKind:
                    units[k] += force[k]
                if a is not lead:  # they join the leading army where it stands
                    seasoned = origin.veterancy
                    base.add(origin.take(sum(force.values()), force), seasoned)
            general = lead.general if lead.general is not None else None
            self.joined[(nation, target)] = [a.origin for a in ready]
            out.append(
                Attack(
                    origin=lead.origin,
                    target=target,
                    regiments=sum(units.values()),
                    units={k: n for k, n in units.items() if n},
                    general=general,
                    tactic=lead.tactic,
                )
            )
        return out

    def _coordination(self, nation: NationId, target: ProvinceId) -> float:
        """Armies from several provinces are hard to bring onto one field at one hour."""
        armies = len(self.joined.get((nation, target), [])) or 1
        rules = self.s.rules
        return 1 - min(rules.joint_attack_penalty_max, rules.joint_attack_penalty * (armies - 1))

    def _reach_error(
        self, nation: NationId, origin: ProvinceId, target: ProvinceId, regiments: int
    ) -> str | None:
        """Why an army cannot get from `origin` to `target`: not neighbours, and no fleet of
        the realm on a sea between them to carry it (stronger than the defender's there, and
        with room for every regiment)."""
        if self.s.map.adjacent(origin, target):
            return None
        shared = self.s.map.shared_seas(origin, target)
        if not shared:
            return f"{self._pname(origin)} and {self._pname(target)} do not border"
        sea = landing_sea(self.s, nation, origin, target)
        if sea is None:
            return (
                f"no fleet of yours holds {self._sea(shared[0])} to carry an army from "
                f"{self._pname(origin)} to {self._pname(target)}"
            )
        room = carries(self.s.rules, self.s.nations[nation].ships(sea))
        if regiments > room:
            return f"your ships in {self._sea(sea)} can carry only {room} regiments"
        return None

    def _crossing_error(self, nation: NationId, a: Attack) -> str | None:
        """An army cannot cross a strait whose sea the enemy's fleet commands."""
        sea = self.s.map.strait_sea(a.origin, a.target)
        if sea is None:
            return None
        target = self.s.provinces[a.target]
        enemy = target.siege_by if target.siege_by not in (None, nation) else target.holder
        if enemy is None or enemy == nation:
            return None
        if sea_command(self.s, nation, enemy, sea) == "closed":
            return (
                f"the fleet of {self._name(enemy)} commands {self._sea(sea)}: no army of yours "
                "can cross until you match it at sea"
            )
        return None

    def _join_error(self, nation: NationId, a: Attack) -> str | None:
        """Why one army of a joint attack cannot march with the others."""
        if a.target not in self.s.provinces:
            return f"there is no province '{a.target}'"
        if error := self._hold_error(nation, a.origin):
            return error
        if error := self._reach_error(nation, a.origin, a.target, a.regiments):
            return error
        if error := self._crossing_error(nation, a):
            return error
        if self.s.provinces[a.origin].troops == 0:
            return f"no regiments left in {self._pname(a.origin)}"
        if a.units is not None and (
            wrong := self._composition_error(a.origin, a.regiments, a.units)
        ):
            return wrong
        _general, error = self._leader(nation, a)
        if error:
            return error
        target = self.s.provinces[a.target]
        enemy = target.siege_by if target.siege_by not in (None, nation) else target.holder
        if target.siege_by is None and enemy == nation:
            return f"{self._pname(a.target)} is already yours"
        if enemy is not None and enemy != nation:
            war = self.s.war(nation, enemy)
            if war is None:
                return f"you are not at war with {self._name(enemy)}: declare war first"
            if self.turn < war.since + self.s.rules.mobilization_turns:
                ready = war.since + self.s.rules.mobilization_turns
                return f"your armies are still mobilising: attack from turn {ready}"
        return None

    def _attack(self, nation: NationId, a: Attack) -> None:
        if a.target not in self.s.provinces:
            self._reject(nation, a, f"there is no province '{a.target}'")
            return
        if error := self._hold_error(nation, a.origin):
            self._reject(nation, a, error)
            return
        if error := self._reach_error(nation, a.origin, a.target, a.regiments):
            self._reject(nation, a, error)
            return
        origin, target = self.s.provinces[a.origin], self.s.provinces[a.target]
        if error := self._crossing_error(nation, a):
            self._reject(nation, a, error)
            return
        if target.siege_by == nation:
            self._reinforce(nation, a)
            return
        if target.siege_by is not None:
            self._relieve(nation, a)
            return
        defender = target.holder
        if defender == nation:
            self._reject(nation, a, f"{self._pname(a.target)} is already yours")
            return
        if defender is not None:
            war = self.s.war(nation, defender)
            if war is None:
                self._reject(
                    nation, a, f"you are not at war with {self._name(defender)}: declare war first"
                )
                return
            ready = war.since + self.s.rules.mobilization_turns
            if self.turn < ready:
                self._reject(
                    nation, a, f"your armies are still mobilising: attack from turn {ready}"
                )
                return
        if origin.troops == 0:
            self._reject(nation, a, f"no regiments left in {self._pname(a.origin)}")
            return
        wrong = (
            self._composition_error(a.origin, a.regiments, a.units) if a.units is not None else None
        )
        if wrong:
            self._reject(nation, a, wrong)
            return
        general, error = self._leader(nation, a)
        if error:
            self._reject(nation, a, error)
            return
        seasoned = origin.veterancy  # before they leave: an empty province has none
        force = origin.take(min(a.regiments, origin.troops), a.units)
        committed = sum(force.values())
        attacker_name = self._name(nation)
        if general:
            attacker_name += f" under {general.name}"
        defender_name = self._name(defender) if defender else "the local levies"
        walls = self._walls(nation, a.target, force)
        if target.troops == 0:
            if walls:
                self._siege(nation, a, force, general, walls, seasoned)
            else:
                self._capture(nation, a.target, force, general, origin=a.origin, veterancy=seasoned)
            return
        guard = self.s.general_in(a.target)
        if guard and guard.nation != defender:
            guard = None
        if guard:
            defender_name += f" under {guard.name}"
        rules = self.s.rules
        ground = self.s.map.provinces[a.target].terrain
        held = target.army()
        edge = tactic_factor(rules, a.tactic, target.posture, force, held, ground)
        result = fight(
            rules,
            committed,
            target.troops,
            defense_multiplier(self.s, a.origin, a.target, siege_levels(rules, force)),
            self.rng,
            attack_factor=battle_factor(self.s, nation, general.skill if general else 0)
            * self._rivalry(nation, defender)
            * self._coordination(nation, a.target)
            * edge
            * veteran(rules, seasoned)
            * morale(self.s, nation),
            defence_factor=battle_factor(self.s, defender, guard.skill if guard else 0)
            * self._rivalry(defender, nation)
            * veteran(rules, target.veterancy)
            * morale(self.s, defender),
            attack_quality=army_strength(rules, force, ground, attacking=True, nation=nation)
            / committed,
            defence_quality=army_strength(rules, held, ground, attacking=False, nation=defender)
            / target.troops,
        )
        then = (
            ("the walls still stand: a siege begins" if walls else "the province is taken")
            if result.attacker_won
            else "the attack is thrown back"
        )
        self._battle_event(
            a,
            nation,
            defender,
            attacker_name,
            defender_name,
            committed,
            target.troops,
            result,
            then,
            defender_army=held,
            attacker_army=force,
            tactic=a.tactic.value,
            posture=target.posture.value,
            edge=round(edge, 3),
            attacker_veterancy=round(seasoned, 2),
            defender_veterancy=round(target.veterancy, 2),
        )
        self._battle_counts(nation, defender, won=result.attacker_won)
        if result.attacker_won:
            fallen = share(force, result.attacker_losses)
            survivors = {k: force[k] - fallen[k] for k in UnitKind}
            seasoned = self._seasoned(seasoned, committed, target.troops, nation)
            if walls:
                target.set_army({})  # the garrison is beaten, the walls still stand
                self._siege(nation, a, survivors, general, walls, seasoned)
            else:
                self._capture(
                    nation, a.target, survivors, general, origin=a.origin, veterancy=seasoned
                )
        else:
            target.veterancy = self._seasoned(target.veterancy, target.troops, committed, defender)
            target.take(result.defender_losses)

    def _seasoned(
        self, veterancy: float, regiments: int, beaten: int, nation: NationId | None = None
    ) -> float:
        """An army's veterancy after a victory: rules.veterancy_per_victory more for beating an
        army its own size or larger, less for a smaller one (more with Old soldiers)."""
        gain = self.s.rules.veterancy_per_victory * min(1.0, beaten / max(1, regiments))
        gain *= 1 + modifiers(self.s, nation).veterancy
        return min(1.0, veterancy + gain)

    def _walls(self, nation: NationId, province: ProvinceId, force: dict[UnitKind, int]) -> int:
        """Fort levels still standing against this army: they must be besieged."""
        return siege_walls(self.s, nation, province, force)

    def _siege(
        self,
        nation: NationId,
        a: Attack,
        force: dict[UnitKind, int],
        general: General | None,
        walls: int,
        veterancy: float = 0.0,
    ) -> None:
        """The garrison is gone but walls stand: the army digs in before them. Its general
        stays behind at `a.origin`."""
        del general
        target = self.s.provinces[a.target]
        target.end_siege()
        target.siege_by, target.siege_from = nation, a.origin
        target.besiegers = {k: n for k, n in force.items() if n}
        target.siege_veterancy = veterancy
        regiments = sum(force.values())
        self._emit(
            EventKind.SIEGE,
            f"{self._name(nation)} lays siege to {self._pname(a.target)}: {regiments} regiments "
            f"dig in before {walls} level{'s' if walls > 1 else ''} of walls",
            nations=(nation, target.holder) if target.holder else (nation,),
            province=a.target,
            started=True,
            walls=walls,
            regiments=regiments,
            progress=0,
        )

    def _reinforce(self, nation: NationId, a: Attack) -> None:
        """More regiments for one's own siege lines; with guns enough, they storm at once."""
        target = self.s.provinces[a.target]
        holder = target.holder
        if holder is not None and not self.s.at_war(nation, holder):
            self._reject(nation, a, f"you are no longer at war with {self._name(holder)}")
            return
        if error := self._composition_error(a.origin, a.regiments, a.units):
            self._reject(nation, a, error)
            return
        origin = self.s.provinces[a.origin]
        seasoned = origin.veterancy
        force = origin.take(a.regiments, a.units)
        coming = sum(force.values())
        lines = target.siege_army()
        dug_in = sum(lines.values())
        merged = {k: lines[k] + force[k] for k in UnitKind}
        target.besiegers = {k: n for k, n in merged.items() if n}
        target.siege_veterancy = (target.siege_veterancy * dug_in + seasoned * coming) / max(
            1, dug_in + coming
        )
        if self._walls(nation, a.target, merged) == 0:  # enough guns now: storm the breach
            veterancy = target.siege_veterancy
            army = target.end_siege()
            self._capture(nation, a.target, army, origin=a.origin, veterancy=veterancy)
            return
        self._emit(
            EventKind.SIEGE,
            f"{self._name(nation)} sends {sum(force.values())} more regiments to the siege of "
            f"{self._pname(a.target)} ({sum(merged.values())} in the lines)",
            nations=(nation, holder) if holder else (nation,),
            province=a.target,
            regiments=sum(merged.values()),
            progress=target.siege_progress,
        )

    def _relieve(self, nation: NationId, a: Attack) -> None:
        """An army marches on the siege lines before a friendly town."""
        target = self.s.provinces[a.target]
        besieger = target.siege_by
        assert besieger is not None  # noqa: S101 (the caller checked)
        if not self.s.at_war(nation, besieger):
            self._reject(
                nation, a, f"{self._name(besieger)} besieges {self._pname(a.target)} already"
            )
            return
        if self.s.provinces[a.origin].troops == 0:
            self._reject(nation, a, f"no regiments left in {self._pname(a.origin)}")
            return
        if error := self._composition_error(a.origin, a.regiments, a.units):
            self._reject(nation, a, error)
            return
        general, error = self._leader(nation, a)
        if error:
            self._reject(nation, a, error)
            return
        origin = self.s.provinces[a.origin]
        seasoned = origin.veterancy
        force = origin.take(min(a.regiments, origin.troops), a.units)
        committed = sum(force.values())
        lines = target.siege_army()
        dug_in = sum(lines.values())
        rules = self.s.rules
        ground = self.s.map.provinces[a.target].terrain
        edge = tactic_factor(rules, a.tactic, Posture.HOLD, force, lines, ground)  # dug in
        result = fight(
            rules,
            committed,
            dug_in,
            rules.defender_advantage * rules.terrain_defense[ground],
            self.rng,
            attack_factor=battle_factor(self.s, nation, general.skill if general else 0)
            * self._rivalry(nation, besieger)
            * self._coordination(nation, a.target)
            * edge
            * veteran(rules, seasoned)
            * morale(self.s, nation),
            defence_factor=battle_factor(self.s, besieger)
            * self._rivalry(besieger, nation)
            * veteran(rules, target.siege_veterancy)
            * morale(self.s, besieger),
            attack_quality=army_strength(rules, force, ground, attacking=True, nation=nation)
            / committed,
            defence_quality=army_strength(rules, lines, ground, attacking=False, nation=besieger)
            / dug_in,
        )
        name = self._name(nation) + (f" under {general.name}" if general else "")
        then = "the siege is broken" if result.attacker_won else "the siege goes on"
        self._battle_event(
            a,
            nation,
            besieger,
            name,
            f"{self._name(besieger)}'s siege lines",
            committed,
            dug_in,
            result,
            then,
            defender_army=lines,
            attacker_army=force,
            tactic=a.tactic.value,
            posture=Posture.HOLD.value,
            edge=round(edge, 3),
            attacker_veterancy=round(seasoned, 2),
            defender_veterancy=round(target.siege_veterancy, 2),
        )
        self._battle_counts(nation, besieger, won=result.attacker_won)
        if result.attacker_won:
            target.besiegers = {}  # beaten: the lines are destroyed
            self._lift(a.target, f"{self._name(nation)} breaks the siege lines")
            fallen = share(force, result.attacker_losses)
            survivors = {k: force[k] - fallen[k] for k in UnitKind}
            seasoned = self._seasoned(seasoned, committed, dug_in, nation)
            if target.holder == nation:  # into the town they saved
                target.add(survivors, seasoned)
                if general is not None and self.s.general_in(a.target) is None:
                    general.province = a.target
            else:
                origin.add(survivors, seasoned)
        else:
            beaten = share(lines, result.defender_losses)
            target.besiegers = {k: lines[k] - beaten[k] for k in UnitKind if lines[k] - beaten[k]}
            target.siege_veterancy = self._seasoned(
                target.siege_veterancy, dug_in, committed, besieger
            )

    def _battle_event(
        self,
        a: Attack,
        nation: NationId,
        defender: NationId | None,
        attacker_name: str,
        defender_name: str,
        committed: int,
        defending: int,
        result: BattleResult,
        then: str,
        *,
        defender_army: Mapping[UnitKind, int],
        attacker_army: Mapping[UnitKind, int],
        **extra: EventValue,
    ) -> None:
        winner = attacker_name if result.attacker_won else defender_name
        origins = self.joined.get((nation, a.target), [a.origin])
        places = [self._pname(o) for o in origins]
        whence = places[0] if len(places) == 1 else ", ".join(places[:-1]) + " and " + places[-1]

        def kinds(army: Mapping[UnitKind, int]) -> str:
            return ", ".join(f"{n} {k.value}" for k, n in army.items() if n)

        self._emit(
            EventKind.BATTLE,
            f"Battle of {self._pname(a.target)}: {attacker_name}, {committed} regiments from "
            f"{whence}, against {defender_name}, {defending}. {winner} wins. "
            f"Lost: {result.attacker_losses} to {result.defender_losses}; {then}",
            nations=(nation, defender) if defender else (nation,),
            province=a.target,
            attacker=nation,
            defender=defender or "",
            attacker_name=attacker_name,
            defender_name=defender_name,
            origin=a.origin,
            origins=", ".join(origins),
            armies=len(origins),
            attacker_regiments=committed,
            defender_regiments=defending,
            attacker_army=kinds(attacker_army),
            defender_army=kinds(defender_army),
            attacker_losses=result.attacker_losses,
            defender_losses=result.defender_losses,
            attacker_power=round(result.attacker_power, 1),
            defender_power=round(result.defender_power, 1),
            attacker_won=result.attacker_won,
            then=then,
            extra=extra,
        )

    def _camp(
        self, nation: NationId, preferred: ProvinceId | None, near: ProvinceId
    ) -> ProvinceId | None:
        """Where a lifted siege's army goes: whence it came, else next door, else home."""
        held = set(self.s.held_by(nation))
        if preferred in held:
            return preferred
        for p in sorted(self.s.map.all_neighbors(near)):
            if p in held:
                return p
        capital = self.s.nations[nation].capital
        if capital in held:
            return capital
        return min(held) if held else None

    def _lift(self, province: ProvinceId, why: str) -> None:
        """End a siege; its army, if any is left, marches back."""
        p = self.s.provinces[province]
        besieger = p.siege_by
        if besieger is None:
            return
        came, seasoned = p.siege_from, p.siege_veterancy
        army = p.end_siege()
        regiments = sum(army.values())
        home = self._camp(besieger, came, province) if regiments else None
        if home is not None:
            self.s.provinces[home].add(army, seasoned)
        back = f": {regiments} regiments march back to {self._pname(home)}" if home else ""
        self._emit(
            EventKind.SIEGE,
            f"The siege of {self._pname(province)} by {self._name(besieger)} is lifted "
            f"({why}){back}",
            nations=(besieger, p.holder) if p.holder else (besieger,),
            province=province,
            lifted=True,
            regiments=regiments,
        )

    def _sieges(self) -> None:
        """Every siege rolls its year: a die, the modifiers, and the progress they buy."""
        rules = self.s.rules
        for pid in sorted(self.s.provinces):
            p = self.s.provinces[pid]
            besieger = p.siege_by
            if besieger is None:
                continue
            if not self.s.nations[besieger].alive:
                p.end_siege()
                continue
            seasoned = p.siege_veterancy
            if p.holder == besieger:  # it changed hands by treaty: the lines move in
                p.add(p.end_siege(), seasoned)
                continue
            if p.holder is not None and not self.s.at_war(besieger, p.holder):
                self._lift(pid, "the war is over")
                continue
            army = p.siege_army()
            regiments = sum(army.values())
            if regiments == 0:
                p.end_siege()
                continue
            if self._walls(besieger, pid, army) == 0:
                came = p.siege_from
                self._capture(besieger, pid, p.end_siege(), origin=came, veterancy=seasoned)
                continue
            mods = siege_modifiers(self.s, pid)
            die = self.rng.randint(1, 6)
            score = die + sum(v for _, v in mods)
            gain, result = siege_result(rules, score)
            p.siege_years += 1
            lost = 0
            if gain == rules.siege_results[0][1]:  # the worst roll: disease
                lost = max(1, round(regiments * rules.siege_disease))
                gone = share(army, lost)
                army = {k: army[k] - gone[k] for k in UnitKind}
                p.besiegers = {k: n for k, n in army.items() if n}
            p.siege_progress = min(100, p.siege_progress + gain)
            sums = "".join(f" {'+' if v > 0 else '-'}{abs(v)} {label}" for label, v in mods)
            self._emit(
                EventKind.SIEGE,
                f"Siege of {self._pname(pid)} by {self._name(besieger)}, year {p.siege_years}: "
                f"rolled {die}{sums} = {score}: {result} (+{gain}%)"
                + (f", {lost} regiments dead of it" if lost else "")
                + f". {p.siege_progress}% done",
                nations=(besieger, p.holder) if p.holder else (besieger,),
                province=pid,
                die=die,
                score=score,
                result=result,
                gain=gain,
                progress=p.siege_progress,
                modifiers="; ".join(f"{label} {v:+d}" for label, v in mods),
                lost=lost,
                regiments=sum(army.values()),
            )
            left = sum(army.values())
            if p.siege_progress >= 100 and left > 0:
                came = p.siege_from
                self._capture(besieger, pid, p.end_siege(), origin=came, veterancy=seasoned)
            elif left == 0:
                p.end_siege()

    def _battle_counts(self, attacker: NationId, defender: NationId | None, *, won: bool) -> None:
        """Battles between great powers feed the war score and the loser's exhaustion."""
        if defender is None:
            return
        war = self.s.war(attacker, defender)
        if war is None:
            return
        winner, loser = (attacker, defender) if won else (defender, attacker)
        war.battles[winner] = war.battles.get(winner, 0) + 1
        self._prestige(winner, self.s.rules.prestige_battle, "a battle won")
        self._prestige(loser, -self.s.rules.prestige_battle, "a battle lost")
        self._exhaust(loser, self.s.rules.exhaustion_per_battle_lost)

    def _exhaust(self, nation: NationId, amount: float) -> None:
        state = self.s.nations[nation]
        rules = self.s.rules
        state.war_exhaustion = round(
            max(0.0, min(rules.exhaustion_max, state.war_exhaustion + amount)), 2
        )

    def _rivalry(self, nation: NationId | None, against: NationId | None) -> float:
        """Regiments fight harder against a declared rival."""
        if nation is None or against is None:
            return 1.0
        if self.s.nations[nation].stances.get(against) == Stance.RIVAL:
            return 1 + self.s.rules.rival_battle_bonus
        return 1.0

    def _capture(
        self,
        nation: NationId,
        province: ProvinceId,
        troops: dict[UnitKind, int],
        general: General | None = None,
        *,
        origin: ProvinceId | None = None,
        veterancy: float = 0.0,
    ) -> None:
        """Take a province. Independent land is annexed at once; a great power's is occupied
        until a peace says otherwise; one's own (or an ally's) is liberated."""
        state: ProvinceState = self.s.provinces[province]
        previous = state.owner
        beaten = self.s.general_in(province)
        if beaten is not None and beaten.nation != nation:
            self._general_falls(beaten, province)
        if state.siege_by is not None:
            self._lift(province, "the town has fallen")
        if previous is not None and (previous == nation or not self.s.at_war(nation, previous)):
            self._liberate(nation, province, troops, general, origin, veterancy)
            return
        if general is not None and self.s.general_in(province) is None:
            general.province = province
        if previous is not None:
            self._occupy(nation, province, troops, origin, veterancy)
            return
        state.owner = nation
        state.posture = Posture.HOLD  # the new garrison waits as it was drilled
        state.set_army(troops, veterancy)
        state.unrest = self.s.rules.unrest_turns
        if state.faith is not None and state.faith != self.s.nations[nation].faith:
            state.unrest += self.s.rules.faith_conquest_unrest
        self._expand(nation, province)
        loser = self._name(previous) if previous else "independence"
        if previous is not None:
            self._opine(previous, nation, self.s.rules.opinion_province_taken)
        self._emit(
            EventKind.PROVINCE_CAPTURED,
            f"{self._name(nation)} takes {self._pname(province)} from {loser}",
            nations=(nation, previous) if previous else (nation,),
            province=province,
            origin=origin or "",
        )

    def _after_loss(self, loser: NationId, province: ProvinceId, to: NationId) -> None:
        """A nation lost a province for good: it may have to move its capital, or vanish."""
        remaining = self.s.provinces_of(loser)
        if not remaining:
            self._eliminate(loser, by=to)
            return
        loser_state = self.s.nations[loser]
        if loser_state.capital == province:
            new_capital = min(remaining, key=lambda p: (-self.s.provinces[p].development, p))
            loser_state.capital = new_capital
            self._emit(
                EventKind.CAPITAL_MOVED,
                f"{loser_state.name} loses its capital and moves it to {self._pname(new_capital)}",
                nations=(loser,),
                province=new_capital,
            )
            self._change_stability(loser, -1, "lost its capital")

    def _occupy(
        self,
        nation: NationId,
        province: ProvinceId,
        troops: dict[UnitKind, int],
        origin: ProvinceId | None = None,
        veterancy: float = 0.0,
    ) -> None:
        state = self.s.provinces[province]
        owner = state.owner
        assert owner is not None  # noqa: S101 (only great powers' land is occupied)
        state.controller = nation
        state.posture = Posture.HOLD
        state.set_army(troops, veterancy)
        self._opine(owner, nation, self.s.rules.opinion_province_taken)
        self._emit(
            EventKind.PROVINCE_OCCUPIED,
            f"{self._name(nation)} occupies {self._pname(province)}, "
            f"a province of {self._name(owner)}",
            nations=(nation, owner),
            province=province,
            origin=origin or "",
        )
        if self.s.nations[owner].capital == province:
            self._change_stability(owner, -1, "its capital is occupied")

    def _liberate(
        self,
        nation: NationId,
        province: ProvinceId,
        troops: dict[UnitKind, int],
        general: General | None,
        origin: ProvinceId | None,
        veterancy: float = 0.0,
    ) -> None:
        """Win back a province from its occupier, for oneself or for an ally."""
        state = self.s.provinces[province]
        owner = state.owner
        state.controller = None
        state.posture = Posture.HOLD
        if owner == nation:
            state.set_army(troops, veterancy)
            if general is not None and self.s.general_in(province) is None:
                general.province = province
        else:  # an ally's land: hand it back and go home
            state.set_army({})
            if origin is not None:
                self.s.provinces[origin].add(troops, veterancy)
        self._emit(
            EventKind.PROVINCE_LIBERATED,
            f"{self._name(nation)} frees {self._pname(province)}"
            + (f" for {self._name(owner)}" if owner and owner != nation else ""),
            nations=(nation, owner) if owner and owner != nation else (nation,),
            province=province,
            origin=origin or "",
        )

    def _general_falls(self, general: General, province: ProvinceId) -> None:
        self.s.generals.remove(general)
        self.fallen[general.nation] += 1
        self._emit(
            EventKind.GENERAL_FELL,
            f"{general.name} of {self._name(general.nation)} falls at {self._pname(province)}",
            nations=(general.nation,),
            province=province,
        )

    def _eliminate(self, nation: NationId, *, by: NationId) -> None:
        state = self.s.nations[nation]
        self.s.generals = [g for g in self.s.generals if g.nation != nation]
        state.alive = False
        state.resources = Resources()
        state.fleets, state.colonies, state.expeditions = {}, {}, []
        for p in self.s.provinces.values():
            if p.controller == nation:  # its occupying armies melt away
                p.controller = None
                p.set_army({})
            if p.siege_by == nation:  # and its siege lines
                p.end_siege()
        self.s.wars = [w for w in self.s.wars if nation not in w.parties]
        self.s.treaties = [t for t in self.s.treaties if nation not in t.parties]
        self.s.proposals = [
            p for p in self.s.proposals if nation not in (p.sender, p.recipient, p.enemy)
        ]
        self._emit(
            EventKind.NATION_ELIMINATED,
            f"{state.name} is wiped off the map by {self._name(by)}",
            nations=(nation, by),
        )

    # ------------------------------------------------------------ phase 6: end of turn

    def _end_of_turn(self) -> None:
        for nation in self.s.alive_nations():
            self._produce_and_feed(nation)
        self._pay_tributes()
        self._taxes()
        self._faiths()
        self._infamy_fades()
        self._missions()
        self._drift_opinions()
        self._weary()
        self._fortune()
        self._history()
        self._crisis()
        self._move_prices()
        self._sieges()
        self._expeditions()
        decay = self.s.rules.veterancy_decay  # the veterans grow old and go home
        for province in self.s.provinces.values():
            settles = 2 if BuildingKind.CATHEDRAL in province.buildings else 1
            province.unrest = max(0, province.unrest - settles)
            province.veterancy = round(max(0.0, province.veterancy - decay), 3)
            province.siege_veterancy = round(max(0.0, province.siege_veterancy - decay), 3)
        self._age_rulers()
        for treaty in [t for t in self.s.treaties if t.until is not None and t.until <= self.turn]:
            self.s.treaties.remove(treaty)
            a, b = treaty.parties
            self._emit(
                EventKind.TREATY_EXPIRED,
                f"The {treaty.kind.value.replace('_', ' ')} between {self._name(a)} and "
                f"{self._name(b)} expires",
                nations=(a, b),
                treaty=treaty.kind.value,
            )
        self._check_victory()
        if not self.s.finished:
            self.s.turn += 1

    def _fortune(self) -> None:
        """Last year's unanswered events take their first option; debts are paid; and fortune
        may bring each nation a new event for next year."""
        rules = self.s.rules
        for nation in self.s.alive_nations():
            me = self.s.nations[nation]
            for pending in [e for e in me.pending_events if e.turn < self.turn]:
                self._decide(nation, pending, 0)
            for loan in list(me.loans):
                paid = min(loan.yearly, me.resources.ducats)
                me.resources = me.resources - Resources(ducats=paid)
                if loan.until <= self.turn:
                    me.loans.remove(loan)
            if me.prestige > 0:
                me.prestige = max(0, me.prestige - rules.prestige_decay)
            if me.pending_events:
                continue
            drawn = fortune.roll(self.s, nation, self.rng, rules.event_chance)
            if drawn is None:
                continue
            spec, province = drawn
            pending = PendingEvent(
                id=self.s.next_event_id, event=spec.id, turn=self.turn, province=province
            )
            self.s.next_event_id += 1
            me.pending_events.append(pending)
            if spec.once:
                me.events_seen.append(spec.id)
            self._emit(
                EventKind.EVENT_HAPPENED,
                f"{spec.title} in {me.name}: the crown must decide",
                nations=(nation,),
                audience=(nation,),
                event=spec.id,
            )

    def _crisis(self) -> None:
        """The age's great trouble: drawn on the first year, announced the year before it
        falls, raging for its years (the plague takes towns), and then passing."""
        rules = self.s.rules
        if self.s.crisis is None:
            dice = random.Random(f"{self.s.seed}:crisis")  # noqa: S311 (game dice)
            lo, hi = rules.crisis_window
            hi = min(hi, self.s.max_turns - 2)
            kind = dice.choice(sorted(fortune.CRISES))
            start = dice.randint(lo, hi) if hi >= lo else 10**6
            self.s.crisis = Crisis(kind=kind, start=start, end=start + fortune.CRISES[kind].years)
        c, spec = self.s.crisis, fortune.CRISES.get(self.s.crisis.kind)
        if spec is None:
            return
        first, last = self.s.rules.start_year - 1 + c.start, self.s.rules.start_year - 1 + c.end - 1
        if self.turn + 1 == c.start:  # it falls on Europe next year: every crown must answer
            self._emit(
                EventKind.CRISIS,
                f"{spec.title}, {first} to {last}: {spec.text}",
                crisis=spec.id,
                begins=True,
                first=first,
                last=last,
            )
            event = fortune.EVENTS_BY_ID[spec.event]
            for nation in self.s.alive_nations():
                me = self.s.nations[nation]
                me.pending_events.append(
                    PendingEvent(id=self.s.next_event_id, event=event.id, turn=self.turn)
                )
                self.s.next_event_id += 1
        if c.kind == "plague" and c.start <= self.turn < c.end:
            self._plague()
        if self.turn + 1 == c.end:
            self._emit(
                EventKind.CRISIS,
                f"{spec.title} passes: Europe counts what it lost",
                crisis=spec.id,
                begins=False,
                first=first,
                last=last,
            )
            for realm in self.s.nations.values():
                realm.flags = [f for f in realm.flags if f != "quarantine"]

    def _plague(self) -> None:
        """A year of the Great Plague: each town may lose people, fewer behind closed gates."""
        for nation in self.s.alive_nations():
            closed = "quarantine" in self.s.nations[nation].flags
            chance = 0.06 if closed else 0.18
            struck = [
                pid
                for pid in self.s.provinces_of(nation)
                if self.s.provinces[pid].development >= 2
                and not self.s.provinces[pid].controller
                and self.rng.random() < chance
            ]
            for pid in struck:
                self.s.provinces[pid].development -= 1
            if struck:
                names = ", ".join(self._pname(p) for p in struck)
                self._emit(
                    EventKind.PLAGUE,
                    f"The plague carries off the people of {names} ({self._name(nation)}): "
                    f"-1 development each",
                    nations=(nation,),
                    province=struck[0],
                    towns=len(struck),
                    closed=closed,
                )

    def _prestige(self, nation: NationId, delta: int, reason: str) -> None:
        me = self.s.nations[nation]
        new = max(0, min(self.s.rules.prestige_max, me.prestige + delta))
        if new == me.prestige:
            return
        me.prestige = new
        self._emit(
            EventKind.PRESTIGE_CHANGED,
            f"{me.name}'s prestige is now {new} ({reason})",
            nations=(nation,),
            audience=(nation,),
            prestige=new,
            delta=delta,
        )

    def _weary(self) -> None:
        """War exhaustion: every year of war, every province under occupation, weighs on a
        realm; peace lets it recover. Past the threshold, it costs stability."""
        rules = self.s.rules
        for nation in self.s.alive_nations():
            wars = len(self.s.enemies_of(nation))
            if wars:
                lost = len(self.s.occupied_from(nation))
                self._exhaust(
                    nation,
                    rules.exhaustion_per_war_year * wars
                    + rules.exhaustion_per_province_occupied * lost,
                )
            else:
                self._exhaust(nation, -rules.exhaustion_recovery)
            if self.s.nations[nation].war_exhaustion >= rules.exhaustion_unrest_threshold:
                self._change_stability(nation, -1, "war exhaustion")

    def _work(self, nation: NationId) -> tuple[Resources, Resources]:
        """This year's income and the buildings' inputs it pays for. A building whose inputs the
        treasury and the year's yield cannot cover stands idle and yields nothing."""
        for pid in self.s.provinces_of(nation):
            self.s.provinces[pid].idle = []
        idle: list[tuple[ProvinceId, BuildingKind]] = []
        while True:  # an idle building yields less, which may leave another unfed in turn
            income = nation_income(self.s, nation)
            available = self.s.nations[nation].resources + income
            paid, short = Resources(), []
            for pid, kind in building_inputs(self.s, nation):
                if (pid, kind) in idle:
                    continue
                need = building_consumes(self.s.rules, kind, self.s.provinces[pid].level(kind))
                if available.covers(need):
                    available = available - need
                    paid = paid + need
                else:
                    short.append((pid, kind))
            if not short:
                break
            for pid, kind in short:
                idle.append((pid, kind))
                self.s.provinces[pid].idle.append(kind)
        if idle:
            names = ", ".join(
                f"{self.s.rules.buildings[k].name.lower()} in {self._pname(pid)}" for pid, k in idle
            )
            self._emit(
                EventKind.BUILDINGS_IDLE,
                f"{self._name(nation)}'s {names} stand idle for want of their inputs",
                nations=(nation,),
                audience=(nation,),
                count=len(idle),
            )
        return income, paid

    def _pay_tributes(self) -> None:
        for t in self.s.treaties:
            if t.kind != TreatyKind.TRIBUTE or t.payer is None:
                continue
            payee = t.parties[1] if t.parties[0] == t.payer else t.parties[0]
            payer = self.s.nations[t.payer]
            amount = min(t.amount, payer.resources.ducats)
            if not amount:
                continue
            payer.resources = payer.resources - Resources(ducats=amount)
            receiver = self.s.nations[payee]
            receiver.resources = receiver.resources + Resources(ducats=amount)
            self._emit(
                EventKind.TRIBUTE_PAID,
                f"{payer.name} pays {self._name(payee)} its tribute of {amount} ducats",
                nations=(t.payer, payee),
                audience=(t.payer, payee),
                ducats=amount,
            )

    def _drift_opinions(self) -> None:
        """Grudges and friendships fade; a common enemy brings courts together."""
        rules = self.s.rules
        unforgiven = set()
        for nation in self.s.nations.values():  # what a court will not forget keeps weighing
            nation.grudges = [g for g in nation.grudges if g.until > self.turn]
            for g in nation.grudges:
                if self.s.nations[g.against].alive:
                    self._opine(nation.id, g.against, -g.weight)
                    unforgiven.add((nation.id, g.against))
        for holder, opinions in self.s.opinions.items():
            for other, value in list(opinions.items()):
                if (holder, other) in unforgiven and value < 0:
                    continue  # a wound that does not heal while the grudge lasts
                fade = max(1, round(abs(value) * rules.opinion_decay)) if value else 0
                opinions[other] = value - fade if value > 0 else value + fade
        alive = self.s.alive_nations()
        for a in alive:
            enemies = set(self.s.enemies_of(a))
            for b in alive:
                if a != b and enemies & set(self.s.enemies_of(b)) and (a, b) not in unforgiven:
                    self._opine(a, b, rules.opinion_shared_enemy)
            for b in alive:
                if a != b:
                    fa, fb = self.s.nations[a].faith, self.s.nations[b].faith
                    infidel = (fa == Faith.SUNNI) != (fb == Faith.SUNNI)
                    drift = (
                        rules.opinion_same_faith
                        if fa == fb
                        else rules.opinion_infidel
                        if infidel
                        else rules.opinion_other_faith
                    )
                    if drift < 0 or (a, b) not in unforgiven:  # a shared faith heals no wrong
                        self._opine(a, b, drift)
            feared = self.s.nations[a].infamy
            if feared >= rules.coalition_infamy / 2:  # a conqueror cools every court
                for other in alive:
                    if other != a:
                        self._opine(other, a, -int(feared // 10) - 1)
            for spouse in self.s.partners(a, TreatyKind.MARRIAGE):
                self._opine(a, spouse, rules.opinion_marriage_yearly)
            for target, stance in self.s.nations[a].stances.items():
                if target in alive:  # a declared stance colours both courts
                    self._opine(target, a, rules.opinion_stance.get(stance.value, 0))
                    self._opine(a, target, rules.opinion_stance.get(stance.value, 0))
            ruler = self.s.nations[a].ruler
            traits = ruler.traits if ruler else []
            for other in alive:
                if Trait.CHARMING in traits:
                    self._opine(other, a, rules.opinion_charming)
                if Trait.CRUEL in traits:
                    self._opine(other, a, rules.opinion_cruel)

    def _produce_and_feed(self, nation: NationId) -> None:
        """Income arrives, the manpower pool is capped, and the army is fed and paid. Every
        regiment that cannot be fed or paid deserts."""
        rules = self.s.rules
        state = self.s.nations[nation]
        income, inputs = self._work(nation)
        state.resources = state.resources + income - inputs  # inputs never exceed what is there
        cap = manpower_cap(self.s, nation)
        if state.resources.manpower > cap:
            state.resources = state.resources.model_copy(update={"manpower": cap})
        self._pay_council(nation)
        self._pay_fleet(nation)
        factor = modifiers(self.s, nation).grain_upkeep_factor
        upkeep = army_upkeep(rules, army_of(self.s, nation), factor)
        paid = upkeep.capped_by(state.resources)
        state.resources = state.resources - paid
        if paid == upkeep:
            return
        # Regiments eat and earn differently by kind: desert by the average.
        regiments = max(1, self.s.troops_of(nation))
        unfed = math.ceil((upkeep.grain - paid.grain) / max(1e-9, upkeep.grain / regiments))
        unpaid = math.ceil((upkeep.ducats - paid.ducats) / max(1e-9, upkeep.ducats / regiments))
        deserters = max(unfed, unpaid)
        if deserters <= 0:  # short only of iron: the army makes do with worn gear
            return
        deserted = 0
        for _ in range(deserters):
            garrisons = [p for p in self.s.held_by(nation) if self.s.provinces[p].troops]
            if not garrisons:
                break
            biggest = min(garrisons, key=lambda p: (-self.s.provinces[p].troops, p))
            self.s.provinces[biggest].take(1)
            deserted += 1
        lack = " and ".join(
            word for word, short in (("grain", unfed), ("pay", unpaid)) if short > 0
        )
        self._emit(
            EventKind.DESERTION,
            f"{deserted} of {state.name}'s regiments desert for lack of {lack}",
            nations=(nation,),
            audience=(nation,),
            regiments=deserted,
        )

    def _check_victory(self) -> None:
        alive = self.s.alive_nations()
        total = len(self.s.provinces)
        winner, reason = None, ""
        if len(alive) == 1:
            winner, reason = alive[0], "last nation standing"
        else:
            needed = math.ceil(self.s.rules.domination_share * total)
            dominant = [n for n in alive if len(self.s.provinces_of(n)) >= needed]
            # a crown that fulfils every ambition of its history has won its own game
            destined = [
                n
                for n in alive
                if self.s.rules.ambition_victory
                and missions.missions_of(n)
                and {m.id for m in missions.missions_of(n)} <= set(self.s.nations[n].missions_done)
            ]
            if dominant:
                winner = max(dominant, key=lambda n: len(self.s.provinces_of(n)))
                reason = f"rules {len(self.s.provinces_of(winner))} of {total} provinces"
            elif destined:
                winner = min(destined, key=self._ranking)
                reason = (
                    f"fulfilled every ambition of its crown ({len(missions.missions_of(winner))})"
                )
            elif self.turn >= self.s.max_turns:
                winner = min(alive, key=self._ranking)
                reason = (
                    f"highest standing ({self.s.standing(winner)}: development "
                    f"{self.s.score(winner)}, prestige {self.s.nations[winner].prestige}) "
                    "when time ran out"
                )
        if winner is None:
            return
        self.s.finished = True
        self.s.winner = winner
        self._emit(
            EventKind.GAME_OVER,
            f"{self._name(winner)} wins: {reason}",
            nations=(winner,),
            reason=reason,
        )

    def _ranking(self, nation: NationId) -> tuple[int, int, int, str]:
        return (
            -self.s.standing(nation),
            -len(self.s.provinces_of(nation)),
            -self.s.nations[nation].resources.ducats,
            nation,
        )

    def _year(self, turn: int) -> int:
        return self.s.rules.start_year + turn - 1


def _terms(t: Terms, kind: ProposalKind) -> dict[str, object]:
    """A proposal's fields from an action's terms."""
    if kind == ProposalKind.TRADE:
        return {"give": t.give, "receive": t.receive, "note": t.note}
    return t.model_dump(include=set(Terms.model_fields))


def _as_terms(p: Proposal) -> Terms:
    return Terms(cede=p.cede, demand=p.demand)


def _article(name: str) -> str:
    noun = name.lower()
    if noun.endswith("s"):  # farm estates
        return noun
    return f"an {noun}" if noun[0] in "aeiou" else f"a {noun}"


def _flat(prefix: str, resources: Resources) -> dict[str, EventValue]:
    return {f"{prefix}_{k}": v for k, v in resources.model_dump().items() if v}
