"""Analytics events: what happened at the tables, as newline-delimited JSON for BigQuery.

The tables server appends one JSON object per line under its saves directory, which on Cloud Run
is the mounted bucket, so BigQuery reads the files where they lie (external tables, see
docs/analytics.md and scripts/bigquery/):

    <saves>/analytics/<kind>/dt=YYYY-MM-DD/<table>.<writer>.ndjson

`dt` is the Hive-style partition, so a query on a few days reads a few folders. One file per
table, day and server process: GCS objects cannot be appended to, so the mount rewrites a file on
every append, and small files keep that cheap; the writer's id keeps two revisions running side
by side during a deploy from overwriting each other's rows.

Writing never fails a request or a year: an error is logged and the row is lost. No personal data:
a ruler is recorded by kind ("human", "council", a bot's name), never by the name a player typed.
"""

import json
import logging
import os
import re
import secrets
import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from pax_agentica.engine import NationId
from pax_agentica.runner import GameRecord

log = logging.getLogger(__name__)

AI_RULERS = frozenset({"council", "strategist"})  # rulers that call a model
BOT_RULERS = frozenset({"greedy", "random", "steady", "random-plan"})
HUMAN = "human"


class Standing(BaseModel):
    """One crown at the end of a game."""

    nation: NationId
    ruler: str  # "human", "council", "strategist" or a bot's name
    standing: int  # what wins when time runs out
    score: int
    alive: bool
    provinces: int


class GameRow(BaseModel):
    """`games`: one row when a table closes, or per local game exported."""

    source: str  # "tables" (the public server) or "local" (pax analytics export)
    table_id: str
    seed: int
    started_at: str | None  # timestamps as "YYYY-MM-DD HH:MM:SS.ffffff+00:00"
    ended_at: str
    closed_reason: str | None  # "everyone left", "over"; None for a local game
    years_played: int
    max_years: int
    finished: bool
    winner: NationId | None
    humans: int
    human_nations: list[NationId] = Field(default_factory=list)
    ai_nations: list[NationId] = Field(default_factory=list)
    ai_cost_usd: float | None  # what the table's councils spent, if known
    standings: list[Standing] = Field(default_factory=list)


class DecisionRow(BaseModel):
    """`decisions`: one row per AI council decision (a crown's orders for a year)."""

    at: str
    source: str
    table_id: str
    nation: NationId
    turn: int
    year: int
    model: str
    cost_usd: float  # the real cost of this decision's calls, retries and failures included
    model_calls: int
    latency_s: float  # from starting to think to the orders; the humans' year hides most of it
    plan_asked: bool
    plan_written: bool
    diplomacy_asked: bool
    diplomacy_written: bool
    letters: int
    failures: list[str] = Field(default_factory=list)  # "plan:TimeoutError", per failed try
    timed_out: bool
    fallback: bool  # something asked for never came: the last plan or the bot stood in
    error: str | None = None  # the decision itself failed, and the crown did nothing that year


class AudienceRow(BaseModel):
    """`audience`: one row per AI reply in a chat with a human (wired by the audience feature)."""

    at: str
    source: str
    table_id: str
    nation: NationId
    turn: int
    year: int
    model: str
    cost_usd: float
    model_calls: int
    latency_s: float
    error: str | None = None


type Row = GameRow | DecisionRow | AudienceRow

KINDS: dict[type[BaseModel], str] = {
    GameRow: "games",
    DecisionRow: "decisions",
    AudienceRow: "audience",
}


def timestamp(seconds: float | None = None) -> str:
    """A UTC time as BigQuery's JSON loader reads a TIMESTAMP."""
    moment = datetime.now(UTC) if seconds is None else datetime.fromtimestamp(seconds, UTC)
    return moment.isoformat(sep=" ")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)[:64] or "_"


