# Game rules: Europe, 1500

The rules of Pax Agentica as the engine applies them. A ruler (bot, LLM or human) needs nothing
else to play. Every number here comes from `Rules` in
[`engine/model.py`](../src/pax_agentica/engine/model.py), and a game can override any of them.

## The world

- **104 provinces** from Lisbon to Nizhny Novgorod and from Trøndelag to Tunis
  ([`scenario.py`](../src/pax_agentica/engine/scenario.py)). Each one has a **terrain**, a
  **trade good** (one of fourteen, see below), a **development** level (1–12), **workings**
  (0–3), **buildings** and a garrison of **regiments**.
- **Borders** are land borders or **straits** (the Channel, the Øresund, Gibraltar…). Straits
  can be crossed, but they favour the defender. Land borders are exactly the ones drawn on the
  map, which is built from real geography.
- **Nine great powers**: England, France, Spain, Austria, the Ottoman Empire, Sweden, Russia,
  Poland-Lithuania and Brandenburg-Prussia. Two unions come early, so the middle of Europe has
  powers of its own: Austria is the Danubian monarchy from the start (Vienna, Styria, Tyrol,
  Bohemia, Buda and Transylvania, as after 1526), and Brandenburg-Prussia holds Brandenburg,
  Pomerania and Prussia (united in 1618 and 1648). The Low Countries are left to the Burgundian
  court, outside the powers. Each starts with its capital (6 regiments), its other provinces (2 each; 3 on
  France's long borders, in Styria and in Kiev and Transylvania, where Vienna and Buda also
  start with a fort), a ruler, one general and the same treasury: 60 ducats, 10 manpower, 10
  iron, 20 grain and 15 timber.
- Everything else is an **independent minor**: no ruler, no income, and a garrison equal to its
  development (3 more in Wallachia and Bosnia, which raised real armies). Anyone can attack
  them without declaring war.
- **The courts remember**: in 1500 France resents England, Austria and Spain; Spain and Austria
  are bound by the double Habsburg marriage; the Ottomans and Austria face each other across the
  frontier of Christendom; Poland-Lithuania and Muscovy contest the lands of Rus', and Poland
  and Brandenburg the Baltic coast. These
  opinions fade like any other.

## A turn

One turn is one year, starting in 1500. All nations decide **at the same time**, seeing the same
world; then the engine resolves every order in fixed phases
([ADR 0001](adr/0001-simultaneous-turns.md)):

1. **Answers** to last turn's proposals. Unanswered proposals expire.
2. **Diplomacy**: declarations of war, cancelled treaties, new proposals, gifts, messages.
3. **Economy**: recruiting, development, buildings, stability. Regiments raised now can march
   and attack this same year.
4. **Movement** between your own provinces.
5. **Battles**, taking one attack from each nation in turn. A realm's armies that fall on the
   same province in the same year fight there as one army: a single battle.
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
| **Timber** | development and most buildings; ironworks burn it as charcoal |
| **Goods** | cloth, glass and arms: marketplaces, universities and the royal exchange consume them, arquebusiers (1) and guns (2) need them, and developing past level 5 takes them |

**Each province produces, per turn:**
- ducats equal to its development,
- manpower equal to half its development (at least 1),
- 1 iron, 3 grain and 1 timber,
- plus its **trade good**, per level of development (rounded down):

| Good | Per development | Where, for example |
|---|---|---|
| Gold | 2.5 ducats | Transylvania, Morocco |
| Silver | 2 ducats | Saxony, Tyrol, Bohemia, Serbia |
| Spices | 2 ducats, 0.5 goods | Lisbon, Venice, Constantinople |
| Wine | 1.5 ducats | Champagne, Gascony, Andalusia, Rome, Buda |
| Salt | 1.5 ducats | Kraków, Brittany, Bavaria, Hamburg |
| Copper | 1.25 ducats, 0.5 iron | Stockholm (the Great Copper Mountain) |
| Furs | 1.25 ducats, 0.5 goods | Moscow, Novgorod |
| Wool | 1 ducat, 0.5 goods | York, Ireland, Madrid, Aragon |
| Cloth | 1 goods, 0.5 ducats | London, Lyon, Flanders, Milan, Florence |
| Fish | 1 grain, 0.5 ducats | Holland, Scotland, Norway, Galicia |
| Horses | 0.5 grain, 0.5 manpower | Kiev, Wallachia, Switzerland |
| Grain | 1.5 grain | Paris, Masovia, Prussia, Sicily |
| Iron | 1.25 iron | Wales, Styria, Bosnia, Norrland |
| Timber | 1.5 timber | Finland, Lithuania, Smolensk |

