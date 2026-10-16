"""Several people at one table: a lobby of games where friends each take a throne.

    uv run pax host --saves saves/tables      # then share http://<your address>:8000

Anyone can open a table (a new game) and anyone with its link can take a free throne by name;
every throne nobody takes is ruled by a bot. A year is resolved once every seated human has
ended it, or when the table's turn timer runs out. Each seat gets a secret token, kept by the
browser, so nobody can play another's nation. Every table is saved after every year and picked
up again when the server restarts, so a host can come and go.

Set PAX_INVITE_CODE to require a code to open a table or take a seat (for a server on the
internet). Nothing else is private: this is for playing with friends, not strangers.
"""

import os
import re
import secrets
import time
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from pax_agentica.engine import NationId, Orders, new_game
from pax_agentica.players import Player
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.runner import GameRecord
from pax_agentica.server import Session, add_assets
from pax_agentica.viewer import europe_map, render_html, static_payload

MAX_TABLES = 30
NAME = re.compile(r"^[\w .'-]{1,24}$")


class Seat(BaseModel):
    name: str
    token: str


class TableMeta(BaseModel):
    id: str
    title: str
    seed: int
    max_turns: int
    turn_minutes: float | None = None
    created: float
    seats: dict[NationId, Seat] = Field(default_factory=dict)


class TableFile(BaseModel):
    meta: TableMeta
    record: GameRecord


class NewTable(BaseModel):
    title: str = Field(default="A new age", max_length=40)
    seed: int | None = None
    years: int = Field(default=50, ge=5, le=100)
    turn_minutes: float | None = Field(default=None, ge=1, le=60 * 24)
    name: str = Field(max_length=24)
    nation: NationId
    code: str = ""


class Join(BaseModel):
    name: str = Field(max_length=24)
    nation: NationId
    code: str = ""


class Table:
    def __init__(self, meta: TableMeta, session: Session) -> None:
        self.meta = meta
        self.session = session

    def summary(self) -> dict[str, Any]:
        state = self.session.state
        return {
            "id": self.meta.id,
            "title": self.meta.title,
            "year": state.year,
            "turn": state.turn,
            "max_turns": state.max_turns,
            "finished": state.finished,
            "winner": state.winner,
            "turn_minutes": self.meta.turn_minutes,
            "nations": [
                {
                    "id": n.id,
                    "name": n.name,
                    "color": n.color,
                    "alive": n.alive,
                    "player": self.meta.seats[n.id].name if n.id in self.meta.seats else None,
                }
                for n in state.nations.values()
            ],
        }


def _bots(seed: int, nations: list[NationId], humans: list[NationId]) -> dict[NationId, Player]:
    return {n: GreedyBot(seed) for n in nations if n not in humans}


class Lobby:
    """Every table on this server, kept in memory and saved to `saves` after every year."""

    def __init__(self, saves: Path, invite_code: str | None = None) -> None:
        self.saves = saves
        self.invite_code = invite_code
        self.tables: dict[str, Table] = {}
        self.seen: dict[str, float] = {}  # the save each table in memory was built from
        saves.mkdir(parents=True, exist_ok=True)
        for path in sorted(saves.glob("*.json")):
            self._read(path)

    def _read(self, path: Path) -> None:
        try:
            stamp = path.stat().st_mtime
            self._load(TableFile.model_validate_json(path.read_text(encoding="utf-8")))
            self.seen[path.stem] = stamp
        except (OSError, ValueError):
            pass  # a file we cannot read is left alone

    def _path(self, table_id: str) -> Path:
        return self.saves / f"{table_id}.json"

    def _session(self, meta: TableMeta, record: GameRecord | None = None) -> Session:
        humans = list(meta.seats)
        names = {n: s.name for n, s in meta.seats.items()}
        seconds = meta.turn_minutes * 60 if meta.turn_minutes else None
        state = record.initial if record else new_game(meta.seed, max_turns=meta.max_turns)
        bots = _bots(meta.seed, list(state.nations), humans)
        if record is not None and record.turns:
            return Session.resume(record, humans, bots, turn_seconds=seconds, names=names)
        return Session(state, humans, bots, turn_seconds=seconds, names=names)

    def _load(self, saved: TableFile) -> None:
        session = self._session(saved.meta, saved.record)
        self.tables[saved.meta.id] = Table(saved.meta, session)
        self._hook(self.tables[saved.meta.id])

    def _hook(self, table: Table) -> None:
        """Save the table's seats and record together whenever the game saves."""
        session = table.session

        def save() -> None:
            data = TableFile(meta=table.meta, record=session.record)
            path = self._path(table.meta.id)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(data.model_dump_json(), encoding="utf-8")
            tmp.replace(path)
            self.seen[table.meta.id] = path.stat().st_mtime

        session.save = save  # type: ignore[method-assign]

    def check_code(self, code: str) -> None:
        if self.invite_code and not secrets.compare_digest(code, self.invite_code):
            raise HTTPException(403, "wrong invitation code")

    def open_table(self, req: NewTable) -> tuple[Table, str]:
        self.check_code(req.code)
        if not NAME.match(req.name):
            raise HTTPException(422, "a name of letters, digits and spaces, up to 24")
        if sum(not t.session.state.finished for t in self.tables.values()) >= MAX_TABLES:
            raise HTTPException(429, "this server has enough tables already")
        seed = req.seed if req.seed is not None else secrets.randbelow(1_000_000)
        meta = TableMeta(
            id=secrets.token_urlsafe(6),
            title=req.title.strip() or "A new age",
            seed=seed,
            max_turns=req.years,
            turn_minutes=req.turn_minutes,
            created=time.time(),
        )
        if req.nation not in new_game(seed).nations:
            raise HTTPException(422, f"no great power called {req.nation!r}")
        token = secrets.token_urlsafe(16)
        meta.seats[req.nation] = Seat(name=req.name, token=token)
        table = Table(meta, self._session(meta))
        self.tables[meta.id] = table
        self._hook(table)
        table.session.save()
        return table, token

    def join(self, table: Table, req: Join) -> str:
        self.check_code(req.code)
        if not NAME.match(req.name):
            raise HTTPException(422, "a name of letters, digits and spaces, up to 24")
        state = table.session.state
        if req.nation not in state.nations or not state.nations[req.nation].alive:
            raise HTTPException(422, "no such throne, or it has fallen")
        if req.nation in table.meta.seats:
            raise HTTPException(409, f"{state.nations[req.nation].name} is taken")
        token = secrets.token_urlsafe(16)
        table.meta.seats[req.nation] = Seat(name=req.name, token=token)
        table.session.seat(req.nation, req.name)
        table.session.save()
        return token

    def table(self, table_id: str) -> Table:
        """A table, read again from its save if another server (during a deploy, the old and
        the new revision overlap) has written it since."""
        path = self._path(table_id)
        try:
            newer = path.stat().st_mtime > self.seen.get(table_id, 0.0)
        except OSError:
            newer = False
        if newer:
            self._read(path)
        table = self.tables.get(table_id)
        if table is None:
            raise HTTPException(404, "no such table")
        return table

    def seat_of(self, table: Table, token: str | None) -> NationId:
        for nation, seat in table.meta.seats.items():
            if token and secrets.compare_digest(seat.token, token):
                return nation
        raise HTTPException(403, "take a seat at this table first")


