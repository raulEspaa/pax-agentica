# 003 · Evaluating the strategist

- **Status:** In progress
- **Milestone:** AI roadmap, phase 3 (reduced on 2026-11-05)

## Why

A plan that reads well can still be nonsense for the game. Before changing the model, the
thinking level or the prompt, we need a number that says whether the change made plans better.

## What

`pax eval --budget USD` asks a model for a plan in each of twenty situations from games of greedy
bots, scores each plan with rules, and records it all in Langfuse as one run of an experiment on
one dataset, so runs with other settings sit side by side.

## Acceptance criteria

1. **Given** a seed, a year and a nation, **when** the situation is rebuilt, **then** it is the view
   that nation saw that year in a game of greedy bots of the usual length, the same every time.
2. **Given** the dataset, **then** it holds twenty different situations (five nations, four years),
   each stored as its three numbers and the contract version.
3. **Given** a plan and its view, **when** it is scored, **then** it gets `valid`, `real_names`,
   `consistent`, `keeps_treaties` and `reachable` (see `agents/evals.py`); a model that gives no
   plan scores only `valid` = 0.
4. **Given** no Langfuse keys, **when** `pax eval` runs, **then** it stops before any call.
5. **Given** keys and a budget, **when** `pax eval` runs, **then** each situation is one item of an
   experiment run named after the model, the thinking level and the prompt version, with its
   scores and its model call traced, and the averages and the spending are printed.

## Out of scope

- An LLM judge of strategic sense: added only if the rules stop telling settings apart.
- Paired tournaments with confidence intervals: cut from the reduced plan; a small pilot with
  `pax tournament` is enough for now.
- Recorded answers replayed in CI.
