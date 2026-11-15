# 007 · A nation's view over MCP

- **Status:** Done
- **Milestone:** AI roadmap, phase 7 (reduced: the MCP server, without the evaluation of tools)

## Why

The rulers' tools (`tools.py`) only reach a model that this repo calls itself. The Model Context
Protocol is the standard way for any agent (Claude Code, Claude Desktop, an IDE, someone else's
framework) to discover and call tools. Serving the same tools over MCP lets any MCP client read a
nation's situation, from a local game or from a seat at a public table, without a line of glue,
and with the same fog of war as the rulers.

## What

One MCP server, built on the official SDK's low-level `Server`, with seven read-only tools, each
computed from **one** `NationView` and never from `GameState`:

| Tool | From | Returns |
|---|---|---|
| `briefing` | `tools.briefing` | a page of text |
| `compact_view` | `tools.compact_view` (`scope`: near or all) | a page of text |
| `inbox` | `tools.inbox` (`years`) | a page of text |
| `battle_odds`, `targets`, `work_gain`, `market_quote` | `TOOL_SPECS` + `call_tool` | JSON, also as structured content |

The calculators' input schemas are `TOOL_SPECS` itself, not a copy. Two ways to reach it:

- **Local, stdio:** `pax mcp france --seed 1 [--turn N | --game record.json]` serves a nation of a
  fresh game (optionally played by bots up to a year, as `pax brief`) or of a game saved with
  `pax play --save`.
- **The public tables, Streamable HTTP:** `POST /mcp` on the tables server. The table is named by
  the `X-Table` header and the seat by its token, in `X-Seat` or `Authorization: Bearer`. The
  transport is stateless (JSON responses, no MCP session kept): each request is authenticated on
  its own, and the server keeps nothing new.

### Decisions

- **The low-level `Server`, not `MCPServer` (formerly FastMCP).** `MCPServer` builds a tool's
  schema from a Python signature; the calculators already have a JSON schema written for models,
  so the low-level server lists them as they are and one handler dispatches to `call_tool`.
- **The SDK goes in the main dependencies**, not the `council` group: the server is part of the
  game's interface (no model, no AI), `pax mcp` must work in any install, and the tables image gets
  it either way. Its own dependencies are mostly already there (Starlette, uvicorn, pydantic,
  anyio); it adds a few MB to the image.
- **Read-only.** No `submit_orders`: it would be easy to route through `Session.submit`, but a
  read-only server cannot change a game, so a leaked token or a confused agent can only read.
  Orders keep going through `POST /api/t/{table}/turn`.
- **Stateless HTTP.** No session to keep or expire, any Cloud Run instance can answer, and no
  memory grows with clients.

## Acceptance criteria

1. **Given** a nation's view, **when** an MCP client calls `briefing`, `compact_view` or `inbox`,
   **then** it gets exactly the text `tools.py` writes for that view.
2. **Given** a calculator call, **then** the answer is `call_tool`'s dict, as JSON text and as
   structured content; an answer with an `error` is marked as a tool error.
3. **Given** a client, **when** it lists the tools, **then** it gets the seven tools, all marked
   read-only, and each calculator's input schema is its `TOOL_SPECS` entry.
4. **Given** `pax mcp`, **then** it serves the nation over stdio, from a seed, a year played by
   bots or a saved game; an unknown nation is refused before serving.
5. **Given** the tables server, **when** a request to `/mcp` has no seat token, **then** it is
   refused with 401; a wrong token with 403; a missing or unknown table with 404.
6. **Given** two players at one table, **when** each asks for its briefing over `/mcp`, **then**
   each reads its own nation, and nothing a call can pass names another one.
7. **Given** the tables server, **then** `/mcp` answers a `tools/list` without an `initialize`
   first and keeps no session (no `Mcp-Session-Id`).

## Out of scope

- Writing over MCP (`submit_orders`, letters, chat).
- OAuth: the seat token is the credential, as it is for the web page.
- MCP resources and prompts; the full `NationView` as a tool (some 76,000 tokens late in a game).
- Measuring whether rulers play better with tools (the other half of roadmap phase 7).
