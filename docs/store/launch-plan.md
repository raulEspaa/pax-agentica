# Price, launch plan and what is missing for Steam

Written on 2026-10-17. The figures for other games and for Steam's rules come from the sources
listed at the end; check Steamworks' own pages before acting on any of them.

## Price

**Recommendation: USD 14.99 (EUR 14.99), with a 10 % launch discount.** Use Valve's suggested
regional prices for the other currencies.

- **What comparable games cost.** Small indie strategy and tactics games on Steam cluster at
  USD 10 to 25. Symphony of War, Untamed Tactics and Stolen Realm all list at USD 19.99, Felvidek
  at 10.99 and Mahokenshi at 24.99.
- **Why not 19.99.** That is the price of games with a full art team. Pax Agentica's map is
  beautiful, but the rest of its look (period paintings, a parchment interface) reads as
  "small game", and a strategy player compares it with the big names of the genre.
- **Why not under 10.** Below 10 dollars the game says "slight". It also gives up margin it
  needs, because the seasonal sales will take it down to 7 to 10 anyway. A 50-year campaign
  that replays differently, nine crowns, multiplayer tables and AI rulers you can write are
  worth more than an impulse buy.
- **The price after launch.** Valve allows no discount in the 30 days after release, except a
  launch discount set up beforehand. After that, discounts must be at least 30 days apart,
  except during the seasonal sales. Plan the first real discount (25 to 35 %) for the first
  seasonal sale after launch, and never raise the base price: a raise blocks discounts for
  30 days.

## What it can earn (orders of magnitude, not a promise)

Wishlists turn into sales at a rate that varies tenfold from game to game. GameDiscoverCo's
median for games priced over 10 dollars is about **0.10 sales per wishlist in the first week**.
Over the first year a game sells about three to five times its first week.

| Wishlists at launch | First week | First year | Net to you in the first year (after Valve's 30 %, VAT and refunds, about 55 % of the list price) |
|---|---|---|---|
| 2,000 | ~200 | ~700 | ~USD 5,500 |
| 7,000 | ~700 | ~2,500 | ~USD 20,000 |
| 20,000 | ~2,000 | ~7,000 | ~USD 55,000 |

The app fee is USD 100, and Valve pays it back once the game has made USD 1,000. The game's
running costs are close to nothing if the Steam build plays offline.

The difference between the rows is what happens **before** launch: how long the store page is
up, Next Fest, the demo, creators who play it, and the reviews in the first week. The best
performers in GameDiscoverCo's sample had a 91 % positive score in their first week; the worst
had 67 %.

## The plan

| When | What |
|---|---|
| Oct to Nov 2026 | Steamworks account, tax and bank forms. A desktop build that installs and plays offline. Steam achievements and cloud saves. |
| End of Nov 2026 | **Coming Soon page live**: capsules and trailer from `pax press`, five screenshots, the copy in `steam-page.md`. Announce it on r/4Xgaming, r/grandstrategy, r/indiegames and in a short devlog. |
| Dec 2026 to Feb 2027 | Steam Playtest (closed): 50 to 200 players, a feedback form, balance and onboarding fixes. A Discord for the community. |
| Mar to May 2027 | **The demo**: one crown, the first 15 years, the whole of the first-steps guide. A press kit page. Write to 30 to 50 strategy creators on YouTube and Twitch with a key. |
| June 2027 | **Steam Next Fest** (each game can enter only one, ever: it should be the last one before launch). Register about two months ahead and submit the demo three to five weeks before the fest. |
| Late July to Sept 2027 | **Release**, two to six weeks after Next Fest, away from the Summer Sale and from big strategy releases. Launch discount of 10 %. |
| After release | A patch in the first week, from the reviews. A free update every 6 to 8 weeks (a new crown, a new start date, new events). Each one is a reason to post and to discount. |

Valve's advice is to put the Coming Soon page up as early as possible. The page must be live
for at least two weeks before release. The games that converted best had been on the store for
about seven months, which is why the page should go up in November 2026 for a release in summer
2027.

The October 2026 Next Fest starts on the 19th and registration is closed. The February 2027
one would arrive before there is a demo. So June 2027 is the realistic fest.

**Early Access or full release?** Release in full if the desktop build, the tutorial and the
localisation are ready by summer 2027. Choose Early Access, at the same price, if the Steam
multiplayer is not: strategy players accept Early Access when updates are regular, and it
gives the game a second launch (1.0) a year later.

## What is missing

### Required to be on Steam

1. **A desktop build.** Today the game is a web page and a Python server. It needs an
   installable app (Tauri or Electron with the server inside, or the server frozen with
   PyInstaller) that starts from the Steam client and plays offline. Windows first; Linux and
   Steam Deck if they come cheap.
2. **Steamworks integration** (the Steamworks SDK, or a binding such as steamworks.js):
   achievements (the deeds of renown map onto them almost one to one), cloud saves (a game is
   one JSON file) and rich presence ("France, 1534").
3. **Multiplayer on Steam.** Today's tables run on Cloud Run with an invitation code. On
   Steam they should become Steam lobbies, where the host's game is the server and friends join
   through Steam, with no server of yours to pay for. Otherwise, keep a server and take on its
   cost and its moderation.
4. **The AI disclosure in the content survey.** The bots that ship are hand-written: say so
   plainly on the page. If the Steam build lets players plug in a ruler that calls a language
   model, that counts as "live-generated" content. Valve then asks for the guardrails (orders
   validated by the engine, letters limited to 500 characters, never executed) and lets players
   report content through the overlay. Many Steam players distrust generative AI, so the copy
   should say that the AI rulers are optional and that the game ships without them.
5. **Business paperwork.** Valve's tax interview (form W-8BEN as a resident of Spain, which
   lowers the US withholding under the treaty), a bank account, the IARC age rating (filled in
   on Steamworks, free), a short EULA and a privacy policy (the game keeps feedback notes).
