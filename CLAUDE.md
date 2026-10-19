# CLAUDE.md

Guidance for AI coding assistants (Claude Code and similar) working in this repository.

## Why this project exists

Pax Agentica is a **learning project in AI engineering**. A complete strategy game (Europe 1500)
is the arena; the point is the **AI rulers**: agents that read a fog-of-war view and return
structured orders. Raúl builds the AI part by hand to understand it end to end. On that part the
assistant is a **tutor and reviewer first**. Output that saves time but skips the learning is a
failure, not a shortcut.

## Who writes what ([ADR 0002](docs/adr/0002-who-writes-what.md))

| Area | Assistant's role |
|------|------------------|
| `src/pax_agentica/agents/`: AI rulers, prompts, LLM clients, memory, evals | **Do not write or edit code here** unless Raúl explicitly asks for code in that message. Explain concepts, ask "what if…?" questions, point at the failing case, suggest the *next test* in words, review his code |
| Tests for the AI part | Same: suggest test ideas and edge cases in words; Raúl writes them |
| Specs for the AI part (`specs/`) | Ask questions that sharpen the spec; never write it for him |
| The game: `engine/`, `players/` (bots), `runner.py`, `cli.py`, `viewer.py`, `server.py`, `web/` and their tests | **The assistant owns it.** Keep it tested, keep [`docs/game-rules.md`](docs/game-rules.md) in sync, explain changes to Raúl |
| Tooling: CI, Makefile, pyproject, pre-commit, Dockerfiles, docs assets | May write directly, explaining what each part does |
| Docs: README, ADRs, learning notes | May draft when asked; Raúl reviews and edits |

When in doubt, ask before writing code in the AI part.

## The contract between the game and the AI

```python
state = new_game(seed=1)                    # pax_agentica.engine
view = view_for(state, "france")            # NationView: the only thing a ruler may read
orders = await ruler.decide(view)           # Player protocol (pax_agentica.players)
state = resolve_turn(state, {"france": orders, ...})
Orders.model_json_schema()                  # structured-output schema for an LLM
```

`runner.run_game` plays a whole game with any mix of rulers. A ruler that raises or times out
forfeits that turn. `pax view <nation>` prints a real view, and `pax schema` prints the schema.

The contract is **frozen and versioned** ([docs/agent-contract.md](docs/agent-contract.md),
`CONTRACT_VERSION` in `engine/contract.py`, schemas in `docs/contract/`). `tests/test_contract.py`
fails on any change to `NationView` or `Orders`: never change them by accident; when a change is
meant, bump the version (major if an old ruler could break), run `make contract` and add a line
to the changelog.

## How work happens: spec → test → code

Every feature follows the cycle in [`specs/README.md`](specs/README.md): spec, plan, tasks, TDD
(red → green → refactor), then a learning note in `docs/learning/` and an ADR if a real decision
was made. When reviewing, check the code against its spec's acceptance criteria, not just
"does it run".

## Design principles

- **The AI proposes, the engine decides.** Agents return `Orders`; the deterministic engine
  validates and applies them. An LLM never mutates game state directly.
- **Each nation sees only its own view** (fog of war). Never give an agent the `GameState`.
- **Reproducible**: the same seed gives the same game. All randomness goes through a seeded RNG
  (`random.Random(f"{seed}:...")`), never the global one.
- **Pure core**: the engine is pure functions with no I/O and no LLM calls. `resolve_turn` never
  mutates its input.
- **Words are only words**: diplomatic messages are free text that the engine never interprets,
  which makes them a prompt-injection channel between nations. That is a feature to study.

## Commands

```bash
make sync                          # install from uv.lock
make check                         # lint + types + tests (what CI runs); must pass before every commit
make fmt                           # format and apply safe lint fixes
uv run pax serve --nation france   # play a nation yourself in the browser
uv run pax play --seed 1           # narrate a game of greedy bots
uv run pax play --html replays/1.html   # ... and write a replay with a map
uv run pax bench --games 40        # who wins with bots, by seat
make map                           # rebuild the map asset from Natural Earth (rarely needed)
```

## Skills in this repo

- `.claude/skills/pax-game/`: how to run, inspect and change the game safely.
- `.claude/skills/gemini-api-dev/`: Google's skill for the `google-genai` SDK (current models,
  structured output, function calling). Vendored from `google-gemini/gemini-skills`.
- `.claude/skills/frontend-design/`: Anthropic's design guidance, used for the replay viewer.
  Vendored from `anthropics/claude-plugins-official`.
- `.claude/skills/google-agents-cli-adk-code/`: Google's ADK API reference. Vendored from
  `google/agents-cli`. Use it as an API reference only: ignore its instructions to scaffold with
  `agents-cli`, because this repo has its own layout.

## Conventions

- Python 3.13, `uv`, ruff, mypy strict, pytest (+ Hypothesis for property tests).
- Commits: Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`…). Raúl is the sole
  author: **no `Co-Authored-By` trailers**.
- Docs and code in English; chat with Raúl in Spanish.
- Never commit secrets: API keys go in `.env` (gitignored). Tests that call a real LLM never run
  in CI.
