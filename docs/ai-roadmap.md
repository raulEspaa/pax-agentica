# AI roadmap: from a finished game to a council of AI rulers

Drafted 2026-11-01. The engine roadmap in [roadmap.md](roadmap.md) stays as the record of the game.

## Minimum viable plan (2026-11-05)

Time is short, so the ten phases below shrink to a minimum viable product: AI rulers that play,
are traced and are measured, plus one vertical slice that answers questions about the games they
played. The phases below stay as the record of the full plan; this is the order of work.

| Step | Covers | Status |
|---|---|---|
| Strategist, Gemini, budget, Langfuse traces | phases 1, 2 | Done |
| Evaluation: 20 situations scored by rules, as Langfuse experiments ([spec 003](../specs/003-strategist-evaluation/spec.md)) | phase 3, reduced | Done |
| Council in LangGraph with a diplomat; letter defence and checkpoints ([spec 004](../specs/004-council-graph/spec.md)) | phases 4, 5, 8, reduced | Done; red team and a 3-seed pilot in [results](ai-results.md) |
| **A. The archive:** `pax ingest` loads finished games and the rules into Postgres, with embeddings, pgvector and hybrid search (vector + full text, RRF), and a recall measure on a dozen questions | phase 6, reduced | Done |
| **B. The Archivist:** an ADK agent that answers "why did France attack Spain in 1512?" from the archive with citations, served by FastAPI ([spec 006](../specs/006-archivist/spec.md)) | phase 9, reduced | Done |
| **C. Closing:** README, [architecture](architecture.md), [results](ai-results.md), merge to `main` | phase 10 | Done but the merge, which Raúl makes |

Cut from the MVP: rulers that read their own chronicle (memory with the fog-of-war filter), the
prompt-injection red team, MCP, a human in the loop, decisions streamed by SSE, the Postgres
checkpointer, paired tournaments with bootstrap intervals, an LLM judge, and the written LangSmith
comparison. Each is a later addition, not a missing piece.

## Goals

1. **A portfolio project that survives a technical interview.** Every technology solves a problem
   the game really has, and comes with a measured result and a rejected alternative.
2. **Raúl understands everything, little by little.** Claude Code drafts a v0 that Raúl then reviews
   and rewrites; each step ends with a guided review (below). Nothing moves on until he can explain
   it.
3. **Rulers measurably better than the greedy bot,** or an honest report of why they are not.

## What the game already gives us

| Asset | Why it matters |
|---|---|
| `Player` protocol, `runner.run_game` | Any agent framework plugs in behind one method, so frameworks can be compared on equal terms |
| `Plan`, `GreedyBot(plan=...)`, `combine` | The strategist only has to produce a small structured object |
| `compact_view`, `inbox`, `TOOL_SPECS`, `call_tool` | Prompt inputs and tools are ready |
| `pax tournament`, seeded games | A reproducible evaluation arena, which most agent projects lack |
| `GameRecord` per game, 50 turns, 9 nations | A real, structured data source to ingest |
| Fog of war | A true access-control requirement for retrieval, not an invented one |
| Letters between nations | A genuine prompt-injection attack surface |

## Stack

| Need | Choice | Why this | Rejected, and why |
|---|---|---|---|
| Model calls | `google-genai`, behind our own `PlanModel` protocol | Already chosen by the specs; the protocol lets tests use a fake and evals swap models | Calling the SDK from the ruler: untestable without network |
| Orchestration of the council | **LangGraph** | Explicit state, branching, checkpoints and interrupts fit a council with several roles | CrewAI: hides the control flow we want to study. Hand-written loop: fine for one call (phase 1), poor once there are pauses and resumes |
| A second, differently shaped agent | **ADK** for the Archivist | A conversational agent with tools and sessions, a different shape from the rulers | ADK for the rulers too: two frameworks on one job has no technical reason |
| Observability, datasets, scores | **Langfuse**, self-hosted | Open source, framework-neutral, and sees both LangGraph and ADK through one place | Only LangSmith: quota too small (below) and tied closer to one ecosystem |
| LangGraph debugging comparison | **LangSmith**, free tier, opt-in by environment variable, small runs only | 5,000 traces a month is about 20 full games at roughly 250 plans a game, so it cannot carry tournaments, but it can carry a written comparison | Sending everything to both: burns the quota and adds nothing |
| Data store | **Postgres + pgvector** | One database for memory, vectors and checkpoints; the corpus is far below the sizes that justify more | Qdrant or Pinecone: a second system to keep in sync, for no measurable gain at this size |
| Search | Hybrid: vector + `tsvector`, merged with RRF | Exact names (`flanders`, a treaty id) suit keywords, meaning suits vectors. Measured against each alone | Reranker: added only if the retrieval eval shows a gap |
| Embeddings | `gemini-embedding-001` to start | Text-only corpus, same provider. Confirm the price on the official page in phase 6 | `gemini-embedding-2`: multimodal we do not need, at a higher listed price |
| Ingestion | Plain, typed Python pipeline, run by `pax ingest` | Small batch job, idempotent by content hash | Airflow, Kafka, dlt: machinery for problems we do not have |
| API | **FastAPI** (already a dependency), in a new `pax_agentica.api` app | Streaming decisions, human approval, the Archivist | Adding it to `server.py`: the public tables image would inherit LLM dependencies |
| Tools protocol | **MCP** server over `TOOL_SPECS` | The calculators already exist; MCP makes them usable by any client | A framework-specific tool layer only |

