# 005 · The archive: ingestion, embeddings and hybrid search

- **Status:** In progress
- **Milestone:** AI roadmap, MVP step A (phase 6, reduced)

## Why

The Archivist (step B) must answer questions about finished games with citations. It needs the
games and the rules cut into pieces it can find by meaning ("who betrayed Spain?") and by exact
name (`flanders`, a year), and a number that says which way of finding works best.

## What

`pax ingest GAME.json...` cuts finished games and `docs/game-rules.md` into chunks, embeds the new
ones and stores them in Postgres with pgvector. `pax search` finds chunks by vector, keyword or
both merged with Reciprocal Rank Fusion. `pax recall GAME.json` measures recall@5 of each.

## Acceptance criteria

1. **Given** a game, **then** it gives a chunk of public, non-routine news per year and a chunk of
   thoughts and letters per crown and year; **given** the rules, a chunk per subsection, nothing
   lost.
2. **Given** the same games ingested twice, **then** nothing new is embedded or stored.
3. **Given** vectors of another embedding model, **then** they are never compared with these.
4. **Given** a question, **then** keyword search finds exact names, vector search finds meaning,
   and hybrid merges both; a search can keep to one game and the rules.
5. **Given** Gemini embeddings, **then** each batch is paid for within the budget before it is sent.
6. **Given** a game, **then** `pax recall` asks questions written from its own events and a few
   about the rules, and prints recall@5 for each kind of search.
7. **Given** CI, **then** the database tests run against the same pgvector image as `make db`.

## Out of scope

- Rulers that read their own chronicle during a game (would need the fog-of-war filter).
- Public-domain history of the period: licences to check, not needed for the MVP.
- A reranker: only if recall shows a gap hybrid search cannot close.
