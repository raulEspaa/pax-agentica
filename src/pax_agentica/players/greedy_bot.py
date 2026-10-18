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
from typing import ClassVar

from pax_agentica.engine import NationView, Orders, Resources
from pax_agentica.engine.actions import (
    MAX_ACTIONS_PER_TURN,
    Action,
    AssignGeneral,
    Attack,
    BoostStability,
    Build,
    BuildColonialFort,
    BuildShips,
    Buy,
    ChooseAgenda,
    ChooseOption,
    ConquerNatives,
    Convert,
    DeclareWar,
    Develop,
    EducateHeir,
    FoundViceroyalty,
    HireAdvisor,
    HireGeneral,
    HireMercenaries,
    Improve,
    Move,
    Patronize,
    PressClaim,
    Proclaim,
    ProposeAlliance,
    ProposeCoalition,
    ProposeMarriage,
    ProposeNonAggression,
    ProposePeace,
    ProposeTrade,
    Recruit,
    Research,
    Respond,
    RoyalAction,
    SailFleet,
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
    ShipTroops,
    TakeDecision,
    Terms,
    UpgradeBuilding,
    UpgradeMonument,
)
from pax_agentica.engine.fortune import EVENTS_BY_ID, Option
from pax_agentica.engine.mechanics import tactic_factor
from pax_agentica.engine.model import (
    AdvisorRole,
    BuildingKind,
    ColonyKind,
    Focus,
    Good,
    Personality,
    PolicyAxis,
    Posture,
    ProposalKind,
    ProvinceId,
    RoyalAct,
    Ship,
    Stance,
    Tactic,
    TechBranch,
    TechLevel,
    TechOption,
    TreatyKind,
    UnitKind,
    Water,
)
from pax_agentica.engine.view import ProposalView, ProvinceView, RegionView
from pax_agentica.tools import best_tactic, landing, sea_command

