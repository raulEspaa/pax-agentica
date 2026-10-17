"""Play a nation yourself: a small web server around one game.

You see exactly what an AI ruler sees (your `NationView`, fog of war included) and answer with
the same `Orders`. Every other throne is held by a `Player` (bots today, LLM rulers later), and
they decide in parallel while the engine waits for you to end the turn.

    uv run pax serve --nation france --seed 1     # then open http://127.0.0.1:8000
"""

import asyncio
import secrets
import time
from collections.abc import Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from pax_agentica.engine import (
    Event,
    GameState,
    NationId,
    NationView,
    Orders,
    new_game,
    resolve_turn,
    view_for,
)
from pax_agentica.engine.mechanics import output_with
from pax_agentica.engine.model import BuildingKind
from pax_agentica.players import Player
from pax_agentica.runner import GameRecord, play_turn, snapshot
from pax_agentica.viewer import europe_map, render_html, static_payload

CHRONICLE_YEARS = 25  # past years sent to the page; the replay keeps them all
PATIENCE = 600.0  # seconds a player who has answered waits before ending the year without others


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
    """One game in progress, with one or more humans on their thrones. A year is resolved once
    every human has sent their orders (or, with a turn timer, once time runs out: whoever has not
    answered by then does nothing that year)."""

    def __init__(
        self,
        state: GameState,
        humans: NationId | Sequence[NationId],
        rulers: Mapping[NationId, Player],
        save_to: Path | None = None,
        turn_seconds: float | None = None,
        names: Mapping[NationId, str] | None = None,
    ) -> None:
        self.humans = [humans] if isinstance(humans, str) else list(humans)
        for human in self.humans:
            if human not in state.nations:
                raise ValueError(f"unknown nation {human!r}")
        self.state = state
        self.rulers = {n: p for n, p in rulers.items() if n not in self.humans}
        self.save_to = save_to
        self.turn_seconds = turn_seconds
        self.names = dict(names or {})
        self.record = GameRecord(
            players={n: p.name for n, p in self.rulers.items()}
            | {h: self.names.get(h, "you") for h in self.humans},
            initial=state,
            start=snapshot(state),
        )
        self.pending: dict[NationId, Orders] = {}
        # orders a human is still working on, sent as they change: if the year ends without
        # their answer (the clock, or the others going on), these are carried out instead
        self.drafts: dict[NationId, Orders] = {}
        # wall-clock times, so a saved table keeps its clock across a restart
        self.deadline = time.time() + turn_seconds if turn_seconds else None
        self.first_answer: float | None = None  # when the first human ended this year
        self.patience = PATIENCE
        self.lock = asyncio.Lock()

    @property
    def human(self) -> NationId:
        """The first human: the only one in a game for one."""
        return self.humans[0]

    @classmethod
    def resume(
        cls,
        record: GameRecord,
        humans: NationId | Sequence[NationId],
        rulers: Mapping[NationId, Player],
        **kw: Any,
    ) -> "Session":
        """Pick a saved game up where it stopped. The engine is deterministic, so replaying
        the recorded orders rebuilds the exact state."""
        session = cls(record.initial, humans, rulers, **kw)
        state = record.initial
        for turn in record.turns:
            state = resolve_turn(state, turn.orders)
        session.state, session.record = state, record
        return session

    def save(self) -> None:
        if self.save_to is not None:
            self.save_to.parent.mkdir(parents=True, exist_ok=True)
            self.save_to.write_text(self.record.model_dump_json(), encoding="utf-8")

    def seat(self, nation: NationId, name: str) -> None:
        """A human takes over a throne a bot was holding; it decides from the next answer on."""
        self.rulers.pop(nation, None)
        if nation not in self.humans:
            self.humans.append(nation)
        self.names[nation] = name
        self.record.players[nation] = name

    def unseat(self, nation: NationId, bot: Player) -> None:
        """A human leaves: a bot takes the throne from this year on."""
        if nation in self.humans:
            self.humans.remove(nation)
        self.pending.pop(nation, None)
        self.drafts.pop(nation, None)
        self.names.pop(nation, None)
        self.rulers[nation] = bot
        self.record.players[nation] = bot.name

    def waiting_for(self) -> list[NationId]:
        alive = set(self.state.alive_nations())
        return [h for h in self.humans if h not in self.pending and h in alive]

    async def submit(self, nation: NationId, orders: Orders) -> bool:
        """Hand in a human's orders; the year is resolved once nobody is left to wait for.
        True if this answer resolved it."""
        async with self.lock:
            if self.state.finished:
                raise HTTPException(409, "the game is over")
            if nation not in self.humans:
                raise HTTPException(403, "that throne is not yours")
            self.pending[nation] = orders
            if self.first_answer is None:
                self.first_answer = time.time()
            if self.waiting_for():
                self.save()  # the answer survives a restart while the others decide
                return False
            await self._resolve()
            return True

    def draft(self, nation: NationId, orders: Orders) -> None:
        """Keep a human's unsent orders, in case the year ends before they answer."""
        if nation not in self.humans:
            raise HTTPException(403, "that throne is not yours")
        if not self.state.finished:
            self.drafts[nation] = orders

    def force_in(self, nation: NationId) -> int | None:
        """Seconds before `nation`, having answered, may end the year without the absent;
        None when there is no one to wait for or it has not answered."""
        if nation not in self.pending or not self.waiting_for() or self.state.finished:
            return None
        since = self.first_answer or time.time()
        return max(0, round(since + self.patience - time.time()))

    async def force(self, nation: NationId) -> bool:
        """End the year without those who have not answered (their drafts are carried out)."""
        async with self.lock:
            wait = self.force_in(nation)
            if wait is None or wait > 0:
                return False
            await self._resolve()
            return True

    async def settle(self) -> bool:
        """Resolve the year if no one is left to wait for (after someone leaves)."""
        async with self.lock:
            if self.pending and not self.waiting_for() and not self.state.finished:
                await self._resolve()
                return True
        return False

    async def end_turn(self, orders: Orders) -> None:
        """The single player's orders: in a game for one, the year ends at once."""
        await self.submit(self.human, orders)

    async def tick(self) -> bool:
        """Resolve the year if its time is up. Called whenever someone looks at the game."""
        if self.deadline is None or time.time() < self.deadline or self.state.finished:
            return False
        async with self.lock:
            if self.deadline is not None and time.time() >= self.deadline:
                await self._resolve()
                return True
        return False

    async def _resolve(self) -> None:
        players: dict[NationId, Player] = dict(self.rulers)
        for human in self.humans:
            chosen = self.pending[human] if human in self.pending else self.drafts.get(human)
            players[human] = HumanOrders(chosen or Orders())
        self.state, turn = await play_turn(self.state, players)
        self.record.turns.append(turn)
        self.record.winner = self.state.winner
        self.pending = {}
        self.drafts = {}
        self.first_answer = None
        if self.turn_seconds:
            self.deadline = time.time() + self.turn_seconds
        self.save()

    def chronicle(self, nation: NationId | None = None) -> list[dict[str, Any]]:
        """Every past event this human could witness, newest year first."""
        nation = nation or self.human
        years = []
        for turn in reversed(self.record.turns):
            seen = [e for e in turn.events if e.visible_to(nation)]
            years.append({"turn": turn.turn, "year": turn.year, "events": _events(seen)})
        return years

    def history(self, nation: NationId | None = None) -> list[dict[str, Any]]:
        """Year by year: this human's realm in full, and of every court what all Europe can see
        (development, provinces, standing). For the page's charts of a reign."""
        nation = nation or self.human
        rows = []
        start = self.record.initial.rules.start_year
        for year, snap in [(start, self.record.start)] + [
            (t.year + 1, t.after) for t in self.record.turns
        ]:
            mine = snap.nations.get(nation)
            if mine is None:
                continue
            rows.append(
                {
                    "year": year,
                    "me": {
                        "development": mine.score,
                        "provinces": mine.provinces,
                        "regiments": mine.regiments,
                        "ducats": mine.resources.ducats,
                        "income": mine.income,
                        "prestige": mine.prestige,
                        "standing": mine.standing,
                        "stability": mine.stability,
                        "ruler": mine.ruler,
                        "at_war": bool(mine.at_war_with),
                    },
                    "courts": {
                        nid: [n.score, n.provinces, n.standing]
                        for nid, n in snap.nations.items()
                        if n.alive
                    },
                }
            )
        return rows

    def story(self, nation: NationId | None = None) -> dict[str, Any]:
        """The milestones of this human's whole reign, and what binds it to every court:
        battles fought, wars, treaties, land taken. For the page's chronicle of the reign."""
        nation = nation or self.human
        keep = {
            "province_captured", "province_ceded", "province_liberated", "province_occupied",
            "mission_completed", "succession", "war_declared", "peace_signed", "treaty_signed",
            "treaty_broken", "monument_raised", "nation_eliminated", "coalition_joined", "grudge",
        }  # fmt: skip
        milestones: list[dict[str, Any]] = []
        bonds: dict[str, dict[str, int]] = {}

        def bond(other: str) -> dict[str, int]:
            return bonds.setdefault(
                other,
                {"battles_won": 0, "battles_lost": 0, "wars": 0, "treaties": 0, "taken": 0,
                 "lost": 0, "betrayals": 0},
            )  # fmt: skip

        for turn in self.record.turns:
            for e in turn.events:
                if nation not in e.nations or not e.visible_to(nation):
                    continue
                others = [n for n in e.nations if n != nation]
                if e.kind.value == "battle" and others:
                    won = (e.data.get("attacker") == nation) == bool(e.data.get("attacker_won"))
                    bond(others[0])["battles_won" if won else "battles_lost"] += 1
                if e.kind.value == "war_declared" and others:
                    bond(others[0])["wars"] += 1
                if e.kind.value == "treaty_signed" and others:
                    bond(others[0])["treaties"] += 1
                if e.kind.value == "treaty_broken" and others:
                    bond(others[0])["betrayals"] += 1
                if e.kind.value in ("province_captured", "province_ceded") and others:
                    taker = e.nations[0] if e.kind.value == "province_captured" else e.nations[-1]
                    bond(others[0])["taken" if taker == nation else "lost"] += 1
                if e.kind.value in keep:
                    milestones.append(
                        {"year": turn.year, "kind": e.kind.value, "summary": e.summary,
                         "nations": list(e.nations), "province": e.province}
                    )  # fmt: skip
        return {"milestones": milestones, "bonds": bonds}

    def previews(self, nation: NationId | None = None) -> dict[str, dict[str, Any]]:
        """For each of the human's provinces, what one more development or each building not
        yet standing would add to its yearly output, and what each standing one adds. Only for
        the page: an AI ruler's view stays lean."""
        state, out = self.state, {}
        for pid in state.provinces_of(nation or self.human):
            p = state.provinces[pid]
            now = output_with(state, pid)
            gains = {
                kind.value: (output_with(state, pid, extra=(kind,)) - now).model_dump()
                for kind in BuildingKind
                if kind not in p.buildings
            }
            built = {
                kind.value: (now - output_with(state, pid, without=(kind,))).model_dump()
                for kind in p.buildings
            }
            upgrades = {
                kind.value: (output_with(state, pid, upgrade=kind) - now).model_dump()
                for kind in p.buildings
                if p.level(kind) < state.rules.buildings[kind].max_level
            }
            develop = output_with(state, pid, development=p.development + 1) - now
            improve = output_with(state, pid, workings=p.workings + 1) - now
            out[pid] = {
                "develop": develop.model_dump(),
                "improve": improve.model_dump(),
                "buildings": gains,
                "built": built,
                "upgrades": upgrades,
            }
        return out

    def payload(self, nation: NationId | None = None) -> dict[str, Any]:
        nation = nation or self.human
        state = self.state
        left = max(0, round(self.deadline - time.time())) if self.deadline is not None else None
        return {
            "human": nation,
            "view": view_for(state, nation).model_dump(mode="json"),
            "finished": state.finished,
            "winner": state.winner,
            "chronicle": self.chronicle(nation)[:CHRONICLE_YEARS],
            "rulers": self.record.players,
            "previews": self.previews(nation),
            "history": self.history(nation),
            "story": self.story(nation),
            "saved_to": str(self.save_to) if self.save_to else None,
            "humans": {h: self.names.get(h, "you") for h in self.humans},
            "submitted": nation in self.pending,
            "waiting_for": self.waiting_for(),
            "seconds_left": left,
            "force_in": self.force_in(nation),
        }


