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

**The land matters.** Terrain adds to (or takes from) what a province yields, changes what
developing it costs, and how well it is defended:

| Terrain | Yield | Developing | Defence |
|---|---|---|---|
| Plains | +2 grain | 10% cheaper | ×1 |
| Forest | +2 timber, −1 grain | 10% dearer | ×1.1 |
| Hills | +1 iron, +1 manpower | 20% dearer | ×1.25 |
| Marsh | +1 timber, −1 grain | 30% dearer | ×1.25 |
| Mountains | +2 iron, +1 manpower, −2 grain | 50% dearer | ×1.5 |

**Stability** (−3 to +3) multiplies ducat income by 1 + 0.1 × stability.

**A conquered province is in unrest** for 5 turns and produces nothing.

**Armies cost every year.** At the end of each turn every regiment eats 1 grain, and the army is
paid half a ducat per regiment (rounded up for the whole army; cavalry and artillery cost
double, cavalry eats double). Regiments that cannot
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
| Stables | military | 45 ducats, 8 timber | lets this province raise cavalry |
| Cannon foundry | military | 90 ducats, 10 iron, 6 timber | lets this province cast artillery; needs military 2 |

**Great works** stand once in a realm and are felt across all of it:

| Great work | Cost | Effect |
|---|---|---|
| Military academy | 140 ducats, 6 iron, 12 timber | one more general; generals appointed here start a star higher; needs military 3 |
| Royal exchange | 160 ducats, 4 iron, 14 timber | +10% ducat income; needs economy 3 |
| Observatory | 120 ducats, 4 iron, 10 timber | research 15% cheaper; needs economy 2 |

### Monuments

Sixteen provinces hold a monument of the age, at the level it had reached in 1500. Whoever holds
the province enjoys its bonus, once per level, so monuments are prizes of war.
`upgrade_monument` raises one a level (to 3 at most) for 90 ducats and 10 timber times the new
level.

| Monument | Province | Level in 1500 | Per level |
|---|---|---|---|
| Westminster Abbey | London | 2 | stability 8% cheaper |
| Notre-Dame de Paris | Paris | 2 | research 5% cheaper |
| Hagia Sophia | Constantinople | 3 | +3% ducats |
| The Alhambra | Andalusia | 2 | +4% ducats |
| El Escorial | Madrid | 0 (a site) | buildings and development 6% cheaper |
| St. Stephen's Cathedral | Vienna | 2 | forts +5% stronger |
| The Kremlin | Moscow | 2 | +3% battle power |
| Tre Kronor | Stockholm | 1 | forts +5% stronger |
| The Arsenal of Venice | Venice | 2 | +3% battle power |
| Santa Maria del Fiore | Florence | 3 | research 5% cheaper |
| St. Peter's Basilica | Rome | 0 (a site) | stability 8% cheaper |
| Wawel Castle | Kraków | 2 | forts +5% stronger |
| Cologne Cathedral | Rhineland | 1 | buildings and development 5% cheaper |
| Marienburg | Prussia | 2 | +3% battle power |
| Kronborg | Zealand | 0 (a site) | +3% ducats |
| Santiago de Compostela | Galicia | 2 | stability 6% cheaper |

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
| 2 | Bastions: the citadel and the cannon foundry | Printing Press: the university and the observatory | Water Mills: farm estates and lumber mills yield +150% instead of +100% |
| 3 | Tercios: training grounds and the military academy | Mercantilism: marketplaces yield +150% instead of +100%, and the royal exchange | Roads and Canals: armies eat 20% less grain |
| 4 | Field Artillery: your attacks ignore one level of enemy forts | Humanism: the cathedral | Star Forts: forts and citadels give +35% instead of +25% |
| 5 | Military Revolution: one more general | Cameralism: one more building slot in every province | Grand Architecture: provinces can grow to development 15 |

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

