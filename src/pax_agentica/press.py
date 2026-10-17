"""The press kit: store capsules and a trailer, drawn by the game itself from a game of bots.

`pax press` serves two pages on this machine only, never on the tables: one that paints the
store's capsule art at the sizes the store asks for, and one that plays a trailer to record
from the screen. Both are fed by a reel: a whole game played by bots, reduced to who held each
province every year and the armies that marched, fought and conquered in it.
"""

from __future__ import annotations

import asyncio
from importlib.resources import files
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from pax_agentica.engine import new_game
from pax_agentica.engine.events import Event, EventKind
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.runner import GameRecord, run_game
from pax_agentica.server import add_assets
from pax_agentica.viewer import europe_map, static_payload

TAKEN = {EventKind.PROVINCE_CAPTURED, EventKind.PROVINCE_OCCUPIED, EventKind.PROVINCE_LIBERATED}
HEADLINES = {
    EventKind.WAR_DECLARED,
    EventKind.PEACE_SIGNED,
    EventKind.NATION_ELIMINATED,
    EventKind.CRISIS,
    EventKind.COALITION_JOINED,
    EventKind.SUCCESSION,
    EventKind.GAME_OVER,
}


def _marches(events: list[Event]) -> list[dict[str, Any]]:
    """The armies of one year: from where each set out to where it arrived, and how it went."""
    took = {e.province: e.nations[0] for e in events if e.kind in TAKEN and e.province}
    fought = {e.province for e in events if e.kind == EventKind.BATTLE and "attacker" in e.data}
    out: list[dict[str, Any]] = []
    for e in events:
        if e.kind == EventKind.BATTLE and "attacker" in e.data and e.province:
            origins = str(e.data.get("origins") or e.data.get("origin") or "").split(", ")
            for origin in filter(None, origins):
                out.append(
                    {
                        "from": origin,
                        "to": e.province,
                        "nation": str(e.data["attacker"]),
                        "fight": True,
                        "won": bool(e.data.get("attacker_won")),
                        "took": took.get(e.province, ""),
                    }
                )
        elif e.kind in TAKEN and e.province not in fought and e.data.get("origin"):
            out.append(
                {
                    "from": str(e.data["origin"]),
                    "to": e.province,
                    "nation": e.nations[0],
                    "fight": False,
                    "won": True,
                    "took": e.nations[0],
                }
            )
    return out


def reel(record: GameRecord) -> dict[str, Any]:
    """A whole game for the camera: the map every year and what moved on it."""
    start = record.initial.rules.start_year
    provinces = list(record.start.provinces)
    snaps = [record.start] + [t.after for t in record.turns]
    return {
        "years": [start + k for k in range(len(snaps))],
        "provinces": provinces,
        "owners": [[s.provinces[p].owner or "" for p in provinces] for s in snaps],
        "standing": [{nid: n.standing for nid, n in s.nations.items() if n.alive} for s in snaps],
        "marches": [_marches(t.events) for t in record.turns],
        "headlines": [
            [
                {"kind": e.kind.value, "text": e.summary, "nations": list(e.nations)}
                for e in t.events
                if e.kind in HEADLINES
            ]
            for t in record.turns
        ],
        "winner": record.winner,
    }


def play_reel(seed: int, turns: int) -> dict[str, Any]:
    state = new_game(seed, max_turns=turns)
    record = asyncio.run(run_game(state, {n: GreedyBot(seed) for n in state.nations}))
    return reel(record)


def create_press_app(seed: int = 7, turns: int = 50) -> FastAPI:
    app = FastAPI(title="Pax Agentica press kit", docs_url=None, redoc_url=None)
    web = files("pax_agentica").joinpath("web")
    static = static_payload(new_game(seed), europe_map())
    add_assets(app, static)
    cache: dict[tuple[int, int], dict[str, Any]] = {}

    @app.get("/", response_class=HTMLResponse)
    @app.get("/press", response_class=HTMLResponse)
    def press() -> str:
        return web.joinpath("press.html").read_text(encoding="utf-8")

    @app.get("/trailer", response_class=HTMLResponse)
    def trailer() -> str:
        return web.joinpath("trailer.html").read_text(encoding="utf-8")

    @app.get("/api/static")
    def static_data() -> dict[str, Any]:
        return static

    @app.get("/api/reel")
    def get_reel(seed: int = seed, turns: int = turns) -> dict[str, Any]:
        if not 5 <= turns <= 80:
            raise HTTPException(422, "between 5 and 80 years")
        if (seed, turns) not in cache:
            cache[(seed, turns)] = play_reel(seed, turns)
        return cache[(seed, turns)]

    return app
