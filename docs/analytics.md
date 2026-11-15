# Analytics: the tables and the AI, in BigQuery

What the public tables did, and what their AI cost, as SQL over BigQuery. Spec:
[`specs/009-analytics`](../specs/009-analytics/spec.md).

```
tables server (Cloud Run)                     GCS bucket                          BigQuery
  Lobby.close ────── games row ──┐     /data = gs://pax-agentica-261016-tables
  council decides ─ decisions ───┼──>  analytics/<kind>/dt=YYYY-MM-DD/      <──  pax_analytics.<kind>
  (audience reply) ─ audience ───┘       <table>.<writer>.ndjson                  external tables
```

## What is recorded

| Kind | One row per | Fields |
|---|---|---|
| `games` | table that closes (everyone left, abandoned, over) | `source`, `table_id`, `seed`, `started_at`, `ended_at`, `closed_reason`, `years_played`, `max_years`, `finished`, `winner`, `humans`, `human_nations[]`, `ai_nations[]`, `ai_cost_usd`, `standings[]{nation, ruler, standing, score, alive, provinces}` |
| `decisions` | AI council decision (a crown's orders for one year) | `at`, `source`, `table_id`, `nation`, `turn`, `year`, `model`, `cost_usd`, `model_calls`, `latency_s`, `plan_asked`, `plan_written`, `diplomacy_asked`, `diplomacy_written`, `letters`, `failures[]`, `timed_out`, `fallback`, `error` |
| `audience` | AI reply in a chat with a human (to be wired by the audience feature, with `agents.tables.audience`) | `at`, `source`, `table_id`, `nation`, `turn`, `year`, `model`, `cost_usd`, `model_calls`, `latency_s`, `error` |

The schemas are [`scripts/bigquery/*.json`](../scripts/bigquery/), and the row models are in
[`analytics.py`](../src/pax_agentica/analytics.py); a test fails if the two drift apart, or if an
emitted row has a field the schema does not declare or a value of the wrong type.

No personal data: a ruler is recorded as `human`, `council`, `strategist` or a bot's name, never by
the name a player typed; no orders, letters or chat text.

### How the cost of one decision is measured

Several councils think at once (two crowns at each of up to twelve tables), all spending from one
daily budget, so "what the budget spent between the start and the end of a decision" would count
the other councils' calls too. Instead:

1. Each decision runs in its own asyncio task (`ThinksAhead` starts it), and `Recorded.decide`
   opens a `Meter` in a **context variable** ([`agents/meter.py`](../src/pax_agentica/agents/meter.py)).
2. asyncio gives every task a copy of the context of the code that started it, so the meter follows
   the decision into the tasks LangGraph starts for its nodes, and into no other decision.
3. `Budget.settle`, where every call's real cost (from its tokens) is known, adds it to the meter
   of whoever made the call. Retries and failed calls are counted as they were billed (a call that
   fails is charged at its worst cost, as the budget already does).
4. `MeteredModel` wraps the council's model and notes on the same meter what was asked (`plan`,
   `diplomacy`), what came back, the letters written, and each failure as `kind:ExceptionName`. A
   node's timeout cancels the call, so it shows as `CancelledError` or `TimeoutError`:
   `timed_out`. Something asked for and never written is a `fallback` (the last plan, or the
   bot, stood in).

A test runs two councils at once on one budget, with calls that settle in between each other's,
and checks that each row has exactly its own cost.

`latency_s` runs from the start of thinking to the orders. The council thinks while the humans
play their year, so this is not time anyone waited.

## Why files and external tables, not streaming inserts

| | NDJSON in the bucket + external tables (chosen) | Streaming inserts / Storage Write API |
|---|---|---|
| The serving image | nothing new: it writes files to `/data`, as it does for saves | the `google-cloud-bigquery` client and its dependencies |
| Credentials, IAM | the runtime account keeps its one right (write the bucket) | the runtime account also needs `bigquery.dataEditor`: one more surface |
| Cost | storage of a few KB a day; queries scan a few MB (free tier) | streaming inserts are billed per GB (tiny here, but not zero), Storage Write is free up to 2 TB/month |
| A failure | a lost line, logged; the game goes on | a network call on the request path, or a queue to build |
| Query speed | slower: every query lists and reads the files | native tables, fast |
| Freshness | a row is in the bucket when it is written | seconds |

At this volume (a few hundred decisions a day at most) query speed does not matter, and keeping
the server free of a second cloud client does. If it ever grows, a scheduled
`INSERT INTO native SELECT * FROM external` copies the files into a native table without
touching the server.

## The GCS append caveat, and the file layout

GCS objects are immutable. The bucket is mounted with Cloud Storage FUSE, which makes an append
look like a file append, but on close it **uploads the whole object again**. Two writers appending
to one object would each upload their own copy, and the last one wins: rows lost silently.

So each file belongs to one table, one day and one **writer** (`<Cloud Run revision>-<random>`,
fixed for the life of the process): `analytics/decisions/dt=2026-11-15/AbC123.pax-tables-00042-xyz-1f2e3d.ndjson`.

