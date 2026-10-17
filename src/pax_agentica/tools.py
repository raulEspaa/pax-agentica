"""Tools for a ruler: a briefing to read and calculators to call, all over its `NationView`.

Everything here is a pure function of the view a ruler already has, so a tool can never leak
what the fog of war hides: a battle against a garrison you cannot see has no odds. The numbers
follow the engine's own rules (`mechanics`), so a ruler that trusts them is not misled.

    from pax_agentica.tools import briefing, call_tool, TOOL_SPECS

`briefing(view)` is a page of plain text for a prompt. `TOOL_SPECS` describes each calculator as
a JSON-schema function for a language model's tool calling, and `call_tool(view, name, args)`
answers such a call with a small JSON-able dict.
"""

from collections.abc import Callable, Mapping
from typing import Any

from pax_agentica.engine import NationView, Resources
from pax_agentica.engine.mechanics import (
    army_strength,
    buildings_yield,
    good_yield,
    land_yield,
    tactic_factor,
    veteran,
)
from pax_agentica.engine.model import (
    BuildingKind,
    Posture,
    ProvinceId,
    Tactic,
    TechBranch,
    UnitKind,
)
from pax_agentica.engine.view import ProvinceView

# ---------------------------------------------------------------- odds


def win_chance(attack: float, defence: float, low: float, high: float) -> float:
    """The chance that attack * U(low, high) beats defence * U(low, high), exactly."""
    if defence <= 0:
        return 1.0
    if attack <= 0:
        return 0.0
    r = defence / attack  # the attacker wins when u1 > r * u2
    span = high - low
    # integrate P(u1 > r*u2) over u2 in [low, high]; P is 1 below a, 0 above b, linear between
    a = (low / r) if r else high  # r*u2 <= low  -> certain win
    b = high / r  # r*u2 >= high -> certain loss
    lo_c, hi_c = max(low, min(high, a)), max(low, min(high, b))
    total = lo_c - low  # the certain part

    def linear(u: float) -> float:  # antiderivative of (high - r*u) / span
        return (high * u - r * u * u / 2) / span

    total += linear(hi_c) - linear(lo_c)
    return max(0.0, min(1.0, total / span))


def _province(view: NationView, pid: ProvinceId) -> ProvinceView:
    for p in view.provinces:
        if p.id == pid:
            return p
    raise KeyError(f"no province {pid!r}")


def _guns_breach(view: NationView, army: Mapping[UnitKind, int]) -> int:
    total = sum(army.values())
    if not total:
        return 0
    share = army.get(UnitKind.ARTILLERY, 0) / total
    return int(share / view.rules.artillery_share_per_fort_level + 1e-9)


def battle_odds(
    view: NationView,
    origin: ProvinceId,
    target: ProvinceId,
    army: Mapping[UnitKind, int] | None = None,
    *,
    with_general: bool = True,
    tactic: Tactic | None = None,
) -> float | None:
    """The chance an attack from `origin` on `target` wins, with `army` (default: everything at
    `origin`) fighting by `tactic` (default: the best against the garrison's posture). None when
    the defenders are hidden by the fog of war."""
    rules = view.rules
    here, there = _province(view, origin), _province(view, target)
    army = dict(army if army is not None else (here.army or {}))
    if not sum(army.values()):
        return 0.0
    if there.troops is None:
        return None
    if there.troops == 0:
        return 1.0
    ground = there.terrain
    held = there.army or {UnitKind.INFANTRY: there.troops}
    posture = Posture.HOLD if there.siege_by else (there.posture or Posture.HOLD)
    tactic = tactic or best_tactic(view, origin, target, army)
    mine = army_strength(rules, army, ground, attacking=True, nation=view.me.id)
    mine *= 1 + view.me.modifiers.battle_power
    mine *= tactic_factor(rules, tactic, posture, army, held, ground)
    mine *= veteran(rules, here.veterancy or 0.0) * view.me.morale
    if with_general and here.general is not None and here.general.nation == view.me.id:
        mine *= 1 + rules.general_bonus_per_skill * here.general.skill
    theirs = (
        army_strength(
            rules, there.army, ground, attacking=False, nation=there.controller or there.owner
        )
        if there.army
        else float(there.troops)
    )
    owner = next((n for n in view.nations if n.id == there.owner), None)
    if owner is not None:
        theirs *= 1 + rules.military_tech_bonus * owner.technology[TechBranch.MILITARY]
        theirs *= 1 - rules.morale_per_exhaustion * owner.war_exhaustion  # their stability: unseen
    theirs *= veteran(rules, there.veterancy or 0.0)
    if there.general is not None and there.general.nation == there.owner:
        theirs *= 1 + rules.general_bonus_per_skill * there.general.skill
    breach = _guns_breach(view, army) + view.me.modifiers.ignores_fort_levels
    bonus = rules.fort_bonus_per_level * max(0, there.fort - breach)
    if BuildingKind.TRAINING_GROUNDS in there.buildings:
        bonus += 0.2
    if there.is_capital:
        bonus += rules.capital_bonus
    if target in here.sea_neighbors and not view.me.modifiers.navy:
        bonus += rules.sea_crossing_bonus
    theirs *= rules.defender_advantage * rules.terrain_defense[ground] * (1 + bonus)
    return round(win_chance(mine, theirs, rules.roll_min, rules.roll_max), 3)


