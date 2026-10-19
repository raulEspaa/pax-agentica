# The contract between the game and its rulers

**Version 1.0.0**, frozen on 2026-10-19. This is everything a ruler (a bot, a language model or
a person at the page) may read and do. It is the only interface between the game and the AI
rulers in `src/pax_agentica/agents/`: if it is not here, a ruler cannot see it or do it.

The contract is code, kept honest by tests:

- [`engine/contract.py`](../src/pax_agentica/engine/contract.py) holds `CONTRACT_VERSION`.
- [`docs/contract/`](contract/) holds the JSON schemas of what a ruler reads
  (`nation_view.schema.json`) and what it answers (`orders.schema.json`), and `CONTRACT.lock`
  with the version, a fingerprint of both schemas and the list of orders.
- The two references at the end of this page (every order, every field of the view) are written
  from the code by `make contract`.
- `tests/test_contract.py` fails as soon as the code and any of these disagree.

## Versions

The version follows semantic versioning, and every view carries it (`view.contract`):

- **Major** (2.0.0): a ruler written for the old contract could break. A field or an order
  removed or renamed, a type changed, an optional field made required, a meaning changed.
- **Minor** (1.1.0): something is only added. A new field in the view, a new order, a new
  optional field in an order. Old rulers keep working; they just do not use it.
- **Patch** (1.0.1): wording only (descriptions, comments), the schemas otherwise the same.

Changing the contract is always deliberate: change the code, bump `CONTRACT_VERSION`, run
`make contract`, and add a line to the changelog below. Rule changes that leave the contract as
it is (a number in `Rules`, how a battle is fought) do not change its version: the numbers a
ruler needs are in `view.rules`, and the rules are explained in [game-rules.md](game-rules.md).

### Changelog

- **1.0.0** (2026-10-19): the first frozen contract. 55 orders; the view with fog of war, the
  New World, the sea zones, national decisions, the hegemon and lost land.

## The loop

```python
from pax_agentica.engine import new_game, resolve_turn, view_for
from pax_agentica.players import Player

state = new_game(seed=1)
view = view_for(state, "france")  # NationView: the only thing a ruler may read
orders = await ruler.decide(view)  # Orders: the only thing a ruler may give
state = resolve_turn(state, {"france": orders, "spain": ...})
```

A ruler is anything that implements the `Player` protocol
([`players/__init__.py`](../src/pax_agentica/players/__init__.py)):

```python
class Player(Protocol):
    @property
    def name(self) -> str: ...  # a short label: "greedy", "gemini-flash"
    async def decide(self, view: NationView) -> Orders: ...
```

- `decide` is async, so slow rulers (language models) think in parallel: all the crowns decide
  **at the same time**, on the same world, and no ruler sees another's orders before the year
  is resolved ([ADR 0001](adr/0001-simultaneous-turns.md)).
