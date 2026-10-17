# Translations

The game, its engine and everything the AI rulers read are in English. The page translates what
it shows as it shows it: `src/pax_agentica/web/i18n.js` watches the page and replaces every text
node, title, label, placeholder and tip by its entry in `src/pax_agentica/web/i18n/<lang>.json`.
The player picks the language in the Options window (or in the lobby); the browser's own language
is the first choice.

## The dictionary

Each entry is an English phrase and its translation. A phrase can have numbered holes:

```json
"{0} moves {1} regiments from {2} to {3}": "{0} mueve {1} regimientos de {2} a {3}"
```

What fills a hole is translated in turn when the dictionary knows it (province and crown names,
works, the lower-case titles of events), so the holes can be reordered freely. A pattern with
little fixed text of its own (`"{0} and {1}"`) applies only when its holes translate too, so it
never cuts an unknown sentence in half. The upper-case, lower-case and capitalised forms of a
phrase come for free; icons, quotes and a final full stop around a phrase are kept.

What players write (letters, proclamations, the names of tables and courtiers they choose) is
never translated: it sits inside `translate="no"`, or in a text area.

## Adding phrases, or a language

```bash
uv run python scripts/i18n_extract.py --missing es    # phrases the sources hold and es.json lacks
```

The extractor reads the page's templates, the engine's f-strings (event summaries, refusals), the
bots' letters, the fortune events and the static data. Some text is only built at run time; in the
browser, `PaxI18n.missing()` lists every phrase the page showed and could not translate.

For a new language, add its code to `LANGS` in `i18n.js` and to `languages` in `server.py`, and
write `i18n/<code>.json`. `tests/test_server.py` checks that every pattern keeps its holes.