CAPITAL_GUARD = 3
type Army = dict[UnitKind, int]

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
        self.seas = {z.id: z for z in view.seas}
        self.landings: dict[tuple[ProvinceId, ProvinceId], int] = {}  # what ships carry
        self.shipped = 0  # regiments carried overseas this year
        self.authority = view.me.authority  # left to spend this year
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
        self._sea_battles()
        self._seize_colonies()
        self._attack()
        self._march_to_the_border()
        self._postures()
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
        if sea_command(self.v, origin, target.id) == "contested":
            bonus += rules.sea_crossing_bonus
        elif (origin, target.id) in self.landings:  # off the boats, onto a defended beach
            bonus += rules.sea_crossing_bonus + rules.landing_bonus - self.me.modifiers.landing
        return rules.defender_advantage * rules.terrain_defense[target.terrain] * (1 + bonus)

    def _needed(self, origin: ProvinceId, target: ProvinceView) -> int:
        defenders = target.troops or 0
        if defenders == 0:  # behind walls, enough men to close the ring
            return max(1, self.v.rules.siege_ring_per_wall * target.fort)
        return math.floor(defenders * self._defense(origin, target) * self.margin) + 1

    def _relief_needed(self, target: ProvinceView) -> int:
        rules = self.v.rules
        lines = target.besiegers or 0
        ground = rules.defender_advantage * rules.terrain_defense[target.terrain]
        return math.floor(lines * ground * self.margin) + 1

    def _targets(self) -> list[tuple[float, ProvinceId, ProvinceId, int]]:
        """(value, origin, target, regiments needed) for every province we could attack."""
        found = []
        for origin in sorted(self.mine):
            for t in self._neighbors(origin):
                target = self.provinces[t]
                holder = target.controller or target.owner
                if target.siege_by == self.me.id:
                    continue  # our lines are already there
                if target.siege_by is not None:
                    if holder == self.me.id and target.siege_by in self.enemies:
                        need = self._relief_needed(target)  # break the enemy's siege
                        found.append((target.development * 3 / need, origin, t, need))
                    continue
                if holder == self.me.id:
                    continue
                ours = target.owner == self.me.id  # occupied by the enemy: win it back first
                if sea_command(self.v, origin, t) == "closed":
                    continue  # their fleet bars the strait
                if holder is None or (
                    holder in self.enemies and holder not in self.suing_for_peace | self.mobilising
                ):
                    need = self._needed(origin, target)
                    worth = target.development * (2 if ours else 1)
                    if t in self.ambitions:  # a province our missions ask for
                        worth *= 2
                    found.append((worth / need, origin, t, need))
        found += self._landing_targets()
        found.sort(key=lambda c: (-c[0], c[1], c[2]))
        return found

    def _landing_targets(self) -> list[tuple[float, ProvinceId, ProvinceId, int]]:
        """At war, the enemy's shores our fleets can carry an army to: worth a little less
        than a march (the beach is defended harder), and only if the ships carry enough."""
        found: list[tuple[float, ProvinceId, ProvinceId, int]] = []
        if not self.enemies:
            return found
        for origin in sorted(self.mine):
            here = self.provinces[origin]
            near = set(self._neighbors(origin)) | {origin}
            for sea in here.seas:
                for t in self.seas[sea].coasts:
                    target = self.provinces[t]
                    holder = target.controller or target.owner
                    if t in near or holder not in self.enemies or target.siege_by is not None:
                        continue
                    if holder in self.suing_for_peace | self.mobilising:
                        continue
                    room = landing(self.v, origin, t)
                    if not room:
                        continue
                    self.landings[(origin, t)] = room
                    need = self._needed(origin, target)
                    if need > room:
                        del self.landings[(origin, t)]
                        continue
                    worth = target.development * (2 if target.owner == self.me.id else 1) * 0.8
                    found.append((worth / need, origin, t, need))
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
            note = "" if accept or counter else self._why_not(p)
            self.actions.append(
                Respond(proposal_id=p.id, accept=accept, counter=counter, note=note)
            )

    def _infidel(self, nation: str) -> bool:
        them = next((n for n in self.v.nations if n.id == nation), None)
        return them is not None and them.faith != self.me.faith

    def _why_not(self, p: ProposalView) -> str:
        """A refusal in a sentence, so a human (or an agent) across the table knows why."""
        them = self._nation_name(p.sender)
        opinion = self.me.opinions.get(p.sender, 0)
        wrongs = [g for g in self.me.grudges if g.against == p.sender]
        bound = (ProposalKind.ALLIANCE, ProposalKind.MARRIAGE, ProposalKind.NON_AGGRESSION)
        if p.kind in bound and wrongs and self._grudge(p.sender) >= self.v.rules.grudge_refuses:
            worst = max(wrongs, key=lambda g: g.weight)
            return (
                f"We have not forgotten that you {worst.reason.replace(' it', ' us')} in "
                f"{worst.since_year}. Ask again when that is forgotten, in {worst.until_year}."
            )
        match p.kind:
            case ProposalKind.ALLIANCE | ProposalKind.MARRIAGE if self._infidel(p.sender):
                return "Our faiths are not the same, and our court will not bind itself to yours."
            case ProposalKind.ALLIANCE if len(self.allies) >= 2:
                return "Our court is bound to enough allies already."
            case ProposalKind.ALLIANCE | ProposalKind.MARRIAGE if opinion < 0:
                return f"{them} has given us little reason to trust it. Show us goodwill first."
            case ProposalKind.TRADE:
                return "The terms do not suit us. Offer more, or ask for less."
            case ProposalKind.PEACE:
                asked = self._war_score_cost(p)
                earned = max(0, -self.score_of.get(p.sender, 0))
                if asked > 0:
                    return (
                        f"You ask for terms worth {asked} war score, and you have won only "
                        f"{earned}. Win more, or ask for less."
                    )
                ahead = self.score_of.get(p.sender, 0)
                return (
                    f"The war stands {ahead:+d} in our favour and is not yet three years old. "
                    "Offer something for peace, or ask again next year."
                )
            case ProposalKind.COALITION:
                return "We do not fear that court enough to bind ourselves against it."
        return "We decline, for now."

    def _reply_to_letters(self) -> None:
        """Answer the letters of last year in a sentence that reflects what the court feels."""
        for e in self.v.last_turn_events:
            sender = e.data.get("sender")
            if e.kind.value != "message" or not isinstance(sender, str) or sender == self.me.id:
                continue
            if "proposal_id" in e.data or self.rng.random() > 0.8:
                continue
            opinion = self.me.opinions.get(sender, 0)
            if sender in self.enemies:
                text = "Words will not end this war. Send terms, or send armies."
            elif opinion >= 30:
                text = "Our court holds yours in high regard. Write to us of anything you need."
            elif opinion >= 0:
                text = "Your letter has been read in council. We shall weigh it."
            else:
                text = "Your words are noted. Our memory is long."
            self.actions.append(SendMessage(target=sender, text=text))

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

    def _war_years(self, enemy: str) -> int:
        war = next((w for w in self.me.wars if w.enemy == enemy), None)
        return self.v.turn - war.since_turn if war else 0

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
        provinces = sum(
            share if self.provinces[x].controller else max(5, share)
            for x in p.demand
            for share in [round(100 * self.provinces[x].development / mine)]
        )
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
            best = self._great_choice(spec.id)
            if best is None:
                best = max(
                    range(len(spec.options)),
                    key=lambda k: (self._option_worth(spec.options[k]), -k),
                )
            self.actions.append(ChooseOption(event_id=pending.id, option=best))
            self.decided.append(f"{spec.title}: {spec.options[best].label.lower()}")

    def _great_choice(self, event: str) -> int | None:
        """The great events of the age, weighed as a crown would: land is land, a league is
        worth its galleys when the treasury can pay, and Vienna is worth a war when the
        janissaries outnumber the defenders."""
        if event == "burgundy":
            return 0
        if event == "holy_league":
            return 0 if self.budget.ducats >= 80 else 1
        if event == "vienna":
            ours = sum(self.troops.values())
            austria = next((n for n in self.v.nations if n.id == "austria"), None)
            theirs = austria.provinces * 4 if austria else 99  # a guess: their armies are hidden
            return 0 if ours > theirs else 1
        if event == "cloth_of_gold":
            return 0 if self.budget.ducats >= 120 else 1
        return None

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
        if o.flag == "quarantine":  # three years of plague: the towns it may save, at 45 each
            towns = sum(1 for p in self.owned if self.provinces[p].development >= 2)
            total += 45 * 3 * (0.18 - 0.06) * towns - 0.15 * 3 * self.me.income_per_turn.ducats
        return total

    def _fears(self, nation: str) -> bool:
        their = next((n for n in self.v.nations if n.id == nation), None)
        return their is not None and their.score >= self.me.score * 0.9

    def _grudge(self, nation: str) -> int:
        """How heavily this court holds wrongs against `nation`."""
        return sum(g.weight for g in self.me.grudges if g.against == nation)

    def _wants(self, p: ProposalView) -> bool:
        bound = (ProposalKind.ALLIANCE, ProposalKind.MARRIAGE, ProposalKind.NON_AGGRESSION)
        if p.kind in bound and self._grudge(p.sender) >= self.v.rules.grudge_refuses:
            return False  # not with a court that wronged us, not yet
        if p.kind == ProposalKind.COALITION and p.enemy and self._grudge(p.enemy):
            return True  # a league against the court that wronged us: gladly
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
                # no dice: a court even or behind takes peace; a little ahead, once the war
                # has stood three years without deciding anything
                stalemate = won <= 0 or self._war_years(p.sender) >= 3
                return losing or weary or self._cost_of_peace(p) < 0 or stalemate
            case ProposalKind.ALLIANCE | ProposalKind.MARRIAGE if self._infidel(p.sender):
                return (
                    self.me.opinions.get(p.sender, 0) >= 40
                )  # only a true friend of another faith
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
            case ProposalKind.MARRIAGE:
                return self.me.opinions.get(p.sender, 0) >= -10 and self.rng.random() < 0.8
            case ProposalKind.COALITION:
                target = p.enemy
                if target is None or target in self.friends:
                    return False
                return (
                    self._fears(target)
                    or target in self._border_nations()
                    or self.me.opinions.get(target, 0) <= -20
                )
        return False

    # ------------------------------------------------------------ 2. war

    def _maybe_declare_war(self) -> None:
        if self.enemies or self.v.turn < 3:
            return
        if self._strike_with_the_league():
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
            ratio = ours / max(1, theirs) * (1.3 if self._grudge(nation) >= 2 else 1.0)
            if ratio > best_ratio:
                best, best_ratio = nation, ratio
        if best is not None:
            self.actions.append(DeclareWar(target=best))
            self.enemies.add(best)
            self.mobilising.add(best)
            self.declared = best
            name = self._nation_name(best)
            wrong = max(
                (g for g in self.me.grudges if g.against == best),
                key=lambda g: g.weight,
                default=None,
            )
            if wrong is not None:  # a war of vengeance says so
                self.actions.append(
                    Proclaim(
                        text=f"{name} {wrong.reason.replace(' it', ' us')} in {wrong.since_year}. "
                        f"{self.me.name} has not forgotten, and now it answers."
                    )
                )
                return
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
                if (origin, target) not in self.landings:
                    self._joint_attack(target, need)  # several armies may do what one cannot
                continue
            seen = self.provinces[target]
            fighting = (seen.troops or 0) or seen.siege_by is not None
            send = spare if fighting else min(spare, max(2, need + 2))
            if (origin, target) in self.landings:  # no more than the ships can carry
                send = min(send, self.landings[(origin, target)])
            leader = self.leaders.pop(origin, None)
            tactic = best_tactic(self.v, origin, target)
            self.actions.append(
                Attack(origin=origin, target=target, regiments=send, general=leader, tactic=tactic)
            )
            self.troops[origin] -= send
            self.targeted.add(target)

    def _joint_attack(self, target: ProvinceId, need: int) -> None:
        """Fall on `target` from every neighbouring province at once: the engine joins the
        armies into one battle."""
        seen = self.provinces[target]
        if target in self.targeted or (seen.controller or seen.owner) is None:
            return  # independents fall to one army; joint blows are for wars between crowns
        pool = [
            (o, self.troops[o] - self._reserve(o))
            for o in sorted(self.mine)
            if target in self._neighbors(o)
        ]
        pool = sorted(((o, n) for o, n in pool if n > 0), key=lambda x: (-x[1], x[0]))
        if len(pool) < 2 or sum(n for _, n in pool) < need:
            return
        left = need + max(1, need // 5)  # what it takes, and a fifth more: not every man
        for o, n in pool:
            if left <= 0:
                break
            send = min(n, left)
            leader, tactic = self.leaders.pop(o, None), best_tactic(self.v, o, target)
            self.actions.append(
                Attack(origin=o, target=target, regiments=send, general=leader, tactic=tactic)
            )
            self.troops[o] -= send
            left -= send
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

    def _postures(self) -> None:
        """Every garrison on a border waits in the posture the armies next door can do least
        against, each with its best tactic: the enemy's if at war, any crown's in peace."""
        rules = self.v.rules
        for pid in sorted(self.mine):
            here = self.provinces[pid]
            if not here.army or not sum(here.army.values()):
                continue
            threats = [
                n.army
                for n in (self.provinces[x] for x in self._neighbors(pid))
                if n.army
                and sum(n.army.values())
                and (n.controller or n.owner) not in (None, self.me.id, *self.friends)
                and (not self.enemies or (n.controller or n.owner) in self.enemies)
            ]
            if not threats:
                continue

            def worst(
                posture: Posture, at: ProvinceView = here, threats: list[Army] = threats
            ) -> float:
                return max(
                    tactic_factor(rules, t, posture, army, at.army or {}, at.terrain)
                    for army in threats
                    for t in Tactic
                )

            current = here.posture or Posture.HOLD
            best = min(Posture, key=lambda p: (worst(p) - (p == current) * 1e-6, p.value))
            if best != current and worst(best) < worst(current) - 0.01:
                self.actions.append(SetPosture(province=pid, posture=best))

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
        self._policies()
        self._decisions()  # authority first for the great choices and the colonies
        self._viceroyalty()
        self._crown()
        self._dynasty()
        self._focus(reserve)  # cheap and for good: before the works
        self._navy(reserve)
        self._colonize(reserve)
        self._colonial_forts(reserve)
        for _ in range(1 + (self.budget.ducats > 250) + (self.budget.ducats > 500)):
            self._build(reserve)  # a rich treasury raises more than one work a year
        self._improve(reserve)
        self._convert(reserve)
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

    def _navy(self, reserve: int) -> None:
        """Ships only for a war at sea: in each sea zone our ports look onto where an enemy's
        fleet (there or next door) could blockade us or bar our straits, build towards matching
        it, a few ships a year and never more pay than a tenth of the ducats we earn. Each ship
        is the one that buys most strength in that water per ducat."""
        if not self.enemies:
            return
        rules = self.v.rules
        pay = sum(
            n * rules.ships[k].pay for ships in self.me.fleets.values() for k, n in ships.items()
        )
        room = self.me.income_per_turn.ducats / 10 - pay
        for sea in sorted(self.seas):
            zone = self.seas[sea]
            ports = sorted(
                (p for p in self.owned if sea in self.provinces[p].seas),
                key=lambda p: (-self.provinces[p].development, p),
            )
            if not ports or room <= 0:
                continue
            mine = zone.power.get(self.me.id, 0.0)
            near = (sea, *zone.neighbors)
            rival = max(
                (self.seas[z].power.get(e, 0.0) for z in near for e in self.enemies), default=0.0
            )
            if rival < rules.blockade_min or mine >= rival:
                continue
            water = zone.water
            ship = max(
                Ship, key=lambda k: rules.ships[k].strength[water] / rules.ships[k].cost.ducats
            )
            spec = rules.ships[ship]
            port = self.provinces[ports[0]]
            n = min(
                math.ceil((rival - mine) / spec.strength[water]),
                3,
                rules.ships_per_port + port.development // 3,
                int(room / spec.pay) if spec.pay else 3,
            )
            while n > 0 and not self._afford(spec.cost.times(n), reserve):
                n -= 1
            if n > 0 and self.budget.covers(spec.cost.times(n)):  # goods are not for sale
                self.actions.append(BuildShips(province=port.id, ship=ship, count=n, sea=sea))
                self.budget = self.budget - spec.cost.times(n)
                room -= n * spec.pay

    # how each crown likes to settle: Spain works plantations, France sends settlers, England
    # trades first
    TASTE: ClassVar[dict[str, ColonyKind]] = {
        "spain": ColonyKind.PLANTATION,
        "france": ColonyKind.SETTLEMENT,
        "england": ColonyKind.POST,
    }

    def _colonize(self, reserve: int) -> None:
        """With ducats to spare, send an expedition where a colony pays best for its cost and
        the years it takes, while places are left: of the kind that pays best there."""
        taste = self.TASTE.get(self.me.id)
        lasting = {ColonyKind.PLANTATION: 1.0, ColonyKind.POST: 0.6, ColonyKind.SETTLEMENT: 1.1}

        left = self.v.max_turns - self.v.turn

        def worth(r: RegionView, kind: ColonyKind) -> float:
            """What the colony would bring over the years left, less what it costs."""
            y = r.yields
            due = r.cargo * r.price + 2 * y.goods + y.timber + 0.8 * y.grain + y.iron
            free = r.slots - sum(r.held.values())
            years = 100 / max(5, r.progress_by_kind[kind] + 17.5)
            liked = 1.2 if kind == taste else 1.0
            earned = due * lasting[kind] * liked * max(0.0, left - years)
            return min(1.0, free / 2) * earned - r.cost_by_kind[kind].ducats

        ready = [
            (worth(r, k), r.id.value, k.value, r, k)
            for r in self.v.new_world
            if r.send_error is None
            for k in ColonyKind
        ]
        if not ready or max(ready, key=lambda c: c[:3])[0] <= 0:
            return
        _, _, _, best, kind = max(ready, key=lambda c: c[:3])
        cost = best.cost_by_kind[kind]
        if self.budget.ducats < cost.ducats + reserve + 20 or not self.budget.covers(cost):
            return
        self.actions.append(SendExpedition(region=best.id, kind=kind))
        self.budget = self.budget - cost

    def _decisions(self) -> None:
        """Take every national decision that can be taken, the dearest in authority first."""
        left = self.authority
        for d in sorted(self.me.decisions, key=lambda d: (-d.authority, d.id)):
            if d.taken or d.missing or d.authority > left:
                continue
            if d.ducats and not self.budget.covers(Resources(ducats=d.ducats)):
                continue
            self.actions.append(TakeDecision(decision=d.id))
            left -= d.authority
            self.authority = left
            self.budget = self.budget - Resources(ducats=d.ducats)

    def _viceroyalty(self) -> None:
        """Make the region with the most colonies a viceroyalty, once it can be."""
        rules = self.v.rules
        if not self.budget.covers(rules.viceroyalty_cost) or self.budget.ducats < 150:
            return
        if self.authority < rules.viceroyalty_authority:
            return
        ready = [r for r in self.v.new_world if r.viceroyalty_error is None]
        if not ready:
            return
        best = max(ready, key=lambda r: (r.cargo * r.price, r.id.value))
        self.actions.append(FoundViceroyalty(region=best.id))
        self.budget = self.budget - rules.viceroyalty_cost
        self.authority -= rules.viceroyalty_authority

    def _ocean(self, nation: str) -> float:
        return sum(
            z.power.get(nation, 0.0) for z in self.seas.values() if z.water == Water.ATLANTIC
        )

    def _ports(self) -> list[ProvinceId]:
        """Our ports on the ocean or the Baltic that can spare regiments, the most first."""
        return sorted(
            (
                pid
                for pid in self.mine
                if {Water.ATLANTIC, Water.BALTIC} & set(self.provinces[pid].coasts)
                and not self.provinces[pid].controller
                and self.troops.get(pid, 0) - self._reserve(pid) > 0
            ),
            key=lambda pid: (-(self.troops[pid] - self._reserve(pid)), pid),
        )

    def _carry(self) -> int:
        """The regiments our ships on the ocean and the Baltic can still carry this year."""
        ships = self.v.rules.ships
        room = sum(
            n * ships[k].carries
            for z, zone in self.seas.items()
            if zone.water in (Water.ATLANTIC, Water.BALTIC)
            for k, n in self.me.fleets.get(z, {}).items()
        )
        mine = self._ocean(self.me.id)
        rules = self.v.rules
        if any(self._ocean(e) >= rules.fleet_command * max(mine, 0.1) for e in self.enemies):
            return 0  # an enemy commands the ocean: nothing sails
        return room - self.shipped

    def _embark(self, wanted: int) -> tuple[ProvinceId | None, int]:
        """A port and the regiments it sends overseas (no more than the ships carry)."""
        room = min(wanted, self._carry())
        for pid in self._ports():
            n = min(room, self.troops[pid] - self._reserve(pid))
            if n > 0:
                self.troops[pid] -= n
                self.shipped += n
                return pid, n
        return None, 0

    def _seize_colonies(self) -> None:
        """Beyond the sea: at war, take the enemy's colonies (by sea where nobody holds them,
        by storm where they do); hold the colonies the peoples resist, and break the peoples
        when the regiments there are enough."""
        rules = self.v.rules
        mine = self._ocean(self.me.id)
        power = 1 + self.me.modifiers.battle_power
        regions = {r.id: r for r in self.v.new_world}
        for enemy in sorted(self.enemies - self.mobilising):
            other = next((n for n in self.v.nations if n.id == enemy), None)
            if other is None or not other.colonies or mine < rules.expedition_ships:
                continue
            theirs = self._ocean(enemy)
            best = max(other.colonies, key=lambda r: (regions[r].cargo, r.value))
            defence = regions[best].defence.get(enemy, 0.0)
            if not defence:
                if mine >= rules.seize_command * theirs:  # the Sea Dogs need less
                    self.actions.append(SeizeColony(region=best, enemy=enemy))
                continue
            if mine < theirs:
                continue
            here = self.me.garrisons.get(best, 0)
            need = max(0, math.ceil(1.5 * defence / power) - here)
            if need > self._carry():
                continue
            port, n = self._embark(need) if need else (None, 0)
            if n < need:
                continue
            self.actions.append(SeizeColony(region=best, enemy=enemy, regiments=n, port=port))
        for region, held in sorted(self.me.colonies.items(), key=lambda c: c[0].value):
            r = regions[region]
            here = self.me.garrisons.get(region, 0)
            if r.natives:  # build up a garrison, then strike
                need = math.ceil(1.4 * r.natives_defence / power)
                if here >= need:
                    self.actions.append(ConquerNatives(region=region))
                    continue
                worth = r.resistance >= 0.1 or r.cargo * r.price * held >= 6
                if not worth:
                    continue
                if here + self._carry() >= need:
                    port, n = self._embark(need - here)
                    if port is not None and here + n >= need:
                        self.actions.append(ConquerNatives(region=region, regiments=n, port=port))
                        continue
                    if port is not None:
                        self.actions.append(ShipTroops(region=region, port=port, regiments=n))
                        continue
                port, n = self._embark(min(4, need - here))
                if port is not None:
                    self.actions.append(ShipTroops(region=region, port=port, regiments=n))
                continue
            rivals = any(n != self.me.id for n in r.held) and bool(self.enemies)
            if rivals and here < 2:
                port, n = self._embark(2 - here)
                if port is not None:
                    self.actions.append(ShipTroops(region=region, port=port, regiments=n))

    def _colonial_forts(self, reserve: int) -> None:
        """A fort over the richest colonies a rival could storm."""
        rules = self.v.rules
        cost = rules.colonial_fort_cost
        if self.budget.ducats < cost.ducats + reserve + 60 or not self.budget.covers(cost):
            return
        for r in sorted(self.v.new_world, key=lambda r: (-r.cargo * r.price, r.id.value)):
            held = self.me.colonies.get(r.id, 0)
            rivals = any(n != self.me.id for n in r.held)
            level = self.me.colonial_forts.get(r.id, 0)
            if held >= 2 and rivals and level < rules.colonial_fort_max:
                self.actions.append(BuildColonialFort(region=r.id))
                self.budget = self.budget - cost
                return

    def _sea_battles(self) -> None:
        """Seek out an enemy fleet we clearly outmatch, where ours is or a zone away (the fleet
        sails there first): a fleet worth sinking, and sure odds."""
        engaged: set[str] = set()
        for sea in sorted(self.seas, key=lambda z: -self.seas[z].power.get(self.me.id, 0.0)):
            mine = self.seas[sea].power.get(self.me.id, 0.0)
            if not mine:
                continue
            best = None
            for z in (sea, *self.seas[sea].neighbors):
                if z in engaged:
                    continue
                for enemy in sorted(self.enemies - self.mobilising):
                    ships = sum(self.seas[z].fleets.get(enemy, {}).values())
                    theirs = self.seas[z].power.get(enemy, 0.0)
                    if ships >= 4 and mine >= 1.5 * theirs and (best is None or z == sea):
                        best = (z, enemy)
            if best is None:
                continue
            z, enemy = best
            if z != sea:
                here = self.me.fleets.get(sea, {})
                self.actions.append(SailFleet(origin=sea, target=z, ships=dict(here)))
            self.actions.append(SeekBattle(sea=z, enemy=enemy))
            engaged.add(z)

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
        for pid in sorted(self.owned):  # raise each focused province to its designation
            p = self.provinces[pid]
            design = rules.designations.get(p.focus) if p.focus else None
            if design is None or p.designation_tier >= 3:
                continue
            missing = [k for k in design.keys if k not in p.buildings]
            if missing:
                wishes.append((missing[0], [pid]))
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
        planned = [a for a in self.actions if isinstance(a, Build | UpgradeBuilding)]
        owned = {b for pid in self.owned for b in self.provinces[pid].buildings} | {
            a.building for a in planned if isinstance(a, Build)
        }
        busy = {(a.province, a.building) for a in planned}
        cost = me.building_costs
        for kind, places in wishes:
            spec = rules.buildings[kind]
            for pid in places:
                p = self.provinces[pid]
                if (pid, kind) in busy:
                    continue
                slots_left = p.building_slots - len(p.buildings)
                slots_left -= sum(1 for a in planned if isinstance(a, Build) and a.province == pid)
                if (
                    kind not in p.buildings
                    and not (spec.unique and kind in owned)
                    and (spec.requires is None or spec.requires in p.buildings)
                    and slots_left > 0
                    and not p.unrest
                    and self._unlocked(spec.requires_tech)
                    and self.budget.covers(cost[kind] + Resources(ducats=reserve))
                ):
                    self.actions.append(Build(province=pid, building=kind))
                    self.budget = self.budget - cost[kind]
                    return
                level = p.building_levels.get(kind, 0)
                if 0 < level < spec.max_level and kind not in p.idle and not p.unrest:
                    scale = rules.building_upgrade_costs[level]
                    price = Resources(
                        **{k: math.ceil(v * scale) for k, v in cost[kind].amounts().items()}
                    )
                    if self.budget.covers(price + Resources(ducats=reserve + 20)):
                        self.actions.append(UpgradeBuilding(province=pid, building=kind))
                        self.budget = self.budget - price
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

    def _focus(self, reserve: int) -> None:
        """Give one province a year the focus that pays best there: its richest side of output,
        or a garrison on a threatened border, or learning in a great town with little else."""
        rules = self.v.rules
        if not self.budget.covers(rules.focus_cost + Resources(ducats=reserve)):
            return
        starving = self.me.income_per_turn.grain < self.me.army_upkeep_per_turn.grain
        worth = {"ducats": 1.0, "grain": 1.6 if starving else 0.8, "iron": 2.0, "timber": 1.5,
                 "manpower": 1.2 if self.enemies else 0.6}  # fmt: skip
        fields = {Focus.TRADE: ("ducats",), Focus.FARMING: ("grain",),
                  Focus.MINING: ("iron", "timber"), Focus.GARRISON: ("manpower",),
                  Focus.SHIPYARD: ("timber",)}  # fmt: skip
        best: tuple[float, ProvinceId, Focus] | None = None
        for pid in self.owned:
            p = self.provinces[pid]
            if p.focus is not None or p.controller:
                continue
            out = p.output_per_turn
            for focus, names in fields.items():
                if focus == Focus.SHIPYARD and not (p.seas and (self.me.fleets or self.enemies)):
                    continue  # yards for a realm that sails
                gain = sum(worth[n] * getattr(out, n) for n in names)
                if focus == Focus.GARRISON:
                    gain = gain * 2 + (5 if self._exposed(pid) and self.enemies else 0)
                if best is None or gain > best[0]:
                    best = (gain, pid, focus)
            if p.development >= 6:  # a city builds itself up cheaper as a seat of learning
                gain = 0.6 * p.develop_cost.ducats
                if best is None or gain > best[0]:
                    best = (gain, pid, Focus.LEARNING)
        if best is not None and best[0] >= 4:
            self.actions.append(SetFocus(province=best[1], focus=best[2]))
            self.budget = self.budget - rules.focus_cost

    def _crown(self) -> None:
        """The crown's own deeds: an ambition for the reign, and one royal act a year where it
        is needed most (or before the authority overflows)."""
        if self.me.agenda is None and self.me.agenda_offers:
            self.actions.append(ChooseAgenda(agenda=self.me.agenda_offers[0].id))
        acts, have = self.v.rules.royal_acts, self.authority
        unrest = sum(1 for p in self.owned if self.provinces[p].unrest)
        wish: list[RoyalAct] = []
        if self.me.stability < 1:
            wish.append(RoyalAct.PROGRESS)
        if unrest >= 2:
            wish.append(RoyalAct.PARDON)
        if self.enemies and self.budget.manpower < 6:
            wish.append(RoyalAct.BANNERS)
        if self.enemies and any(isinstance(a, Attack) for a in self.actions):
            wish.append(RoyalAct.PRESENCE)
        if self.budget.ducats < 60:
            wish.append(RoyalAct.LEVY)
        if have >= 90:
            wish += [RoyalAct.PROGRESS, RoyalAct.CHURCH]
        for act in wish:
            if have >= acts[act].cost:
                self.actions.append(RoyalAction(act=act))
                return

    def _dynasty(self) -> None:
        """Tutors for the heir in their weakest art when the crown can spare them; a claim
        pressed when the realm is the stronger, renounced otherwise."""
        rules, heir = self.v.rules, self.me.heir
        if (
            heir is not None
            and self.me.authority >= rules.education_authority + 30
            and self.budget.covers(rules.education_cost + Resources(ducats=80))
        ):
            skill = min(("administration", "diplomacy", "military"), key=lambda k: getattr(heir, k))
            if getattr(heir, skill) < 6:
                self.actions.append(EducateHeir(skill=skill))  # type: ignore[arg-type]
                self.budget = self.budget - rules.education_cost
        for claim in self.me.claims:
            other = next((n for n in self.v.nations if n.id == claim), None)
            press = other is not None and len(self.mine) > other.provinces and not self.enemies
            self.actions.append(PressClaim(nation=claim, press=press))

    def _policies(self) -> None:
        """Take a side on each great choice once, as the realm is: a professional army for a
        soldier king, levies otherwise; mercantile for a realm of ports, agrarian for one that
        must feed its men; fueros while the realm is restless, centralism once it is steady."""
        if self.v.turn < 2:
            return
        ruler = self.me.ruler
        wanted = {
            PolicyAxis.ARMY: 0 if ruler is not None and ruler.military >= 3 else 1,
            PolicyAxis.ECONOMY: 1 if any(self.provinces[p].seas for p in self.owned) else 0,
            PolicyAxis.STATE: 1 if self.me.stability < 1 else 0,
        }
        for axis, side in wanted.items():
            if axis not in self.me.policies:
                self.actions.append(SetPolicy(axis=axis, side=side))
                return

    def _convert(self, reserve: int) -> None:
        """Preach to the richest province of another faith, when the treasury allows."""
        heretics = [
            p
            for p in self.owned
            if self.provinces[p].convert_cost is not None and not self.provinces[p].unrest
        ]
        for pid in sorted(heretics, key=lambda x: (-self.provinces[x].development, x))[:1]:
            cost = self.provinces[pid].convert_cost
            if cost is not None and self.budget.covers(cost + Resources(ducats=reserve + 40)):
                self.actions.append(Convert(province=pid))
                self.budget = self.budget - cost

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
        """One technology a year when the treasury allows: war first in war, wealth in peace,
        the sea for a realm with ports, and the doctrine that suits the realm."""
        costs, tech, levels = self.me.research_costs, self.me.technology, self.v.rules.tech_tree

        def tree(branch: TechBranch, level: int) -> TechLevel | None:
            return levels[branch][level] if level < len(levels[branch]) else None

        ports = any(self.provinces[p].seas for p in self.owned)
        order = [TechBranch.MILITARY] if self.enemies else []
        branches = [TechBranch.ECONOMY, TechBranch.ENGINEERING, TechBranch.MILITARY]
        branches += [TechBranch.ADMINISTRATION] + ([TechBranch.NAVAL] if ports else [])
        order += sorted(branches, key=lambda b: (tech[b], b != TechBranch.ECONOMY, b.value))
        for branch in order:
            cost = costs.get(branch)
            if cost is None or not self.budget.covers(cost + Resources(ducats=reserve)):
                continue
            step = tree(branch, tech[branch])
            if step is None:
                continue
            if step.requires is not None and tech[step.requires[0]] < step.requires[1]:
                continue
            self.actions.append(Research(branch=branch, choice=self._doctrine(step.options)))
            self.budget = self.budget - cost
            return

    def _doctrine(self, options: tuple[TechOption, ...]) -> int:
        """The doctrine worth most to this realm: arms in war, money in peace, the sea and the
        colonies for a realm that sails."""
        if not options:
            return 0
        war = bool(self.enemies)
        sails = bool(self.me.colonies or self.me.expeditions)
        weight = {
            "battle_power": 3.0 if war else 1.5, "morale": 3.0 if war else 1.5,
            "siege": 0.08 if war else 0.04, "fort": 1.0, "veterancy": 0.3, "manpower": 0.8,
            "ducat_income": 2.5, "grain_income": 1.2, "trade": 1.0, "research": 1.5,
            "stability": 1.0, "building": 1.5, "tolerance": 0.6, "grain_upkeep": -1.5,
            "navy": 1.0 if sails else 0.4, "ship_cost": 0.4, "landing": 0.3,
            "colonial": 0.1 if sails else 0.03, "colonial_dues": 1.5 if sails else 0.2,
            "convoys": 0.4, "privateers": 0.1, "infamy": 0.8, "yards": 0.02,
        }  # fmt: skip
        worth = [sum(weight.get(k, 0.0) * v for k, v in o.effects.items()) for o in options]
        return max(range(len(options)), key=lambda i: (worth[i], -i))

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
            share = round(100 * p.development / max(1, their.score))
            cost = share if p.controller else max(5, share)
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

    def _strike_with_the_league(self) -> bool:
        """Leagued against a conqueror next door: strike while it is busy, or when the league
        together outweighs it."""
        against = {t.against for t in self.me.treaties if t.kind == TreatyKind.COALITION}
        for nid in sorted(a for a in against if a and a in self._border_nations()):
            them = next((n for n in self.v.nations if n.id == nid), None)
            if them is None or not them.alive:
                continue
            members = [n for n in self.v.nations if nid in n.leagued_against and n.alive]
            weight = self.me.score + sum(n.score for n in members if n.id != self.me.id)
            busy = bool(them.at_war_with)
            if (busy or weight >= 1.3 * them.score) and self.rng.random() < 0.35:
                self.actions.append(DeclareWar(target=nid))
                self.enemies.add(nid)
                self.mobilising.add(nid)
                self.declared = nid
                self.actions.append(
                    Proclaim(text=f"The league stands against {them.name}. Its conquests end here.")
                )
                return True
        return False

    def _league(self, pending: set[tuple[ProposalKind, str]], others: list[str]) -> None:
        """Against a conqueror Europe fears, look for partners among its other neighbours."""
        rules = self.v.rules
        feared = [
            n
            for n in self.v.nations
            if n.alive
            and n.id != self.me.id
            and n.infamy >= rules.coalition_infamy
            and n.id not in self.friends
            and (n.id in self._border_nations() or self._fears(n.id))
        ]
        if not feared or self.rng.random() > 0.5:
            return
        target = max(feared, key=lambda n: (n.infamy, n.id))
        leagued = {
            t.partner
            for t in self.me.treaties
            if t.kind == TreatyKind.COALITION and t.against == target.id
        }
        near = {
            p.owner
            for p in self.v.provinces
            if p.owner and p.owner not in (target.id, self.me.id)
            for q in (*p.neighbors, *p.sea_neighbors)
            if self.provinces[q].owner == target.id
        }
        partners = sorted(n for n in others if n in near and n != target.id and n not in leagued)
        for partner in partners[:2]:
            if (ProposalKind.COALITION, partner) not in pending:
                self.actions.append(
                    ProposeCoalition(
                        target=partner,
                        against=target.id,
                        note=f"{target.name} swallows its neighbours one by one. Stand with us.",
                    )
                )

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

        self._reply_to_letters()
        self._league(pending, others)
        liked = [n for n in others if self.me.opinions.get(n, 0) >= 10]
        marriages = sum(t.kind == TreatyKind.MARRIAGE for t in self.me.treaties)
        if liked and marriages < self.v.rules.max_marriages and self.rng.random() < 0.06:
            bride = self.rng.choice(liked)
            if (ProposalKind.MARRIAGE, bride) not in pending and not any(
                t.kind == TreatyKind.MARRIAGE and t.partner == bride for t in self.me.treaties
            ):
                self.actions.append(ProposeMarriage(target=bride))

        borders = self._border_nations()
        friendly = self.rng.choice(others)
        if self.rng.random() < 0.08 and friendly not in self.friends:
            if friendly in borders:
                if (ProposalKind.NON_AGGRESSION, friendly) not in pending:
                    self.actions.append(ProposeNonAggression(target=friendly))
            elif (ProposalKind.ALLIANCE, friendly) not in pending and len(self.allies) < 2:
                self.actions.append(ProposeAlliance(target=friendly))
