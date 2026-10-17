# The Steam store page

Everything the store page needs, in the order Steamworks asks for it: the words, the images,
the trailer, the disclosures, and what is still missing before a "Coming soon" page can go up.
The images and the trailer are made by the game itself (`uv run pax press`); see
[Making the images and the trailer](#making-the-images-and-the-trailer).

## The words

**Name:** Pax Agentica

**Short description** (the line under the header capsule; 300 characters at most, this is 255):

> Europe, 1500. Take one of nine crowns and outlast the others for fifty years: raise armies,
> besiege fortresses, marry, scheme and sign treaties you may have to break. Every rival court is
> ruled by an artificial mind, and you can write a ruler of your own.

**About this game** (the long description):

> **Nine crowns. Fifty years. One Europe.**
>
> It is 1500. France, Spain, England, Austria, the Ottoman Empire, Poland-Lithuania, Russia,
> Sweden and Brandenburg-Prussia share a continent of a hundred and four provinces, and none of
> them is content with its share. You rule one of them. The others are ruled by artificial
> minds that read the same map you do, see only what their spies and borders let them see, and
> answer for themselves every year.
>
> **A year is one decision.** Each turn you give your orders (where your regiments march, what
> your provinces build, whom you write to) and every court does the same at once. Then the year
> turns: armies meet, sieges grind on, letters arrive, harvests come in, and the map shows you,
> province by province, what everyone else decided.
>
> **War is the last argument of kings.** Pikes, horse and guns; generals who win battles before
> they are fought; fortresses that hold out for years; armies that join from two provinces at
> once, and pay for every mile of bad coordination. Taken land is only occupied until a peace
> treaty moves the border, and only as far as your war score allows.
>
> **Diplomacy remembers.** Alliances, pacts, royal marriages, tribute, leagues against whoever
> grows too strong. Break a treaty and every court thinks less of you; wrong a crown and it holds
> a grudge for years.
>
> **The age has plans of its own.** Plague, the Reformation, silver from the Indies, peasants'
> risings, comets over the capital, the Little Ice Age: each of them a choice for your crown, and
> each of them a scene in the chronicle of your reign.
>
> **Write your own ruler.** The rival courts are programs that answer the same view of the world
> a human sees, with the same orders. Pax Agentica ships with them, and it is built for you to
> write your own and set it loose against them.
>
> **Play with friends.** Host a table where several people each take a crown, with a clock on
> every year so nobody waits for long.

**Key features** (the list the store shows on the side):

- Europe in 1500 on a hand-drawn map of 104 provinces, with the towns' real engravings
- Simultaneous turns: every court decides at once, then the year resolves
- Battles, sieges, generals, joint attacks and fortresses that fight for their holder
- Treaties, marriages, leagues, grudges and a peace you negotiate province by province
- The crises of the age: plague, the Little Ice Age, the price revolution
- A chronicle of every reign, deeds of renown, and the whole game replayed at the end
- Rival courts ruled by artificial minds, and the tools to write your own
- Multiplayer tables for friends, with a clock on every year

**Tags** (pick up to 20 in Steamworks; most telling first): Strategy, Grand Strategy,
Turn-Based Strategy, Historical, Diplomacy, Map, Wargame, Simulation, Singleplayer, Multiplayer,
Asynchronous Multiplayer, Programming, Political, Military, Renaissance, Medieval, 2D,
Hand-drawn, Indie, Turn-Based Tactics.

**Genre (store categories):** Strategy, Simulation, Indie. **Languages:** English (interface and
text). **Single-player, online multiplayer.**

## The images

Made by `pax press` at the sizes Steamworks asks for (as of 2026; check the
[graphical assets rules](https://partner.steamgames.com/doc/store/assets) before uploading):

| Asset | Size | What it shows |
|-------|------|---------------|
| Header capsule | 920 × 430 | the map, the title and the tagline |
| Small capsule | 462 × 174 | the title over the map, nothing else |
| Main capsule | 1232 × 706 | as the header, larger |
| Vertical capsule | 748 × 896 | central Europe, the crest, the title stacked |
| Library capsule | 600 × 900 | as the vertical one |
| Library hero | 3840 × 1240 | the map alone: no title, no lettering |
| Library logo | 1280 × 720 | the title alone on transparency |
| Page background | 1438 × 810 | the map, darkened and without lettering |
| Community icon | 184 × 184 | the crest |

Steam's rules for the capsules: the title must be legible on each of them, and none may carry
review quotes, award laurels, prices or "sale" text. The hero has no text at all, because the
library lays the logo over it.

**Screenshots** (at least five, 1920 × 1080, of the game as it is played; none of them art):

1. The map in the first year, France's court open beside it, a march and an attack ordered.
2. The year's report: the headline, the painting of the year, the battles with their odds.
3. A siege on the map, the province window showing the walls and the besiegers.
4. The peace window, with provinces picked as the price of peace.
5. An event card: the comet, the fair or the Reformation, with its scene.
6. The end of a game: the chart of every court's course and the closing table.
7. A multiplayer table in the lobby.

## The trailer

`pax press` plays it at `/trailer`: about seventy seconds, from a game of bots chosen by its seed.
Black, the premise, Europe coming up out of the dark, the first years with their armies marching
and fighting, a battle, a peace and a plague as period paintings, fifty years in a breath, the winner,
the title and the call to action. Record it full screen at 1920 × 1080 (OBS, 60 fps), then cut
in a few seconds of real play (orders being given, the report opening), which the store's
reviewers and players both look for. Upload as MP4 (H.264, 1920 × 1080, 5000 kbps or more).

The music is the game's own lute (Greensleeves and three grounds of the age), synthesised in the
browser; `?music=0` records it silent, to score it in the editor instead.

## Disclosures

**AI-generated content** (Steamworks' content survey asks for it):

- *Pre-generated:* none. The portraits, the town views and the scenes of the age are paintings
  and engravings of the period in the public domain, from Wikimedia Commons (credited in the
  `CREDITS.md` of `src/pax_agentica/web/portraits`, `faces`, `views` and `scenes`). The map is
  drawn from Natural Earth (public domain). The icons and the music are made by the game's own
  code.
- *Live-generated:* the rival courts are programs. The ones the game ships with are written by
  hand and use no language model. A player may plug in a ruler of their own that calls a
  language model; its words reach other players only as in-game letters and proclamations, which
  the engine limits in length (500 characters a letter, 400 a proclamation) and never executes.
  Before the store page goes up, decide whether those player-written rulers ship in the Steam
  build, and say so here.

**Mature content:** none. War and plague appear only as Renaissance paintings that hang in
museums (battle scenes, Bruegel's *Triumph of Death*); declare it as mild, non-graphic violence.

## Before the page can go up

The full list, with the dates of the plan, is in [launch-plan.md](launch-plan.md).

- [ ] A Steamworks partner account and the app fee (USD 100 per game, recouped after USD 1,000 of
  sales).
- [ ] A desktop build: the game runs in a browser today. Wrap it (Tauri or Electron, with the
  server inside) so it installs and starts from the Steam client, offline.
- [ ] Steam achievements: the deeds of renown map onto them almost one to one.
- [ ] Cloud saves: the saves are one JSON file per game, which Steam Cloud can sync as they are.
- [ ] The price: USD 14.99 with a 10 % launch discount (the reasons, the plan and everything
  else still missing are in [launch-plan.md](launch-plan.md)).
- [ ] The "Coming soon" page live at least two weeks before release, to gather wishlists.
- [ ] Check every text and image once more: the store page and the capsules must name no other
  game or studio.

## Making the images and the trailer

```bash
uv run pax press                 # http://127.0.0.1:8090/press and /trailer, from a game of bots
uv run pax press --seed 12       # another game: other wars, other borders
```

The capsule page paints every size from the map of any year of that game (a few years in reads
best: the borders have started to move) and downloads each as PNG. Only this machine sees it:
`pax press` serves on 127.0.0.1 and is not part of the tables.
