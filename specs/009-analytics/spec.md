# 009 · Analytics: what the tables and the AI did, queryable in BigQuery

- **Status:** Done (in code; the BigQuery setup is a one-time command, see docs/analytics.md)
- **Milestone:** AI roadmap, deployment

## Why

The public tables answer "is it running?", not "what does the AI cost per game, how slow is it,
how often does it fall back, and does it win more than a bot?". Those questions need the events
in one place that SQL can read, cheaply, without giving the serving image a database client.

## What

- The tables server writes **events as newline-delimited JSON** into the bucket it already mounts,
  under `/data/analytics/<kind>/dt=YYYY-MM-DD/<table>.<writer>.ndjson` (Hive-style partitions).
  Three kinds: `games` (a row when a table closes), `decisions` (a row per AI council decision)
  and `audience` (a row per AI chat reply; defined now, wired when the audience feature lands).
- **BigQuery external tables** over those files (`pax_analytics.games`, `.decisions`,
  `.audience`), made by an idempotent script, with saved queries: cost per game, cost and
  latency (p50/p95) per decision, AI win rate against bots, games per day, fallback and timeout
  rates.
- `pax analytics export GAMES... --out DIR` turns local game records (`pax play --save`,
  `pax tournament --save`, table saves) into the same `games` rows, for `bq load`.

Decisions taken (alternatives in docs/analytics.md):

- **External tables over files, not streaming inserts**: no BigQuery client, credentials or
  dependency in the image; the runtime account keeps its one permission (write the bucket).
- **One object per table, day and server process**, appended to. GCS objects are immutable and
  the bucket is mounted with gcsfuse, so an append rewrites the object: per table and day keeps
  each object small, and the writer's id in the name keeps two revisions (a deploy overlaps
  them) from overwriting each other's rows.
- **Cost per decision from a context variable**, not a delta of the shared daily budget: several
  councils think at once, so a global delta would mix their calls. Each decision runs in its own
  asyncio task with its own `Meter`; `Budget.settle` adds every call's real cost to the meter of
  the task that made it.

## Acceptance criteria

1. **Given** the schema files in `scripts/bigquery/`, **when** any event row is written, **then**
   every field it has is declared there with a compatible type, and every declared field exists
   in the row model.
2. **Given** a table with an AI crown, **when** its council decides a year, **then** one
   `decisions` row is written with the table, nation, year, model, cost, latency, model calls,
   whether a plan and letters were asked and written, and the failures.
3. **Given** two councils deciding at once on one shared budget, **then** each decision's cost is
   exactly what its own calls cost.
4. **Given** a council whose plan call times out or fails, **then** its row says `fallback` (and
   `timed_out` for a timeout), and the year is still played.
5. **Given** a table that closes (everyone left, abandoned, or over), **then** one `games` row is
   written with seed, years played, humans, AI crowns, winner, standings, why it closed and the
   AI spend of the table.
6. **Given** an analytics directory that cannot be written, **then** the request and the year go
   on, and the failure is only logged.
7. **Given** local game records or table saves, **when** `pax analytics export` runs, **then** it
   writes `games.ndjson` rows of the same schema, with `source` = `local`.
8. **Given** the schema files, **then** `scripts/bigquery_ddl.py` prints one
   `CREATE OR REPLACE EXTERNAL TABLE` per kind, partitioned by `dt`.

## Out of scope

- Streaming inserts, a BigQuery client in the image, Pub/Sub or Dataflow.
- A per-turn table of the whole game (the replay files already hold it).
- Dashboards (Looker Studio can read the views later).
- Rows for human players' orders or names: no personal data goes into analytics; rulers are
  recorded by kind (`human`, `council`, a bot's name), never by a player's name.