A gold province is worth about twice a grain one; a cloth town feeds the workshops of a realm.

**Workings.** `improve` raises a province's workings (its mine, vineyard, fishery, looms…) by one
level, up to 3, for 35 ducats and 6 timber times the new level. Each level adds **half the good's
yield again**, so it grows as the province develops. Workings take no building slot.

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

**Taxes** run from −2 (very low) to +2 (very high), set with `set_taxes` and kept until changed.
Each level up brings +15% ducat income and −10% manpower, makes raising stability 20% dearer,
and above normal risks a point of stability every year (10% at high, 25% at very high); below
normal, the same chances of gaining one.

**The ledger.** `me.ledger` lists the year's income and expenses by source: land, buildings,
workings, the crown's modifiers (stability, technology, ruler, prestige, taxes, exhaustion),
the army, the council, building inputs, loans and tribute.

**A conquered province is in unrest** for 5 turns and produces nothing.

**Armies cost every year.** At the end of each turn every regiment eats 1 grain, and the army is
paid half a ducat per regiment (rounded up for the whole army; cavalry and artillery cost
double, cavalry eats double), and wears an iron a year for every ten regiments (a gun counts
as three) in shot, powder and repairs. Regiments that cannot be fed or paid desert; an army
short of iron makes do with worn gear.

**Manpower is finite.** The pool fills up to 10 + 6 × your yearly manpower; anything above is
lost. Barracks raise both. Disbanding a regiment sends its 2 manpower back to the pool.

| Action | Cost | Effect |
|---|---|---|
| `recruit` | 6 ducats, 2 manpower and 2 iron per regiment | regiments appear in one of your provinces |
| `hire_mercenaries` | 15 ducats per regiment, nothing else; at most 10 regiments a year | pikemen appear in one of your provinces, then serve like any other |
| `disband` | nothing | regiments go home: no more upkeep, +2 manpower each |
| `develop` | 10 + 7 × development ducats and 3 + development timber (times the terrain), 4 + development grain to feed the new townsfolk, from development 4 an iron a level above 3 (tools and nails), and from development 5 development ÷ 3 goods | +1 development (max 12, or 15 with Grand Architecture): more output and more score |
| `improve` | 35 ducats and 6 timber, times the new level | +1 level of workings (max 3) |
| `build` | see below | a building in one of your provinces |
| `boost_stability` | 50 ducats, less with a diplomatic ruler | +1 stability (max +3) |

### Inputs and idle buildings

Some buildings **consume** every year: marketplaces a bale of goods (they sell it), universities a
bale (books), the royal exchange two, ironworks 2 timber (charcoal), cannon foundries 2 iron,
barracks 2 grain. **Workshops** turn 1 iron and 1 timber into 2 + development ÷ 3 goods. Inputs
are paid at the end of the year from the treasury and the year's yield; a building whose inputs
cannot be paid **stands idle** that year and yields nothing.

### The European market

`buy` and `sell` trade grain, iron, timber and goods at the market's price, plus or minus the
**merchants' cut** (15%), at once and before anything else that year. Prices start at 1 ducat for
grain, 2 for iron, 1.5 for timber and 3 for goods; what all Europe buys and sells in a year moves
them (by a quarter for every 100 units of net demand), and they drift back a fifth of the way to
their usual level every year, never below 60% or above three times it.

A realm's **trade bonuses** waive part of the cut, buying and selling alike, up to 80% of it:
each level of economy technology 4%, each level of each marketplace it owns 2% (up to 20%), a
treasurer 3% per point of skill, a royal exchange 25%, and England's Merchant Adventurers 20%.
The view's `market` shows each realm its own prices.

### Buildings

A province's development makes its chief town a **settlement**, and the settlement decides how
many buildings it has room for (one more everywhere with Cameralism):

| Settlement | Development | Building slots |
|---|---|---|
| Hamlet | 1 | 4 |
| Village | 2–3 | 5 |
| Market town | 4–5 | 6 |
| City | 6–8 | 7 |
| Great city | 9 and more | 8 |