def _events(events: list[Event]) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json", exclude={"audience"}) for e in events]


class Feedback(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    table: str | None = Field(default=None, max_length=20)
    nation: str | None = Field(default=None, max_length=20)
    year: int | None = None


MAX_FEEDBACK = 1000  # notes kept; beyond this the box is full


def add_feedback(app: FastAPI, folder: Path | None) -> None:
    """A box for play-testers' notes: one JSON file each, read by whoever runs the server."""

    @app.post("/api/feedback")
    def feedback(note: Feedback) -> dict[str, str]:
        if folder is None:
            raise HTTPException(503, "this server keeps no feedback")
        folder.mkdir(parents=True, exist_ok=True)
        if sum(1 for _ in folder.glob("*.json")) >= MAX_FEEDBACK:
            raise HTTPException(507, "the feedback box is full")
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        path = folder / f"{stamp}-{secrets.token_hex(3)}.json"
        path.write_text(note.model_dump_json() + "\n", encoding="utf-8")
        return {"status": "thank you"}


def add_assets(app: FastAPI, static: dict[str, Any]) -> None:
    """The page's scripts, styles, engravings and portraits: only the files we ship."""
    web = files("pax_agentica").joinpath("web")

    @app.get("/static/{name}")
    def asset(name: str) -> Response:
        types = {
            "map.js": "text/javascript",
            "map.css": "text/css",
            "play.js": "text/javascript",
            "icons.js": "text/javascript",
            "juice.js": "text/javascript",
            "scenes.js": "text/javascript",
            "favicon.svg": "image/svg+xml",
        }
        if name not in types:
            raise HTTPException(404)
        return Response(web.joinpath(name).read_text(encoding="utf-8"), media_type=types[name])

    paintings = {f"{slug}.jpg" for slug in static["portraits"].values()}
    views = {f"{pid}.jpg" for pid in static["views"]}

    @app.get("/views/{name}")
    def view_of(name: str) -> Response:
        if name not in views:  # only the engravings we ship
            raise HTTPException(404)
        image = web.joinpath("views", name).read_bytes()
        return Response(image, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

    @app.get("/portraits/{name}")
    def portrait(name: str) -> Response:
        if name not in paintings:  # only the files we ship, never a path
            raise HTTPException(404)
        image = web.joinpath("portraits", name).read_bytes()
        return Response(image, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


def create_app(session: Session) -> FastAPI:
    app = FastAPI(title="Pax Agentica", docs_url="/api/docs", redoc_url=None)
    web = files("pax_agentica").joinpath("web")
    static = static_payload(session.state, europe_map())
    add_assets(app, static)
    add_feedback(app, session.save_to.parent / "feedback" if session.save_to else None)

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return web.joinpath("play.html").read_text(encoding="utf-8")

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
