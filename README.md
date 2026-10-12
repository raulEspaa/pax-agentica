# Pax Agentica

**A strategy game where every nation is ruled by an AI agent.** They produce, trade, sign pacts,
betray each other and go to war. You watch history unfold, and one day you take a throne yourself.

[![CI](https://github.com/raulEspaa/pax-agentica/actions/workflows/ci.yml/badge.svg)](https://github.com/raulEspaa/pax-agentica/actions/workflows/ci.yml)
![Status](https://img.shields.io/badge/status-milestone%200%20%C2%B7%20skeleton-b8860b)
![Python 3.13](https://img.shields.io/badge/python-3.13-3776ab)

<p align="center"><img src="docs/assets/cover.jpg" alt="An old-style map of three AI-ruled realms: Northreach, Ostmark and Southvale" width="760"></p>

## The idea

A map of regions. A handful of nations, each governed by an AI with its own personality: the
warmonger, the merchant, the schemer. Every turn they read **only what their nation can see**,
talk to each other in plain language, propose treaties, and choose their moves. Pacts are
promises, not rules: a nation can break one, and the others will remember.

**The AI proposes, the engine decides.** Agents return structured actions; a deterministic game
engine checks that each move is legal and resolves it. No language model ever touches the game
state directly, so a clever (or confused) agent can't cheat its way to victory.

## Roadmap

Each milestone ends with something you can run and watch. It's built in order, one at a time.

| # | Milestone | What you see | Status |
|---|-----------|--------------|--------|
| 0 | **Foundations** | A repo with tests, linting, types and CI | ✅ |
| 1 | **A world without AI** | `pax play --seed 1`: three rule-based bots play 30 turns in the terminal and one of them wins | ⏳ next |
| 2 | **The first AI ruler** | One nation is governed by Gemini and plays against two bots | |
| 3 | **Every throne an AI** | Rulers with personalities; the same world plays out differently | |
| 4 | **Diplomacy** | Messages, pacts and trade between nations, and betrayals | |
| 5 | **A map to watch** | A web viewer that replays the game turn by turn, with an AI chronicler | |
| 6 | **Memory** | Nations remember who betrayed them | |
| 7 | **Tournaments** | Many seeded games: which personalities win, who keeps their word, what it costs | |
| 8 | **Online** | Deployed, and you can play as one of the nations | |

## How it's built

This is a learning project, built **by hand**, one milestone at a time:

- **Spec first, then tests, then code.** Every feature starts as a one-page spec with testable
  acceptance criteria ([`specs/`](specs/README.md)), then test-driven development: red, green,
  refactor.
- **AI as a tutor, not an author.** Claude Code reviews, questions and explains, but the game
  engine and the agents are written by me. The rules it follows are in [`CLAUDE.md`](CLAUDE.md).
  The tooling (CI, Makefile, this skeleton) was set up with its help.
- **Decisions are written down** as ADRs ([`docs/adr/`](docs/adr/README.md)), and every finished
  milestone gets a learning note ([`docs/learning/`](docs/learning/README.md)).

## Run it

Requirements: [uv](https://docs.astral.sh/uv/) and GNU make.

```bash
make sync    # create .venv from uv.lock (installs Python 3.13 if needed)
make check   # lint, types, tests
```

There is no game to play yet: milestone 1 comes next.

## Repository map

| Path | What |
|------|------|
| `src/pax_agentica/` | The game: engine, rules and (later) the AI rulers |
| `tests/` | Tests, written before the code they test |
| `specs/` | One folder per feature: spec, plan, tasks |
| `docs/vision.md` | What the game is and what the first version includes |
| `docs/adr/`, `docs/learning/` | Decisions and learning notes |