def best_tactic(
    view: NationView,
    origin: ProvinceId,
    target: ProvinceId,
    army: Mapping[UnitKind, int] | None = None,
) -> Tactic:
    """The tactic that does most against the garrison's posture, as far as `army` (default:
    everything at `origin`) can carry it. Assault when the posture is hidden."""
    rules = view.rules
    here, there = _province(view, origin), _province(view, target)
    army = dict(army if army is not None else (here.army or {}))
    if there.posture is None and not there.siege_by:
        return Tactic.ASSAULT
    posture = Posture.HOLD if there.siege_by else (there.posture or Posture.HOLD)
    held = there.army or {UnitKind.INFANTRY: there.troops or 1}
    return max(
        Tactic,
        key=lambda t: (tactic_factor(rules, t, posture, army, held, there.terrain), t == "assault"),
    )


def targets(view: NationView, origin: ProvinceId) -> list[dict[str, Any]]:
    """Where the regiments at `origin` can go: marches to your own land, attacks elsewhere."""
    here = _province(view, origin)
    out: list[dict[str, Any]] = []
    for pid in (*here.neighbors, *here.sea_neighbors):
        p = _province(view, pid)
        holder = p.controller or p.owner
        if holder == view.me.id:
            out.append({"province": pid, "action": "move"})
        elif holder is None or holder in view.me.at_war_with:
            tactic = best_tactic(view, origin, pid)
            odds = battle_odds(view, origin, pid, tactic=tactic)
            out.append({"province": pid, "action": "attack", "tactic": tactic, "odds": odds})
    return out


# ---------------------------------------------------------------- economy


def _output(view: NationView, p: ProvinceView, *, development: int, buildings: list[BuildingKind],
            workings: int) -> Resources:  # fmt: skip
    rules, mods = view.rules, view.me.modifiers
    base = land_yield(rules, p.good, development, p.terrain)
    built = buildings_yield(
        rules,
        base,
        buildings,
        mods.marketplace_share,
        mods.mill_share,
        development,
        p.good,
        p.building_levels,
    )
    works = good_yield(rules, p.good, development, rules.workings_bonus * workings)
    return base + built + works


def _gain(after: Resources, before: Resources) -> dict[str, int]:
    return {
        k: v - before.amounts()[k] for k, v in after.amounts().items() if v != before.amounts()[k]
    }


def work_gain(view: NationView, province: ProvinceId, work: str) -> dict[str, Any]:
    """What one more level of development (`develop`), workings (`improve`) or a building (its
    id) would add to a province's yearly output, before the realm's modifiers, and its cost."""
    p = _province(view, province)
    now = list(p.buildings)
    before = _output(view, p, development=p.development, buildings=now, workings=p.workings)
    if work == "develop":
        after = _output(view, p, development=p.development + 1, buildings=now, workings=p.workings)
        return {"gain": _gain(after, before), "cost": p.develop_cost.amounts()}
    if work == "improve":
        if p.improve_cost is None:
            return {"error": "the workings are at their best, or the province is not yours"}
        after = _output(view, p, development=p.development, buildings=now, workings=p.workings + 1)
        return {"gain": _gain(after, before), "cost": p.improve_cost.amounts()}
    kind = BuildingKind(work)
    if kind in now:
        return {"error": f"{work} already stands there"}
    after = _output(view, p, development=p.development, buildings=[*now, kind], workings=p.workings)
    spec = view.rules.buildings[kind]
    return {
        "gain": _gain(after, before),
        "cost": view.me.building_costs[kind].amounts(),
        "consumes_a_year": spec.consumes.amounts(),
        "upgradable_to": spec.max_level,
        "effect": spec.effect,
    }


def market_quote(view: NationView, resource: str, amount: int) -> dict[str, int]:
    """What buying or selling `amount` of a traded resource would cost or bring today."""
    price = view.market[resource]
    return {"buy_for": int(amount * price.buy) + 1, "sell_for": int(amount * price.sell)}


# ---------------------------------------------------------------- the briefing