Explicitly left out, because nothing in the project needs them: fine-tuning, Kubernetes, a
knowledge graph, LangChain chains beyond what LangGraph itself requires, and A2A.

**Packaging.** AI libraries go in an optional dependency group. The `Dockerfile` installs all
non-dev dependencies, so adding them to `dependencies` would bloat the multiplayer image deployed
on every push to `main`.

**Boundaries that do not move.** The engine stays pure, with no LLM imports. Agents read only
`NationView`. CI never calls a real model and holds no keys.

## Phases

Each phase ends with something runnable. Sizes are relative: S, M, L.

### 0. Method and foundations (S)

- Update the working method in `CLAUDE.md`.
- `compose.yaml` with Postgres + pgvector and Langfuse, `.env.example`, `make env`, `db`, `langfuse`
  and `infra-down`.
- Fill in `docs/vision.md` from a short interview with Raúl.

The optional dependency group and the `pytest` marker for database tests arrive with the first
library and the first such test, not before.

**Learn:** why Compose, secrets in `.env`, what each Langfuse container does.

### 1. The strategist (spec 002, criteria 1-8) (M)

`agents/` with a `PlanModel` protocol, a fake, a Gemini client with structured output and thinking,
prompts as versioned files, plan sanitising, replan triggers and fallback. Plain Python, no
framework: the framework earns its place later, and we will have felt what it replaces. Register
it in the CLI so `pax tournament --player france=strategist` works.

**Cost comes first.** A hard budget stops any run before it overspends, and exists before the first
real model call. All tests use the fake. Each real run is approved by Raúl with an estimate.

Known traps to handle:

- **Timeouts.** The spec allows 30 s and one retry, so up to about 60 s per plan. The runner forfeits
  a ruler at its own `timeout`, which must be larger, or criterion 5 can never hold.
- **Rate limits.** The runner asks all nine crowns at once with `asyncio.gather`: the client needs
  a concurrency limit and backoff.
- **Model default.** The spec names Gemini 3.1 Flash-Lite, while the vendored skill also lists newer
  models. Keep the setting and let phase 3 decide.

**Learn:** structured output, thinking budgets, why the fake comes first.

### 2. Observability (spec 002, criterion 9) (S)

A trace per decision in Langfuse (prompt version, plan, tokens, cost, nation, year), and a no-op
without credentials.

**Learn:** traces and spans, OpenTelemetry, cost accounting. **Why not just logs:** a decision is a
tree of steps you want to compare across runs.

### 3. Evaluation (M) — the most valuable phase for a CV

- **Offline:** a dataset of real situations sampled from recorded games, stored in Langfuse. Checks:
  valid plan, real names, sensible against simple rules, and an LLM judge only where rules cannot
  decide.
- **Online:** tournaments on paired seeds with one AI nation against bots, in every seat (the seats
  are unequal), with confidence intervals by bootstrap. Baselines: greedy bot, scripted plans.
- **Interesting to watch** ([vision](vision.md)): winning is not enough, so also measure what a
  spectator would notice, such as conquests, wars started, changes of plan and reversals of fortune.
- **Regression:** recorded model answers replayed in CI, so prompts are checked at no cost.
- **Output:** the choice of default model and thinking level, with evidence, closing the open
  questions of spec 002.

**Budget:** at the spec's estimate of $0.07 per nation per game, 40 games in each of 9 seats is
about $25. Re-measure in phase 2 before running it.

### 4. The diplomat and the council (spec 003) (L)

