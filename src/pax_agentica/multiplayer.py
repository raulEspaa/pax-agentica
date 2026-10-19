"""Several people at one table: a lobby of games where friends each take a throne.

    uv run pax host --saves saves/tables      # then share http://<your address>:8000

Anyone can open a table (a new game) and anyone with its link can take a free throne by name;
every throne nobody takes is ruled by a bot. A year is resolved once every seated human has
ended it, when the table's turn timer runs out, or when a player who has answered stops waiting
for the absent. Each seat gets a secret token, kept by the browser, so nobody can play another's
nation. Every table is saved after every year (and every answer), and picked up again when the
server restarts, so a host can come and go.

Tables close by themselves: when the last player leaves, when no player has had the game open for
half an hour (longer for tables whose years last longer), when nobody has looked at
them, or once the game is over; a closed table keeps its replay for a week, then goes. A table
nobody has looked at for a while is let go from memory and read again when someone returns.

Set PAX_INVITE_CODE to require a code to open a table or take a seat (for a server on the
internet); several codes, separated by commas, each work (one for friends, one for a group of
testers, each withdrawn on its own). Nothing else is private: this is for playing with
friends, not strangers.
"""

import json
import os
import re
import secrets
import time
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from pax_agentica.engine import NationId, Orders, new_game
from pax_agentica.players import Player
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.runner import GameRecord
from pax_agentica.server import Session, add_assets, add_feedback
from pax_agentica.viewer import europe_map, render_html, static_payload

MAX_TABLES = 30  # open at once
NAME = re.compile(r"^[\w .'-]{1,24}$")
IDLE_CLOSE = 3 * 24 * 3600.0  # the longest a table waits with nobody at it before it closes
ABANDON_AFTER = 30 * 60.0  # with nobody at it this long (a game page polls every few seconds)
KEEP_CLOSED = 7 * 24 * 3600.0  # seconds a closed table keeps its replay
UNLOAD_AFTER = 15 * 60.0  # seconds without a visit before a table leaves memory
SWEEP_EVERY = 60.0
CHAT_CHARS = 400  # the longest word at the table
CHAT_KEPT = 300  # lines a table keeps
CHAT_PAUSE = 1.5  # seconds between two words of the same player


class Seat(BaseModel):
    name: str
    token: str


class ChatLine(BaseModel):
    """A word at the table: to everyone, or to one other player only."""

    n: int  # its number at the table, from 1
    turn: int
    nation: NationId
    name: str  # the player's name
    text: str
    to: NationId | None = None  # a private word to this seat
    at: float


class Chat(BaseModel):
    text: str = Field(min_length=1, max_length=CHAT_CHARS)
    to: NationId | None = None


class TableMeta(BaseModel):
    id: str
    title: str
    seed: int
    max_turns: int
    turn_minutes: float | None = None
    created: float
    seats: dict[NationId, Seat] = Field(default_factory=dict)
    last_active: float = 0.0  # the last time a seated player looked at the table
    closed: str | None = None  # why it closed: "everyone left", "abandoned", "over"
    closed_at: float | None = None
    # the year in progress, so a restart or a deploy loses nothing
    pending: dict[NationId, Orders] = Field(default_factory=dict)
    drafts: dict[NationId, Orders] = Field(default_factory=dict)  # unsent, kept for the clock
    deadline: float | None = None
    first_answer: float | None = None
    chat: list[ChatLine] = Field(default_factory=list)  # the table's talk, the last CHAT_KEPT


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
        self.visited = time.time()

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
            "created": self.meta.created,
            "closed": self.meta.closed,
            "closed_at": self.meta.closed_at,
            "last_active": self.meta.last_active,
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


def abandoned_after(turn_minutes: float | None) -> float:
    """How long a table waits with no player looking at it before it closes: half an hour, or
    two of its years when a year lasts longer (a table playing a year a day waits two days), and
    never more than three days."""
    two_years = 2 * 60 * turn_minutes if turn_minutes else 0.0
    return min(IDLE_CLOSE, max(ABANDON_AFTER, two_years))


