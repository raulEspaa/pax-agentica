# Playing with friends

`pax host` serves **tables**: games where several people each rule a nation and bots rule the
rest. It is how the game gets tested by people before the AI rulers arrive, and the same
`NationView` and `Orders` go through it as through an AI.

## How a table works

- Anyone opens a table from the lobby: a title, a throne, how many years, and an optional
  **clock** per year (3 minutes to a day). The seed is random unless you give one.
- Share the lobby link. Friends write their name and **take** any throne a bot still holds,
  before the first year or in the middle of the game.
- A year passes once **every seated player** has ended it. With a clock, it also passes when
  time runs out. The page sends the orders you are preparing as you go (`POST
  /api/t/{id}/draft`): whoever has not pressed "End the year" when the clock runs out (or when
  the others stop waiting) has those orders carried out. Until the year passes you can change
  your orders and send them again.
- The page shows the clock and who is still deciding in a pill in the top bar, and picks up the
  new year by itself.
- Each seat has a **secret token**, kept by your browser. The lobby gives a *seat link* to
  open the same seat on another device: anyone with that link plays your nation.
- Letters, proposals, alliances and peace treaties between players go through the game's own
  diplomacy, exactly as they will between AI rulers.
- **Leave the table** gives your throne back to a bot. Once you have ended the year, you can
  stop waiting for an absent friend after ten minutes (**Don't wait for them**): they do
  nothing that year.
- A table closes when its last player leaves, after three days without anyone playing, or
  when the game ends; it keeps its replay for a week.
- The full replay, with every ruler's private thoughts, opens only when the game is over.
- **How to play** opens a five-step guide (it also opens on a player's first visit), and
  **Send feedback** leaves a note for whoever runs the server.

## On your own network

```bash
make host        # pax host --host 0.0.0.0 --port 8000
```

Friends on the same network open `http://<your machine's address>:8000`. Tables are saved in
`saves/tables/` after every year and come back when the server restarts.

## On the internet

The tables run on Cloud Run, and every push to `main` that passes CI is deployed by itself:
see [`deploy.md`](deploy.md) for how it works. It lives at <https://pax-tables-clysgkcjqq-ew.a.run.app> and is **open**: anyone
can open a table or take a seat, with no login and no code.

Being open, it caps itself (`multiplayer.py`): at most **12 tables open at once** and **20 new
tables in any hour**, counted for everyone together (a cap per address could be dodged by faking
a header). Abandoned tables close after half an hour.

**The AI council at a table.** Whoever opens a table may set the AI council (the strategist and
the diplomat on Gemini, [`agents/council.py`](../src/pax_agentica/agents/council.py)) on up to two
other crowns (`"ai": ["england"]`; the lobby offers one, an old rival of yours). It needs
`GEMINI_API_KEY` and `PAX_AI_DAILY_USD` on the server
([`agents/tables.py`](../src/pax_agentica/agents/tables.py)); without them the lobby does not
offer it. One model and one **daily budget** serve every table, and what the day spent is saved
beside the tables, so a restart does not hand the money out twice. When it is spent, new tables
cannot ask for the council, and the councils already playing keep their last plan and play on
through their bot: a game never stops for the budget. A 50-year game with one AI crown costs
about $0.15, so $1 a day is about six games.

To close it again, set `PAX_INVITE_CODE` (a secret in Secret Manager): see [`deploy.md`](deploy.md).

To try the image locally first: `make image`, then open `http://localhost:8080`.
