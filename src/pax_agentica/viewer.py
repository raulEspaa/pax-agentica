"""The map in the browser: a self-contained HTML replay, and the data the play page shares.

The map is real geography: `data/europe_1500.json` holds the 68 provinces (and the wasteland
around them) as SVG paths, built from Natural Earth by `scripts/build_map.py`. The drawing code
lives in `web/map.js` and `web/map.css`, shared by the replay (inlined into one offline HTML
file) and by the play server (served as static files).
"""

import html
import json
from importlib.resources import files
from typing import Any

from pax_agentica.engine import EventKind, GameState, Resources, Rules
from pax_agentica.engine.mechanics import buildings_yield, land_yield
from pax_agentica.engine.model import RESOURCE_NAMES, BuildingKind, MapDef, TechBranch
from pax_agentica.runner import GameRecord, Snapshot

KINDS = list(BuildingKind)
TECH = {
    TechBranch.MILITARY: ("Military", "armies fight harder, attacking and defending"),
    TechBranch.ECONOMY: ("Economy", "provinces yield more ducats and grain"),
    TechBranch.ENGINEERING: (
        "Engineering",
        "buildings and development cost fewer ducats and less timber",
    ),
}

CHRONICLE = {
    EventKind.WAR_DECLARED,
    EventKind.JOINED_WAR,
    EventKind.CALL_TO_ARMS_IGNORED,
    EventKind.TREATY_SIGNED,
    EventKind.TREATY_BROKEN,
    EventKind.TREATY_CANCELLED,
    EventKind.TREATY_EXPIRED,
    EventKind.PEACE_SIGNED,
    EventKind.TRADE_COMPLETED,
    EventKind.GIFT,
    EventKind.BATTLE,
    EventKind.PROVINCE_CAPTURED,
    EventKind.CAPITAL_MOVED,
    EventKind.NATION_ELIMINATED,
    EventKind.DEVELOPED,
    EventKind.BUILT,
    EventKind.RESEARCHED,
    EventKind.GENERAL_APPOINTED,
    EventKind.GENERAL_FELL,
    EventKind.GAME_OVER,
}


