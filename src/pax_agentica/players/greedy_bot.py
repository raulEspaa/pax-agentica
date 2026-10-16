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
    Buy,
    ChooseOption,
    DeclareWar,
    Develop,
    HireAdvisor,
    HireGeneral,
    HireMercenaries,
    Improve,
    Move,
    Patronize,
    Proclaim,
    ProposeAlliance,
    ProposeNonAggression,
    ProposePeace,
    ProposeTrade,
    Recruit,
    Research,
    Respond,
    Sell,
    SetStance,
    SetTaxes,
    Terms,
    UpgradeMonument,
)
from pax_agentica.engine.fortune import EVENTS_BY_ID, Option
from pax_agentica.engine.model import (
    AdvisorRole,
    BuildingKind,
    Good,
    Personality,
    ProposalKind,
    ProvinceId,
    Stance,
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
        me = view.me.id
        # Where our regiments stand (our land and what we occupy), and what we can build on.
        self.mine = {p.id for p in view.provinces if (p.controller or p.owner) == me}
        self.owned = {p.id for p in view.provinces if p.owner == me and not p.controller}
        self.troops = {pid: self.provinces[pid].troops or 0 for pid in self.mine}
        self.score_of = {w.enemy: w.war_score for w in view.me.wars}
        self.budget = view.me.resources
        self.enemies = set(view.me.at_war_with)
        self.old_enemies = set(self.enemies)
        self.friends = {t.partner for t in view.me.treaties}  # never attacked: we keep our word
        self.ambitions = {  # provinces our open missions ask us to hold
            pid
            for m in view.me.missions
            if m.status == "open"
            for g in m.goals
            if g.goal.kind == "own"
            for pid in g.goal.provinces
        }
        self.allies = {t.partner for t in view.me.treaties if t.kind == TreatyKind.ALLIANCE}
        self.mobilising = {w.enemy for w in view.me.wars if w.attacks_allowed_from_turn > view.turn}
        self.suing_for_peace = {
            p.recipient for p in view.proposals_sent if p.kind == ProposalKind.PEACE
        }
        self.targeted: set[ProvinceId] = set()
        self.declared: str | None = None
        self.decided: list[str] = []
        self.leaders: dict[ProvinceId, int] = {}
        self.actions: list[Action] = []

    def run(self) -> Orders:
        self._answer_proposals()
        self._decide_events()
        self._trade_market()
        self._maybe_declare_war()
        self._recruit()
        self._command()
        self._attack()
        self._march_to_the_border()
        self._invest()
        self._diplomacy()
        self._stances()
        return Orders(
            actions=self.actions[:MAX_ACTIONS_PER_TURN],
            thoughts=self._thoughts(),
            counsel=self._counsel(),
        )

    # ------------------------------------------------------------ geography

    def _neighbors(self, pid: ProvinceId) -> tuple[ProvinceId, ...]:
        p = self.provinces[pid]
        return p.neighbors + p.sea_neighbors

    def _border_nations(self) -> set[str]:
        owners = {
            self.provinces[n].controller or self.provinces[n].owner
            for pid in self.mine
            for n in self._neighbors(pid)
        }
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
                holder = target.controller or target.owner
                if holder == self.me.id:
                    continue
                ours = target.owner == self.me.id  # occupied by the enemy: win it back first
                if holder is None or (
                    holder in self.enemies and holder not in self.suing_for_peace | self.mobilising
                ):
                    need = self._needed(origin, target)
                    worth = target.development * (2 if ours else 1)
                    if t in self.ambitions:  # a province our missions ask for
                        worth *= 2
                    found.append((worth / need, origin, t, need))
        found.sort(key=lambda c: (-c[0], c[1], c[2]))
        return found

    # ------------------------------------------------------------ 1. proposals

    def _losing_to(self, enemy: str) -> bool:
        """Behind in the war score, worn out, or simply outmatched."""
        if self.score_of.get(enemy, 0) <= -15 or self.me.war_exhaustion >= 10:
            return True
        their = next((n for n in self.v.nations if n.id == enemy), None)
        return their is not None and their.score > self.me.score * 1.5

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
        """Haggle: a winner names its price, a beaten court offers gold for land, a trader asks
        for a fairer deal."""
        if p.kind == ProposalKind.PEACE and self.score_of.get(p.sender, 0) >= 10:
            ours = self._peace_terms(p.sender)
            return Terms(demand=ours.demand, receive=ours.receive, note=ours.note)
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

    def _offered_worth(self, p: ProposalView) -> int:
        """What a peace offers us, in war score: their land and gold, as the engine prices it."""
        their = next((n for n in self.v.nations if n.id == p.sender), None)
        total = max(1, their.score if their else 1)
        land = sum(max(5, round(100 * self.provinces[x].development / total)) for x in p.cede)
        income = max(10, self.me.income_per_turn.ducats)  # a rough stand-in for theirs
        gold = round(10 * value(p.give) / income)
        tribute = round(5 * p.pay_tribute * self.v.rules.tribute_years / income)
        return land + gold + tribute

    def _war_score_cost(self, p: ProposalView) -> int:
        """What a peace demands of us, in war score, as the engine prices it."""
        mine = max(1, self.me.score)
        provinces = sum(max(5, round(100 * self.provinces[x].development / mine)) for x in p.demand)
        income = max(10, self.me.income_per_turn.ducats)
        lump = round(10 * value(p.receive) / income) if not p.receive.is_empty() else 0
        tribute = round(5 * p.ask_tribute * self.v.rules.tribute_years / income)
        limit = self.v.rules.peace_cost_army_limit if p.limit_army is not None else 0
        return provinces + lump + tribute + limit

    def _trade_market(self) -> None:
        """Sell what piles up, buy what the realm lacks for its buildings and its levies."""
        me, market = self.me, self.v.market
        income, upkeep, inputs = me.income_per_turn, me.army_upkeep_per_turn, me.inputs_per_turn
        keep = {
            "grain": upkeep.grain * 3 + 20,
            "iron": 40,
            "timber": 40 + inputs.timber * 3,
            "goods": 10 + inputs.goods * 3,
        }
        for res, floor in keep.items():
            surplus = getattr(self.budget, res) - floor
            if surplus >= 10:
                amount = min(surplus, 200)
                self.actions.append(Sell(resource=res, amount=amount))  # type: ignore[arg-type]
                self.budget = (
                    self.budget
                    - Resources(**{res: amount})
                    + Resources(ducats=int(amount * market[res].sell))
                )
        # what this year's works will want: developing the three humblest provinces and
        # deepening the best workings; a rich realm buys the timber and goods it lacks
        plans = Resources()
        for pid in sorted(self.owned, key=lambda x: (self.provinces[x].development, x))[:3]:
            p = self.provinces[pid]
            if p.development < me.modifiers.max_development:
                plans = plans + p.develop_cost
        costs = [c for x in self.owned if (c := self.provinces[x].improve_cost) is not None]
        best = min(costs, key=lambda c: c.ducats, default=None)
        if best is not None:
            plans = plans + best
        wants = {
            "goods": max(inputs.goods - income.goods + 2, plans.goods) - self.budget.goods,
            "iron": self.v.rules.recruit_cost.iron * 4 - self.budget.iron,
            "grain": upkeep.grain + inputs.grain - income.grain - self.budget.grain // 2,
            "timber": inputs.timber + plans.timber - self.budget.timber,
        }
        for res, need in wants.items():
            if need <= 0:
                continue
            amount = min(need, 200)
            cost = int(amount * market[res].buy) + 1
            if self.budget.ducats >= cost + plans.ducats + 40:
                self.actions.append(Buy(resource=res, amount=amount))  # type: ignore[arg-type]
                self.budget = self.budget - Resources(ducats=cost) + Resources(**{res: amount})

    def _decide_events(self) -> None:
        """Weigh each answer to the crown's pending events by what it gives and takes."""
        for pending in self.me.pending_events:
            spec = EVENTS_BY_ID[pending.event]
            best = max(
                range(len(spec.options)), key=lambda k: (self._option_worth(spec.options[k]), -k)
            )
            self.actions.append(ChooseOption(event_id=pending.id, option=best))
            self.decided.append(f"{spec.title}: {spec.options[best].label.lower()}")

    def _option_worth(self, o: Option) -> float:
        if -o.ducats > self.budget.ducats:
            return -1e9  # cannot pay
        total: float = o.ducats + o.grain + 2 * (o.iron + o.timber) + 3 * o.manpower
        total += o.stability * (60 if self.me.stability <= 0 else 25) + 4 * o.prestige
        total += 45 * o.development - 15 * o.unrest + 8 * o.regiments
        total += 2 * o.opinion + 30 * o.general_skill
        if o.faith:
            total -= 40  # a bot keeps the faith of its fathers
        if o.loan:
            yearly, years = o.loan
            total -= 0.9 * yearly * years
        return total

    def _fears(self, nation: str) -> bool:
        their = next((n for n in self.v.nations if n.id == nation), None)
        return their is not None and their.score >= self.me.score * 0.9

    def _wants(self, p: ProposalView) -> bool:
        match p.kind:
            case ProposalKind.PEACE:
                overstretched = len(self.old_enemies) >= 2
                losing = overstretched or self._losing_to(p.sender)
                weary = self.me.war_exhaustion >= 6
                earned = -self.score_of.get(p.sender, 0)  # their war score against us
                asked = self._war_score_cost(p)
                if asked > 0:  # they ask for something: grant what they have won, no more
                    return asked <= max(0, earned) + 5 or (weary and asked <= earned + 20)
                won = self.score_of.get(p.sender, 0)
                if won >= 10:  # we are winning: a peace must pay for what we hold
                    return self._offered_worth(p) >= 0.6 * won or self.me.war_exhaustion >= 12
                return losing or weary or self._cost_of_peace(p) < 0 or self.rng.random() < 0.4
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
            self.declared = best
            name = self._nation_name(best)
            self.actions.append(
                Proclaim(
                    text=self.rng.choice(
                        [
                            f"{name} has wronged us long enough. {self.me.name} takes up arms.",
                            f"Let all Europe know: {self.me.name} marches against {name}.",
                            f"Our patience with {name} is spent. God defend the right.",
                        ]
                    )
                )
            )

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
        if not self.mine:  # every province occupied: nowhere to stand but the old capital
            return self.me.capital
        if self.enemies:
            threatened = max(sorted(self.mine), key=self._threat)
            if self._threat(threatened) > 0:
                return threatened
        targets = self._targets()
        if targets:
            return targets[0][1]
        exposed = sorted(p for p in self.mine if self._exposed(p))
        return exposed[0] if exposed else self.me.capital

    def _levy_province(self) -> ProvinceId | None:
        """Where to raise regiments: our own free land nearest the front."""
        staging = self._staging_province()
        if staging in self.owned:
            return staging
        near = [p for p in self.owned if staging in self._neighbors(p)]
        return min(near) if near else (min(self.owned) if self.owned else None)

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
        where = self._levy_province()
        if where is not None and self.enemies and regiments < 4:
            self._mercenaries(where, room)
        if regiments <= 0 or where is None:
            return
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

    def _mercenaries(self, where: ProvinceId, room: int) -> None:
        """At war and short of men or iron, a full treasury hires Landsknechte."""
        rules = self.v.rules
        spare = self.budget.ducats - 120
        n = min(rules.mercenary_limit, spare // rules.mercenary_cost, max(0, room))
        if n > 0:
            self.actions.append(HireMercenaries(province=where, regiments=n))
            self.budget = self.budget - Resources(ducats=n * rules.mercenary_cost)
            self.troops[where] += n

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
        self._taxes()
        self._research(reserve)
        self._council(reserve)
        self._build(reserve)
        self._improve(reserve)
        self._monument(reserve)
        self._patronize(reserve)
        starving = self.me.income_per_turn.grain < self.me.army_upkeep_per_turn.grain
        candidates = sorted(
            (
                p
                for p in self.owned
                if self.provinces[p].development < self.me.modifiers.max_development
            ),
            key=lambda p: (
                not (starving and self.provinces[p].good in (Good.GRAIN, Good.FISH)),
                self.provinces[p].development,
                p,
            ),
        )
        for pid in candidates[:8]:
            cost = self.provinces[pid].develop_cost
            if not self._afford(cost, reserve):
                break
            self.actions.append(Develop(province=pid))
            self.budget = self.budget - cost

    def _afford(self, cost: Resources, reserve: int) -> bool:
        """Whether the budget covers `cost`, buying at the market whatever traded resource is
        short when the ducats stretch that far (trades are settled before works)."""
        market = self.v.market
        short = {
            res: getattr(cost, res) - getattr(self.budget, res)
            for res in market
            if getattr(cost, res) > getattr(self.budget, res)
        }
        price = sum(int(n * market[res].buy) + 1 for res, n in short.items())
        if any(getattr(cost, r) > getattr(self.budget, r) for r in ("manpower",)):
            return False
        if self.budget.ducats < cost.ducats + price + reserve:
            return False
        for res, n in short.items():
            self.actions.append(Buy(resource=res, amount=n))  # type: ignore[arg-type]
            self.budget = (
                self.budget - Resources(ducats=int(n * market[res].buy) + 1) + Resources(**{res: n})
            )
        return True

    def _build(self, reserve: int) -> None:
        """One building a turn, chosen by what the realm lacks most."""
        rules, me = self.v.rules, self.me

        def best(field: str) -> list[ProvinceId]:
            output = {p: getattr(self.provinces[p].output_per_turn, field) for p in self.owned}
            return sorted(self.owned, key=lambda p: (-output[p], p))

        wishes: list[tuple[BuildingKind, list[ProvinceId]]] = []
        capital = self.provinces.get(me.capital) if me.capital in self.owned else None
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
        staging = self._levy_province() or me.capital
        goods_short = me.inputs_per_turn.goods + 1 > me.income_per_turn.goods
        if goods_short:
            by_development = sorted(self.owned, key=lambda p: (-self.provinces[p].development, p))
            wishes.append((BuildingKind.WORKSHOP, by_development))
        if self.enemies:
            wishes.append((BuildingKind.ARMORY, [staging]))
        if self.enemies:
            wishes.append((BuildingKind.CANNON_FOUNDRY, [staging]))
            wishes.append((BuildingKind.ARMS_MANUFACTORY, [me.capital]))
            wishes.append((BuildingKind.POWDER_MILL, [me.capital]))
        wishes += [
            *([] if goods_short else [(BuildingKind.MARKETPLACE, richest[:2])]),
            (BuildingKind.ROYAL_EXCHANGE, richest[:1]),
            (BuildingKind.BANK, richest[:2]),
            (BuildingKind.STABLES, [staging]),
            (BuildingKind.OBSERVATORY, richest[1:2]),
            (BuildingKind.UNIVERSITY, richest[:1]),
            *([] if goods_short else [(BuildingKind.MARKETPLACE, richest)]),
            (BuildingKind.MILITARY_ACADEMY, [me.capital]),
            (BuildingKind.TRAINING_GROUNDS, [staging]),
            (BuildingKind.CATHEDRAL, richest[:1]),
            (BuildingKind.BANK, richest),
        ]
        owned = {b for pid in self.owned for b in self.provinces[pid].buildings}
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

    def _improve(self, reserve: int) -> None:
        """Deepen the mine (or vineyard, or fishery) of the province whose good pays best."""
        rules = self.v.rules
        worth = {"ducats": 1, "goods": 3, "iron": 2, "timber": 1.5, "grain": 1, "manpower": 3}

        def value_of(pid: ProvinceId) -> float:
            p = self.provinces[pid]
            rates = rules.good_yields.get(p.good, {})
            return sum(worth[k] * r for k, r in rates.items()) * p.development

        for pid in sorted(self.owned, key=lambda x: (-value_of(x), x)):
            cost = self.provinces[pid].improve_cost
            if cost is not None and self._afford(cost, reserve + 30):
                self.actions.append(Improve(province=pid))
                self.budget = self.budget - cost
                return

    def _taxes(self) -> None:
        """Squeeze the land in war while the realm is steady; ease off when it wobbles."""
        me = self.me
        level = 1 if self.enemies and me.stability >= 1 else -1 if me.stability < 0 else 0
        if level != me.tax:
            self.actions.append(SetTaxes(level=level))

    def _patronize(self, reserve: int) -> None:
        """A treasury with nothing better to buy pays for painters and feasts."""
        cost = self.me.patronage_cost
        if self.budget.ducats >= cost + reserve + 150 + 2 * self.me.income_per_turn.ducats:
            self.actions.append(Patronize())
            self.budget = self.budget - Resources(ducats=cost)

    def _monument(self, reserve: int) -> None:
        """Raise a monument when the treasury is comfortably full."""
        rules = self.v.rules
        for pid in sorted(self.owned):
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
        score = self.score_of.get(enemy, 0)
        their = next((n for n in self.v.nations if n.id == enemy), None)
        if their is None or score < 10:
            return ProposePeace(target=enemy)
        # Ask for what we hold of theirs, as far as the war score covers it.
        held = sorted(
            (p for p in self.v.provinces if p.owner == enemy and p.controller == self.me.id),
            key=lambda p: (-p.development, p.id),
        )
        demand, spent = [], 0
        for p in held:
            cost = max(5, round(100 * p.development / max(1, their.score)))
            if p.is_capital or spent + cost > score:
                continue
            demand.append(p)
            spent += cost
        if demand:
            names = ", ".join(p.name for p in demand)
            return ProposePeace(
                target=enemy,
                demand=[p.id for p in demand],
                note=f"Our soldiers stand in {names}. Sign them over and the war is done.",
            )
        return ProposePeace(
            target=enemy,
            receive=Resources(ducats=min(score, 60)),
            note="Pay for the trouble and go in peace.",
        )

    def _nation_name(self, nid: str) -> str:
        return next((n.name for n in self.v.nations if n.id == nid), nid)

    # ------------------------------------------------------------ 8. voices

    def _stances(self) -> None:
        """Name the enemy we fight (or most fear) our rival, and our allies our friends."""
        mine = self.me.stances
        rival = sorted(self.enemies)[0] if self.enemies else None
        rivals = sum(1 for v in mine.values() if v == Stance.RIVAL)
        if rival and mine.get(rival) != Stance.RIVAL and rivals < self.v.rules.max_rivals:
            self.actions.append(SetStance(target=rival, stance=Stance.RIVAL))
        friends = sum(1 for v in mine.values() if v == Stance.FRIEND)
        for ally in sorted(self.allies):
            if mine.get(ally) != Stance.FRIEND and friends < self.v.rules.max_friends:
                self.actions.append(SetStance(target=ally, stance=Stance.FRIEND))
                friends += 1

    def _thoughts(self) -> str:
        """What this ruler would say to themself about the year: the reasons behind the orders."""
        me, parts = self.me, []
        if self.declared:
            parts.append(f"We outnumber {self._nation_name(self.declared)} on the border: war.")
        if self.enemies:
            parts.append(
                "At war with " + ", ".join(self._nation_name(e) for e in sorted(self.enemies)) + "."
            )
        else:
            parts.append("At peace.")
        recruits = sum(a.regiments for a in self.actions if isinstance(a, Recruit))
        attacks = [a for a in self.actions if isinstance(a, Attack)]
        if recruits:
            parts.append(f"Raise {recruits} regiments.")
        if attacks:
            places = ", ".join(self.provinces[a.target].name for a in attacks)
            parts.append(f"Strike at {places}.")
        works = [a for a in self.actions if isinstance(a, Build | Research | UpgradeMonument)]
        if works:
            parts.append(f"Invest in {len(works)} works and studies.")
        for choice in self.decided:
            parts.append(f"{choice}.")
        hated = min(me.opinions.items(), key=lambda kv: kv[1], default=None)
        if hated and hated[1] < -20:
            parts.append(f"{self._nation_name(hated[0])} hates us ({hated[1]}).")
        return " ".join(parts)

    def _counsel(self) -> dict[AdvisorRole, str]:
        """Each seated advisor speaks in their own temper."""
        me, out = self.me, {}
        net = me.income_per_turn.ducats - me.army_upkeep_per_turn.ducats
        for role, adviser in me.advisors.items():
            temper = adviser.personality
            if role == AdvisorRole.TREASURER:
                line = (
                    f"We take in {me.income_per_turn.ducats} ducats and spend "
                    f"{me.army_upkeep_per_turn.ducats} on the army."
                )
                line += (
                    " Spend nothing we need not."
                    if temper == Personality.FRUGAL or net < 5
                    else " Build: money makes money."
                )
            elif role == AdvisorRole.MARSHAL:
                threat = max(sorted(self.mine), key=self._threat, default=None)
                line = f"We have {me.regiments} regiments."
                if temper == Personality.HAWK:
                    line += " Strike first, Majesty: the weak neighbour will not stay weak."
                elif threat and self._threat(threat) > 0:
                    line += f" {self.provinces[threat].name} is outnumbered; reinforce it."
                else:
                    line += " The borders hold."
            else:
                friendly = max(me.opinions.items(), key=lambda kv: kv[1], default=None)
                line = (
                    f"{self._nation_name(friendly[0])} looks on us kindly; court them."
                    if friendly and friendly[1] > 10
                    else "No court loves us; a gift would open doors."
                )
                if temper == Personality.DOVE and self.enemies:
                    line += " And make peace while it is cheap."
                if temper == Personality.SCHEMER:
                    line += " Let our rivals bleed each other first."
            out[role] = line[:600]
        return out

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
            pressing = self.score_of.get(enemy, 0) >= 25 or self.me.war_exhaustion >= 8
            if (ProposalKind.PEACE, enemy) not in pending and (
                overstretched
                or pressing
                or self._losing_to(enemy)
                or (stalled and self.rng.random() < 0.3)
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