def _plain(code: str) -> str:
    """An invitation code as people type it: case, spaces and a stray shell '%' do not count."""
    return "".join(code.split()).rstrip("%").lower()


def _bots(seed: int, nations: list[NationId], humans: list[NationId]) -> dict[NationId, Player]:
    return {n: GreedyBot(seed) for n in nations if n not in humans}


class Lobby:
    """Every table on this server. Only a small summary of each is kept at hand; a table's
    game is read from its save when someone opens it, and let go after a while unvisited."""

    def __init__(self, saves: Path, invite_code: str | None = None) -> None:
        self.saves = saves
        self.invite_code = invite_code
        self.tables: dict[str, Table] = {}  # the tables in memory
        self.summaries: dict[str, dict[str, Any]] = {}  # every table, in brief
        self.seen: dict[str, float] = {}  # the save each table in memory was built from
        self.swept = 0.0
        saves.mkdir(parents=True, exist_ok=True)
        for path in sorted(saves.glob("*.summary.json")):
            try:
                summary = json.loads(path.read_text(encoding="utf-8"))
                self.summaries[summary["id"]] = summary
            except (OSError, ValueError, KeyError):
                continue
        for path in sorted(saves.glob("*.json")):  # tables saved before summaries existed
            fresh = not path.name.endswith(".summary.json") and path.stem not in self.summaries
            if fresh and (table := self._read(path.stem)):
                self._write_summary(table)

    # ------------------------------------------------------------ files

    def _path(self, table_id: str) -> Path:
        return self.saves / f"{table_id}.json"

    def _summary_path(self, table_id: str) -> Path:
        return self.saves / f"{table_id}.summary.json"

    def _session(self, meta: TableMeta, record: GameRecord | None = None) -> Session:
        humans = list(meta.seats)
        names = {n: s.name for n, s in meta.seats.items()}
        seconds = meta.turn_minutes * 60 if meta.turn_minutes else None
        state = record.initial if record else new_game(meta.seed, max_turns=meta.max_turns)
        bots = _bots(meta.seed, list(state.nations), humans)
        if record is not None and record.turns:
            session = Session.resume(record, humans, bots, turn_seconds=seconds, names=names)
        else:
            session = Session(state, humans, bots, turn_seconds=seconds, names=names)
        session.pending = {n: o for n, o in meta.pending.items() if n in humans}
        session.drafts = {n: o for n, o in meta.drafts.items() if n in humans}
        session.first_answer = meta.first_answer
        if meta.deadline is not None:
            session.deadline = meta.deadline
        return session

    def _read(self, table_id: str) -> Table | None:
        path = self._path(table_id)
        try:
            stamp = path.stat().st_mtime
            saved = TableFile.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # a file we cannot read is left alone
        table = Table(saved.meta, self._session(saved.meta, saved.record))
        self.tables[table_id] = table
        self.seen[table_id] = stamp
        self._hook(table)
        return table

    def _hook(self, table: Table) -> None:
        """Save the table's seats, the year in progress and the record together whenever the
        game saves."""
        session = table.session

        def save() -> None:
            meta = table.meta
            meta.pending = dict(session.pending)
            meta.drafts = dict(session.drafts)
            meta.deadline = session.deadline
            meta.first_answer = session.first_answer
            data = TableFile(meta=meta, record=session.record)
            path = self._path(meta.id)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(data.model_dump_json(), encoding="utf-8")
            tmp.replace(path)
            self.seen[meta.id] = path.stat().st_mtime
            self._write_summary(table)

        session.save = save  # type: ignore[method-assign]

    def _write_summary(self, table: Table) -> None:
        summary = table.summary()
        self.summaries[table.meta.id] = summary
        path = self._summary_path(table.meta.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(summary), encoding="utf-8")
        tmp.replace(path)

    def _forget(self, table_id: str) -> None:
        self.tables.pop(table_id, None)
        self.summaries.pop(table_id, None)
        self.seen.pop(table_id, None)
        for path in (self._path(table_id), self._summary_path(table_id)):
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------ the life of a table

    def check_code(self, code: str) -> None:
        codes = [_plain(c) for c in (self.invite_code or "").split(",") if _plain(c)]
        typed = _plain(code).encode()
        if codes and not any([secrets.compare_digest(typed, c.encode()) for c in codes]):
            raise HTTPException(
                403, "wrong invitation code: check it letter by letter (no spaces needed)"
            )

    def open_count(self) -> int:
        return sum(not s.get("closed") for s in self.summaries.values())

    def open_table(self, req: NewTable) -> tuple[Table, str]:
        self.check_code(req.code)
        if not NAME.match(req.name):
            raise HTTPException(422, "a name of letters, digits and spaces, up to 24")
        self.sweep(force=True)
        if self.open_count() >= MAX_TABLES:
            raise HTTPException(429, "this server has enough tables already")
        seed = req.seed if req.seed is not None else secrets.randbelow(1_000_000)
        if req.nation not in new_game(seed).nations:
            raise HTTPException(422, f"no great power called {req.nation!r}")
        now = time.time()
        meta = TableMeta(
            id=secrets.token_urlsafe(6),
            title=req.title.strip() or "A new age",
            seed=seed,
            max_turns=req.years,
            turn_minutes=req.turn_minutes,
            created=now,
            last_active=now,
        )
        token = secrets.token_urlsafe(16)
        meta.seats[req.nation] = Seat(name=req.name, token=token)
        table = Table(meta, self._session(meta))
        self.tables[meta.id] = table
        self._hook(table)
        table.session.save()
        return table, token

    def join(self, table: Table, req: Join) -> str:
        self.check_code(req.code)
        self._open(table)
        if not NAME.match(req.name):
            raise HTTPException(422, "a name of letters, digits and spaces, up to 24")
        state = table.session.state
        if req.nation not in state.nations or not state.nations[req.nation].alive:
            raise HTTPException(422, "no such throne, or it has fallen")
        if req.nation in table.meta.seats:
            raise HTTPException(409, f"{state.nations[req.nation].name} is taken")
        token = secrets.token_urlsafe(16)
        table.meta.seats[req.nation] = Seat(name=req.name, token=token)
        table.meta.last_active = time.time()
        table.session.seat(req.nation, req.name)
        table.session.save()
        return token

    async def leave(self, table: Table, nation: NationId) -> None:
        """A player gives the throne back to a bot; the last one to go closes the table."""
        table.meta.seats.pop(nation, None)
        table.session.unseat(nation, GreedyBot(table.meta.seed))
        if not table.meta.seats:
            self.close(table, "everyone left")
            return
        await table.session.settle()  # perhaps the others were only waiting for this one
        table.session.save()

    def close(self, table: Table, why: str) -> None:
        if table.meta.closed:
            return
        table.meta.closed = why
        table.meta.closed_at = time.time()
        table.session.deadline = None
        table.session.save()

    def _open(self, table: Table) -> None:
        if table.meta.closed:
            raise HTTPException(410, f"this table is closed ({table.meta.closed})")

    def table(self, table_id: str) -> Table:
        """A table, read from its save if it is not in memory, or if another server (during a
        deploy, the old and the new revision overlap) has written it since."""
        path = self._path(table_id)
        try:
            newer = path.stat().st_mtime > self.seen.get(table_id, 0.0)
        except OSError:
            newer = False
        table = self._read(table_id) if newer or table_id not in self.tables else None
        table = table or self.tables.get(table_id)
        if table is None:
            raise HTTPException(404, "no such table")
        table.visited = time.time()
        self.sweep()
        return table

    def seat_of(self, table: Table, token: str | None) -> NationId:
        for nation, seat in table.meta.seats.items():
            if token and secrets.compare_digest(seat.token, token):
                table.meta.last_active = time.time()
                return nation
        raise HTTPException(403, "take a seat at this table first")

    def sweep(self, *, force: bool = False) -> None:
        """Close abandoned and finished tables, delete long-closed ones, and let go of tables
        nobody has visited for a while. At most once a minute unless forced."""
        now = time.time()
        if not force and now - self.swept < SWEEP_EVERY:
            return
        self.swept = now
        for table_id, s in list(self.summaries.items()):
            if not self._summary_path(table_id).exists():  # removed by hand: forget it
                self.tables.pop(table_id, None)
                self.summaries.pop(table_id, None)
                continue
            if s.get("closed") and now - (s.get("closed_at") or now) > KEEP_CLOSED:
                self._forget(table_id)
                continue
            if s.get("closed"):
                continue
            idle = now - max(s.get("last_active") or 0.0, s.get("created") or 0.0)
            table = self.tables.get(table_id)
            if table is not None:
                idle = now - max(table.meta.last_active, table.meta.created)
            if s.get("finished") or idle > abandoned_after(s.get("turn_minutes")):
                table = table or self._read(table_id)
                if table is not None:
                    finished = table.session.state.finished
                    self.close(table, "over" if finished else "everyone left")
        for table_id, table in list(self.tables.items()):
            if now - table.visited > UNLOAD_AFTER and table.session.lock.locked() is False:
                if not table.meta.closed:
                    table.session.save()  # keep when its players last looked
                del self.tables[table_id]


