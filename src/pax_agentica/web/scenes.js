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
  return {battle, siege, treaty, laurels, plague, frost, galleon};
})();
