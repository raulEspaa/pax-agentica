# 008 · Memory and audiences: a small RAG inside each ruler

Spec: [008](../../specs/008-memory-and-audience/spec.md). Code:
[`agents/memory.py`](../../src/pax_agentica/agents/memory.py),
[`agents/audience.py`](../../src/pax_agentica/agents/audience.py), the wiring in
[`agents/tables.py`](../../src/pax_agentica/agents/tables.py) and
[`multiplayer.py`](../../src/pax_agentica/multiplayer.py).

## What was built

- **A chronicle per AI crown.** Each year the council turns its own view into short dated lines
  ("1504, betrayal: England breaks its alliance with France"), embeds the new ones and keeps them
  in a JSON file beside the table's save.
- **Recall per court.** The diplomat gets "WHAT YOU REMEMBER OF england": the five lines that best
  match what England is writing about now, from three rankings fused with RRF.
- **An audience.** A player speaks to an AI crown in the chat and its monarch answers in seconds,
  in words only. The exchange goes into the memory, so next year's diplomat knows what was promised.

## Reading order for the review

1. `memory.entries_from`: what a view says about each court. This is where fog of war is held:
   it reads only a `NationView`.
2. `Chronicle.recall`: the three rankings and `_fuse`. Compare with `archive.search`, which does
   the same in SQL.
3. `Embeddings.vectors`: why a thread, why a lock, why `None` instead of an exception.
4. `diplomat.fence` and `remembered_block`: the same defence as letters, now for three tags.
5. `council.Council.remembered` and `_to_the_desk`: where memory enters the graph.
6. `audience.build_request`, then `TableAI.audience`, then `Lobby.audience`: the request, the
   call, and the limits.

Run: `uv run pytest tests/agents/test_memory.py tests/agents/test_audience.py -n 0 -v`, and
`uv run pax audience --prompt "Will you march with us against Spain?"` to read a real prompt
without calling a model.

## Decisions, and what breaks if they change

| Setting | Value | If changed |
|---|---|---|
| `TOP_K` | 5 lines per court | more lines, a longer prompt each year for every court on the desk |
| `RRF_K` | 60 | smaller: the top of each ranking dominates more; 60 is the paper's constant |
| recency as a ranking | on | off: an old betrayal and last year's promise weigh the same; on, a memory that only says recent things is possible, which words and meaning balance |
| `MEMORY_DIMENSIONS` | 256 | 768: three times the file; at a few hundred lines the cosine barely changes |
| `EMBED_TIMEOUT_SECONDS` | 10 | longer: an audience waits behind a council's embedding (the free tier's 50 texts a minute can make it wait a whole minute) |
| `AUDIENCE_WORDS` | 3 a year per court | more: each word is a model call on the shared daily budget |
| `AUDIENCE_TIMEOUT_SECONDS` | 30 | longer: the player stares at "considering…"; shorter: more silences on a slow day |

## What I learned

- **RRF works for any list you can rank**, not only vector and keyword: recency is one more
  list, with no weight to tune. The archive merges two lists in SQL; here three merge in twelve
  lines of Python, because a crown's memory is a few hundred lines and needs no index.
- **Graceful degradation is a design, not a try/except.** Each part has a fallback that still
  answers: no vector, then words and dates; no reply, then an in-character silence. The budget
  is checked before the call (429 with a clear message), and anything after that becomes silence.
- **A synchronous SDK in an async server** needs `asyncio.to_thread`, and the shared objects it
  touches (the rate window, the budget's file) need a lock: two threads replacing the same
  temporary file is a real race.
- **Memory is a second injection channel.** A line remembered from a letter is still the
  letter's words. It keeps the letter's treatment: one line, tags it cannot close.

## What I would do differently

- Measure it: do crowns with memory keep or break more treaties, and do they win more? That is
  phase 6's real question, and it needs a tournament with memory on and off.
- Ask the model to write the memory's lines (a summary of the year) instead of templating events:
  better lines, at the cost of a call a year per crown.