**Character.** Every ruler has one or two traits: the historical ones what history gave them
(Suleiman warlike and a builder, Ivan IV cruel and warlike, Philip II pious and cautious), an heir
history never knew whatever fortune deals.

| Trait | Effect |
|---|---|
| Warlike | +5% battle power |
| Cautious | forts 5% stronger |
| Thrifty | +5% ducats |
| Pious | stability 10% cheaper |
| Scholar | research 10% cheaper |
| Builder | buildings and development 8% cheaper |
| Cunning | breaking a treaty costs 1 less stability |
| Charming | every court warms to them: +2 opinion a year |
| Cruel | +3% battle power, but every court cools: −1 opinion a year |
| Ambitious, Melancholic | no effect on the numbers: who they are, for whoever plays them |

**The council.** Three seats, each filled by an advisor of skill 1 to 3, and of a temper (hawk,
dove, schemer, loyal, frugal or visionary) that has no effect on the numbers but tells an AI
advisor how to counsel:

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
- **Regiments come in four kinds.** Each fights with its own strength, times the terrain of the
  battle:

  | Kind | Cost | Upkeep a year | Attack | Defence | Ground | Raised where |
  |---|---|---|---|---|---|---|
  | Pikemen (infantry) | 6 ducats, 2 manpower, 2 iron | ½ ducat, 1 grain | 1.0 | 1.0 | any | anywhere |
  | Archers and arquebusiers | 7 ducats, 2 manpower, 1 iron, 2 timber | ½ ducat, 1 grain | 0.8 | 1.3 | ×1.2 in forest and hills | anywhere |
  | Cavalry | 14 ducats, 2 manpower, 3 iron | 1 ducat, 2 grain | 1.5 | 0.9 | ×1.25 on plains, ×0.75 forest, ×0.6 marsh and mountains | with stables |
  | Artillery | 20 ducats, 1 manpower, 6 iron, 2 timber | 1 ducat, 1 grain | 1.1 | 1.2 | any | with a cannon foundry |

  **Combined arms**: an army with three kinds (each at least a tenth of it) fights 10% harder,
  with all four 15%. **Guns breach walls**: every tenth of an attacking army in artillery knocks
  one fort level off. `move` and `attack` send a proportional mix unless `units` names exactly
  which regiments go. Every capital starts with the troops its realm was famed for: English
  longbowmen, French gendarmes, Ottoman sipahis and janissaries, Muscovite horse.
- **Battle**: attacker power = the attacking regiments' strength × a roll between 0.8 and 1.2 ×
  the attacker's military technology and general. Defender power = the garrison's strength ×
  defence × a roll × the defender's military technology and general. Defence = 1.2 (home ground)
  × terrain (plains 1, forest 1.1, hills 1.25, marsh 1.25, mountains 1.5)
  × (1 + 0.25 for a fort + 0.25 for a citadel + 0.25 for a capital + 0.25 across a strait).
- **The loser loses every regiment** in the fight. The winner loses about half the ratio of the
  loser's power to its own, and always keeps at least one regiment.
- **A winning attacker takes the province.** An independent minor is annexed at once. A great
  power's province is **occupied**: the occupier's survivors garrison it and its armies may
  march on from there, but the province still belongs to its owner, who gets nothing from it
  meanwhile. Only a peace transfers it; at peace, whatever is still occupied goes back, and its
  garrison goes home. An owner (or an ally) who beats the occupier frees the province.
- **Walls hold out.** A fort or citadel stands a year of siege per level: the attacker must win
  that many years running before the next assault takes the province. A siege not pressed for a
  year is lifted. Every tenth of the attacking army in artillery knocks one level off, and so
  does Field Artillery.
- **An occupied capital** costs its owner 1 stability. A capital only changes hands in a peace,
  and only to the side that occupies it; a nation that loses its last province is gone.

### War score and exhaustion

Each war has a **war score** from each side, from −100 to 100: the share of the enemy's land
(by development) you occupy, +15 for its capital, and +2 for each battle won (up to 20), minus
the same for them. A peace **may only demand what your war score covers**:

