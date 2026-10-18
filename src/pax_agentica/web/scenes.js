// Scenes: a period painting for the deed of the year and the news of the age, from the public
// domain paintings in web/scenes (credited in its CREDITS.md). Each returns an HTML string; the
// crowns a battle, a siege or a treaty concerns fly as pennants in its corner. Nothing here
// reads the game: the page tells it what the paintings show with use().
"use strict";
window.PaxScenes = (() => {
  let INDEX = {};
  const use = (index) => { INDEX = index || {}; };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const hash = (s) => { let h = 2166136261; for (const c of String(s)) h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0; return h; };
  const pennant = (color) => `<svg viewBox="0 0 22 30" width="22" height="30" aria-hidden="true"><path d="M2 0 v30" stroke="#2a1b0c" stroke-width="2"/>
    <path d="M3 2 h17 l-5 6 l5 6 h-17 z" fill="${color}" stroke="#2a1b0c" stroke-width="1"/></svg>`;
  function painting(id, colours = []) {
    const info = INDEX[id] || {}, title = info.label ? `${info.label}${info.by ? `, ${info.by}` : ""}` : "";
    return `<div class="scene"><img src="/scenes/${id}.jpg" alt="${esc(info.label || "")}" title="${esc(title)}" width="760" height="300" loading="lazy">${
      colours.length ? `<span class="pennants">${colours.map(pennant).join("")}</span>` : ""}</div>`;
  }
  const battle = ({a, b, seed = ""}) => painting(hash(seed) % 2 ? "battle-orsha" : "battle-pavia", [a, b]);
  const siege = ({by, of}) => painting("siege", [by, of]);
  const treaty = ({a, b}) => painting("treaty", [a, b]);
  const laurels = ({color}) => painting("triumph", [color]);
  const plague = () => painting("plague");
  const frost = () => painting("frost");
  const galleon = () => painting("fleet");
  const seaBattle = ({a, b, seed = ""}) => painting(hash(seed) % 2 ? "sea-armada" : "sea-lepanto", [a, b]);
  const landfall = ({color}) => painting("landfall", [color]); // an expedition reaching the far shore
  const colony = ({color, rival}) => painting("colony", rival ? [color, rival] : [color]);
  const comet = () => painting("comet");
  // the painting for a fortune of the age, by its id; null when it has none
  const EVENT = {reformation: "reformation", reformer: "drill", plague: "plague", great_plague: "plague", harvest: "harvest", fuggers: "money",
    artist: "painter", revolt: "revolt", silver: "fleet", silver_flood: "fleet", price_revolution: "fleet", comet: "comet", nobles: "court",
    fair: "fair", mine: "mine", frozen_harvests: "frost", ice_age: "frost"};
  const ofEvent = (id) => (EVENT[id] ? painting(EVENT[id]) : null);
  return {use, painting, battle, siege, treaty, laurels, plague, frost, galleon, comet, seaBattle, landfall, colony, ofEvent};
})();
