# Specs: how a feature gets built

Pax Agentica follows a lightweight **spec-driven** and **test-driven** workflow. Every feature
gets a folder here, numbered in order:

```
specs/
├── _template/            copy this to start a feature
├── 001-world-and-state/  (example of what comes first)
└── 002-...
```

## The cycle

| Step | File | Question it answers |
|------|------|---------------------|
| 1. Spec | `spec.md` | **What** are we building, **why**, and how do we know it works? |
| 2. Plan | `plan.md` | **How**: types, modules, data flow, decisions and their alternatives |
| 3. Tasks | `tasks.md` | In which **small steps**? Each one ends with a passing test |
| 4. TDD | `tests/`, `src/` | Red: write a failing test. Green: the simplest code that passes. Refactor |
| 5. Close | `docs/learning/` | What did I learn? Did a decision deserve an ADR? |

## Rules

- **The spec comes first and stays short.** One page. If it needs more, the feature is too big:
  split it.
- **Acceptance criteria are testable.** Write them as *Given / When / Then*; each one becomes at
  least one test.
- **Out of scope is explicit.** What this feature does *not* do is as important as what it does.
- **Specs can change**, but in the spec first, then in the code.