def _res(r: Resources | Mapping[str, int]) -> str:
    amounts = r.amounts() if isinstance(r, Resources) else dict(r)
    return ", ".join(f"{v} {k}" for k, v in amounts.items() if v) or "nothing"


def briefing(view: NationView) -> str:
    """A page of plain text: what a ruler needs to decide this year, and nothing it cannot see."""
    me = view.me
    name = {n.id: n.name for n in view.nations} | {me.id: me.name}
    pname = {p.id: p.name for p in view.provinces}
    net = {
        k: v - me.army_upkeep_per_turn.amounts()[k] - me.inputs_per_turn.amounts()[k]
        for k, v in me.income_per_turn.amounts().items()
    }
    lines = [
        f"# {me.name}, {view.year} (year {view.turn} of {view.max_turns})",
        f"Ruler: {me.ruler.title} {me.ruler.name}, aged {me.ruler.age}" if me.ruler else "",
        f"Treasury: {_res(me.resources)}.",
        "Net a year: " + ", ".join(f"{v:+d} {k}" for k, v in net.items() if v) + ".",
        f"Stability {me.stability:+d}, prestige {me.prestige}, taxes {me.tax:+d}, "
        f"war exhaustion {me.war_exhaustion:.1f}, standing {me.standing}.",
        f"Army: {me.regiments} regiments; manpower pool up to {me.manpower_cap}.",
    ]
    if me.wars:
        lines.append("\n## Wars")
        for w in me.wars:
            lines.append(
                f"- {name[w.enemy]}: war score {w.war_score:+d}, battles {w.battles_won} won, "
                f"{w.battles_lost} lost; attacks allowed from year {w.attacks_allowed_from_turn}"
            )
    threats = []
    mine = set(me.provinces)
    for p in view.provinces:
        if p.id not in mine:
            continue
        for nid in (*p.neighbors, *p.sea_neighbors):
            q = _province(view, nid)
            if q.owner and q.owner != me.id and q.troops and q.troops > (p.troops or 0):
                threats.append(f"- {name.get(q.owner, q.owner)} has {q.troops} in {q.name}, "
                               f"next to your {p.troops} in {p.name}")  # fmt: skip
    if threats:
        lines += ["\n## Borders where you are outnumbered", *threats[:8]]
    lines.append("\n## Your provinces")
    for p in sorted((p for p in view.provinces if p.id in mine), key=lambda p: -p.development):
        flag = " (capital)" if p.is_capital else ""
        state = f", unrest {p.unrest}" if p.unrest else ""
        lines.append(
            f"- {p.name}{flag}: development {p.development}, {p.good.value}, workings "
            f"{p.workings}, {p.troops} regiments, buildings: "
            f"{', '.join(b.value for b in p.buildings) or 'none'}{state}"
        )
    open_missions = [m for m in me.missions if m.status == "open"]
    if open_missions:
        lines.append("\n## Missions")
        for m in open_missions:
            goals = "; ".join(f"{g.text} ({g.have}/{g.need})" for g in m.goals)
            lines.append(f"- {m.title}: {goals}. Reward: {m.reward}")
    if me.pending_events:
        lines.append("\n## Decisions waiting (choose_option)")
        for e in me.pending_events:
            options = " | ".join(f"{i}: {o.label} ({o.effects})" for i, o in enumerate(e.options))
            lines.append(f"- event {e.id}, {e.title}: {options}")
    if view.proposals_to_answer:
        lines.append("\n## Proposals to answer this year (respond)")
        for offer in view.proposals_to_answer:
            terms = []
            if not offer.give.is_empty():
                terms.append(f"gives {_res(offer.give)}")
            if not offer.receive.is_empty():
                terms.append(f"asks {_res(offer.receive)}")
            if offer.cede:
                terms.append("cedes " + ", ".join(pname.get(x, x) for x in offer.cede))
            if offer.demand:
                terms.append("demands " + ", ".join(pname.get(x, x) for x in offer.demand))
            if offer.ask_tribute:
                terms.append(f"asks a tribute of {offer.ask_tribute} a year")
            note = f' "{offer.note}"' if offer.note else ""
            what = "; ".join(terms) or "no terms"
            lines.append(
                f"- #{offer.id} {offer.kind.value} from {name[offer.sender]}: {what}{note}"
            )
    rules = view.rules
    lines.append(
        f"\n## Courts (your infamy {me.infamy:.0f}; leagues can form against a court from "
        f"{rules.coalition_infamy:.0f})"
    )
    for court in sorted(view.nations, key=lambda c: -c.standing):
        if not court.alive:
            continue
        treaties = [
            f"league against {name.get(t.against, t.against)}" if t.against else t.kind.value
            for t in me.treaties
            if t.partner == court.id
        ]
        wars = ", at war with you" if court.id in me.at_war_with else ""
        pacts = ", " + ", ".join(treaties) if treaties else ""
        feared = (
            f", infamy {court.infamy:.0f}" if court.infamy >= rules.coalition_infamy / 2 else ""
        )
        leagues = (
            ", leagued against " + ", ".join(name.get(x, x) for x in court.leagued_against)
            if court.leagued_against
            else ""
        )
        lines.append(
            f"- {court.name}: standing {court.standing}, {court.provinces} provinces, thinks "
            f"{court.opinion_of_you:+d} of you{wars}{pacts}{feared}{leagues}"
        )
    recent = [
        (court.name, e)
        for court in view.nations
        for e in court.correspondence
        if e.turn >= view.turn - 2
    ]
    if recent:
        lines.append("\n## Lately between you and the courts")
        for court_name, said in sorted(recent, key=lambda x: x[1].turn)[-12:]:
            if said.kind.value == "message":
                who = "you" if said.data.get("sender") == me.id else court_name
                year = view.rules.start_year + said.turn - 1
                lines.append(f'- {year}, {who} wrote: "{said.data.get("text")}"')
            else:
                lines.append(f"- {view.rules.start_year + said.turn - 1}: {said.summary}")
    heard = [e for e in view.last_turn_events if said.kind.value == "proclamation"]
    if heard:
        lines.append("\n## Proclamations last year")
        lines += [f"- {said.summary}" for e in heard[:10]]
    prices = ", ".join(f"{k} {p.buy:.2f}/{p.sell:.2f}" for k, p in view.market.items())
    lines.append(f"\nMarket (buy/sell a unit): {prices}.")
    return "\n".join(line for line in lines if line != "")


