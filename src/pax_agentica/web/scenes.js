// Scenes: a small picture for the deed of the year, drawn as SVG in the manner of the town
// vistas (ink outlines, washed colours). Each takes plain data and returns an <svg> string of
// 380 by 150; nothing here reads the game.
"use strict";
window.PaxScenes = (() => {
  const W = 380, H = 150, GROUND_Y = 104, INK = "#3a2a18";
  const SKY = {plains: ["#bcd3dc", "#f1e6c9"], forest: ["#b6cdd0", "#e9e2c6"], hills: ["#c3d4d8", "#f0e2c2"],
               marsh: ["#b4c6c6", "#e3dec6"], mountains: ["#aec4d2", "#eee6d2"]};
  const GROUND = {plains: ["#b9bd74", "#8f9a52"], forest: ["#7f9a55", "#566f37"], hills: ["#b49a64", "#8a7346"],
                  marsh: ["#8aa087", "#5f7a66"], mountains: ["#a49c8a", "#77705f"]};
  let uid = 0;
  function rng(seed) { let h = 2166136261; for (const c of String(seed)) h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0;
    return () => { h = Math.imul(h ^ (h >>> 15), 2246822507) >>> 0; h = Math.imul(h ^ (h >>> 13), 3266489909) >>> 0; return ((h ^= h >>> 16) >>> 0) / 4294967296; }; }
  function frame(body, terrain = "plains", {sky, ground, dusk} = {}) {
    const id = ++uid, [s1, s2] = sky || SKY[terrain] || SKY.plains, [g1, g2] = ground || GROUND[terrain] || GROUND.plains;
    return `<svg class="scene" viewBox="0 0 ${W} ${H}" role="img" preserveAspectRatio="xMidYMid slice">
      <defs><linearGradient id="ss${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${s1}"/><stop offset="1" stop-color="${s2}"/></linearGradient>
        <linearGradient id="sg${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${g1}"/><stop offset="1" stop-color="${g2}"/></linearGradient></defs>
      <rect width="${W}" height="${H}" fill="url(#ss${id})"/>
      <rect y="${GROUND_Y}" width="${W}" height="${H - GROUND_Y}" fill="url(#sg${id})"/>
      ${body}${dusk ? `<rect width="${W}" height="${H}" fill="${dusk}" opacity=".28"/>` : ""}
      <rect x="1" y="1" width="${W - 2}" height="${H - 2}" fill="none" stroke="${INK}" stroke-width="1.5"/></svg>`;
  }
  const banner = (x, y, color, h = 30) => `<line x1="${x}" y1="${y}" x2="${x}" y2="${y - h}" stroke="${INK}" stroke-width="1.2"/>
    <path d="M${x} ${y - h} l16 3 l-4 5 l4 5 l-16 -2 z" fill="${color}" stroke="${INK}" stroke-width=".7"/>`;
  // a block of pikemen: heads, coats in the realm's colour, pikes raised or levelled
  function pikes(x0, y0, cols, rows, color, dir, levelled, r, s = 1.45) {
    let out = "";
    for (let row = rows - 1; row >= 0; row--) for (let c = 0; c < cols; c++) { // back rows first
      const x = x0 + dir * (c * 8 * s + row * 5 * s) + (r() - .5) * 2, y = y0 - row * 6 * s;
      out += `<line x1="${x}" y1="${y - 6 * s}" x2="${x + dir * (levelled ? 26 : 5) * s}" y2="${y - (levelled ? 9 : 30) * s}" stroke="#5a4028" stroke-width="${.9 * s}"/>
        <rect x="${x - 2.6 * s}" y="${y - 9 * s}" width="${5.2 * s}" height="${9 * s}" fill="${color}" stroke="${INK}" stroke-width=".5"/>
        <rect x="${x - 2.6 * s}" y="${y - 2 * s}" width="${5.2 * s}" height="${2 * s}" fill="#4a3a2a"/>
        <circle cx="${x}" cy="${y - 11.4 * s}" r="${2.3 * s}" fill="#e8c9a4" stroke="${INK}" stroke-width=".4"/>
        <path d="M${x - 2.6 * s} ${y - 12.8 * s} h${5.2 * s} l-${1 * s} -${1.6 * s} h-${3.2 * s} z" fill="#7a7a80" stroke="${INK}" stroke-width=".3"/>`;
    }
    return out;
  }
  const fallen = (x, y, color) => `<rect x="${x - 6}" y="${y - 3}" width="10" height="4" rx="1" fill="${color}" stroke="${INK}" stroke-width=".4" transform="rotate(-8 ${x} ${y})"/>
    <circle cx="${x + 6}" cy="${y - 2}" r="2" fill="#e8c9a4" stroke="${INK}" stroke-width=".4"/>`;
  const smoke = (x, y, s, r) => [0, 1, 2, 3].map((k) => `<ellipse cx="${x + k * 9 * s + r() * 6}" cy="${y - k * 5 * s}" rx="${(9 + r() * 6) * s}" ry="${(6 + r() * 3) * s}"
    fill="#efe9dc" opacity="${0.75 - k * 0.12}" stroke="${INK}" stroke-opacity=".15"/>`).join("");
  const cannon = (x, y, dir, color) => `<rect x="${x - 9}" y="${y - 6}" width="18" height="5" rx="2" fill="#4a4038" stroke="${INK}" stroke-width=".6" transform="rotate(${dir * -8} ${x} ${y})"/>
    <circle cx="${x - 4}" cy="${y}" r="3.5" fill="#6a4a2a" stroke="${INK}" stroke-width=".6"/><circle cx="${x + 4}" cy="${y}" r="3.5" fill="#6a4a2a" stroke="${INK}" stroke-width=".6"/>
    <rect x="${x - 2}" y="${y - 11}" width="4" height="4" fill="${color}" opacity=".9"/>`;

  function battle({a, b, terrain = "plains", attackerWon = true, seed = "battle"}) {
    const r = rng(seed);
    let body = `<path d="M0 ${GROUND_Y - 6} Q 95 ${GROUND_Y - 14} 190 ${GROUND_Y - 6} T 380 ${GROUND_Y - 8} L380 ${GROUND_Y} L0 ${GROUND_Y} Z" fill="${(GROUND[terrain] || GROUND.plains)[0]}" opacity=".7"/>`;
    body += smoke(150, 70, 1.4, r) + smoke(205, 64, 1.2, r);
    body += banner(64, 104, a, 46) + banner(318, 104, b, attackerWon ? 26 : 46);
    body += pikes(40, 140, 7, 3, a, 1, true, r) + pikes(342, 140, attackerWon ? 4 : 7, 3, b, -1, !attackerWon, r);
    body += cannon(128, 116, 1, a) + cannon(254, 116, -1, b);
    for (let k = 0; k < 6; k++) body += fallen(160 + r() * 70, 126 + r() * 16, k % 2 ? a : b);
    if (attackerWon) body += `<path d="M300 ${GROUND_Y + 2} l18 -6 l3 4 l-17 6 z" fill="${b}" stroke="${INK}" stroke-width=".6" transform="rotate(20 308 ${GROUND_Y})"/>`;
    for (let k = 0; k < 5; k++) body += `<circle cx="${170 + r() * 40}" cy="${80 + r() * 20}" r="${1.5 + r() * 1.5}" fill="#f7c35a" opacity=".9"/>`;
    return frame(body, terrain);
  }

  function castle(x, y, color, scale = 1) {
    const s = scale, stone = "#ddd0ac", dark = "#bfae86";
    return `<g transform="translate(${x} ${y}) scale(${s})">
      <rect x="-46" y="-34" width="92" height="34" fill="${stone}" stroke="${INK}" stroke-width=".9"/>
      ${[-46, -28, -10, 8, 26].map((k) => `<rect x="${k}" y="-40" width="10" height="7" fill="${stone}" stroke="${INK}" stroke-width=".7"/>`).join("")}
      ${[-58, 46].map((k) => `<rect x="${k}" y="-54" width="14" height="54" fill="${dark}" stroke="${INK}" stroke-width=".9"/>
        <path d="M${k - 2} -54 l9 -14 l9 14 z" fill="#8a5a3a" stroke="${INK}" stroke-width=".7"/>`).join("")}
      <path d="M-8 0 v-14 a8 8 0 0 1 16 0 v14 z" fill="#3a2414"/>
      ${banner(0, -40, color, 26)}</g>`;
  }
  function siege({by, of, terrain = "plains", seed = "siege"}) {
    const r = rng(seed);
    let body = castle(268, GROUND_Y + 8, of);
    for (let k = 0; k < 4; k++) { const x = 30 + k * 34 + r() * 8, y = GROUND_Y + 20 + r() * 14;
      body += `<path d="M${x - 13} ${y} L${x} ${y - 20} L${x + 13} ${y} Z" fill="${k % 2 ? "#efe6cf" : by}" stroke="${INK}" stroke-width=".7"/><line x1="${x}" y1="${y - 20}" x2="${x}" y2="${y - 26}" stroke="${INK}"/>`; }
    body += `<path d="M150 ${GROUND_Y + 30} q 30 -6 60 0 q 30 6 50 0" fill="none" stroke="#6a5030" stroke-width="2" stroke-dasharray="5 3"/>`;
    body += cannon(178, GROUND_Y + 24, 1, by) + cannon(205, GROUND_Y + 34, 1, by);
    body += smoke(196, GROUND_Y + 8, 1.1, r) + smoke(232, GROUND_Y - 18, 0.9, r);
    body += banner(60, GROUND_Y + 14, by, 34);
    return frame(body, terrain);
  }
  function treaty({a, b}) {
    let body = `<rect x="70" y="16" width="240" height="118" rx="3" fill="#f3e6c4" stroke="${INK}" stroke-width="1"/>
      <path d="M70 22 q -12 -6 -6 -14 h 14 M310 128 q 12 6 6 14 h -14" fill="#e8d6aa" stroke="${INK}" stroke-width=".8"/>`;
    for (let k = 0; k < 7; k++) body += `<path d="M92 ${34 + k * 11} q 50 ${k % 2 ? 3 : -3} 100 0 t ${k === 6 ? 40 : 96} 0" fill="none" stroke="#6a5a40" stroke-width="1.1" opacity=".75"/>`;
    for (const [x, c] of [[150, a], [230, b]]) body += `<path d="M${x - 6} 116 l-6 22 l6 -4 l4 6 z M${x + 6} 116 l6 22 l-6 -4 l-4 6 z" fill="${c}" stroke="${INK}" stroke-width=".6"/>
      <circle cx="${x}" cy="114" r="13" fill="${c}" stroke="${INK}" stroke-width="1"/><circle cx="${x}" cy="114" r="8" fill="none" stroke="#fff6dc" stroke-opacity=".6" stroke-width="1.2"/>`;
    body += `<path d="M300 40 q 30 -30 50 -32 q -10 18 -40 44 z" fill="#f6f1e4" stroke="${INK}" stroke-width=".8"/><line x1="300" y1="40" x2="286" y2="60" stroke="${INK}" stroke-width="1.2"/>`;
    return frame(body, "plains", {sky: ["#5a3a22", "#3a2414"], ground: ["#3a2414", "#2a190e"]});
  }
  function laurels({color}) {
    let body = "";
    for (let k = 0; k < 14; k++) body += `<line x1="190" y1="72" x2="${190 + Math.cos(k / 14 * Math.PI * 2) * 200}" y2="${72 + Math.sin(k / 14 * Math.PI * 2) * 200}" stroke="#fff3cf" stroke-width="10" opacity=".18"/>`;
    for (const side of [-1, 1]) for (let k = 0; k < 9; k++) { const ang = (200 + side * (k * 14 + 20)) * Math.PI / 180, x = 190 + Math.cos(ang) * 48 * side * -1, y = 72 + Math.sin(ang) * 48;
      body += `<ellipse cx="${190 + side * (Math.sin(k / 9 * Math.PI) * 46 + 4)}" cy="${118 - k * 10}" rx="9" ry="4" fill="#5d7a35" stroke="${INK}" stroke-width=".5" transform="rotate(${side * (40 - k * 8)} ${190 + side * (Math.sin(k / 9 * Math.PI) * 46 + 4)} ${118 - k * 10})"/>`; void x; void y; }
    body += `<path d="M168 40 h44 v44 l-22 -10 l-22 10 z" fill="${color}" stroke="${INK}" stroke-width="1"/>
      <path d="M176 22 l6 12 l8 -14 l8 14 l6 -12 l-2 16 h-24 z" fill="#e6c27e" stroke="#5a3f17" stroke-width=".8"/>`;
    return frame(body, "plains", {sky: ["#f3dea0", "#c89a50"], ground: ["#a97f3a", "#7c5a25"]});
  }
  function plague({color, seed = "plague"}) {
    const r = rng(seed);
    let body = "";
    for (let k = 0; k < 9; k++) { const x = 20 + k * 40 + r() * 10, h = 24 + r() * 26;
      body += `<rect x="${x}" y="${GROUND_Y - h}" width="30" height="${h}" fill="#7a6e5e" stroke="${INK}" stroke-width=".7"/><path d="M${x - 3} ${GROUND_Y - h} l18 -14 l18 14 z" fill="#5a4a3a" stroke="${INK}" stroke-width=".6"/>
        ${r() > .5 ? `<path d="M${x + 15} ${GROUND_Y - 14} v-10 M${x + 10} ${GROUND_Y - 20} h10" stroke="#b8333a" stroke-width="2"/>` : ""}`; }
    body += `<rect x="176" y="34" width="22" height="70" fill="#6a6050" stroke="${INK}"/><path d="M172 34 l15 -20 l15 20 z" fill="#4a3a2a" stroke="${INK}"/>${banner(187, 14, color, 0)}`;
    for (let k = 0; k < 7; k++) { const x = 40 + r() * 300, y = 20 + r() * 40; body += `<path d="M${x} ${y} q 4 -4 8 0 q 4 -4 8 0" fill="none" stroke="#1a1410" stroke-width="1.4"/>`; }
    body += `<path d="M120 ${GROUND_Y + 22} h46 l-6 10 h-34 z" fill="#5a4030" stroke="${INK}"/><circle cx="128" cy="${GROUND_Y + 34}" r="5" fill="#3a2a1a"/><circle cx="158" cy="${GROUND_Y + 34}" r="5" fill="#3a2a1a"/>`;
    return frame(body, "plains", {sky: ["#7c7a74", "#b5a88e"], ground: ["#6e6a52", "#4e4a3a"], dusk: "#2a1a10"});
  }
  function frost({seed = "frost"}) {
    const r = rng(seed);
    let body = `<path d="M0 ${GROUND_Y + 18} q 120 -10 240 6 t 140 -4 v12 q -120 10 -240 -4 t -140 6 z" fill="#cfe3ea" stroke="#9fbccc" stroke-width=".8"/>`;
    for (let k = 0; k < 7; k++) { const x = 20 + k * 55 + r() * 20, y = GROUND_Y + 6 + r() * 30;
      body += `<path d="M${x} ${y} v-26 M${x} ${y - 14} l-8 -8 M${x} ${y - 18} l7 -9 M${x} ${y - 24} l-4 -6" stroke="#4a3a2a" stroke-width="1.4" fill="none"/>`; }
    for (let k = 0; k < 70; k++) body += `<circle cx="${r() * W}" cy="${r() * H}" r="${0.8 + r() * 1.4}" fill="#ffffff" opacity=".9"/>`;
    return frame(body, "plains", {sky: ["#c9d6de", "#eef2f3"], ground: ["#f4f7f8", "#dfe7ea"]});
  }
  function galleon({seed = "silver"}) {
    const r = rng(seed);
    let body = `<rect y="80" width="${W}" height="${H - 80}" fill="#5f8aa3"/>`;
    for (let k = 0; k < 10; k++) body += `<path d="M${r() * W} ${92 + r() * 50} q 8 -4 16 0" fill="none" stroke="#e8f0f2" stroke-width="1" opacity=".7"/>`;
    body += `<path d="M110 100 h150 l-18 22 h-118 z" fill="#6a4426" stroke="${INK}" stroke-width="1"/><path d="M110 100 l-6 -14 h30 v14" fill="#7a5030" stroke="${INK}"/>
      ${[150, 190, 228].map((x, k) => `<line x1="${x}" y1="100" x2="${x}" y2="${36 - k * 2}" stroke="${INK}" stroke-width="1.4"/>
        <path d="M${x - 16} ${50} q 16 8 32 0 v24 q -16 8 -32 0 z" fill="#f4ecd6" stroke="${INK}" stroke-width=".7"/>`).join("")}
      <path d="M190 34 l14 4 l-14 4 z" fill="#d9b13c" stroke="${INK}" stroke-width=".6"/>`;
    body += `<rect x="270" y="112" width="40" height="22" fill="#6a4426" stroke="${INK}"/>`;
    for (let k = 0; k < 9; k++) body += `<circle cx="${276 + r() * 28}" cy="${110 + r() * 6}" r="3" fill="#d8dde2" stroke="#8a929a" stroke-width=".6"/>`;
    return frame(body, "plains", {sky: ["#e9cf9a", "#f6ead2"], ground: ["#5f8aa3", "#476e86"]});
  }

  // ---- the ordinary news of the age: a person, a house, a church, and the scenes built of them
  const SKIN = "#e8c9a4";
  // a townsman or a lord, standing at (x, y); holding a fork, a torch, a hammer or a tankard
  function person(x, y, coat, {s = 1, hat = "#4a3424", hold = "", robe = false, flip = 1} = {}) {
    const hands = {fork: `<line x1="4" y1="-6" x2="7" y2="-26" stroke="#5a4028" stroke-width="1"/><path d="M5 -26 v-4 M7 -26.4 v-4.4 M9 -26.8 v-4" stroke="#6a6a70" stroke-width=".9"/>`,
      torch: `<line x1="4" y1="-6" x2="6" y2="-22" stroke="#5a4028" stroke-width="1.2"/><path d="M6 -22 q -4 -5 0 -11 q 4 6 0 11 z" fill="#f2a33a" stroke="#c4561e" stroke-width=".5"/>`,
      hammer: `<line x1="4" y1="-9" x2="9" y2="-20" stroke="#5a4028" stroke-width="1.1"/><rect x="6.5" y="-23" width="6" height="3" fill="#6a6a70" transform="rotate(-24 9 -21)"/>`,
      staff: `<line x1="5" y1="2" x2="5" y2="-26" stroke="#5a4028" stroke-width="1.1"/>`,
      musket: `<line x1="-2" y1="-10" x2="14" y2="-16" stroke="#3a2a18" stroke-width="1.6"/>`}[hold] || "";
    const body = robe ? `<path d="M-4.5 0 L-3 -13 h6 L4.5 0 z" fill="${coat}" stroke="${INK}" stroke-width=".5"/>`
      : `<rect x="-3" y="-13" width="6" height="8" fill="${coat}" stroke="${INK}" stroke-width=".5"/><path d="M-2.6 -5 v5 M2.6 -5 v5" stroke="#3a2a1a" stroke-width="1.6"/>`;
    return `<g transform="translate(${x} ${y}) scale(${s * flip} ${s})">${body}${hands}
      <circle cy="-15.6" r="2.6" fill="${SKIN}" stroke="${INK}" stroke-width=".4"/>
      ${hat ? `<path d="M-4 -17 h8 M-2.4 -17 v-2.4 h4.8 v2.4" fill="${hat}" stroke="${hat}" stroke-width="1.3"/>` : ""}</g>`;
  }
  function house(x, w, h, {wall = "#e6d6b0", roof = "#9a5236", beams = true} = {}) {
    const y = GROUND_Y;
    return `<rect x="${x}" y="${y - h}" width="${w}" height="${h}" fill="${wall}" stroke="${INK}" stroke-width=".7"/>
      ${beams ? `<path d="M${x} ${y - h / 2} h${w} M${x + w / 3} ${y - h} v${h} M${x + 2 * w / 3} ${y - h} v${h}" stroke="#6a4a2a" stroke-width=".9"/>` : ""}
      <path d="M${x - 3} ${y - h} L${x + w / 2} ${y - h - w * .55} L${x + w + 3} ${y - h} z" fill="${roof}" stroke="${INK}" stroke-width=".7"/>
      <rect x="${x + w / 2 - 3}" y="${y - 9}" width="6" height="9" fill="#4a2e18"/>`;
  }
  function church(x, scale = 1) {
    return `<g transform="translate(${x} ${GROUND_Y}) scale(${scale})">
      <rect x="-34" y="-62" width="68" height="62" fill="#d8ccad" stroke="${INK}" stroke-width=".9"/>
      <path d="M-38 -62 L0 -92 L38 -62 z" fill="#8a5a3a" stroke="${INK}" stroke-width=".8"/>
      <rect x="-8" y="-118" width="16" height="30" fill="#cfc2a0" stroke="${INK}" stroke-width=".8"/><path d="M-10 -118 L0 -136 L10 -118 z" fill="#6e4a30" stroke="${INK}" stroke-width=".7"/>
      <path d="M0 -136 v-8 M-3 -141 h6" stroke="${INK}" stroke-width="1"/>
      <circle cy="-72" r="7" fill="#a8b8c8" stroke="${INK}" stroke-width=".8"/><path d="M0 -79 v14 M-7 -72 h14" stroke="${INK}" stroke-width=".5"/>
      <path d="M-12 0 v-26 a12 12 0 0 1 24 0 v26 z" fill="#5a3a20" stroke="${INK}" stroke-width=".8"/><path d="M0 -38 v38" stroke="#3a2412" stroke-width=".8"/></g>`;
  }
  const crowd = (x0, x1, y, r, colours, opts = {}) => { let out = "";
    for (let x = x0; x < x1; x += 11 + r() * 7) out += person(x, y + r() * 8, colours[Math.floor(r() * colours.length)], {...opts, s: .95 + r() * .25, hat: r() > .5 ? "#4a3424" : ""});
    return out; };
  const TOWNSFOLK = ["#8a4a3a", "#4a6a8a", "#6a7a3a", "#7a5a8a", "#9a7a3a", "#5a5a5a"];
  const sun = (x, y, rays = true) => `${rays ? Array.from({length: 12}, (_, k) => `<line x1="${x}" y1="${y}" x2="${x + Math.cos(k * Math.PI / 6) * 28}" y2="${y + Math.sin(k * Math.PI / 6) * 28}" stroke="#f7d27a" stroke-width="2" opacity=".55"/>`).join("") : ""}
    <circle cx="${x}" cy="${y}" r="13" fill="#f9dc8a" stroke="#d9a83a" stroke-width="1"/>`;

  function reformation({color = "#7a5a3a", seed = "reformation"}) {
    const r = rng(seed);
    let body = house(14, 46, 34) + house(318, 50, 30, {roof: "#7a4a30"}) + church(190, .74);
    body += `<rect x="182" y="${GROUND_Y - 24}" width="8" height="10" fill="#f8f2e0" stroke="${INK}" stroke-width=".5" transform="rotate(-4 186 ${GROUND_Y - 19})"/>`;
    for (let k = 0; k < 4; k++) body += `<line x1="183.5" y1="${GROUND_Y - 22 + k * 2}" x2="188.5" y2="${GROUND_Y - 22.4 + k * 2}" stroke="#4a3a2a" stroke-width=".5"/>`;
    body += person(170, GROUND_Y + 2, "#5a4630", {robe: true, hat: "", hold: "hammer", s: 1.3});
    body += crowd(70, 150, GROUND_Y + 22, r, TOWNSFOLK) + crowd(232, 330, GROUND_Y + 22, r, TOWNSFOLK, {flip: -1});
    body += banner(352, GROUND_Y + 30, color, 30);
    return frame(body, "plains", {sky: ["#c8d4d8", "#efe4c8"]});
  }
  function harvest({color = "#c9a24a", seed = "harvest"}) {
    const r = rng(seed);
    let body = sun(318, 34);
    for (let row = 0; row < 3; row++) for (let k = 0; k < 9; k++) { const x = 18 + k * 42 + row * 14 + r() * 8, y = GROUND_Y + 12 + row * 14, s = .8 + row * .2;
      body += `<path d="M${x - 7 * s} ${y} L${x} ${y - 18 * s} L${x + 7 * s} ${y} z" fill="#e2b84e" stroke="#9a7424" stroke-width=".6"/><path d="M${x - 6 * s} ${y - 5 * s} h${12 * s}" stroke="#9a7424" stroke-width=".8"/>`; }
    body += `<path d="M120 ${GROUND_Y + 4} h70 l-6 -26 h-58 z" fill="#e8c560" stroke="#8a6a24" stroke-width=".8"/><rect x="118" y="${GROUND_Y + 2}" width="74" height="8" fill="#7a5030" stroke="${INK}" stroke-width=".7"/>
      <circle cx="132" cy="${GROUND_Y + 12}" r="7" fill="none" stroke="#4a3020" stroke-width="2"/><circle cx="178" cy="${GROUND_Y + 12}" r="7" fill="none" stroke="#4a3020" stroke-width="2"/>
      <path d="M192 ${GROUND_Y + 6} l22 4" stroke="#5a4028" stroke-width="1.4"/>`;
    body += person(232, GROUND_Y + 14, "#8a6a3a", {hold: "fork", s: 1.2}) + person(96, GROUND_Y + 16, "#6a7a3a", {s: 1.15, flip: -1}) + banner(30, GROUND_Y + 2, color, 26);
    return frame(body, "plains", {sky: ["#f4dca0", "#f7ecd0"], ground: ["#d8b65a", "#b8923a"]});
  }
  function counting({color = "#7a5a3a", seed = "fuggers"}) {
    const r = rng(seed);
    let body = `<rect x="0" y="0" width="${W}" height="${H}" fill="#4a2e1a"/>
      <path d="M150 12 h80 v64 h-80 z" fill="#c9d6dc" stroke="#2a1a0e" stroke-width="3"/><path d="M190 12 v64 M150 44 h80" stroke="#2a1a0e" stroke-width="2"/>
      <rect x="40" y="96" width="300" height="12" fill="#7a4a26" stroke="#2a1a0e"/><rect x="40" y="108" width="300" height="42" fill="#5a3418" stroke="#2a1a0e"/>`;
    for (let s = 0; s < 6; s++) { const x = 70 + s * 26 + r() * 6, n = 3 + Math.floor(r() * 6);
      for (let k = 0; k < n; k++) body += `<ellipse cx="${x}" cy="${94 - k * 3.2}" rx="9" ry="3" fill="#e2b84e" stroke="#8a6a1a" stroke-width=".6"/>`; }
    body += `<path d="M232 94 l30 -6 l30 6 l-30 4 z" fill="#f4ecd6" stroke="#2a1a0e" stroke-width=".8"/><path d="M262 88 v8" stroke="#2a1a0e" stroke-width=".6"/>`;
    for (let k = 0; k < 4; k++) body += `<path d="M240 ${91 + k * .3} l${18} -3.6 M266 ${88 + k * 1.4} l20 3.6" stroke="#6a5a40" stroke-width=".5"/>`;
    body += `<line x1="312" y1="94" x2="312" y2="62" stroke="#b08a3a" stroke-width="1.6"/><line x1="296" y1="64" x2="328" y2="64" stroke="#b08a3a" stroke-width="1.6"/>
      <path d="M296 64 l-6 14 h12 z M328 64 l-6 14 h12 z" fill="none" stroke="#b08a3a"/><path d="M290 78 h12 M322 78 h12" stroke="#b08a3a" stroke-width="2"/>
      <path d="M52 94 q -4 -18 8 -22 q 12 4 8 22 z" fill="#8a6a3a" stroke="#2a1a0e" stroke-width=".8"/><path d="M56 72 l4 -4 l4 4" fill="none" stroke="#2a1a0e"/>`;
    body += banner(360, 92, color, 40);
    return frame(body, "plains", {sky: ["#4a2e1a", "#3a2414"], ground: ["#5a3418", "#3a2010"]});
  }
  function easel({color = "#7a5a3a"}) {
    let body = `<rect width="${W}" height="${H}" fill="#e8dcc0"/>
      <path d="M40 0 v150 M90 0 v150" stroke="#cbb994" stroke-width="10"/><path d="M290 150 v-100 a40 40 0 0 1 80 0 v100" fill="#b9d0da" stroke="#a8946a" stroke-width="6"/>
      <rect y="122" width="${W}" height="28" fill="#a9845a"/>`;
    for (let k = 0; k < 10; k++) body += `<rect x="${k * 40 + (k % 2) * 20}" y="122" width="20" height="28" fill="#8a6440" opacity=".5"/>`;
    body += `<path d="M150 140 L176 20 M222 140 L196 20 M186 20 v126" stroke="#6a4424" stroke-width="3"/>
      <rect x="146" y="30" width="80" height="84" fill="#f2e6c8" stroke="#8a5a20" stroke-width="4"/>
      <rect x="150" y="34" width="72" height="76" fill="#3a3a2a"/><path d="M150 110 q 36 -50 72 0 z" fill="${color}"/>
      <ellipse cx="186" cy="62" rx="12" ry="15" fill="#e8c9a4"/><path d="M174 58 q 12 -18 24 0 q -4 -10 -12 -10 q -8 0 -12 10 z" fill="#4a2e1a"/>
      <path d="M126 112 h20" stroke="#6a4424" stroke-width="3"/>
      <ellipse cx="96" cy="100" rx="22" ry="14" fill="#c99a5a" stroke="#6a4424" stroke-width="1"/><circle cx="88" cy="96" r="3" fill="#b8333a"/><circle cx="98" cy="93" r="3" fill="#2f5aa0"/><circle cx="106" cy="98" r="3" fill="#e2b84e"/><circle cx="96" cy="104" r="2.6" fill="#3a7a3a"/>
      <circle cx="84" cy="104" r="3.6" fill="#e8dcc0"/><line x1="108" y1="108" x2="128" y2="88" stroke="#4a2e1a" stroke-width="1.6"/>`;
    body += person(262, 140, "#3a2a4a", {s: 2, hat: "#2a1a2a", flip: -1});
    return frame(body, "plains", {sky: ["#e8dcc0", "#e8dcc0"], ground: ["#a9845a", "#8a6440"]});
  }
  function revolt({color = "#7a5a3a", seed = "revolt"}) {
    const r = rng(seed);
    let body = `<path d="M210 ${GROUND_Y} v-48 h96 v48 z" fill="#c8b48c" stroke="${INK}" stroke-width=".8"/><path d="M204 ${GROUND_Y - 48} L258 ${GROUND_Y - 80} L312 ${GROUND_Y - 48} z" fill="#5a3a2a" stroke="${INK}"/>
      ${[224, 252, 280].map((x) => `<rect x="${x}" y="${GROUND_Y - 38}" width="10" height="12" fill="#f2a33a"/>`).join("")}${banner(258, GROUND_Y - 80, color, 18)}`;
    for (let k = 0; k < 9; k++) { const x = 214 + r() * 90, h = 18 + r() * 30;
      body += `<path d="M${x - 8} ${GROUND_Y - 48 + r() * 20} q ${4} ${-h} ${8} ${-h - 6} q ${6} ${h / 2} ${8} ${h + 6} z" fill="${k % 2 ? "#f2a33a" : "#e0662a"}" opacity=".9"/>`; }
    body += smoke(230, 20, 1.4, r) + smoke(280, 30, 1.1, r);
    body += crowd(20, 190, GROUND_Y + 30, r, ["#6a5a3a", "#5a4a3a", "#7a6a4a", "#4a3a2a"], {hold: "fork"});
    for (let k = 0; k < 4; k++) body += person(40 + k * 40 + r() * 10, GROUND_Y + 40, "#5a4a32", {hold: "torch", s: 1.2, hat: ""});
    return frame(body, "plains", {sky: ["#5a2a1a", "#d07a3a"], ground: ["#5a4a2a", "#3a2a1a"]});
  }
  function comet({seed = "comet"}) {
    const r = rng(seed);
    let body = "";
    const tail = `tail${++uid}`;
    for (let k = 0; k < 80; k++) body += `<circle cx="${r() * W}" cy="${r() * 96}" r="${.4 + r() * .9}" fill="#fff8e0" opacity="${.5 + r() * .5}"/>`;
    body += `<defs><linearGradient id="${tail}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff6d0" stop-opacity="0"/><stop offset="1" stop-color="#fff6d0" stop-opacity=".95"/></linearGradient></defs>
      <path d="M60 14 Q 180 30 268 46 L 272 54 Q 180 46 54 26 z" fill="url(#${tail})"/><circle cx="272" cy="50" r="6" fill="#fffbe8"/><circle cx="272" cy="50" r="13" fill="#fff6d0" opacity=".25"/>`;
    body += `<path d="M0 ${GROUND_Y} V84 h20 v-10 h14 v12 h22 v-20 l8 -12 l8 12 v20 h24 v-8 h30 v16 h16 v-30 l10 -18 l10 18 v30 h40 v-14 h26 v8 h30 v-16 h18 v22 h34 v-6 h30 V${GROUND_Y} z" fill="#1e1a24"/>`;
    for (let k = 0; k < 9; k++) body += `<rect x="${20 + r() * 330}" y="${80 + r() * 18}" width="3" height="4" fill="#f2c45a" opacity=".85"/>`;
    for (let k = 0; k < 6; k++) { const x = 60 + k * 48 + r() * 10;
      body += `<g transform="translate(${x} ${GROUND_Y + 34})"><path d="M-4 0 L-3 -13 h6 L4 0 z" fill="#4a4458"/><circle cy="-15.6" r="2.6" fill="#4a4458"/><path d="M2 -12 l7 -9" stroke="#4a4458" stroke-width="1.6"/></g>`; }
    return frame(body, "plains", {sky: ["#0e1430", "#3a3a5a"], ground: ["#26222c", "#16141a"]});
  }
  function drill({color = "#7a5a3a", seed = "drill"}) {
    const r = rng(seed);
    let body = house(300, 54, 30, {roof: "#6e4a30"});
    for (let row = 0; row < 2; row++) for (let k = 0; k < 9; k++) body += person(60 + k * 20 + row * 8, GROUND_Y + 22 + row * 14, color, {hold: "musket", s: 1.15, hat: "#3a2a1a"});
    body += smoke(250, GROUND_Y + 2, 1, r) + smoke(262, GROUND_Y + 18, .8, r);
    for (let k = 0; k < 5; k++) body += `<circle cx="${244 + r() * 12}" cy="${GROUND_Y + 10 + r() * 20}" r="1.6" fill="#f7c35a"/>`;
    body += person(30, GROUND_Y + 34, "#5a2a2a", {s: 1.5, hat: "#2a1a1a", hold: "staff"}) + banner(330, GROUND_Y + 40, color, 34);
    return frame(body, "plains");
  }
  function court({color = "#7a5a3a", seed = "nobles"}) {
    const r = rng(seed);
    let body = `<rect width="${W}" height="${H}" fill="#6a4a2e"/><rect y="118" width="${W}" height="32" fill="#4a3220"/>
      ${[30, 110, 270, 350].map((x) => `<rect x="${x - 7}" y="0" width="14" height="118" fill="#5a3e26" stroke="#2a1a0e" stroke-width=".6"/>`).join("")}
      ${[70, 310].map((x) => `<path d="M${x - 16} 8 h32 v50 l-16 -8 l-16 8 z" fill="${color}" stroke="#2a1a0e" stroke-width=".8"/>`).join("")}
      <rect x="150" y="96" width="80" height="22" fill="#7a5030" stroke="#2a1a0e"/><path d="M170 96 v-50 h40 v50" fill="${color}" stroke="#2a1a0e"/>
      <path d="M166 46 l24 -14 l24 14 z" fill="#e2b84e" stroke="#6a4a1a" stroke-width=".8"/>`;
    body += person(190, 114, "#e8dcc0", {robe: true, s: 1.6, hat: "#e2b84e"});
    const lords = ["#7a2a2a", "#2a4a6a", "#4a2a5a", "#2a5a3a", "#6a5a2a", "#5a2a4a"];
    for (let k = 0; k < 6; k++) { const left = k < 3, x = left ? 40 + k * 32 : 236 + (k - 3) * 32 + 14;
      body += person(x + r() * 6, 146, lords[k], {robe: true, s: 1.7, hat: "#1a1a1a", flip: left ? 1 : -1}); }
    return frame(body, "plains", {sky: ["#6a4a2e", "#5a3e26"], ground: ["#4a3220", "#3a2618"]});
  }
  function fair({color = "#7a5a3a", seed = "fair"}) {
    const r = rng(seed);
    const awnings = [["#b8333a", "#f4ecd6"], ["#2f5aa0", "#f4ecd6"], ["#3a7a3a", "#f2d06a"], [color, "#f4ecd6"]];
    let body = church(196, .7);
    body += `<path d="M0 22 Q 95 44 190 26 T 380 30" fill="none" stroke="#5a4028" stroke-width=".8"/>`;
    for (let k = 0; k < 18; k++) { const x = 10 + k * 21, y = 22 + Math.sin(k / 18 * Math.PI * 2) * 6 + 10 * Math.sin(k / 9 * Math.PI) * .6;
      body += `<path d="M${x} ${y} l5 12 l5 -12 z" fill="${["#b8333a", "#e2b84e", "#2f5aa0", "#3a7a3a"][k % 4]}" stroke="${INK}" stroke-width=".3"/>`; }
    [[20, 0], [104, 1], [248, 2], [318, 3]].forEach(([x, k]) => { const [a, b] = awnings[k];
      body += `<rect x="${x}" y="${GROUND_Y - 16}" width="52" height="30" fill="#8a6440" stroke="${INK}" stroke-width=".6"/>`;
      for (let s = 0; s < 6; s++) body += `<path d="M${x - 4 + s * 10} ${GROUND_Y - 34} h10 l2 18 h-10 z" fill="${s % 2 ? b : a}" stroke="${INK}" stroke-width=".4"/>`;
      for (let g = 0; g < 4; g++) body += `<circle cx="${x + 8 + g * 12}" cy="${GROUND_Y - 18}" r="3.4" fill="${["#c0563f", "#e2b84e", "#8aa04a", "#7a5aa0"][(g + k) % 4]}" stroke="${INK}" stroke-width=".3"/>`; });
    body += `<ellipse cx="210" cy="${GROUND_Y + 22}" rx="8" ry="10" fill="#8a5a30" stroke="${INK}" stroke-width=".6"/><path d="M202 ${GROUND_Y + 18} h16 M202 ${GROUND_Y + 26} h16" stroke="#4a2e18"/>`;
    body += crowd(10, 370, GROUND_Y + 40, r, TOWNSFOLK);
    return frame(body, "plains", {sky: ["#b8d4e0", "#f4ead0"]});
  }
  function mine({seed = "mine"}) {
    const r = rng(seed);
    let body = `<path d="M0 ${GROUND_Y} L60 40 L110 70 L170 18 L260 ${GROUND_Y} z" fill="#9a8a6a" stroke="${INK}" stroke-width=".8"/>
      <path d="M200 ${GROUND_Y} L280 30 L380 ${GROUND_Y - 10} V${GROUND_Y} z" fill="#8a7a5a" stroke="${INK}" stroke-width=".8"/>
      <path d="M160 18 l10 0 l-8 14 z M276 30 l8 2 l-8 10 z" fill="#f4f2ea"/>
      <path d="M122 ${GROUND_Y} v-38 h46 v38" fill="#1a120a" stroke="#6a4424" stroke-width="5"/><path d="M116 ${GROUND_Y - 40} h58" stroke="#6a4424" stroke-width="6"/>
      <circle cx="176" cy="${GROUND_Y - 30}" r="3" fill="#f2c45a"/><circle cx="176" cy="${GROUND_Y - 30}" r="8" fill="#f2c45a" opacity=".25"/>
      <path d="M140 ${GROUND_Y + 2} L300 ${GROUND_Y + 40} M150 ${GROUND_Y + 2} L314 ${GROUND_Y + 36}" stroke="#4a4038" stroke-width="1.4"/>`;
    for (let k = 0; k < 7; k++) body += `<path d="M${150 + k * 22} ${GROUND_Y + 5 + k * 5} l10 2" stroke="#6a4424" stroke-width="2"/>`;
    body += `<path d="M228 ${GROUND_Y + 14} l40 10 l-4 16 l-34 -8 z" fill="#6a4426" stroke="${INK}"/><circle cx="238" cy="${GROUND_Y + 32}" r="5" fill="#3a2a1a"/><circle cx="260" cy="${GROUND_Y + 37}" r="5" fill="#3a2a1a"/>`;
    for (let k = 0; k < 8; k++) body += `<circle cx="${236 + r() * 26}" cy="${GROUND_Y + 14 + r() * 6}" r="${2.4 + r() * 1.6}" fill="${k % 3 ? "#9aa2aa" : "#e2b84e"}" stroke="${INK}" stroke-width=".4"/>`;
    body += person(300, GROUND_Y + 44, "#5a4a3a", {hold: "hammer", s: 1.3, hat: "#3a3a3a"});
    return frame(body, "hills");
  }
  // the scene for a fortune of the age, by its id; null when it has none
  function ofEvent(id, {color = "#7a5a3a", seed = id} = {}) {
    const make = {reformation: () => reformation({color, seed}), reformer: () => drill({color, seed}), plague: () => plague({color, seed}), great_plague: () => plague({color, seed}),
      harvest: () => harvest({color, seed}), fuggers: () => counting({color, seed}), artist: () => easel({color}), revolt: () => revolt({color, seed}),
      silver: () => galleon({seed}), silver_flood: () => galleon({seed}), comet: () => comet({seed}), nobles: () => court({color, seed}), fair: () => fair({color, seed}),
      mine: () => mine({seed}), frozen_harvests: () => frost({seed}), ice_age: () => frost({seed}), price_revolution: () => galleon({seed})}[id];
    return make ? make() : null;
  }
  return {battle, siege, treaty, laurels, plague, frost, galleon, reformation, harvest, counting, easel, revolt, comet, drill, court, fair, mine, ofEvent};
})();
