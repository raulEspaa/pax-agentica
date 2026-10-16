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

from pax_agentica.engine.actions import (
    Action,
    AssignGeneral,
    Attack,
    BoostStability,
    Build,
    CancelTreaty,
    DeclareWar,
    Develop,
    Disband,
    DismissAdvisor,
    Gift,
    HireAdvisor,
    HireGeneral,
    Move,
    Orders,
    Proclaim,
    ProposeAlliance,
    ProposeNonAggression,
    ProposePeace,
    ProposeTrade,
    Recruit,
    RequestCallToArms,
    Research,
    Respond,
    SendMessage,
    SetStance,
    Terms,
    UpgradeMonument,
)
from pax_agentica.engine.events import Event, EventKind, EventValue
from pax_agentica.engine.mechanics import (
    army_of,
    army_strength,
    army_upkeep,
    battle_factor,
    building_cost,
    building_slots,
    defense_multiplier,
    develop_cost,
    fight,
    manpower_cap,
    nation_income,
    peace_cost,
    recruit_cost,
    research_cost,
    siege_levels,
    stability_cost,
    war_score,
)
from pax_agentica.engine.model import (
    BuildingKind,
    GameState,
    General,
    NationId,
    Proposal,
    ProposalKind,
    ProvinceId,
    ProvinceState,
    Resources,
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
    make_ruler,
    modifiers,
)


