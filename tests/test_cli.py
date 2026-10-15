import json
from pathlib import Path

import pytest

from pax_agentica.cli import main
from pax_agentica.runner import GameRecord


def test_play_prints_the_final_standings(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["play", "--seed", "3", "--turns", "5"]) == 0
    out = capsys.readouterr().out
    assert "nation" in out
    assert "wins" in out


def test_play_can_save_the_record_and_a_replay(tmp_path: Path) -> None:
    record, replay = tmp_path / "game.json", tmp_path / "replays" / "game.html"  # folder is created
    args = ["play", "--seed", "2", "--turns", "4", "--quiet", "--save", str(record)]
    assert main([*args, "--html", str(replay), "--player", "france=random"]) == 0
    saved = GameRecord.model_validate_json(record.read_text())
    assert saved.players["france"] == "random"
    assert len(saved.turns) == 4
    assert "<svg" in replay.read_text()


def test_view_prints_one_nations_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["view", "sweden"]) == 0
    assert json.loads(capsys.readouterr().out)["me"]["id"] == "sweden"
    assert main(["view", "atlantis"]) == 2


def test_schema_prints_the_orders_schema(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema"]) == 0
    assert "actions" in json.loads(capsys.readouterr().out)["properties"]


def test_map_and_bench_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["map"]) == 0
    assert main(["bench", "--games", "2", "--turns", "10"]) == 0
    assert "2 games" in capsys.readouterr().out