6. **The name.** Check that nobody holds "Pax Agentica" as a trademark in games (EUIPO and
   USPTO searches), and keep the domain and the social handles.

### Needed to sell well

7. **Localisation.** The game is a lot of text. After English, the biggest strategy audiences
   on Steam read Simplified Chinese, German, Russian, French and Spanish. Spanish can be done in
   house; for the others, translators who know the genre, at USD 0.08 to 0.12 a word.
8. **A real tutorial and settings.** The first-steps guide is a good start. Still missing: an
   options screen (interface scale, which the testers with small screens asked for; volume
   sliders; key bindings), save slots, and difficulty levels for the bots.
9. **Accessibility.** Nations are told apart by colour alone. Add a colour-blind mode, or
   patterns and flags on the map. Keep text readable at 1280 × 800 (the Steam Deck).
10. **Steam Workshop for rulers.** Being able to write a ruler is the game's most original
    feature. Players sharing their rulers through the Workshop, and leagues of rulers, would
    give it a community no other strategy game has.
11. **More to play.** More crowns to choose from (the minors), a second start date (1550 or
    1600), more events of the age. These can arrive as free updates after launch.
12. **Key art.** The capsules made by `pax press` are tidy. A commissioned painting in the
    period style (EUR 300 to 1,000) is what makes people click on the small capsule in a list.
13. **Stability.** Crash reports, opt-in telemetry of where players give up, and the
    performance of a 50-year game on a modest laptop.

## Sources

- [Strategy games on sale, Steam Summer Sale 2026 (Turn Based Lovers)](https://turnbasedlovers.com/news/25-turn-based-rpg-and-strategy-games-to-get-before-the-end-of-steam-summer-sale-2026/)
- [Terra Invicta's 1.0 launch with a 35 % discount (Notebookcheck)](https://www.notebookcheck.net/New-grand-strategy-game-launches-on-Steam-with-promising-reviews-and-35-launch-discount.1197887.0.html)
- [Steamworks: discounts](https://partner.steamgames.com/doc/marketing/discounts)
- [Steamworks: wishlists](https://partner.steamgames.com/doc/marketing/wishlist)
- [Steamworks: Next Fest, June 2026](https://partner.steamgames.com/doc/marketing/upcoming_events/nextfest/2026june)
- [Steam Next Fest dates and rules (Steam Page Analyzer)](https://www.steampageanalyzer.com/blog/steam-next-fest-2026-dates)
- [Steam Coming Soon page guide (Steam Page Analyzer)](https://www.steampageanalyzer.com/blog/steam-coming-soon-page-guide)
- [GameDiscoverCo: the state of Steam wishlist conversions, 2024–2025](https://gamedevreports.substack.com/p/gamediscoverco-the-state-of-steam)
- [Valve's rules for AI content on Steam (GamingOnLinux)](https://gamingonlinux.com/2024/01/valve-announces-new-rules-for-games-with-ai-content-on-steam)
- [Steam's AI disclosure policy (tbreak)](https://tbreak.com/steam-ai-disclosure-policy-update-developers/)
