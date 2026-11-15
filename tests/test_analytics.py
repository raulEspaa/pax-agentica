"""Analytics events (spec 009): rows that fit the BigQuery schemas, written without ever failing
a request, and local game records exported as the same rows."""

import asyncio
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from pax_agentica.analytics import (
    KINDS,
    Analytics,
    AudienceRow,
    export_games,
    game_row,
)
from pax_agentica.cli import main
from pax_agentica.engine import new_game
from pax_agentica.multiplayer import create_lobby_app
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.random_bot import RandomBot
from pax_agentica.runner import GameRecord, run_game

type FitsSchema = Callable[[dict[str, Any], str], None]  # the fixtures of conftest.py
type NdjsonRows = Callable[[Path, str], list[dict[str, Any]]]

SCHEMAS = Path(__file__).parent.parent / "scripts" / "bigquery"


def schema(kind: str) -> list[dict[str, Any]]:
    return json.loads((SCHEMAS / f"{kind}.json").read_text())  # type: ignore[no-any-return]


@pytest.mark.parametrize(("model", "kind"), list(KINDS.items()))
def test_every_row_field_is_declared_in_its_schema_and_back(
    model: type[BaseModel], kind: str
) -> None:
    def names(fields: list[dict[str, Any]]) -> set[str]:
        return {f["name"] for f in fields}

    assert set(model.model_fields) == names(schema(kind))
    if kind == "games":
        standings = next(f for f in schema(kind) if f["name"] == "standings")
        from pax_agentica.analytics import Standing

        assert set(Standing.model_fields) == names(standings["fields"])


def finished_record(seed: int = 4, turns: int = 6) -> GameRecord:
    state = new_game(seed, max_turns=turns)
    players = {n: GreedyBot(seed) for n in state.nations} | {"france": RandomBot(seed)}
    return asyncio.run(run_game(state, players))


def test_a_game_row_fits_the_schema_and_tells_rulers_by_kind_only(fits_schema: FitsSchema) -> None:
    record = finished_record()
    record.players["spain"] = "Anne"  # a human's name stays out of analytics
    row = game_row(record, source="local", table_id="t1", ai=["england"])
    fits_schema(json.loads(row.model_dump_json()), "games")
    rulers = {s.nation: s.ruler for s in row.standings}
    assert rulers["spain"] == "human"
    assert rulers["france"] == "random"
    assert row.human_nations == ["spain"]
    assert row.years_played == 6
    assert row.finished
    assert row.winner == record.winner
    assert "Anne" not in row.model_dump_json()


def test_rows_are_appended_one_file_per_table_day_and_writer(
    tmp_path: Path, fits_schema: FitsSchema, ndjson_rows: NdjsonRows
) -> None:
    sink = Analytics(tmp_path, writer="rev-1")
    row = AudienceRow(
        at="2026-11-15 10:00:00+00:00",
        source="tables",
        table_id="abc",
        nation="france",
        turn=1,
        year=1500,
        model="fake",
        cost_usd=0.001,
        model_calls=1,
        latency_s=0.5,
    )
    assert sink.emit(row)
    assert sink.emit(row)
    files = list((tmp_path / "audience").glob("dt=*/abc.rev-1.ndjson"))
    assert len(files) == 1
    assert len(files[0].read_text().splitlines()) == 2
    fits_schema(ndjson_rows(tmp_path, "audience")[0], "audience")
    assert Analytics(tmp_path).writer != Analytics(tmp_path).writer  # two processes, two files


def test_a_row_that_cannot_be_written_is_only_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocked = tmp_path / "analytics"
    blocked.write_text("a file where the folder should be")
    row = game_row(finished_record(turns=2), source="tables", table_id="x")
    assert Analytics(blocked).emit(row) is False
    assert "could not write" in caplog.text


def test_a_closed_table_writes_its_games_row(
    tmp_path: Path, fits_schema: FitsSchema, ndjson_rows: NdjsonRows
) -> None:
    client = TestClient(create_lobby_app(tmp_path, invite_code=""))
    opened = client.post(
        "/api/tables", json={"name": "Anne", "nation": "france", "seed": 3, "years": 5}
    ).json()
    seat = {"X-Seat": opened["token"]}
    for _ in range(2):
        client.post(f"/api/t/{opened['table']}/turn", json={"actions": []}, headers=seat)
    client.post(f"/api/t/{opened['table']}/leave", headers=seat)
    [row] = ndjson_rows(tmp_path / "analytics", "games")
    fits_schema(row, "games")
    assert row["table_id"] == opened["table"]
    assert row["closed_reason"] == "everyone left"
    assert row["years_played"] == 2
    assert row["humans"] == 1
    assert row["human_nations"] == ["france"]
    assert row["ai_cost_usd"] is None  # no AI at this table
    assert row["source"] == "tables"


def test_a_table_closes_even_when_analytics_cannot_be_written(tmp_path: Path) -> None:
    (tmp_path / "analytics").write_text("not a folder")
    client = TestClient(create_lobby_app(tmp_path, invite_code=""))
    opened = client.post("/api/tables", json={"name": "Anne", "nation": "france"}).json()
    seat = {"X-Seat": opened["token"]}
    r = client.post(f"/api/t/{opened['table']}/leave", headers=seat)
    assert r.status_code == 200
    assert r.json()["closed"] == "everyone left"


def test_export_turns_records_and_table_saves_into_game_rows(
    tmp_path: Path, fits_schema: FitsSchema
) -> None:
    record = tmp_path / "seed-4.json"
    record.write_text(finished_record().model_dump_json())
    saves = tmp_path / "tables"
    client = TestClient(create_lobby_app(saves, invite_code=""))
    opened = client.post("/api/tables", json={"name": "Anne", "nation": "france"}).json()
    client.post(f"/api/t/{opened['table']}/leave", headers={"X-Seat": opened["token"]})
    out = tmp_path / "out"
    assert main(["analytics", "export", str(record), str(saves / f"{opened['table']}.json"),
                 "--out", str(out)]) == 0  # fmt: skip
    rows = [json.loads(line) for line in (out / "games.ndjson").read_text().splitlines()]
    assert [r["table_id"] for r in rows] == ["seed-4", opened["table"]]
    for row in rows:
        fits_schema(row, "games")
        assert row["source"] == "local"
    assert rows[1]["closed_reason"] == "everyone left"
    assert export_games([], tmp_path / "empty") == 0


def test_tournament_can_save_its_records_for_export(tmp_path: Path) -> None:
    args = ["tournament", "--games", "2", "--turns", "3", "--save", str(tmp_path)]
    assert main(args) == 0
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["seed-0.json", "seed-1.json"]


def test_the_ddl_has_one_partitioned_external_table_per_kind() -> None:
    script = SCHEMAS.parent / "bigquery_ddl.py"
    args = ["--project", "p", "--bucket", "b"]
    out = subprocess.run(  # noqa: S603
        [sys.executable, str(script), *args], capture_output=True, text=True, check=True
    ).stdout
    for kind in KINDS.values():
        assert f"CREATE OR REPLACE EXTERNAL TABLE `p.pax_analytics.{kind}`" in out
        assert f"hive_partition_uri_prefix = 'gs://b/analytics/{kind}'" in out
    assert out.count("WITH PARTITION COLUMNS (dt DATE)") == len(KINDS)
    assert "standings ARRAY<STRUCT<nation STRING" in out
    assert "failures ARRAY<STRING>" in out
