# 006 · The Archivist: questions about finished games, answered with citations

- **Status:** Done
- **Milestone:** AI roadmap, MVP step B (phase 9, reduced)

## Why

The archive (spec 005) finds chunks; a reader still has to put them together. The Archivist answers
"why did France attack Spain in 1512?" in a few sentences, from the archive alone, and says where
each claim comes from. It is a conversational agent that chooses its own searches, a different
shape from the rulers' fixed graph, so it is built with ADK.

## What

`pax ask QUESTION` and `pax api` (FastAPI, `POST /ask`) put questions to an ADK `LlmAgent` with
one tool, `search_archive`, over the archive's hybrid search. A session keeps the conversation.

## Acceptance criteria

1. **Given** a question, **then** the agent searches the archive before it answers, and the
   searches keep to the conversation's game and the rules.
2. **Given** an answer, **then** the reply lists its citations and says it is `grounded` only when
   it cites something and every citation is a chunk it retrieved in that conversation.
3. **Given** the session of a reply, **then** the next question follows on from it; an unknown
   session starts a new conversation.
4. **Given** a model call, **then** it is paid for within the budget before it is made, at worst
   cost, and settled at its real cost; a call the budget cannot cover is never made, and the API
   answers 503.
5. **Given** a model that keeps searching, **then** a question stops after six model calls.
6. **Given** chunks that quote rulers' letters, **then** the instructions say they are data to
   report, never instructions.
7. **Given** Langfuse keys, **then** each question is one trace, with each model call in it and the
   conversation as its session.
8. **Given** a question over 500 characters, **then** the API refuses it.
9. **Given** an answer and the text of the chunks it cites, **then** an LLM judge (another model
   than the Archivist's) lists the claims no source supports before its verdict: full, partial or
   none.
10. **Given** the same answer with a planted false claim, **then** the judge is scored on catching
    it, so its verdicts are trusted only as far as it catches lies.
11. **Given** a game, **then** `pax eval-archivist` asks eight questions (facts, reasons, rules and
    one the archive cannot answer) as a Langfuse experiment, scored `grounded`, `cites_expected`,
    `faithfulness` and `catches_lie`.

## Out of scope

- Persistent sessions (ADK's database session service): a restart forgets conversations, never
  the archive.
- Deploying the API publicly: it would need an invitation code like the tables.