| Demand | Costs in war score |
|---|---|
| a province | its share of the loser's development (at least 5) |
| a lump sum | 10 per year of the loser's ducat income it is worth |
| a tribute | half that, for all its years |
| an army limit | 15 |

Offering is never limited. **War exhaustion** (0 to 20) grows by 1 for each war each year, 0.5 for
each battle lost and 0.5 a year for each of your provinces occupied; it falls by 2 a year at
peace. Each point costs 1% of ducat income, and from 10 it costs 1 stability every year.

### Generals

Every nation starts with one general (skill 2) in its capital and can appoint up to **4** (one
more with the Military Revolution, one more with a military academy), for
50 ducats each; a new general's skill (1 to 3) is up to fortune. A general adds **10% battle
power per point of skill** to the regiments he leads (`move` and `attack` take an optional
`general`) or defends with (he stands in the province). `assign_general` sends him anywhere in
your realm. He moves with the regiments he leads, takes command of a province he conquers, and
**falls** if his province is taken.

## Prestige, faith and fortune

**Prestige** (0 to 100) is a realm's glory. It grows with battles won against great powers
(+1), land won by treaty (+3 a province), monuments raised (+2 times the new level), great works
(+5) and some decisions; it falls with battles lost, land ceded, broken treaties (−10) and
abandoned allies (−5), and fades by 1 a year. Each point gives +0.1% ducat income and makes
stability 0.2% cheaper, and **half of it counts towards victory**.

**Faith.** England, France, Spain, Austria and Sweden start Catholic, Russia Orthodox, the
Ottomans Sunni. Courts of the same faith warm to each other by 1 a year, of different faiths cool
by 1. The Reformation can turn a Catholic realm Protestant.

**Fortune.** Every year each nation has a 30% chance of an event of the age, a decision for the
crown, which waits in `me.pending_events` until answered with `choose_option`; unanswered by the
end of the next year, it takes its first option.

| Event | When | The choice |
|---|---|---|
| The Reformation | from 1517, Catholic realms, once | defend the old faith (+1 stability, +5 prestige) or take the Church's lands (+150 ducats, −1 stability, turn Protestant) |
| Plague | in a town of development 3 or more | pay 40 ducats to quarantine, or lose a level of development, men and stability |
| A great harvest | any year | +30 grain, or sell it for +35 ducats |
| The Fuggers' loan | any year | 120 ducats now for 16 a year over ten years, or nothing |
| A master seeks a patron | once | 70 ducats for +8 prestige and +1 stability (Leonardo for France, Holbein for England, Titian, Dürer, Sinan…) |
| The peasants rise | at negative stability | pay 50 ducats for +1 stability, or put it down: regiments lost, unrest |
| Silver from the Indies | Spain, from 1545, once | +200 ducats and −1 stability, or +90 |
| A comet | any year | pay astronomers for prestige, or lose stability |
| A captain with new ideas | with a general | 60 ducats for a star on your best general |
| The nobles grumble | at stability 0 or more | confirm their privileges, or stand above them |
| A great fair | any year | a charter for gold and goodwill, or a heavy tax |
| A new vein | in an iron or gold province | open a mine (+1 development) or sell the rights |

## Diplomacy

| Action | What happens |
|---|---|
| `propose_alliance` | if accepted: allies share vision, and each is **called to arms** when war is declared on the other |
| `propose_non_aggression` | if accepted: a pact for 10 turns |
| `propose_peace` | if accepted: the war ends, a **truce** of 5 turns begins, and its **terms** are carried out (see below) |
| `propose_trade` | if accepted: the goods change hands, provided both sides still have them (giving nothing is a demand for tribute) |
| `call_to_arms` | ask an ally to join your war against someone; refusing or ignoring dissolves the alliance |
| `respond` | accept or reject a proposal addressed to you, **on the turn after** it was made; or reject a peace or a trade with a **counter-offer** |
| `cancel_treaty` | end an alliance or pact openly, at no cost |
| `declare_war` | starts a war; see below |
| `gift` | give resources at once |
| `send_message` | a private letter of up to 500 characters, read next turn. **Words have no effect on the rules.** |