In 1500 the great towns of the age (Paris, Constantinople, Venice, Naples, Milan, Flanders,
London, Vienna, Moscow) are cities; most of Europe is villages. A town whose development falls
keeps the works it has, but builds no more until it has room again. Each building can stand once per province, and most can be **upgraded**
(`upgrade_building`, once a year per building) to level 2 or 3: a level does 1.6 and 2.2 times
what the first does, and eats as much more (rounded up); reaching level 2 costs the building's
own cost again, level 3 one and a half times it. A fort or citadel at level 2 counts as two levels
of walls. Walls fight for whoever holds them, with that realm's art of fortification (Star
Forts); an occupied capital gives its occupier no capital bonus. A fortification whose upkeep
went unpaid stands **unmanned** the next year: its walls do not count. The map draws a castle
beside every fortified province, with its levels. Walls fight for whoever holds them, with that realm's art of fortification (Star
Forts); an occupied capital gives its occupier no capital bonus. A fortification whose upkeep
went unpaid stands **unmanned** the next year: its walls do not count. The map draws a castle
beside every fortified province, with its levels. Buildings survive conquest, so the conqueror keeps them. Output buildings **double the
province's base output** of their resource (at least +1), so they are worth more in developed
provinces. Marketplaces, banks and cathedrals **tax the town, not the mines**: the ducats of the
province's trade good are left out of their share; workings deepen those instead.

| Building | Kind | Cost | Levels | Effect |
|---|---|---|---|---|
| Marketplace | civil | 40 ducats, 2 iron, 12 timber | 3 | doubles the province's ducats; consumes 1 goods |
| Farm estates | civil | 30 ducats, 2 iron, 10 timber | 3 | doubles the province's grain; consumes 1 timber |
| Ironworks | civil | 45 ducats, 4 iron, 12 timber | 3 | doubles the province's iron; consumes 2 timber; needs engineering 1 |
| Lumber mill | civil | 35 ducats, 6 iron, 4 timber | 3 | doubles the province's timber; consumes 1 iron |
| University | civil | 75 ducats, 4 iron, 20 timber | 1 | developing this province costs 30% fewer ducats; consumes 1 goods; needs economy 2 |
| Bank | civil | 65 ducats, 6 iron, 12 timber | 3 | +3 ducats and +50% of the province's ducats; consumes 1 goods; needs economy 1 |
| Cathedral | civil | 90 ducats, 2 manpower, 6 iron, 30 timber | 2 | +1 manpower and +25% of the province's ducats; unrest ends twice as fast; consumes 1 goods; needs economy 4 |
| Barracks | military | 40 ducats, 6 iron, 10 timber | 3 | doubles the province's manpower, and a higher cap; consumes 1 iron, 2 grain |
| Armory | military | 45 ducats, 12 iron, 8 timber | 1 | regiments recruited here need half the iron; needs military 1 |
| Training grounds | military | 55 ducats, 2 manpower, 4 iron, 12 timber | 3 | the garrison here fights 20% harder; needs military 3 |
| Fort | military | 45 ducats, 12 iron, 18 timber | 2 | defenders here fight 25% harder; each level is a level of walls an attacker must besiege; consumes 1 ducat |
| Citadel | military | 80 ducats, 2 manpower, 20 iron, 25 timber | 2 | another +25% defence, and more walls; consumes 2 ducats; needs a fort; needs military 2 |
| Workshops | civil | 40 ducats, 6 iron, 12 timber | 3 | 2 + development ÷ 3 goods; consumes 2 iron, 2 timber |
| Stables | military | 35 ducats, 2 iron, 12 timber | 1 | lets this province raise cavalry |
| Cannon foundry | military | 70 ducats, 16 iron, 10 timber | 1 | lets this province cast artillery; consumes 2 iron; needs military 2 |

**Great works** stand once in a realm and are felt across all of it:

| Great work | Cost | Effect |
|---|---|---|
| Military academy | 115 ducats, 10 iron, 20 timber | one more general; generals appointed here start a star higher; needs military 3 |
| Arms manufactory | 105 ducats, 16 iron, 16 timber | every levy in the realm needs half the iron and no goods; consumes 3 iron; needs military 1 |
| Powder mill | 95 ducats, 10 iron, 18 timber | +5% battle power, and guns breach one more fort level; consumes 2 timber; needs military 2 |
| Royal exchange | 130 ducats, 6 iron, 22 timber | +10% ducat income, and the merchants' cut 25% lower; consumes 2 goods; needs economy 3 |
| Observatory | 95 ducats, 8 iron, 16 timber | research 15% cheaper; needs economy 2 |

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

