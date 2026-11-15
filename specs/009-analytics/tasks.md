# 009 · Tasks

- [x] 1. Row models (`analytics.py`) and BigQuery schemas (`scripts/bigquery/*.json`), with a test
      that they match field by field and that emitted rows fit them (criterion 1).
- [x] 2. `Analytics.emit`: append to `<kind>/dt=<day>/<table>.<writer>.ndjson`, log and go on on
      any error (criterion 6).
- [x] 3. `agents/meter.py`: a `Meter` in a context variable; `Budget.settle` charges it.
- [x] 4. `MeteredModel` and `Recorded` in `agents/tables.py`: a `decisions` row per decision;
      the concurrency and timeout tests (criteria 2-4).
- [x] 5. The lobby: a `games` row on close, the table's AI spend and every human crown kept in
      its meta (criterion 5).
- [x] 6. `pax analytics export` and `pax tournament --save` (criterion 7).
- [x] 7. `scripts/bigquery_ddl.py`, `scripts/bigquery_setup.sh` and the saved queries (criterion 8).
- [x] 8. docs/analytics.md, docs/deploy.md.
- [ ] 9. Run `scripts/bigquery_setup.sh` in the project, and the queries on the first real rows.
- [ ] 10. Wire `agents.tables.audience` into the audience chat when it lands.