### Peace terms and haggling

A peace can settle any mix of:

| Term | Meaning |
|---|---|
| `give` / `receive` | a lump sum of any resources, either way; whoever cannot pay everything pays what they have |
| `cede` / `demand` | provinces either way. A capital cannot change hands, and every province must border the realm that receives it (or another province it receives in the same peace). The garrison goes home and the province settles for 2 years |
| `pay_tribute` / `ask_tribute` | ducats a year, either way, for **10 years**, paid at the end of each year as far as the payer can |
| `limit_army` | the recipient may not recruit beyond this many regiments while the truce lasts |
| `note` | words to go with the offer, up to 300 characters. They bind nobody |

No terms at all is a white peace. The recipient can accept, reject, or reject with a
`counter`: their own terms, written from their side, which reach the first court as a new
proposal next turn. Trades can be countered too (goods only). Back and forth, one turn at a time,
two courts can haggle a war to its end; that is the table an AI ruler negotiates at.

### Stances and proclamations

`set_stance` declares a court your **friend** or your **rival** (or neutral again), at most three
of each. Stances are public. Each year a declared stance moves both courts' opinions (+2 between
friends, −3 between rivals), and your regiments fight **5% harder against a declared rival**.

`proclaim` speaks to all Europe: every court reads it next turn, and it binds nobody.

### What a ruler thinks

`Orders` carry two private fields the engine ignores: `thoughts`, the ruler's reasoning for the
year, and `counsel`, what each advisor said. No other court ever sees them; they are kept in the
game record, and the replay shows them, year by year, as each court's mind.

### Opinion

Every court has an opinion of every other, from −100 to 100, and sees what each court thinks of
it (`opinion_of_you`). Gifts raise it (+1 for every 4 ducats' worth, up to +25), as do trades
(+5), pacts (+10), alliances (+20), peace (+5), an answered call to arms (+20) and a common enemy
(+3 a year). A declaration of war costs −40 with its victim (and the aggressor thinks 20 less of its victim), a lost province −10, an ignored call
to arms −30, and breaking a treaty −10 with **every** court (−20 more with the victim). Opinions
fade by a tenth every year. The rules never act on opinion; rulers do.

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
- **Otherwise**, when the turn limit (50 by default) runs out, the highest **standing** wins:
  the total development you own plus half your prestige. Ties go to more provinces, then more
  ducats.

## Playing it yourself

`uv run pax serve --nation france` opens the game in your browser. You see exactly the
`NationView` an AI ruler gets, fog of war included, and you answer with the same `Orders`: the
page is just a friendlier way to write them. The other thrones are held by bots (or, later, by
AI rulers), and the turn resolves when you end the year.

Click a province to open its deed. Your own provinces have three leaves: **Economy** (what it
yields, what the next level of development would add, and the best works to build there),
**Buildings** (every work, with what it would add in this province, its cost, or what it still
needs) and **Army** (the garrison by kind, march a fair share or choose regiments by kind, levies of each kind,
disband, appoint a general). The Realm office warns you when a neighbour masses regiments on your
border.

The Envoys office is the court of Europe: each ruler's portrait and history, what they think of
you, your strength side by side, the treaties between you, and what they propose. Peace terms
are written in a treaty form (provinces on the border to demand or cede, sums, tribute, an army
limit and a note), and any peace or trade can be answered with a counter-offer, which opens the
same form with their terms turned to face you.

Every year is saved to `saves/<nation>-<seed>.json`, and `pax serve` picks the game up where you
left it; `--new` starts over. The engine is deterministic, so a save is just the record of
orders, replayed.
