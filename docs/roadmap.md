# Roadmap: finishing the engine before the AI rulers

Where the game stands, what is shallow, and what is left before the AI work starts. Written
2026-10-16; tick items off as they land.

## Where it stands

| Area | Today | Depth |
|---|---|---|
| Map and scenario | 68 provinces, nine powers, minors, terrain, fourteen trade goods, monuments, the grudges of 1500 | solid |
| Economy | five resources, development, buildings that double output, stability | **linear**: income grows in a straight line, iron and timber rarely bind, nothing is ever scarce for long |
| Trade | bilateral swaps of resources | **thin**: no market, no prices, nothing to specialise for |
| Technology | three branches with milestones, lore | good |
| Government | historical rulers with traits, three advisors with tempers | good |
| Army | four kinds of regiment, combined arms, siege by guns, generals | good |
| War | one roll per attack; the winner **annexes the province at once** | **shallow**: no occupation, no war score, no exhaustion; a war only ends when someone feels like it, and conquest snowballs |
| Diplomacy | treaties, opinion, stances, proclamations, peace terms with counter-offers | rich |
| Goals | score (development) or domination | **thin**: nothing pulls a nation in a direction of its own |
| AI contract | `NationView` in, `Orders` out, private thoughts and counsel, replay of minds | solid |

The diplomacy is already deeper than the things it negotiates over. The three thin areas are
what make a strategy game feel like progress: **what you fight over** (war), **what you are
trying to achieve** (goals) and **what your economy is for** (trade).

## What to build, in order

### 1. Occupation, war score and war exhaustion (war) — done

- Taking an enemy province in a war **occupies** it: the owner loses its output, the occupier
  holds it. Only a peace transfers it (independent minors are still annexed at once: there is
  no one to sign).
- **War score** from occupied provinces (by development), battles won and the enemy capital
  held. A peace may demand at most what the war score covers; an AI can read the number and
  argue over it.
- **War exhaustion** grows every year of war and with every lost battle, and costs stability;
  it pushes both sides to the table.
- A province with a fort holds out for a **siege** of a year or more unless artillery breaches it.

Why first: it makes peace the centre of every war, which is the negotiation table the AI
rulers will sit at, and it slows the snowball. Size: large.

### 2. Ambitions: missions and prestige (goals) — prestige, faith and events done; missions left

- Each nation gets a short **mission tree** from its history (France: Milan and Naples; Spain:
  the Mediterranean; England: the Channel; Austria: Hungary and Bohemia; Ottomans: the Danube;
  Sweden: out of the Kalmar Union; Russia: Novgorod and Kiev). Completing one pays out (gold,
  stability, a claim, a permanent bonus) and unlocks the next.
- **Prestige** from missions, victories, monuments and great works; part of the final score.
- **Historical events** with a choice: the Reformation (1517), the price revolution, plague,
  a great harvest. Each choice is an order, so an AI chooses too.

Why: progress you can see and want ("two steps from the Italian mission"), and every AI ruler
gets a motive of its own instead of maximising the same number. Size: medium to large.

### 3. Market, manufactures and production chains (economy and trade) — done (trade agreements left)

- A sixth resource, **goods** (cloth, glass, arms): made by **workshops** that consume raw
  materials. Goods are wanted for high development, for luxury that keeps stability, and abroad.
- Buildings with an **input**: ironworks burn timber (charcoal), the cannon foundry eats iron,
  barracks eat grain. Output buildings stop being free money; a realm has to be balanced, or trade.
- A **European market**: sell surpluses and buy shortages at prices that move with total
  supply and demand. Trade agreements (a treaty) cut the market's toll between partners.

Why: scarcity and prices create decisions every year, and give courts something to negotiate
besides war. Size: large; the bots need teaching.

### 4. Reputation and the balance of power (AI fit)

- **Aggressive expansion**: every province taken or demanded cools every neighbour's opinion;
  past a threshold, they can form a **coalition** (a defensive alliance against you).
- **Honour**: broken treaties, ignored calls to arms and broken public pledges lower it, and every
  court sees it. Words start to have a price, which is what makes talking to an AI interesting.
- **Espionage**: a spymaster (or the chancellor) can steal a glimpse of another court: its
  treasury, its army, or last year's private `thoughts`. Lying in letters becomes risky.

Why: emergent politics among the agents, and a reason for them to be honest, or careful.
Size: medium.

### 5. Agent support in the engine

- A compact **briefing** of the view for prompts (the full view is very large).
- **Calculators** an agent can call as tools: battle odds, the cost and yield of a building,
  what a peace would cost. Pure functions over the view.
- **Tournaments**: many seeds, mixed players, a table of wins, score, survival and honour.

Size: small to medium. Part of it may belong in `agents/`; the calculators belong to the game.

### 6. Polish

A first-year tutorial, balance passes after each block, the replay's mind panel for missions
and war score, and performance once games run with LLMs.

## Balance to watch

Over 32 bot games with nine powers, fourteen goods and workings (2026-10-16): France wins 13,
the Ottomans 12, Spain 5. France takes about nine minors a game and Austria loses the Low
Countries to it; the poorest powers (Poland-Lithuania, Hungary, Sweden) grow slowly because
their armies eat half their income. Developing now feeds the new townsfolk with grain, which
lifted grain off the market's floor (0.4 to about 0.8 of its price); iron still sits at 0.4.

What would fix the rest, in order: **aggressive expansion and coalitions** (block 4) to check
France; **missions** (block 2) to give the small powers a direction; and something for a
rich treasury to buy once its provinces are developed (Spain and the Ottomans still end with
over a thousand ducats).

## How much is left

Blocks 1 and 2 are the ones I would finish **before** the AI: they decide what the agents talk
about. Block 3 deepens the economy and can come after the first AI ruler plays. Block 4 is
best built once there are agents to watch. The `NationView` and `Orders` contract will grow but
not break, so AI work can start in parallel on the current game.
