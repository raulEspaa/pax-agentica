// Pax Agentica map: draws the geography once, then paints any state of the world onto it.
// Shared by the replay (replay.html, inlined) and the play page (play.html, served).
"use strict";

const PaxMap = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs = {}, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const mix = (a, b, t) => { const x = hex(a), y = hex(b);
    return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join(""); };
  const devColor = (v) => { const t = Math.min(1, (v - 1) / 9);
    return t < .5 ? mix("#f3e6bd", "#e09a3e", t * 2) : mix("#e09a3e", "#7a2a12", (t - .5) * 2); };
  const cap = (s) => s[0].toUpperCase() + s.slice(1);

  const TERRAIN = {plains: "#a9b06c", forest: "#4f6d36", hills: "#a58c5a", marsh: "#5f7e6b", mountains: "#8d8678"};
  const RES = [["ducats", "Ducats", "💰"], ["manpower", "Manpower", "👥"], ["iron", "Iron", "⛏"],
               ["grain", "Grain", "🌾"], ["timber", "Timber", "🪵"], ["goods", "Goods", "🧵"]];
  const GOOD = {grain: "grain", iron: "iron", gold: "gold", timber: "timber"};
  const BICON = {marketplace: "⚖", farm_estates: "🌾", ironworks: "⚒", lumber_mill: "🪚", university: "📜", bank: "🏦", cathedral: "⛪", training_grounds: "🎯",
                 barracks: "⚔", armory: "🛡", fort: "🏰", citadel: "🏯", stables: "🐴", cannon_foundry: "🔥",
                 military_academy: "🎓", royal_exchange: "⚜", observatory: "🔭", workshop: "🔨"};
  const UICON = {infantry: "⚔", archers: "🏹", cavalry: "🐎", artillery: "💣"};
  const ICON = {proclamation: "📣", stance_changed: "⚑", province_ceded: "📜", tribute_paid: "💰", monument_raised: "🏛", proposal_countered: "↔",
    war_declared: "⚔", joined_war: "⚔", call_to_arms_ignored: "💔", treaty_signed: "🤝",
    treaty_broken: "💔", treaty_cancelled: "✂", treaty_expired: "⌛", peace_signed: "🕊", trade_completed: "⚖",
    trade_failed: "✗", gift: "🎁", battle: "⚔", province_captured: "⚑", capital_moved: "♛", nation_eliminated: "☠",
    developed: "⌂", built: "🏗", game_over: "👑", researched: "⚙", general_appointed: "⚑", general_fell: "✝", message: "✉", proposal_made: "📜", proposal_rejected: "✗",
    proposal_expired: "⌛", order_rejected: "⚠", recruited: "⚔", disbanded: "⚐", moved: "➜", desertion: "⚠",
    stability_changed: "⚖"};
  const MAJOR = new Set(["war_declared", "joined_war", "call_to_arms_ignored", "treaty_broken", "peace_signed",
    "nation_eliminated", "game_over", "capital_moved", "general_fell"]);
  const MINOR = new Set(["developed", "built", "battle", "treaty_expired", "recruited", "moved", "disbanded", "researched"]);
  const BAD = new Set(["order_rejected", "desertion", "trade_failed"]);
  const costText = (c) => RES.map(([, label], k) => c[k] ? `${c[k]} ${label.toLowerCase()}` : "").filter(Boolean).join(", ") || "nothing";

  function create(svg, S, hooks = {}) {
    const P = S.provinces, N = S.nations, B = S.buildings, W = S.map.width, H = S.map.height;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.classList.add("paxmap");
    const defs = el("defs", {}, svg);
    defs.innerHTML = `
      <radialGradient id="seaFill" cx="45%" cy="42%" r="78%">
        <stop offset="0" stop-color="#5a8fac"/><stop offset=".6" stop-color="#3a6b88"/><stop offset="1" stop-color="#1f4058"/>
      </radialGradient>
      <filter id="grain" x="0" y="0" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="7"/>
        <feColorMatrix type="saturate" values="0"/>
        <feComponentTransfer><feFuncA type="table" tableValues="0 .16"/></feComponentTransfer>
      </filter>
      <filter id="relief" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency=".022" numOctaves="5" seed="11"/>
        <feDiffuseLighting surfaceScale="2.4" lighting-color="#fff"><feDistantLight azimuth="225" elevation="55"/></feDiffuseLighting>
        <feColorMatrix type="matrix" values="0 0 0 0 .08  0 0 0 0 .05  0 0 0 0 0  -.62 0 0 0 .5"/>
      </filter>
      <pattern id="hatchWaste" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="7" stroke="rgba(0,0,0,.22)" stroke-width="1.6"/></pattern>
      ${N.map((n, k) => `<pattern id="occ${k}" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="4" height="9" fill="${n.color}"/><rect x="4" width="1" height="9" fill="#1a120b" opacity=".35"/></pattern>`).join("")}
      <pattern id="hatchFree" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
        <line x1="0" y1="0" x2="0" y2="6" stroke="rgba(90,66,30,.28)" stroke-width="1"/></pattern>
      <pattern id="t-mountains" width="16" height="13" patternUnits="userSpaceOnUse">
        <path d="M1 11 L6 3 L11 11" fill="none" stroke="rgba(35,25,15,.75)" stroke-width="1.1"/>
        <path d="M4.6 5.3 L6 3 L7.4 5.3" fill="none" stroke="rgba(255,255,255,.85)" stroke-width="1.1"/></pattern>
      <pattern id="t-hills" width="14" height="10" patternUnits="userSpaceOnUse">
        <path d="M1 8 Q5 2 9 8" fill="none" stroke="rgba(55,38,18,.6)" stroke-width="1"/></pattern>
      <pattern id="t-forest" width="11" height="11" patternUnits="userSpaceOnUse">
        <path d="M5 1.5 L8 7.5 L2 7.5 Z" fill="rgba(25,45,15,.55)"/><line x1="5" y1="7.5" x2="5" y2="9.5" stroke="rgba(40,25,10,.5)"/></pattern>
      <pattern id="t-marsh" width="12" height="8" patternUnits="userSpaceOnUse">
        <path d="M1 3 H6 M5 6 H11" stroke="rgba(30,60,55,.6)" stroke-width="1"/></pattern>
      <marker id="arrow-move" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
        <path d="M0 0 L10 5 L0 10 z" fill="#3f8f55"/></marker>
      <marker id="arrow-attack" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
        <path d="M0 0 L10 5 L0 10 z" fill="#b8392b"/></marker>
      <clipPath id="landclip"></clipPath>`;

    const off = {"pointer-events": "none"};
    const gSea = el("g", off, svg);
    el("rect", {width: W, height: H, fill: "url(#seaFill)"}, gSea);
    el("rect", {width: W, height: H, filter: "url(#grain)", opacity: ".8"}, gSea);
    el("path", {d: S.map.coast, class: "shallow"}, gSea);
    el("path", {d: S.map.coast, class: "shallow", "stroke-width": 4, "stroke-opacity": .3}, gSea);
    for (const s of S.map.seas) {
      const size = {1: 40, 2: 26, 3: 17}[s.size];
      el("text", {x: s.x, y: s.y, class: "sea", "font-size": size, "letter-spacing": size * .22,
        transform: `rotate(${s.angle} ${s.x} ${s.y})`}, gSea).textContent = s.name;
    }
    const landclip = defs.querySelector("#landclip");
    el("path", {d: S.map.wasteland}, landclip);
    P.forEach((p) => el("path", {d: p.d}, landclip));

    const gLand = el("g", {}, svg);
    el("path", {d: S.map.wasteland, fill: "var(--waste)"}, gLand);
    el("path", {d: S.map.wasteland, fill: "url(#hatchWaste)"}, gLand);
    const provPaths = P.map((p, i) => { const e = el("path", {d: p.d, class: "prov"}, gLand); e.dataset.i = i; return e; });
    const gFree = el("g", off, svg);
    const freePaths = P.map((p) => el("path", {d: p.d, fill: "url(#hatchFree)"}, gFree));
    const gOcc = el("g", off, svg); // occupied land: the occupier's colours in stripes over the owner's
    const occPaths = P.map((p) => el("path", {d: p.d, class: "occupied"}, gOcc));
    const gTerrain = el("g", off, svg);
    P.forEach((p) => { if (p.terrain !== "plains") el("path", {d: p.d, fill: `url(#t-${p.terrain})`}, gTerrain); });
    const gTexture = el("g", {"clip-path": "url(#landclip)", ...off}, svg);
    el("rect", {width: W, height: H, filter: "url(#relief)"}, gTexture);
    const gRivers = el("g", off, svg);
    for (const [d, rank] of S.map.rivers) el("path", {d, class: "river", "stroke-width": {1: 2.2, 2: 1.4, 3: .9}[rank]}, gRivers);
    const gGlow = el("g", off, svg), gBorders = el("g", off, svg);
    const borders = S.map.borders.map(([a, b, d]) => ({a, b, e: el("path", {d, class: "pborder"}, gBorders),
      g: el("path", {d, class: "bglow"}, gGlow)}));
    el("path", {d: S.map.coast, class: "coast", ...off}, svg);
    const gStraits = el("g", off, svg);
    P.forEach((p, i) => p.sea.forEach((j) => { if (i < j) { const q = P[j];
      el("line", {x1: p.x, y1: p.y, x2: q.x, y2: q.y, class: "strait"}, gStraits); } }));
    const gTargets = el("g", off, svg);
    const pickOutline = el("path", {class: "pick", d: ""}, svg);
    const gNames = el("g", off, svg);
    const gPLabels = el("g", off, svg);
    const plabels = P.map((p, i) => { const t = el("text", {x: p.x, y: p.y, class: "plabel"}, gPLabels);
      t.dataset.i = i; t.textContent = p.name; return t; });
    const gArrows = el("g", off, svg);
    const gMarks = el("g", off, svg), gEvents = el("g", off, svg);
    let arrows = [];

    const view = {x: 0, y: 0, w: W, h: H};
    let world = null, picked = -1, hovered = -1;
    const px = () => view.w / Math.max(1, svg.getBoundingClientRect().width);
    const aspect = () => { const r = svg.getBoundingClientRect(); return r.width / Math.max(1, r.height); };
    const maxW = () => Math.min(W, H * aspect());

    function fillFor(i) {
      const w = world, o = w.owner[i];
      if (w.mode === "terrain") return TERRAIN[P[i].terrain];
      if (w.mode === "development") return devColor(w.dev[i]);
      if (w.mode === "diplomacy") {
        const f = w.focus;
        if (f < 0) return o < 0 ? "var(--free)" : mix(N[o].color, "#8a8478", .55);
        if (o === f) return "#e3bd5c";
        if (o < 0) return "#b9b09a";
        if (w.relations.wars.includes(o)) return "#c4473b";
        if (w.relations.allies.includes(o)) return "#5aa56f";
        if ((w.relations.pacts || []).includes(o)) return "#c9a54a";
        return "#8f897c";
      }
      return o < 0 ? "var(--free)" : N[o].color;
    }

    function nationLabels() {
      gNames.textContent = "";
      const placed = [];
      N.forEach((n, k) => {
        if (!world.alive[k]) return;
        const mine = new Set(P.map((_, i) => i).filter((i) => world.owner[i] === k));
        let best = null, bestArea = 0;
        const seen = new Set();
        for (const s of mine) {
          if (seen.has(s)) continue;
          const comp = [], stack = [s]; seen.add(s);
          while (stack.length) { const c = stack.pop(); comp.push(c);
            for (const j of P[c].land) if (mine.has(j) && !seen.has(j)) { seen.add(j); stack.push(j); } }
          const area = comp.reduce((a, i) => a + P[i].area, 0);
          if (area > bestArea) { best = comp; bestArea = area; }
        }
        if (!best) return;
        let cx = 0, cy = 0;
        best.forEach((i) => { cx += P[i].x * P[i].area; cy += P[i].y * P[i].area; });
        cx /= bestArea; cy /= bestArea;
        let sxx = 0, syy = 0, sxy = 0;
        best.forEach((i) => { const dx = P[i].x - cx, dy = P[i].y - cy, w = P[i].area;
          sxx += w * dx * dx; syy += w * dy * dy; sxy += w * dx * dy; });
        let angle = best.length > 1 ? 0.5 * Math.atan2(2 * sxy, sxx - syy) * 180 / Math.PI : 0;
        angle = Math.max(-30, Math.min(30, angle));
        const rad = angle * Math.PI / 180, ux = Math.cos(rad), uy = Math.sin(rad);
        const along = best.map((i) => (P[i].x - cx) * ux + (P[i].y - cy) * uy);
        const span = Math.max(...along) - Math.min(...along) + Math.sqrt(bestArea / best.length) * 0.9;
        const name = n.name.toUpperCase();
        const size = Math.max(12, Math.min(84, span / (name.length * 1.05), Math.sqrt(bestArea) * 0.42));
        placed.push({name, cx, cy, angle, size, area: bestArea});
      });
      const box = (l) => { const w = l.name.length * l.size * 1.05, h = l.size, r = Math.abs(l.angle) * Math.PI / 180;
        const bw = w * Math.cos(r) + h * Math.sin(r), bh = w * Math.sin(r) + h * Math.cos(r);
        return [l.cx - bw / 2, l.cy - bh / 2, l.cx + bw / 2, l.cy + bh / 2]; };
      const hit = (a, b) => { const p = box(a), q = box(b); return p[0] < q[2] && q[0] < p[2] && p[1] < q[3] && q[1] < p[3]; };
      placed.sort((a, b) => b.area - a.area);
      for (let pass = 0; pass < 6; pass++)
        for (let i = 0; i < placed.length; i++) for (let j = i + 1; j < placed.length; j++) {
          const small = placed[j];
          if (hit(placed[i], small) && small.size > 12) small.size = Math.max(12, small.size * 0.8);
          else if (hit(placed[i], small) && small.angle !== 0) small.angle = 0;
        }
      for (const l of placed) el("text", {x: l.cx, y: l.cy, class: "nlabel", transform: `rotate(${l.angle.toFixed(1)} ${l.cx} ${l.cy})`,
        "font-size": l.size.toFixed(1), "letter-spacing": (l.size * 0.28).toFixed(1)}, gNames).textContent = l.name;
    }

    function markers() {
      gMarks.textContent = "";
      if (!world) return;
      const k = px(), close = view.w < maxW() * 0.6;
      P.forEach((p, i) => {
        const o = (world.controller || [])[i] >= 0 ? world.controller[i] : world.owner[i];
        if (world.capitals.has(i) && world.owner[i] >= 0) el("path", {class: "capital", transform: `translate(${p.x} ${p.y - 14 * k}) scale(${1.1 * k})`,
          d: "M0-6 1.8-1.9 6.2-1.9 2.7 0.9 4 5.3 0-2.4-4 5.3-2.7 0.9-6.2-1.9-1.8-1.9Z"}, gMarks);
        const troops = world.troops[i], hidden = troops === null;
        if ((troops > 0 || (hidden && close)) && (o >= 0 || close)) {
          const label = hidden ? "?" : String(troops), w = 9 + label.length * 6;
          const g = el("g", {class: "badge" + (hidden ? " fog" : ""), transform: `translate(${p.x} ${p.y + 2 * k}) scale(${1.15 * k})`}, gMarks);
          el("rect", {class: "box", x: -w / 2, y: -7, width: w, height: 14, rx: 2,
            stroke: o >= 0 ? N[o].color : "#8a7d60", opacity: o >= 0 && !hidden ? 1 : .75}, g);
          el("text", {}, g).textContent = label;
        }
        const general = world.generals && world.generals.get(i);
        if (general) { // a pennant in the general's colours, his skill on the flag
          const g = el("g", {class: "general", transform: `translate(${p.x - 20 * k} ${p.y + 2 * k}) scale(${1.15 * k})`}, gMarks);
          el("title", {}, g).textContent = `${general.name}, skill ${general.skill}`;
          el("line", {x1: 0, y1: 8, x2: 0, y2: -10, class: "pole"}, g);
          el("path", {d: "M0.5 -10 L11 -6.5 L0.5 -3 Z", fill: N[general.nation].color, class: "pennant"}, g);
          el("text", {x: 4.6, y: -6.3, class: "skill"}, g).textContent = general.skill;
        }
        const bs = world.buildings[i];
        if (close && bs.length) {
          const g = el("g", {transform: `translate(${p.x} ${p.y + 15 * k}) scale(${1.15 * k})`}, gMarks);
          bs.forEach((b, j) => el("rect", {class: "bpip", x: (j - bs.length / 2) * 7 + .5, y: 0, width: 6, height: 6,
            fill: B[b].category === "civil" ? "#5d93b8" : "#c0563f"}, g));
        }
      });
    }

    function eventMarks() {
      gEvents.textContent = "";
      if (!world) return;
      const k = px();
      for (const [kind, prov, nats] of world.events || []) {
        if (prov < 0) continue;
        const p = P[prov];
        if (kind === "battle") el("text", {x: p.x + 16 * k, y: p.y - 12 * k, class: "battle", "font-size": 16 * k}, gEvents).textContent = "⚔";
        if (kind === "province_captured" && nats.length) el("circle", {cx: p.x, cy: p.y, r: 8, class: "pulse", stroke: N[nats[0]].color}, gEvents);
      }
    }

    function paint(next) {
      world = next;
      provPaths.forEach((e, i) => { e.style.fill = fillFor(i); });
      freePaths.forEach((e, i) => { e.style.display = world.owner[i] < 0 && world.mode === "political" ? "" : "none"; });
      occPaths.forEach((e, i) => { const c = (world.controller || [])[i];
        const show = c >= 0 && (world.mode === "political" || world.mode === "diplomacy");
        e.style.display = show ? "" : "none"; if (show) e.setAttribute("fill", `url(#occ${c})`); });
      gTerrain.style.opacity = world.mode === "terrain" ? .7 : world.mode === "political" ? .3 : .12;
      const f = world.focus;
      borders.forEach(({a, b, e, g}) => {
        const oa = a < 0 ? -2 : world.owner[a], ob = b < 0 ? -2 : world.owner[b], nation = oa !== ob;
        e.setAttribute("class", "pborder" + (nation ? " nation" : "") + (nation && f >= 0 && (oa === f || ob === f) ? " mine" : ""));
        g.style.display = nation && world.mode !== "terrain" ? "" : "none";
      });
      gNames.style.display = world.mode === "terrain" || world.mode === "development" ? "none" : "";
      nationLabels(); markers(); eventMarks();
      pick(picked);
    }

    function pick(i) {
      if (picked >= 0) provPaths[picked].classList.remove("picked");
      picked = i;
      if (i >= 0) provPaths[i].classList.add("picked");
      pickOutline.setAttribute("d", i >= 0 ? P[i].d : "");
    }

    function setArrows(list) { arrows = list; drawArrows(); } // [[from, to, kind, count]]
    function drawArrows() {
      gArrows.textContent = "";
      const k = px();
      for (const [a, b, kind, count] of arrows) {
        const p = P[a], q = P[b], mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
        const dx = q.x - p.x, dy = q.y - p.y, len = Math.hypot(dx, dy) || 1;
        const cx = mx - dy / len * len * 0.18, cy = my + dx / len * len * 0.18; // a gentle bow
        el("path", {d: `M${p.x} ${p.y} Q${cx} ${cy} ${q.x} ${q.y}`, class: `arrow ${kind}`,
          "stroke-width": 4.5 * k, "marker-end": `url(#arrow-${kind})`}, gArrows);
        const t = el("text", {x: (p.x + 2 * cx + q.x) / 4, y: (p.y + 2 * cy + q.y) / 4, class: `arrowcount ${kind}`,
          "font-size": 12 * k, "stroke-width": 3 * k}, gArrows);
        t.textContent = count;
      }
    }

    function setTargets(list) { // [[province, "move" | "attack"]]
      gTargets.textContent = "";
      for (const [i, kind] of list) el("path", {d: P[i].d, class: `target ${kind}`}, gTargets);
    }

    function applyView() {
      view.w = Math.min(maxW(), Math.max(W / 12, view.w)); view.h = view.w / aspect();
      view.x = Math.min(W - view.w, Math.max(0, view.x)); view.y = Math.min(H - view.h, Math.max(0, view.y));
      svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
      gPLabels.style.display = view.w < maxW() * 0.6 ? "" : "none";
      gNames.style.opacity = view.w < maxW() * 0.45 ? .4 : 1;
      const k = px();
      plabels.forEach((t) => { t.setAttribute("font-size", (12 * k).toFixed(2)); t.setAttribute("y", P[+t.dataset.i].y - 22 * k); });
    }
    const refresh = () => { markers(); eventMarks(); drawArrows(); };
    function toMap(cx, cy) { const r = svg.getBoundingClientRect(), s = view.w / r.width;
      return [view.x + (cx - r.left) * s, view.y + (cy - r.top) * s]; }
    function zoomAt(factor, cx, cy) {
      const [mx, my] = cx === undefined ? [view.x + view.w / 2, view.y + view.h / 2] : toMap(cx, cy);
      const nw = Math.min(maxW(), Math.max(W / 12, view.w * factor)), k = nw / view.w;
      view.x = mx - (mx - view.x) * k; view.y = my - (my - view.y) * k; view.w = nw; applyView(); refresh();
    }
    function home(on) { // the whole width of Europe, or zoomed onto some provinces
      const set = on && on.length ? on : P.map((_, i) => i);
      const xs = set.map((i) => P[i].x), ys = set.map((i) => P[i].y);
      const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
      view.w = on && on.length ? Math.max(W / 3.2, (Math.max(...xs) - Math.min(...xs)) * 3.2) : maxW();
      view.h = view.w / aspect(); view.x = cx - view.w / 2; view.y = cy - view.h / 2; applyView(); refresh();
    }
    function centerOn(i, zoom, shiftPx = 0) {
      view.w = maxW() / zoom; view.h = view.w / aspect();
      view.x = P[i].x - view.w / 2 - shiftPx * (view.w / svg.getBoundingClientRect().width); view.y = P[i].y - view.h / 2;
      applyView(); refresh();
    }

    // interaction: hover, click, drag, wheel
    const wrap = svg.parentElement;
    let drag = null, moved = false;
    gLand.addEventListener("pointermove", (e) => { const i = +e.target.dataset.i;
      if (Number.isNaN(i) || drag) return;
      if (i !== hovered) { if (hovered >= 0) provPaths[hovered].classList.remove("hover"); hovered = i; provPaths[i].classList.add("hover"); }
      if (hooks.hover) hooks.hover(i, e); });
    gLand.addEventListener("pointerleave", () => { if (hovered >= 0) provPaths[hovered].classList.remove("hover");
      hovered = -1; if (hooks.leave) hooks.leave(); });
    gLand.addEventListener("click", (e) => { if (moved) return; const i = +e.target.dataset.i;
      if (hooks.click) hooks.click(Number.isNaN(i) ? -1 : i, e); });
    gLand.addEventListener("contextmenu", (e) => { const i = +e.target.dataset.i;
      if (!hooks.command || Number.isNaN(i)) return;
      e.preventDefault(); hooks.command(i, e); });
    wrap.addEventListener("wheel", (e) => {
      if (!svg.contains(e.target)) return; // over the deed or the legend, the wheel scrolls them
      e.preventDefault(); zoomAt(e.deltaY > 0 ? 1.18 : 1 / 1.18, e.clientX, e.clientY); }, {passive: false});
    svg.addEventListener("pointerdown", (e) => { if (e.button !== 0) return;
      drag = {x: e.clientX, y: e.clientY, vx: view.x, vy: view.y}; moved = false; });
    window.addEventListener("pointermove", (e) => { if (!drag) return;
      const s = view.w / svg.getBoundingClientRect().width, dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) { moved = true; wrap.classList.add("dragging"); if (hooks.leave) hooks.leave(); }
      view.x = drag.vx - dx * s; view.y = drag.vy - dy * s; applyView(); });
    window.addEventListener("pointerup", () => { drag = null; wrap.classList.remove("dragging"); });
    window.addEventListener("resize", () => { applyView(); refresh(); });

    return {paint, pick, setTargets, setArrows, zoomAt, home, centerOn, refresh, view, maxW, px, get picked() { return picked; }};
  }

  // ------------------------------------------------------------------ the province vista
  // A small painted view of the province: its land, its town and every building in it, so that
  // developing and building visibly changes the place. Deterministic for each province.
  const SKY = {plains: ["#bcd3dc", "#f1e6c9"], forest: ["#b6cdd0", "#e9e2c6"], hills: ["#c3d4d8", "#f0e2c2"],
               marsh: ["#b4c6c6", "#e3dec6"], mountains: ["#aec4d2", "#eee6d2"]};
  const GROUND = {plains: ["#b9bd74", "#8f9a52"], forest: ["#7f9a55", "#566f37"], hills: ["#b49a64", "#8a7346"],
                  marsh: ["#8aa087", "#5f7a66"], mountains: ["#a49c8a", "#77705f"]};
  const INK = "#3a2a18";
  function seeded(text) {
    let h = 2166136261;
    for (const c of text) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); }
    return () => { h ^= h << 13; h ^= h >>> 17; h ^= h << 5; return ((h >>> 0) % 10000) / 10000; };
  }
  // Which kind of landmark each monument is, for the province's picture.
  const MONUMENT_STYLE = {constantinople: "mosque", florence: "dome", rome: "dome", paris: "gothic", london: "gothic",
    rhineland: "gothic", galicia: "gothic", vienna: "spire", moscow: "kremlin", krakow: "castle", stockholm: "castle",
    prussia: "castle", zealand: "castle", andalusia: "palace", madrid: "palace", venice: "arsenal"};
  function landmark(style, level, ground, flag) {
    const x = 140, g = ground, stone = "#e3d6b4", dark = "#c4b48e", gold = level >= 3 ? "#e6c27e" : "#b9ad92";
    if (!level) { // a bare site: scaffolding and a crane
      return `<g opacity=".9"><path d="M${x - 22} ${g} v-26 M${x - 6} ${g} v-34 M${x + 10} ${g} v-26 M${x - 24} ${g - 12} h36 M${x - 24} ${g - 24} h36" stroke="#8a6a40" stroke-width="1.2"/>
        <path d="M${x + 22} ${g} v-46 l-26 4" stroke="#6a4a2a" stroke-width="1.4" fill="none"/><path d="M${x - 2} ${g - 42} v8" stroke="#6a4a2a"/><rect x="${x - 5}" y="${g - 34}" width="6" height="5" fill="${dark}"/></g>`;
    }
    const tall = 1 + level * 0.12;
    switch (style) {
      case "mosque": return `<path d="M${x - 26} ${g} v-22 h52 v22 z" fill="${stone}" stroke="${INK}" stroke-width=".7"/><path d="M${x - 20} ${g - 22} a20 ${18 * tall} 0 0 1 40 0 z" fill="#b7a98a" stroke="${INK}" stroke-width=".7"/>
        ${[-34, 34].map((dx) => `<rect x="${x + dx - 2}" y="${g - 40 * tall}" width="4" height="${40 * tall}" fill="${stone}" stroke="${INK}" stroke-width=".5"/><path d="M${x + dx - 3} ${g - 40 * tall} l3 -8 l3 8 z" fill="${gold}"/>`).join("")}
        <path d="M${x} ${g - 22 - 18 * tall} v-6" stroke="${gold}" stroke-width="1.4"/>`;
      case "dome": return `<rect x="${x - 22}" y="${g - 24}" width="44" height="24" fill="${stone}" stroke="${INK}" stroke-width=".7"/><rect x="${x - 12}" y="${g - 32}" width="24" height="8" fill="${dark}" stroke="${INK}" stroke-width=".6"/>
        <path d="M${x - 12} ${g - 32} a12 ${16 * tall} 0 0 1 24 0 z" fill="#b8644a" stroke="${INK}" stroke-width=".7"/><rect x="${x - 2}" y="${g - 32 - 16 * tall - 7}" width="4" height="7" fill="${gold}" stroke="${INK}" stroke-width=".4"/>`;
      case "gothic": return `<rect x="${x - 16}" y="${g - 30}" width="32" height="30" fill="${stone}" stroke="${INK}" stroke-width=".7"/><circle cx="${x}" cy="${g - 20}" r="5" fill="#7d8f9a" stroke="${INK}" stroke-width=".5"/>
        ${[-16, 16].map((dx) => `<rect x="${x + dx - 6}" y="${g - 40 * tall}" width="12" height="${40 * tall}" fill="${dark}" stroke="${INK}" stroke-width=".7"/>${level >= 2 ? `<path d="M${x + dx - 6} ${g - 40 * tall} l6 -${6 * level} l6 ${6 * level} z" fill="${gold}" stroke="${INK}" stroke-width=".5"/>` : ""}`).join("")}`;
      case "spire": return `<rect x="${x - 18}" y="${g - 26}" width="30" height="26" fill="${stone}" stroke="${INK}" stroke-width=".7"/><path d="M${x - 20} ${g - 26} l15 -10 l15 10 z" fill="#5a7a6a" stroke="${INK}" stroke-width=".6"/>
        <rect x="${x + 10}" y="${g - 38 * tall}" width="10" height="${38 * tall}" fill="${dark}" stroke="${INK}" stroke-width=".7"/><path d="M${x + 10} ${g - 38 * tall} l5 -${16 * tall} l5 ${16 * tall} z" fill="${gold}" stroke="${INK}" stroke-width=".5"/>`;
      case "kremlin": return `<rect x="${x - 30}" y="${g - 16}" width="60" height="16" fill="#b8473a" stroke="${INK}" stroke-width=".7"/>${[-30, -10, 10, 30].map((dx) => `<path d="M${x + dx - 2} ${g - 16} v-3 h4 v3" fill="#b8473a" stroke="${INK}" stroke-width=".4"/>`).join("")}
        <rect x="${x - 5}" y="${g - 40 * tall}" width="10" height="${24 * tall}" fill="#b8473a" stroke="${INK}" stroke-width=".7"/><path d="M${x - 5} ${g - 40 * tall} l5 -12 l5 12 z" fill="#3a6a4a" stroke="${INK}" stroke-width=".5"/>
        ${[-18, 18].map((dx) => `<rect x="${x + dx - 5}" y="${g - 28}" width="10" height="12" fill="${stone}" stroke="${INK}" stroke-width=".5"/><path d="M${x + dx - 6} ${g - 28} q6 -14 12 0 z" fill="${gold}" stroke="${INK}" stroke-width=".5"/>`).join("")}`;
      case "castle": return `<rect x="${x - 26}" y="${g - 22}" width="52" height="22" fill="${dark}" stroke="${INK}" stroke-width=".7"/>${[-26, 18].map((dx) => `<rect x="${x + dx}" y="${g - 34 * tall}" width="8" height="${34 * tall}" fill="${stone}" stroke="${INK}" stroke-width=".6"/><path d="M${x + dx - 1} ${g - 34 * tall} l5 -9 l5 9 z" fill="#8a3f2a" stroke="${INK}" stroke-width=".5"/>`).join("")}
        <rect x="${x - 6}" y="${g - 38 * tall}" width="12" height="${16 * tall}" fill="${stone}" stroke="${INK}" stroke-width=".6"/><line x1="${x}" y1="${g - 38 * tall}" x2="${x}" y2="${g - 48 * tall}" stroke="${INK}"/><path d="M${x} ${g - 48 * tall} l9 3 l-9 3 z" fill="${flag}"/>`;
      case "palace": return `<rect x="${x - 34}" y="${g - 20}" width="68" height="20" fill="#d8b48a" stroke="${INK}" stroke-width=".7"/>${[-34, -2, 28].map((dx) => `<rect x="${x + dx}" y="${g - 30 * tall}" width="8" height="${30 * tall}" fill="#c99a6a" stroke="${INK}" stroke-width=".6"/>`).join("")}
        ${[-24, -14, 10, 20].map((dx) => `<path d="M${x + dx} ${g - 4} v-8 a3 3 0 0 1 6 0 v8" fill="#6a4a2a"/>`).join("")}`;
      default: return `<rect x="${x - 30}" y="${g - 18}" width="60" height="18" fill="${dark}" stroke="${INK}" stroke-width=".7"/><path d="M${x - 32} ${g - 18} l16 -10 l16 10 l16 -10 l16 10" fill="${stone}" stroke="${INK}" stroke-width=".6"/>
        <rect x="${x - 8}" y="${g - 10}" width="16" height="10" fill="#4a6a8a"/><path d="M${x - 4} ${g - 14} q4 -10 8 0" fill="none" stroke="#6a4a2a" stroke-width="1.4"/>`;
    }
  }
  function vista(S, i, d) {
    const p = S.provinces[i], B = S.buildings, rnd = seeded(p.id), has = (id) => d.built.some((b) => B[b].id === id);
    const W = 380, H = 150, ground = 104, [sky1, sky2] = SKY[p.terrain], [g1, g2] = GROUND[p.terrain];
    const flag = d.owner >= 0 ? S.nations[d.owner].color : "#9a8f78";
    const out = [];
    const add = (s) => out.push(s);
    add(`<defs><linearGradient id="vs${i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${sky1}"/><stop offset="1" stop-color="${sky2}"/></linearGradient>
      <linearGradient id="vg${i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${g1}"/><stop offset="1" stop-color="${g2}"/></linearGradient></defs>`);
    add(`<rect width="${W}" height="${H}" fill="url(#vs${i})"/>`);
    if (d.unrest) add(`<rect width="${W}" height="${H}" fill="#5a3a2a" opacity=".18"/>`);
    add(`<circle cx="${300 + rnd() * 50}" cy="${26 + rnd() * 10}" r="11" fill="#fbf1cf" opacity=".85"/>`);
    // far ridges
    const ridge = (y, amp, color, peaks) => {
      let path = `M0 ${y}`;
      for (let x = 0; x <= W; x += W / peaks) path += ` L${x.toFixed(0)} ${(y - amp * (0.4 + rnd() * 0.6)).toFixed(0)}`;
      add(`<path d="${path} L${W} ${ground} L0 ${ground} Z" fill="${color}" stroke="${INK}" stroke-opacity=".25" stroke-width=".6"/>`);
    };
    if (p.terrain === "mountains") {
      for (let k = 0; k < 4; k++) {
        const x = 30 + k * 95 + rnd() * 30, h = 55 + rnd() * 25;
        add(`<path d="M${x - 55} ${ground} L${x} ${ground - h} L${x + 55} ${ground} Z" fill="#8e8a80" stroke="${INK}" stroke-opacity=".35" stroke-width=".7"/>`);
        add(`<path d="M${x - 14} ${ground - h + 18} L${x} ${ground - h} L${x + 14} ${ground - h + 18} L${x + 5} ${ground - h + 13} L${x - 4} ${ground - h + 19} Z" fill="#fbfbf6"/>`);
      }
    } else if (p.terrain === "hills") { ridge(88, 28, "#a99a74", 6); ridge(96, 16, "#9b8a60", 8); }
    else ridge(96, 10, mix(g1, sky2, .45), 7);
    add(`<rect y="${ground}" width="${W}" height="${H - ground}" fill="url(#vg${i})"/>`);
    // the land's character
    const tree = (x, y, s = 1) => add(`<path d="M${x} ${y - 16 * s} L${x + 6 * s} ${y} L${x - 6 * s} ${y} Z" fill="#3f5f2c" stroke="${INK}" stroke-opacity=".35" stroke-width=".5"/><rect x="${x - .8}" y="${y}" width="1.6" height="${3 * s}" fill="#4a3220"/>`);
    if (p.terrain === "forest") { for (let k = 0; k < 26; k++) { const x = rnd() * W; if (x > 110 && x < 270) continue; tree(x, ground + 4 + rnd() * 30, 0.8 + rnd() * .6); } }
    if (p.terrain === "marsh") for (let k = 0; k < 7; k++) add(`<ellipse cx="${rnd() * W}" cy="${ground + 12 + rnd() * 28}" rx="${14 + rnd() * 18}" ry="3.5" fill="#7fa0a8" opacity=".75"/>`);
    if (p.good === "grain" || has("farm_estates")) for (let k = 0; k < (has("farm_estates") ? 9 : 5); k++) {
      const x = (k % 2 ? 268 : 8) + rnd() * 90, y = ground + 8 + rnd() * 30;
      add(`<rect x="${x}" y="${y}" width="${22 + rnd() * 16}" height="7" fill="${k % 3 ? "#d9c26a" : "#c5a94c"}" stroke="${INK}" stroke-opacity=".2" stroke-width=".5"/>`);
    }
    if (p.good === "iron") add(`<path d="M320 ${ground} q 22 -30 44 0 z" fill="#8b7a5c" stroke="${INK}" stroke-width=".7"/><path d="M335 ${ground} v-9 a7 7 0 0 1 14 0 v9 z" fill="#2a1f14"/><rect x="352" y="${ground + 3}" width="12" height="6" fill="#6b5236" stroke="${INK}" stroke-width=".5"/>`);
    if (p.good === "timber" || has("lumber_mill")) for (let k = 0; k < 3; k++) add(`<rect x="${20 + k * 3}" y="${ground + 18 - k * 4}" width="34" height="4" rx="2" fill="#8a6239" stroke="${INK}" stroke-width=".5"/>`);
    if (p.good === "gold") add(`<path d="M0 ${ground + 26} C 90 ${ground + 18}, 250 ${ground + 40}, ${W} ${ground + 30}" stroke="#7fa6bd" stroke-width="7" fill="none" opacity=".8"/><path d="M60 ${ground + 20} l14 0 l-3 4 l-8 0 z M67 ${ground + 20} v-9 l6 6 z" fill="#6b4a2a"/>`);
    // a road to the gate, and grass in the foreground
    add(`<path d="M172 ${H} C 180 ${ground + 30}, 186 ${ground + 14}, 188 ${ground + 4} L192 ${ground + 4} C 196 ${ground + 14}, 204 ${ground + 30}, 214 ${H} Z" fill="#cdbb8c" opacity=".85"/>`);
    for (let k = 0; k < 40; k++) { const x = rnd() * W, y = ground + 18 + rnd() * (H - ground - 20);
      add(`<path d="M${x} ${y} l-2 -5 M${x} ${y} l0 -6 M${x} ${y} l2 -5" stroke="${mix(g2, "#000000", .25)}" stroke-width=".7" opacity=".6"/>`); }
    const outside = out.splice(0); // what follows is the town, drawn larger around its gate
    const outer = [], addOut = (x) => outer.push(x); // works outside the walls keep their size
    const bannerOut = (x, y) => addOut(`<line x1="${x}" y1="${y}" x2="${x}" y2="${y - 16}" stroke="${INK}" stroke-width="1"/><path d="M${x} ${y - 16} l11 3 l-11 3 z" fill="${flag}" stroke="${INK}" stroke-width=".5"/>`);
    // the town: grows with development
    const houses = Math.min(26, 2 + Math.round(d.dev * 1.8)), left = 190 - Math.min(64, 16 + d.dev * 4.5), right = 190 + Math.min(64, 16 + d.dev * 4.5);
    const roof = ["#9c4a32", "#8a3f2a", "#7a5232", "#a65a3a"];
    const spots = [];
    for (let k = 0; k < houses; k++) spots.push([left + rnd() * (right - left), ground + 4 - rnd() * 10, 7 + rnd() * 5, 6 + rnd() * 6]);
    spots.sort((a, b) => a[1] - b[1]);
    const house = ([x, y, w, h]) => add(`<rect x="${x - w / 2}" y="${y - h}" width="${w}" height="${h}" fill="#e7d9b8" stroke="${INK}" stroke-width=".6"/><path d="M${x - w / 2 - 1.5} ${y - h} L${x} ${y - h - w * .55} L${x + w / 2 + 1.5} ${y - h} Z" fill="${roof[Math.floor(rnd() * 4)]}" stroke="${INK}" stroke-width=".6"/><rect x="${x - 1}" y="${y - 3.5}" width="2" height="3.5" fill="#5a4026"/>`);
    const back = spots.filter((_, k) => k % 2), front = spots.filter((_, k) => !(k % 2));
    if (d.monument !== null && d.monument !== undefined && MONUMENT_STYLE[p.id]) add(landmark(MONUMENT_STYLE[p.id], d.monument, ground, flag));
    back.forEach(house);
    const tower = (x, w, h, top, color = "#ddd0ae") => add(`<rect x="${x - w / 2}" y="${ground - h}" width="${w}" height="${h}" fill="${color}" stroke="${INK}" stroke-width=".7"/>${top}`);
    const banner = (x, y) => add(`<line x1="${x}" y1="${y}" x2="${x}" y2="${y - 16}" stroke="${INK}" stroke-width="1"/><path d="M${x} ${y - 16} l11 3 l-11 3 z" fill="${flag}" stroke="${INK}" stroke-width=".5"/>`);
    let highest = [190, ground - 20];
    if (d.dev >= 3 || has("cathedral")) { // the church, or the cathedral
      const big = has("cathedral"), x = 172, h = big ? 52 : 26 + d.dev;
      tower(x, big ? 14 : 9, h, `<path d="M${x - (big ? 9 : 6)} ${ground - h} L${x} ${ground - h - (big ? 30 : 16)} L${x + (big ? 9 : 6)} ${ground - h} Z" fill="#6a6e72" stroke="${INK}" stroke-width=".7"/>`);
      if (big) add(`<rect x="${x + 7}" y="${ground - 30}" width="26" height="30" fill="#ddd0ae" stroke="${INK}" stroke-width=".7"/><circle cx="${x + 20}" cy="${ground - 19}" r="5" fill="#8fb3c9" stroke="${INK}" stroke-width=".6"/>`);
      highest = [x, ground - h - (big ? 30 : 16)];
    }
    if (d.dev >= 6) tower(214, 10, 30 + d.dev, `<path d="M207 ${ground - 30 - d.dev} h14 v-4 h-3 v3 h-2.5 v-3 h-3 v3 h-2.5 v-3 h-3 z" fill="#ddd0ae" stroke="${INK}" stroke-width=".6"/>`);
    if (d.isCapital) { tower(196, 22, 40, `<path d="M184 ${ground - 40} L196 ${ground - 52} L208 ${ground - 40} Z" fill="#5b6b8a" stroke="${INK}" stroke-width=".7"/>`, "#e9dcbc"); banner(196, ground - 52); }
    if (has("university")) tower(240, 12, 34, `<path d="M233 ${ground - 34} a7 7 0 0 1 14 0 z" fill="#7d8f9a" stroke="${INK}" stroke-width=".7"/>`);
    if (has("royal_exchange")) add(`<rect x="208" y="${ground - 24}" width="30" height="24" fill="#f1e8d0" stroke="${INK}" stroke-width=".7"/><path d="M205 ${ground - 24} L223 ${ground - 34} L241 ${ground - 24} Z" fill="#d8c79a" stroke="${INK}" stroke-width=".7"/>${[211, 217, 223, 229, 235].map((x) => `<rect x="${x}" y="${ground - 22}" width="2" height="20" fill="#cbbf9d"/>`).join("")}<circle cx="223" cy="${ground - 28}" r="2" fill="#c49a52"/>`);
    if (has("military_academy")) { add(`<rect x="100" y="${ground - 30}" width="24" height="30" fill="#c9b892" stroke="${INK}" stroke-width=".7"/><path d="M100 ${ground - 30} v-4 h4 v4 h4 v-4 h4 v4 h4 v-4 h4 v4 h4 v-4 h0" fill="none" stroke="${INK}" stroke-width=".7"/>`); banner(112, ground - 34); }
    if (has("bank")) add(`<rect x="128" y="${ground - 20}" width="26" height="20" fill="#efe6cf" stroke="${INK}" stroke-width=".7"/><path d="M126 ${ground - 20} L141 ${ground - 28} L156 ${ground - 20} Z" fill="#cbbf9d" stroke="${INK}" stroke-width=".7"/>${[131, 137, 143, 149].map((x) => `<rect x="${x}" y="${ground - 18}" width="2" height="16" fill="#cbbf9d"/>`).join("")}`);
    if (has("ironworks")) { addOut(`<rect x="292" y="${ground - 18}" width="22" height="18" fill="#8d7a62" stroke="${INK}" stroke-width=".7"/><rect x="306" y="${ground - 34}" width="5" height="16" fill="#6b5a48" stroke="${INK}" stroke-width=".6"/>`);
      for (let k = 0; k < 3; k++) addOut(`<circle cx="${309 + k * 4}" cy="${ground - 40 - k * 7}" r="${3 + k * 1.6}" fill="#8a8580" opacity="${.6 - k * .15}"/>`); }
    if (has("lumber_mill")) addOut(`<rect x="60" y="${ground - 16}" width="22" height="16" fill="#a2774a" stroke="${INK}" stroke-width=".7"/><path d="M58 ${ground - 16} L71 ${ground - 24} L84 ${ground - 16} Z" fill="#7a5232" stroke="${INK}" stroke-width=".6"/><circle cx="88" cy="${ground - 6}" r="7" fill="none" stroke="${INK}" stroke-width="1.2"/><path d="M81 ${ground - 6} h14 M88 ${ground - 13} v14" stroke="${INK}" stroke-width=".8"/>`);
    if (has("farm_estates")) { const x = 300, y = ground + 4; addOut(`<path d="M${x - 5} ${y} L${x - 3} ${y - 24} L${x + 3} ${y - 24} L${x + 5} ${y} Z" fill="#e6d8b4" stroke="${INK}" stroke-width=".7"/>`);
      for (const a of [20, 110, 200, 290]) addOut(`<rect x="${x - 1}" y="${y - 40}" width="2" height="17" fill="#8a6a40" transform="rotate(${a} ${x} ${y - 24})"/>`); }
    if (has("barracks")) for (let k = 0; k < 3; k++) { const x = 300 + k * 18, y = ground + 20; addOut(`<path d="M${x - 8} ${y} L${x} ${y - 13} L${x + 8} ${y} Z" fill="#efe7d2" stroke="${INK}" stroke-width=".7"/>`); if (!k) bannerOut(x, y - 13); }
    if (has("armory")) add(`<rect x="94" y="${ground - 20}" width="22" height="20" fill="#9a8a72" stroke="${INK}" stroke-width=".7"/><path d="M99 ${ground - 15} l12 10 M111 ${ground - 15} l-12 10" stroke="#e8e0cc" stroke-width="1.6"/>`);
    if (has("stables")) { addOut(`<rect x="8" y="${ground - 14}" width="30" height="14" fill="#b08458" stroke="${INK}" stroke-width=".7"/><path d="M5 ${ground - 14} L23 ${ground - 24} L41 ${ground - 14} Z" fill="#7a5232" stroke="${INK}" stroke-width=".6"/>`);
      addOut(`<path d="M44 ${ground + 8} h26 M44 ${ground + 3} h26 M46 ${ground + 10} v-10 M58 ${ground + 10} v-10 M68 ${ground + 10} v-10" stroke="#6a4a2a" stroke-width="1.2"/>`);
      addOut(`<path d="M50 ${ground + 1} q2 -7 9 -7 l3 -4 l2 3 q2 2 0 4 l-2 0 l0 4 l-1 6 h-2 l0 -5 h-6 l-1 5 h-2 z" fill="#4a3220"/>`); }
    if (has("cannon_foundry")) { addOut(`<rect x="334" y="${ground - 20}" width="26" height="20" fill="#7a6a5a" stroke="${INK}" stroke-width=".7"/><path d="M340 ${ground - 20} l4 -16 h6 l4 16 z" fill="#5a4a3a" stroke="${INK}" stroke-width=".6"/><rect x="338" y="${ground - 8}" width="8" height="8" fill="#e8742a"/>`);
      for (let k = 0; k < 3; k++) addOut(`<circle cx="${347 + k * 3}" cy="${ground - 42 - k * 8}" r="${3.5 + k * 2}" fill="#5a524a" opacity="${.65 - k * .17}"/>`);
      addOut(`<path d="M318 ${ground + 14} h14" stroke="#2a2420" stroke-width="3.2" stroke-linecap="round"/><circle cx="320" cy="${ground + 17}" r="3" fill="none" stroke="#5a3a1a" stroke-width="1.4"/>`); }
    if (has("workshop")) addOut(`<rect x="250" y="${ground + 6}" width="26" height="14" fill="#c9a77a" stroke="${INK}" stroke-width=".7"/><path d="M248 ${ground + 6} l15 -7 l15 7 z" fill="#8a5a3a" stroke="${INK}" stroke-width=".6"/><circle cx="263" cy="${ground + 14}" r="4" fill="none" stroke="${INK}" stroke-width="1"/>`);
        if (has("observatory")) addOut(`<rect x="358" y="${ground - 40}" width="12" height="40" fill="#ddd0ae" stroke="${INK}" stroke-width=".7"/><path d="M356 ${ground - 40} a8 8 0 0 1 16 0 z" fill="#8a9aa8" stroke="${INK}" stroke-width=".7"/><path d="M364 ${ground - 46} l10 -8" stroke="${INK}" stroke-width="2"/>`);
    if (has("training_grounds")) { addOut(`<rect x="22" y="${ground + 26}" width="70" height="16" fill="none" stroke="#7a5a34" stroke-width="1.2" stroke-dasharray="3 2"/>`);
      for (let k = 0; k < 3; k++) addOut(`<circle cx="${34 + k * 22}" cy="${ground + 34}" r="4" fill="#e8dcb8" stroke="#9c2a1e" stroke-width="1.4"/>`); }
    front.forEach(house);
    if (has("marketplace")) for (let k = 0; k < 4; k++) { const x = 150 + k * 22, y = ground + 14;
      add(`<rect x="${x}" y="${y - 6}" width="16" height="6" fill="#d8c8a0" stroke="${INK}" stroke-width=".5"/><path d="M${x - 2} ${y - 6} L${x + 18} ${y - 6} L${x + 16} ${y - 11} L${x} ${y - 11} Z" fill="${k % 2 ? "#a83a2c" : "#e7dcc0"}" stroke="${INK}" stroke-width=".5"/>`); }
    if (d.fort >= 1) { // walls before the town, towers at the ends
      add(`<rect x="${left - 10}" y="${ground + 2}" width="${right - left + 20}" height="10" fill="#b9ad92" stroke="${INK}" stroke-width=".8"/>`);
      for (let x = left - 10; x < right + 8; x += 7) add(`<rect x="${x}" y="${ground - 1}" width="4" height="3" fill="#b9ad92" stroke="${INK}" stroke-width=".5"/>`);
      for (const x of [left - 12, right + 6]) add(`<rect x="${x}" y="${ground - 10}" width="9" height="22" fill="#a79b80" stroke="${INK}" stroke-width=".8"/>`);
    }
    if (d.fort >= 2) { // a citadel: angled bastions at the corners and a moat before the wall
      add(`<rect x="${left - 18}" y="${ground + 12}" width="${right - left + 36}" height="4" fill="#7fa6bd" stroke="${INK}" stroke-width=".4"/>`);
      for (const [x, dir] of [[left - 12, -1], [right + 15, 1]])
        add(`<path d="M${x} ${ground - 8} L${x + dir * 12} ${ground + 3} L${x} ${ground + 12} Z" fill="#9c9178" stroke="${INK}" stroke-width=".8"/>`);
      add(`<rect x="183" y="${ground - 62}" width="14" height="22" fill="#b9ad92" stroke="${INK}" stroke-width=".8"/>`);
    }
    if (!d.isCapital) banner(highest[0], highest[1]);
    const town = out.splice(0);
    out.push(...outside, ...outer, `<g transform="translate(190 ${ground + 6}) scale(1.4) translate(-190 ${-(ground + 6)})">${town.join("")}</g>`);
    if (d.unrest) for (let k = 0; k < 2; k++) add(`<path d="M${200 + k * 40} ${ground - 10} q -10 -20 4 -36 q 12 -14 0 -30" stroke="#4a4038" stroke-width="${6 - k * 2}" fill="none" opacity=".45"/>`);
    // Laid on canvas: brushed edges, the weave of the cloth, a varnish darkening at the corners.
    const paint = `<filter id="brush${i}" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".06 .09" numOctaves="2" seed="${i}" result="n"/>
        <feDisplacementMap in="SourceGraphic" in2="n" scale="3.2"/></filter>
      <filter id="weave${i}"><feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="2" seed="3"/><feColorMatrix values="0 0 0 0 .32  0 0 0 0 .24  0 0 0 0 .12  0 0 0 .55 0"/></filter>
      <radialGradient id="varnish${i}" cx=".5" cy=".45" r=".75"><stop offset=".55" stop-color="#3a2410" stop-opacity="0"/><stop offset="1" stop-color="#3a2410" stop-opacity=".45"/></radialGradient>`;
    return `<svg class="vista" viewBox="0 0 ${W} ${H}" role="img" aria-label="A view of ${esc(p.name)}"><defs>${paint}</defs>
      <g filter="url(#brush${i})">${out.join("")}</g>
      <rect width="${W}" height="${H}" filter="url(#weave${i})" opacity=".35"/><rect width="${W}" height="${H}" fill="url(#varnish${i})"/>
      <rect x=".5" y=".5" width="${W - 1}" height="${H - 1}" fill="none" stroke="${INK}" stroke-opacity=".5"/></svg>`;
  }

  // ------------------------------------------------------------------ the deed's common sections
  // ---------------------------------------------------------------- the land, in words
  const TERRAIN_ICON = {plains: "🌾", forest: "🌲", hills: "⛰", marsh: "🌿", mountains: "🏔"};
  const TERRAIN_LORE = {plains: "Open fields: bread for armies, easy to grow, hard to hold.",
    forest: "Woods and clearings: timber in plenty, little bread, a cavalryman's trap.",
    hills: "Mines and hardy folk: iron and soldiers, and good ground to defend.",
    marsh: "Fens and reeds: slow to drain, slow to take.", mountains: "Passes and peaks: iron and men, little bread, a fortress made by God."};
  function terrainLines(S, t) {
    const e = (S.terrains || {})[t];
    if (!e) return [];
    const icon = Object.fromEntries(RES.map(([key, , ic]) => [key, ic]));
    const yields = Object.entries(e.yield).map(([k, v]) => `${v > 0 ? "+" : "−"}${Math.abs(v)} ${icon[k] || k}`).join(" ");
    const pct = (x) => `${x < 1 ? "−" : "+"}${Math.round(Math.abs(x - 1) * 100)}%`;
    const out = [];
    if (yields) out.push(`<b class="${Object.values(e.yield).some((v) => v < 0) ? "mixed" : "good"}">${yields}</b> a year`);
    out.push(e.develop === 1 ? "developing at the usual price" : `developing ${pct(e.develop)}`);
    out.push(`defenders ×${e.defence}`);
    if (e.cavalry !== 1) out.push(`cavalry ×${e.cavalry}`);
    if (e.archers !== 1) out.push(`archers ×${e.archers}`);
    return out;
  }

  // ---------------------------------------------------------------- portraits
  // A face for anyone at court: drawn from their name, so the same person always looks the same,
  // greying with age, and crowned, turbaned or capped as their title demands.
  let PAINTED = {}, PAINTED_AT = "";
  function usePortraits(index, base) { PAINTED = index || {}; PAINTED_AT = base; }
  function portrait(person, color, size = 64) {
    const seed = person.name || "?";
    if (PAINTED[seed]) // a period painting, framed in the court's colour
      return `<img class="portrait painted" src="${PAINTED_AT}${PAINTED[seed]}.jpg" width="${size}" height="${Math.round(size * 1.25)}"
        alt="${esc(seed)}" loading="lazy" style="border-color:${color}">`;
    let h = 2166136261;
    for (const c of seed) h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0;
    const pick = (k, n) => ((h >>> k) ^ (h >>> (k + 7))) % n;
    const title = (person.title || "").toLowerCase(), age = person.age || 40, queen = title === "queen";
    const skin = ["#f1d2b0", "#e6bf98", "#d9ab82", "#c99a72"][pick(1, 4)];
    const shade = mix(skin, "#5a3a22", .28);
    let hair = ["#2b1a0e", "#4a2e16", "#6e4a26", "#9a7444", "#c8a46a", "#3a2a1c"][pick(3, 6)];
    if (age > 62) hair = "#e8e2d6"; else if (age > 50) hair = mix(hair, "#d8d4cc", .55);
    const sultan = title === "sultan", tsar = title === "tsar" || title === "grand prince";
    const beard = !queen && (sultan || tsar || pick(5, 10) > 3);
    const long = queen || pick(8, 3) === 0;
    const robe = mix(color, "#000000", .35), trim = person.title ? "#f4efe2" : mix(color, "#000000", .55);
    const eyeY = 31, brow = pick(10, 3);
    let hat = "";
    if (title === "king" || queen) {
      hat = `<path d="M${queen ? 22 : 20} 20 l2 -9 l4 6 l4 -9 l4 9 l4 -6 l2 9 z" fill="#e6c27e" stroke="#5a3f17" stroke-width=".8"/>
        <circle cx="32" cy="15" r="1.4" fill="#b8333a"/><circle cx="25" cy="17" r="1" fill="#2f55a4"/><circle cx="39" cy="17" r="1" fill="#2f8a4a"/>`;
    } else if (title === "emperor") {
      hat = `<path d="M20 21 v-8 q12 -9 24 0 v8 z" fill="#e6c27e" stroke="#5a3f17" stroke-width=".8"/>
        <path d="M32 6 v8 M29 8.5 h6" stroke="#5a3f17" stroke-width="1.4"/><path d="M20 15 q12 -6 24 0" fill="none" stroke="#b8333a" stroke-width="1.6"/>`;
    } else if (sultan) {
      hat = `<ellipse cx="32" cy="15" rx="15" ry="10" fill="#f6f1e4" stroke="#7a6a4a" stroke-width=".8"/>
        <path d="M19 16 q13 -6 26 0 M20 12 q12 -5 24 0" fill="none" stroke="#d8cfb8" stroke-width="1"/>
        <ellipse cx="32" cy="9" rx="4" ry="3" fill="#b8333a"/><path d="M33 7 q4 -7 2 -9" stroke="#3a6a3a" stroke-width="1.6" fill="none"/>`;
    } else if (tsar) {
      hat = `<path d="M20 20 q12 -16 24 0 z" fill="#e6c27e" stroke="#5a3f17" stroke-width=".8"/>
        <rect x="18" y="18" width="28" height="5" rx="2.5" fill="#5a3a22"/><path d="M32 4 v6 M29.5 6 h5" stroke="#5a3f17" stroke-width="1.3"/>`;
    } else if (title === "regent") {
      hat = `<ellipse cx="30" cy="16" rx="14" ry="5" fill="#1d1712"/><circle cx="40" cy="14" r="1.6" fill="#e6c27e"/>`;
    } else if (!person.title && pick(12, 3) === 0) {
      hat = `<path d="M19 19 q13 -11 26 0 z" fill="${mix(color, "#1a120b", .5)}"/>`;
    }
    return `<svg class="portrait" viewBox="0 0 64 64" width="${size}" height="${size}" role="img" aria-label="${esc(seed)}">
      <defs><radialGradient id="bg${h}" cx=".5" cy=".35" r=".8"><stop offset="0" stop-color="${mix(color, "#fff6e0", .35)}"/><stop offset="1" stop-color="${mix(color, "#000000", .25)}"/></radialGradient></defs>
      <rect width="64" height="64" fill="url(#bg${h})"/>
      ${long ? `<path d="M19 26 q-3 22 3 30 h20 q6 -8 3 -30 z" fill="${hair}"/>` : ""}
      <path d="M8 64 q4 -18 24 -18 q20 0 24 18 z" fill="${robe}"/>
      <path d="M20 50 q12 6 24 0 l2 4 q-14 8 -28 0 z" fill="${trim}"/>
      ${person.title ? `<g fill="#1a120b">${[22, 28, 34, 40].map((x) => `<rect x="${x}" y="52" width="1.6" height="2.4"/>`).join("")}</g>` : ""}
      <rect x="28" y="40" width="8" height="8" fill="${shade}"/>
      <ellipse cx="32" cy="31" rx="10.5" ry="12.5" fill="${skin}" stroke="${mix(skin, "#3a2a18", .5)}" stroke-width=".6"/>
      <ellipse cx="21.6" cy="32" rx="1.6" ry="2.6" fill="${shade}"/><ellipse cx="42.4" cy="32" rx="1.6" ry="2.6" fill="${shade}"/>
      <path d="M21.5 ${26 - brow} q10.5 -${8 + brow} 21 0 q-1 -9 -10.5 -10 q-9.5 1 -10.5 10" fill="${hair}"/>
      <path d="M25.5 ${eyeY - 3.4} q2.5 -1.4 5 0 M33.5 ${eyeY - 3.4} q2.5 -1.4 5 0" stroke="${mix(hair, "#000000", .3)}" stroke-width="1.1" fill="none"/>
      <ellipse cx="28" cy="${eyeY}" rx="1.8" ry="1.1" fill="#fbf6ec"/><ellipse cx="36" cy="${eyeY}" rx="1.8" ry="1.1" fill="#fbf6ec"/>
      <circle cx="28.3" cy="${eyeY}" r=".8" fill="#2a1d12"/><circle cx="36.3" cy="${eyeY}" r=".8" fill="#2a1d12"/>
      <path d="M32 ${eyeY + 1} q-1.6 4.5 -1 5.6 q1 .8 2.2 .1" stroke="${mix(skin, "#3a2a18", .45)}" stroke-width=".9" fill="none"/>
      ${age > 48 ? `<path d="M25 ${eyeY + 3.5} q1.6 1 3 .4 M36 ${eyeY + 3.9} q1.4 .6 3 -.4" stroke="${shade}" stroke-width=".6" fill="none"/>` : ""}
      ${beard ? `<path d="M22.5 34 q1 ${tsar || sultan ? 17 : 12} 9.5 ${tsar || sultan ? 17 : 12} q8.5 0 9.5 -${tsar || sultan ? 17 : 12} q-2 5 -4.5 4.5 q-2 -1.4 -5 -1.4 q-3 0 -5 1.4 q-2.5 .5 -4.5 -4.5" fill="${hair}"/>
        <path d="M28.6 40.2 q3.4 1.6 6.8 0" stroke="${mix(hair, "#000000", .35)}" stroke-width=".9" fill="none"/>`
        : `<path d="M28.6 40 q3.4 1.6 6.8 0" stroke="#9a5a4a" stroke-width="1" fill="none"/>`}
      ${hat}
      <rect x=".5" y=".5" width="63" height="63" fill="none" stroke="#3a2a18"/></svg>`;
  }

  function deedInfo(S, i, d) {
    // d: {owner, isCapital, dev, maxDev, troops (null: hidden), fort, unrest, base[5], bonus[5], built[], queued[], general}
    const P = S.provinces, N = S.nations, B = S.buildings, R = S.rules, p = P[i];
    const slots = d.slots ?? 1 + Math.floor(d.dev / R.slotEvery);
    const defence = R.defender * R.terrain[p.terrain] * (1 + R.fort * d.fort + (d.isCapital ? R.capital : 0));
    const rows = RES.map(([, label, ic], k) => {
      const total = d.unrest ? 0 : d.base[k] + d.bonus[k];
      return `<tr><td>${ic} ${label}</td><td>${d.base[k]}</td><td class="plus">${d.bonus[k] ? "+" + d.bonus[k] : ""}</td>
        <td class="total">${total}</td></tr>`; }).join("");
    const tiles = [], queued = d.queued || [];
    for (let s = 0; s < Math.max(4, slots); s++) {
      if (s < d.built.length) { const b = B[d.built[s]];
        tiles.push(`<div class="slot ${b.category}" title="${esc(b.name)}: ${esc(b.effect)}"><span class="ic">${BICON[b.id]}</span>${esc(b.name)}</div>`); }
      else if (s < d.built.length + queued.length) { const b = B[queued[s - d.built.length]];
        tiles.push(`<div class="slot queued" title="Ordered this year"><span class="ic">${BICON[b.id]}</span>${esc(b.name)}<br><small>ordered</small></div>`); }
      else if (s < slots) tiles.push(`<div class="slot free" data-slot><span class="ic">＋</span>Free slot</div>`);
      else tiles.push(`<div class="slot locked" title="Opens at development ${s * R.slotEvery}"><span class="ic">🔒</span>Development ${s * R.slotEvery}</div>`);
    }
    const owner = d.owner >= 0 ? esc(N[d.owner].name) + (d.isCapital ? ", capital" : "") : "Independent";
    const maxDev = d.maxDev || R.maxDevelopment;
    const kind = d.dev >= 10 ? "City" : d.dev >= 6 ? "Town" : d.dev >= 3 ? "Village" : "Hamlet";
    return {
      slots,
      vista: vista(S, i, d),
      header: `<header class="deedhead">${d.view ? `<figure class="view"><img src="${d.view.src}" alt="${esc(d.view.city)} in the 1570s" width="570" height="225">
          <figcaption>${esc(d.view.city)}, as ${esc(d.view.by)} engraved it</figcaption></figure>` : vista(S, i, d)}
        <div class="ribbon"><span class="shield" style="background:${d.owner >= 0 ? N[d.owner].color : "var(--free)"}"></span>
          <div><h2 id="deedname">${esc(p.name)}</h2><div class="owner">${d.owner >= 0 ? `${kind} of ${owner}` : `Independent ${kind.toLowerCase()}`}</div></div></div>
        <button class="x" data-close aria-label="Close the province deed" title="Close (Esc)">×</button></header>`,
      facts: `<section class="strip num">
        <div title="Development: output, score and building slots. ${d.dev} of ${maxDev}."><span>🏛</span><b>${d.dev}</b><i style="width:${Math.round(d.dev / maxDev * 100)}%"></i><small>development</small></div>
        <div title="Regiments in garrison"><span>⚔</span><b>${d.troops === null ? "?" : d.troops}</b><small>regiments</small></div>
        <div title="How much harder defenders fight here: terrain, forts, capital"><span>🛡</span><b>×${defence.toFixed(2)}</b><small>defence</small></div>
        <div title="${esc(cap(p.terrain))}: ${esc((S.terrainEffects || {})[p.terrain] || "")}"><span>${{plains: "🌾", forest: "🌲", hills: "⛰", marsh: "🌿", mountains: "🏔"}[p.terrain]}</span><b>${cap(p.terrain)}</b><small>terrain</small></div>
        <div title="What the province produces most"><span>${{grain: "🌾", iron: "⛏", gold: "✦", timber: "🪵"}[p.good]}</span><b>${cap(GOOD[p.good])}</b><small>trade good</small></div>
      </section>
      ${d.unrest ? `<p class="note unrest">🔥 In unrest for ${d.unrest} more ${d.unrest === 1 ? "year" : "years"}: it produces nothing until then.</p>` : ""}
      ${d.general ? `<p class="note" style="font-style:normal">⚑ ${esc(d.general.name)} <span class="stars">${"★".repeat(d.general.skill)}${"☆".repeat(3 - d.general.skill)}</span> commands here.</p>` : ""}`,
      production: `<section><h4>Production per year</h4>
        <table class="prod num"><thead><tr><th></th><th>Land</th><th>Buildings</th><th>Total</th></tr></thead><tbody>${rows}</tbody></table></section>`,
      slotsHtml: `<h4>Buildings, ${d.built.length} of ${slots} slots</h4><div class="slots">${tiles.join("")}</div>`,
    };
  }

  return {create, deedInfo, vista, portrait, usePortraits, terrainLines, TERRAIN_ICON, TERRAIN_LORE, el, esc, mix, devColor, cap, costText, TERRAIN, RES, GOOD, BICON, UICON, ICON, MAJOR, MINOR, BAD};
})();
