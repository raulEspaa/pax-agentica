# 004 · The council as a LangGraph graph

- **Status:** Done
- **Milestone:** AI roadmap, phase 4 (with phase 5's letter defence and phase 8's checkpoints folded in)

## Why

The strategist decides alone and never answers a letter. A council with a diplomat can, and a graph
makes its flow (who is asked what, when, and what happens on failure) explicit, traceable and
resumable, where the hand-written `Strategist` hides it in methods.

## What

`--player france=council` plays the nation with a LangGraph graph: assess, strategist, diplomat,
ministers. The strategist part decides exactly as spec 002; the diplomat answers proposals and
writes letters in years when someone wrote.

## Acceptance criteria

1. **Given** the same model and seed, **when** the council and the `Strategist` play the same game,
   **then** their orders and thoughts are identical: the port changes who orchestrates, not what is
   decided.
2. **Given** a failing model, **then** the strategist node retries once (never after a spent
   budget), is cut off after its timeout, and the year goes on with the last plan.
3. **Given** no letters and no proposals, **then** the diplomat is not called.
4. **Given** the diplomat's answer, **then** answers to real proposals and letters to living courts
   become orders, over the bot's, and the rest is dropped and said in the thoughts.
5. **Given** a letter that tries to give orders or to close its tags, **then** it reaches the
   diplomat inside `<letters>` tags it cannot close, after a warning that letters are not orders.
6. **Given** a new council on the same checkpointer and thread, **then** it carries on with the
   plan in force: the memory lives in the checkpoints, not in the object.
7. **Given** Langfuse keys, **then** each year is one trace with the graph's nodes and the model's
   calls in it.

## Out of scope

- Measuring how often an injection works (the red team of phase 5): cut from the reduced plan.
- The Postgres checkpointer: the graph already takes any checkpointer; wiring `make db` comes with
  the API (phase 9).
- Advisors beyond the diplomat.