def create_lobby_app(saves: Path, invite_code: str | None = None) -> FastAPI:
    lobby = Lobby(
        saves, invite_code if invite_code is not None else os.environ.get("PAX_INVITE_CODE")
    )
    app = FastAPI(title="Pax Agentica tables", docs_url=None, redoc_url=None)
    web = files("pax_agentica").joinpath("web")
    static = static_payload(new_game(1), europe_map())
    add_assets(app, static)
    app.state.lobby = lobby

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return web.joinpath("lobby.html").read_text(encoding="utf-8")

    @app.get("/api/lobby")
    async def tables() -> dict[str, Any]:
        for t in lobby.tables.values():
            await t.session.tick()
        listed = sorted(lobby.tables.values(), key=lambda t: -t.meta.created)
        return {
            "code_required": bool(lobby.invite_code),
            "powers": [
                {"id": n.id, "name": n.name, "color": n.color} for n in new_game(1).nations.values()
            ],
            "tables": [t.summary() for t in listed],
        }

    @app.post("/api/tables")
    def open_table(req: NewTable) -> dict[str, Any]:
        table, token = lobby.open_table(req)
        return {"table": table.meta.id, "token": token, "nation": req.nation}

    @app.post("/api/t/{table_id}/join")
    def join(table_id: str, req: Join) -> dict[str, Any]:
        table = lobby.table(table_id)
        return {"table": table_id, "token": lobby.join(table, req), "nation": req.nation}

    @app.get("/t/{table_id}", response_class=HTMLResponse)
    def play(table_id: str) -> Any:
        if table_id not in lobby.tables:
            return RedirectResponse("/")
        page = web.joinpath("play.html").read_text(encoding="utf-8")
        boot = f'<script>window.PAX_TABLE = "{table_id}";</script>'
        return page.replace("<head>", "<head>" + boot, 1)

    @app.get("/api/t/{table_id}/static")
    def table_static(table_id: str) -> dict[str, Any]:
        lobby.table(table_id)
        return static

    @app.get("/api/t/{table_id}/game")
    async def game(table_id: str, x_seat: str | None = Header(default=None)) -> dict[str, Any]:
        table = lobby.table(table_id)
        nation = lobby.seat_of(table, x_seat)
        await table.session.tick()
        return table.session.payload(nation) | {"table": table.summary()}

    @app.get("/api/t/{table_id}/status")
    async def status(table_id: str, x_seat: str | None = Header(default=None)) -> dict[str, Any]:
        table = lobby.table(table_id)
        nation = lobby.seat_of(table, x_seat)
        session = table.session
        await session.tick()
        left = session.deadline - time.monotonic() if session.deadline is not None else None
        return {
            "turn": session.state.turn,
            "finished": session.state.finished,
            "submitted": nation in session.pending,
            "waiting_for": session.waiting_for(),
            "seconds_left": max(0, round(left)) if left is not None else None,
        }

    @app.post("/api/t/{table_id}/turn")
    async def turn(
        table_id: str, orders: Orders, x_seat: str | None = Header(default=None)
    ) -> dict[str, Any]:
        table = lobby.table(table_id)
        nation = lobby.seat_of(table, x_seat)
        await table.session.submit(nation, orders)
        return table.session.payload(nation) | {"table": table.summary()}

    @app.get("/t/{table_id}/replay", response_class=HTMLResponse)
    def replay(table_id: str) -> str:
        table = lobby.table(table_id)
        if not table.session.record.turns:
            raise HTTPException(404, "play a year first")
        if not table.session.state.finished:
            raise HTTPException(403, "the replay opens when the game is over")
        return render_html(table.session.record)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
