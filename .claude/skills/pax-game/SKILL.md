---
name: pax-game
description: Run, inspect, debug or change the Pax Agentica game (engine, map, rules, bots, CLI, replay viewer). Use when asked to play or simulate games, look at what a nation sees, balance the rules, add an action or event, or check that a change keeps the engine deterministic and pure.
---

# Working on the Pax Agentica game

The game is the arena for the AI rulers. It is owned by the assistant (see `CLAUDE.md`), so
changes here are allowed. Keep them small, tested and documented.

## Map of the code

| File | What lives there |
|---|---|
| `src/pax_agentica/engine/model.py` | `GameState`, `Rules` (every number), resources, treaties |
| `src/pax_agentica/engine/scenario.py` | the Europe 1500 map: provinces, borders, straits, nations |
| `src/pax_agentica/engine/actions.py` | the `Orders` / action union: the only input a ruler has |
| `src/pax_agentica/engine/resolve.py` | `resolve_turn`: the phases, validation and every rule |
| `src/pax_agentica/engine/view.py` | fog of war: `view_for(state, nation) -> NationView` |
| `src/pax_agentica/engine/events.py` | `Event` / `EventKind`: what happened and who may see it |
| `src/pax_agentica/players/` | the `Player` protocol, `RandomBot` and `GreedyBot` |
| `src/pax_agentica/runner.py` | async game loop, timeouts, `GameRecord` |
| `src/pax_agentica/web/map.js`, `map.css` | the map drawing shared by the replay and the play page |
| `src/pax_agentica/viewer.py` + `web/replay.html` | the self-contained HTML replay |
| `src/pax_agentica/server.py` + `web/play.html`, `play.js` | `pax serve`: a human plays one nation through its `NationView` |
| `scripts/build_map.py` → `src/pax_agentica/data/europe_1500.json` | the drawn map: Natural Earth regions merged into provinces (`make map`) |
| `docs/game-rules.md` | the rules in prose; keep it in sync with `Rules` and `resolve.py` |

## Look before you change

```bash
uv run pax play --seed 1 --verbose          # every public event, turn by turn
uv run pax view france --seed 1             # exactly what one ruler receives
uv run pax schema                           # the structured-output schema of Orders
uv run pax bench --games 40                 # winners by seat with greedy bots
uv run pax play --seed 1 --html replays/1.html   # watch it on a map
```

## Invariants every change must keep

1. **Determinism**: all randomness comes from `random.Random(f"{seed}:...")`. Never use the
   global `random`, the clock or a set's iteration order in a way that affects outcomes.
2. **Purity**: `resolve_turn` deep-copies its input and never mutates it. No I/O in `engine/`.
3. **Fog of war**: new state that a ruler must not see stays out of `NationView`. Private events
   carry an `audience`.
4. **Every illegal order is explained**: reject with `self._reject(nation, action, reason)` and a
   reason a model can act on ("only 2 regiments in Madrid", not "invalid").
5. **Rules live in `Rules`**: no magic numbers in `resolve.py` or `mechanics.py`.

## Changing the map

Province shapes come from `scripts/build_map.py`: each Natural Earth admin-1 region goes to a
province by an explicit `OVERRIDES` entry or to the nearest allowed province seat (`COUNTRIES`),
or becomes wasteland. After `make map`, the script prints any difference between drawn borders
and the game's `_LAND_BORDERS`; `tests/test_map_asset.py` fails until they match. Fix
`scenario.py` (or the assignment) so the game graph and the picture agree.

## Checklist for a rule change

1. Write or adjust the test first (`tests/engine/`).
2. Change `Rules` / `resolve.py` / `mechanics.py`.
3. Update `docs/game-rules.md`, and the action docstrings if the meaning changed, since they go
   into the LLM schema.
4. Run `make check`, then `uv run pax bench --games 40` to see what the change did to balance.