**The spirit of the nation.** Every crown has two spirits it keeps all game, and one kind of
regiment it was famed for, which fights under its own name. The crowns that win least often in the
bots' tournaments get a little more.

| Crown | Its own regiments | Spirits |
|---|---|---|
| Spain | Tercios (pikemen, attack and defence ×1.15) | The Catholic Kings: stability 10% cheaper · The Mesta: +10% grain |
| Austria | Landsknechte (pikemen, attack ×1.15, 15% cheaper) | The imperial crown: +5% ducats · Let others wage war: stability 10% cheaper |
| France | Gendarmes (cavalry, attack ×1.3, defence ×1.15) | The Most Christian King: +10% ducats · The first army of Christendom: +8% battle power |
| England | Longbowmen (archers, defence ×1.25, 20% cheaper) | The Navy Royal: no sea-crossing bonus against its attacks, a fifth of the merchants' cut waived · The wool staple: +10% ducats |
| Ottomans | Janissaries (archers, attack ×1.35, defence ×1.15) | The millet system: other faiths cost half · The devshirme: +5% battle power, +10% manpower |
| Poland-Lithuania | Winged Hussars (cavalry, attack ×1.35, ×1.45 on plains) | The granary of Europe: +20% grain · Golden liberty: stability 10% cheaper |
| Russia | Streltsy (archers, defence ×1.2, 15% cheaper) | The lands of Rus': +25% manpower · The Third Rome: buildings and development 10% cheaper |
| Sweden | Dalecarlians (pikemen, defence ×1.2, ×1.15 in forests and hills) | Baltic fleets and peasant pikes: no sea-crossing bonus against its attacks, +5% battle power · The copper of Falun: +10% ducats |
| Brandenburg-Prussia | Reiters (cavalry, attack ×1.2, no penalty in forests) | Prussian drill: +10% battle power, 15% less grain · A refuge for the persecuted: buildings and development 10% cheaper |

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
  | Archers and arquebusiers | 7 ducats, 2 manpower, 1 iron, 2 timber, 1 goods | ½ ducat, 1 grain | 0.8 | 1.3 | ×1.2 in forest and hills | anywhere |
  | Cavalry | 14 ducats, 2 manpower, 3 iron | 1 ducat, 2 grain | 1.5 | 0.9 | ×1.25 on plains, ×0.75 forest, ×0.6 marsh and mountains | with stables |
  | Artillery | 20 ducats, 1 manpower, 6 iron, 2 timber, 2 goods | 1 ducat, 1 grain | 1.1 | 1.2 | any | with a cannon foundry |

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
- **Armies from several provinces join.** Every `attack` a realm orders on the same province in
  the same year becomes one battle: their regiments fight together (the combined arms of all of
  them count), led by the best general among them, and the battle counts once for the war
  score. Bringing armies from several provinces onto one field is hard: each army after the
  first costs 10% battle power, 20% at most. The greedy bot joins armies only against a crown it
  is at war with, and sends what the battle needs and a fifth more. An army that cannot march (not bordering, not at war yet) is dropped, and the others go
  on without it.
- **A winning attacker takes the province.** An independent minor is annexed at once. A great
  power's province is **occupied**: the occupier's survivors garrison it and its armies may
  march on from there, but the province still belongs to its owner, who gets nothing from it
  meanwhile. Only a peace transfers it; at peace, whatever is still occupied goes back, and its
  garrison goes home. An owner (or an ally) who beats the occupier frees the province.
