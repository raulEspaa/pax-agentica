"""The map in the browser: a self-contained HTML replay, and the data the play page shares.

The map is real geography: `data/europe_1500.json` holds the 69 provinces (and the wasteland
around them) as SVG paths, built from Natural Earth by `scripts/build_map.py`. The drawing code
lives in `web/map.js` and `web/map.css`, shared by the replay (inlined into one offline HTML
file) and by the play server (served as static files).
"""

import html
import json
from importlib.resources import files
from typing import Any

from pax_agentica.engine import Event, EventKind, GameState, Resources, Rules
from pax_agentica.engine.mechanics import buildings_yield, land_yield
from pax_agentica.engine.model import (
    RESOURCE_NAMES,
    BuildingKind,
    Good,
    MapDef,
    TechBranch,
    Terrain,
    UnitKind,
)
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
    EventKind.PROCLAMATION,
    EventKind.EVENT_DECIDED,
    EventKind.PROVINCE_OCCUPIED,
    EventKind.PROVINCE_LIBERATED,
    EventKind.SIEGE,
    EventKind.STANCE_CHANGED,
    EventKind.PROVINCE_CEDED,
    EventKind.MONUMENT_RAISED,
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
    EventKind.IMPROVED,
    EventKind.MISSION_COMPLETED,
    EventKind.BUILT,
    EventKind.RESEARCHED,
    EventKind.GENERAL_APPOINTED,
    EventKind.GENERAL_FELL,
    EventKind.GAME_OVER,
}


TRAIT_WORDS = {
    "warlike": "+5% battle power",
    "cautious": "forts 5% stronger",
    "thrifty": "+5% ducats",
    "pious": "stability 10% cheaper",
    "scholar": "research 10% cheaper",
    "builder": "buildings and development 8% cheaper",
    "cunning": "breaking a treaty costs 1 less stability",
    "charming": "every court warms to them, +2 opinion a year",
    "cruel": "+3% battle power, but every court cools, -1 opinion a year",
    "ambitious": "hungry for land and glory",
    "melancholic": "withdrawn, brooding, hard to read",
}
GOOD_ICONS = {
    Good.GRAIN: "🌾",
    Good.FISH: "🐟",
    Good.HORSES: "🐎",
    Good.WINE: "🍷",
    Good.SALT: "🧂",
    Good.WOOL: "🐑",
    Good.CLOTH: "🧵",
    Good.TIMBER: "🪵",
    Good.IRON: "⛏",
    Good.COPPER: "🟠",
    Good.FURS: "🦊",
    Good.SILVER: "🥈",
    Good.GOLD: "🪙",
    Good.SPICES: "🌶",
}
PERSONALITY_WORDS = {
    "hawk": "counsels war: strike before the enemy grows",
    "dove": "counsels peace: war is the dearest thing a crown can buy",
    "schemer": "serves themself first, and the crown when it pays",
    "loyal": "serves the crown before all",
    "frugal": "counts every ducat twice",
    "visionary": "thinks in generations, not in years",
}


def portraits() -> dict[str, str]:
    """Who has a painted portrait (public domain, see web/portraits/CREDITS.md): name -> file."""
    index = files("pax_agentica").joinpath("web/portraits/index.json").read_text(encoding="utf-8")
    result: dict[str, str] = json.loads(index)
    return result


def _terrain_words(rules: Rules, terrain: Terrain) -> str:
    """What a terrain does, in one line: its yield, the price of developing it, its defence."""
    parts = [f"{v:+d} {k}" for k, v in rules.terrain_yield.get(terrain, {}).items()]
    parts += [
        f"developing at {rules.terrain_develop_cost.get(terrain, 1.0):g} times the price",
        f"defence {rules.terrain_defense[terrain]:g} times",
    ]
    return "; ".join(parts)


