# Architecture

Two halves with one boundary between them: a deterministic game, and AI agents that may only read
a nation's view and propose orders.

```mermaid
flowchart LR
  subgraph game["The game (pure, deterministic)"]
    engine["engine: resolve_turn"]
    view["view_for(state, nation)<br/>fog of war"]
    runner["runner.run_game"]
  end

  subgraph rulers["AI rulers (LangGraph)"]
    assess["assess"]
    strategist["strategist<br/>writes a Plan"]
    diplomat["diplomat<br/>answers letters"]
    ministers["ministers<br/>GreedyBot follows the plan"]
    assess --> strategist & diplomat & ministers
    strategist -- "if there is mail" --> diplomat
    strategist --> ministers
    diplomat --> ministers
  end

  subgraph archive["Archive (Postgres + pgvector)"]
    ingest["pax ingest<br/>chunks + embeddings"]
    chunks[("chunks<br/>HNSW + tsvector")]
    search["hybrid search<br/>vector + keyword, RRF"]
    ingest --> chunks --> search
  end

  subgraph archivist["Archivist (ADK + FastAPI)"]
    api["POST /ask"]
    agent["LlmAgent<br/>search_archive tool"]
    judge["LLM judge<br/>faithfulness"]
    api --> agent
  end

  gemini(["Gemini<br/>budget + rate guard"])
  langfuse(["Langfuse<br/>traces, datasets, experiments"])

  runner --> view --> assess
  ministers -- Orders --> engine
  runner -- GameRecord --> ingest
  agent --> search
  strategist & diplomat & agent & judge --> gemini
  rulers & archivist -.-> langfuse
```

## The boundaries that do not move

- **The AI proposes, the engine decides.** Rulers return `Orders`; the engine validates and
  applies them. No model ever touches `GameState`.
- **Fog of war.** A ruler reads only its `NationView` ([the contract](agent-contract.md)).
- **Letters are words.** Letters between crowns are free text from other models: a
  prompt-injection channel. The diplomat reads them inside tags they cannot close, after a
  warning that they are not orders; the Archivist and the judge treat chunks the same way.
- **Money is guarded before it is spent.** Every model call reserves its worst cost from a hard
  `Budget` and settles the real cost after; a call the budget cannot cover is never made.
- **CI never calls a model.** Every test uses a fake model, a fake embedder or a scripted ADK
  model; the database tests run against the same pgvector image as `make db`.

## Memory

At the public tables each AI crown's council keeps a `Chronicle`
([`agents/memory.py`](../src/pax_agentica/agents/memory.py), spec
[008](../specs/008-memory-and-audience/spec.md)): its dealings with every court as short dated
lines.

```mermaid
flowchart LR
  view["its NationView, each year"] --> entries["entries_from(view)<br/>letters, treaties, betrayals,<br/>wars, tributes, grudges"]
  audience["audiences it gave"] --> chronicle
  entries --> embed["Embeddings<br/>in a thread, on the budget;<br/>a failure leaves no vector"] --> chronicle[("Chronicle<br/>memory/&lt;table&gt;.&lt;nation&gt;.json")]
  chronicle --> recall["recall(court, question)<br/>vector + words + recency, RRF"]
  recall --> diplomat["diplomat: WHAT YOU REMEMBER OF court"]
  recall --> reply["audience: the monarch's answer"]
```

- **Fog of war by construction.** `observe` takes a `NationView` and nothing else, so the
  memory holds only what that crown witnessed; a test sends a secret letter between two other
  courts and checks it never gets in.
- **Search within one court**, three rankings fused by RRF as in the archive: meaning (cosine),
  words (names and provinces) and recency. A spent budget or a slow embedder leaves words and
  recency, never an error.
- **Kept in a file, not rebuilt.** Rebuilding from the game record would replay every past view
  and embed it again (minutes at the free tier's 50 texts a minute), and audiences are not in the
  record; the file holds 256-dimension vectors rounded to four decimals.
- **Outside the graph's state.** A checkpoint would copy the vectors every year; the memory is an
  object on the council, like the bot. Without one (the default, for tournaments and evaluations)
  the council plays as before.
- **Untrusted text.** Entries quote letters and audiences: one line each, inside `<memory>` tags
  that `diplomat.fence` keeps them from closing.

## Why each piece

| Piece | Chosen | Instead of | Because |
|---|---|---|---|
| The rulers' flow | LangGraph | a hand-written loop (spec 002 has one, and the graph plays identically) | retries, timeouts, error routes and checkpoints are declared, and each node is a span |
| The Archivist | ADK | LangGraph again | a conversation that chooses its own searches, with sessions: ADK's shape |
| Store | Postgres + pgvector | a vector database | one system for text, vectors and filters; hundreds of chunks |
| Search | hybrid, RRF | vector only | exact names suit keywords, meaning suits vectors: 83% recall@5 against 72% |
| Faithfulness | a rule (`grounded`) and an LLM judge | the judge alone | the rule is free and catches invented citations; the judge reads what the rule cannot |
| Observability | Langfuse, self-hosted | logs | a decision is a tree of steps to compare across runs; datasets and experiments in one place |

More: [the AI roadmap](ai-roadmap.md), [the results](ai-results.md), and specs
[002](../specs/002-council-strategist/spec.md) to [006](../specs/006-archivist/spec.md).