- **Walls must be besieged.** Every tenth of the attacking army in artillery knocks one fort
  level off, and so does Field Artillery; enough guns storm the walls at once. Otherwise, once
  the garrison is beaten (or if there was none), the army **digs in before the walls**: it stays
  in the siege lines, still paid and fed, and its general stays home. At the end of every year
  the siege rolls a die (1 to 6) and adds:

  | Modifier | |
  |---|---|
  | each fort level still standing | −1 |
  | cannon among the besiegers | +1 |
  | each year the siege has lasted (the garrison starves) | +1 |
  | fewer than 5 regiments per level of wall: the ring is not closed | −2 |
  | the defender has Star Forts | −1 |
  | a capital | −1 |

  | Score | Result | Progress |
  |---|---|---|
  | 0 or less | disease in the camp: a tenth of the besiegers die | +10% |
  | 1 | the walls hold | +30% |
  | 2 to 3 | the trenches creep closer | +45% |
  | 4 to 5 | hunger in the town | +65% |
  | 6 or more | a breach in the walls | +100% |

  At 100% the town falls to the besiegers (taken, occupied or freed, as an assault would).
  Attacking a province you besiege sends reinforcements to the lines; `lift_siege` marches them
  back next door. The defender (or an ally at war with the besieger) breaks the siege by
  attacking the lines: a battle on open ground, without the walls. A besieged town cannot be
  marched into, nor raise levies or build. A peace lifts the siege.
- **An occupied capital** costs its owner 1 stability. A capital only changes hands in a peace,
  and only to the side that occupies it; a nation that loses its last province is gone.

### War score and exhaustion

Each war has a **war score** from each side, from −100 to 100: the share of the enemy's land
(by development) you occupy, +15 for its capital, and +2 for each battle won (up to 20), minus
the same for them. A peace **may only demand what your war score covers**:

| Demand | Costs in war score |
|---|---|
| a province | its share of the loser's development (at least 5, unless you occupy it: then exactly its share, what holding it earns) |
| a lump sum | 10 per year of the loser's ducat income it is worth |
| a tribute | half that, for all its years |
| an army limit | 15 |

Offering is never limited. A proposal is answered the year after it is sent. The greedy bot
answers by the state of the war, never by chance: it grants demands its war score has lost,
plus a little; even or behind, it takes a white peace; a little ahead, only once the war is
three years old; well ahead, it names its own price. A refusal says why, in numbers.

**War exhaustion** (0 to 20) grows by 1 for each war each year, 0.5 for
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

**Patronage.** Once a year, `patronize` spends 40 ducats plus 2 for every point of prestige you
hold on painters, chapels, feasts and alms, for +4 prestige: the way a rich treasury turns gold
into glory, dearer the more glory it already has.

**Missions.** Every great power has five ambitions from its history, in `me.missions`: France
wants Milan, then Naples, and the Rhine; Spain the gold of Seville, Navarre, the two Sicilies
and the Barbary coast; England Scotland, then Ireland, and Normandy; Austria the Low Countries
and walls on the Danube; the Ottomans Bosnia, Buda and then Vienna; Sweden out of the Kalmar
Union and the Baltic; Russia Kiev and Livonia; Poland-Lithuania Prussia and the Wild Fields;
Brandenburg-Prussia Saxony, Hamburg and a great army. Each mission is a list of goals written
as data (hold these provinces, a realm of this development, this building here, an alliance
with that court, this technology, this prestige, an army this large), shown with how far it
has come. Some open only once an earlier one is done. A mission completes **by itself** at the end of a year in which
all its goals hold, in front of every court: it pays ducats, prestige or stability, and the last
of each chain leaves a lasting bonus (+5% ducats, +5% battle power, forts +10%...).

**Faith.** England, France, Spain, Austria, Sweden, Poland-Lithuania and Brandenburg-Prussia
start Catholic, Russia Orthodox, the Ottomans Sunni. Every province has a faith of its own too:
the Balkans, Greece and the Ruthenian lands are Orthodox, Anatolia and the Barbary coast Sunni,
whoever rules them.

- A province of **another faith than its ruler's yields 25% less** (the Ottomans' millet
  system halves that), shown in the ledger as its own line.
- Land of another faith taken in war or by treaty starts **2 years more of unrest**.
- Once a year, `convert` sends preachers to one of your provinces: 40 ducats plus 10 a level of
  development, and it takes your faith. Each year an unconverted province also has a 5% chance
  of turning by itself.
- A crown that changes faith (the Reformation) takes its capital and half its old-faith
  provinces with it.
- Courts of the same faith warm to each other by 2 a year, of different faiths cool by 1, and
  Christian and Muslim courts by 3. The greedy bot will not ally with or marry into another
  faith unless it thinks well of that court (opinion 40 or more).

