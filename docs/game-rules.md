# Game rules: Europe, 1500

The rules of Pax Agentica as the engine applies them. A ruler (bot, LLM or human) needs nothing
else to play. Every number here comes from `Rules` in
[`engine/model.py`](../src/pax_agentica/engine/model.py), and a game can override any of them.

## The world

- **68 provinces** from Lisbon to Moscow and from Norrland to Tunis
  ([`scenario.py`](../src/pax_agentica/engine/scenario.py)). Each one has a **terrain**, a
  **good** (grain, iron, timber or gold), a **development** level (1–12), **buildings** and
  a garrison of **regiments**.
- **Borders** are land borders or **straits** (the Channel, the Øresund, Gibraltar…). Straits
  can be crossed, but they favour the defender. Land borders are exactly the ones drawn on the
  map, which is built from real geography.
- **Seven great powers**: England, France, Spain, Austria, the Ottoman Empire, Sweden and Russia.
  Each starts with its capital (6 regiments), its other provinces (2 each; 3 on France's long
  borders and Austria's Hungarian frontier, where Vienna and Buda also start with a fort), a
  ruler, one general and the same treasury: 60 ducats, 10 manpower, 10 iron, 20 grain and 15
  timber.
- Everything else is an **independent minor**: no ruler, no income, and a garrison equal to its
  development (3 more in Poland, Lithuania and the Danube principalities, which raised real
  armies). Anyone can attack them without declaring war.

## A turn

One turn is one year, starting in 1500. All nations decide **at the same time**, seeing the same
world; then the engine resolves every order in fixed phases
([ADR 0001](adr/0001-simultaneous-turns.md)):

1. **Answers** to last turn's proposals. Unanswered proposals expire.
2. **Diplomacy**: declarations of war, cancelled treaties, new proposals, gifts, messages.
3. **Economy**: recruiting, development, buildings, stability.
4. **Movement** between your own provinces.
5. **Battles**, taking one attack from each nation in turn.
6. **End of turn**: income arrives, the council is paid, armies eat, rulers age (and may die),
   treaties expire, and victory is checked.

Inside each phase, nations act in an order the seeded dice shuffle every turn. An order that
breaks the rules is skipped, and the engine tells its author why next turn.

## Economy

| Resource | Used for |
|---|---|
| **Ducats** | everything: regiments, army pay, development, buildings, stability |
| **Manpower** | regiments (2 each); the pool has a cap |
| **Iron** | regiments (2 each) and military buildings |
| **Grain** | feeding the army: 1 per regiment per turn |
| **Timber** | development and most buildings |

**Each province produces, per turn:**
- ducats equal to its development,
- manpower equal to half its development (at least 1),
- 1 iron, 3 grain and 1 timber,
- plus its good: development × 1 extra grain, iron, timber or ducats (gold).

**Stability** (−3 to +3) multiplies ducat income by 1 + 0.1 × stability.

**A conquered province is in unrest** for 5 turns and produces nothing.

**Armies cost every year.** At the end of each turn every regiment eats 1 grain, and the army is
paid a quarter of a ducat per regiment (rounded up for the whole army). Regiments that cannot
be fed or paid desert.

**Manpower is finite.** The pool fills up to 10 + 6 × your yearly manpower; anything above is
lost. Barracks raise both. Disbanding a regiment sends its 2 manpower back to the pool.

| Action | Cost | Effect |
|---|---|---|
| `recruit` | 6 ducats, 2 manpower and 2 iron per regiment | regiments appear in one of your provinces |
| `disband` | nothing | regiments go home: no more upkeep, +2 manpower each |
| `develop` | 25 + 5 × development ducats, 2 + development ÷ 2 timber | +1 development (max 12, or 15 with Grand Architecture): more output, more score, more building slots |
| `build` | see below | a building in one of your provinces |
| `boost_stability` | 50 ducats, less with a diplomatic ruler | +1 stability (max +3) |

### Buildings

A province has **1 + development ÷ 4** building slots (rounded down): 1 at development 3, 2 at
4, 3 at 8, 4 at 12 (one more everywhere with Cameralism). Each building can stand once per
province. Buildings survive conquest, so the conqueror keeps them. Output buildings **double the
province's base output** of their resource (at least +1), so they are worth more in developed
provinces.

| Building | Kind | Cost | Effect |
|---|---|---|---|
| Marketplace | civil | 50 ducats, 6 timber | doubles the province's ducats |
| Farm estates | civil | 40 ducats, 5 timber | doubles the province's grain |
| Ironworks | civil | 60 ducats, 8 timber | doubles the province's iron; needs engineering 1 |
| Lumber mill | civil | 45 ducats, 4 iron | doubles the province's timber |
| University | civil | 90 ducats, 12 timber | developing this province costs 30% fewer ducats; needs economy 2 |
| Bank | civil | 80 ducats, 4 iron, 6 timber | +3 ducats and +50% of the province's ducats; needs economy 1 |
| Cathedral | civil | 110 ducats, 2 manpower, 20 timber | +1 manpower and +25% of the province's ducats; unrest ends twice as fast; needs economy 4 |
| Barracks | military | 50 ducats, 3 iron, 6 timber | doubles the province's manpower, and a higher cap |
| Armory | military | 60 ducats, 8 iron, 4 timber | regiments recruited here need half the iron; needs military 1 |
| Training grounds | military | 70 ducats, 2 manpower, 8 timber | the garrison here fights 20% harder; needs military 3 |
| Fort | military | 60 ducats, 6 iron, 10 timber | defenders here fight 25% harder |
| Citadel | military | 100 ducats, 2 manpower, 12 iron, 15 timber | another +25% defence; needs a fort and military 2 |

### Technology

Three branches, levels 0 to 5. **One research a year**; the first level costs the branch's base
cost and each one after it half the base cost more (×1, ×1.5, ×2, ×2.5, ×3). Every nation's
levels are public.

| Branch | Base cost | Each level |
|---|---|---|
| Military | 60 ducats, 5 iron | +6% battle power, attacking and defending |
| Economy | 70 ducats | +5% ducat and grain income |
| Engineering | 50 ducats, 6 timber | −8% ducats and timber for buildings and development |

Every level is also a **milestone** that unlocks something new:

| Level | Military | Economy | Engineering |
|---|---|---|---|
| 1 | Pike and Shot: the armory | Banking: the bank | Blast Furnace: ironworks |
| 2 | Bastions: the citadel | Printing Press: the university | Water Mills: farm estates and lumber mills yield +150% instead of +100% |
| 3 | Tercios: training grounds | Mercantilism: marketplaces yield +150% instead of +100% | Roads and Canals: armies eat 20% less grain |
| 4 | Field Artillery: your attacks ignore one level of enemy forts | Humanism: the cathedral | Star Forts: forts and citadels give +35% instead of +25% |
| 5 | Military Revolution: a fourth general | Cameralism: one more building slot in every province | Grand Architecture: provinces can grow to development 15 |

## Government

**The ruler.** Every nation starts with the head of its historical line (Louis XII of France,
Bayezid II of the Ottomans...). A ruler has three skills from 1 to 6:

| Skill | Effect |
|---|---|
| Administration | +2% ducat income per point |
| Diplomacy | stability 8% cheaper per point; at 5 or more, breaking a treaty costs 1 less stability |
| Military | +2% battle power per point |

Rulers age a year every turn. Past 40 each year carries a growing chance of death (1.2% per
year over 40). The heir, next in the historical line, comes with new skills, and a new reign
costs 1 stability.

**The council.** Three seats, each filled by an advisor of skill 1 to 3:

| Seat | Per point of skill |
|---|---|
| Treasurer | +4% ducat income |
| Chancellor | research 8% cheaper |
| Marshal | +3% battle power |

Two candidates seek each seat; the list changes every 5 years. `hire_advisor` costs 40 ducats
per point of skill and replaces whoever held the seat; `dismiss_advisor` frees it. Advisors draw
2 ducats per point of skill every year, paid before the army. **If the treasury cannot pay
them, the whole council leaves.**

Your view lists, in `me.modifiers`, every bonus your realm enjoys and where it comes from:
technology, milestones, ruler and council.

## War

- **You must be at war** to attack another nation. A **newly declared war** mobilises for one
  turn: no attacks until the next turn.
- **Attack** an adjacent province with some of the regiments in one of yours. Moves happen
  before battles, so regiments that move in the same turn cannot also attack.
- **Battle**: attacker power = regiments × a roll between 0.8 and 1.2 × the attacker's military
  technology and general. Defender power = regiments × defence × a roll × the defender's military
  technology and general. Defence = 1.2 (home ground)
  × terrain (plains 1, forest 1.1, hills 1.25, marsh 1.25, mountains 1.5)
  × (1 + 0.25 for a fort + 0.25 for a citadel + 0.25 for a capital + 0.25 across a strait).
- **The loser loses every regiment** in the fight. The winner loses about half the ratio of the
  loser's power to its own, and always keeps at least one regiment.
- **A winning attacker takes the province.** The survivors become its garrison, and an empty
  province falls without a fight.
- **Losing your capital** moves it to your most developed province and costs 1 stability.
  Losing every province ends your nation.

### Generals

Every nation starts with one general (skill 2) in its capital and can appoint up to **3** (4 with
the Military Revolution), for
50 ducats each; a new general's skill (1 to 3) is up to fortune. A general adds **10% battle
power per point of skill** to the regiments he leads (`move` and `attack` take an optional
`general`) or defends with (he stands in the province). `assign_general` sends him anywhere in
your realm. He moves with the regiments he leads, takes command of a province he conquers, and
**falls** if his province is taken.

## Diplomacy

| Action | What happens |
|---|---|
| `propose_alliance` | if accepted: allies share vision, and each is **called to arms** when war is declared on the other |
| `propose_non_aggression` | if accepted: a pact for 10 turns |
| `propose_peace` | if accepted: the war ends and a **truce** of 5 turns begins. It can carry reparations either way (`give`, `receive`); whoever cannot pay everything pays what they have |
| `propose_trade` | if accepted: the goods change hands, provided both sides still have them (giving nothing is a demand for tribute) |
| `call_to_arms` | ask an ally to join your war against someone; refusing or ignoring dissolves the alliance |
| `respond` | accept or reject a proposal addressed to you, **on the turn after** it was made |
| `cancel_treaty` | end an alliance or pact openly, at no cost |
| `declare_war` | starts a war; see below |
| `gift` | give resources at once |
| `send_message` | a private letter of up to 500 characters, read next turn. **Words have no effect on the rules.** |

**Treaties are promises, not rules.** You can declare war on an ally, a pact partner or a nation
under truce. That breaks the treaty in front of everyone and costs **2 stability**.

**Calls to arms.** When war is declared on you, each of your allies receives a call to arms; you
can also call an ally into a war you started. An ally who accepts joins the war. An ally who
refuses or ignores it **dissolves the alliance**, in public.

## What you can see (fog of war)

- Your own nation, completely: treasury, income, upkeep, treaties, wars.
- The whole map: borders, owners, development, buildings, what each province produces, terrain
  and goods.
- Troop counts only in your provinces, your allies' provinces and every province bordering
  yours. Elsewhere they are hidden.
- Other nations: size, score, capital, wars and alliances, ruler, technology and number of
  generals, but not their treasuries or councils.
- Last turn's events you could witness: public news (wars, battles, treaties, trades, conquests),
  your private letters and proposals, and the reasons for any order of yours that failed.

## Victory

- **Domination**: rule half the provinces of Europe (34 of 68), or be the last nation standing.
- **Otherwise**, when the turn limit (50 by default) runs out, the highest **score** wins. Score
  is the total development you own. Ties go to more provinces, then more ducats.

## Playing it yourself

`uv run pax serve --nation france` opens the game in your browser. You see exactly the
`NationView` an AI ruler gets, fog of war included, and you answer with the same `Orders`: the
page is just a friendlier way to write them. The other thrones are held by bots (or, later, by
AI rulers), and the turn resolves when you end the year.