- A single process writes a file, under a lock, so there is no lost update. During a deploy the
  old and new revisions overlap for a few seconds and may both write about a table: into two
  files, both kept.
- A table writes at most two `decisions` rows a year (two AI crowns), and a year takes at least a
  minute, so each file stays a few KB and rewriting it on every append is cheap (each save of the
  same table already rewrites ~2 MB).
- One object per event would avoid rewrites entirely but make thousands of tiny files, which
  BigQuery lists and opens one by one; one per table and day is the middle way.
- A table closes once, but two overlapping revisions could each report the close. The saved
  queries keep the first row of each table (`QUALIFY ROW_NUMBER() ... = 1`).

`dt` is a Hive partition: BigQuery reads it from the path, and a query filtered on `dt` opens
only those folders. It is not a field of the rows.

The files are not deleted with the tables (closed tables go after a week; their analytics stay).

## Setting it up (once)

Who: someone with `roles/bigquery.admin` on the project (or `bigquery.dataEditor` +
`bigquery.jobUser`) and read access to the bucket. The server needs nothing new.

```bash
gcloud storage buckets describe gs://pax-agentica-261016-tables --format 'value(location)'  # europe-west1?
scripts/bigquery_setup.sh       # dataset pax_analytics + external tables games, decisions, audience
```

The script is idempotent (`CREATE OR REPLACE EXTERNAL TABLE`): run it again after changing a schema.
`LOCATION` must be the bucket's region (or the EU multi-region if the bucket is in it). To see the
DDL without running it: `python3 scripts/bigquery_ddl.py --project pax-agentica-261016 --bucket pax-agentica-261016-tables`.

A table whose folder has no file yet (`audience`, until that feature is wired; `games`, until the
first table closes) answers queries with a "matched no files" error rather than zero rows.

## The saved queries

In [`scripts/bigquery/queries/`](../scripts/bigquery/queries/):

| File | Answers |
|---|---|
| `cost_per_game.sql` | what the AI cost each game with AI crowns, and per AI crown-year |
| `decision_cost_latency.sql` | per day and model: decisions, calls, cost per decision and per plan, latency p50/p95 |
| `ai_win_rate.sql` | win rate, average standing and survival per kind of ruler (council vs bots vs humans) |
| `games_per_day.sql` | tables closed per day, how they ended, how many had the AI, the AI's spend |
| `fallbacks.sql` | per day: fallback, timeout, forfeit, missed plan and missed letters rates |
| `failures.sql` | which failures the model calls met, most common first |

```bash
bq query --project_id pax-agentica-261016 --nouse_legacy_sql < scripts/bigquery/queries/decision_cost_latency.sql
```

## Local runs: `pax analytics export`

Local games (`pax play --save`, `pax tournament --save DIR`, or saves of `pax host` tables) turn
into `games` rows of the same schema, with `source = 'local'`:

```bash
uv run pax tournament --games 20 --player england=council --budget 0.5 --save runs/t1   # costs money
uv run pax tournament --games 20 --save runs/bots                                      # free
uv run pax analytics export runs/t1/*.json --out runs/t1-analytics
bq load --project_id pax-agentica-261016 --source_format=NEWLINE_DELIMITED_JSON \
  pax_analytics.local_games runs/t1-analytics/games.ndjson scripts/bigquery/games.json
```

`bq load` appends to a native table (created on the first load); load jobs are free. Then
`ai_win_rate.sql` with `pax_analytics.local_games` in place of `pax_analytics.games` compares the
council with the bots over local seeds. Local records carry no costs or decisions: those come
from the tables, or from Langfuse for local runs.

## What it costs

About **$0**:

- BigQuery queries: on-demand pricing is per TB scanned, and the first **1 TB a month is free**.
  These tables are a few MB after months of play; a query scans all of a kind's files (external
  tables have no column pruning for JSON), still far under the free tier. External tables have no
  BigQuery storage cost.
- GCS: the files are KB a day in a bucket that already exists; each append is one write operation
  (class A, $0.005 per 1,000), a few hundred a day at most.
- Local `bq load`: free; native storage of the loaded rows is inside the 10 GB free tier.

Turn it off: nothing to turn off on the server side beyond the files it writes;
`bq rm -r -f pax-agentica-261016:pax_analytics` removes the dataset (the files stay in the bucket).

## First reading (2026-11-15)

The first table in production with all eight rivals ruled by the council (5 years, one human) gave,
from `decision_cost_latency.sql` and a query by year:

| Year | Decisions | Model calls | Mean latency | Cost |
|---|---|---|---|---|
| 1 | 8 | 9 | 50 s | $0.021 |
| 2 | 8 | 8 | 11 s | $0.006 |
| 3-5 | 24 | 78 | 47-52 s | $0.078 |

$0.105 in all, $0.0026 a decision. The latency was the queue, not the model: from the third year
the eight crowns write to each other, about 25 calls a year, and the model let only 4 run at once.
`PAX_AI_CONCURRENT_CALLS=16` came from this reading. It is the kind of question this table exists
to answer: one query, no logs to grep.
