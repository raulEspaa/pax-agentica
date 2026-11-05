# Results

What the AI part measured, on 2026-11-05. Every run is in the local Langfuse as an experiment or
a trace. Costs are at paid-tier prices, as the budget charges them; the free tier billed nothing.
Every number below comes from a small sample: read it as a direction, not a benchmark.

## The strategist: 20 situations, scored by rules

From [spec 003](../specs/003-strategist-evaluation/spec.md): a plan for twenty moments of
greedy-bot games (seed 1, turns 1, 8, 15 and 22, five crowns).

| Model, thinking | valid | real_names | consistent | reachable | Median latency | Cost |
|---|---|---|---|---|---|---|
| 3.1-flash-lite, low | 85% | 94% | 94% | 100% | 3.4 s | $0.062 |
| 3.1-flash-lite, high | 100% | 95% | 90% | 98% | 9.2 s | $0.072 |
| 3.5-flash-lite, low | 85% | 100% | 100% | 97% | 2.3 s | $0.083 |

- Every invalid plan was the provider's (rate limits and 503s), not the model's: the client now
  keeps under the free tier's 15 calls a minute.
- The rules cannot tell the settings apart; more thinking triples latency for nothing measurable.
  Default: `gemini-3.1-flash-lite` at `low`.

## The archive: recall@5 on 18 questions

From [spec 005](../specs/005-archive/spec.md): one game of greedy bots (`bots-seed1`, 50 years)
and the rules, cut into 545 chunks. Twelve questions written from the game's own events and six
about the rules; a question is found when the chunk that answers it is in the first five.

| Embeddings | keyword | vector | hybrid (RRF) |
|---|---|---|---|
| word hash (a free stand-in that only matches shared words) | 33% | 22% | 50% |
| `gemini-embedding-001`, 768 dimensions | 33% | 72% | **83%** |

- Hybrid search beats either kind alone with both embedders: the keyword list rescues exact names
  and years that vectors blur, and RRF merges by rank, so the two scores never need a common
  scale.
- Embedding the corpus cost $0.017 by the budget's safe estimate (2 characters a token).

## The Archivist: 8 questions about one game

From [spec 006](../specs/006-archivist/spec.md): three facts, two "why" questions, two about the
rules and one the archive cannot answer, asked of `gemini-3.1-flash-lite` at `low` with the
archive above.

| Score | Result | What it says |
|---|---|---|
| `grounded` | 75% (6 of 8) | it cited, and only chunks it retrieved; never an invented citation |
| `cites_expected` | 57% (4 of 7) | it cited the chunk that holds the answer |
| `faithfulness` (judge) | 3 of 3 judged: full | the cited chunks say what the answer says |
| `catches_lie` (judge) | pending | the judge's own check: see below |

- **It does not make things up.** Asked what the Aztec emperor wrote to France, it said the
  archive holds no such record. The two answers that were not `grounded` were the same honest
  "the archive does not say", about two successions in Russia: a retrieval miss, not an invention.
- **It separates what a ruler did from why.** "England went to war against France because it
  believed it outnumbered France on the border", cited from England's own thoughts of 1527.
- **The judge's run failed on the provider's side:** `gemini-3.5-flash-lite` answered 503 (high
  demand) to most judge calls, so only three answers were judged and no planted lie was. The
  judge now uses `gemini-3.1-flash-lite` at `high`; its rerun, with the planted-lie check, is the
  open item.

## What these numbers do not show

- Whether the rulers play better than the bots: that needs paired tournaments over many seeds,
  cut from the minimum plan.
- Whether the judge agrees with a person: the planted lie checks that it catches a gross error,
  not that its "partial" means what a reader would mean.
