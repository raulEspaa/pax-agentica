# 008 · A ruler's memory of treaties and betrayals, and an audience with an AI court

- **Status:** Done (v0, tested with fakes; a real run is still to do)
- **Milestone:** AI roadmap, phase 6 "Chronicle" (reduced), at the public tables

## Why

An AI crown at a table forgets: its diplomat reads only the last three years of letters, so a
betrayal in 1512 is gone by 1516. And a human who writes to it waits two years for an answer
(read in year N+1, seen in N+2). The game promises rivals you negotiate with over chat, and who
remember what you did to them.

## What

1. **Memory.** Each AI crown at a table keeps a chronicle of its dealings with every court:
   short dated entries (treaties signed and broken, wars and peaces, tributes, letters, grudges,
   audiences), taken **only from its own `NationView`** each year, and from audiences it gave.
   Entries are embedded and searched with a hybrid ranking (vector + keyword + recency, merged by
   RRF), always within one court. The diplomat reads "WHAT YOU REMEMBER OF <court>" for each
   court on its desk.
2. **Audience.** At a table, a seated human may speak privately to an AI-ruled crown. The
   crown's model answers at once, in the monarch's voice, as a chat line only that seat sees.
   Words only: nothing in it is an order or a treaty. The exchange enters the crown's memory, so
   its diplomat meets it next year.

## Acceptance criteria

1. **Given** a game where two other courts exchange a private letter, **when** a crown's memory
   observes its own views, **then** nothing of that letter enters it (fog of war).
2. **Given** a memory with a betrayal by England among other entries, **when** it recalls about
   England, **then** the betrayal comes first, and a recall about Spain never returns an entry
   about England.
3. **Given** a council with memory and a court on the desk it remembers, **then** the diplomat's
   prompt holds "WHAT YOU REMEMBER OF <court>" with those entries, inside `<memory>` tags that a
   remembered letter cannot close, each entry on one line; `DIPLOMAT_PROMPT_VERSION` is
   `diplomat-3`.
4. **Given** a council without memory (the default), **then** it plays as before: the graph still
   plays the same game as the loop.
5. **Given** a spent budget or a failing embedder, **then** memory still records entries and
   recalls by keyword and recency; the year is never lost to it.
6. **Given** a table with an AI crown, **when** a seated player speaks `to` that crown, **then**
   the reply appears at once as a chat line marked `ai`, from that crown, seen by that seat only.
7. **Given** a seat that has spoken three times to one AI court this year, **then** a fourth word
   to it is refused (429) until next year; other courts are not affected.
8. **Given** a spent day's budget, **then** an audience is refused with 429 and a clear message;
   **given** a model that fails or times out, **then** the court answers with an in-character
   silence, and the game goes on.
9. **Given** player words that try to close the tags or forge a system line, **then** they reach
   the model flattened to one line, inside `<audience>` tags they cannot close.
10. **Given** an audience in year N, **then** the crown's diplomat in year N+1 is called, even with
    no letter on its desk, and its prompt remembers what was said.
11. **Given** a table that unloads or a server that restarts, **then** each crown's memory is read
    back from its file beside the table's saves, and is deleted when the table is.

## Out of scope

- Memory in the tournaments and evaluations (`pax play --ai`, `pax eval`): off by default there,
  so earlier results stay comparable. Whether memory wins games is phase 6's question, not this.
- Postgres for memory: the tables' image has none, and a crown's memory is a few hundred lines.
- Audiences with bots, or between AI crowns.
- Turning words in an audience into a treaty: treaties still go through proposals.

## Decisions

- **Persist, not rebuild.** A crown's entries and vectors (256 dimensions, rounded) are written to
  `saves/memory/<table>.<nation>.json` after each change. Rebuilding from the `GameRecord` would
  replay every past year's view and embed every entry again, which the free tier's 50 texts a
  minute turns into many minutes for a long game, and audiences are not in the record at all. The
  file is a few hundred KB at most.
- **Memory outside the graph state.** Vectors in a LangGraph checkpoint would be copied every
  year; the memory is an object on the council, like the greedy bot.
- **Hybrid with recency.** Names are keywords (`england`), meaning is vectors ("who wronged us"),
  and a ruler remembers last year better than twenty years ago: three rankings, merged by RRF,
  so no scale has to be tuned against another.
