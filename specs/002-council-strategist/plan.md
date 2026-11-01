# 002 · Plan

## Design

```
NationView ──> Strategist.decide ──> is a plan due? ──no──────────────┐
                    │                    │ yes                        │
                    │                    v                            v
                    │        PlanModel.write_plan(request) ──> GreedyBot.follow(plan)
                    │                                                 │
                    └────────── Orders <── the bot's orders + the note ┘
```

- `agents/strategist.py`: `Strategist`, a `Player`, and `PlanModel`, the protocol every model obeys.
- Later steps add the monarch's prompt, plan checks, the budget and the Gemini client.

## Decisions

| Decision | Alternatives considered | Why this one |
|----------|-------------------------|--------------|
| `PlanModel` protocol between ruler and SDK | Call `google-genai` in the ruler | Tests run free, offline and deterministic; evaluations swap models without touching the ruler |
| Plain Python, no framework | LangGraph from the start | One call with a retry has no graph to draw; porting in phase 4 shows what LangGraph adds |
| `GreedyBot` is held, not inherited | `class Strategist(GreedyBot)` | The ruler only needs the bot's public `follow` and `decide`, so bot internals can change freely |
| Budget guard before the first real call | Add it with tracing | Cost is a hard constraint for this project |

## Risks / unknowns

- **Timeouts.** A plan may take about 60 s (30 s and one retry), so the runner's `timeout` must be
  larger, or the runner forfeits the year that criterion 5 promises to keep.
- **Rate limits.** The runner asks all crowns at once: the Gemini client needs a concurrency limit.
- **Model.** Spec 002 starts with Gemini 3.1 Flash-Lite; its current price is checked on the official
  page before the first real call.
