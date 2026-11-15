"""A nation's view over MCP (spec 007): the same tools as tools.py, one seat, one view."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp_types import CallToolResult, TextContent

from pax_agentica.cli import main
from pax_agentica.engine import NationView, new_game, view_for
from pax_agentica.mcp_server import build_server
from pax_agentica.multiplayer import create_lobby_app
from pax_agentica.tools import TOOL_SPECS, briefing, call_tool, compact_view, inbox

PAGES = ["briefing", "compact_view", "inbox"]
CALCULATORS = [spec["name"] for spec in TOOL_SPECS]


@pytest.fixture(scope="module")
def view() -> NationView:
    return view_for(new_game(3), "france")


def text(result: CallToolResult) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def _listed(view: NationView) -> dict[str, Any]:
    async with Client(build_server(lambda _ctx: view)) as client:
        return {t.name: t for t in (await client.list_tools()).tools}


async def _calls(view: NationView, calls: list[tuple[str, dict[str, Any]]]) -> list[CallToolResult]:
    async with Client(build_server(lambda _ctx: view)) as client:
        return [await client.call_tool(name, args) for name, args in calls]


# ---------------------------------------------------------------- the tools


def test_the_server_lists_the_pages_and_the_calculators_as_read_only(view: NationView) -> None:
    tools = asyncio.run(_listed(view))
    assert sorted(tools) == sorted(PAGES + CALCULATORS)
    for tool in tools.values():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False
    for spec in TOOL_SPECS:  # the schemas written for models, not a copy of them
        assert tools[spec["name"]].input_schema == spec["parameters"]
        assert tools[spec["name"]].description == spec["description"]


def test_the_pages_are_the_text_tools_py_writes(view: NationView) -> None:
    got = asyncio.run(
        _calls(view, [("briefing", {}), ("compact_view", {"scope": "all"}), ("inbox", {})])
    )
    assert [text(r) for r in got] == [
        briefing(view),
        compact_view(view, "all"),
        inbox(view) or "(nobody wrote)",
    ]
    assert not any(r.is_error for r in got)


def test_the_calculators_answer_as_call_tool_does(view: NationView) -> None:
    calls: list[tuple[str, dict[str, Any]]] = [
        ("targets", {"origin": "paris"}),
        ("battle_odds", {"origin": "paris", "target": "flanders"}),
        ("market_quote", {"resource": "iron", "amount": 5}),
        ("work_gain", {"province": "paris", "work": "develop"}),
    ]
    for (name, args), result in zip(calls, asyncio.run(_calls(view, calls)), strict=True):
        expected = call_tool(view, name, args)
        assert json.loads(text(result)) == expected
        assert result.structured_content == expected
        assert not result.is_error


def test_a_bad_call_comes_back_as_a_tool_error(view: NationView) -> None:
    calls: list[tuple[str, dict[str, Any]]] = [
        ("targets", {"origin": "atlantis"}),
        ("compact_view", {"scope": "everything"}),
        ("no_such_tool", {}),
    ]
    assert all(r.is_error for r in asyncio.run(_calls(view, calls)))


# ---------------------------------------------------------------- pax mcp, over stdio


def test_pax_mcp_serves_a_nation_over_stdio() -> None:
    command = [sys.executable, "-m", "pax_agentica.cli", "mcp", "spain", "--seed", "3"]

    async def ask() -> tuple[list[str], str]:
        params = StdioServerParameters(command=command[0], args=command[1:])
        async with Client(params) as client:
            names = [t.name for t in (await client.list_tools()).tools]
            return names, text(await client.call_tool("briefing", {}))

    names, page = asyncio.run(ask())
    assert sorted(names) == sorted(PAGES + CALCULATORS)
    assert page == briefing(view_for(new_game(3), "spain"))


def test_pax_mcp_refuses_an_unknown_nation(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["mcp", "atlantis"]) == 2
    assert "unknown nation" in capsys.readouterr().err


# ---------------------------------------------------------------- /mcp on the tables

ACCEPT = {"Accept": "application/json, text/event-stream"}


def rpc(client: TestClient, method: str, headers: dict[str, str], **params: Any) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return client.post("/mcp", json=body, headers=ACCEPT | headers)


@pytest.fixture
def tables(tmp_path: Path) -> Any:
    with TestClient(create_lobby_app(tmp_path, invite_code="")) as client:  # runs the lifespan
        yield client


def seats(client: TestClient) -> tuple[str, str, str]:
    """A table with Anne as France and Pedro as Spain: (table, Anne's token, Pedro's token)."""
    body = {"name": "Anne", "nation": "france", "seed": 3, "years": 10}
    opened = client.post("/api/tables", json=body).json()
    table = opened["table"]
    joined = client.post(f"/api/t/{table}/join", json={"name": "Pedro", "nation": "spain"})
    return table, opened["token"], joined.json()["token"]


def test_each_seat_reads_its_own_nation_over_http(tables: TestClient) -> None:
    table, anne, pedro = seats(tables)
    state = new_game(3, max_turns=10)
    pages = {}
    for nation, headers in {
        "france": {"X-Table": table, "X-Seat": anne},
        "spain": {"X-Table": table, "Authorization": f"Bearer {pedro}"},
    }.items():
        r = rpc(tables, "tools/call", headers, name="briefing", arguments={})
        assert r.status_code == 200, r.text
        assert "mcp-session-id" not in r.headers  # stateless: nothing kept between requests
        pages[nation] = r.json()["result"]["content"][0]["text"]
        assert pages[nation] == briefing(view_for(state, nation))
    assert pages["france"] != pages["spain"]


def test_the_tables_list_tools_without_a_handshake(tables: TestClient) -> None:
    table, anne, _ = seats(tables)
    r = rpc(tables, "tools/list", {"X-Table": table, "X-Seat": anne})
    assert r.status_code == 200, r.text
    assert sorted(t["name"] for t in r.json()["result"]["tools"]) == sorted(PAGES + CALCULATORS)


def test_the_tables_refuse_a_missing_or_wrong_seat(tables: TestClient) -> None:
    table, anne, _ = seats(tables)
    no_token = rpc(tables, "tools/list", {"X-Table": table})
    assert no_token.status_code == 401
    assert no_token.headers["www-authenticate"] == "Bearer"
    assert rpc(tables, "tools/list", {"X-Table": table, "X-Seat": "guess"}).status_code == 403
    assert rpc(tables, "tools/list", {"X-Table": "nowhere", "X-Seat": anne}).status_code == 404
    assert rpc(tables, "tools/list", {"X-Seat": anne}).status_code == 404
    escape = {"X-Table": f"../{table}", "X-Seat": anne}  # a header could hold a path
    assert rpc(tables, "tools/list", escape).status_code == 404
    basic = {"X-Table": table, "Authorization": f"Basic {anne}"}
    assert rpc(tables, "tools/list", basic).status_code == 401