class Analytics:
    """Appends event rows to NDJSON files under `root`. Safe to call from several threads."""

    def __init__(self, root: Path, writer: str | None = None, source: str = "tables") -> None:
        self.root = root
        revision = os.environ.get("K_REVISION", "local")  # Cloud Run names its revision
        self.writer = _safe(writer or f"{revision}-{secrets.token_hex(3)}")
        self.source = source
        self._lock = threading.Lock()

    def path(self, row: Row, day: str | None = None) -> Path:
        day = day or datetime.now(UTC).date().isoformat()
        name = f"{_safe(row.table_id)}.{self.writer}.ndjson"
        return self.root / KINDS[type(row)] / f"dt={day}" / name

    def emit(self, row: Row) -> bool:
        """Append the row; False (and a log line) if it could not be written."""
        try:
            line = row.model_dump_json() + "\n"
            path = self.path(row)
            with self._lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as out:
                    out.write(line)
            return True
        except Exception:
            log.exception("analytics: could not write a %s row", type(row).__name__)
            return False


# ---------------------------------------------------------------- games


def ruler_kind(player: str) -> str:
    """What ruled a crown, from its name in the record: a bot's or a model's name is kept, and
    any other name is a human's, recorded only as "human"."""
    return player if player in AI_RULERS | BOT_RULERS else HUMAN


def game_row(
    record: GameRecord,
    *,
    source: str,
    table_id: str,
    ended_at: float | None = None,
    started_at: float | None = None,
    closed_reason: str | None = None,
    humans: Iterable[NationId] | None = None,
    ai: Iterable[NationId] | None = None,
    ai_cost_usd: float | None = None,
) -> GameRow:
    """A `games` row from a game's record. Without `humans` and `ai` (a local record), the
    rulers are told apart by the names in `record.players`."""
    players: Mapping[NationId, str] = record.players
    if humans is None:
        humans = [n for n, p in players.items() if p not in AI_RULERS | BOT_RULERS]
    if ai is None:
        ai = [n for n, p in players.items() if p in AI_RULERS]
    humans, ai = sorted(set(humans)), sorted(set(ai) - set(humans))
    final = record.turns[-1].after if record.turns else record.start
    standings = [
        Standing(
            nation=nation,
            ruler=ruler_kind(players.get(nation, "")),
            standing=s.standing,
            score=s.score,
            alive=s.alive,
            provinces=s.provinces,
        )
        for nation, s in sorted(final.nations.items(), key=lambda kv: (-kv[1].standing, kv[0]))
    ]
    return GameRow(
        source=source,
        table_id=table_id,
        seed=record.initial.seed,
        started_at=timestamp(started_at) if started_at is not None else None,
        ended_at=timestamp(ended_at),
        closed_reason=closed_reason,
        years_played=len(record.turns),
        max_years=record.initial.max_turns,
        finished=record.winner is not None,
        winner=record.winner,
        humans=len(humans),
        human_nations=humans,
        ai_nations=ai,
        ai_cost_usd=ai_cost_usd,
        standings=standings,
    )


def export_games(paths: Iterable[Path], out: Path) -> int:
    """Write `out/games.ndjson` from local game records and table saves; return the rows."""
    rows = [_local_game(path) for path in paths]
    out.mkdir(parents=True, exist_ok=True)
    text = "".join(row.model_dump_json() + "\n" for row in rows)
    (out / "games.ndjson").write_text(text, encoding="utf-8")
    return len(rows)


def _local_game(path: Path) -> GameRow:
    """A game record (`pax play --save`, `pax tournament --save`) or a table's save."""
    from pax_agentica.multiplayer import TableFile  # the lobby's types, only for its saves

    data = json.loads(path.read_text(encoding="utf-8"))
    ended = path.stat().st_mtime
    if isinstance(data, dict) and "meta" in data:
        saved = TableFile.model_validate(data)
        meta = saved.meta
        return game_row(
            saved.record,
            source="local",
            table_id=meta.id,
            started_at=meta.created,
            ended_at=meta.closed_at or ended,
            closed_reason=meta.closed,
            humans=meta.humans_ever or list(meta.seats),
            ai=meta.ai,
            ai_cost_usd=meta.ai_spent_usd,
        )
    record = GameRecord.model_validate(data)
    return game_row(record, source="local", table_id=path.stem, ended_at=ended)
