# ADR 0002: The assistant builds the game; I build the AI

- **Status:** accepted (replaces the original plan of writing everything by hand)
- **Date:** 2026-10-15

## Context

The project exists so that I can learn **AI engineering**: agents, structured output, prompts,
evaluation, memory, multi-agent diplomacy, observability and cost. The game engine (map,
economy, combat, rules) is necessary, but building it teaches me little I don't already practise
in my day job.

## Decision

- **Claude Code writes and maintains the game**: the engine (`src/pax_agentica/engine/`), the
  rule-based bots (`players/`), the runner, the CLI and the replay viewer. The engine is fully
  tested, and its rules are documented in [`docs/game-rules.md`](../game-rules.md).
- **I write the AI rulers** (`src/pax_agentica/agents/`) and everything around them: prompts,
  validation, retries, frameworks (google-genai, then ADK), memory, evaluation and tournaments.
  There, Claude is a tutor and reviewer, not the author (see `CLAUDE.md`).
- The contract between the two is small and stable: `view_for(state, nation) -> NationView`,
  `Player.decide(view) -> Orders` and `Orders.model_json_schema()`.

## Consequences

- I can start on the AI part straight away, against a complete game and competent baseline bots.
- I have to treat the engine as a dependency I understand but did not write: its rules document
  and its tests are the specification I rely on.
