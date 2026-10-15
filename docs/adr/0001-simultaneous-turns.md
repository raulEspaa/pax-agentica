# ADR 0001: Simultaneous turns resolved in fixed phases

- **Status:** accepted
- **Date:** 2026-10-15

## Context

Each turn, seven rulers must decide what to do. Some of them will be LLMs, and an LLM call takes
seconds. With sequential turns (France moves, then Spain sees the result and moves...), a turn
costs seven calls in a row, and whoever moves first has a built-in advantage.

## Decision

All nations decide **simultaneously**, on the same snapshot of the world, each through its own
fog-of-war view. The engine then resolves all orders in fixed phases: answers, diplomacy,
economy, movement, battles, end of turn. Inside each phase, nations act in an order shuffled by
the seeded RNG, and battles interleave one attack per nation at a time.

A newly declared war mobilises for one turn before attacks are allowed, so an ally can answer a
call to arms before the fighting starts.

## Consequences

- The runner asks every ruler at once (`asyncio.gather`): a turn takes as long as the slowest
  ruler, not the sum of all of them.
- Orders can collide: an attack can find that its target changed hands earlier in the same
  phase, or that a peace was signed in phase 1. Such orders are rejected with a reason, which
  the ruler reads next turn. Rulers must cope with plans that do not survive contact.
- Fairness comes from the shuffled order, and reproducibility from seeding that shuffle.
