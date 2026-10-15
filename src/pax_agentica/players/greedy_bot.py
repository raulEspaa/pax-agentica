"""A simple but competent ruler: the opponent an AI ruler has to beat.

Every turn it:
1. answers proposals with simple self-interest (fair trades, peace when losing);
2. declares war on its weakest neighbour once there is nothing easy left to grab;
3. recruits as many regiments as it can feed, at the most promising border;
4. attacks every adjacent target it can beat with a safety margin;
5. marches idle regiments from the interior towards the border;
6. spends spare ducats on development and stability, and haggles for iron and grain.

It only reads its `NationView`, exactly like an LLM ruler would.
"""

import math
import random
from collections import deque

from pax_agentica.engine import NationView, Orders, Resources
from pax_agentica.engine.actions import (
    MAX_ACTIONS_PER_TURN,
    Action,
    AssignGeneral,
    Attack,
    BoostStability,
    Build,
    DeclareWar,
    Develop,
    HireAdvisor,
    HireGeneral,
    Move,
    ProposeAlliance,
    ProposeNonAggression,
    ProposePeace,
    ProposeTrade,
    Recruit,
    Research,
    Respond,
    Terms,
    UpgradeMonument,
)
from pax_agentica.engine.events import EventKind
from pax_agentica.engine.model import (
    AdvisorRole,
    BuildingKind,
    Good,
    ProposalKind,
    ProvinceId,
    TechBranch,
    TreatyKind,
    UnitKind,
)
from pax_agentica.engine.view import ProposalView, ProvinceView

CAPITAL_GUARD = 3

# How much the bot thinks each resource is worth, in ducats.
PRICES = Resources(ducats=1, manpower=3, iron=2, grain=1, timber=2)


def value(bundle: Resources) -> int:
    return sum(amount * getattr(PRICES, name) for name, amount in bundle.amounts().items())


class GreedyBot:
    def __init__(self, seed: int = 0, margin: float = 1.3) -> None:
        self.seed = seed
        self.margin = margin  # attack only with this much more power than the defenders

    @property
    def name(self) -> str:
        return "greedy"

    async def decide(self, view: NationView) -> Orders:
        return self.plan(view)

    def plan(self, view: NationView) -> Orders:
        rng = random.Random(f"{self.seed}:{view.me.id}:{view.turn}")  # noqa: S311
        return _Planner(view, rng, self.margin).run()


