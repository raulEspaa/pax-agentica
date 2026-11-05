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

## Results, 2026-11-05 (prompt `strategist-1`, 20 situations each)

| Run | valid | real_names | consistent | reachable | Median latency | Thinking tokens (median) | Cost |
|---|---|---|---|---|---|---|---|
| 3.1-flash-lite, low | 85% | 94% | 94% | 100% | 3.4 s | 122 | $0.062 |
| 3.1-flash-lite, high | 100% | 95% | 90% | 98% | 9.2 s | 1,839 | $0.072 |
| 3.5-flash-lite, low | 85% | 100% | 100% | 97% | 2.3 s | 0 | $0.083 |

`keeps_treaties` was 100% everywhere. Costs are at paid-tier prices; the free tier billed nothing.

- **Every invalid answer was the provider's, not the model's:** 5 rate limits (15 requests a minute on
  the free tier) and 2 overloads (503). Fixed with `CALLS_PER_MINUTE` in the client.
- **The rules do not tell these settings apart:** the gaps are one plan in twenty. More thinking costs
  three times the latency for nothing measurable.
- **Decision:** keep `gemini-3.1-flash-lite` with `low` as the default (cheapest, fast). Move to
  `gemini-3.5-flash-lite` before 3.1 shuts down on 2027-05-07; at `low` it does not think at all.
- No error message held the API key: the check left open in spec 002 is closed.

## Out of scope

- An LLM judge of strategic sense: added only if the rules stop telling settings apart.
- Paired tournaments with confidence intervals: cut from the reduced plan; a small pilot with
  `pax tournament` is enough for now.
- Recorded answers replayed in CI.
