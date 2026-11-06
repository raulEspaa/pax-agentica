# 002 · The strategist: a monarch who rules by plan

- **Status:** Done
- **Milestone:** M2 (the Royal Council, phases 1–2)
- **Author:** Claude Code, at Raúl's request, from his decisions (2026-10-20)

## Why

A language model that gives every order every year has to read the whole view (some 76,000
tokens late in a game) and do the arithmetic of battles and budgets, which it does badly. A ruler
that only decides **strategy**, and leaves the tactics to the greedy bot, reads about 2,000 tokens
every second year and costs cents per game. Scripted plans already move a nation's final
standing by -40% to +80% against the plain bot (an experiment of 2026-10-19, 27 games a side),
so the quality of that strategy is worth measuring and improving.

## What

Each AI nation is ruled by **its monarch**: the model is told it *is* the reigning king, queen,
sultan or tsar of that nation, by name and title, with their age, skills, character, ambition and
story, and it decides as that person would, in the first person.

- **Every second year**, and at once when something grave happens, the monarch reads the compact
  view of the realm (`tools.compact_view`) and writes a `Plan` (`players/plan.py`): how to spend,
  what the army is for, what to take, whom to fight, befriend or spare, what to study, and why,
  in a line of their own voice.
- **Every year**, the greedy bot turns the current plan into orders. In years without a new plan,
  the last plan stands.
- The monarch **thinks before answering** (the model's reasoning is on), with a fast, inexpensive
  model that is still capable enough to plan well. The model and its thinking budget are
  settings, so that later evaluations can compare models.
- When the monarch dies, **the heir takes the throne and the council**: the next plan is written
  by the new monarch, as themself.
- A failing model never costs the nation its year: the last valid plan stands.
- Every call to the model is traced (prompt, plan, reasoning tokens, cost) when tracing is
  configured, and the game runs the same without it.

## Acceptance criteria

1. **Given** a game of 30 years, **when** the ruler plays it with a model that answers every
   time, **then** the model is asked for a plan in its first year and then every second year,
   and never more than once in a year.
2. **Given** a year in which a war starts or ends for the nation, a province of its own is lost,
   or a new monarch is crowned, **when** the ruler decides, **then** it asks for a new plan that
   year, even if the last one is a year old.
3. **Given** a reigning monarch, **when** the ruler asks for a plan, **then** the request names
   the nation and the monarch by title and name, and gives their age, skills, traits, ambition
   and story; **and given** a succession, the next request names the new monarch.
4. **Given** a plan from the model, **when** the ruler decides a year, **then** it returns exactly
   the orders the greedy bot gives with that plan, and its thoughts begin with "The plan:" and the note.
5. **Given** a model that raises, times out (after 30 seconds) or returns something that is not
   a valid plan, **when** the ruler decides, **then** it retries once, and if that fails it plays
   the year with the last valid plan (or with no plan, before the first), records why in its
   thoughts, and never forfeits the year.
6. **Given** a plan that names provinces or courts that do not exist, or the nation itself as an
   enemy, **when** the ruler accepts it, **then** those names are dropped, the rest of the plan
   stands, and the thoughts say what was dropped.
7. **Given** a request for a plan, **when** it is sent, **then** it is under 20,000 characters
   (about 6,000 tokens), rules and schema included.
8. **Given** the same seed and a scripted fake model, **when** a game is played twice, **then**
   both games are identical: the ruler adds no randomness of its own.
9. **Given** no tracing credentials, **when** the ruler plays, **then** it plays the same and
   reports nothing; **given** credentials, each request appears as one trace with the nation,
   the year, the model, the tokens and the cost.

## Out of scope

- Letters, answers to proposals and negotiation: the diplomat, spec 003. Until then the greedy
  bot answers every proposal, guided by the plan's `peace_with` and `befriend`.
- Guarding against prompt injection in letters: spec 004.
- Memory across plans (a chronicle, retrieval): spec 005. The monarch sees only this year's
  compact view and their own last plan.
- Tools the model can call (battle odds, targets, MCP): spec 006.
- Durable checkpoints in Postgres and replaying a single decision: phase 8.
- Choosing the final model: an evaluation (tournament against the bot and against scripted
  plans), not this spec.

## Open questions

- Which model by default: Gemini 3.1 Flash-Lite with thinking ($0.25 / $1.50 per million
  tokens, about $0.07 per nation per game) or Gemini 3 Flash ($0.50 / $3, about $0.15)? Start
  with 3.1 Flash-Lite; the evaluation of phase 3 decides.
- How much thinking: the lowest level that keeps plans valid and sensible, measured in phase 3.
