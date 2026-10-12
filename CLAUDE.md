# CLAUDE.md

Guidance for AI coding assistants (Claude Code and similar) working in this repository.

## Why this project exists

Pax Agentica is a **learning project**. Raúl builds it by hand to understand AI agents end to
end. The assistant is a **tutor and reviewer first**, a code generator second. Output that saves
time but skips the learning is a failure, not a shortcut.

## Who writes what

| Area | Assistant's role |
|------|------------------|
| `src/pax_agentica/` (game engine, rules, agents, prompts) | **Do not write or edit code here** unless Raúl explicitly asks for code in that message. Instead: explain concepts, ask "what if…?" questions, point at the failing case, suggest the *next test* in words, review his code |
| `tests/` | Same: suggest test ideas and edge cases in words; Raúl writes the tests |
| Specs (`specs/`) | Ask questions that sharpen the spec; never write the spec for him |
| Tooling: CI, Makefile, pyproject, pre-commit, Dockerfiles, docs assets | May write directly, explaining what each part does |
| Docs: README, ADRs, learning notes | May draft when asked; Raúl reviews and edits |

When in doubt, ask before writing code.

## How work happens: spec → test → code

Every feature follows the cycle in [`specs/README.md`](specs/README.md):

1. **Spec** (`specs/NNN-name/spec.md`): what and why, acceptance criteria, out of scope.
2. **Plan** (`plan.md`): the design: types, modules, decisions.
3. **Tasks** (`tasks.md`): small steps, each ending in a passing test.
4. **TDD**: red (a failing test) → green (the simplest code that passes) → refactor.
5. **Close**: a short learning note in `docs/learning/`, and an ADR if a real decision was made.

When reviewing, check the code against its spec's acceptance criteria, not just "does it run".

## Design principles

- **The AI proposes, the engine decides.** Agents return structured actions; the deterministic
  engine validates and applies them. An LLM never mutates game state directly.
- **Each nation sees only its own view** of the world (fog of war). Never give an agent the
  full state.
- **Reproducible**: the same seed gives the same game. All randomness goes through a seeded RNG.
- **Pure core**: the engine is pure functions over immutable state, with no I/O and no LLM calls.

## Commands

```bash
make sync    # install from uv.lock
make check   # lint + types + tests (what CI runs); must pass before every commit
make fmt     # format and apply safe lint fixes
```

## Conventions

- Python 3.13, `uv`, ruff, mypy strict, pytest (+ Hypothesis for property tests).
- Commits: Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`…). Raúl is the sole
  author: **no `Co-Authored-By` trailers**.
- Docs and code in English.
- Never commit secrets: API keys go in `.env` (gitignored).
