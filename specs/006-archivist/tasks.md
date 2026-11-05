# 006 · Tasks

- [x] 1. `google-adk` in the `ai` group; lift its OpenTelemetry cap to share langfuse's.
- [x] 2. `Archivist` with `search_archive`, sessions and the `grounded` check (criteria 1-3, 6).
- [x] 3. `Metered`: budget and Langfuse generation around every model call (criteria 4, 7).
- [x] 4. `max_llm_calls` per question (criterion 5).
- [x] 5. `pax_agentica.api`: `POST /ask`, 503 on a spent budget, 422 on a long question (criterion 8).
- [x] 6. `pax ask` and `pax api`.
- [ ] 7. A real run on an ingested game, with Raúl's approval: a handful of questions, grounded rate.
