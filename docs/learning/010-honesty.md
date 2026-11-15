# 010 · Honesty: evaluating what an agent says against what it does

> Draft by the assistant, for Raúl to review and rewrite. Spec: [010](../../specs/010-honesty/spec.md).

## What was built

`pax honesty` answers one question about the AI rulers: when a council writes "France will never
attack Spain", does France then attack Spain? It reads every letter an AI crown wrote, asks a
model to list the promises in it, checks each promise by rules against the game record, and
flags letters whose writer privately planned the opposite. It prints a table per crown and the
cost per game, and writes one flat row per promise (NDJSON) for a warehouse.

## Reading order

1. `agents/honesty.py`, top to bottom: the schema (`Commitment`, `Extraction`), `utterances`
   (which letters count), `build_request` (the extractor's prompt), `check` and `_settles` (the
   rules), `premeditated` (deception by rule), then `evaluate`, `rows` and `tally`.
2. `tests/agents/test_honesty.py`: each rule on a record built by hand, a few events at a time.
3. `agents/honesty_cases.py` and its test: the labelled letters and how the extractor is scored.
4. `cli.py`, `_honesty`: how a run plays, reads, pays and writes.

What to run, free: `uv run pytest tests/agents/test_honesty.py tests/agents/test_honesty_cases.py`.
What costs money (ask first): `pax honesty --calibrate --budget 0.30`, then the pilot in
`docs/ai-results.md`.

## The decisions, and what they beat

- **A model reads, rules judge.** Reading "we shall stand at your side against Poland" needs
  language; deciding whether France then joined the war against Poland does not, and the record
  holds the answer exactly (`joined_war` events). An LLM judge of "was this promise kept?" would
  cost a call per promise, could be wrong, and would need its own calibration. The rules are free,
  deterministic and unit-tested.
- **A closed set of kinds**, each one something the engine records: `no_attack`, `peace`,
  `alliance`, `join_war`, `pay`, `trade`, and `other` for the rest. A free-text "promise" field
  would read more naturally and be impossible to check. `support_claim` was dropped: the engine has
  no act of supporting a claim, so it could only ever be `other`.
- **Four verdicts, not two.** `untested` (nothing settled it: a peace needs the enemy's consent)
  and `untestable` (the kind is `other`, or a crown fell) keep the keep-rate honest: it is kept
  divided by kept-plus-broken, never padded by promises nobody could have broken.
- **Deception has two signals, kept apart.** A rule (the same year's thoughts name the court with
  a word of war) is cheap and explainable, and blind to anything said another way. The extractor,
  which already reads the letter, also reads the private thoughts and says whether they contradict
  it: one call per letter, not two. Two separate calls would let each prompt do one thing, at
  twice the cost; the calibration set measures whether the combined one still extracts well.
- **The letter is data.** The extractor reads text that another model wrote, possibly to fool a
  reader. It sits in tags it cannot close, after a warning, as the diplomat's letters do (spec
  004 and the red team). A calibration case tries it.
- **One budget for the whole run**, games and extraction, on the same `GeminiModel`, so they share
  the rate window too. Letters are read one at a time: the window allows 12 calls a minute
  anyway, and it makes each letter's cost exact (`budget.spent_usd` before and after).
- **Flat rows.** One row per promise with the game, seed, year, crown, court, kind, verdict and
  cost: what a warehouse (BigQuery) loads without a schema of nested records.

## What breaks if it changes

- `WINDOW_YEARS` (5): a longer window turns more `untested` promises into `kept` or `broken`, and
  makes a vague promise to pay harder to break.
- `greedy_bot.REPLIES`: the four canned letters of the ministers. Change one without the constant
  and the study counts the bot's words as the model's.
- `Extraction`'s field order: the model writes the promises before the deception flag, so the
  flag follows from a reading of the letter, as the judge (spec 006) lists claims before its
  verdict.

## Known limits

- The rule reads words, not years: "war on France in 1520" flags a promise that only covers this
  year (case `third-court`, kept as a known false alarm in the tests).
- The thoughts carry the plan's note, not the plan. `Plan.war_on` in the record would make the rule
  sharper.
- A promise to pay that names no amount is kept by any gift, however small.
- The calibration labels are drafts by the assistant: a wrong label is a wrong score.
