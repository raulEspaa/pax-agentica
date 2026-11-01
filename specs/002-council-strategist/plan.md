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
- `agents/prompts.py`: `build_request(view, last_plan)` writes the `PlanRequest` a model reads.
- `agents/checks.py`: `clean_plan(plan, view)` drops what names nothing real and says what.
- `agents/budget.py`: `Budget`, which sets money aside before each call and refuses past its limit.
- `agents/gemini.py`: `GeminiModel`, the `PlanModel` for Google's models, on the Interactions API.

## Decisions

| Decision | Alternatives considered | Why this one |
|----------|-------------------------|--------------|
| `PlanModel` protocol between ruler and SDK | Call `google-genai` in the ruler | Tests run free, offline and deterministic; evaluations swap models without touching the ruler |
| Plain Python, no framework | LangGraph from the start | One call with a retry has no graph to draw; porting in phase 4 shows what LangGraph adds |
| `GreedyBot` is held, not inherited | `class Strategist(GreedyBot)` | The ruler only needs the bot's public `follow` and `decide`, so bot internals can change freely |
| Prompts as Python text with a `PROMPT_VERSION` | Files in a folder; Langfuse prompt management | Git already versions them, a run stays reproducible offline, and nothing new has to be packaged |
| System text for who and how, user text for this year | One string | The rules open every request identically, which providers can cache, and the two kinds of text stay apart |
| Schema sent as structured output | Described in the prompt | The provider enforces it, and the words are not spent twice |
| Drop bad names and keep the rest | Reject the plan and ask again | A retry costs money for one wrong name, and most of a plan is still good |
| Check names against the view | Enums of ids in the schema | The schema would grow with 104 provinces, and only the view knows who is alive |
| Catch `Exception`, never `BaseException` | Catch everything | A cancellation from the runner must still stop the ruler |
| No pause before the retry | Exponential backoff here | Waiting for rate limits belongs in the Gemini client, the only part that knows the provider's errors |
| A failed year asks again next year | Wait for the usual two years | The realm is already without a fresh plan, and the budget bounds the cost |
| Budget guard before the first real call | Add it with tracing | Cost is a hard constraint for this project |
| Reserve the worst cost, then settle the real one | Add up costs after each call | Nine crowns ask at once, and the cost is known only afterwards: only a reservation really holds the limit |
| A failed or cancelled call is charged its worst cost | Charge nothing | It may have been billed: better to stop early than to overspend |
| One SDK retry, counted in the reservation | The default of three; forcing none with `attempts=-1` | The SDK has no public way to none, and the one left waits out a 429. Reserving both sends keeps the limit |
| Tests with the real SDK against a local server | Mock the SDK | Checks the real requests and answers at no cost, and it caught the hidden retries |
| Interactions API | `generate_content` | The vendored Gemini skill and current docs use it for new work; `store=False` keeps our prompts off Google's history |

## Risks / unknowns

- **Timeouts.** A plan may take about 60 s (30 s and one retry), so the runner's `timeout` must be
  larger, or the runner forfeits the year that criterion 5 promises to keep.
- **Rate limits.** The runner asks all crowns at once: the client allows 4 calls at a time, and the SDK
  retries a 429 once. Real runs will show if that is enough.
- **Model.** Spec 002 starts with Gemini 3.1 Flash-Lite; its current price is checked on the official
  page before the first real call.