class GameOverError(Exception):
    """Raised when asked to resolve a turn of a finished game."""


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
        self.besieged: set[ProvinceId] = set()  # sieges pressed this year
        self.fallen: dict[NationId, int] = dict.fromkeys(self.s.nations, 0)

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
        self.events.append(
            Event(
                turn=self.turn,
                kind=kind,
                summary=summary,
                nations=nations,
                province=province,
                audience=audience,
                data={**data, **(extra or {})},
            )
        )

    def _reject(self, nation: NationId, action: Action, reason: str) -> None:
        self._emit(
            EventKind.ORDER_REJECTED,
            f"{action.type} rejected: {reason}",
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
            for action in self._actions(nation, Respond):
                proposal = next((p for p in self.s.proposals if p.id == action.proposal_id), None)
                if proposal is None or proposal.recipient != nation:
                    self._reject(
                        nation, action, f"no pending proposal #{action.proposal_id} for you"
                    )
                    continue
                self.s.proposals.remove(proposal)
                if action.accept:
                    self._accept(proposal)
                elif action.counter is not None:
                    self._counter(nation, proposal, action, action.counter)
                else:
                    self._decline(proposal)

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
            case ProposalKind.CALL_TO_ARMS:
                enemy = p.enemy
                if enemy is None or not self.s.nations[enemy].alive or not self.s.at_war(s, enemy):
                    self._expired(p, "that war is over")
                    return
                if not self.s.at_war(r, enemy):
                    self._start_war(r, enemy, joined_for=s)

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
                p.siege_by, p.siege_years = None, 0

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
        if state.controller == to:
            state.controller = None
            state.owner = to
            state.unrest = self.s.rules.ceded_unrest_turns
            self._opine(frm, to, self.s.rules.opinion_province_taken // 2)
            self._emit(
                EventKind.PROVINCE_CEDED,
                f"{self._name(frm)} cedes {self._pname(province)} to {self._name(to)}",
                nations=(frm, to),
                province=province,
            )
            self._after_loss(frm, province, to)
            return
        giver = self.s.nations[frm]
        giver.resources = giver.resources + self.s.rules.disband_refund.times(state.troops)
        state.set_army({})
        general = self.s.general_in(province)
        if general is not None:
            free = [
                p for p in self.s.provinces_of(frm) if p != province and not self.s.general_in(p)
            ]
            home = giver.capital if giver.capital in free else (free[0] if free else None)
            if home is None:
                self.s.generals.remove(general)
            else:
                general.province = home
        state.owner = to
        state.controller = None
        state.unrest = self.s.rules.ceded_unrest_turns
        self._opine(frm, to, self.s.rules.opinion_province_taken // 2)
        self._emit(
            EventKind.PROVINCE_CEDED,
            f"{self._name(frm)} cedes {self._pname(province)} to {self._name(to)}",
            nations=(frm, to),
            province=province,
        )
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
            penalty = modifiers(self.s, attacker).treaty_break_penalty
            self._change_stability(attacker, -penalty, "broke a treaty")
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
                    case ProposeAlliance() | ProposeNonAggression() | ProposePeace():
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
        treaty = self.s.treaty(nation, a.target, TreatyKind(a.kind))
        if treaty is None:
            self._reject(nation, a, f"no {a.kind.replace('_', ' ')} with {self._name(a.target)}")
            return
        self.s.treaties.remove(treaty)
        self._emit(
            EventKind.TREATY_CANCELLED,
            f"{self._name(nation)} ends its {a.kind.replace('_', ' ')} with {self._name(a.target)}",
            nations=(nation, a.target),
            treaty=a.kind,
        )

    def _propose_treaty(
        self, nation: NationId, a: ProposeAlliance | ProposeNonAggression | ProposePeace
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
        self._propose(kind, nation, a.target)

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
        self._propose(ProposalKind.CALL_TO_ARMS, nation, a.target, enemy=a.enemy)

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
            n * w for n, w in zip(a.resources.amounts().values(), (1, 3, 2, 1, 2), strict=True)
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
        for nation in self.order:
            for action in self.orders[nation]:
                match action:
                    case Recruit():
                        self._recruit(nation, action)
                    case Develop():
                        self._develop(nation, action)
                    case Disband():
                        self._disband(nation, action)
                    case Build():
                        self._build(nation, action)
                    case UpgradeMonument():
                        self._upgrade_monument(nation, action)
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
        for limit in self.s.treaties:
            bound = limit.kind == TreatyKind.ARMY_LIMIT and limit.payer == nation
            if bound and self.s.troops_of(nation) + a.regiments > limit.amount:
                other = limit.parties[1] if limit.parties[0] == nation else limit.parties[0]
                self._reject(
                    nation,
                    a,
                    f"the peace with {self._name(other)} limits your army to "
                    f"{limit.amount} regiments",
                )
                return
        cost = recruit_cost(rules, a.regiments, province.buildings, a.unit)
        if error := self._pay(nation, cost):
            self._reject(nation, a, error)
            return
        province.add({a.unit: a.regiments})
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
        if error := self._pay(nation, cost):
            self._reject(nation, a, error)
            return
        self.researched.add(nation)
        me.technology[a.branch] = level + 1
        self._emit(
            EventKind.RESEARCHED,
            f"{me.name} reaches {a.branch.value} technology {level + 1}",
            nations=(nation,),
            branch=a.branch.value,
            level=level + 1,
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
        slots = building_slots(rules, province.development, mods.extra_building_slots)
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
            error = (
                f"all {slots} building slots of {where} are taken; develop it to "
                f"{(slots) * rules.development_per_building_slot} for another"
            )
        else:
            error = self._pay(nation, building_cost(rules, a.building, mods.building_discount))
        if error:
            self._reject(nation, a, error)
            return
        province.buildings.append(a.building)
        self._emit(
            EventKind.BUILT,
            f"{self._name(nation)} builds {_article(spec.name)} in {where}",
            nations=(nation,),
            province=a.province,
            building=a.building.value,
        )

    # ------------------------------------------------------------ phase 4: movement

    def _movement(self) -> None:
        for nation in self.order:
            for a in self._actions(nation, Move):
                error = self._hold_error(nation, a.origin) or self._hold_error(nation, a.target)
                if not error and not self.s.map.adjacent(a.origin, a.target):
                    error = f"{self._pname(a.origin)} and {self._pname(a.target)} do not border"
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
                moved = self.s.provinces[a.origin].take(a.regiments, a.units)
                self.s.provinces[a.target].add(moved)
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
        queues = {n: list(self._actions(n, Attack)) for n in self.order}
        while any(queues.values()):
            for nation in self.order:
                if queues[nation] and self.s.nations[nation].alive:
                    self._attack(nation, queues[nation].pop(0))
                elif queues[nation]:
                    queues[nation].clear()

    def _attack(self, nation: NationId, a: Attack) -> None:
        if a.target not in self.s.provinces:
            self._reject(nation, a, f"there is no province '{a.target}'")
            return
        if error := self._hold_error(nation, a.origin):
            self._reject(nation, a, error)
            return
        if not self.s.map.adjacent(a.origin, a.target):
            self._reject(
                nation, a, f"{self._pname(a.origin)} and {self._pname(a.target)} do not border"
            )
            return
        origin, target = self.s.provinces[a.origin], self.s.provinces[a.target]
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
        force = origin.take(min(a.regiments, origin.troops), a.units)
        committed = sum(force.values())
        attacker_name = self._name(nation)
        if general:
            attacker_name += f" under {general.name}"
        defender_name = self._name(defender) if defender else "the local levies"
        walls = self._walls(nation, a.target, force)
        if target.troops == 0:
            if walls:
                self._siege(nation, a, force, general, walls)
            else:
                self._capture(nation, a.target, force, general, origin=a.origin)
            return
        guard = self.s.general_in(a.target)
        if guard and guard.nation != defender:
            guard = None
        if guard:
            defender_name += f" under {guard.name}"
        rules = self.s.rules
        ground = self.s.map.provinces[a.target].terrain
        held = target.army()
        result = fight(
            rules,
            committed,
            target.troops,
            defense_multiplier(self.s, a.origin, a.target, siege_levels(rules, force)),
            self.rng,
            attack_factor=battle_factor(self.s, nation, general.skill if general else 0)
            * self._rivalry(nation, defender),
            defence_factor=battle_factor(self.s, defender, guard.skill if guard else 0)
            * self._rivalry(defender, nation),
            attack_quality=army_strength(rules, force, ground, attacking=True) / committed,
            defence_quality=army_strength(rules, held, ground, attacking=False) / target.troops,
        )
        verdict = "wins" if result.attacker_won else "is repulsed"
        self._emit(
            EventKind.BATTLE,
            f"Battle of {self._pname(a.target)}: {attacker_name} ({committed}) attacks "
            f"{defender_name} ({target.troops}) from {self._pname(a.origin)} and {verdict}; "
            f"losses {result.attacker_losses} to {result.defender_losses}",
            nations=(nation, defender) if defender else (nation,),
            province=a.target,
            attacker_regiments=committed,
            defender_regiments=target.troops,
            attacker_losses=result.attacker_losses,
            defender_losses=result.defender_losses,
            attacker_won=result.attacker_won,
        )
        self._battle_counts(nation, defender, won=result.attacker_won)
        if result.attacker_won:
            fallen = share(force, result.attacker_losses)
            survivors = {k: force[k] - fallen[k] for k in UnitKind}
            if walls:
                target.set_army({})  # the garrison is beaten, the walls still stand
                self._siege(nation, a, survivors, general, walls)
            else:
                self._capture(nation, a.target, survivors, general, origin=a.origin)
        else:
            target.take(result.defender_losses)

    def _walls(self, nation: NationId, province: ProvinceId, force: dict[UnitKind, int]) -> int:
        """Fort levels still standing against this army: each holds out a year of siege."""
        target = self.s.provinces[province]
        ignored = modifiers(self.s, nation).ignores_fort_levels
        return max(0, target.fort - ignored - siege_levels(self.s.rules, force))

    def _siege(
        self,
        nation: NationId,
        a: Attack,
        force: dict[UnitKind, int],
        general: General | None,
        walls: int,
    ) -> None:
        target = self.s.provinces[a.target]
        target.siege_years = target.siege_years + 1 if target.siege_by == nation else 1
        target.siege_by = nation
        self.besieged.add(a.target)
        if target.siege_years > walls:  # each level of wall holds out a year
            target.siege_by, target.siege_years = None, 0
            self._capture(nation, a.target, force, general, origin=a.origin)
            return
        self.s.provinces[a.origin].add(force)  # the besiegers camp at home for the winter
        self._emit(
            EventKind.SIEGE,
            f"The walls of {self._pname(a.target)} hold against {self._name(nation)}: "
            f"they fall at the next assault after {walls} year{'s' if walls > 1 else ''} of siege "
            f"({target.siege_years} so far)",
            nations=(nation, target.holder) if target.holder else (nation,),
            province=a.target,
            years=target.siege_years,
            walls=walls,
        )

    def _battle_counts(self, attacker: NationId, defender: NationId | None, *, won: bool) -> None:
        """Battles between great powers feed the war score and the loser's exhaustion."""
        if defender is None:
            return
        war = self.s.war(attacker, defender)
        if war is None:
            return
        winner, loser = (attacker, defender) if won else (defender, attacker)
        war.battles[winner] = war.battles.get(winner, 0) + 1
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
    ) -> None:
        """Take a province. Independent land is annexed at once; a great power's is occupied
        until a peace says otherwise; one's own (or an ally's) is liberated."""
        state: ProvinceState = self.s.provinces[province]
        previous = state.owner
        beaten = self.s.general_in(province)
        if beaten is not None and beaten.nation != nation:
            self._general_falls(beaten, province)
        state.siege_by, state.siege_years = None, 0
        if previous is not None and (previous == nation or not self.s.at_war(nation, previous)):
            self._liberate(nation, province, troops, general, origin)
            return
        if general is not None and self.s.general_in(province) is None:
            general.province = province
        if previous is not None:
            self._occupy(nation, province, troops)
            return
        state.owner = nation
        state.set_army(troops)
        state.unrest = self.s.rules.unrest_turns
        loser = self._name(previous) if previous else "independence"
        if previous is not None:
            self._opine(previous, nation, self.s.rules.opinion_province_taken)
        self._emit(
            EventKind.PROVINCE_CAPTURED,
            f"{self._name(nation)} takes {self._pname(province)} from {loser}",
            nations=(nation, previous) if previous else (nation,),
            province=province,
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

    def _occupy(self, nation: NationId, province: ProvinceId, troops: dict[UnitKind, int]) -> None:
        state = self.s.provinces[province]
        owner = state.owner
        assert owner is not None  # noqa: S101 (only great powers' land is occupied)
        state.controller = nation
        state.set_army(troops)
        self._opine(owner, nation, self.s.rules.opinion_province_taken)
        self._emit(
            EventKind.PROVINCE_OCCUPIED,
            f"{self._name(nation)} occupies {self._pname(province)}, "
            f"a province of {self._name(owner)}",
            nations=(nation, owner),
            province=province,
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
    ) -> None:
        """Win back a province from its occupier, for oneself or for an ally."""
        state = self.s.provinces[province]
        owner = state.owner
        state.controller = None
        if owner == nation:
            state.set_army(troops)
            if general is not None and self.s.general_in(province) is None:
                general.province = province
        else:  # an ally's land: hand it back and go home
            state.set_army({})
            if origin is not None:
                self.s.provinces[origin].add(troops)
        self._emit(
            EventKind.PROVINCE_LIBERATED,
            f"{self._name(nation)} frees {self._pname(province)}"
            + (f" for {self._name(owner)}" if owner and owner != nation else ""),
            nations=(nation, owner) if owner and owner != nation else (nation,),
            province=province,
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
        for p in self.s.provinces.values():
            if p.controller == nation:  # its occupying armies melt away
                p.controller = None
                p.set_army({})
            if p.siege_by == nation:
                p.siege_by, p.siege_years = None, 0
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
        self._drift_opinions()
        self._weary()
        for pid, p in self.s.provinces.items():  # a siege not pressed this year is lifted
            if p.siege_by and pid not in self.besieged:
                p.siege_by, p.siege_years = None, 0
        for province in self.s.provinces.values():
            settles = 2 if BuildingKind.CATHEDRAL in province.buildings else 1
            province.unrest = max(0, province.unrest - settles)
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
        for opinions in self.s.opinions.values():
            for other, value in list(opinions.items()):
                fade = max(1, round(abs(value) * rules.opinion_decay)) if value else 0
                opinions[other] = value - fade if value > 0 else value + fade
        alive = self.s.alive_nations()
        for a in alive:
            enemies = set(self.s.enemies_of(a))
            for b in alive:
                if a != b and enemies & set(self.s.enemies_of(b)):
                    self._opine(a, b, rules.opinion_shared_enemy)
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
        state.resources = state.resources + nation_income(self.s, nation)
        cap = manpower_cap(self.s, nation)
        if state.resources.manpower > cap:
            state.resources = state.resources.model_copy(update={"manpower": cap})
        self._pay_council(nation)
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
            if dominant:
                winner = max(dominant, key=lambda n: len(self.s.provinces_of(n)))
                reason = f"rules {len(self.s.provinces_of(winner))} of {total} provinces"
            elif self.turn >= self.s.max_turns:
                winner = min(alive, key=self._ranking)
                reason = f"highest score ({self.s.score(winner)} development) when time ran out"
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
            -self.s.score(nation),
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