**The crisis of the age.** Once a game, between its 18th and 28th year (the seed decides
which and when), a great trouble falls on all Europe, announced the year it begins, and every
crown must answer it:

| Crisis | Years | What it does | The choice |
|---|---|---|---|
| The Great Plague | 3 | each year every town of development 2 or more has an 18% chance to lose a level | close the towns and ports (30 ducats, −1 stability, ducats −15% while it lasts, and only a 6% chance), or keep the markets open |
| The Little Ice Age | 5 | grain from every field −35%; the market's grain dearer (×1.6) | open the royal granaries (−30 grain, +1 stability) or requisition for the army (+25 grain, −1 stability) |
| The Price Revolution | 6 | market prices ×1.4, buildings and development 20% dearer, ducats +10% | strike new coin (+80 ducats, −1 stability) or hold the currency (+1 stability, +2 prestige) |

The view shows the crisis (`crisis`) from the year it is announced, never before.

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

### Marriages, infamy and coalitions

**Royal marriages** (`propose_marriage`) join two houses until war breaks them: +15 opinion when
signed and +2 both ways every year. A realm has heirs for three at most.

**Infamy.** Every province taken from a minor or gained by treaty adds infamy equal to its
development, and every court bordering that land thinks 2 less of the taker per point. Infamy
fades by 1 a year. From 6, every court cools a little toward the conqueror each year; from
**12**, Europe may **league** against it.

**Coalitions** (`propose_coalition`, against a court of infamy 12 or more) are public defensive
leagues. If the conqueror declares war on any member, every other member is at war with it at
once, without being asked. If a member strikes first, the others are called to arms (refusing
costs nothing). A league dissolves when the conqueror's infamy falls below 5. Every court sees
everyone's infamy and leagues.

### Words

Letters (`send_message`) change no rule. Every proposal, and every answer (`respond` with a
`note`), can carry a few words; an answer's words arrive as a letter. The view keeps, for each
court, the last exchanges between it and you (letters, proposals and their fate, treaties,
wars, gifts) in `nations[].correspondence`, so a ruler remembers what was said and promised.

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

**Grudges.** Some wrongs a court does not forget. A province taken from it by treaty is
remembered for 20 years, a treaty broken to make war on it for 30, a war declared on it for 10,
an ally that left it alone in a war for 15. While a grudge lasts it costs the wrongdoer 1 to 3
opinion every year, the wound does not heal by itself (a shared faith or a common enemy does
not warm it either), and once grudges weigh 2 or more the court signs no alliance, pact or
marriage with the wrongdoer. Each court sees what the others hold against it (`remembers` in
the view; your own in `me.grudges`). The greedy bot names the grudge when it refuses, joins
leagues against those who wronged it, and is readier to make war on them.

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

- **Domination**: rule half the provinces of Europe (52 of 104), or be the last nation standing.
- **Destiny**: fulfil every ambition of your crown (its five missions). Small crowns can win this
  way as surely as great ones.
- **Otherwise**, when the turn limit (50 by default) runs out, the highest **standing** wins:
  the total development you own plus half your prestige. Ties go to more provinces, then more
  ducats.

## Playing it yourself

Every year closes with its own moment: the new year written large, a headline for the year that
passed, how your rank, standing, development, provinces and regiments moved, your ambitions
within reach, and a sound and a flourish for what mattered (an ambition fulfilled, land won or
lost, war on your borders). The **Your reign** window charts your standing against the leading
courts and your realm's growth year by year, with the reigns of your rulers, your nemesis and
firmest friend, and the milestones of your reign; the **Chronicle** gives every year a headline;
and the end of the game writes the chronicle of your reign, to keep or share, with a picture
of it (the map of your realm, your standing over the years, the chronicle and your deeds) to
save or share.

The year's report opens on the **deed of the year**, drawn: the greatest battle, a town won, a
siege, a peace, an ambition, the crisis of the age. A new ruler is **crowned** on screen.
**Deeds of renown** (22 achievements, from first blood to victory with Brandenburg-Prussia) are
kept by your browser across games. A first game is **guided**: eight first steps, each with a
"Show me", crossed out by themselves (bring them back from the guide). The top bar has a switch
for the **music** (a lute playing Greensleeves and pavanes and galliards over the grounds of the
age, synthesised in the browser) and one for all **sound**.

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