class _Planner:
    def __init__(self, view: NationView, rng: random.Random, margin: float) -> None:
        self.v = view
        self.me = view.me
        self.rng = rng
        self.margin = margin
        self.provinces = {p.id: p for p in view.provinces}
        self.mine = {p.id for p in view.provinces if p.owner == view.me.id}
        self.troops = {pid: self.provinces[pid].troops or 0 for pid in self.mine}
        self.budget = view.me.resources
        self.enemies = set(view.me.at_war_with)
        self.old_enemies = set(self.enemies)
        self.friends = {t.partner for t in view.me.treaties}  # never attacked: we keep our word
        self.allies = {t.partner for t in view.me.treaties if t.kind == TreatyKind.ALLIANCE}
        self.mobilising = {w.enemy for w in view.me.wars if w.attacks_allowed_from_turn > view.turn}
        self.suing_for_peace = {
            p.recipient for p in view.proposals_sent if p.kind == ProposalKind.PEACE
        }
        self.targeted: set[ProvinceId] = set()
        self.leaders: dict[ProvinceId, int] = {}
        self.actions: list[Action] = []

    def run(self) -> Orders:
        self._answer_proposals()
        self._maybe_declare_war()
        self._recruit()
        self._command()
        self._attack()
        self._march_to_the_border()
        self._invest()
        self._diplomacy()
        return Orders(actions=self.actions[:MAX_ACTIONS_PER_TURN])

    # ------------------------------------------------------------ geography

    def _neighbors(self, pid: ProvinceId) -> tuple[ProvinceId, ...]:
        p = self.provinces[pid]
        return p.neighbors + p.sea_neighbors

    def _border_nations(self) -> set[str]:
        owners = {self.provinces[n].owner for pid in self.mine for n in self._neighbors(pid)}
        return {o for o in owners if o is not None and o != self.me.id}

    def _reserve(self, pid: ProvinceId) -> int:
        """Regiments that stay home: a garrison on the border, a guard in the capital."""
        foreign = [
            self.provinces[n].troops or 0
            for n in self._neighbors(pid)
            if self.provinces[n].owner not in (None, self.me.id)
        ]
        border = math.ceil(max(foreign) / 2) if foreign else 0
        if foreign:
            border = max(1, border)
        return max(border, CAPITAL_GUARD if pid == self.me.capital else 0)

    def _exposed(self, pid: ProvinceId) -> bool:
        """Borders another nation, so it should keep a garrison."""
        return any(self.provinces[n].owner not in (None, self.me.id) for n in self._neighbors(pid))

    def _defense(self, origin: ProvinceId, target: ProvinceView) -> float:
        rules = self.v.rules
        bonus = rules.fort_bonus_per_level * target.fort
        if target.is_capital:
            bonus += rules.capital_bonus
        if target.id in self.provinces[origin].sea_neighbors:
            bonus += rules.sea_crossing_bonus
        return rules.defender_advantage * rules.terrain_defense[target.terrain] * (1 + bonus)

    def _needed(self, origin: ProvinceId, target: ProvinceView) -> int:
        defenders = target.troops or 0
        if defenders == 0:
            return 1
        return math.floor(defenders * self._defense(origin, target) * self.margin) + 1

    def _targets(self) -> list[tuple[float, ProvinceId, ProvinceId, int]]:
        """(value, origin, target, regiments needed) for every province we could attack."""
        found = []
        for origin in sorted(self.mine):
            for t in self._neighbors(origin):
                target = self.provinces[t]
                if target.owner is None or (
                    target.owner in self.enemies
                    and target.owner not in self.suing_for_peace | self.mobilising
                ):
                    need = self._needed(origin, target)
                    found.append((target.development / need, origin, t, need))
        found.sort(key=lambda c: (-c[0], c[1], c[2]))
        return found

    # ------------------------------------------------------------ 1. proposals

    def _losing_to(self, enemy: str) -> bool:
        lost = any(
            e.kind == EventKind.PROVINCE_CAPTURED and e.nations == (enemy, self.me.id)
            for e in self.v.last_turn_events
        )
        their = next((n for n in self.v.nations if n.id == enemy), None)
        return lost or (their is not None and their.score > self.me.score * 1.5)

    def _answer_proposals(self) -> None:
        for p in self.v.proposals_to_answer:
            accept = self._wants(p)
            if accept and p.kind == ProposalKind.TRADE:
                self.budget = self.budget - p.receive + p.give
            if accept and p.kind == ProposalKind.CALL_TO_ARMS and p.enemy:
                self.enemies.add(p.enemy)
            if accept and p.kind == ProposalKind.PEACE:
                self.enemies.discard(p.sender)
                self.old_enemies.discard(p.sender)
            counter = None if accept else self._counter(p)
            self.actions.append(Respond(proposal_id=p.id, accept=accept, counter=counter))

    def _counter(self, p: ProposalView) -> Terms | None:
        """Haggle: a beaten court offers gold for land; a trader asks for a fairer deal."""
        if p.kind == ProposalKind.PEACE and self._losing_to(p.sender):
            gold = min(self.budget.ducats // 4, 60)
            return Terms(give=Resources(ducats=gold), note="Take gold, not our land.")
        if p.kind == ProposalKind.TRADE and value(p.give) >= 0.7 * value(p.receive) > 0:
            fair = Resources(
                **{k: v * 7 // 10 for k, v in p.receive.amounts().items()}
            )  # what we would hand over
            if self.budget.covers(fair) and not fair.is_empty():
                return Terms(give=fair, receive=p.give, note="A fairer price.")
        return None

    def _cost_of_peace(self, p: ProposalView) -> int:
        """What a peace's terms take from us, in ducats, minus what they bring."""
        dev = {pid: self.provinces[pid].development for pid in p.cede + p.demand}
        years = self.v.rules.tribute_years
        cost = value(p.receive) + sum(dev[x] for x in p.demand) * 30 + p.ask_tribute * years
        cost += 60 if p.limit_army is not None else 0
        gain = value(p.give) + sum(dev[x] for x in p.cede) * 30 + p.pay_tribute * years
        return cost - gain

    def _fears(self, nation: str) -> bool:
        their = next((n for n in self.v.nations if n.id == nation), None)
        return their is not None and their.score >= self.me.score * 0.9

    def _wants(self, p: ProposalView) -> bool:
        match p.kind:
            case ProposalKind.PEACE:
                overstretched = len(self.old_enemies) >= 2
                losing = overstretched or self._losing_to(p.sender)
                cost = self._cost_of_peace(p)
                if cost > 0:  # they ask for something: only when beaten, and not everything
                    return losing and cost <= 40 * self.me.score // max(1, len(self.mine))
                return losing or cost < 0 or self.rng.random() < 0.4
            case ProposalKind.ALLIANCE:
                if len(self.allies) >= 2:
                    return False
                liked = self.me.opinions.get(p.sender, 0) >= 25
                return liked or p.sender not in self._border_nations() or self.rng.random() < 0.3
            case ProposalKind.NON_AGGRESSION:
                # Peace with the strong, the liked, or while busy elsewhere; the weak are prey.
                liked = self.me.opinions.get(p.sender, 0) >= 15
                return (
                    self._fears(p.sender) or liked or bool(self.enemies) or self.rng.random() < 0.2
                )
            case ProposalKind.TRADE:
                return value(p.give) >= value(p.receive) and self.budget.covers(p.receive)
            case ProposalKind.CALL_TO_ARMS:
                return p.enemy in self._border_nations() or self.rng.random() < 0.5

    # ------------------------------------------------------------ 2. war

    def _maybe_declare_war(self) -> None:
        if self.enemies or self.v.turn < 3:
            return
        easy = [c for c in self._targets() if c[3] <= self.troops[c[1]]]
        if easy and self.rng.random() > 0.1:
            return
        # Early on, only a clear edge starts a war; later, peace grows restless.
        best, best_ratio = None, 1.5 if self.v.turn < 15 else 1.2
        for nation in sorted(self._border_nations() - self.friends):
            ours = theirs = 0
            for pid in self.mine:
                facing = [n for n in self._neighbors(pid) if self.provinces[n].owner == nation]
                if facing:
                    ours += self.troops[pid]
                    theirs += sum(self.provinces[n].troops or 0 for n in facing)
            ratio = ours / max(1, theirs)
            if ratio > best_ratio:
                best, best_ratio = nation, ratio
        if best is not None:
            self.actions.append(DeclareWar(target=best))
            self.enemies.add(best)
            self.mobilising.add(best)

    # ------------------------------------------------------------ 3. recruit

    def _threat(self, pid: ProvinceId) -> int:
        """Visible enemy regiments next door minus our own garrison."""
        enemy = sum(
            self.provinces[n].troops or 0
            for n in self._neighbors(pid)
            if self.provinces[n].owner in self.enemies
        )
        return enemy - self.troops[pid]

    def _staging_province(self) -> ProvinceId:
        if self.enemies:
            threatened = max(sorted(self.mine), key=self._threat)
            if self._threat(threatened) > 0:
                return threatened
        targets = self._targets()
        if targets:
            return targets[0][1]
        exposed = sorted(p for p in self.mine if self._exposed(p))
        return exposed[0] if exposed else self.me.capital

    def _recruit(self) -> None:
        cost = self.v.rules.recruit_cost
        # In peace, only what the harvest can feed; at war, eat into the granaries too.
        feedable = self.me.income_per_turn.grain + self.budget.grain // (3 if self.enemies else 8)
        room = feedable - self.me.regiments
        # Keep army pay under half the income.
        payable = int(self.me.income_per_turn.ducats / 2 / self.v.rules.ducat_upkeep_per_regiment)
        room = min(room, payable - self.me.regiments)
        limits = [room]
        for have, need in (
            (self.budget.ducats, cost.ducats),
            (self.budget.manpower, cost.manpower),
            (self.budget.iron, cost.iron),
            (self.budget.grain, cost.grain),
        ):
            if need:
                limits.append(have // need)
        regiments = min(limits)
        if regiments <= 0 or not self.mine:
            return
        where = self._staging_province()
        offered = self.provinces[where].recruit_costs
        # A balanced army: a quarter archers, a fifth horse where there are stables, a tenth
        # guns in war where there is a foundry; pikemen for the rest.
        mix = {
            UnitKind.ARTILLERY: 0.1 if self.enemies else 0.0,
            UnitKind.CAVALRY: 0.2,
            UnitKind.ARCHERS: 0.25,
        }
        left = regiments
        for kind, part in [*mix.items(), (UnitKind.INFANTRY, 1.0)]:
            price = offered.get(kind, cost if kind == UnitKind.INFANTRY else None)
            if price is None:
                continue
            n = left if kind == UnitKind.INFANTRY else min(round(regiments * part), left)
            while n > 0 and not self.budget.covers(price.times(n)):
                n -= 1
            if n > 0:
                self.actions.append(Recruit(province=where, regiments=n, unit=kind))
                self.budget = self.budget - price.times(n)
                self.troops[where] += n
                left -= n

    # ------------------------------------------------------------ 4. attack

    def _attack(self) -> None:
        for _value, origin, target, need in self._targets():
            if target in self.targeted:
                continue
            spare = self.troops[origin] - self._reserve(origin)
            if spare < need:
                continue
            send = spare if (self.provinces[target].troops or 0) else min(spare, 2)
            leader = self.leaders.pop(origin, None)
            self.actions.append(
                Attack(origin=origin, target=target, regiments=send, general=leader)
            )
            self.troops[origin] -= send
            self.targeted.add(target)

    # ------------------------------------------------------------ 5. march

    def _march_to_the_border(self) -> None:
        frontier = [p for p in self.mine if any(n not in self.mine for n in self._neighbors(p))]
        distance = {p: 0 for p in frontier}
        queue = deque(sorted(frontier))
        while queue:
            current = queue.popleft()
            for n in self._neighbors(current):
                if n in self.mine and n not in distance:
                    distance[n] = distance[current] + 1
                    queue.append(n)
        for pid in sorted(self.mine):
            here = distance.get(pid)
            spare = self.troops[pid] - self._reserve(pid)
            if not here or spare <= 0:
                continue
            closer = [n for n in self._neighbors(pid) if distance.get(n, here) < here]
            if closer:
                step = min(closer)
                self.actions.append(Move(origin=pid, target=step, regiments=spare))
                self.troops[pid] -= spare

    # ------------------------------------------------------------ 6. invest

    def _invest(self) -> None:
        rules = self.v.rules
        reserve = 30 if self.enemies else 10
        stab = Resources(ducats=rules.stability_boost_ducats)
        if self.me.stability < 1 and self.budget.covers(stab + Resources(ducats=reserve)):
            self.actions.append(BoostStability())
            self.budget = self.budget - stab
        self._research(reserve)
        self._council(reserve)
        self._build(reserve)
        self._monument(reserve)
        starving = self.me.income_per_turn.grain < self.me.army_upkeep_per_turn.grain
        candidates = sorted(
            (
                p
                for p in self.mine
                if self.provinces[p].development < self.me.modifiers.max_development
            ),
            key=lambda p: (
                not (starving and self.provinces[p].good == Good.GRAIN),
                self.provinces[p].development,
                p,
            ),
        )
        for pid in candidates[:4]:
            cost = self.provinces[pid].develop_cost
            if not self.budget.covers(cost + Resources(ducats=reserve)):
                break
            self.actions.append(Develop(province=pid))
            self.budget = self.budget - cost

    def _build(self, reserve: int) -> None:
        """One building a turn, chosen by what the realm lacks most."""
        rules, me = self.v.rules, self.me

        def best(field: str) -> list[ProvinceId]:
            output = {p: getattr(self.provinces[p].output_per_turn, field) for p in self.mine}
            return sorted(self.mine, key=lambda p: (-output[p], p))

        wishes: list[tuple[BuildingKind, list[ProvinceId]]] = []
        capital = self.provinces.get(me.capital)
        if capital and any(
            self.provinces[n].owner in self.enemies for n in self._neighbors(capital.id)
        ):
            wishes += [(BuildingKind.FORT, [capital.id]), (BuildingKind.CITADEL, [capital.id])]
        if me.income_per_turn.grain < me.army_upkeep_per_turn.grain:
            wishes.append((BuildingKind.FARM_ESTATES, best("grain")))
        if self.budget.iron < rules.recruit_cost.iron * 4:
            wishes.append((BuildingKind.IRONWORKS, best("iron")))
        if self.budget.manpower < 5:
            wishes.append((BuildingKind.BARRACKS, best("manpower")))
        if self.budget.timber < 10:
            wishes.append((BuildingKind.LUMBER_MILL, best("timber")))
        richest = best("ducats")
        staging = self._staging_province()
        if self.enemies:
            wishes.append((BuildingKind.ARMORY, [staging]))
        if self.enemies:
            wishes.append((BuildingKind.CANNON_FOUNDRY, [staging]))
        wishes += [
            (BuildingKind.MARKETPLACE, richest[:2]),
            (BuildingKind.ROYAL_EXCHANGE, richest[:1]),
            (BuildingKind.BANK, richest[:2]),
            (BuildingKind.STABLES, [staging]),
            (BuildingKind.OBSERVATORY, richest[1:2]),
            (BuildingKind.UNIVERSITY, richest[:1]),
            (BuildingKind.MARKETPLACE, richest),
            (BuildingKind.MILITARY_ACADEMY, [me.capital]),
            (BuildingKind.TRAINING_GROUNDS, [staging]),
            (BuildingKind.CATHEDRAL, richest[:1]),
            (BuildingKind.BANK, richest),
        ]
        owned = {b for pid in self.mine for b in self.provinces[pid].buildings}
        cost = me.building_costs
        for kind, places in wishes:
            spec = rules.buildings[kind]
            for pid in places:
                p = self.provinces[pid]
                if (
                    kind not in p.buildings
                    and not (spec.unique and kind in owned)
                    and (spec.requires is None or spec.requires in p.buildings)
                    and len(p.buildings) < p.building_slots
                    and not p.unrest
                    and self._unlocked(spec.requires_tech)
                    and self.budget.covers(cost[kind] + Resources(ducats=reserve))
                ):
                    self.actions.append(Build(province=pid, building=kind))
                    self.budget = self.budget - cost[kind]
                    return

    def _monument(self, reserve: int) -> None:
        """Raise a monument when the treasury is comfortably full."""
        rules = self.v.rules
        for pid in sorted(self.mine):
            level = self.provinces[pid].monument
            if level is None or level >= rules.max_monument_level or self.provinces[pid].unrest:
                continue
            cost = rules.monument_cost.times(level + 1)
            if self.budget.covers(cost + Resources(ducats=reserve + 60)):
                self.actions.append(UpgradeMonument(province=pid))
                self.budget = self.budget - cost
                return

    def _unlocked(self, requirement: tuple[TechBranch, int] | None) -> bool:
        return requirement is None or self.me.technology[requirement[0]] >= requirement[1]

    def _council(self, reserve: int) -> None:
        """Fill the council's empty seats, money first, the army in war, learning in peace."""
        order = [AdvisorRole.TREASURER]
        order += (
            [AdvisorRole.MARSHAL, AdvisorRole.CHANCELLOR]
            if self.enemies
            else [AdvisorRole.CHANCELLOR, AdvisorRole.MARSHAL]
        )
        for role in order:
            if role in self.me.advisors:
                continue
            offers = sorted(
                (c for c in self.me.advisor_candidates if c.role == role),
                key=lambda c: (-c.skill, c.id),
            )
            for candidate in offers:
                cost = Resources(ducats=candidate.hire_cost + 20 * candidate.salary)
                if self.budget.covers(cost + Resources(ducats=reserve)):
                    self.actions.append(HireAdvisor(candidate=candidate.id))
                    self.budget = self.budget - Resources(ducats=candidate.hire_cost)
                    return

    def _research(self, reserve: int) -> None:
        """One technology a year when the treasury allows: war first in war, wealth in peace."""
        costs = self.me.research_costs
        order = [TechBranch.MILITARY] if self.enemies else []
        order += sorted(
            (TechBranch.ECONOMY, TechBranch.ENGINEERING, TechBranch.MILITARY),
            key=lambda b: (self.me.technology[b], b != TechBranch.ECONOMY),
        )
        for branch in order:
            cost = costs[branch]
            if cost is not None and self.budget.covers(cost + Resources(ducats=reserve)):
                self.actions.append(Research(branch=branch))
                self.budget = self.budget - cost
                return

    # ------------------------------------------------------------ 3b. generals

    def _command(self) -> None:
        """Put the best general where the next blow will fall, and hire one more if rich."""
        staging = self._staging_province()
        here = {g.province: g for g in self.me.generals}
        if staging not in here and self.me.generals:
            best = max(self.me.generals, key=lambda g: (g.skill, -g.id))
            if best.province != staging:
                self.actions.append(AssignGeneral(general=best.id, province=staging))
                here.pop(best.province, None)
                here[staging] = best
        rules = self.v.rules
        if (
            len(self.me.generals) < 2
            and staging not in here
            and self.budget.covers(rules.general_cost + Resources(ducats=100))
        ):
            self.actions.append(HireGeneral(province=staging))
            self.budget = self.budget - rules.general_cost
        self.leaders = {pid: g.id for pid, g in here.items()}

    # ------------------------------------------------------------ 7. diplomacy

    def _peace_terms(self, enemy: str) -> ProposePeace:
        """Winning: ask for their best province on our border and some gold. Losing: pay."""
        if self._losing_to(enemy):
            gold = min(self.budget.ducats // 4, 50)
            return ProposePeace(
                target=enemy, give=Resources(ducats=gold), note="Let this end. We will pay."
            )
        their = next((n for n in self.v.nations if n.id == enemy), None)
        if their is not None and their.score * 1.3 < self.me.score:
            border = sorted(
                (
                    self.provinces[n]
                    for pid in self.mine
                    for n in self._neighbors(pid)
                    if self.provinces[n].owner == enemy and not self.provinces[n].is_capital
                ),
                key=lambda p: (-p.development, p.id),
            )
            if border:
                return ProposePeace(
                    target=enemy,
                    demand=[border[0].id],
                    receive=Resources(ducats=30),
                    note=f"Give us {border[0].name} and this war ends.",
                )
        return ProposePeace(target=enemy)

    def _war_value(self, enemy: str) -> float:
        return sum(v for v, _o, t, _n in self._targets() if self.provinces[t].owner == enemy)

    def _diplomacy(self) -> None:
        pending = {(p.kind, p.recipient) for p in self.v.proposals_sent}
        targets = {self.provinces[t].owner for _v, _o, t, _n in self._targets()}
        # Fighting on several fronts: keep only the most profitable war.
        keep = max(sorted(self.old_enemies), key=self._war_value) if self.old_enemies else None
        for enemy in sorted(self.old_enemies):
            stalled = enemy not in targets
            overstretched = len(self.old_enemies) >= 2 and enemy != keep
            if (ProposalKind.PEACE, enemy) not in pending and (
                overstretched or self._losing_to(enemy) or (stalled and self.rng.random() < 0.3)
            ):
                self.actions.append(self._peace_terms(enemy))

        others = sorted(n.id for n in self.v.nations if n.alive and n.id not in self.enemies)
        if not others:
            return
        cost = self.v.rules.recruit_cost
        partner = self.rng.choice(others)
        offer: tuple[Resources, Resources] | None = None
        if self.budget.iron < cost.iron * 3 and self.budget.ducats >= 40:
            offer = Resources(ducats=20), Resources(iron=8)
        elif self.me.income_per_turn.grain < self.me.army_upkeep_per_turn.grain and (
            self.budget.ducats >= 40
        ):
            offer = Resources(ducats=20), Resources(grain=15)
        elif self.budget.timber < 8 and self.budget.ducats >= 40:
            offer = Resources(ducats=20), Resources(timber=8)
        if offer and (ProposalKind.TRADE, partner) not in pending and self.rng.random() < 0.4:
            give, receive = offer
            self.actions.append(ProposeTrade(target=partner, give=give, receive=receive))

        borders = self._border_nations()
        friendly = self.rng.choice(others)
        if self.rng.random() < 0.08 and friendly not in self.friends:
            if friendly in borders:
                if (ProposalKind.NON_AGGRESSION, friendly) not in pending:
                    self.actions.append(ProposeNonAggression(target=friendly))
            elif (ProposalKind.ALLIANCE, friendly) not in pending and len(self.allies) < 2:
                self.actions.append(ProposeAlliance(target=friendly))
