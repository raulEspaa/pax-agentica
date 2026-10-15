# 001 · The game engine: Europe 1500

- **Status:** Done
- **Milestone:** M1
- **Author:** Claude Code (see [ADR 0002](../../docs/adr/0002-who-writes-what.md))

## Why

The AI rulers need a world to rule. That world has to be complete (economy, war and diplomacy),
deterministic and honest: an agent must not be able to cheat, and the same seed must always
replay the same game.

## What

A turn-based, arcade grand strategy game. 68 provinces of Europe, seven great powers, five
resources (ducats, manpower, iron, grain, timber), and the classic diplomatic options: alliances,
non-aggression pacts, peace, trade, gifts, war and private messages. The full rules are in
[`docs/game-rules.md`](../../docs/game-rules.md).

Players see a fog-of-war `NationView` and answer with `Orders`. Two rule-based bots (random and
greedy) play as baselines. `pax play` narrates a game in the terminal, and `--html` writes a
replay with a map.

## Acceptance criteria

Each one is covered by tests in `tests/`.

1. **Given** a seed, **when** a game is played twice with the same players, **then** both
   records are identical. (`test_properties.py`)
2. **Given** any state and any orders, **when** a turn is resolved, **then** the input state is
   unchanged and the new state is consistent: owners alive, capitals owned, no war between
   treaty partners. (`test_properties.py`, property-based)
3. **Given** an illegal order, **when** the turn resolves, **then** it has no effect and its author
   gets an `order_rejected` event with a reason. (`test_economy.py`, `test_combat.py`,
   `test_diplomacy.py`)
4. **Given** a nation, **when** its view is built, **then** it shows troops only at home, on its
   borders and in allied land, hides other treasuries, and only includes events it could
   witness. (`test_view.py`)
5. **Given** a declaration of war on a treaty partner, **when** it resolves, **then** the treaty
   breaks in public and the betrayer loses stability. (`test_diplomacy.py`)
6. **Given** a ruler that crashes or times out, **when** the turn is played, **then** that nation
   does nothing and the game continues. (`test_runner.py`)
7. **Given** greedy bots, **when** a game is played, **then** it ends with a winner within the
   turn limit, and fewer than 5% of their orders are rejected. (`test_properties.py`,
   `test_runner.py`)

## Out of scope

- Fleets and naval battles (straits stand in for the sea).
- Peace terms beyond ending the war (no ceded provinces; trades can carry reparations).
- Random events, technology, rebels and coalitions (see the ideas box in the README).
- Any LLM: that is the AI rulers' part, from milestone 2 on.