- `runner.run_game` plays a whole game with any mix of rulers. A ruler that raises an exception
  or runs out of time (the runner's `timeout`) **forfeits that turn**: it gives no orders that
  year, and the game goes on.
- A ruler never touches the game's state. **The AI proposes, the engine decides**: the engine
  validates every order and applies only those that are legal.

## What a ruler sees

`view_for(state, nation)` builds a `NationView`: the world as that crown may know it.

- **Its own realm, completely** (`me`): the treasury and what it does a year (a ledger by
  source), stability, prestige, taxes, every regiment by kind, its fleets, colonies, treaties,
  wars and their war score, its ruler and heir, its council, its missions and decisions, the
  events waiting for its answer, the land it lost.
- **The whole map** (`provinces`): owners, development, buildings, terrain, goods, what each
  province produces, its fort and monument.
- **Troops only where it can see** (fog of war): in its own provinces, its allies' provinces and
  every province bordering its own. Elsewhere `troops` is `null`. Fleets at sea are public.
- **Every other court** (`nations`): size, standing, capital, wars and alliances, marriages and
  pacts, ruler, technology, infamy, policies and decisions taken, and its opinion of you. Never
  its treasury, its council or its orders.
- **What it witnessed last year** (`last_turn_events`): public news (wars, battles, treaties,
  conquests), its own letters and proposals, and the reasons why any order of its own failed
  (`order_rejected`).
- **Every number the engine uses** (`rules`): costs, yields, limits, the technology tree. A
  ruler never has to guess a rule.

`pax view france --seed 1` prints a real view. `tools.briefing(view)` turns it into a page of
plain text for a prompt, and the calculators in `tools.py` answer questions about it without
seeing through the fog (see [agent-tools.md](agent-tools.md)).

## What a ruler answers

`Orders` holds a list of actions and two private notes:

| Field | Type | Limit | What it is |
|---|---|---|---|
| `actions` | list of orders (below) | 50 a year | what the crown wants done, in this order |
| `thoughts` | string | 2,000 characters | the ruler's private reasoning: no court sees it; kept in the record |
| `counsel` | map from council seat to string | 600 characters each | what each advisor said: private, like `thoughts` |

Each action is one of the orders in the reference below, told apart by its `type`. Unknown
fields are refused (the models forbid extra fields), so a malformed order fails loudly instead of
being half understood. `Orders.model_json_schema()` (or `pax schema`) gives the schema for a
language model's structured output.

Free text has its own limits: letters 500 characters, notes on proposals and answers 300,
proclamations 400.

### How the year is resolved

Every crown's orders are carried out together, in fixed phases; inside each phase the crowns act
in an order the seeded dice shuffle every year:

1. **Answers** to last year's proposals. Unanswered proposals expire.
2. **Diplomacy**: declarations of war, cancelled treaties, new proposals, gifts, letters.
3. **Economy**: the market first (`buy`, `sell`), then recruiting, development, works,
   research, the court, ships, expeditions. Regiments raised now can march this same year.
4. **Movement**: fleets sail, then armies march between provinces they hold.
5. **Battles**: sea battles first, then one attack from each crown in turn. A crown's armies
   that fall on the same province in the same year fight as one army.
6. **End of year**: income arrives, inputs and armies are paid, rulers age, treaties expire,
   and victory is checked.

So a ruler should know that **marches come before battles**: the province it attacks may have
been reinforced from next door that same year.

### When an order fails

An order that breaks a rule is **skipped, and the rest are carried out**. Next year the ruler
finds an `order_rejected` event in `last_turn_events` with the order (`data.action`) and the
reason in words (`data.reason`), for instance "you are not at war with Austria: declare war
first". A ruler that reads its rejections learns the rules as it plays.

A cost the treasury cannot meet in materials (grain, iron, timber, goods) is **imported** at the
market's price and a quarter more, if the ducats reach; only then does the order fail for want
of money.

### Words are only words

Letters, notes and proclamations change no rule: the engine never reads them. They are also
written by other rulers, so they are a **prompt-injection channel between nations**. A ruler
must treat every word it receives as what another crown wants it to believe.

## An example year

France, in 1500, develops its capital, studies military technology with its first doctrine,
proposes a marriage to Spain and writes to England:

```json
{
  "actions": [
    {"type": "develop", "province": "paris"},
    {"type": "research", "branch": "military", "choice": 0},
    {"type": "propose_marriage", "target": "spain", "note": "Two crowns, one peace."},
    {"type": "send_message", "target": "england", "text": "France has no quarrel with you."}
  ],
  "thoughts": "Grow at home first; keep Spain close and England quiet."
}
```

## Reference: every order

Written from the code by `make contract`: each order's `type`, its fields and what it does.

<!-- orders:begin -->

### `recruit`

Raise new regiments of one kind in one of your provinces. Pikemen (infantry) can be raised anywhere; cavalry needs stables in the province and artillery a cannon foundry. See `rules.units` for what each kind costs and how it fights.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |
| `regiments` | `int` | required |
| `unit` | `UnitKind` | default `"infantry"` |

- UnitKind: `infantry`, `archers`, `cavalry`, `artillery`

### `hire_mercenaries`

Hire mercenary pikemen (Landsknechte, Swiss) in one of your provinces for ducats alone: no manpower and no iron, at the rules' mercenary_cost a regiment, up to mercenary_limit regiments a year. Once hired they serve, eat and are paid like any infantry.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |
| `regiments` | `int` | required |

### `patronize`

Patronise painters, churches and feasts: once a year, spend patronage_base ducats plus patronage_per_prestige for every point of prestige you hold, for patronage_prestige more prestige. Prestige raises income and counts in the final score.

### `set_taxes`

Set the realm's taxes from -2 (very low) to +2 (very high). Each level up brings rules.tax_income_step more ducat income and rules.tax_manpower_step less manpower, makes raising stability dearer, and above 0 risks a point of stability every year; below 0 the people may grow content and stability rise. The level stays until changed.

| Field | Type | |
|---|---|---|
| `level` | `int` | required |

### `develop`

Invest ducats to raise a province's development by 1 (more output, more score).

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |

### `disband`

Send regiments home: they stop costing grain and ducats, and their men return to the manpower pool (up to its cap).

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |
| `regiments` | `int` | required |
| `unit` | `UnitKind \| null` | default `null` |

- UnitKind: `infantry`, `archers`, `cavalry`, `artillery`

### `build`

Construct a building in one of your provinces. Each costs and does what the rules' `buildings` catalogue says. A province has as many slots as its town allows (its `building_slots` in the view), holds each building once, and a citadel needs a fort first.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |
| `building` | `BuildingKind` | required |

- BuildingKind: `marketplace`, `farm_estates`, `ironworks`, `lumber_mill`, `university`, `bank`, `cathedral`, `barracks`, `armory`, `training_grounds`, `fort`, `citadel`, `workshop`, `stables`, `cannon_foundry`, `military_academy`, `arms_manufactory`, `powder_mill`, `royal_exchange`, `observatory`

### `upgrade_building`

Raise a building standing in one of your provinces to its next level: it does more (and eats more), by `rules.building_level_factors`, up to its `max_level`. It costs its own cost times `rules.building_upgrade_costs` for the new level. Once a year per building.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |
| `building` | `BuildingKind` | required |

- BuildingKind: `marketplace`, `farm_estates`, `ironworks`, `lumber_mill`, `university`, `bank`, `cathedral`, `barracks`, `armory`, `training_grounds`, `fort`, `citadel`, `workshop`, `stables`, `cannon_foundry`, `military_academy`, `arms_manufactory`, `powder_mill`, `royal_exchange`, `observatory`

### `upgrade_monument`

Raise the monument of one of your provinces by a level (from a bare site to level 1, up to `rules.max_monument_level`). Its bonus grows with every level and serves whoever holds it.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |

### `improve`

Improve the workings of one of your provinces by a level (up to 3): its mine, vineyard, fishery or looms, by what it is known for. Each level adds half of what its good yields; it takes no building slot. The next level costs the rules' improve_cost times it.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |

### `set_focus`

Turn one of your provinces to a focus: trade (more ducats), farming (more grain), mining (more iron and timber), garrison (more manpower, defended harder) or learning (cheaper to develop; each province of learning makes the realm's research cheaper). The bonus is rules.focus_base plus focus_per_settlement for each step its town has grown above a hamlet. Costs rules.focus_cost; a province keeps its focus at least rules.focus_years years.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |
| `focus` | `Focus` | required |

- Focus: `trade`, `farming`, `mining`, `garrison`, `learning`, `shipyard`

### `set_posture`

Tell the garrison of one of your provinces how to wait for an attack: hold (the line of pikes, carried by infantry), skirmish (shot and bows thrown forward, carried by archers) or sally (horse kept back to charge, carried by cavalry). Each beats one attacking tactic and loses to another (see Attack.tactic). Free; whoever can see the garrison sees its posture.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |
| `posture` | `Posture` | required |

- Posture: `hold`, `skirmish`, `sally`

### `set_policy`

Take a side on one of the realm's great choices (see rules.policies): army (a professional army or militia levies), economy (agrarian or mercantile) or state (centralism or fueros). The first side taken on an axis is free; changing it later costs rules.policy_stability stability, and a policy stands at least rules.policy_years years.

| Field | Type | |
|---|---|---|
| `axis` | `PolicyAxis` | required |
| `side` | `int` | required |

- PolicyAxis: `army`, `economy`, `state`

### `royal_action`

Spend the crown's authority (it gathers every year by the ruler's skills) on a royal act (see rules.royal_acts for each one's cost and effect): an extraordinary levy, a royal progress, calling the banners, a general pardon, a royal embassy to `target`, leading the army in person, or patronage of the Church.

| Field | Type | |
|---|---|---|
| `act` | `RoyalAct` | required |
| `target` | `NationId \| null` | default `null` |

- RoyalAct: `levy`, `progress`, `banners`, `pardon`, `embassy`, `presence`, `church`

### `choose_agenda`

Give the reign an ambition, one of the agendas offered in your view (`agenda_offers`). Fulfilled, it brings rules.agenda_prestige prestige and rules.agenda_authority authority, and the ruler may take another.

| Field | Type | |
|---|---|---|
| `agenda` | `str` | required |

### `educate_heir`

Give the heir tutors in one of the three arts of rule: +1 to that skill (up to 6), for rules.education_cost and rules.education_authority authority. Once a year.

| Field | Type | |
|---|---|---|
| `skill` | `"administration" \| "diplomacy" \| "military"` | required |

### `press_claim`

A throne's line has failed and your crown, married into it, holds a claim (see `claims` in your view): press it by war, or renounce it for the goodwill of its court. The claim is spent either way.

| Field | Type | |
|---|---|---|
| `nation` | `NationId` | required |
| `press` | `bool` | default `true` |

### `build_ships`

Launch ships from a port of yours into one of the sea zones it looks onto (name it if it has more than one; see the province's `seas`). Galleys are cheap and rule calm seas; galleons cost more, rule the ocean and carry more men (see rules.ships). A port launches at most rules.ships_per_port ships a year, and one more for every 3 development.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |
| `ship` | `Ship` | required |
| `count` | `int` | required |
| `sea` | `SeaId \| null` | default `null` |

- Ship: `galley`, `galleon`

### `scrap_ships`

Lay up ships of yours in a sea zone.

| Field | Type | |
|---|---|---|
| `sea` | `SeaId` | required |
| `ship` | `Ship` | required |
| `count` | `int` | required |

- Ship: `galley`, `galleon`

### `sail_fleet`

Sail ships from a sea zone to a neighbouring one, before the battles: fleets move a zone a year, as armies march a province. Sail into an enemy's zone and seek_battle there the same year.

| Field | Type | |
|---|---|---|
| `origin` | `SeaId` | required |
| `target` | `SeaId` | required |
| `ships` | `dict[Ship, int]` | required |

- Ship: `galley`, `galleon`

### `seek_battle`

Send your fleet in a sea zone against the fleet of a realm you are at war with in the same zone, after the fleets have sailed and before the armies march. Strength is each ship's in that kind of water, times a roll of the dice and each realm's morale; the beaten fleet loses half its ships. A fleet rules.fleet_command times the enemy's in a zone closes its straits to the enemy's armies and blockades its ports there; any fleet stronger than the defender's lets your armies cross its straits freely and land on its shores.

| Field | Type | |
|---|---|---|
| `sea` | `SeaId` | required |
| `enemy` | `NationId` | required |

### `send_expedition`

Send settlers and soldiers to found a colony in a region beyond the sea (see `new_world` in your view: what each region yields, when it opens, how many places are left and how fast your expeditions go). Needs a port of yours on the Atlantic or the Baltic and an escort of rules.expedition_ships fleet strength there; costs rules.expedition_cost, times the kind's cost (rules.colony_kinds). Each year it makes progress; at 100% the colony is founded, unless the region filled up first. A plantation ships the region's full cargo and angers its peoples; a trading post is cheap and quick but ships 60%; a settlement starts at half, grows to half again as much, and defends itself.

| Field | Type | |
|---|---|---|
| `region` | `Region` | required |
| `kind` | `ColonyKind` | default `"plantation"` |

- Region: `caribbean`, `brazil`, `guinea`, `new_spain`, `east_indies`, `peru`, `north_america`
- ColonyKind: `plantation`, `post`, `settlement`

### `take_decision`

Take one of your crown's national decisions (`decisions` in your view), once its goals hold and you can pay its authority and ducats: it pays at once and leaves a lasting effect, and some give the realm a new name. Each is taken once.

| Field | Type | |
|---|---|---|
| `decision` | `str` | required |

### `found_viceroyalty`

Make a region where you hold rules.viceroyalty_colonies colonies a viceroyalty, under a viceroy of skill 1 to 3: more cargo there (rules.viceroy_cargo a point of skill), and the colonies better held. Costs rules.viceroyalty_cost and rules.viceroyalty_authority.

| Field | Type | |
|---|---|---|
| `region` | `Region` | required |

- Region: `caribbean`, `brazil`, `guinea`, `new_spain`, `east_indies`, `peru`, `north_america`

### `seize_colony`

At war, take one of an enemy's colonies in a region. Colonies nobody defends fall to a fleet: your Atlantic fleet must be rules.seize_command times the enemy's (England's Sea Dogs need less). Colonies held by a garrison or by settlers must be stormed: `regiments` sail from your `port` (and your own garrison in the region joins them), your ocean fleet at least the enemy's; they fight the defenders behind their forts. Win, and the colony is yours and the survivors garrison it; lose, and they come back to the port.

| Field | Type | |
|---|---|---|
| `region` | `Region` | required |
| `enemy` | `NationId` | required |
| `regiments` | `int` | default `0` |
| `port` | `ProvinceId \| null` | default `null` |

- Region: `caribbean`, `brazil`, `guinea`, `new_spain`, `east_indies`, `peru`, `north_america`

### `ship_troops`

Carry regiments from one of your ports on the ocean or the Baltic to garrison your colonies in a region (rules.garrison_pay ducats a year each; they calm the peoples and hold the colonies against a storm), or with `home` bring them back to the port. Your ships on the ocean must carry them, and no enemy fleet command the ocean.

| Field | Type | |
|---|---|---|
| `region` | `Region` | required |
| `port` | `ProvinceId` | required |
| `regiments` | `int` | required |
| `home` | `bool` | default `false` |

- Region: `caribbean`, `brazil`, `guinea`, `new_spain`, `east_indies`, `peru`, `north_america`

### `build_colonial_fort`

Raise a fort over your colonies in a region (rules.colonial_fort_cost a level, up to rules.colonial_fort_max): their defenders hold out rules.colonial_fort_defence better a level.

| Field | Type | |
|---|---|---|
| `region` | `Region` | required |

- Region: `caribbean`, `brazil`, `guinea`, `new_spain`, `east_indies`, `peru`, `north_america`

### `conquer_natives`

March on the peoples of a region where you hold a colony: your garrison there and `regiments` carried from your `port` against their strength on their own ground. Each victory kills many of their warriors and brings plunder (and a little infamy); break them and the plunder of an empire is yours, and they no longer deny anyone the region's dues.

| Field | Type | |
|---|---|---|
| `region` | `Region` | required |
| `regiments` | `int` | default `0` |
| `port` | `ProvinceId \| null` | default `null` |

- Region: `caribbean`, `brazil`, `guinea`, `new_spain`, `east_indies`, `peru`, `north_america`

### `convert`

Send preachers to one of your provinces whose people keep another faith: it takes yours at once, ending its discontent (a province of another faith yields rules.faith_mismatch_output less). Costs rules.convert_cost plus convert_cost_per_development ducats a level; one a year.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |

### `boost_stability`

Spend ducats to raise your stability by 1 (stability boosts ducat income).

### `research`

Advance one technology branch by a level: military (stronger armies), economy (richer provinces), engineering (cheaper building and development), naval (stronger fleets, cheaper ships, faster expeditions) or administration (a steadier realm, cheaper research, less infamy). One research a year. Some levels need a level of another branch first (see rules.tech_tree requires). Every level offers doctrines to choose between: `choice` is the index of the one you take, for good.

| Field | Type | |
|---|---|---|
| `branch` | `TechBranch` | required |
| `choice` | `int` | default `0` |

- TechBranch: `military`, `economy`, `engineering`, `naval`, `administration`

### `hire_general`

Appoint a new general in one of your provinces. His skill (1 to 3) is up to fortune.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |

### `assign_general`

Send one of your generals to take command in another of your provinces.

| Field | Type | |
|---|---|---|
| `general` | `int` | required |
| `province` | `ProvinceId` | required |

### `hire_advisor`

Bring one of the candidates at your court onto your council (see `advisor_candidates` in your view). Replaces whoever holds that seat.

| Field | Type | |
|---|---|---|
| `candidate` | `int` | required |

### `dismiss_advisor`

Send an advisor away: no more salary, no more bonus.

| Field | Type | |
|---|---|---|
| `role` | `AdvisorRole` | required |

- AdvisorRole: `treasurer`, `chancellor`, `marshal`

### `move`

Move regiments between two adjacent provinces that you own. Happens before battles. By sea too: between two of your coastal provinces on the same sea zone, if your ships there can carry them and no enemy fleet commands it.

| Field | Type | |
|---|---|---|
| `origin` | `ProvinceId` | required |
| `target` | `ProvinceId` | required |
| `regiments` | `int` | required |
| `general` | `int \| null` | default `null` |
| `units` | `dict[UnitKind, int] \| null` | default `null` |

- UnitKind: `infantry`, `archers`, `cavalry`, `artillery`

### `attack`

Attack an adjacent province owned by a nation you are at war with, or an independent one.  If you win, your surviving regiments take the province. Behind walls they lay a siege instead: they camp before the walls, which fall once the siege reaches 100% (see `siege_modifiers` on the province). Attacking a province you besiege sends reinforcements to the siege lines; attacking a province of yours (or an ally's) under siege fights the besiegers to relieve it.  A landing: from a coastal province, attack any province on the same sea zone where your fleet is stronger than the defender's; the ships there carry the men (rules.ships carries) and the defenders fight rules.sea_crossing_bonus + rules.landing_bonus harder on the beach.

| Field | Type | |
|---|---|---|
| `origin` | `ProvinceId` | required |
| `target` | `ProvinceId` | required |
| `regiments` | `int` | required |
| `general` | `int \| null` | default `null` |
| `units` | `dict[UnitKind, int] \| null` | default `null` |
| `tactic` | `Tactic` | default `"assault"` |

- UnitKind: `infantry`, `archers`, `cavalry`, `artillery`
- Tactic: `assault`, `flank`, `bombard`

### `lift_siege`

Raise a siege you lay: the besiegers march back to one of your provinces next to it.

| Field | Type | |
|---|---|---|
| `province` | `ProvinceId` | required |

### `declare_war`

Declare war. Breaks any alliance, non-aggression pact or truce with the target, which costs stability and is seen by everyone. The target's allies are called to arms against you.

| Field | Type | |
|---|---|---|
| `target` | `NationId` | required |

### `propose_alliance`

Offer an alliance. Allies share vision and are called to arms when one is attacked.

| Field | Type | |
|---|---|---|
| `target` | `NationId` | required |
| `note` | `str` | default `""` |

### `propose_non_aggression`

Offer a non-aggression pact for a fixed number of turns.

| Field | Type | |
|---|---|---|
| `target` | `NationId` | required |
| `note` | `str` | default `""` |

### `propose_marriage`

Offer a royal marriage between the two houses. It lasts until war breaks it: both courts warm to each other by rules.opinion_marriage_yearly every year. At most rules.max_marriages for a realm.

| Field | Type | |
|---|---|---|
| `target` | `NationId` | required |
| `note` | `str` | default `""` |

### `propose_coalition`

Invite `target` into a defensive league against `against`, a power whose infamy has reached rules.coalition_infamy. Once signed, if `against` declares war on either of you, the other (and every other court leagued against it) goes to war at once, without being asked. The league dissolves when the conqueror's infamy falls below rules.coalition_dissolves.

| Field | Type | |
|---|---|---|
| `target` | `NationId` | required |
| `against` | `NationId` | required |
| `note` | `str` | default `""` |

### `propose_peace`

Offer peace to a nation you are at war with. Accepted peace starts a five-year truce and carries out the terms. The recipient may accept, reject, or answer with a counter-offer.

| Field | Type | |
|---|---|---|
| `give` | `Resources` | optional |
| `receive` | `Resources` | optional |
| `cede` | `list[ProvinceId]` | optional |
| `demand` | `list[ProvinceId]` | optional |
| `pay_tribute` | `int` | default `0` |
| `ask_tribute` | `int` | default `0` |
| `limit_army` | `int \| null` | default `null` |
| `note` | `str` | default `""` |
| `target` | `NationId` | required |

### `propose_trade`

Offer an exchange: you give `give` and receive `receive` if the target accepts.  Asking for something while giving nothing is a demand for tribute.

| Field | Type | |
|---|---|---|
| `target` | `NationId` | required |
| `give` | `Resources` | optional |
| `receive` | `Resources` | optional |
| `note` | `str` | default `""` |

### `call_to_arms`

Ask an ally to join your war against `enemy`. An ally who refuses or ignores the call dissolves the alliance, in public.

| Field | Type | |
|---|---|---|
| `target` | `NationId` | required |
| `enemy` | `NationId` | required |
| `note` | `str` | default `""` |

### `respond`

Accept or reject a proposal addressed to you. Unanswered proposals expire; ignoring a call to arms from an ally dissolves the alliance.  To haggle over a peace or a trade, reject it with a `counter`: your own terms, written from your side (`give` is what you would pay). It reaches them as a new proposal next turn, and they can accept, reject or counter again. A trade's counter may only use `give`, `receive` and `note`.

| Field | Type | |
|---|---|---|
| `proposal_id` | `int` | required |
| `accept` | `bool` | required |
| `counter` | `Terms \| null` | default `null` |
| `note` | `str` | default `""` |

### `cancel_treaty`

End an alliance, a non-aggression pact, a marriage or every coalition with `target` openly. No stability cost.

| Field | Type | |
|---|---|---|
| `target` | `NationId` | required |
| `kind` | `"alliance" \| "non_aggression" \| "marriage" \| "coalition"` | required |

### `gift`

Give resources to another nation, no strings attached.

| Field | Type | |
|---|---|---|
| `target` | `NationId` | required |
| `resources` | `Resources` | required |

### `send_message`

Send a private diplomatic message. The target reads it next turn. It has no effect on the rules: words are only words.

| Field | Type | |
|---|---|---|
| `target` | `NationId` | required |
| `text` | `str` | required |

### `set_stance`

Declare a court your friend or your rival, or neutral again. Stances are public: every court sees them. A friend warms to you every year, a rival cools, and your regiments fight 5% harder against a declared rival. At most three friends and three rivals.

| Field | Type | |
|---|---|---|
| `target` | `NationId` | required |
| `stance` | `Stance` | required |

- Stance: `friend`, `neutral`, `rival`

### `proclaim`

Speak to all Europe: a public proclamation every court reads next turn. Like letters, it binds nobody.

| Field | Type | |
|---|---|---|
| `text` | `str` | required |

### `choose_option`

Answer one of your pending events (see `me.pending_events`) with one of its options, by index. Unanswered by the end of the next year, an event takes its first option.

| Field | Type | |
|---|---|---|
| `event_id` | `int` | required |
| `option` | `int` | required |

### `buy`

Buy from the European market at today's price plus the merchants' cut (see `market`). What all Europe buys and sells this year moves next year's prices.

| Field | Type | |
|---|---|---|
| `resource` | `"grain" \| "iron" \| "timber" \| "goods"` | required |
| `amount` | `int` | required |

### `sell`

Sell to the European market at today's price minus the merchants' cut.

| Field | Type | |
|---|---|---|
| `resource` | `"grain" \| "iron" \| "timber" \| "goods"` | required |
| `amount` | `int` | required |

<!-- orders:end -->

## Reference: every field of the view

Written from the code by `make contract`: each model of the view and what its fields mean.

<!-- view:begin -->

### `NationView`

| Field | Type | What it is |
|---|---|---|
| `contract` | `str` | the version of the contract this view is written in (engine/contract.py) |
| `turn` | `int` | the turn, from 1 |
| `year` | `int` | the year, from 1500 |
| `max_turns` | `int` | the last turn: then the highest standing wins |
| `me` | `MyNation` | everything about your own realm |
| `provinces` | `tuple[ProvinceView, ...]` | every province of the map, as far as you can see it |
| `nations` | `tuple[NationSummary, ...]` | every other court, as all Europe knows it |
| `proposals_to_answer` | `tuple[ProposalView, ...]` | answer them this turn or they expire |
| `proposals_sent` | `tuple[ProposalView, ...]` | your proposals still waiting for an answer |
| `last_turn_events` | `tuple[Event, ...]` | last year's events you witnessed, your rejected orders among them |
| `market` | `dict[str, PriceView]` | the European market today: trade with `buy` and `sell` |
| `crisis` | `CrisisView \| null` | the age's great trouble, from the year it is announced |
| `new_world` | `tuple[RegionView, ...]` | the regions beyond the sea: send_expedition, seize_colony |
| `seas` | `tuple[SeaView, ...]` | the sea zones and their fleets: sail_fleet, seek_battle, landings |
| `hegemon` | `NationId \| null` | the crown Europe fears: any court may league against it |
| `rules` | `Rules` | every number the engine uses |

### `MyNation`

| Field | Type | What it is |
|---|---|---|
| `id` | `NationId` | its id |
| `name` | `str` | its name |
| `capital` | `ProvinceId` | your capital |
| `resources` | `Resources` | your treasury: ducats, manpower, iron, grain, timber, goods |
| `stability` | `int` | -3 to +3: income, unrest and the cost of most things |
| `income_per_turn` | `Resources` | production, already including the stability modifier |
| `army_upkeep_per_turn` | `Resources` | what the army eats and is paid, plus advisors' salaries |
| `inputs_per_turn` | `Resources` | what your buildings consume a year, if all of them work |
| `manpower_cap` | `int` | the pool never grows beyond this; barracks raise it |
| `regiments` | `int` | every regiment you have |
| `army` | `dict[UnitKind, int]` | every regiment you have, by kind |
| `provinces` | `tuple[ProvinceId, ...]` | the provinces you own |
| `held` | `tuple[ProvinceId, ...]` | where your armies stand: your own unoccupied land and what you occupy |
| `war_exhaustion` | `float` | 0 to 20: costs ducats, and from 10 stability while at war |
| `morale` | `float` | your armies' battle power from stability and war exhaustion (1 = even) |
| `fleets` | `dict[SeaId, dict[Ship, int]]` | your ships in each sea zone |
| `naval_power` | `dict[SeaId, float]` | what they are worth there (galleys rule calm seas) |
| `blockaded` | `tuple[SeaId, ...]` | zones an enemy fleet holds against you: ports there earn less |
| `colonies` | `dict[Region, int]` | your colonies beyond the sea, by region |
| `colony_list` | `dict[Region, tuple[Colony, ...]]` | each one: its kind and the turn it was founded |
| `expeditions` | `tuple[Expedition, ...]` | yours under way, with their progress out of 100 |
| `colonial_dues` | `Resources` | what the colonies send home a year (already in your income) |
| `trade` | `tuple[TradeView, ...]` | your colonial goods: cargoes, prices, monopolies |
| `viceroys` | `dict[Region, Viceroy]` | your viceroyalties |
| `inflation` | `float` | 0 to rules.inflation_max: the land's ducats fall by it; silver feeds it |
| `inflation_loss` | `int` | the ducats it takes this year |
| `garrisons` | `dict[Region, int]` | your regiments overseas (rules.garrison_pay a year each) |
| `colonial_forts` | `dict[Region, int]` | your forts over the colonies, by level |
| `prestige` | `int` | 0 to 100: ducats, cheaper stability, and half of it counts towards victory |
| `standing` | `int` | development plus half the prestige: what wins when time runs out |
| `faith` | `Faith` | your realm's faith |
| `pending_events` | `tuple[EventView, ...]` | decisions awaiting the crown |
| `loans` | `tuple[Loan, ...]` | what you owe, and when |
| `missions` | `tuple[MissionView, ...]` | your ambitions: done at the end of a year all goals hold |
| `decisions` | `tuple[DecisionView, ...]` | your crown's great choices: take_decision |
| `lost` | `tuple[ProvinceId, ...]` | land taken from you, to win back: revanche (see rules) |
| `patronage_cost` | `int` | ducats for patronize (+rules.patronage_prestige prestige), once a year |
| `tax` | `int` | -2 very low ... +2 very high; change it with set_taxes |
| `infamy` | `float` | your conquests' weight on Europe; past rules.coalition_infamy, leagues form |
| `grudges` | `tuple[GrudgeView, ...]` | the wrongs your court will not forget |
| `ledger` | `tuple[LedgerLine, ...]` | where this year's resources come from and go, line by line |
| `score` | `int` | your total development |
| `at_war_with` | `tuple[NationId, ...]` | the courts you fight |
| `wars` | `tuple[WarView, ...]` | each war: its enemy, its age, its battles and its war score |
| `treaties` | `tuple[TreatyView, ...]` | your treaties, with whom and until when |
| `technology` | `dict[TechBranch, int]` | your level in each branch (0 to rules.max_tech_level) |
| `doctrines` | `dict[TechBranch, list[int]]` | the doctrine chosen at each level reached |
| `policies` | `dict[PolicyAxis, int]` | the side taken on each axis (rules.policies) |
| `policy_locked_until` | `dict[PolicyAxis, int]` | the turn from which each may change again |
| `authority` | `int` | the crown's to spend on royal acts (rules.royal_acts) |
| `heir` | `Ruler \| null` | who takes the throne next; educate_heir to teach them |
| `regency` | `bool` | the ruler is a minor: authority gathers at half the pace |
| `claims` | `tuple[NationId, ...]` | thrones your crown may press a claim to (press_claim) |
| `authority_per_year` | `int` | gathered every year: the ruler's three skills |
| `agenda` | `AgendaView \| null` | the reign's ambition, if it has one |
| `agenda_offers` | `tuple[AgendaView, ...]` | the ambitions it may take (choose_agenda) |
| `research_costs` | `dict[TechBranch, Resources \| null]` | None: already at the top |
| `building_costs` | `dict[BuildingKind, Resources]` | after engineering |
| `generals` | `tuple[GeneralView, ...]` | your generals and where they stand |
| `modifiers` | `Modifiers` | every bonus you enjoy, with its source spelled out |
| `ruler` | `Ruler \| null` | who sits on your throne |
| `advisors` | `dict[AdvisorRole, Advisor]` | your council, by seat |
| `advisor_candidates` | `tuple[CandidateView, ...]` | who you can hire right now |
| `opinions` | `dict[NationId, int]` | what you think of each court, from -100 to 100 |
| `stances` | `dict[NationId, Stance]` | the friends and rivals you have declared (public) |

### `ProvinceView`

| Field | Type | What it is |
|---|---|---|
| `id` | `ProvinceId` | its id |
| `name` | `str` | its name |
| `owner` | `NationId \| null` | None: independent |
| `controller` | `NationId \| null` | an enemy occupying it in a war (it yields nothing meanwhile) |
| `siege_by` | `NationId \| null` | who besieges its walls |
| `siege_years` | `int` | years the siege has lasted |
| `siege_progress` | `int` | 0 to 100: at 100 the walls fall |
| `besiegers` | `int \| null` | regiments in the siege lines (None: hidden by the fog of war) what is added to the besiegers' die next year (1 to 6), line by line; see rules.siege_results |
| `siege_modifiers` | `tuple[tuple[str, int], ...]` | what speeds or slows the siege here: (reason, points) |
| `terrain` | `Terrain` | plains, forest, hills, marsh or mountains: defence and output |
| `good` | `Good` | its trade good: what its land and workings yield |
| `development` | `int` | 1 and up: output, score, and the size of its town |
| `fort` | `int` | fortification level: 1 with a fort, 2 with a citadel too |
| `buildings` | `tuple[BuildingKind, ...]` | the works standing in it |
| `building_levels` | `dict[BuildingKind, int]` | the level of every building standing (1 to 3) |
| `idle` | `tuple[BuildingKind, ...]` | works that stood idle last year for want of their inputs |
| `settlement` | `str` | what its development makes of it: "Hamlet" up to "Great city" |
| `focus` | `Focus \| null` | what its people turn their hands to (yours and everyone's are public) |
| `focus_bonus` | `float` | the share its focus adds to its side of the output |
| `focus_locked_until` | `int \| null` | the turn from which its focus may change |
| `designation` | `str \| null` | what its focus has made of it: "Trade port" |
| `designation_tier` | `int` | 0 none, 1 the focus, 2 one key work (+1 slot), 3 two (a landmark) |
| `building_slots` | `int` | the settlement's room for works, and one more with Cameralism |
| `output_per_turn` | `Resources` | what it yields its owner each turn (nothing during unrest) |
| `building_output_per_turn` | `Resources` | the part of that output its buildings add |
| `unrest` | `int` | turns before a recently conquered province produces again |
| `is_capital` | `bool` | its owner's capital |
| `troops` | `int \| null` | None: hidden by the fog of war |
| `army` | `dict[UnitKind, int] \| null` | the same regiments by kind; None when hidden |
| `general` | `GeneralView \| null` | the general here, if you can see this province |
| `posture` | `Posture \| null` | how its garrison waits for an attack; None when hidden |
| `veterancy` | `float \| null` | of its garrison, 0 (raw) to 1 (veteran); None when hidden |
| `siege_veterancy` | `float \| null` | of the besiegers before it, when you can see them |
| `develop_cost` | `Resources` | for its owner, after universities and engineering |
| `recruit_cost` | `Resources` | per pikeman, for its owner, after an armory |
| `recruit_costs` | `dict[UnitKind, Resources]` | yours only: per regiment of each kind raisable here |
| `workings` | `int` | level of its mine, vineyard, fishery... (0 to rules.max_workings) |
| `faith` | `Faith \| null` | what its people believe; another faith than its ruler's yields less |
| `convert_cost` | `Resources \| null` | what converting it to your faith would cost (None: it cannot be) |
| `improve_cost` | `Resources \| null` | yours only: what the next level of workings costs |
| `monument` | `int \| null` | level of its monument (see rules.monuments); None if it has none |
| `neighbors` | `tuple[ProvinceId, ...]` | provinces it borders by land |
| `sea_neighbors` | `tuple[ProvinceId, ...]` | provinces across a strait: armies cross, the defenders favoured |
| `coasts` | `tuple[Water, ...]` | the kinds of water it looks onto |
| `seas` | `tuple[SeaId, ...]` | the sea zones it looks onto: where its ships launch and land |
| `straits` | `dict[ProvinceId, SeaId]` | the sea zone each strait crossing goes over |

### `NationSummary`

| Field | Type | What it is |
|---|---|---|
| `id` | `NationId` | its id |
| `name` | `str` | its name |
| `alive` | `bool` | still a power on the map |
| `capital` | `ProvinceId` | its capital |
| `provinces` | `int` | how many provinces it owns |
| `score` | `int` | its total development |
| `at_war_with` | `tuple[NationId, ...]` | the courts it fights (public) |
| `allies` | `tuple[NationId, ...]` | its allies (public) |
| `technology` | `dict[TechBranch, int]` | public, as in any court of Europe |
| `doctrines` | `dict[TechBranch, list[int]]` | its doctrines, public too |
| `policies` | `dict[PolicyAxis, int]` | its policies, public |
| `generals` | `int` | how many generals it has |
| `ruler` | `Ruler \| null` | public too: every court knows who reigns where |
| `heir` | `Ruler \| null` | and who comes next |
| `opinion_of_you` | `int` | what this court thinks of you, from -100 to 100 |
| `war_exhaustion` | `float` | 0 to 20: how weary of war it is |
| `prestige` | `int` | 0 to 100: half of it counts towards victory |
| `standing` | `int` | development plus half the prestige: what wins when time runs out |
| `faith` | `Faith` | its faith |
| `fleets` | `dict[SeaId, dict[Ship, int]]` | its ships in each sea zone: navies are public |
| `naval_power` | `dict[SeaId, float]` | what they are worth there |
| `colonies` | `dict[Region, int]` | its colonies beyond the sea (public) |
| `viceroys` | `dict[Region, str]` | its viceroys, by region (public) |
| `decisions` | `tuple[str, ...]` | the national decisions it has taken (public) |
| `lost` | `tuple[ProvinceId, ...]` | land taken from it, that it wants back (public) |
| `marriages` | `tuple[NationId, ...]` | the courts it is married into (public) |
| `pacts` | `tuple[NationId, ...]` | the courts it has a pact of non-aggression with (public) |
| `garrisons` | `dict[Region, int]` | its regiments overseas, by region (public) |
| `stances` | `dict[NationId, Stance]` | the friends and rivals this court has declared (public) |
| `infamy` | `float` | its conquests' weight on Europe; from rules.coalition_infamy, a league may form |
| `leagued_against` | `tuple[NationId, ...]` | the conquerors this court has leagued against |
| `remembers` | `tuple[GrudgeView, ...]` | the wrongs this court holds against you |
| `correspondence` | `tuple[Event, ...]` | what last passed between this court and you, oldest first |

### `AgendaView`

| Field | Type | What it is |
|---|---|---|
| `id` | `str` | its id |
| `name` | `str` | its name |
| `text` | `str` | what it asks |
| `progress` | `int` | done so far this reign (taken: since it was taken) |
| `target` | `int` | how many deeds fulfil it |

### `CandidateView`

| Field | Type | What it is |
|---|---|---|
| `id` | `int` | its id |
| `name` | `str` | its name |
| `role` | `AdvisorRole` | the council seat they seek |
| `skill` | `int` | 1 to 3 stars |
| `personality` | `Personality` | their temper as an advisor |
| `hire_cost` | `int` | ducats, once |
| `salary` | `int` | ducats, every year |

### `CrisisView`

The age's great trouble, once it is announced (the year before it falls) and while it rages. Its effects are in the realm's modifiers and the market.

| Field | Type | What it is |
|---|---|---|
| `kind` | `str` | "plague", "ice_age", "price_revolution" |
| `title` | `str` | its title |
| `text` | `str` | what it says, in words |
| `first_year` | `int` | when it begins |
| `last_year` | `int` | when it ends |
| `raging` | `bool` | false the year it is announced |

### `DecisionView`

One of your crown's national decisions: `take_decision` it once its goals hold.

| Field | Type | What it is |
|---|---|---|
| `id` | `str` | its id |
| `title` | `str` | its title |
| `lore` | `str` | its story, in words |
| `goals` | `tuple[GoalView, ...]` | what it needs, each with its progress |
| `authority` | `int` | spent when taken |
| `ducats` | `int` | spent when taken |
| `rename` | `str \| null` | the realm's new name, if it gives one |
| `reward` | `str` | what it gives, in words |
| `taken` | `bool` | taken already (each is taken once) |
| `missing` | `tuple[str, ...]` | what it still lacks (empty: it can be taken now) |

### `EventView`

| Field | Type | What it is |
|---|---|---|
| `id` | `int` | answer with choose_option(event_id=id, option=index) |
| `event` | `str` | the kind of event |
| `title` | `str` | its title |
| `text` | `str` | what it says, in words |
| `province` | `ProvinceId \| null` | where it happens, if anywhere |
| `options` | `tuple[OptionView, ...]` | the answers to choose from (choose_option) |
| `deadline_turn` | `int` | unanswered by the end of this turn, the first option is taken |

### `GeneralView`

| Field | Type | What it is |
|---|---|---|
| `id` | `int` | its id |
| `name` | `str` | its name |
| `nation` | `NationId` | whose general |
| `skill` | `int` | 1 to 3: +10% battle power per point |
| `province` | `ProvinceId` | where the general stands |

### `GoalView`

| Field | Type | What it is |
|---|---|---|
| `text` | `str` | what is asked, in words |
| `have` | `int` | how far it has come |
| `need` | `int` | what it needs |
| `goal` | `Goal` | the same goal as data |

### `GrudgeView`

A wrong one court holds against another, and how long it will weigh.

| Field | Type | What it is |
|---|---|---|
| `against` | `NationId` | the court it is held against |
| `reason` | `str` | "took Navarre" |
| `since_year` | `int` | when the wrong was done |
| `until_year` | `int` | when it is forgotten |
| `weight` | `int` | opinion lost each year while it lasts; from rules.grudge_refuses, no treaties |

### `LedgerLine`

| Field | Type | What it is |
|---|---|---|
| `kind` | `"income" \| "expense"` | income or expense |
| `source` | `str` | land, buildings, workings, the crown's modifiers, the army, the council... |
| `amount` | `dict[str, int]` | by resource; a modifier line can be negative |

### `MissionView`

| Field | Type | What it is |
|---|---|---|
| `id` | `str` | its id |
| `title` | `str` | its title |
| `lore` | `str` | its story, in words |
| `goals` | `tuple[GoalView, ...]` | what it asks, each with its progress |
| `reward` | `str` | what it pays, in words |
| `status` | `"done" \| "open" \| "locked"` | locked: its earlier mission is not done |
| `after` | `str \| null` | the mission that must be done first |

### `OptionView`

| Field | Type | What it is |
|---|---|---|
| `label` | `str` | the answer, in words |
| `effects` | `str` | what it does, in words |

### `PriceView`

| Field | Type | What it is |
|---|---|---|
| `price` | `float` | ducats a unit, before the merchants' cut |
| `buy` | `float` | what a unit costs you, the cut included |
| `sell` | `float` | what a unit brings you |

### `ProposalView`

| Field | Type | What it is |
|---|---|---|
| `id` | `int` | its id |
| `kind` | `ProposalKind` | what is proposed: alliance, peace, trade, marriage, coalition... |
| `sender` | `NationId` | who proposes |
| `recipient` | `NationId` | to whom |
| `turn` | `int` | when it was sent |
| `give` | `Resources` | trade and peace: what the sender gives |
| `receive` | `Resources` | trade and peace: what the sender asks for |
| `enemy` | `NationId \| null` | call to arms: who the sender is fighting |
| `cede` | `list[ProvinceId]` | peace: provinces the sender hands over |
| `demand` | `list[ProvinceId]` | peace: provinces the sender asks for |
| `pay_tribute` | `int` | peace: ducats a year the sender pays, for rules.tribute_years |
| `ask_tribute` | `int` | peace: ducats a year the sender asks for |
| `limit_army` | `int \| null` | peace: the recipient's army may not grow beyond this |
| `note` | `str` | the sender's words |
| `reply_to` | `int \| null` | the proposal of yours this one counters |

### `RegionView`

A region beyond the sea, as the chart of the New World shows it.

| Field | Type | What it is |
|---|---|---|
| `id` | `Region` | its id |
| `name` | `str` | its name |
| `opens` | `int` | the year the way there is known |
| `open` | `bool` | the way there is known this year |
| `slots` | `int` | colonies it holds, among all the crowns |
| `held` | `dict[NationId, int]` | whose colonies are there (public) |
| `yields` | `Resources` | each colony's yearly due |
| `goods` | `str` | what it sends home, in words |
| `hardness` | `int` | taken off each year's expedition progress |
| `lore` | `str` | its story, in words |
| `your_progress` | `int` | what your expedition there would make a year before the die (5-30) |
| `send_error` | `str \| null` | why you cannot send one now; None: you can |
| `good` | `ColonialGood` | what it ships |
| `cargo` | `int` | cargoes a plantation there ships a year |
| `price` | `float` | ducats a cargo of its good today |
| `people` | `str` | who lives there |
| `natives` | `int` | the regiments its peoples can still field (0: broken) |
| `natives_defence` | `float` | what they fight with on their own ground (conquer_natives) |
| `resistance` | `float` | the share of your dues there they deny you |
| `defence` | `dict[NationId, float]` | what each crown's colonies there hold out with (seize_colony) |
| `garrisons` | `dict[NationId, int]` | each crown's regiments there |
| `forts` | `dict[NationId, int]` | each crown's fort there |
| `viceroys` | `dict[NationId, str]` | the crowns that made it a viceroyalty, and their viceroys |
| `progress_by_kind` | `dict[ColonyKind, int]` | your progress a year, by the kind of colony |
| `cost_by_kind` | `dict[ColonyKind, Resources]` | what an expedition of each kind costs |
| `viceroyalty_error` | `str \| null` | why you cannot make it a viceroyalty; None: you can |

### `SeaView`

A zone of the sea, with every fleet in it (navies are public).

| Field | Type | What it is |
|---|---|---|
| `id` | `SeaId` | its id |
| `name` | `str` | its name |
| `water` | `Water` | what kind of sea: what galleys and galleons are worth here |
| `neighbors` | `tuple[SeaId, ...]` | where a fleet can sail from here in a year |
| `coasts` | `tuple[ProvinceId, ...]` | the provinces it washes: ports, and shores to land on |
| `fleets` | `dict[NationId, dict[Ship, int]]` | every crown's ships in it, by kind (navies are public) |
| `power` | `dict[NationId, float]` | what each fleet is worth here |

### `TradeView`

A crown's trade in one colonial good.

| Field | Type | What it is |
|---|---|---|
| `good` | `ColonialGood` | the colonial good |
| `cargo` | `float` | its cargoes a year |
| `price` | `float` | ducats a cargo today (a monopoly's bonus in it) |
| `ducats` | `float` | what they bring, before the crown's own bonuses |
| `shipped` | `float` | every crown's cargoes of it: past the good's glut, prices fall |
| `monopoly` | `bool` | the crown ships rules.monopoly_share of it, and names its price |

### `TreatyView`

| Field | Type | What it is |
|---|---|---|
| `kind` | `TreatyKind` | alliance, non_aggression, truce, marriage, coalition, tribute, army_limit... |
| `partner` | `NationId` | the other court |
| `until_turn` | `int \| null` | when it expires (None: until broken) |
| `payer` | `NationId \| null` | tribute and army limit: the side bound by it |
| `against` | `NationId \| null` | coalition: the conqueror the league stands against |
| `amount` | `int` | tribute: ducats a year; army limit: regiments |

### `WarView`

| Field | Type | What it is |
|---|---|---|
| `enemy` | `NationId` | the court you fight |
| `since_turn` | `int` | when the war began |
| `attacks_allowed_from_turn` | `int` | armies mobilise for a while after a war starts |
| `war_score` | `int` | -100 to 100, your side: what a peace may demand of them |
| `battles_won` | `int` | your victories in it |
| `battles_lost` | `int` | your defeats in it |

<!-- view:end -->
