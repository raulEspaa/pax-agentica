"""Play a nation yourself: a small web server around one game.

You see exactly what an AI ruler sees (your `NationView`, fog of war included) and answer with
the same `Orders`. Every other throne is held by a `Player` (bots today, LLM rulers later), and
they decide in parallel while the engine waits for you to end the turn.

    uv run pax serve --nation france --seed 1     # then open http://127.0.0.1:8000
"""

import asyncio
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

from pax_agentica.engine import (
    Event,
    GameState,
    NationId,
    NationView,
    Orders,
    new_game,
    view_for,
)
from pax_agentica.players import Player
from pax_agentica.runner import GameRecord, play_turn, snapshot
from pax_agentica.viewer import europe_map, render_html, static_payload


class HumanOrders:
    """The human's orders for one turn, wrapped as a `Player`."""

    def __init__(self, orders: Orders) -> None:
        self.orders = orders

    @property
    def name(self) -> str:
        return "human"

    async def decide(self, view: NationView) -> Orders:
        return self.orders


class Session:
    """One game in progress, with a human on one throne."""

    def __init__(
        self, state: GameState, human: NationId, rulers: Mapping[NationId, Player]
    ) -> None:
        if human not in state.nations:
            raise ValueError(f"unknown nation {human!r}")
        self.state = state
        self.human = human
        self.rulers = dict(rulers)
        self.record = GameRecord(
            players={n: p.name for n, p in self.rulers.items()} | {human: "you"},
            initial=state,
            start=snapshot(state),
        )
        self.lock = asyncio.Lock()

    async def end_turn(self, orders: Orders) -> None:
        async with self.lock:
            if self.state.finished:
                raise HTTPException(409, "the game is over")
            players: dict[NationId, Player] = dict(self.rulers)
            players[self.human] = HumanOrders(orders)
            self.state, turn = await play_turn(self.state, players)
            self.record.turns.append(turn)
            self.record.winner = self.state.winner

    def chronicle(self) -> list[dict[str, Any]]:
        """Every past event the human could witness, newest year first."""
        years = []
        for turn in reversed(self.record.turns):
            seen = [e for e in turn.events if e.visible_to(self.human)]
            years.append({"turn": turn.turn, "year": turn.year, "events": _events(seen)})
        return years

    def payload(self) -> dict[str, Any]:
        state = self.state
        return {
            "human": self.human,
            "view": view_for(state, self.human).model_dump(mode="json"),
            "finished": state.finished,
            "winner": state.winner,
            "chronicle": self.chronicle(),
            "rulers": self.record.players,
        }


def _events(events: list[Event]) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json", exclude={"audience"}) for e in events]


def create_app(session: Session) -> FastAPI:
    app = FastAPI(title="Pax Agentica", docs_url="/api/docs", redoc_url=None)
    web = files("pax_agentica").joinpath("web")
    static = static_payload(session.state, europe_map())

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return web.joinpath("play.html").read_text(encoding="utf-8")

    @app.get("/static/{name}")
    def asset(name: str) -> Response:
        types = {"map.js": "text/javascript", "map.css": "text/css", "play.js": "text/javascript"}
        if name not in types:
            raise HTTPException(404)
        return Response(web.joinpath(name).read_text(encoding="utf-8"), media_type=types[name])

    @app.get("/api/static")
    def static_data() -> dict[str, Any]:
        return static

    @app.get("/api/game")
    def game() -> dict[str, Any]:
        return session.payload()

    @app.post("/api/turn")
    async def turn(orders: Orders) -> dict[str, Any]:
        await session.end_turn(orders)
        return session.payload()

    @app.get("/api/schema")
    def schema() -> dict[str, Any]:
        return Orders.model_json_schema()

    @app.get("/replay", response_class=HTMLResponse)
    def replay() -> str:
        if not session.record.turns:
            raise HTTPException(404, "play a turn first")
        return render_html(session.record)

    return app


def default_session(
    nation: NationId,
    seed: int = 1,
    max_turns: int = 50,
    rulers: Mapping[NationId, Player] | None = None,
) -> Session:
    """A new game where `nation` is yours and every other throne goes to a greedy bot, unless
    `rulers` says otherwise."""
    from pax_agentica.players.greedy_bot import GreedyBot

    state = new_game(seed, max_turns=max_turns)
    chosen = dict(rulers or {})
    for n in state.nations:
        if n != nation and n not in chosen:
            chosen[n] = GreedyBot(seed)
    chosen.pop(nation, None)
    return Session(state, nation, chosen)
