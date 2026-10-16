# Tools for a ruler

What the game gives an AI ruler besides its `NationView`. Everything lives in
[`tools.py`](../src/pax_agentica/tools.py) and is a pure function of the view, so no tool can
see through the fog of war; the numbers follow the engine's own rules.

## The briefing

`briefing(view)` turns the view (a large JSON document) into a page of plain text for a prompt:
the treasury and what it does a year, stability, prestige and taxes, the wars and their war
score, borders where the ruler is outnumbered, its provinces, its open missions with their
progress, decisions and proposals waiting for an answer, every court with its standing and its
opinion, last year's letters and proclamations, and the market.

```bash
uv run pax brief france --seed 1
```

## Calculators

| Tool | Answers |
|---|---|
| `battle_odds(view, origin, target, army=None)` | the chance an attack wins (None if the defenders are hidden) |
| `targets(view, origin)` | where the regiments of a province can march or attack, with the odds of each attack |
| `work_gain(view, province, work)` | what developing, improving the workings or a building would add a year, and its cost |
| `market_quote(view, resource, amount)` | what buying or selling costs or brings today |

For a language model's tool calling, `TOOL_SPECS` describes them as JSON-schema functions and
`call_tool(view, name, args)` answers a call with a small dict, or `{"error": ...}` for the model
to read and correct.

## Tournaments

```bash
uv run pax tournament --games 20 --player spain=random
```

Plays many seeds with mixed rulers and prints, per nation, its ruler, wins, average standing,
survival and missions fulfilled. A new kind of ruler only needs to be a `Player` (see
[ADR 0002](adr/0002-who-writes-what.md)) and an entry in the CLI's `BOTS`.

## Playing against people

[Multiplayer tables](multiplayer.md) let friends play the same game in their browsers, each on a
throne, with bots on the rest: the same views and orders, before any AI ruler takes a seat.