# ---------------------------------------------------------------- tool calling

ToolFn = Callable[[NationView, dict[str, Any]], Any]

TOOLS: dict[str, ToolFn] = {
    "battle_odds": lambda v, a: {
        "odds": battle_odds(
            v,
            a["origin"],
            a["target"],
            {UnitKind(k): n for k, n in a["army"].items()} if a.get("army") else None,
            tactic=Tactic(a["tactic"]) if a.get("tactic") else None,
        )
    },
    "targets": lambda v, a: {"targets": targets(v, a["origin"])},
    "work_gain": lambda v, a: work_gain(v, a["province"], a["work"]),
    "market_quote": lambda v, a: market_quote(v, a["resource"], int(a["amount"])),
}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "battle_odds",
        "description": "The chance an attack wins, from the engine's own battle rules. None when "
        "the defenders are hidden.",
        "parameters": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "your province attacking from"},
                "target": {"type": "string", "description": "the province attacked"},
                "army": {
                    "type": "object",
                    "description": "regiments by kind (infantry, archers, cavalry, artillery); "
                    "default: everything at origin",
                    "additionalProperties": {"type": "integer"},
                },
                "tactic": {
                    "type": "string",
                    "enum": [t.value for t in Tactic],
                    "description": "assault, flank or bombard; default: the best against the "
                    "garrison's posture",
                },
            },
            "required": ["origin", "target"],
        },
    },
    {
        "name": "targets",
        "description": "Where the regiments of a province can march (your land) or attack, with "
        "the best tactic and the odds of each attack.",
        "parameters": {
            "type": "object",
            "properties": {"origin": {"type": "string"}},
            "required": ["origin"],
        },
    },
    {
        "name": "work_gain",
        "description": "What developing, improving the workings, or raising a building would "
        "add to a province's yearly output, and what it costs.",
        "parameters": {
            "type": "object",
            "properties": {
                "province": {"type": "string"},
                "work": {
                    "type": "string",
                    "description": "'develop', 'improve' or a building id",
                },
            },
            "required": ["province", "work"],
        },
    },
    {
        "name": "market_quote",
        "description": "What buying or selling an amount of grain, iron, timber or goods costs "
        "or brings today, the merchants' cut included.",
        "parameters": {
            "type": "object",
            "properties": {
                "resource": {"type": "string", "enum": ["grain", "iron", "timber", "goods"]},
                "amount": {"type": "integer", "minimum": 1},
            },
            "required": ["resource", "amount"],
        },
    },
]


def call_tool(view: NationView, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Answer one tool call; a bad call comes back as {"error": ...} for the model to read."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"no tool called {name!r}; try one of {sorted(TOOLS)}"}
    try:
        result = tool(view, args)
    except (KeyError, ValueError, TypeError) as err:
        return {"error": f"{type(err).__name__}: {err}"}
    return result if isinstance(result, dict) else {"result": result}