def europe_map() -> dict[str, Any]:
    """The projected map: province paths, wasteland, coastline, rivers, seas and borders."""
    text = files("pax_agentica").joinpath("data/europe_1500.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def _web(name: str) -> str:
    return files("pax_agentica").joinpath("web", name).read_text(encoding="utf-8")


def amounts(r: Resources) -> list[int]:
    return [getattr(r, name) for name in RESOURCE_NAMES]


def static_payload(state: GameState, geo: dict[str, Any]) -> dict[str, Any]:
    """Everything about a game that never changes: the drawn map, provinces, nations, rules."""
    order = list(state.map.provinces)
    rules = state.rules
    return {
        "map": {
            "width": geo["width"],
            "height": geo["height"],
            "wasteland": geo["wasteland"],
            "coast": geo["coast"],
            "rivers": geo.get("rivers", []),
            "seas": geo.get("seas", []),
            "borders": [
                [order.index(a) if a in order else -1, order.index(b) if b in order else -1, d]
                for a, b, d in geo["borders"]
            ],
        },
        "provinces": [
            {
                "id": pid,
                "name": d.name,
                "terrain": d.terrain.value,
                "good": d.good.value,
                "d": geo["provinces"][pid]["d"],
                "x": geo["provinces"][pid]["x"],
                "y": geo["provinces"][pid]["y"],
                "area": geo["provinces"][pid]["area"],
                "land": [order.index(n) for n in d.neighbors],
                "sea": [order.index(n) for n in d.sea_neighbors],
            }
            for pid, d in state.map.provinces.items()
        ],
        "nations": [{"id": n.id, "name": n.name, "color": n.color} for n in state.nations.values()],
        "resources": list(RESOURCE_NAMES),
        "buildings": [
            {
                "id": kind.value,
                "name": spec.name,
                "category": spec.category.value,
                "cost": amounts(spec.cost),
                "effect": spec.effect,
                "requires": KINDS.index(spec.requires) if spec.requires else -1,
                "tech": [spec.requires_tech[0].value, spec.requires_tech[1]]
                if spec.requires_tech
                else None,
            }
            for kind in KINDS
            for spec in [rules.buildings[kind]]
        ],
        "tech": [
            {
                "id": branch.value,
                "name": TECH[branch][0],
                "effect": TECH[branch][1],
                "perLevel": {
                    TechBranch.MILITARY: rules.military_tech_bonus,
                    TechBranch.ECONOMY: rules.economy_tech_bonus,
                    TechBranch.ENGINEERING: rules.engineering_tech_discount,
                }[branch],
                "cost": amounts(rules.tech_costs[branch]),
                "levels": [
                    {"name": step.name, "unlocks": step.unlocks} for step in rules.tech_tree[branch]
                ],
            }
            for branch in TechBranch
        ],
        "advisors": [
            {
                "id": "treasurer",
                "name": "Treasurer",
                "effect": f"+{rules.treasurer_income_bonus:.0%} ducats per star",
            },
            {
                "id": "chancellor",
                "name": "Chancellor",
                "effect": f"research {rules.chancellor_research_discount:.0%} cheaper per star",
            },
            {
                "id": "marshal",
                "name": "Marshal",
                "effect": f"+{rules.marshal_battle_bonus:.0%} battle power per star",
            },
        ],
        "rules": {
            "maxTech": rules.max_tech_level,
            "rulerIncome": rules.ruler_income_bonus,
            "rulerBattle": rules.ruler_battle_bonus,
            "rulerStability": rules.ruler_stability_discount,
            "advisorSalary": rules.advisor_salary_ducats,
            "advisorYears": rules.advisor_pool_years,
            "generalCost": amounts(rules.general_cost),
            "maxGenerals": rules.max_generals,
            "generalBonus": rules.general_bonus_per_skill,
            "slotEvery": rules.development_per_building_slot,
            "defender": rules.defender_advantage,
            "terrain": {t.value: v for t, v in rules.terrain_defense.items()},
            "fort": rules.fort_bonus_per_level,
            "capital": rules.capital_bonus,
            "sea": rules.sea_crossing_bonus,
            "rollMin": rules.roll_min,
            "rollMax": rules.roll_max,
            "stabilityBonus": rules.stability_income_bonus,
            "pay": rules.ducat_upkeep_per_regiment,
            "recruit": amounts(rules.recruit_cost),
            "disband": amounts(rules.disband_refund),
            "developBase": rules.develop_base_ducats,
            "developPerLevel": rules.develop_ducats_per_level,
            "developTimberBase": rules.develop_timber_base,
            "developTimberPerTwo": rules.develop_timber_per_two_levels,
            "universityDiscount": rules.university_develop_discount,
            "armoryDiscount": rules.armory_iron_discount,
            "maxDevelopment": rules.max_development,
            "stabilityCost": rules.stability_boost_ducats,
            "maxStability": rules.max_stability,
            "mobilization": rules.mobilization_turns,
            "breakPenalty": rules.treaty_break_stability_penalty,
            "startYear": rules.start_year,
        },
    }


def _frame(
    snapshot: Snapshot, order: list[str], nations: list[str], rules: Rules, game_map: MapDef
) -> dict[str, Any]:
    provinces = [snapshot.provinces[p] for p in order]
    base = [
        land_yield(rules, game_map.provinces[pid].good, p.development)
        for pid, p in zip(order, provinces, strict=True)
    ]
    kinds = [[BuildingKind(b) for b in p.buildings] for p in provinces]
    return {
        "b": [[KINDS.index(k) for k in ks] for ks in kinds],
        "base": [amounts(b) for b in base],
        "bonus": [
            amounts(buildings_yield(rules, b, ks)) for b, ks in zip(base, kinds, strict=True)
        ],
        "o": [nations.index(p.owner) if p.owner else -1 for p in provinces],
        "g": [
            [order.index(g.province), nations.index(g.nation), g.name, g.skill]
            for g in snapshot.generals
        ],
        "t": [p.troops for p in provinces],
        "f": [p.fort for p in provinces],
        "v": [p.development for p in provinces],
        "u": [p.unrest for p in provinces],
        "n": [
            {
                "alive": s.alive,
                "capital": order.index(s.capital),
                "provinces": s.provinces,
                "score": s.score,
                "army": s.regiments,
                "res": amounts(s.resources),
                "stability": s.stability,
                "wars": [nations.index(n) for n in s.at_war_with],
                "allies": [nations.index(n) for n in s.allies],
                "tech": [s.technology.get(b.value, 0) for b in TechBranch],
                "ruler": s.ruler,
            }
            for s in (snapshot.nations[n] for n in nations)
        ],
    }


def render_html(record: GameRecord) -> str:
    state = record.initial
    order = list(state.map.provinces)
    nations = list(state.nations)

    frames = [_frame(record.start, order, nations, state.rules, state.map)]
    years = [state.rules.start_year]
    chronicle: list[list[list[Any]]] = [[]]
    for turn in record.turns:
        frames.append(_frame(turn.after, order, nations, state.rules, state.map))
        years.append(turn.year)
        chronicle.append(
            [
                [
                    e.kind.value,
                    e.summary,
                    order.index(e.province) if e.province else -1,
                    [nations.index(n) for n in e.nations if n in nations],
                ]
                for e in turn.events
                if e.audience is None and e.kind in CHRONICLE
            ]
        )

    over = next(
        (e.summary for t in record.turns[-1:] for e in t.events if e.kind == EventKind.GAME_OVER),
        "",
    )
    data = static_payload(state, europe_map()) | {
        "rulers": [record.players.get(n, "") for n in nations],
        "frames": frames,
        "years": years,
        "chronicle": chronicle,
        "winner": nations.index(record.winner) if record.winner else -1,
        "over": over,
        "seed": state.seed,
    }
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(f"Pax Agentica · seed {state.seed}")
    page = _web("replay.html")
    return (
        page.replace("__TITLE__", title)
        .replace("/*__CSS__*/", _web("map.css"))
        .replace("/*__MAPJS__*/", _web("map.js").replace("</", "<\\/"))
        .replace("__DATA__", payload)
    )
