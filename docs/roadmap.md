# Roadmap: finishing the engine before the AI rulers

Where the game stands, what is still shallow, and what is left before the AI work starts.
Revised 2026-10-16, after missions, patronage, mercenaries, taxes, multiplayer tables and the
agent tools landed.

## Where it stands

| Area | Today | Depth |
|---|---|---|
| Map and scenario | 104 provinces, nine powers with banners (the Danubian Austria and Brandenburg-Prussia in the middle), minors, terrain, fourteen trade goods, monuments, the grudges of 1500 | solid |
| Economy | six resources, development that eats grain and timber, workings, buildings with inputs, taxes, a ledger by source, stability | deep |
| Trade | a European market with moving prices, bilateral trades | good; trade agreements left |
| Technology | three branches with milestones and lore | good |
| Government | historical rulers with traits and portraits, a council of three with tempers | good |
| Army | four kinds of regiment, combined arms, sieges, generals, mercenaries | good |
| War | occupation, sieges, war score, exhaustion; only a peace moves a border | good |
| Diplomacy | treaties, opinion, stances, proclamations, peace terms with counter-offers | rich |
| Goals | five historical missions per crown, prestige, patronage, events of the age | good |
| Balance of power | nothing stops a conqueror but its neighbours' armies | **missing** |
| AI contract | `NationView` in, `Orders` out, private thoughts and counsel, replay of minds, a briefing and calculators | solid |
| Play-testing | `pax serve` alone, `pax host` tables for friends, ready for Cloud Run | ready |

## Review of the mechanics

**What works.** A year has real decisions: what to develop given grain and timber, which
workings to deepen, which buildings can be fed, what to buy and sell, whether a war is worth
its exhaustion, what a peace should cost. Missions give every crown a direction of its own,
and a rich treasury now has places to go (development, workings, monuments, patronage,
mercenaries) instead of piling up.

**What the bot games show** (32 games of nine greedy bots, seeds 200 to 231):

- Spain wins 23, France 7. Both grow by swallowing the independent minors around them: Spain
  takes Portugal, Navarre and the Barbary coast, France Milan, Naples and the Rhine. Every bot
  fulfils its first conquest missions in every game; the missions that need a great power's
  land (Vienna, Buda, Kiev) are rarely done.
- Austria, Hungary and Poland-Lithuania barely grow: their armies eat half their income and
  their neighbours are great powers, not minors.
- Bots hire about ten regiments of mercenaries a game and almost never patronise the arts: they
  spend first.
- Gold is worth about twice grain per level of development, and buildings no longer multiply
  it, so a gold province pays well without snowballing.

**The one structural gap** is the balance of power: nothing in the rules makes Europe react to
a conqueror. That is block A below, and it is also the most interesting thing the AI rulers
will negotiate over.

## Finishing the engine

Four blocks, in order. After them the engine is done: the rules stop changing in ways that
break a ruler, and the work moves to `agents/`.

### A. Aggressive expansion and coalitions (balance of power)

- Every province taken from a minor or by treaty adds **aggressive expansion** to the taker,
  seen by every court and fading over the years; neighbours of the land taken think worse of
  the taker.
- Past a threshold, any court that fears the taker can join a **coalition**: a public defensive
  league that is called to arms together if the taker attacks any member.
- The greedy bot joins coalitions against the leader and fears them.

Why: it is what checks Spain and France in the bot games, and coalitions are pure diplomacy,
the AI rulers' job. Size: medium.

### B. Agent support (done: `tools.py`, `pax brief`, `pax tournament`, see agent-tools.md)

- A compact **briefing** of the view for a prompt: the realm, threats, open missions, offers to
  answer, in a page of text. The full view stays for tools.
- **Calculators** an agent can call: battle odds, what a building or development would yield,
  what a peace would cost, how far each mission is. Pure functions over the view.
- **Tournaments**: many seeds, mixed players, a table of wins, standing, survival and missions.

Size: small to medium.

### C. Freeze the contract (done 2026-10-19: [agent-contract.md](agent-contract.md), version 1.0.0)

- Version `NationView` and `Orders`, export their JSON schema, and a test that fails when they
  change by accident.
- `docs/agent-contract.md`: everything a ruler sees and can do, with an example turn.

Size: small.

### D. Polish

- Balance passes with block A in place (target: no power above a third of the wins).
  After faith landed (32 games, seeds 200 to 231) France wins 20, Spain 9, the Ottomans 3:
  France is now the one to check. With sieges that camp before the walls: France 22, Spain 9,
  Austria 1.
  With 104 provinces, five slots, building levels and the material-heavy economy of 2026-10-16
  (buildings and development cost more timber and iron and fewer ducats, armies wear iron,
  market floor at 60%): Austria 12, Spain 10, France 9, the Ottomans 1. The spread between seeds
  is wide: a one-point change in Silesia gave Spain 14, Austria 13, France 3.
- The replay's mind panel shows missions and war score; a short first-year tutorial on the
  play page.
- Performance once games run with language models.

Left for later, if ever: trade agreements, espionage, a formal honour score.

## How much is left

Block A is the last mechanic I would add before the AI; B and C are what the AI needs to plug
in; D can run alongside the first agents. The `NationView` and `Orders` contract will grow
during A and B and is frozen in C.