def create_lobby_app(saves: Path, invite_code: str | None = None) -> FastAPI:
    code = invite_code if invite_code is not None else os.environ.get("PAX_INVITE_CODE")
    lobby = Lobby(saves, code)
    powers = [{"id": n.id, "name": n.name, "color": n.color} for n in new_game(1).nations.values()]
    app = FastAPI(title="Pax Agentica tables", docs_url=None, redoc_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=1000)  # a game's view is mostly JSON
    web = files("pax_agentica").joinpath("web")
    static = static_payload(new_game(1), europe_map())
    add_assets(app, static)
    add_feedback(app, saves / "feedback")
    app.state.lobby = lobby

    def playable(table: Table) -> None:
        lobby._open(table)

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return web.joinpath("lobby.html").read_text(encoding="utf-8")

    @app.get("/api/lobby")
    async def tables() -> dict[str, Any]:
        for t in list(lobby.tables.values()):
            if not t.meta.closed and await t.session.tick():
                pass  # a table whose clock ran out moves on, and saves its summary
        lobby.sweep()
        listed = sorted(lobby.summaries.values(), key=lambda s: -(s.get("created") or 0))
        return {"code_required": bool(lobby.invite_code), "powers": powers, "tables": listed}

    class CodeCheck(BaseModel):
        code: str = Field(default="", max_length=100)

    @app.post("/api/code")
    def check(req: CodeCheck) -> dict[str, bool]:
        """Whether an invitation code is right, so the lobby can say so while it is typed."""
        try:
            lobby.check_code(req.code)
        except HTTPException:
            return {"ok": False}
        return {"ok": True}

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
        if table_id not in lobby.summaries:
            return RedirectResponse("/")
        page = web.joinpath("play.html").read_text(encoding="utf-8")
        boot = f'<script>window.PAX_TABLE = "{table_id}";</script>'
        return page.replace("<head>", "<head>" + boot, 1)

    @app.get("/api/t/{table_id}/static")
    def table_static(table_id: str) -> dict[str, Any]:
        if table_id not in lobby.summaries:
            raise HTTPException(404, "no such table")
        return static

    @app.get("/api/t/{table_id}/game")
    async def game(table_id: str, x_seat: str | None = Header(default=None)) -> dict[str, Any]:
        table = lobby.table(table_id)
        nation = lobby.seat_of(table, x_seat)
        if not table.meta.closed:
            await table.session.tick()
        return table.session.payload(nation) | {"table": table.summary()}

    @app.get("/api/t/{table_id}/status")
    async def status(table_id: str, x_seat: str | None = Header(default=None)) -> dict[str, Any]:
        table = lobby.table(table_id)
        nation = lobby.seat_of(table, x_seat)
        session = table.session
        if not table.meta.closed:
            await session.tick()
        left = session.deadline - time.time() if session.deadline is not None else None
        return {
            "turn": session.state.turn,
            "finished": session.state.finished,
            "closed": table.meta.closed,
            "submitted": nation in session.pending,
            "waiting_for": session.waiting_for(),
            "seconds_left": max(0, round(left)) if left is not None else None,
            "force_in": session.force_in(nation),
            "chat": max((c.n for c in heard(table, nation)), default=0),
        }

    def heard(table: Table, nation: NationId) -> list[ChatLine]:
        """The lines a seat may read: every public one, and the private ones to or from it."""
        return [c for c in table.meta.chat if c.to is None or nation in (c.to, c.nation)]

    @app.get("/api/t/{table_id}/chat")
    def chat(table_id: str, after: int = 0, x_seat: str | None = Header(default=None)) -> Any:
        table = lobby.table(table_id)
        nation = lobby.seat_of(table, x_seat)
        return {"lines": [c.model_dump() for c in heard(table, nation) if c.n > after]}

    @app.post("/api/t/{table_id}/chat")
    def say(table_id: str, req: Chat, x_seat: str | None = Header(default=None)) -> Any:
        """Speak at the table, to all or to one player. Bots do not listen: write them letters."""
        table = lobby.table(table_id)
        nation = lobby.seat_of(table, x_seat)
        playable(table)
        text = " ".join(req.text.split())
        if not text:
            raise HTTPException(422, "say something")
        if req.to is not None and (req.to == nation or req.to not in table.meta.seats):
            raise HTTPException(422, "only another player at this table can be spoken to alone")
        now = time.time()
        mine = [c for c in table.meta.chat if c.nation == nation]
        if mine and now - mine[-1].at < CHAT_PAUSE:
            raise HTTPException(429, "a moment: let the others answer")
        line = ChatLine(
            n=(table.meta.chat[-1].n if table.meta.chat else 0) + 1,
            turn=table.session.state.turn,
            nation=nation,
            name=table.meta.seats[nation].name,
            text=text,
            to=req.to,
            at=now,
        )
        table.meta.chat = [*table.meta.chat, line][-CHAT_KEPT:]
        table.session.save()
        return {"line": line.model_dump()}

    @app.post("/api/t/{table_id}/turn")
    async def turn(
        table_id: str, orders: Orders, x_seat: str | None = Header(default=None)
    ) -> dict[str, Any]:
        table = lobby.table(table_id)
        nation = lobby.seat_of(table, x_seat)
        playable(table)
        await table.session.submit(nation, orders)
        return table.session.payload(nation) | {"table": table.summary()}

    @app.post("/api/t/{table_id}/draft")
    async def draft(
        table_id: str, orders: Orders, x_seat: str | None = Header(default=None)
    ) -> dict[str, bool]:
        """The orders a player is still working on: carried out if the year ends without them.
        Kept in memory (and saved with the table's next save), so drafting costs no write."""
        table = lobby.table(table_id)
        nation = lobby.seat_of(table, x_seat)
        playable(table)
        table.session.draft(nation, orders)
        return {"ok": True}

    @app.post("/api/t/{table_id}/force")
    async def force(table_id: str, x_seat: str | None = Header(default=None)) -> dict[str, Any]:
        """End the year without the players who have not answered, once patience runs out."""
        table = lobby.table(table_id)
        nation = lobby.seat_of(table, x_seat)
        playable(table)
        if not await table.session.force(nation):
            raise HTTPException(409, "not yet: give the others a little more time")
        return table.session.payload(nation) | {"table": table.summary()}

    @app.post("/api/t/{table_id}/leave")
    async def leave(table_id: str, x_seat: str | None = Header(default=None)) -> dict[str, Any]:
        """Give your throne back to a bot. When the last player leaves, the table closes."""
        table = lobby.table(table_id)
        nation = lobby.seat_of(table, x_seat)
        playable(table)
        await lobby.leave(table, nation)
        return {"left": nation, "closed": table.meta.closed}

    @app.get("/t/{table_id}/replay", response_class=HTMLResponse)
    def replay(table_id: str) -> str:
        table = lobby.table(table_id)
        if not table.session.record.turns:
            raise HTTPException(404, "no year was played at this table")
        if not (table.session.state.finished or table.meta.closed):
            raise HTTPException(403, "the replay opens when the game is over")
        return render_html(table.session.record)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
