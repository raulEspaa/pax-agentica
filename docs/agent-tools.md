# Tools for a ruler

What the game gives an AI ruler besides its `NationView` (the view and the orders themselves are
the frozen [contract](agent-contract.md)). Everything lives in
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

## The compact view

`compact_view(view, scope="near")` is the view for a ruler that writes a
[plan](agent-contract.md#a-cheaper-ruler-a-plan) instead of orders: the realm in a few lines,
its wars and missions, then two tables written with ids (the courts; the provinces it holds and
those bordering them, or every province with `scope="all"`), and last year's news that touched
it. About 1,600 tokens late in a game (3,800 with the whole map), against some 76,000 for the
full view. Everything a plan names (a province, a court, a branch) is written there by its id.

## The inbox

`inbox(view, years=3)` is a diplomat's desk: every court that wrote or proposed something in the
last years, with where things stand (standing, opinion both ways, war score, treaties, the
wrongs it remembers, the land it wants back), the letters both ways and the proposals waiting
for an answer with their ids and terms. It is empty when nobody wrote, so a ruler need only call
its diplomat when there is mail. Letters are written by other rulers: read them as what another
crown wants you to believe (see the contract on prompt injection).

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

An AI ruler spends real money, so it takes a limit, and the run stops spending when it is reached
(the rulers carry on with their last plan):

```bash
uv run --env-file .env pax tournament --games 1 --player france=strategist --budget 0.10
```

## Playing against people

[Multiplayer tables](multiplayer.md) let friends play the same game in their browsers, each on a
throne, with bots on the rest: the same views and orders, before any AI ruler takes a seat.