def province_views() -> dict[str, dict[str, str]]:
    """Which provinces have a period city view (public domain, see web/views/CREDITS.md)."""
    index = files("pax_agentica").joinpath("web/views/index.json").read_text(encoding="utf-8")
    result: dict[str, dict[str, str]] = json.loads(index)
    return result


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
                "consumes": amounts(spec.consumes),
                "effect": spec.effect,
                "requires": KINDS.index(spec.requires) if spec.requires else -1,
                "tech": [spec.requires_tech[0].value, spec.requires_tech[1]]
                if spec.requires_tech
                else None,
                "unique": spec.unique,
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
                    {"name": step.name, "unlocks": step.unlocks, "lore": step.lore}
                    for step in rules.tech_tree[branch]
                ],
            }
            for branch in TechBranch
        ],
        "units": [
            {
                "id": kind.value,
                "name": spec.name,
                "cost": amounts(spec.cost or rules.recruit_cost),
                "pay": spec.pay * rules.ducat_upkeep_per_regiment,
                "rations": spec.rations * rules.grain_upkeep_per_regiment,
                "attack": spec.attack,
                "defence": spec.defence,
                "terrain": {t.value: v for t, v in spec.terrain.items()},
                "requires": KINDS.index(spec.requires) if spec.requires else -1,
                "role": spec.role,
            }
            for kind, spec in rules.units.items()
        ],
        "monuments": {
            pid: {
                "name": m.name,
                "effect": m.effect,
                "lore": m.lore,
                "bonus": m.bonus,
                "perLevel": m.per_level,
            }
            for pid, m in rules.monuments.items()
        },
        "portraits": portraits(),
        "views": province_views(),
        "traits": TRAIT_WORDS,
        "terrainEffects": {t.value: _terrain_words(rules, t) for t in rules.terrain_defense},
        "terrains": {
            t.value: {
                "yield": rules.terrain_yield.get(t, {}),
                "develop": rules.terrain_develop_cost.get(t, 1.0),
                "defence": rules.terrain_defense[t],
                "cavalry": rules.units[UnitKind.CAVALRY].terrain.get(t, 1.0),
                "archers": rules.units[UnitKind.ARCHERS].terrain.get(t, 1.0),
            }
            for t in rules.terrain_defense
        },
        "goods": {
            good.value: {
                "name": good.value.capitalize(),
                "icon": GOOD_ICONS[good],
                "yield": rules.good_yields.get(good, {}),
                "workings": rules.workings.get(good, "Workings"),
            }
            for good in Good
        },
        "personalities": PERSONALITY_WORDS,
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
            "workingsBonus": rules.workings_bonus,
            "mercenaryCost": rules.mercenary_cost,
            "mercenaryLimit": rules.mercenary_limit,
            "patronagePrestige": rules.patronage_prestige,
            "maxWorkings": rules.max_workings,
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
            "grainUpkeep": rules.grain_upkeep_per_regiment,
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
            "monumentCost": amounts(rules.monument_cost),
            "maxMonument": rules.max_monument_level,
            "tributeYears": rules.tribute_years,
            "peaceCostArmyLimit": rules.peace_cost_army_limit,
            "marketBase": rules.market_prices,
            "marketSpread": rules.market_spread,
            "combinedShare": rules.combined_arms_share,
            "combinedBonus": {str(k): v for k, v in rules.combined_arms_bonus.items()},
            "siegeShare": rules.artillery_share_per_fort_level,
        },
    }


def _frame(
    snapshot: Snapshot, order: list[str], nations: list[str], rules: Rules, game_map: MapDef
) -> dict[str, Any]:
    provinces = [snapshot.provinces[p] for p in order]
    base = [
        land_yield(
            rules, game_map.provinces[pid].good, p.development, game_map.provinces[pid].terrain
        )
        for pid, p in zip(order, provinces, strict=True)
    ]
    kinds = [[BuildingKind(b) for b in p.buildings] for p in provinces]
    return {
        "b": [[KINDS.index(k) for k in ks] for ks in kinds],
        "base": [amounts(b) for b in base],
        "bonus": [
            amounts(
                buildings_yield(
                    rules, b, ks, development=p.development, good=game_map.provinces[pid].good
                )
            )
            for b, ks, pid, p in zip(base, kinds, order, provinces, strict=True)
        ],
        "o": [nations.index(p.owner) if p.owner else -1 for p in provinces],
        "c": [nations.index(p.controller) if p.controller else -1 for p in provinces],
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
                "friends": [nations.index(k) for k, x in s.stances.items() if x == "friend"],
                "rivals": [nations.index(k) for k, x in s.stances.items() if x == "rival"],
            }
            for s in (snapshot.nations[n] for n in nations)
        ],
    }


def _chronicle_line(e: Event) -> str:
    """An event as the chronicle tells it; a proclamation is quoted."""
    if e.kind == EventKind.PROCLAMATION:
        return f"{e.summary}: “{e.data['text']}”"
    return e.summary


def render_html(record: GameRecord) -> str:
    state = record.initial
    order = list(state.map.provinces)
    nations = list(state.nations)

    frames = [_frame(record.start, order, nations, state.rules, state.map)]
    years = [state.rules.start_year]
    chronicle: list[list[list[Any]]] = [[]]
    minds: list[dict[int, list[Any]]] = [{}]  # each court's private thoughts and counsel
    for turn in record.turns:
        minds.append(
            {
                nations.index(n): [o.thoughts, {r.value: c for r, c in o.counsel.items()}]
                for n, o in turn.orders.items()
                if o.thoughts or o.counsel
            }
        )
        frames.append(_frame(turn.after, order, nations, state.rules, state.map))
        years.append(turn.year)
        chronicle.append(
            [
                [
                    e.kind.value,
                    _chronicle_line(e),
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
        "minds": minds,
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
