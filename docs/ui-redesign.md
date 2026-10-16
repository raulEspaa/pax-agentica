# The play page, redesigned (2026-10-16)

Inspired by the grand strategy games of the genre: the map is the table, the management windows
open over it from a rail of icons and get out of its way, numbers say where they come from.

## Plan

1. **Shell.** The map fills the window. A thin top bar holds the realm: one icon and one number
   per resource (its yearly change below, green if it grows, red if it shrinks), stability,
   prestige, infamy, faith, battle power, then the date, the orders and End the year.
   A rail of large icons on the left opens the management windows: hovering an icon gives
   the window a peek, a click pins it, Esc or the cross closes it. Map modes and zoom are icon
   buttons in the map's corner; the legend sits above them.
2. **Icons over words.** Lucide line icons for the interface (ISC licence), coloured glyphs
   for the resources (an ingot for iron, coins, a sheaf, logs, a bolt of cloth, men).
3. **Tooltips that explain.** Every number in the top bar and the totals in the windows carry
   a tooltip that breaks them down by source, with gains in green and losses in red: income
   by source, battle power, ducat bonuses and the like from the realm's modifiers.
4. **Windows.** Economy and the province deed stay as they are, larger.
   - *Missions* get a window of their own, as a vertical tree: each chain a column, each
     mission a node joined to the one it waits for, its goals and reward in the tooltip.
   - *Army* gains recruitment: pick a province, set the regiments of each kind, see the cost.
   - *Learning* shows what each level unlocks (buildings, units) with their effects.
   - *Correspondence* gathers letters, proposals, decisions and replies, with filters by
     court and by kind.
   - *Ledger* (new) compares every court: standing, provinces, development, regiments seen,
     generals, technology, prestige, infamy, opinion; sortable, with filters.
   - *Chronicle* gains filters by court and kind.
5. **Pop-ups.** The year's report separates what happened to your realm from what happened in
   Europe; events get a larger card with the scene and options whose effects are coloured.
6. **Text** is larger throughout (17 px in the windows), icons larger (22 to 28 px).

## Left for the next iteration (reported while testing)

- Wars: bugs reported in play (to reproduce).
- Technology and recruiting: bugs reported in play (to reproduce).
- Peace terms: the checkbox to demand a province could not be ticked (fixed: a CSS class
  shared with the map's picking layer; occupied interior provinces and capitals are offered too).
- Buildings: upgrades (levels) for buildings.