Port the strategist to **LangGraph** and add a diplomat for letters and proposals, using `inbox`
and `combine`. Node functions are kept from phase 1, so the port is small and shows what the
framework adds. In-memory checkpoints for now.

Add advisors (`Orders.counsel` exists for them) only if a tournament shows they beat a simpler
council; otherwise the negative result is reported. Write the LangSmith vs Langfuse comparison here.

**Learn:** state, reducers, conditional edges, supervisor vs fixed graph.

### 5. Prompt injection (spec 004) (M)

A red team: nations and scripted letters that try to manipulate rulers. Metric: attack success rate
with and without defences (separating data from instructions, a validation layer, a reader model
with no authority). The engine already limits the damage, so the interesting harm is bad strategy.

**Learn:** why injection cannot be fully solved, and defence in depth.

### 6. Ingestion, memory and RAG (spec 005) (L)

**Ingestion.** `pax ingest` loads three sources into Postgres, with content hash, source version and
embedding model recorded: game rules, finished `GameRecord`s, and public-domain or suitably licensed
history about the period's rulers and treaties (licences checked per source).

**Three retrieval uses, each justified:**

| Use | Who reads it | Key constraint |
|---|---|---|
| Chronicle: what this nation lived through | That nation's ruler | **Only what was in its own views.** A test proves no secret crosses the fog |
| Precedents: what worked in past games | Rulers | Built only from training seeds, evaluated on others, or the evaluation leaks |
| Rules and history | Rulers, Archivist | Public |

**Measured twice.** Retrieval quality on a labelled question set (recall@k, MRR) for keyword, vector
and hybrid, and across chunking choices. Then the question that matters: do rulers with memory win
more in a tournament? If not, that is reported.

**Learn:** embeddings, chunking, HNSW, RRF, metadata filtering as access control.

### 7. Tools and MCP (spec 006) (M)

Battle odds and targets as tools for the model, and an MCP server exposing them. Evaluate better
plans against the extra tokens and latency.

### 8. Durable execution (M)

The LangGraph Postgres checkpointer. A long tournament that dies resumes where it stopped, and a
single decision can be reopened and replayed with another prompt.

**Learn:** checkpoints, idempotency, what must not run twice.

### 9. API, a human in the loop and the Archivist (L)

- **FastAPI:** start AI games as background jobs, stream decisions by SSE, read a decision's trace.
- **Human in the loop:** a LangGraph interrupt lets a player act as the monarch's chancellor and
  approve or edit a plan in the browser.
- **The Archivist (ADK):** ask "why did France betray Spain in 1531?" and get an answer cited from
  chronicles and traces. Evaluated on faithfulness to its sources. It also covers the chronicler of
  the original milestone 5.

### 10. Public demo and portfolio (M)

Recorded games browsable with their reasoning, so that visitors spend no LLM budget; live AI only
behind a code and a budget. Architecture diagram, results page, and README rewrite.

## Where it is safe to stop

| After phase | What the CV can honestly say |
|---|---|
| 3 | LLM agent with structured output, tracing and a statistically sound evaluation |
| 6 | Plus LangGraph multi-agent, prompt-injection testing, ingestion and an evaluated hybrid RAG |
| 9 | Plus durable execution, human in the loop, FastAPI, ADK and MCP |

## How we work in each phase

1. **Before code:** Claude Code writes spec, plan and tasks; Raúl approves the decisions.
2. **While coding:** spec, then tests, then code, in small commits, with `make check` passing.
3. **Guided review**, delivered at the end of each phase:
   - the reading order of the files, shortest path first;
   - commands to run and what to look for, including the trace in Langfuse;
   - each decision: the alternatives, and why this one won;
   - each configuration setting: what it does and what breaks if it changes;
   - three interview questions for Raúl to answer aloud, plus one small change to try himself.
4. **Closing:** a learning note in `docs/learning/`, an ADR for real decisions, and the results.

## Risks

| Risk | Answer |
|---|---|
| Reading code is not the same as being able to write it | The small change and the questions in each review; slow down if they fail |
| Technologies added for the CV make the system worse | Each one has to pass an evaluation or a written comparison, or it is removed |
| Tournaments cost too much | Budget guard, recorded answers in CI, small pilots before full runs |
| Tournament results are noise | Paired seeds, all seats, intervals; the spread between seeds is known to be wide |
| Library APIs move quickly | Pinned by `uv.lock`, checked against official docs at the start of each phase |
| Rule changes invalidate results | Record the contract version and git commit with every evaluation |
| Licensing of Langfuse or LangGraph server parts | Use only open source parts: Langfuse core, the LangGraph library |
