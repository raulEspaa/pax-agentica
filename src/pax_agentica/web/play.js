// Pax Agentica: play one nation. You see your NationView (fog of war included), queue Orders,
// and end the year. The server resolves the turn with every other ruler and sends the new view.
"use strict";

(async () => {
  const {esc, mix, devColor, cap, costText, RES, BICON, UICON, ICON, BAD, TERRAIN} = PaxMap;
  const $ = (id) => document.getElementById(id);
  // At a table of several players (pax host) the page lives at /t/<table> and every call carries
  // this browser's seat token; alone (pax serve) it talks to /api directly.
  const TABLE = window.PAX_TABLE || null, BASE = TABLE ? `/api/t/${TABLE}` : "/api";
  const seatKey = `pax-seat-${TABLE}`;
  if (TABLE) {
    const fromLink = new URLSearchParams(location.search).get("seat");
    if (fromLink) { try { localStorage.setItem(seatKey, fromLink); } catch {} history.replaceState(null, "", location.pathname); }
  }
  const SEAT = TABLE ? (() => { try { return localStorage.getItem(seatKey); } catch { return null; } })() : null;
  if (TABLE && !SEAT) { location.href = `/?table=${TABLE}`; return; }
  const api = (path, opts = {}) => fetch(`${BASE}${path}`, {...opts, headers: {...(opts.headers || {}), ...(SEAT ? {"X-Seat": SEAT} : {})}});
  const REPLAY = TABLE ? `/t/${TABLE}/replay` : "/replay";
  const S = await (await api("/static")).json();
  const P = S.provinces, N = S.nations, B = S.buildings, R = S.rules, T = S.tech, U = S.units, M = S.monuments;
  const KINDS = U.map((u) => u.id);
  PaxMap.usePortraits(S.portraits, "/portraits/");
  const pIndex = Object.fromEntries(P.map((p, i) => [p.id, i]));
  const nIndex = Object.fromEntries(N.map((n, i) => [n.id, i]));
  const bIndex = Object.fromEntries(B.map((b, i) => [b.id, i]));
  const unbundle = (obj) => S.resources.map((r) => (obj && obj[r]) || 0);
  const sign = (v) => (v > 0 ? "+" : "") + v;
  const stars = (n) => "★".repeat(n) + "☆".repeat(3 - n);
  const MAX_ORDERS = 50;

  let G = null, V = null, me = -1;                // game payload, my view, my nation index
  let orders = [], mode = "political", picked = -1, focus = -1, tab = "realm", send = Infinity, lead = true;
  let pickMix = null; // regiments chosen by kind for the next march, or null for a proportional draw

  const map = PaxMap.create($("map"), S, {
    hover: (i, e) => tooltip(i, e),
    leave: () => { $("tip").style.display = "none"; },
    click: (i) => select(i),
    command: (i) => command(i),
  });

  // ------------------------------------------------------------------ server
  async function load() {
    const r = await api("/game");
    if (r.status === 403 && TABLE) { location.href = `/?table=${TABLE}`; return; }
    G = await r.json(); afterLoad(); watch();
  }
  async function endTurn() {
    const button = $("endturn"); button.disabled = true; button.textContent = "The year passes…";
    try {
      const r = await api("/turn", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({actions: orders})});
      if (!r.ok) { const body = await r.json().catch(() => ({})); throw new Error(body.detail ? JSON.stringify(body.detail) : r.statusText); }
      const before = V, next = await r.json();
      if (next.view.turn === V.turn && !next.finished) { G = next; afterLoad(); watch(); return; } // the others are still deciding
      G = next; orders = []; picked = -1; afterLoad(); report(before); watch();
    } catch (err) { flash(`The orders could not be sent: ${err.message}`); render(); }
  }
  // At a table: while others decide (or a turn timer runs), ask now and then whether the year has passed.
  function watch() {
    clearTimeout(watch.t);
    if (!TABLE || G.finished) return;
    watch.t = setTimeout(async () => {
      try {
        const st = await (await api("/status")).json();
        if (st.turn !== V.turn || st.finished) {
          const before = V; G = await (await api("/game")).json();
          orders = []; picked = -1; afterLoad(); report(before);
        } else { G.waiting_for = st.waiting_for; G.submitted = st.submitted; G.seconds_left = st.seconds_left; G.force_in = st.force_in;
          if (st.closed && G.table) G.table.closed = st.closed; banner(); }
      } catch {}
      watch();
    }, G.submitted ? 2500 : 6000);
  }
  const who = (nid) => `${nameOf(nid)}${G.humans && G.humans[nid] ? ` (${G.humans[nid]})` : ""}`;
  function banner() {
    const fallen = !V.me.provinces.length;
    const clock = G.seconds_left != null && !G.finished ? ` ⏳ ${Math.floor(G.seconds_left / 60)}:${String(G.seconds_left % 60).padStart(2, "0")} left this year.` : "";
    const others = (G.waiting_for || []).filter((n) => n !== G.human);
    const closed = TABLE && G.table && G.table.closed;
    const force = G.force_in === 0 ? ` <button class="btn" id="forceyear">Don't wait for them</button>`
      : G.force_in ? ` You may go on without them in ${Math.ceil(G.force_in / 60)} min.` : "";
    const leave = TABLE && !closed && !G.finished ? ` <button class="btn quiet" id="leavetable" title="Give your throne back to a bot">Leave the table</button>` : "";
    const table = closed ? `<div class="banner">This table is closed (${esc(closed)}). <a href="${REPLAY}" target="_blank">Watch the replay</a> · <a href="/">Back to the tables</a></div>`
      : TABLE && !G.finished ? (G.submitted
      ? `<div class="banner">📜 Your orders are sent; you may still change them and send again. Waiting for ${others.map(who).join(", ") || "the clerks"}.${clock}${force}${leave}</div>`
      : `<div class="banner">${others.length ? `Still deciding: ${others.map(who).join(", ")}.` : "Your court awaits your orders."}${clock}${leave}</div>`) : "";
    $("banner").innerHTML = G.finished ? `<div class="over">👑 ${esc(G.winner ? nameOf(G.winner) + " wins." : "The game is over.")} <a href="${REPLAY}" target="_blank">Watch the replay</a></div>`
      : fallen ? `<div class="banner">Your realm has fallen. You can watch the rest of the game year by year.</div>` : table;
    const fb = $("forceyear");
    if (fb) fb.onclick = async () => { fb.disabled = true; const before = V;
      const r = await api("/force", {method: "POST"});
      if (r.ok) { G = await r.json(); orders = []; picked = -1; afterLoad(); report(before); } else flash("Not yet: give the others a little more time."); };
    const lb = $("leavetable");
    if (lb) lb.onclick = async () => {
      if (!confirm("Leave this table? A bot will rule your realm from now on, and you cannot come back to it.")) return;
      await api("/leave", {method: "POST"});
      try { localStorage.removeItem(seatKey); } catch {}
      location.href = "/"; };
  }
  function afterLoad() {
    V = G.view; me = nIndex[G.human];
    if (!afterLoad.done) { afterLoad.done = true; setTimeout(eventSheet, 400); }
    if (!map.homed) { map.home(V.me.provinces.map((p) => pIndex[p])); map.homed = true; }
    render();
  }
  function flash(text) { const e = $("error"); e.textContent = text; e.style.display = "block"; clearTimeout(flash.t); flash.t = setTimeout(() => (e.style.display = "none"), 5000); }
  function queue(order) {
    if (orders.length >= MAX_ORDERS) return flash(`A realm can give at most ${MAX_ORDERS} orders a year.`);
    orders.push(order); render();
  }

  // ------------------------------------------------------------------ what the orders cost and leave behind
  const prov = (i) => V.provinces[i];
  const holder = (i) => prov(i).controller || prov(i).owner;
  const owned = (i) => holder(i) === G.human; // where your regiments may stand and march from
  const ruled = (i) => prov(i).owner === G.human && !prov(i).controller; // where you may build and levy
  const nameOf = (nid) => N[nIndex[nid]].name;
  const relation = (nid) => {
    const war = V.me.wars.find((w) => w.enemy === nid);
    const t = (kind) => V.me.treaties.find((x) => x.partner === nid && x.kind === kind);
    const leagues = V.me.treaties.filter((x) => x.partner === nid && x.kind === "coalition").map((x) => x.against);
    return {war, alliance: t("alliance"), pact: t("non_aggression"), truce: t("truce"), marriage: t("marriage"), leagues};
  };
  const buildCost = (id) => unbundle(V.me.building_costs[id]);
  const researching = () => orders.find((o) => o.type === "research");
  function projected() {
    const t = unbundle(V.me.resources);
    const sub = (c) => c.forEach((v, k) => (t[k] -= v));
    for (const o of orders) {
      if (o.type === "recruit") { const p = prov(pIndex[o.province]); sub(unbundle((p.recruit_costs || {})[o.unit || "infantry"] || p.recruit_cost).map((v) => v * o.regiments)); }
      if (o.type === "upgrade_monument") sub(R.monumentCost.map((v) => v * ((prov(pIndex[o.province]).monument || 0) + 1)));
      if (o.type === "propose_peace") sub(unbundle(o.give));
      if (o.type === "buy") { const k = RES.findIndex(([key]) => key === o.resource); t[k] += o.amount; t[0] -= Math.ceil(o.amount * V.market[o.resource].buy); }
      if (o.type === "sell") { const k = RES.findIndex(([key]) => key === o.resource); t[k] -= o.amount; t[0] += Math.floor(o.amount * V.market[o.resource].sell); }
      if (o.type === "develop") sub(unbundle(prov(pIndex[o.province]).develop_cost));
      if (o.type === "improve") sub(unbundle(prov(pIndex[o.province]).improve_cost));
      if (o.type === "hire_mercenaries") t[0] -= o.regiments * R.mercenaryCost;
      if (o.type === "patronize") t[0] -= V.me.patronage_cost;
      if (o.type === "build") sub(buildCost(o.building));
      if (o.type === "boost_stability") sub([stabilityCost(), 0, 0, 0, 0]);
      if (o.type === "research") sub(unbundle(V.me.research_costs[o.branch]));
      if (o.type === "hire_general") sub(R.generalCost);
      if (o.type === "hire_advisor") { const c = V.me.advisor_candidates.find((x) => x.id === o.candidate); if (c) sub([c.hire_cost, 0, 0, 0, 0]); }
      if (o.type === "gift") sub(unbundle(o.resources));
      if (o.type === "disband") R.disband.forEach((v, k) => (t[k] += v * o.regiments));
    }
    return t;
  }
  const affordable = (cost, t = projected()) => cost.every((v, k) => t[k] >= v);
  const stabilityCost = () => Math.ceil(R.stabilityCost * (1 - V.me.modifiers.stability_discount));
  function troopsAfter(i) {
    let t = prov(i).troops || 0;
    for (const o of orders) {
      if (o.type === "recruit" && pIndex[o.province] === i) t += o.regiments;
      if (o.type === "disband" && pIndex[o.province] === i) t -= o.regiments;
      if ((o.type === "move" || o.type === "attack") && pIndex[o.origin] === i) t -= o.regiments;
      if (o.type === "move" && pIndex[o.target] === i) t += o.regiments;
    }
    return t;
  }
  // Regiments by kind, as the engine counts them: a proportional draw takes largest remainders.
  function share(army, n) {
    const total = KINDS.reduce((t, k) => t + (army[k] || 0), 0);
    n = Math.min(n, total);
    const out = Object.fromEntries(KINDS.map((k) => [k, 0]));
    if (!total || !n) return out;
    const exact = KINDS.map((k) => (army[k] || 0) * n / total);
    KINDS.forEach((k, j) => (out[k] = Math.floor(exact[j])));
    let rest = n - KINDS.reduce((t, k) => t + out[k], 0);
    KINDS.map((k, j) => [exact[j] - out[k], -j, k]).sort((a, b) => b[0] - a[0] || b[1] - a[1]).slice(0, rest).forEach(([, , k]) => out[k]++);
    return out;
  }
  function armyAfter(i) {
    const a = {...(prov(i).army || {infantry: prov(i).troops || 0})};
    KINDS.forEach((k) => (a[k] = a[k] || 0));
    for (const o of orders) {
      if (o.type === "recruit" && pIndex[o.province] === i) a[o.unit || "infantry"] += o.regiments;
      const leaving = (o.type === "move" || o.type === "attack") && pIndex[o.origin] === i ? o
        : o.type === "disband" && pIndex[o.province] === i ? o : null;
      if (leaving) {
        const gone = leaving.units || (leaving.unit ? {[leaving.unit]: leaving.regiments} : share(a, leaving.regiments));
        KINDS.forEach((k) => (a[k] = Math.max(0, a[k] - (gone[k] || 0))));
      }
      if (o.type === "move" && pIndex[o.target] === i) {
        const came = o.units || {infantry: o.regiments};
        KINDS.forEach((k) => (a[k] += came[k] || 0));
      }
    }
    return a;
  }
  function strength(army, terrain, attacking) {
    const total = KINDS.reduce((t, k) => t + (army[k] || 0), 0);
    if (!total) return 0;
    let power = 0, kinds = 0;
    U.forEach((u) => { const n = army[u.id] || 0; power += n * (attacking ? u.attack : u.defence) * (u.terrain[terrain] || 1);
      if (n && n / total >= R.combinedShare) kinds++; });
    const bonus = Math.max(0, ...Object.entries(R.combinedBonus).filter(([k]) => kinds >= +k).map(([, b]) => b));
    return power * (1 + bonus);
  }
  const siege = (army) => { const total = KINDS.reduce((t, k) => t + (army[k] || 0), 0);
    return total ? Math.floor((army.artillery || 0) / total / R.siegeShare + 1e-9) : 0; };
  function generalPositions() { // where each of my generals stands once this year's orders are carried out
    const at = new Map(V.me.generals.map((g) => [g.id, pIndex[g.province]]));
    for (const o of orders) {
      if (o.type === "assign_general" && at.has(o.general)) at.set(o.general, pIndex[o.province]);
      if (o.type === "move" && o.general && at.has(o.general)) at.set(o.general, pIndex[o.target]);
      if (o.type === "attack" && o.general && at.has(o.general)) at.set(o.general, -1); // in the field
    }
    return at;
  }
  function generalAt(i) {
    for (const [id, where] of generalPositions()) if (where === i) return V.me.generals.find((g) => g.id === id);
    return null;
  }

  // ------------------------------------------------------------------ battles, as the engine rolls them
  function defence(origin, target, breach = 0) {
    const p = prov(target);
    const forts = Math.max(0, p.fort - breach - (V.me.modifiers.ignores_fort_levels || 0));
    let bonus = R.fort * forts + (p.is_capital ? R.capital : 0);
    if (P[origin].sea.includes(target) && !V.me.modifiers.navy) bonus += R.sea;
    const owner = p.owner ? V.nations.find((n) => n.id === p.owner) : null;
    const tech = owner ? 1 + T[0].perLevel * owner.technology.military : 1;
    const guard = p.general && p.general.nation === p.owner ? 1 + R.generalBonus * p.general.skill : 1;
    return R.defender * R.terrain[P[target].terrain] * (1 + bonus) * tech * guard;
  }
  const myFactor = (general) => (1 + T[0].perLevel * V.me.technology.military) * (general ? 1 + R.generalBonus * general.skill : 1);
  function winChance(att, def, mult) {
    if (def === 0) return 1;
    const n = 60, lo = R.rollMin, span = R.rollMax - R.rollMin;
    let wins = 0;
    for (let a = 0; a < n; a++) for (let d = 0; d < n; d++)
      if (att * (lo + span * (a + .5) / n) > def * mult * (lo + span * (d + .5) / n)) wins++;
    return wins / (n * n);
  }
  function targetsFrom(i) {
    const out = [];
    for (const j of [...P[i].land, ...P[i].sea]) {
      const o = holder(j);
      if (o === G.human) out.push([j, "move"]);
      else if (o === null) out.push([j, "attack"]);
      else { const w = relation(o).war; if (w && w.attacks_allowed_from_turn <= V.turn) out.push([j, "attack"]); }
    }
    return out;
  }
  // Who marches: the regiments chosen by kind, or a proportional draw of `send`.
  function force(from) {
    const here = armyAfter(from);
    if (pickMix) { const out = {}; KINDS.forEach((k) => (out[k] = Math.min(pickMix[k] || 0, here[k]))); return out; }
    return share(here, Math.min(send, troopsAfter(from)));
  }
  function odds(from, to, army = force(from)) {
    const p = prov(to), g = lead ? generalAt(from) : null;
    const n = KINDS.reduce((t, k) => t + army[k], 0);
    if (p.troops === null || !n) return null;
    if (!p.troops) return 1;
    const ground = P[to].terrain;
    const mine = strength(army, ground, true) * myFactor(g);
    const theirs = p.army ? strength(p.army, ground, false) : p.troops;
    return winChance(mine, theirs, defence(from, to, siege(army)));
  }

  // ------------------------------------------------------------------ selecting and commanding
  function select(i) {
    if (i < 0) return;
    picked = i === picked ? -1 : i;
    send = Infinity; lead = true; pickMix = null;
    const o = picked >= 0 ? prov(picked).owner : null;
    if (o && o !== G.human) focus = nIndex[o];
    else if (o === G.human) focus = -1; // your own land: the diplomacy map shows your relations again
    render();
  }
  function command(i) { // right-click: march or attack from the selected province
    if (picked < 0 || !owned(picked)) return flash("Select one of your provinces first, then right-click where its regiments should go.");
    const target = targetsFrom(picked).find(([j]) => j === i);
    if (!target) {
      const o = prov(i).owner, w = o && o !== G.human ? relation(o).war : null;
      return flash(o && o !== G.human && !w ? `You are not at war with ${nameOf(o)}.`
        : w && w.attacks_allowed_from_turn > V.turn ? "Your armies are still mobilising."
        : `${P[i].name} does not border ${P[picked].name}.`);
    }
    march(picked, i, target[1]);
  }
  function march(from, to, kind) {
    const army = force(from), n = KINDS.reduce((t, k) => t + army[k], 0);
    if (n <= 0) return flash(`No regiments left in ${P[from].name}.`);
    const g = lead ? generalAt(from) : null;
    const order = {type: kind, origin: P[from].id, target: P[to].id, regiments: n};
    if (pickMix) order.units = Object.fromEntries(KINDS.filter((k) => army[k]).map((k) => [k, army[k]]));
    if (g) order.general = g.id;
    queue(order);
  }

  // ------------------------------------------------------------------ the province deed
  // What a work without a yield does, in a few words for its tile.
  const PERK = {university: "develop −30% here", armory: "½ iron per regiment", fort: "+25% defence",
    citadel: "+25% more defence", training_grounds: "+20% garrison", stables: "🐎 cavalry here", cannon_foundry: "💣 artillery here",
    military_academy: "+1 general", royal_exchange: "+10% ducats, all realm", observatory: "−15% research", cathedral: "unrest ends ×2",
    barracks: "higher manpower cap", arms_manufactory: "levies need ½ iron, no goods", powder_mill: "+5% power, breaches a fort level",
    workshop: "makes goods"};
  const icons = (c) => RES.map(([, , ic], k) => c[k] ? `${c[k]}${ic}` : "").filter(Boolean).join(" ");
  const gainText = (g) => RES.map(([key, , ic]) => g && g[key] ? `<span>+${g[key]} ${ic}</span>` : "").join("");
  let ownTab = "economy";
  function monumentCard(i, mine, t) {
    const p = prov(i), mon = M[p.id];
    if (!mon || p.monument === null) return "";
    const level = p.monument, queued = orders.some((o) => o.type === "upgrade_monument" && pIndex[o.province] === i);
    const cost = R.monumentCost.map((v) => v * (level + 1));
    const why = level >= R.maxMonument ? "at its greatest" : queued ? "already ordered" : p.unrest ? "in unrest" : !affordable(cost, t) ? "too costly" : "";
    const now = level ? `Level ${level}: ${esc(mon.effect.replace(/(\d+)%/, (_, x) => `${x * level}%`))}.` : "Not yet built: a bare site.";
    return `<section><div class="card monument ${level ? "built" : "site"}">
      <div class="cardhead"><span class="ic">${level ? "🏛" : "📐"}</span><div><b>${esc(mon.name)}</b>
        <div class="stars" title="Level ${level} of ${R.maxMonument}">${"★".repeat(level)}${"☆".repeat(R.maxMonument - level)}</div></div></div>
      <p class="lore">${esc(mon.lore)}</p>
      <p class="note">${now} Every level adds ${esc(mon.effect)}, to whoever holds ${esc(P[i].name)}.</p>
      ${mine ? `<div class="act"><button class="btn" data-monument ${why ? "disabled" : ""}>${why ? cap(why) : level ? `Raise to level ${level + 1}` : "Lay the first stone"}</button>
        ${level < R.maxMonument ? `<span class="cost">${costText(cost)}</span>` : ""}</div>` : ""}</div></section>`;
  }
  function deed() {
    const box = $("deed");
    if (picked < 0) { box.classList.remove("open"); map.setTargets([]); hint(""); return; }
    const i = picked, p = prov(i), o = p.owner === null ? -1 : nIndex[p.owner], mine = owned(i), works = ruled(i);
    if (mine && !works) ownTab = "army"; // land you occupy: only your regiments act there
    const out = unbundle(p.output_per_turn), extra = unbundle(p.building_output_per_turn);
    const queued = orders.filter((x) => x.type === "build" && pIndex[x.province] === i).map((x) => bIndex[x.building]);
    const info = PaxMap.deedInfo(S, i, {owner: o, isCapital: p.is_capital, dev: p.development, troops: p.troops, monument: p.monument, view: S.views[p.id] ? {...S.views[p.id], src: `/views/${p.id}.jpg`} : null,
      fort: p.fort, unrest: p.unrest, base: out.map((v, k) => v - extra[k]), bonus: extra, slots: p.building_slots,
      maxDev: mine ? V.me.modifiers.max_development : R.maxDevelopment, general: p.general,
      built: p.buildings.map((b) => bIndex[b]), queued: mine ? queued : []});
    let body = "";
    if (mine) {
      const here = troopsAfter(i), t = projected(), g = generalAt(i), targets = here > 0 ? targetsFrom(i) : [];
      const preview = (G.previews || {})[p.id] || {develop: {}, buildings: {}};
      map.setTargets(targets);
      hint(here > 0 ? `${P[i].name}: ${here} regiments ready. Right-click a green province to march, a red one to attack.` : "");
      const free = info.slots - p.buildings.length - queued.length;
      const tabs = [...(works ? [["economy", "💰 Economy"], ["buildings", `🏗 Buildings <small>${p.buildings.length + queued.length}/${info.slots}</small>`]] : []),
        ["army", `⚔ Army <small>${here}</small>`]];
      body += `<nav class="deedtabs" role="tablist">${tabs.map(([id, label]) =>
        `<button role="tab" aria-selected="${ownTab === id}" class="${ownTab === id ? "on" : ""}" data-dtab="${id}">${label}</button>`).join("")}</nav>`;
      if (ownTab === "economy") {
        const dev = unbundle(p.develop_cost), maxDev = V.me.modifiers.max_development;
        const devQueued = orders.some((x) => x.type === "develop" && pIndex[x.province] === i);
        const next = p.development + 1, slotOpens = next % R.slotEvery === 0;
        const devWhy = p.development >= maxDev ? `development is at its ceiling (${maxDev})` : devQueued ? "already ordered this year" : !affordable(dev, t) ? "too costly for now" : "";
        const ground = P[i].terrain;
        body += info.production + `<section><div class="land"><span class="ic">${PaxMap.TERRAIN_ICON[ground]}</span><div><b>${cap(ground)}</b>
            <p class="lore">${esc(PaxMap.TERRAIN_LORE[ground])}</p><div class="effects">${PaxMap.terrainLines(S, ground).map((x) => `<span>${x}</span>`).join("")}</div></div></div></section>
          <section><div class="card ${devWhy ? "blocked" : "ready"}">
            <div class="cardhead"><span class="ic">🏛</span><div><b>Develop to ${Math.min(next, maxDev)}</b>
              <div class="gain">${p.development < maxDev ? gainText(preview.develop) || "<span>more score</span>" : ""}<span>+1 score</span></div></div></div>
            <p class="note">${slotOpens ? "<b>Opens a new building slot.</b> " : `Next building slot at development ${Math.ceil(next / R.slotEvery) * R.slotEvery}. `}Score is what wins the game.</p>
            <div class="act"><button class="btn" data-act="develop" ${devWhy ? "disabled" : ""}>${devWhy ? cap(devWhy) : "Develop"}</button><span class="cost">${costText(dev)}</span></div></div></section>`;
        // the province's workings: its mine, vineyard or fishery, raised level by level
        const good = PaxMap.goodOf(S, P[i].good), level = p.workings || 0, top = R.maxWorkings || 3;
        const impQueued = orders.some((x) => x.type === "improve" && pIndex[x.province] === i);
        const imp = p.improve_cost ? unbundle(p.improve_cost) : null;
        const impWhy = !imp ? "at the highest level" : impQueued ? "already ordered this year" : !affordable(imp, t) ? "too costly for now" : "";
        body += `<section><div class="card ${impWhy ? "blocked" : "ready"}">
            <div class="cardhead"><span class="ic">${good.icon}</span><div><b>${esc(good.workings)} <span class="pips">${"●".repeat(level)}${"○".repeat(top - level)}</span></b>
              <div class="gain">${imp ? gainText(preview.improve) || "<span>little at this development</span>" : ""}</div></div></div>
            <p class="note">${esc(P[i].name)} is known for its ${esc(good.name.toLowerCase())}: ${esc(PaxMap.yieldWords(good.yield))} per development. Each level adds half of it again, and grows as the province develops. No slot needed.</p>
            <div class="act"><button class="btn" data-act="improve" ${impWhy ? "disabled" : ""}>${impWhy ? cap(impWhy) : `Raise to level ${level + 1}`}</button>${imp ? `<span class="cost">${costText(imp)}</span>` : ""}</div></div></section>`;
        const best = B.filter((b) => !p.buildings.includes(b.id) && !queued.includes(bIndex[b.id]) && !(b.tech && V.me.technology[b.tech[0]] < b.tech[1])
            && !(b.requires >= 0 && !p.buildings.includes(B[b.requires].id)))
          .map((b) => [b, preview.buildings[b.id] || {}]).filter(([, gain]) => gain.ducats > 0)
          .sort((a, b) => b[1].ducats - a[1].ducats).slice(0, 2);
        body += monumentCard(i, true, t);
        if (best.length && free > 0) body += `<section><h4>Best works here</h4>${best.map(([b, gain]) =>
          `<div class="act"><span class="ic">${BICON[b.id]}</span><b>${esc(b.name)}</b><span class="gain">${gainText(gain)}</span>
            <button class="btn" data-build="${b.id}" ${affordable(buildCost(b.id), t) ? "" : "disabled"}>Build</button><span class="cost">${costText(buildCost(b.id))}</span></div>`).join("")}</section>`;
      } else if (ownTab === "buildings") {
        const tiles = B.map((b, k) => {
          const built = p.buildings.includes(b.id), ordered = queued.includes(k), cost = buildCost(b.id);
          const needs = b.requires >= 0 && !p.buildings.includes(B[b.requires].id) && !queued.includes(b.requires);
          const tech = b.tech && V.me.technology[b.tech[0]] < b.tech[1];
          const why = built || ordered ? "" : tech ? `🔒 ${cap(b.tech[0])} ${b.tech[1]}` : needs ? `needs a ${B[b.requires].name.toLowerCase()}` : free <= 0 ? "no free slot" : !affordable(cost, t) ? "too costly" : "";
          // one clean ledger per work: what it yields a year in green, what it eats in red, any perk below
          const gain = (built ? preview.built || {} : preview.buildings || {})[b.id] || {};
          const plus = RES.filter(([key]) => gain[key] > 0).map(([key, , ic]) => `<span class="in">+${gain[key]}${ic}</span>`);
          const minus = RES.map(([, , ic], k) => (b.consumes || [])[k] ? `<span class="out">−${b.consumes[k]}${ic}</span>` : "").filter(Boolean);
          const isIdle = built && p.idle.includes(b.id);
          const state = built ? "built" : ordered ? "ordered" : tech ? "locked" : why ? "blocked" : "ready";
          const tip = `${b.name}: ${b.effect}.${minus.length ? ` Eats ${costText(b.consumes)} a year; idle without them.` : ""}${b.tech ? ` Needs ${b.tech[0]} technology ${b.tech[1]}.` : ""}`;
          return [["built", "ordered", "ready", "blocked", "locked"].indexOf(state), `<div class="tile ${b.category} ${state}" title="${esc(tip)}">
            <div class="thead"><span class="ic">${BICON[b.id]}</span><b>${esc(b.name)}</b>${b.unique ? `<small class="star" title="A great work: one per realm">★</small>` : ""}${isIdle ? `<span class="idle" title="Its inputs went unpaid last year">idle</span>` : built ? `<span class="tick">✓</span>` : ordered ? `<span class="tick">⏳</span>` : ""}</div>
            <div class="ledger">${plus.join("")}${minus.length ? `<span class="per">${minus.join("")}<small>/yr</small></span>` : ""}${!plus.length && !minus.length && !PERK[b.id] ? `<span class="none">—</span>` : ""}</div>
            ${PERK[b.id] ? `<div class="perk">${esc(PERK[b.id])}</div>` : ""}
            ${built || ordered ? "" : `<button class="btn" data-build="${b.id}" ${why ? "disabled" : ""}>${why || `Build · ${icons(cost)}`}</button>`}</div>`];
        }).sort((x, y) => x[0] - y[0]).map((x) => x[1]).join("");
        body += `${S.views[p.id] ? `<section class="town"><h4>The town today</h4>${info.vista}</section>` : ""}<section>${info.slotsHtml}<div class="tiles">${tiles}</div>
          <p class="note">A new slot opens every ${R.slotEvery} development. Hover a work to read what it does.</p></section>`;
      } else {
        const now = armyAfter(i), ground = P[i].terrain;
        const comp = U.map((u) => `<div class="unit ${now[u.id] ? "" : "none"}" title="${esc(u.name)}: ${esc(u.role)}">
          <span class="ic">${UICON[u.id]}</span><b>${now[u.id]}</b><small>${esc(u.id)}</small></div>`).join("");
        const mixed = U.filter((u) => now[u.id] / Math.max(1, here) >= R.combinedShare).length;
        const marches = targets.map(([j, kind]) => {
          const chance = kind === "attack" ? odds(i, j) : null;
          return `<button class="btn" data-march="${j}" data-kind="${kind}">${kind === "move" ? "➜" : "⚔"} ${esc(P[j].name)}${chance !== null ? ` ${Math.round(chance * 100)}%` : ""}</button>`;
        }).join("");
        const leader = g ? `<label class="leader"><input type="checkbox" id="lead" ${lead ? "checked" : ""}> led by ${esc(g.name)} <span class="stars">${stars(g.skill)}</span></label>`
          : V.me.generals.length < V.me.modifiers.max_generals ? `<div class="act"><button class="btn" data-act="hire" ${affordable(R.generalCost, t) ? "" : "disabled"}>Appoint a general here</button><span class="cost">${costText(R.generalCost)}</span></div>` : "";
        const chooser = pickMix
          ? U.filter((u) => now[u.id]).map((u) => `<div class="act"><span class="ic">${UICON[u.id]}</span>${stepper(`mix_${u.id}`, Math.min(pickMix[u.id] || 0, now[u.id]), now[u.id], 0)}<span>of ${now[u.id]} ${esc(u.id)}</span></div>`).join("")
          : `<div class="act">${stepper("send", Math.min(send, Math.max(here, 1)), Math.max(here, 1))}<span>of ${here} regiments, a fair share of each kind</span></div>`;
        const terrainNote = (u) => Object.entries(u.terrain).map(([t, v]) => `×${v} ${t}`).join(", ");
        const levy = U.map((u) => {
          const price = (p.recruit_costs || {})[u.id], n = Math.max(1, +(box.dataset[`recruit_${u.id}`] || 1));
          const cost = price ? unbundle(price).map((v) => v * n) : null;
          const why = !price ? (u.requires >= 0 ? `needs ${B[u.requires].name.toLowerCase()}` : "not here") : !affordable(cost, t) ? "too costly" : "";
          return `<div class="levy ${price ? "" : "blocked"}"><span class="ic">${UICON[u.id]}</span>
            <div><b>${esc(u.name)}</b><small>attack ${u.attack}, defence ${u.defence}${terrainNote(u) ? `; ${terrainNote(u)}` : ""}</small></div>
            ${price ? stepper(`recruit_${u.id}`, n, 99) : ""}
            <button class="btn" data-recruit="${u.id}" ${why ? "disabled" : ""}>${why ? cap(why) : "Recruit"}</button>
            ${price ? `<span class="cost">${costText(cost)}</span>` : ""}</div>`;
        }).join("");
        const hired = orders.filter((o) => o.type === "hire_mercenaries").reduce((a, o) => a + o.regiments, 0);
        const mercLeft = R.mercenaryLimit - hired, mercN = Math.max(1, Math.min(mercLeft, +(box.dataset.mercs || 4)));
        const mercCost = [mercN * R.mercenaryCost, 0, 0, 0, 0, 0];
        const mercWhy = mercLeft <= 0 ? "no more for hire this year" : !affordable(mercCost, t) ? "too costly" : "";
        const mercs = `<div class="levy merc"><span class="ic">💰</span>
            <div><b>Mercenaries</b><small>Landsknechte and Swiss pikes: ducats only, no manpower or iron; ${mercLeft} of ${R.mercenaryLimit} left this year</small></div>
            ${mercLeft > 0 ? stepper("mercs", mercN, mercLeft) : ""}
            <button class="btn" data-mercs ${mercWhy ? "disabled" : ""}>${mercWhy ? cap(mercWhy) : "Hire"}</button>
            <span class="cost">${costText(mercCost)}</span></div>`;
        body += `<section><h4>The garrison</h4><div class="units">${comp}</div>
          <p class="note">On ${esc(ground)} they defend with a strength of ${strength(now, ground, false).toFixed(1)}${mixed >= 3 ? `, and fight ${Math.round((R.combinedBonus[mixed] || R.combinedBonus[3]) * 100)}% harder for their combined arms` : ""}.</p></section>
          <section><h4>March</h4><div class="actions">
          <div class="row"><button class="btn" id="mixmode">${pickMix ? "Send a fair share instead" : "Choose regiments by kind"}</button></div>
          ${chooser}
          ${leader}
          ${here > 0 && marches ? `<div class="row">${marches}</div>` : `<p class="note">${here > 0 ? "No province to march to." : "No regiments here."}</p>`}
          <p class="note">Cavalry charges best on plains; every tenth of an attacking army in guns knocks a fort level off.</p></div></section>
          ${works ? `<section><h4>Levy</h4><div class="levies">${levy}${mercs}</div>` : `<section><p class="note">Occupied land: no levies here, only the regiments that hold it.</p>`}
          <div class="act">${stepper("disband", Math.max(1, +(box.dataset.disband || 1)), Math.max(here, 1))}
            <select class="field" id="disbandkind" aria-label="Which regiments to disband"><option value="">a fair share</option>${U.filter((u) => now[u.id]).map((u) => `<option value="${u.id}" ${box.dataset.disbandkind === u.id ? "selected" : ""}>${esc(u.id)}</option>`).join("")}</select>
            <button class="btn" data-act="disband" ${here > 0 ? "" : "disabled"}>Disband</button><span class="cost">returns ${costText(R.disband)} each</span></div>
          <p class="note">A pikeman eats ${R.grainUpkeep} grain and costs ${R.pay} ducats a year; cavalry eats and costs double, guns cost double.</p></section>`;
      }
    } else {
      map.setTargets([]); hint("");
      if (o >= 0) {
        const r = relation(p.owner), ruler = V.nations.find((n) => n.id === p.owner)?.ruler;
        const status = r.war ? `<span class="chip war">at war</span>` : r.alliance ? `<span class="chip">allied</span>` : r.pact ? `<span class="chip">non-aggression pact</span>` : r.truce ? `<span class="chip">truce</span>` : `<span class="chip">at peace</span>`;
        body += `<section class="relation"><span>${status} ${ruler ? `${esc(ruler.title)} ${esc(ruler.name)} reigns.` : ""}</span>
          <button class="btn" data-envoy="${p.owner}">✉ Envoys</button></section>`;
      }
      const near = [...P[i].land, ...P[i].sea].filter((j) => owned(j) && troopsAfter(j) > 0);
      if (near.length && p.troops !== null) {
        const best = near.sort((a, b) => troopsAfter(b) - troopsAfter(a))[0], g = generalAt(best);
        const chance = odds(best, i, armyAfter(best)) ?? 0;
        const war = p.owner === null || relation(p.owner).war;
        body += `<section><h4>Attack</h4><p class="note" style="font-style:normal">All ${troopsAfter(best)} regiments of ${esc(P[best].name)}${g ? ` under ${esc(g.name)}` : ""}
          against ${p.troops}: <b>${Math.round(chance * 100)}% to win</b>.
          ${war ? `Select ${esc(P[best].name)} and right-click here.` : `You must declare war on ${esc(N[o].name)} first.`}</p></section>`;
      }
      body += monumentCard(i, false, projected()) + info.production + `<section>${info.slotsHtml}</section>`;
    }
    const warNotes = [];
    if (p.controller) warNotes.push(`🏴 Occupied by ${esc(nameOf(p.controller))}: it yields nothing to ${p.owner === G.human ? "you" : esc(nameOf(p.owner))} until a peace says whose it is.`);
    if (p.siege_by) warNotes.push(`⚔ Besieged by ${p.siege_by === G.human ? "you" : esc(nameOf(p.siege_by))}: ${p.siege_years} year${p.siege_years === 1 ? "" : "s"} of siege won. Each level of wall holds out a year; guns knock levels off.`);
    const scroll = box.scrollTop;
    box.innerHTML = info.header + info.facts + (warNotes.length ? `<section class="warnotes">${warNotes.map((n) => `<p class="note war">${n}</p>`).join("")}</section>` : "") + body;
    box.scrollTop = scroll;
    box.classList.add("open");
    box.querySelector("[data-close]").onclick = () => { picked = -1; render(); };
    box.querySelectorAll("[data-dtab]").forEach((b) => b.onclick = () => { ownTab = b.dataset.dtab; deed(); });
    box.querySelectorAll("[data-envoy]").forEach((b) => b.onclick = () => { focus = nIndex[b.dataset.envoy]; tab = "diplomacy"; render(); });
    box.querySelectorAll(".stepper").forEach(wireStepper);
    const leadBox = box.querySelector("#lead"); if (leadBox) leadBox.onchange = () => { lead = leadBox.checked; deed(); };
    const mixButton = box.querySelector("#mixmode");
    if (mixButton) mixButton.onclick = () => { pickMix = pickMix ? null : Object.fromEntries(KINDS.map((k) => [k, armyAfter(i)[k]])); deed(); };
    const disbandKind = box.querySelector("#disbandkind"); if (disbandKind) disbandKind.onchange = () => { box.dataset.disbandkind = disbandKind.value; };
    box.querySelectorAll("[data-recruit]").forEach((b) => b.onclick = () => {
      const unit = b.dataset.recruit, n = Math.max(1, +(box.dataset[`recruit_${unit}`] || 1));
      queue({type: "recruit", province: P[i].id, regiments: n, unit});
    });
    box.querySelectorAll("[data-mercs]").forEach((b) => b.onclick = () =>
      queue({type: "hire_mercenaries", province: P[i].id, regiments: Math.max(1, +(box.dataset.mercs || 4))}));
    box.querySelectorAll("[data-monument]").forEach((b) => b.onclick = () => queue({type: "upgrade_monument", province: P[i].id}));
    box.querySelectorAll("[data-march]").forEach((b) => b.onclick = () => march(i, +b.dataset.march, b.dataset.kind));
    box.querySelectorAll("[data-act]").forEach((b) => b.onclick = () => {
      const id = P[i].id, act = b.dataset.act;
      if (act === "develop") queue({type: "develop", province: id});
      if (act === "improve") queue({type: "improve", province: id});
      if (act === "disband") {
        const unit = box.dataset.disbandkind || null, most = unit ? armyAfter(i)[unit] : troopsAfter(i);
        const order = {type: "disband", province: id, regiments: Math.min(+(box.dataset.disband || 1), most)};
        if (unit) order.unit = unit;
        if (order.regiments > 0) queue(order);
      }
      if (act === "hire") queue({type: "hire_general", province: id});
    });
    box.querySelectorAll("[data-build]").forEach((b) => b.onclick = () => queue({type: "build", province: P[i].id, building: b.dataset.build}));
  }
  function hint(text) { const h = $("hintbar"); h.textContent = text; h.classList.toggle("show", !!text); }
  function stepper(name, value, max, min = 1) {
    return `<span class="stepper" data-name="${name}" data-max="${max}" data-min="${min}"><button type="button" data-d="-1" aria-label="Fewer">−</button>
      <input type="number" min="${min}" max="${max}" value="${value}" aria-label="${name.replace("_", " ")}"><button type="button" data-d="1" aria-label="More">+</button></span>`;
  }
  function wireStepper(st) {
    const box = $("deed"), input = st.querySelector("input"), name = st.dataset.name, max = +st.dataset.max, min = +st.dataset.min;
    const set = (v) => { v = Math.max(min, Math.min(max, Number.isFinite(v) ? v : min)); input.value = v;
      if (name === "send") { send = v; deed(); }
      else if (name.startsWith("mix_")) { pickMix[name.slice(4)] = v; deed(); }
      else { box.dataset[name] = v; if (name.startsWith("recruit") || name === "mercs") deed(); } };
    st.querySelectorAll("button").forEach((b) => b.onclick = () => set(+input.value + +b.dataset.d));
    input.onchange = () => set(+input.value);
  }

  // ------------------------------------------------------------------ top bar
  function treasury() {
    const t = projected(), now = unbundle(V.me.resources), inc = unbundle(V.me.income_per_turn), up = unbundle(V.me.army_upkeep_per_turn);
    $("treasury").innerHTML = RES.map(([key, label, ic], k) => {
      const net = inc[k] - up[k];
      return `<div title="${label}: ${now[k]} in the treasury${t[k] !== now[k] ? `, ${t[k]} after this year's orders` : ""}; ${sign(net)} a year">
        <b>${ic} ${t[k]}</b><i class="${net < 0 ? "neg" : ""}">${sign(net)}</i>${key === "manpower" ? `<small>of ${V.me.manpower_cap}</small>` : ""}</div>`; }).join("") +
      `<div title="Stability multiplies ducat income (+${Math.round(R.stabilityBonus * 100)}% a point). Raising it costs ${stabilityCost()} ducats.">
        <b>⚖ ${sign(V.me.stability)}</b><button class="btn" id="stab" ${V.me.stability >= R.maxStability || !affordable([stabilityCost(), 0, 0, 0, 0]) || orders.some((o) => o.type === "boost_stability") ? "disabled" : ""}>raise</button></div>`;
    const FAITH_ICON = {catholic: "✝", protestant: "✠", orthodox: "☦", sunni: "☪"};
    $("treasury").insertAdjacentHTML("beforeend", `<div title="Prestige ${V.me.prestige} of 100: +${(V.me.prestige * 0.1).toFixed(1)}% ducats, cheaper stability. Your standing (development plus half your prestige) is ${V.me.standing}: it decides the winner when time runs out."><b>🏅 ${V.me.prestige}</b><i>prestige</i></div>
      <div title="Your realm is ${V.me.faith}. Courts of the same faith warm to you each year; of other faiths, they cool."><b>${FAITH_ICON[V.me.faith] || "✝"}</b><i>${V.me.faith}</i></div>`);
    if (V.me.war_exhaustion > 0) $("treasury").insertAdjacentHTML("beforeend", `<div title="War exhaustion: ${V.me.war_exhaustion.toFixed(1)} of 20. Each point costs 1% of ducat income; from 10, a point of stability every year. Peace heals it."><b class="${V.me.war_exhaustion >= 10 ? "neg" : ""}">🥀 ${V.me.war_exhaustion.toFixed(1)}</b><i>exhaustion</i></div>`);
    const b = $("stab"); if (b) b.onclick = () => queue({type: "boost_stability"});
  }

  // ------------------------------------------------------------------ offices
  // Courts whose regiments mass on your border: the war a ruler should see coming.
  function threats() {
    const out = [];
    for (const n of V.nations) {
      if (n.id === G.human || !n.alive) continue;
      const r = relation(n.id);
      if (r.alliance || r.truce) continue;
      let theirs = 0, ours = 0;
      const facing = new Set();
      for (const id of V.me.provinces) {
        const i = pIndex[id];
        const near = [...P[i].land, ...P[i].sea].filter((j) => prov(j).owner === n.id);
        if (!near.length) continue;
        ours += troopsAfter(i);
        near.forEach((j) => facing.add(j));
      }
      facing.forEach((j) => (theirs += prov(j).troops || 0));
      if (theirs >= 8 && theirs >= 1.5 * ours) out.push({nation: n.id, theirs, ours, war: !!r.war, pact: !!r.pact});
    }
    return out.sort((a, b) => b.theirs / Math.max(1, b.ours) - a.theirs / Math.max(1, a.ours));
  }
  const threatText = (t) => `${t.war ? "⚔" : "⚠"} ${esc(nameOf(t.nation))} masses ${t.theirs} regiments on your border; you have ${t.ours} facing them${t.pact ? " (a pact holds them, for now)" : t.war ? "" : ". War may come"}.`;
  // The European market: today's prices, and what you hold
  const marketQty = {};
  function marketHtml() {
    const t = projected(), held = Object.fromEntries(RES.map(([key], k) => [key, t[k]]));
    const icon = Object.fromEntries(RES.map(([key, , ic]) => [key, ic]));
    const queued = orders.filter((o) => o.type === "buy" || o.type === "sell");
    const rows = Object.entries(V.market).map(([res, p]) => {
      const n = marketQty[res] || 10, base = S.rules.marketBase[res], trend = p.price > base * 1.05 ? "▲" : p.price < base * 0.95 ? "▼" : "•";
      return `<tr><td>${icon[res]} ${cap(res)}</td><td title="Usual price ${base}">${p.price.toFixed(2)} <span class="trend ${trend === "▲" ? "up" : trend === "▼" ? "down" : ""}">${trend}</span></td>
        <td>${p.buy.toFixed(2)}</td><td>${p.sell.toFixed(2)}</td><td>${held[res]}</td>
        <td class="trade"><input type="number" class="field" min="1" max="200" value="${n}" data-qty="${res}" aria-label="How much ${res}">
          <button class="btn" data-buy="${res}" ${t[0] < Math.ceil(n * p.buy) ? "disabled" : ""} title="Costs ${Math.ceil(n * p.buy)} ducats">Buy</button>
          <button class="btn" data-sell="${res}" ${held[res] < n ? "disabled" : ""} title="Brings ${Math.floor(n * p.sell)} ducats">Sell</button></td></tr>`;
    }).join("");
    return `<h4>The European market</h4><table class="grid num market"><thead><tr><th></th><th>Price</th><th>Buy</th><th>Sell</th><th>Yours</th><th></th></tr></thead><tbody>${rows}</tbody></table>
      ${queued.length ? `<p class="sub">This year: ${queued.map((o) => `${o.type} ${o.amount} ${o.resource}`).join(", ")}.</p>` : ""}
      <p class="sub">Trades happen first, so what you buy can be spent this year. What all Europe buys and sells moves next year's prices; the merchants keep ${Math.round(R.marketSpread * 100)}%.</p>`;
  }
  const TAX_WORDS = ["Very low", "Low", "Normal", "High", "Very high"];
  const taxNow = () => { const o = orders.find((x) => x.type === "set_taxes"); return o ? o.level : V.me.tax; };
  function realmTab() {
    const inc = unbundle(V.me.income_per_turn), now = unbundle(V.me.resources), after = projected();
    const mine = V.me.provinces.map((id) => pIndex[id]);
    const keyIdx = Object.fromEntries(RES.map(([key], k) => [key, k]));
    // the ledger, from the engine: every source of income and expense this year
    const net = RES.map(() => 0);
    const ledgerRows = ["income", "expense"].map((kind) => V.me.ledger.filter((l) => l.kind === kind).map((l) => {
      const cells = RES.map(([key], k) => { const v = l.amount[key] || 0; net[k] += kind === "income" ? v : -v;
        return `<td class="${!v ? "" : kind === "income" ? (v > 0 ? "pos" : "neg") : "neg"}">${v ? (kind === "income" ? sign(v) : "−" + v) : ""}</td>`; }).join("");
      return `<tr><td>${kind === "income" ? "＋" : "－"} ${esc(cap(l.source))}</td>${cells}</tr>`; }).join("")).join("");
    // what you have, and how long it lasts
    const cards = RES.map(([key, label, ic], k) => {
      const n = net[k], left = n < 0 && now[k] > 0 ? Math.floor(now[k] / -n) : null;
      const note = n < 0 ? (now[k] + n < 0 ? "runs out this year" : `lasts ${left} year${left === 1 ? "" : "s"}`) : n > 0 ? "growing" : "steady";
      const cap = key === "manpower" ? `<i class="bar"><b style="width:${Math.min(100, Math.round(100 * now[k] / V.me.manpower_cap))}%"></b></i><small>pool of ${V.me.manpower_cap}</small>` : "";
      return `<div class="stock ${n < 0 ? "falling" : ""}"><span class="ic">${ic}</span><div><b class="num">${now[k]}${after[k] !== now[k] ? ` <small>→ ${after[k]}</small>` : ""}</b>
        <span class="label">${label}</span></div><div class="flow"><b class="num ${n < 0 ? "neg" : n > 0 ? "pos" : ""}">${sign(n)}</b><small>${note}</small></div>${cap}</div>`; }).join("");
    // taxes
    const tax = taxNow(), taxable = V.me.ledger.filter((l) => l.kind === "income" && l.source !== "the crown's modifiers").reduce((a, l) => a + (l.amount.ducats || 0), 0);
    const men = V.me.ledger.filter((l) => l.kind === "income").reduce((a, l) => a + (l.amount.manpower || 0), 0);
    const delta = Math.round(taxable * R.taxIncomeStep * (tax - V.me.tax)), mdelta = -Math.round(men * R.taxManpowerStep * (tax - V.me.tax));
    const risk = R.taxChance[Math.abs(tax)] || 0;
    const taxes = `<div class="taxes"><div class="taxhead"><b>Taxes: ${TAX_WORDS[tax + 2]}</b>${tax !== V.me.tax ? `<span class="chip">from next year</span>` : ""}</div>
      <input type="range" id="taxrange" min="-2" max="2" step="1" value="${tax}" aria-label="Tax level">
      <div class="taxticks">${TAX_WORDS.map((w) => `<span>${w}</span>`).join("")}</div>
      <ul class="effects">
        <li>${sign(Math.round(R.taxIncomeStep * 100 * tax))}% ducats from the land${delta ? ` <b class="${delta > 0 ? "pos" : "neg"}">(${sign(delta)} a year)</b>` : ""}</li>
        <li>${sign(Math.round(-R.taxManpowerStep * 100 * tax))}% manpower${mdelta ? ` <b class="${mdelta > 0 ? "pos" : "neg"}">(${sign(mdelta)} a year)</b>` : ""}</li>
        <li>raising stability ${tax >= 0 ? `${Math.round(R.taxStabilityStep * 100 * tax)}% dearer` : `${Math.round(-R.taxStabilityStep * 100 * tax)}% cheaper`}</li>
        <li>${tax > 0 ? `a ${Math.round(risk * 100)}% chance a year of losing a point of stability` : tax < 0 ? `a ${Math.round(risk * 100)}% chance a year of gaining a point of stability` : "no unrest from taxes"}</li>
      </ul></div>`;
    // the flows of each material: who makes it, who eats it
    const flows = ["grain", "iron", "timber", "goods"].map((key) => {
      const k = keyIdx[key];
      const makers = mine.map((i) => [i, unbundle(prov(i).output_per_turn)[k]]).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
      const eaters = {};
      mine.forEach((i) => prov(i).buildings.forEach((b) => { const c = (B[bIndex[b]].consumes || [])[k]; if (c) { eaters[b] = eaters[b] || [0, 0]; eaters[b][0] += 1; eaters[b][1] += c; } }));
      const army = (V.me.ledger.find((l) => l.source === "the army")?.amount[key]) || 0;
      const made = inc[k], eaten = Object.values(eaters).reduce((a, [, c]) => a + c, 0) + army;
      const idle = mine.flatMap((i) => prov(i).idle.filter((b) => (B[bIndex[b]].consumes || [])[k]).map((b) => `${B[bIndex[b]].name.toLowerCase()} in ${esc(P[i].name)}`));
      const price = V.market[key]?.buy;
      const gap = made - eaten;
      const advice = gap < 0 ? `Short ${-gap} a year${price ? `: about ${Math.ceil(-gap * price)} ducats on the market` : ""}${now[k] > 0 ? `, or ${Math.floor(now[k] / -gap)} years from the stores` : ""}.` : gap > 20 ? `A surplus of ${gap} a year: sell it, or build what eats it.` : "";
      return `<div class="flowcard"><div class="fhead"><span class="ic">${RES[k][2]}</span><b>${RES[k][1]}</b><span class="num ${gap < 0 ? "neg" : "pos"}">${sign(gap)} a year</span></div>
        <div class="fcols"><div><small>Made, ${made}</small>${makers.slice(0, 4).map(([i, v]) => `<div>${esc(P[i].name)} <b class="num">${v}</b></div>`).join("")}${makers.length > 4 ? `<div class="sub">and ${makers.length - 4} more</div>` : ""}</div>
        <div><small>Eaten, ${eaten}</small>${army ? `<div>the army <b class="num">${army}</b></div>` : ""}${Object.entries(eaters).map(([b, [n, c]]) => `<div>${n} ${esc(B[bIndex[b]].name.toLowerCase())} <b class="num">${c}</b></div>`).join("")}${!army && !Object.keys(eaters).length ? `<div class="sub">nothing</div>` : ""}</div></div>
        ${idle.length ? `<p class="warn">Idle last year: ${idle.join(", ")}.</p>` : ""}${advice ? `<p class="sub">${advice}</p>` : ""}</div>`; }).join("");
    const short = [];
    if (now[3] + net[3] < 0) short.push("Your granaries will not feed the army next year: some regiments will desert.");
    if (now[0] + net[0] < 0) short.push("The treasury cannot pay the army next year: some regiments will desert.");
    const table = mine.sort((a, b) => prov(b).development - prov(a).development).map((i) => {
      const p = prov(i), out = unbundle(p.output_per_turn);
      return `<tr class="click" data-p="${i}"><td>${PaxMap.goodOf(S, P[i].good).icon} ${esc(P[i].name)}${p.is_capital ? " ★" : ""}${p.unrest ? " 🔥" : ""}</td><td>${p.development}</td>
        <td>${p.buildings.length}/${p.building_slots}</td><td>${"●".repeat(p.workings || 0) || "·"}</td>${out.map((v) => `<td>${v}</td>`).join("")}</tr>`; }).join("");
    return `<div class="pad"><h4>What you have</h4><div class="stocks">${cards}</div>
      ${short.map((x) => `<p class="warn">${x}</p>`).join("")}
      ${threats().map((t) => `<p class="warn">${threatText(t)}</p>`).join("")}
      <h4>Taxes</h4>${taxes}
      <h4>The year's ledger</h4>
      <table class="grid num ledger-table"><thead><tr><th></th>${RES.map(([, label, ic]) => `<th title="${label}">${ic}</th>`).join("")}</tr></thead>
        <tbody>${ledgerRows}<tr class="netrow"><td>Net</td>${net.map((v) => `<td class="${v < 0 ? "neg" : v > 0 ? "pos" : ""}">${sign(v)}</td>`).join("")}</tr></tbody></table>
      <p class="sub">“The crown's modifiers” are stability, technology, the ruler, the council, prestige, taxes and war exhaustion; hover the realm's bonuses in the Crown tab.</p>
      <h4>Materials</h4><div class="flows">${flows}</div>
      ${marketHtml()}
      <h4>Provinces</h4>
      <table class="grid num"><thead><tr><th>Province</th><th>Dev.</th><th>Bldg.</th><th title="Workings">⛏</th>${RES.map(([, label, ic]) => `<th title="${label}">${ic}</th>`).join("")}</tr></thead><tbody>${table}</tbody></table>
      <p class="sub">★ capital. 🔥 in unrest: a conquered province yields nothing for a few years.</p></div>`;
  }
  function armyTab() {
    const mine = V.me.provinces.map((id) => pIndex[id]);
    const options = (sel) => mine.map((i) => `<option value="${P[i].id}" ${i === sel ? "selected" : ""}>${esc(P[i].name)}</option>`).join("");
    const up = V.me.army_upkeep_per_turn, men = V.me.resources.manpower, capMen = V.me.manpower_cap;
    const hired = orders.filter((o) => o.type === "hire_mercenaries").reduce((a, o) => a + o.regiments, 0);
    const kinds = U.map((u) => `<div class="unit ${V.me.army[u.id] ? "" : "none"}" title="${esc(u.name)}: ${esc(u.role)}"><span class="ic">${UICON[u.id]}</span><b>${V.me.army[u.id]}</b><small>${esc(u.id)}</small></div>`).join("");
    const power = V.me.modifiers.battle_power;
    const summary = `<div class="stocks">
        <div class="stock"><span class="ic">⚔</span><div><b class="num">${V.me.regiments}</b><span class="label">regiments</span></div><div class="flow"><b class="num neg">−${up.ducats}</b><small>ducats a year</small></div></div>
        <div class="stock"><span class="ic">👥</span><div><b class="num">${men}</b><span class="label">manpower of ${capMen}</span></div><div class="flow"><b class="num">${sign(V.me.income_per_turn.manpower)}</b><small>a year</small></div>
          <i class="bar"><b style="width:${Math.min(100, Math.round(100 * men / Math.max(1, capMen)))}%"></b></i></div>
        <div class="stock"><span class="ic">🌾</span><div><b class="num">${up.grain}</b><span class="label">grain eaten a year</span></div><div class="flow"><b class="num">${sign(V.me.income_per_turn.grain - up.grain)}</b><small>net</small></div></div>
        <div class="stock"><span class="ic">💪</span><div><b class="num">${sign(Math.round(power * 100))}%</b><span class="label">battle power</span></div><div class="flow"><small>${V.me.modifiers.navy ? "a navy: straits favour no one" : "technology, ruler, council"}</small></div></div>
        <div class="stock"><span class="ic">💰</span><div><b class="num">${R.mercenaryLimit - hired}</b><span class="label">mercenaries for hire</span></div><div class="flow"><small>${R.mercenaryCost} ducats each</small></div></div>
      </div><div class="units office-units">${kinds}</div>`;
    // the fronts: each war, and every border where a court masses more than you
    const fronts = V.me.wars.map((w) => {
      const held = V.provinces.filter((p) => p.owner === w.enemy && p.controller === G.human).length;
      const lost = V.provinces.filter((p) => p.owner === G.human && p.controller === w.enemy).length;
      return `<div class="front war"><div class="row"><b>⚔ ${esc(nameOf(w.enemy))}</b>${scoreBar(w.war_score)}<span class="num">${sign(w.war_score)}</span></div>
        <small>${w.attacks_allowed_from_turn > V.turn ? `mobilising until ${yearOf(w.attacks_allowed_from_turn)}; ` : ""}you hold ${held} of theirs, they hold ${lost} of yours; battles ${w.battles_won} won, ${w.battles_lost} lost.</small></div>`; }).join("")
      + threats().filter((t) => !t.war).map((t) => `<div class="front"><b>⚠ ${esc(nameOf(t.nation))}</b><small>${t.theirs} regiments on your border against your ${t.ours}${t.pact ? "; a pact holds them" : ""}.</small></div>`).join("");
    // every army: what it is made of, who leads it, and the best blow it could strike
    const rows = mine.filter((i) => troopsAfter(i) > 0).sort((a, b) => troopsAfter(b) - troopsAfter(a)).map((i) => {
      const g = generalAt(i), a = armyAfter(i);
      const blows = targetsFrom(i).filter(([, k]) => k === "attack").map(([j]) => [j, odds(i, j)]).filter(([, c]) => c !== null).sort((x, y) => y[1] - x[1]);
      const best = blows[0];
      return `<tr class="click" data-p="${i}"><td>${esc(P[i].name)}${prov(i).is_capital ? " ★" : ""}</td><td>${troopsAfter(i)}</td>
        <td class="mix">${KINDS.filter((k) => a[k]).map((k) => `${UICON[k]}${a[k]}`).join(" ")}</td><td>${g ? `⚑ ${stars(g.skill)}` : ""}</td>
        <td>${best ? `<span class="${best[1] >= .6 ? "pos" : best[1] < .4 ? "neg" : ""}">${esc(P[best[0]].name)} ${Math.round(best[1] * 100)}%</span>` : ""}</td></tr>`; }).join("");
    const generals = V.me.generals.map((g) => {
      const goes = generalPositions().get(g.id), from = pIndex[g.province];
      const plan = goes === from ? "" : goes === -1 ? ", leading an attack" : `, going to ${esc(P[goes].name)}`;
      return `<div class="general-card"><span class="stars" title="Skill ${g.skill} of 3: +${Math.round(R.generalBonus * 100 * g.skill)}% battle power">${stars(g.skill)}</span>
        <div><b>${esc(g.name)}</b> <span class="sub">in ${esc(P[from].name)}${plan}</span>
        <div class="row"><select class="field" data-gsel="${g.id}" aria-label="Send ${esc(g.name)} to">${options(pIndex[g.province])}</select>
        <button class="btn" data-assign="${g.id}">Send</button><button class="btn" data-goto="${pIndex[g.province]}">Show</button></div></div></div>`; }).join("");
    // what each kind of regiment costs and where it can be raised
    const where = (u) => u.requires < 0 ? "anywhere" : mine.filter((i) => prov(i).buildings.includes(B[u.requires].id)).map((i) => esc(P[i].name)).join(", ") || `nowhere yet: build ${B[u.requires].name.toLowerCase()}`;
    const book = U.map((u) => `<tr><td>${UICON[u.id]} ${esc(u.name)}</td><td>${u.attack}/${u.defence}</td><td>${costText(u.cost)}</td><td>${u.pay} 💰 ${u.rations} 🌾</td><td class="left">${where(u)}</td></tr>`).join("");
    return `<div class="pad"><h4>The army</h4>${summary}
      <h4>Fronts</h4>${fronts || `<p class="muted">No war, and no court masses troops against you.</p>`}
      <h4>Armies</h4><table class="grid num"><thead><tr><th>Province</th><th>Regiments</th><th>Kinds</th><th>General</th><th>Best attack</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="sub">Click an army to select it, then right-click on the map where it should go. The odds count what you can see.</p>
      <h4>Generals, ${V.me.generals.length} of ${V.me.modifiers.max_generals}</h4>${generals || `<p class="muted">No general serves you.</p>`}
      ${V.me.generals.length < V.me.modifiers.max_generals ? `<div class="row"><select class="field" id="hireat" aria-label="Appoint a general in">${options(pIndex[V.me.capital])}</select>
        <button class="btn" id="hire" ${affordable(R.generalCost) ? "" : "disabled"}>Appoint a general</button><span class="sub">${costText(R.generalCost)}</span></div>` : ""}
      <p class="sub">A general adds ${Math.round(R.generalBonus * 100)}% battle power per star to the regiments he leads or defends with. He falls if his province is taken.</p>
      <h4>The regiments of the age</h4><table class="grid num units-book"><thead><tr><th>Kind</th><th>Att/Def</th><th>Cost</th><th>A year</th><th class="left">Raised in</th></tr></thead><tbody>${book}</tbody></table>
      <p class="sub">Two or more kinds, each a fifth of an army, fight harder together. Every tenth of an attacking army in guns knocks a fort level off.</p></div>`;
  }
  const BRANCH_IC = {military: "⚔", economy: "💰", engineering: "⚒"};
  function techTab() {
    const doing = researching();
    const net = V.me.income_per_turn.ducats - V.me.army_upkeep_per_turn.ducats - V.me.inputs_per_turn.ducats;
    const yearsFor = (cost) => { const short = Math.max(0, cost.ducats - V.me.resources.ducats);
      return !short ? "affordable now" : net > 0 ? `in about ${Math.ceil(short / net)} year${Math.ceil(short / net) === 1 ? "" : "s"}` : "not on this income"; };
    const cards = T.map((b) => {
      const level = V.me.technology[b.id], cost = V.me.research_costs[b.id], next = b.levels[level];
      const word = b.id === "engineering" ? "cheaper buildings and development" : b.id === "economy" ? "ducats and grain" : "battle power";
      const unlocked = next ? B.filter((x) => x.tech && x.tech[0] === b.id && x.tech[1] === level + 1) : [];
      const busy = doing && doing.branch === b.id;
      return `<div class="studycard ${busy ? "doing" : ""}"><div class="shead"><span class="ic">${BRANCH_IC[b.id]}</span><b>${b.name}</b><span class="num">${level} / ${R.maxTech}</span></div>
        <i class="bar"><b style="width:${Math.round(100 * level / R.maxTech)}%"></b></i>
        <p class="sub">Now: +${Math.round(b.perLevel * 100 * level)}% ${word}.${next ? ` Next: +${Math.round(b.perLevel * 100 * (level + 1))}%.` : ""}</p>
        ${next ? `<p><b>${esc(next.name)}</b>: ${esc(next.unlocks)}${unlocked.length ? ` <span class="chips">${unlocked.map((x) => `<span class="chipb">${BICON[x.id]} ${esc(x.name)}</span>`).join("")}</span>` : ""}</p>
          ${next.lore ? `<p class="lore">${esc(next.lore)}</p>` : ""}
          <div class="act">${busy ? `<span class="ok">Researching this year</span>` : `<button class="btn" data-research="${b.id}" ${doing || !cost || !affordable(unbundle(cost)) ? "disabled" : ""}>Research</button>`}
            ${cost ? `<span class="cost">${costText(unbundle(cost))}, ${yearsFor(cost)}</span>` : ""}</div>` : `<p class="ok">Mastered.</p>`}</div>`;
    }).join("");
    const columns = T.map((b) => {
      const level = V.me.technology[b.id];
      const nodes = b.levels.map((step, k) => {
        const n = k + 1, done = n <= level, nxt = n === level + 1;
        const state = done ? "done" : nxt ? (doing && doing.branch === b.id ? "doing" : "next") : "locked";
        return `<div class="node ${state}" title="${esc(step.name)}: ${esc(step.unlocks)}. ${esc(step.lore || "")}"><div class="lvl">${done ? "✓" : n}</div><b>${esc(step.name)}</b>
          <div class="unl">${esc(cap(step.unlocks))}</div></div>`;
      }).join(`<div class="link"></div>`);
      return `<div class="branch"><h5>${BRANCH_IC[b.id]} ${b.name}<small>${level} of ${R.maxTech}</small></h5>${nodes}</div>`;
    }).join("");
    // where you stand against every other court, branch by branch
    const courts = [{id: G.human, name: V.me.name, technology: V.me.technology}, ...V.nations.filter((n) => n.alive)];
    const race = T.map((b) => `<div class="race"><h5>${BRANCH_IC[b.id]} ${b.name}</h5>${courts.sort((x, y) => y.technology[b.id] - x.technology[b.id]).map((n) =>
      `<div class="raceline ${n.id === G.human ? "me" : ""}"><span>${esc(n.name)}</span><i><b style="width:${Math.round(100 * n.technology[b.id] / R.maxTech)}%;background:${N[nIndex[n.id]].color}"></b></i><span class="num">${n.technology[b.id]}</span></div>`).join("")}</div>`).join("");
    const helpers = [V.me.modifiers.research_discount ? `research ${Math.round(V.me.modifiers.research_discount * 100)}% cheaper (council, observatory, scholars)` : "a chancellor, an observatory or a scholar on the throne would make research cheaper"];
    return `<div class="pad"><h4>Learning</h4>
      <p class="sub">One research a year: ${doing ? `this year, ${esc(T.find((b) => b.id === doing.branch).name)}.` : "nothing chosen yet."} ${cap(helpers.join(""))}.</p>
      <div class="studies">${cards}</div>
      <h4>The race of learning</h4><div class="races">${race}</div>
      <h4>The tree</h4><div class="tree">${columns}</div></div>`;
  }
  const portrait = (person, color, size) => PaxMap.portrait(person, color, size);
  const traitChips = (traits) => (traits || []).length ? `<div class="chips">${traits.map((t) =>
    `<span class="chip trait" title="${esc(S.traits[t] || "")}">${esc(t)}</span>`).join("")}</div>` : "";
  const temperChip = (p) => p ? `<span class="chip temper ${p}" title="${esc(S.personalities[p] || "")}">${esc(p)}</span>` : "";
  // What the seated advisors would say this year, each in their own temper. AI advisors will
  // replace these rules of thumb; the seats and the words are already theirs.
  function councilAdvice() {
    const out = [], adv = V.me.advisors, net = V.me.income_per_turn.ducats - V.me.army_upkeep_per_turn.ducats;
    if (adv.treasurer) {
      const t = adv.treasurer, previews = G.previews || {};
      let best = null;
      for (const [pid, pv] of Object.entries(previews))
        for (const [kind, gain] of Object.entries(pv.buildings || {})) {
          const b = B[bIndex[kind]], p = prov(pIndex[pid]);
          if (!gain.ducats || p.buildings.length >= p.building_slots || (b.tech && V.me.technology[b.tech[0]] < b.tech[1]) || b.requires >= 0) continue;
          if (!best || gain.ducats > best[2]) best = [pid, b, gain.ducats];
        }
      let text = net < 0 ? `We spend ${-net} ducats a year more than we take in. Cut the army or raise the taxes of trade.`
        : `We take in ${V.me.income_per_turn.ducats} ducats and keep ${net} after the army.`;
      if (best && t.personality !== "frugal") text += ` A ${best[1].name.toLowerCase()} in ${P[pIndex[best[0]]].name} would bring ${best[2]} more a year.`;
      if (t.personality === "frugal") text += " Keep the coffers full; a war is coming, there is always a war coming.";
      if (t.personality === "schemer") text += " And a little for the treasurer's trouble would not go amiss.";
      out.push([t, "treasurer", text]);
    }
    if (adv.marshal) {
      const m = adv.marshal, danger = threats()[0];
      let text = danger ? `${nameOf(danger.nation)} has ${danger.theirs} regiments on our border against our ${danger.ours}. Reinforce, or buy time with a pact.`
        : `${V.me.regiments} regiments, and the borders hold.`;
      const weak = V.provinces.filter((p) => p.owner !== G.human && p.troops !== null && p.troops <= 2
        && (p.owner === null || relation(p.owner).war) && [...p.neighbors, ...p.sea_neighbors].some((x) => owned(pIndex[x])));
      if (m.personality === "hawk" && weak.length) text += ` ${weak[0].name} has only ${weak[0].troops} regiments: it is ours for the taking.`;
      else if (!V.me.army.cavalry && V.provinces.some((p) => p.owner === G.human && p.buildings.includes("stables"))) text += " Raise horse where we have stables: they win on open ground.";
      if (m.personality === "dove") text += " But every battle avoided is a regiment saved.";
      out.push([m, "marshal", text]);
    }
    if (adv.chancellor) {
      const c = adv.chancellor, courts = V.nations.filter((n) => n.alive);
      const hater = courts.reduce((a, n) => (!a || n.opinion_of_you < a.opinion_of_you ? n : a), null);
      const friend = courts.reduce((a, n) => (!a || n.opinion_of_you > a.opinion_of_you ? n : a), null);
      const rivalsOfUs = courts.filter((n) => n.stances[G.human] === "rival").map((n) => n.name);
      let text = rivalsOfUs.length ? `${rivalsOfUs.join(" and ")} name${rivalsOfUs.length > 1 ? "" : "s"} us rival. ` : "";
      text += friend && friend.opinion_of_you > 10 ? `${friend.name} thinks well of us (${sign(friend.opinion_of_you)}): an alliance is within reach.`
        : "No court loves us yet; a gift opens doors.";
      if (hater && hater.opinion_of_you < -20) text += ` Beware ${hater.name} (${hater.opinion_of_you}).`;
      if (c.personality === "dove" && V.me.wars.length) text += " Seek peace while it is cheap.";
      if (c.personality === "visionary") text += " Think of Europe in twenty years, Majesty, not of next spring.";
      out.push([c, "chancellor", text]);
    }
    return out;
  }
  function pips(n, max = 6) { return `<span class="statpips">${Array.from({length: max}, (_, k) => `<i class="${k < n ? "on" : ""}"></i>`).join("")}</span>`; }
  function missionsHtml() {
    const ms = V.me.missions || [];
    if (!ms.length) return `<p class="muted">This crown has no ambitions of its own.</p>`;
    const order = {open: 0, locked: 1, done: 2};
    return `<div class="missions">${[...ms].sort((a, b) => order[a.status] - order[b.status]).map((m) => {
      const after = m.after ? ms.find((x) => x.id === m.after) : null;
      const goals = m.goals.map((g) => `<li class="${g.have >= g.need ? "met" : ""}"><span>${g.have >= g.need ? "✓" : "○"} ${esc(g.text)}</span>
        ${g.need > 1 ? `<i class="bar"><b style="width:${Math.round(100 * g.have / g.need)}%"></b></i><small class="num">${g.have}/${g.need}</small>` : ""}</li>`).join("");
      return `<div class="mission ${m.status}"><div class="mhead"><span class="ic">${m.status === "done" ? "🏆" : m.status === "locked" ? "🔒" : "🎯"}</span>
        <b>${esc(m.title)}</b></div>
        ${m.status === "done" ? "" : `<p class="lore">${esc(m.lore)}</p><ul class="goals">${goals}</ul>`}
        <div class="sub">${m.status === "locked" && after ? `After “${esc(after.title)}”. ` : ""}${m.status === "done" ? "Fulfilled: " : "Reward: "}${esc(m.reward)}</div></div>`;
    }).join("")}</div><p class="sub">A mission is fulfilled by itself at the end of a year in which all its goals hold.</p>`;
  }
  function crownTab() {
    const ruler = V.me.ruler, color = N[me].color;
    const reign = ruler ? R.startYear + ruler.since - 1 : 0;
    const rulerHtml = ruler ? `<div class="throne">${portrait(ruler, color, 96)}
      <div><b>${esc(ruler.title)} ${esc(ruler.name)}</b><div class="sub">Aged ${ruler.age}, reigning since ${reign}.</div>
        ${ruler.bio ? `<p class="lore">${esc(ruler.bio)}</p>` : ""}
        ${traitChips(ruler.traits)}
        <div class="stat"><span>Administration</span>${pips(ruler.administration)}<small>+${Math.round(R.rulerIncome * 100 * ruler.administration)}% ducats</small></div>
        <div class="stat"><span>Diplomacy</span>${pips(ruler.diplomacy)}<small>stability ${Math.round(Math.min(.8, R.rulerStability * ruler.diplomacy) * 100)}% cheaper${ruler.diplomacy >= 5 ? ", betrayal costs less" : ""}</small></div>
        <div class="stat"><span>Military</span>${pips(ruler.military)}<small>+${Math.round(R.rulerBattle * 100 * ruler.military)}% battle power</small></div></div></div>
      <p class="sub">Rulers age a year each turn; past forty, death draws nearer. The heir's talents are a gamble, and a new reign costs a point of stability.</p>`
      : `<p class="muted">An empty throne.</p>`;
    const hiring = new Set(orders.filter((o) => o.type === "hire_advisor").map((o) => V.me.advisor_candidates.find((c) => c.id === o.candidate)?.role));
    const seats = S.advisors.map((role) => {
      const sitting = V.me.advisors[role.id];
      const offers = V.me.advisor_candidates.filter((c) => c.role === role.id);
      const dismissed = orders.some((o) => o.type === "dismiss_advisor" && o.role === role.id);
      const head = sitting ? `<div class="seat-who">${portrait(sitting, mix(color, "#efe2c2", .5), 48)}
          <div><b>${esc(sitting.name)}</b> <span class="stars">${stars(sitting.skill)}</span> ${temperChip(sitting.personality)}
          <div class="sub">${esc(role.effect.replace("per star", `× ${sitting.skill}`))}; paid ${R.advisorSalary * sitting.skill} ducats a year.</div>
          <button class="btn" data-dismiss="${role.id}" ${dismissed ? "disabled" : ""}>${dismissed ? "Leaving" : "Dismiss"}</button></div></div>`
        : `<div class="seat-who empty"><div class="vacant">?</div><div><b>The seat is empty</b><div class="sub">${esc(role.effect)}.</div></div></div>`;
      const list = offers.map((c) => `<div class="offer"><span>${esc(c.name)} <span class="stars">${stars(c.skill)}</span> ${temperChip(c.personality)}</span>
        <span class="sub">${c.hire_cost} ducats, then ${c.salary} a year</span>
        <button class="btn" data-hire="${c.id}" ${hiring.has(role.id) || !affordable([c.hire_cost, 0, 0, 0, 0]) ? "disabled" : ""}>${hiring.has(role.id) && orders.some((o) => o.candidate === c.id) ? "Summoned" : "Hire"}</button></div>`).join("");
      return `<div class="seat"><h5>${role.name}</h5>${head}${list ? `<div class="sub" style="margin-top:6px">Seeking a place at court:</div>${list}` : ""}</div>`;
    }).join("");
    const enjoys = V.me.modifiers.sources.map((line) => `<li>${esc(line)}</li>`).join("");
    const counsel = councilAdvice();
    const proclaimed = orders.find((o) => o.type === "proclaim");
    const patron = orders.some((o) => o.type === "patronize");
    const patronWhy = patron ? "ordered this year" : V.me.prestige >= 100 ? "prestige is at its height" : !affordable([V.me.patronage_cost, 0, 0, 0, 0, 0]) ? "too costly for now" : "";
    const patronage = `<div class="card ${patronWhy ? "blocked" : "ready"}"><div class="cardhead"><span class="ic">🎨</span><div><b>Patronage</b>
        <div class="gain"><span>+${R.patronagePrestige} prestige</span></div></div></div>
      <p class="note">Painters, chapels, feasts and alms. Prestige ${V.me.prestige}: +${(V.me.prestige * 0.1).toFixed(1)}% ducats, and half of it counts in the final standing. Dearer the more you have; once a year.</p>
      <div class="act"><button class="btn" id="patronize" ${patronWhy ? "disabled" : ""}>${patronWhy ? cap(patronWhy) : "Patronise the arts"}</button><span class="cost">${V.me.patronage_cost} ducats</span></div></div>`;
    return `<div class="pad"><h4>Ambitions</h4>${missionsHtml()}
      <h4>Glory</h4>${patronage}
      <h4>The crown</h4>${rulerHtml}
      <h4>The council speaks</h4>${counsel.length ? counsel.map(([who, role, text]) => `<div class="counsel">${portrait(who, mix(color, "#efe2c2", .5), 34)}
        <div><b>${esc(who.name)}</b>, your ${role}: <q>${esc(text)}</q></div></div>`).join("") : `<p class="muted">An empty council gives no counsel. Hire advisors below.</p>`}
      <h4>The council</h4><div class="council">${seats}</div>
      <p class="sub">New candidates come to court every ${R.advisorYears} years. Unpaid advisors leave.</p>
      <h4>Speak to all Europe</h4>
      ${proclaimed ? `<p class="sub">This year you proclaim: <q>${esc(proclaimed.text)}</q></p>` : `<textarea id="proclamation" maxlength="400" placeholder="A proclamation every court will read: a claim, a warning, a promise."></textarea>
      <div class="row"><button class="btn" id="proclaim">Proclaim</button></div>`}
      <h4>What your realm enjoys</h4><ul class="enjoys">${enjoys || "<li>Nothing yet: research, a council and a gifted ruler all add here.</li>"}</ul></div>`;
  }
  function chipsFor(nid) {
    const r = relation(nid), year = (turn) => R.startYear + turn - 1, out = [];
    if (r.war) out.push(`<span class="chip war">at war since ${year(r.war.since_turn)}${r.war.attacks_allowed_from_turn > V.turn ? ", mobilising" : ""}</span>`);
    if (r.alliance) out.push(`<span class="chip ally">allied</span>`);
    if (r.pact) out.push(`<span class="chip pact">pact until ${year(r.pact.until_turn)}</span>`);
    if (r.truce) out.push(`<span class="chip truce">truce until ${year(r.truce.until_turn)}</span>`);
    if (r.marriage) out.push(`<span class="chip ally" title="A royal marriage: both courts warm every year">💍 married</span>`);
    r.leagues.forEach((x) => out.push(`<span class="chip league" title="A defensive league: attack one, fight both">⚔ leagued against ${esc(nameOf(x))}</span>`));
    return out.join("");
  }
  // ------------------------------------------------------------------ diplomacy: the courts of Europe
  const attitude = (v) => v >= 50 ? ["friendly", "Friendly"] : v >= 20 ? ["cordial", "Cordial"] : v > -20 ? ["neutral", "Neutral"]
    : v > -50 ? ["wary", "Wary"] : ["hostile", "Hostile"];
  const opinionBadge = (v, label = "") => { const [cls, word] = attitude(v);
    return `<span class="mood ${cls}" title="${label}${sign(v)} of 100">${word} ${sign(v)}</span>`; };
  let countering = null; // a proposal being answered with a counter-offer
  function termsText(p, from) {
    // From the sender's side: `give` is what the sender pays. Written for the human reader.
    const mineToo = from === G.human, other = p.target || p.recipient;
    const sender = mineToo ? "you" : esc(nameOf(from)), receiver = mineToo ? esc(nameOf(other)) : "you";
    const does = (who, verb) => `${who} ${who === "you" ? verb : verb + "s"}`;
    const names = (ids) => ids.map((x) => esc(P[pIndex[x]].name)).join(", "), years = R.tributeYears, parts = [];
    const give = costText(unbundle(p.give)), ask = costText(unbundle(p.receive));
    if (give !== "nothing") parts.push(`${does(sender, "pay")} ${give}`);
    if (ask !== "nothing") parts.push(`${does(receiver, "pay")} ${ask}`);
    if ((p.cede || []).length) parts.push(`${does(sender, "cede")} ${names(p.cede)}`);
    if ((p.demand || []).length) parts.push(`${does(receiver, "cede")} ${names(p.demand)}`);
    if (p.pay_tribute) parts.push(`${does(sender, "pay")} ${p.pay_tribute} ducats a year for ${years} years`);
    if (p.ask_tribute) parts.push(`${does(receiver, "pay")} ${p.ask_tribute} ducats a year for ${years} years`);
    if (p.limit_army !== null && p.limit_army !== undefined) parts.push(`${does(receiver, "keep")} no more than ${p.limit_army} regiments during the truce`);
    return parts.join("; ");
  }
  function proposalCard(p) {
    const from = esc(nameOf(p.sender)), answered = orders.find((o) => o.type === "respond" && o.proposal_id === p.id);
    const what = p.kind === "alliance" ? `${from} proposes an alliance.`
      : p.kind === "non_aggression" ? `${from} proposes a non-aggression pact for ten years.`
      : p.kind === "peace" ? `${from} offers peace${p.reply_to ? " (a counter-offer)" : ""}: ${termsText(p, p.sender) || "a white peace"}.`
      : p.kind === "trade" ? `${from} offers ${costText(unbundle(p.give))} for ${costText(unbundle(p.receive))}${p.reply_to ? " (a counter-offer)" : ""}.`
      : p.kind === "marriage" ? `${from} proposes a royal marriage between your houses.`
      : p.kind === "coalition" ? `${from} invites you into a league against ${esc(nameOf(p.enemy))}: if it attacks either of you, both go to war.`
      : `${from} calls you to arms against ${esc(nameOf(p.enemy))}. Ignoring it ends the alliance.`;
    const state = answered ? (answered.accept ? `<span class="ok">You accept.</span>` : answered.counter ? `<span class="ok">You counter.</span>` : `<span class="warn">You refuse.</span>`) : "";
    const canCounter = p.kind === "peace" || p.kind === "trade";
    return `<div class="proposal"><div>${what} ${state}</div>${p.note ? `<blockquote>“${esc(p.note)}”</blockquote>` : ""}
      <input class="field answer-note" data-note="${p.id}" maxlength="300" placeholder="A word with your answer (optional)" value="${esc(answered?.note || "")}">
      <div class="row"><button class="btn" data-answer="${p.id}" data-accept="1">Accept</button><button class="btn" data-answer="${p.id}" data-accept="0">Refuse</button>
      ${canCounter ? `<button class="btn" data-counter="${p.id}">Counter-offer…</button>` : ""}</div></div>`;
  }
  let deskTab = "letters";
  const yearOf = (turn) => R.startYear + turn - 1;
  const KIND_WORD = {alliance: "an alliance", non_aggression: "a non-aggression pact", marriage: "a royal marriage", coalition: "a league",
    trade: "a trade", peace: "peace", call_to_arms: "a call to arms"};
  // what each court said and did to you lately, as one letter book (the engine keeps it)
  function thread(nid) {
    const n = V.nations.find((x) => x.id === nid);
    const status = (id) => {
      const later = n.correspondence.find((e) => e.data.proposal_id === id && e.kind !== "proposal_made");
      if (later) return {proposal_rejected: "refused", proposal_expired: "expired", proposal_countered: "answered with a counter-offer"}[later.kind] || "";
      if (V.proposals_to_answer.some((p) => p.id === id)) return "awaiting your answer";
      if (V.proposals_sent.some((p) => p.id === id)) return "awaiting their answer";
      return "accepted, or overtaken by events";
    };
    const items = n.correspondence.map((e) => {
      const fromMe = (e.data.sender || e.nations[0]) === G.human;
      if (e.kind === "message") return `<div class="bubble ${fromMe ? "mine" : "theirs"}"><small>${yearOf(e.turn)}, ${fromMe ? "you wrote" : `${esc(n.name)} wrote`}</small>${esc(e.data.text)}</div>`;
      if (e.kind === "proposal_made") {
        const kind = e.data.proposal_kind, st = status(e.data.proposal_id);
        return `<div class="bubble ${fromMe ? "mine" : "theirs"} offer"><small>${yearOf(e.turn)}, ${fromMe ? "you proposed" : `${esc(n.name)} proposed`}</small>
          📜 ${esc(KIND_WORD[kind] || kind)}${e.data.note ? `<q>${esc(e.data.note)}</q>` : ""}<span class="st ${st.startsWith("refused") || st === "expired" ? "neg" : ""}">${esc(st)}</span></div>`;
      }
      if (["proposal_rejected", "proposal_expired", "proposal_countered"].includes(e.kind)) return "";
      return `<div class="sysline">${ICON[e.kind] || "•"} ${yearOf(e.turn)}: ${esc(e.summary)}</div>`;
    }).join("");
    const drafts = orders.filter((o) => o.target === nid && ["send_message", "propose_alliance", "propose_non_aggression", "propose_marriage", "propose_coalition", "propose_trade", "gift"].includes(o.type))
      .map((o) => `<div class="bubble mine draft"><small>this year, to be sent</small>${o.type === "send_message" ? esc(o.text) : `📜 ${esc(describe(o))}${o.note ? `<q>${esc(o.note)}</q>` : ""}`}</div>`).join("");
    return `<div class="thread">${items || `<p class="muted">No word has passed between your courts yet.</p>`}${drafts}</div>`;
  }
  function composer(nid) {
    const r = relation(nid);
    const feared = V.nations.filter((x) => x.alive && x.id !== nid && x.infamy >= R.coalitionInfamy && !r.leagues.includes(x.id));
    const allies = V.me.treaties.filter((t) => t.kind === "alliance" && t.partner === nid).length;
    const options = [["", "Just the letter"],
      ...(!r.war && !r.alliance ? [["propose_alliance", "Propose an alliance"]] : []),
      ...(!r.war && !r.pact && !r.alliance ? [["propose_non_aggression", "Propose a non-aggression pact"]] : []),
      ...(!r.war && !r.marriage ? [["propose_marriage", "Propose a royal marriage"]] : []),
      ...(!r.war ? feared.map((x) => [`coalition:${x.id}`, `Invite them into a league against ${x.name} (infamy ${Math.round(x.infamy)})`]) : []),
      ...(allies ? V.me.wars.map((w) => [`call:${w.enemy}`, `Call them to arms against ${nameOf(w.enemy)}`]) : [])];
    return `<div class="composer"><textarea id="letter" maxlength="500" placeholder="Write to ${esc(nameOf(nid))}. With a proposal attached, your words go with it as its note."></textarea>
      <div class="row"><select class="field" id="attach" aria-label="Attach a proposal">${options.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select>
      <button class="btn" data-dip="compose">Seal and send</button></div>
      <p class="sub">Words do not change the rules; rulers read them. A proposal must be answered next year or it lapses.</p></div>`;
  }
  function dossier(nid) {
    const n = V.nations.find((x) => x.id === nid), name = esc(n.name);
    const tech = (t) => T.reduce((sum, b) => sum + t[b.id], 0);
    const bound = V.me.treaties.filter((t) => t.partner === nid && (t.kind === "tribute" || t.kind === "army_limit")).map((t) =>
      t.kind === "tribute" ? `${t.payer === G.human ? "You pay" : `${name} pays`} ${t.amount} ducats a year until ${yearOf(t.until_turn)}`
        : `${t.payer === G.human ? "Your" : `${name}'s`} army is limited to ${t.amount} regiments until ${yearOf(t.until_turn)}`);
    const history = G.chronicle.flatMap((y) => y.events.filter((e) => e.nations.includes(nid) && e.nations.includes(G.human) && !["moved", "recruited", "message"].includes(e.kind))
      .map((e) => `<li><span class="yr">${y.year}</span> ${ICON[e.kind] || "•"} ${esc(e.summary)}</li>`)).slice(0, 10).join("");
    return `<table class="grid num versus"><thead><tr><th></th><th>You</th><th>${name}</th></tr></thead><tbody>
        <tr><td>Provinces</td><td>${V.me.provinces.length}</td><td>${n.provinces}</td></tr>
        <tr><td>Standing</td><td>${V.me.standing}</td><td>${n.standing}</td></tr>
        <tr><td>Generals</td><td>${V.me.generals.length}</td><td>${n.generals}</td></tr>
        <tr><td>Technology</td><td>${tech(V.me.technology)}</td><td>${tech(n.technology)}</td></tr>
        <tr><td>Prestige</td><td>${V.me.prestige}</td><td>${n.prestige}</td></tr>
        <tr><td>Infamy</td><td>${V.me.infamy}</td><td class="${n.infamy >= R.coalitionInfamy ? "neg" : ""}">${n.infamy}</td></tr>
        <tr><td>War exhaustion</td><td>${V.me.war_exhaustion.toFixed(1)}</td><td>${n.war_exhaustion.toFixed(1)}</td></tr>
        <tr><td>Faith</td><td>${esc(V.me.faith)}</td><td>${esc(n.faith)}</td></tr></tbody></table>
      <p class="sub">${name} is at war with ${n.at_war_with.map((x) => esc(nameOf(x))).join(", ") || "no one"}; allied with ${n.allies.map((x) => esc(nameOf(x))).join(", ") || "no one"}${n.leagued_against.length ? `; leagued against ${n.leagued_against.map((x) => esc(nameOf(x))).join(", ")}` : ""}.
        It counts as friends ${listOf(n.stances, "friend")}, as rivals ${listOf(n.stances, "rival")}.</p>
      ${bound.map((b) => `<p class="sub">⚖ ${b}.</p>`).join("")}
      ${history ? `<h4>Between your courts</h4><ul class="history">${history}</ul>` : ""}`;
  }
  function treatiesDesk(nid) {
    const r = relation(nid), name = esc(nameOf(nid)), n = V.nations.find((x) => x.id === nid);
    const pending = (...kinds) => V.proposals_sent.some((p) => p.recipient === nid && kinds.includes(p.kind)) || orders.some((o) => o.target === nid && kinds.includes(o.type));
    const treaties = [r.alliance && "your alliance", r.pact && "your non-aggression pact", r.truce && "the truce", r.marriage && "the marriage"].filter(Boolean);
    const counter = countering && countering.sender === nid ? countering : null;
    const tradeCounter = counter && counter.kind === "trade" ? counter : null;
    const row = (have, cancel, propose, label, text) => `<div class="pact-row"><div><b>${label}</b><small>${text}</small></div>${have
      ? `<button class="btn" data-cancel="${cancel}">End it</button>` : r.war ? "" : `<button class="btn" data-dip="${propose}" ${pending(propose, cancel) ? "disabled" : ""}>Propose</button>`}</div>`;
    return `<div class="pacts">
        ${row(r.alliance, "alliance", "propose_alliance", "Alliance", "Each is called to arms when the other is attacked; ignoring a call ends it. +20 opinion.")}
        ${row(r.pact, "non_aggression", "propose_non_aggression", "Non-aggression pact", "Ten years without war between you; breaking it is betrayal. +10 opinion.")}
        ${row(r.marriage, "marriage", "propose_marriage", "Royal marriage", `Both courts warm by ${R.marriageYearly} a year while it lasts; at most ${R.maxMarriages} for a realm. +15 opinion.`)}
        ${r.leagues.length ? `<div class="pact-row"><div><b>Leagues</b><small>Against ${r.leagues.map((x) => esc(nameOf(x))).join(", ")}: if it attacks either of you, both fight.</small></div><button class="btn" data-cancel="coalition">Leave</button></div>` : ""}</div>
      <p class="sub">Your infamy is ${V.me.infamy}, theirs ${n.infamy}. A league can stand only against a court of infamy ${R.coalitionInfamy} or more: write a letter and attach the invitation.</p>
      <details ${tradeCounter ? "open" : ""}><summary>${tradeCounter ? "Your counter-offer" : "Trade, gifts and tribute"}</summary>
        <div class="sub">You give</div>${bundleInputs("trade-give", tradeCounter ? tradeCounter.receive : null)}
        <div class="sub">You ask for</div>${bundleInputs("trade-receive", tradeCounter ? tradeCounter.give : null)}
        <textarea id="trade-note" maxlength="300" placeholder="A word to go with it (optional)"></textarea>
        <div class="row">${tradeCounter ? `<button class="btn" data-dip="counter_trade">Send the counter-offer</button><button class="btn" data-dip="drop_counter">Never mind</button>`
          : `<button class="btn" data-dip="propose_trade" ${r.war ? "disabled" : ""}>Offer the trade</button><button class="btn" data-dip="gift">Send what you give as a gift</button>`}</div>
        <p class="sub">A gift warms them: +1 opinion for every 4 ducats' worth, up to +25.</p></details>
      ${r.war ? "" : `<details><summary>War</summary>${treaties.length ? `<p class="warn">War breaks ${treaties.join(" and ")}: −${R.breakPenalty} stability, and every court in Europe will think less of you.</p>` : ""}
        ${n.leagued_against.length ? `<p class="warn">${name} is in a league against ${n.leagued_against.map((x) => esc(nameOf(x))).join(", ")}${n.leagued_against.includes(G.human) ? ": attack it and the whole league marches on you" : ""}.</p>` : ""}
        <p class="sub">Armies mobilise for ${R.mobilization} year before they can attack. ${name}'s allies will be called to arms.</p>
        <div class="row"><button class="btn danger" data-dip="declare_war" ${pending("declare_war") ? "disabled" : ""}>Declare war on ${name}</button></div></details>`}`;
  }
  function diplomacyTab() {
    const list = V.nations.filter((n) => n.alive).map((n) => {
      const color = N[nIndex[n.id]].color, waiting = V.proposals_to_answer.filter((p) => p.sender === n.id).length;
      const fresh = n.correspondence.filter((e) => e.turn === V.turn - 1 && e.kind === "message" && e.data.sender === n.id).length;
      return `<div class="nrow court ${nIndex[n.id] === focus ? "sel" : ""}" data-n="${n.id}" tabindex="0">
        ${n.ruler ? portrait(n.ruler, color, 38) : `<span class="shield" style="background:${color}"></span>`}
        <div><b>${PaxMap.flag(n.id, color, 20, "flag inline")} ${esc(n.name)}</b>${G.humans && G.humans[n.id] ? ` <span class="chip player" title="A player at this table">👤 ${esc(G.humans[n.id])}</span>` : ""}${waiting ? ` <span class="count" title="Proposals awaiting your answer">${waiting}</span>` : ""}${fresh ? ` <span class="count letters" title="Letters last year">✉ ${fresh}</span>` : ""}<small>${n.ruler ? `${esc(n.ruler.title)} ${esc(n.ruler.name)}` : ""}</small>
          <div class="chips">${opinionBadge(n.opinion_of_you, "Their opinion of you: ")}${stanceChip(n.stances[G.human], "toward you")}${stanceChip(V.me.stances[n.id], "yours")}${n.infamy >= R.coalitionInfamy ? `<span class="chip war" title="Infamy ${n.infamy}: Europe may league against it">feared</span>` : ""}${chipsFor(n.id)}</div></div></div>`;
    }).join("");
    const against = V.nations.filter((n) => n.alive && n.leagued_against.includes(G.human)).map((n) => esc(n.name));
    const feared = V.nations.filter((n) => n.alive && n.infamy >= R.coalitionInfamy / 2).sort((a, b) => b.infamy - a.infamy)
      .map((n) => `${esc(n.name)} ${Math.round(n.infamy)}`);
    const pct = Math.min(100, Math.round(100 * V.me.infamy / (R.coalitionInfamy * 2)));
    const europe = `<div class="pad europe"><h4>Europe watches</h4>
      <div class="infamy"><span>Your infamy <b class="${V.me.infamy >= R.coalitionInfamy ? "neg" : ""}">${V.me.infamy}</b></span>
        <i class="bar"><b style="width:${pct}%"></b><em style="left:50%" title="From ${R.coalitionInfamy}, courts may league against you"></em></i></div>
      <p class="sub">${against.length ? `<span class="warn">Leagued against you: ${against.join(", ")}.</span> ` : ""}${feared.length ? `Feared conquerors: ${feared.join(", ")}.` : "No conqueror frightens Europe yet."}
        Every province taken adds infamy; it fades by ${R.infamyDecay} a year.</p></div>`;
    const alive = focus >= 0 && focus !== me && V.nations.find((n) => n.id === N[focus].id)?.alive;
    const voices = G.chronicle.flatMap((y) => y.events.filter((e) => e.kind === "proclamation").map((e) => [y.year, e])).slice(0, 4)
      .map(([year, e]) => `<li><span class="yr">${year}</span> <b>${esc(nameOf(e.data.sender))}</b>: <q>${esc(e.data.text)}</q></li>`).join("");
    return `${europe}${voices ? `<div class="pad voices"><h4>Voices of Europe</h4><ul class="history">${voices}</ul></div>` : ""}
      <div class="courts">${list}</div>${alive ? desk(N[focus].id) : `<p class="muted pad">Pick a court to treat with it.</p>`}`;
  }
  const stanceChip = (stance, whose) => stance && stance !== "neutral"
    ? `<span class="chip stance ${stance}" title="${whose === "yours" ? "Your declared stance" : "Their declared stance toward you"}">${whose === "yours" ? "your " : ""}${stance}${whose === "yours" ? "" : " of yours"}</span>` : "";
  const borderOf = (owner, other) => V.provinces.filter((p) => p.owner === owner && !p.is_capital
    && [...p.neighbors, ...p.sea_neighbors].some((x) => prov(pIndex[x]).owner === other));
  function desk(nid) {
    const n = V.nations.find((x) => x.id === nid), r = relation(nid), name = esc(n.name), color = N[nIndex[nid]].color;
    const ruler = n.ruler, mine = V.me.opinions[nid] || 0;
    const theirs = V.proposals_to_answer.filter((p) => p.sender === nid).map(proposalCard).join("");
    const counter = countering && countering.sender === nid ? countering : null;
    if (r.war && deskTab === "treaties") deskTab = "war";
    if (!r.war && deskTab === "war") deskTab = "letters";
    const tabs = [["letters", "✉ Letters"], ["dossier", "📋 Dossier"], ["treaties", "🤝 Treaties"], ...(r.war || (counter && counter.kind === "peace") ? [["war", "⚔ War and peace"]] : [])];
    let body = "";
    if (deskTab === "letters") body = `${theirs ? `<h4>They propose</h4>${theirs}` : ""}${thread(nid)}${composer(nid)}`;
    else if (deskTab === "dossier") body = dossier(nid);
    else if (deskTab === "treaties") body = treatiesDesk(nid);
    else {
      const allies = V.me.treaties.filter((t) => t.kind === "alliance").map((t) => t.partner).filter((a) => !V.nations.find((x) => x.id === a).at_war_with.includes(nid));
      body = (r.war ? warBlock(nid) : "") + peaceBuilder(nid, counter && counter.kind === "peace" ? counter : null)
        + (r.war && allies.length ? `<h4>Call your allies</h4><div class="row">${allies.map((a) => `<button class="btn" data-call="${a}">Call ${esc(nameOf(a))}</button>`).join("")}</div>` : "");
    }
    return `<div class="pad desk">
      <div class="audience">${ruler ? portrait(ruler, color, 84) : ""}
        <div><b>${ruler ? `${esc(ruler.title)} ${esc(ruler.name)}` : name}</b><div class="sub">of ${name}${ruler ? `, aged ${ruler.age}` : ""}${G.humans && G.humans[nid] ? `, played by ${esc(G.humans[nid])}` : ""}</div>
          ${ruler && ruler.bio ? `<p class="lore">${esc(ruler.bio)}</p>` : ""}${ruler ? traitChips(ruler.traits) : ""}</div></div>
      <div class="moods"><div><span class="sub">They think of you</span>${opinionBadge(n.opinion_of_you)}<i class="bar"><b style="left:${50 + n.opinion_of_you / 2}%"></b></i></div>
        <div><span class="sub">You think of them</span>${opinionBadge(mine)}<i class="bar"><b style="left:${50 + mine / 2}%"></b></i></div></div>
      <div class="chips">${chipsFor(nid) || `<span class="muted">No treaty.</span>`}</div>
      <div class="row stance-row"><span class="sub">You count them</span>${["friend", "neutral", "rival"].map((st) => {
          const now = (V.me.stances[nid] || "neutral") === st, queued = orders.some((o) => o.type === "set_stance" && o.target === nid && o.stance === st);
          return `<button class="btn ${now ? "on" : ""}" data-stance="${st}" ${now || queued ? "disabled" : ""}>${cap(st)}</button>`; }).join("")}</div>
      <nav class="desktabs">${tabs.map(([id, label]) => `<button class="${deskTab === id ? "on" : ""}" data-desk="${id}">${label}</button>`).join("")}</nav>
      ${body}</div>`;
  }
  function warBlock(nid) {
    const w = warOf(nid);
    if (!w) return "";
    const held = V.provinces.filter((p) => p.owner === nid && p.controller === G.human).map((p) => esc(p.name));
    const lost = V.provinces.filter((p) => p.owner === G.human && p.controller === nid).map((p) => esc(p.name));
    return `<div class="warbox"><div class="row"><b>War score ${sign(w.war_score)}</b>${scoreBar(w.war_score)}</div>
      <p class="sub">You hold ${held.join(", ") || "nothing of theirs"}; they hold ${lost.join(", ") || "nothing of yours"}.
        Battles ${w.battles_won} won, ${w.battles_lost} lost. Your war exhaustion is ${V.me.war_exhaustion.toFixed(1)}.</p>
      <p class="sub">A peace may demand of them only what your war score covers; offering is never limited.</p></div>`;
  }
  const listOf = (stances, kind) => { const xs = Object.entries(stances || {}).filter(([, v]) => v === kind).map(([k]) => k === G.human ? "you" : esc(nameOf(k)));
    return xs.length ? xs.join(", ") : "no one"; };
  // What demands on `payer` cost in war score, as the engine prices them (their income is
  // estimated from what their provinces yield, which every court can see).
  function warCost(payer, terms) {
    const owned = V.provinces.filter((p) => p.owner === payer);
    const total = Math.max(1, owned.reduce((t, p) => t + p.development, 0));
    const income = Math.max(10, payer === G.human ? V.me.income_per_turn.ducats : owned.reduce((t, p) => t + p.output_per_turn.ducats, 0));
    let cost = (terms.demand || []).reduce((t, id) => t + Math.max(5, Math.round(100 * prov(pIndex[id]).development / total)), 0);
    const r = terms.receive || {};
    const worth = (r.ducats || 0) + 2 * ((r.iron || 0) + (r.timber || 0)) + 3 * (r.manpower || 0) + (r.grain || 0);
    if (worth) cost += Math.round(10 * worth / income);
    if (terms.ask_tribute) cost += Math.round(10 * terms.ask_tribute * R.tributeYears / income / 2);
    if (terms.limit_army !== undefined && terms.limit_army !== null) cost += R.peaceCostArmyLimit;
    return cost;
  }
  const warOf = (nid) => V.me.wars.find((w) => w.enemy === nid);
  function scoreBar(score) {
    return `<i class="bar score"><b style="left:${50 + score / 2}%"></b></i>`;
  }
  function peaceBuilder(nid, counter) {
    // A counter-offer starts from their terms, seen from your side.
    const c = counter ? {give: counter.receive, receive: counter.give, cede: counter.demand, demand: counter.cede,
      pay_tribute: counter.ask_tribute, ask_tribute: counter.pay_tribute} : {};
    const pick = (list, chosen, id) => list.length ? list.map((p) => `<label class="pick"><input type="checkbox" data-${id}="${p.id}" ${(chosen || []).includes(p.id) ? "checked" : ""}>
      ${esc(p.name)} <small>${p.development} dev.</small></label>`).join("") : `<span class="muted">none on the border</span>`;
    return `<details open class="peace"><summary>${counter ? "Your counter-offer" : "Terms of peace"}</summary>
      ${counter ? `<p class="sub">Their offer, turned to face you. Change what you will and send it back.</p>` : `<p class="sub">Leave everything empty for a white peace. They may accept, refuse or haggle.</p>`}
      <div class="terms">
        <div><div class="sub">Provinces you demand</div><div class="picks">${pick(borderOf(nid, G.human), c.demand, "demand")}</div></div>
        <div><div class="sub">Provinces you cede</div><div class="picks">${pick(borderOf(G.human, nid), c.cede, "cede")}</div></div>
      </div>
      <div class="sub">A sum you demand</div>${bundleInputs("peace-receive", c.receive)}
      <div class="sub">A sum you pay</div>${bundleInputs("peace-give", c.give)}
      <div class="row tribute"><label>Tribute they pay <input type="number" class="field" min="0" max="500" id="ask-tribute" value="${c.ask_tribute || 0}"></label>
        <label>Tribute you pay <input type="number" class="field" min="0" max="500" id="pay-tribute" value="${c.pay_tribute || 0}"></label>
        <span class="sub">ducats a year, for ${R.tributeYears} years</span></div>
      <div class="row"><label>Limit their army to <input type="number" class="field" min="0" id="limit-army" placeholder="no limit"></label><span class="sub">regiments during the truce</span></div>
      <textarea id="peace-note" maxlength="300" placeholder="Your words to their envoy (optional)"></textarea>
      <p class="sub" id="peace-cost"></p>
      <div class="row">${counter ? `<button class="btn" data-dip="counter_peace">Send the counter-offer</button><button class="btn" data-dip="drop_counter">Never mind</button>`
        : `<button class="btn" data-dip="propose_peace" ${V.proposals_sent.some((p) => p.recipient === nid && p.kind === "peace") || orders.some((o) => o.type === "propose_peace" && o.target === nid) ? "disabled" : ""}>Propose peace</button>`}</div></details>`;
  }
  function bundleInputs(id, values = null) {
    return `<div class="bundle" id="${id}">${RES.map(([key, label, ic]) => `<label>${ic}<input type="number" min="0" value="${(values && values[key]) || 0}" data-r="${key}" aria-label="${label}"></label>`).join("")}</div>`;
  }
  function readBundle(id) { const b = {}; document.querySelectorAll(`#${id} input`).forEach((i) => (b[i.dataset.r] = Math.max(0, +i.value || 0))); return b; }
  const emptyBundle = (b) => Object.values(b).every((v) => !v);
  function readPeace() {
    const ids = (attr) => [...document.querySelectorAll(`[data-${attr}]:checked`)].map((x) => x.dataset[attr]);
    const terms = {give: readBundle("peace-give"), receive: readBundle("peace-receive"), cede: ids("cede"), demand: ids("demand"),
      pay_tribute: Math.max(0, +$("pay-tribute").value || 0), ask_tribute: Math.max(0, +$("ask-tribute").value || 0)};
    const limit = $("limit-army").value.trim(); if (limit !== "") terms.limit_army = Math.max(0, +limit || 0);
    const note = $("peace-note").value.trim(); if (note) terms.note = note;
    return terms;
  }
  function lettersTab() {
    const decisions = V.me.pending_events.map((e) => eventCard(e)).join("");
    const proposals = V.proposals_to_answer.map(proposalCard).join("");
    const letters = V.last_turn_events.filter((e) => e.kind === "message" && e.data.sender !== G.human)
      .map((e) => `<div class="item">From <b>${esc(nameOf(e.data.sender))}</b><div class="letter">${esc(e.data.text)}</div></div>`).join("");
    const replies = V.last_turn_events.filter((e) => ["proposal_rejected", "proposal_expired", "proposal_countered", "treaty_signed", "trade_completed", "trade_failed", "peace_signed", "province_ceded", "tribute_paid"].includes(e.kind) && e.nations.includes(G.human))
      .map((e) => `<div class="item">${ICON[e.kind] || "•"} ${esc(e.summary)}</div>`).join("");
    return `${decisions ? `<div class="pad"><h4>For the crown to decide</h4>${decisions}</div>` : ""}
      ${proposals ? `<div class="pad">${proposals}</div>` : `<p class="muted pad">No proposal waits for your answer.</p>`}
      ${letters ? `<div class="pad" style="padding-bottom:0"><h4>Letters</h4></div>${letters}` : ""}${replies ? `<div class="pad" style="padding-bottom:0"><h4>Replies</h4></div>${replies}` : ""}`;
  }
  const told = (e) => e.kind === "order_rejected" ? "Your order failed: " + e.data.reason
    : e.kind === "proclamation" ? `${e.summary}: “${e.data.text}”` : e.summary;
  function chronicleTab() {
    if (!G.chronicle.length) return `<p class="muted pad">History begins when you end the first year.</p>`;
    const names = new RegExp(N.map((n) => n.name).join("|"), "g");
    const paint = (text) => esc(text).replace(names, (m) => `<span class="nn" style="color:${mix(N.find((n) => n.name === m).color, "#ffffff", .35)}">${m}</span>`);
    return `<ol class="chron" style="max-height:none">${G.chronicle.map((y) => `<li class="year">${y.year}</li>` + y.events
      .filter((e) => !["moved", "proposal_made"].includes(e.kind))
      .map((e) => `<li class="${BAD.has(e.kind) ? "bad" : ""}"><span class="ic">${ICON[e.kind] || "•"}</span><span>${paint(told(e))}</span></li>`).join("")).join("")}</ol>`;
  }
  function office() {
    document.querySelectorAll(".offices button").forEach((b) => {
      b.setAttribute("aria-selected", b.dataset.tab === tab);
      const count = b.dataset.tab === "letters" ? V.proposals_to_answer.filter((p) => !orders.some((o) => o.type === "respond" && o.proposal_id === p.id)).length
        + V.me.pending_events.filter((e) => !chosen(e.id)).length : 0;
      const old = b.querySelector(".count"); if (old) old.remove();
      if (count) b.insertAdjacentHTML("beforeend", `<span class="count">${count}</span>`);
    });
    const panel = $("office");
    panel.innerHTML = {realm: realmTab, crown: crownTab, army: armyTab, tech: techTab, diplomacy: diplomacyTab, letters: lettersTab, chronicle: chronicleTab}[tab]();
    const focusOn = (i) => { picked = i; send = Infinity; lead = true; map.centerOn(i, 2.2, innerWidth > 960 ? 200 : 0); render(); };
    panel.querySelectorAll("tr.click").forEach((tr) => tr.onclick = () => focusOn(+tr.dataset.p));
    panel.querySelectorAll("[data-goto]").forEach((b) => b.onclick = () => focusOn(+b.dataset.goto));
    panel.querySelectorAll("[data-research]").forEach((b) => b.onclick = () => queue({type: "research", branch: b.dataset.research}));
    panel.querySelectorAll("[data-hire]").forEach((b) => b.onclick = () => queue({type: "hire_advisor", candidate: +b.dataset.hire}));
    panel.querySelectorAll("[data-dismiss]").forEach((b) => b.onclick = () => queue({type: "dismiss_advisor", role: b.dataset.dismiss}));
    panel.querySelectorAll("[data-assign]").forEach((b) => b.onclick = () => {
      const id = +b.dataset.assign, to = panel.querySelector(`[data-gsel="${id}"]`).value;
      orders = orders.filter((o) => !(o.type === "assign_general" && o.general === id));
      queue({type: "assign_general", general: id, province: to});
    });
    panel.querySelectorAll("[data-qty]").forEach((x) => x.onchange = () => { marketQty[x.dataset.qty] = Math.max(1, Math.min(200, +x.value || 1)); render(); });
    panel.querySelectorAll("[data-buy]").forEach((b) => b.onclick = () => queue({type: "buy", resource: b.dataset.buy, amount: marketQty[b.dataset.buy] || 10}));
    panel.querySelectorAll("[data-sell]").forEach((b) => b.onclick = () => queue({type: "sell", resource: b.dataset.sell, amount: marketQty[b.dataset.sell] || 10}));
    panel.querySelectorAll("[data-option]").forEach((b) => b.onclick = () => choose(+b.dataset.event, +b.dataset.option));
    const taxRange = panel.querySelector("#taxrange");
    if (taxRange) taxRange.oninput = () => { const level = +taxRange.value;
      orders = orders.filter((o) => o.type !== "set_taxes");
      if (level !== V.me.tax) queue({type: "set_taxes", level}); else render(); };
    const patronize = panel.querySelector("#patronize"); if (patronize) patronize.onclick = () => queue({type: "patronize"});
    const proclaim = panel.querySelector("#proclaim");
    if (proclaim) proclaim.onclick = () => { const text = $("proclamation").value.trim();
      if (!text) return flash("Write the proclamation first."); queue({type: "proclaim", text}); };
    const hire = panel.querySelector("#hire"); if (hire) hire.onclick = () => queue({type: "hire_general", province: panel.querySelector("#hireat").value});
    panel.querySelectorAll(".nrow").forEach((row) => { const go = () => { focus = nIndex[row.dataset.n]; render(); };
      row.onclick = go; row.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
    const nid = focus >= 0 ? N[focus].id : null;
    panel.querySelectorAll("[data-dip]").forEach((b) => b.onclick = () => {
      const kind = b.dataset.dip;
      if (kind === "propose_peace") { const terms = readPeace();
        if (!affordable(unbundle(terms.give))) return flash("You cannot afford what you offer.");
        return queue({type: kind, target: nid, ...terms}); }
      if (kind === "drop_counter") { countering = null; return render(); }
      if (kind === "counter_peace" || kind === "counter_trade") {
        const id = countering.id, counter = kind === "counter_peace" ? readPeace()
          : {give: readBundle("trade-give"), receive: readBundle("trade-receive"), ...($("trade-note").value.trim() ? {note: $("trade-note").value.trim()} : {})};
        if (!affordable(unbundle(counter.give))) return flash("You cannot afford what you offer.");
        orders = orders.filter((o) => !(o.type === "respond" && o.proposal_id === id));
        countering = null;
        return queue({type: "respond", proposal_id: id, accept: false, counter});
      }
      if (kind === "propose_trade") { const give = readBundle("trade-give"), receive = readBundle("trade-receive");
        if (emptyBundle(give) && emptyBundle(receive)) return flash("Fill in what you give or what you ask for.");
        if (!affordable(unbundle(give))) return flash("You cannot afford what you offer.");
        const note = $("trade-note").value.trim();
        return queue({type: kind, target: nid, give, receive, ...(note ? {note} : {})}); }
      if (kind === "gift") { const resources = readBundle("trade-give");
        if (emptyBundle(resources)) return flash("Fill in what you give.");
        if (!affordable(unbundle(resources))) return flash("You cannot afford that gift.");
        return queue({type: kind, target: nid, resources}); }
      if (kind === "send_message") { const text = $("letter").value.trim();
        if (!text) return flash("Write something first.");
        return queue({type: kind, target: nid, text}); }
      if (kind === "compose") {
        const text = $("letter").value.trim(), attach = $("attach").value;
        if (!attach) { if (!text) return flash("Write something first."); return queue({type: "send_message", target: nid, text}); }
        const note = text ? {note: text.slice(0, 300)} : {};
        if (attach.startsWith("coalition:")) return queue({type: "propose_coalition", target: nid, against: attach.slice(10), ...note});
        if (attach.startsWith("call:")) return queue({type: "call_to_arms", target: nid, enemy: attach.slice(5), ...note});
        return queue({type: attach, target: nid, ...note});
      }
      if (kind === "declare_war" && !confirm(`Declare war on ${nameOf(nid)}?`)) return;
      queue({type: kind, target: nid});
    });
    const costLine = panel.querySelector("#peace-cost");
    if (costLine) {
      const update = () => {
        const terms = readPeace(), score = warOf(nid)?.war_score ?? 0, cost = warCost(nid, terms);
        costLine.className = "sub" + (cost > Math.max(0, score) ? " warn" : "");
        costLine.textContent = cost ? `Your demands cost about ${cost} war score; you have ${sign(score)}.${cost > Math.max(0, score) ? " Too much: the envoys will refuse to carry it." : ""}`
          : "You demand nothing: whatever you offer is allowed.";
      };
      panel.querySelectorAll("details.peace input, details.peace textarea").forEach((x) => (x.oninput = update));
      update();
    }
    panel.querySelectorAll("[data-desk]").forEach((b) => b.onclick = () => { deskTab = b.dataset.desk; render(); });
    panel.querySelectorAll("[data-stance]").forEach((b) => b.onclick = () => {
      orders = orders.filter((o) => !(o.type === "set_stance" && o.target === nid));
      queue({type: "set_stance", target: nid, stance: b.dataset.stance});
    });
    panel.querySelectorAll("[data-cancel]").forEach((b) => b.onclick = () => queue({type: "cancel_treaty", target: nid, kind: b.dataset.cancel}));
    panel.querySelectorAll("[data-call]").forEach((b) => b.onclick = () => queue({type: "call_to_arms", target: b.dataset.call, enemy: nid}));
    panel.querySelectorAll("[data-counter]").forEach((b) => b.onclick = () => {
      countering = V.proposals_to_answer.find((p) => p.id === +b.dataset.counter);
      focus = nIndex[countering.sender]; tab = "diplomacy"; deskTab = countering.kind === "peace" ? "war" : "treaties"; render();
    });
    panel.querySelectorAll("[data-answer]").forEach((b) => b.onclick = () => {
      const id = +b.dataset.answer, note = (panel.querySelector(`[data-note="${id}"]`)?.value || "").trim();
      orders = orders.filter((o) => !(o.type === "respond" && o.proposal_id === id));
      queue({type: "respond", proposal_id: id, accept: b.dataset.accept === "1", ...(note ? {note} : {})});
    });
  }
  document.querySelectorAll(".offices button").forEach((b) => b.onclick = () => { tab = b.dataset.tab; render(); });

  // ------------------------------------------------------------------ this year's orders, always in sight
  function describe(o) {
    const pn = (id) => esc(P[pIndex[id]].name), nn = (id) => esc(nameOf(id));
    const gname = (id) => esc(V.me.generals.find((g) => g.id === id)?.name || "a general");
    switch (o.type) {
      case "recruit": return `${UICON[o.unit || "infantry"]} Recruit ${o.regiments} ${o.unit || "infantry"} in ${pn(o.province)}`;
      case "upgrade_monument": return `🏛 Raise ${esc(M[o.province]?.name || "the monument")}`;
      case "disband": return `Disband ${o.regiments}${o.unit ? ` ${o.unit}` : ""} in ${pn(o.province)}`;
      case "develop": return `Develop ${pn(o.province)}`;
      case "improve": return `${PaxMap.goodOf(S, P[pIndex[o.province]].good).icon} Raise the ${PaxMap.goodOf(S, P[pIndex[o.province]].good).workings.toLowerCase()} of ${pn(o.province)}`;
      case "build": return `Build ${B[bIndex[o.building]].name.toLowerCase()} in ${pn(o.province)}`;
      case "boost_stability": return "Raise stability";
      case "set_taxes": return `⚖ Set taxes ${TAX_WORDS[o.level + 2].toLowerCase()}`;
      case "patronize": return `🎨 Patronise the arts (+${R.patronagePrestige} prestige)`;
      case "hire_mercenaries": return `💰 Hire ${o.regiments} mercenary regiments in ${pn(o.province)}`;
      case "research": { const b = T.find((x) => x.id === o.branch); return `Research ${b.levels[V.me.technology[o.branch]]?.name || o.branch}`; }
      case "hire_advisor": { const c = V.me.advisor_candidates.find((x) => x.id === o.candidate); return c ? `Hire ${esc(c.name)} as ${c.role}` : "Hire an advisor"; }
      case "dismiss_advisor": return `Dismiss the ${o.role}`;
      case "hire_general": return `Appoint a general in ${pn(o.province)}`;
      case "assign_general": return `Send ${gname(o.general)} to ${pn(o.province)}`;
      case "move": return `➜ March ${o.regiments} from ${pn(o.origin)} to ${pn(o.target)}${o.general ? ` under ${gname(o.general)}` : ""}`;
      case "attack": return `⚔ Attack ${pn(o.target)} with ${o.regiments} from ${pn(o.origin)}${o.general ? ` under ${gname(o.general)}` : ""}`;
      case "declare_war": return `Declare war on ${nn(o.target)}`;
      case "propose_alliance": return `Propose an alliance to ${nn(o.target)}`;
      case "propose_non_aggression": return `Propose a pact to ${nn(o.target)}`;
      case "propose_marriage": return `💍 Propose a royal marriage to ${nn(o.target)}`;
      case "propose_coalition": return `⚔ Invite ${nn(o.target)} into a league against ${nn(o.against)}`;
      case "propose_peace": { const t = termsText(o, G.human); return `🕊 Offer peace to ${nn(o.target)}${t ? `: ${t}` : ", white peace"}`; }
      case "propose_trade": return `Offer ${nn(o.target)} ${costText(unbundle(o.give))} for ${costText(unbundle(o.receive))}`;
      case "gift": return `Give ${nn(o.target)} ${costText(unbundle(o.resources))}`;
      case "cancel_treaty": return `End the ${o.kind.replace("_", "-")} treaty with ${nn(o.target)}`;
      case "call_to_arms": return `Call ${nn(o.target)} to arms against ${nn(o.enemy)}`;
      case "send_message": return `Letter to ${nn(o.target)}`;
      case "proclaim": return `📣 Proclaim to Europe`;
      case "buy": return `⚖ Buy ${o.amount} ${o.resource} for ${Math.ceil(o.amount * V.market[o.resource].buy)} ducats`;
      case "sell": return `⚖ Sell ${o.amount} ${o.resource} for ${Math.floor(o.amount * V.market[o.resource].sell)} ducats`;
      case "choose_option": { const e = V.me.pending_events.find((x) => x.id === o.event_id);
        return e ? `${EVENT_ICON[e.event] || "📜"} ${esc(e.title)}: ${esc(e.options[o.option].label.toLowerCase())}` : "A decision"; }
      case "set_stance": return o.stance === "neutral" ? `Count ${nn(o.target)} neither friend nor rival` : `Name ${nn(o.target)} your ${o.stance}`;
      case "respond": { const p = V.proposals_to_answer.find((x) => x.id === o.proposal_id), who = p ? nn(p.sender) : "";
        return o.accept ? `Accept ${who}'s ${p ? p.kind.replace("_", " ") : "proposal"}` : o.counter ? `Counter ${who}'s ${p ? p.kind : "offer"}` : `Refuse ${who}'s ${p ? p.kind.replace("_", " ") : "proposal"}`; }
      default: return o.type;
    }
  }
  function ordersBox() {
    $("orders").innerHTML = `<h4>This year's orders <small>${orders.length} of ${MAX_ORDERS}</small></h4>` + (orders.length
      ? orders.map((o, k) => `<div class="order"><span>${describe(o)}</span><button data-drop="${k}" aria-label="Withdraw this order" title="Withdraw">✕</button></div>`).join("")
      : `<p class="muted pad">No orders yet. Select a province on the map, or open an office above.</p>`);
    $("orders").querySelectorAll("[data-drop]").forEach((b) => b.onclick = () => { orders.splice(+b.dataset.drop, 1); render(); });
  }

  // ------------------------------------------------------------------ the year's report
  function report(before) {
    const lost = before ? before.me.provinces.filter((p) => !V.me.provinces.includes(p)) : [];
    const won = before ? V.me.provinces.filter((p) => !before.me.provinces.includes(p)) : [];
    const items = V.last_turn_events.filter((e) => !["moved", "recruited", "proposal_made"].includes(e.kind))
      .filter((e) => e.nations.includes(G.human) || ["war_declared", "nation_eliminated", "treaty_broken", "game_over", "proclamation", "event_decided"].includes(e.kind))
      .map((e) => `<li class="${BAD.has(e.kind) ? "bad" : ""}">${ICON[e.kind] || "•"} ${esc(told(e))}</li>`).join("");
    const discoveries = before ? T.filter((b) => V.me.technology[b.id] > before.me.technology[b.id]).map((b) => {
      const step = b.levels[V.me.technology[b.id] - 1];
      return `<div class="discovery">⚙ <b>${esc(step.name)}</b>: ${esc(step.unlocks)}.</div>`; }).join("") : "";
    const works = V.last_turn_events.filter((e) => e.kind === "built" && e.nations[0] === G.human)
      .map((e) => `<div class="work">🏗 ${esc(e.summary.replace(/^\S+ builds /, "A new ").replace(" in ", " stands in "))}.</div>`).join("");
    const crowned = V.last_turn_events.filter((e) => e.kind === "succession" && e.nations[0] === G.human)
      .map((e) => `<div class="discovery">👑 ${esc(e.summary)}.</div>`).join("");
    const danger = threats().filter((t) => !t.pact).map((t) => `<div class="threat">${threatText(t)}</div>`).join("");
    const ranking = [...V.nations.filter((n) => n.id !== G.human),
      {id: G.human, name: nameOf(G.human), score: V.me.score, provinces: V.me.provinces.length, alive: V.me.provinces.length > 0}]
      .sort((a, b) => b.score - a.score || b.provinces - a.provinces);
    const place = ranking.findIndex((n) => n.id === G.human) + 1;
    const fallen = !V.me.provinces.length;
    const ending = G.finished || fallen ? `<div class="ending ${G.winner === G.human ? "won" : ""}">
        <h3>${G.winner === G.human ? "Your realm is the greatest in Europe" : fallen ? "Your realm is no more" : `${esc(nameOf(G.winner))} prevails`}</h3>
        <p>${esc(V.last_turn_events.find((e) => e.kind === "game_over")?.summary || (fallen ? "Your last province has fallen" : "The game is over")).replace(/\.?$/, ".")}${place && !fallen ? ` You finish ${["first", "second", "third", "fourth", "fifth", "sixth", "seventh"][place - 1]}.` : ""}</p>
        <table class="grid num"><thead><tr><th></th><th>Nation</th><th>Score</th><th>Provinces</th></tr></thead><tbody>${ranking.map((n, k) =>
          `<tr class="${n.id === G.human ? "me" : ""}"><td>${k + 1}</td><td>${esc(n.name)}${n.alive ? "" : " †"}</td><td>${n.score}</td><td>${n.provinces}</td></tr>`).join("")}</tbody></table>
        <p><a href="${REPLAY}" target="_blank">Watch the whole game as a replay</a></p></div>` : "";
    $("sheet").innerHTML = `<h2 id="modaltitle">${G.finished ? "The end of an age" : `The year ${V.year - 1}`}</h2>${ending}${crowned}${discoveries}${works}${G.finished ? "" : danger}
      ${won.length ? `<p>Your realm gained ${won.map((p) => esc(P[pIndex[p]].name)).join(", ")}.</p>` : ""}
      ${lost.length ? `<p style="color:#8f2f22">You lost ${lost.map((p) => esc(P[pIndex[p]].name)).join(", ")}.</p>` : ""}
      <ul>${items || "<li>A quiet year for your realm.</li>"}</ul>
      <button class="btn" id="closemodal">Continue</button>`;
    $("modal").classList.add("open"); $("closemodal").focus();
    $("closemodal").onclick = () => { $("modal").classList.remove("open"); eventSheet(); };
  }
  // ------------------------------------------------------------------ the crown's decisions
  const EVENT_ICON = {reformation: "✝", plague: "☠", harvest: "🌾", fuggers: "💰", artist: "🎨", revolt: "🔥",
    silver: "🪙", comet: "☄", reformer: "⚔", nobles: "👑", fair: "🎪", mine: "⛏"};
  const chosen = (id) => orders.find((o) => o.type === "choose_option" && o.event_id === id);
  function eventCard(e, big = false) {
    const pick = chosen(e.id);
    return `<div class="eventcard ${big ? "big" : ""}"><div class="ehead"><span class="eic">${EVENT_ICON[e.event] || "📜"}</span>
        <div><b>${esc(e.title)}</b>${e.province ? `<small>${esc(P[pIndex[e.province]].name)}</small>` : ""}</div></div>
      <p class="etext">${esc(e.text)}</p>
      <div class="eoptions">${e.options.map((o, k) => `<button class="btn eoption ${pick && pick.option === k ? "on" : ""}" data-event="${e.id}" data-option="${k}">
        <b>${esc(o.label)}</b><small>${esc(o.effects)}</small></button>`).join("")}</div>
      <p class="sub">${pick ? "Your decision is taken; it is carried out when the year ends." : `Undecided by the end of ${R.startYear + e.deadline_turn - 1}, the first answer is taken.`}</p></div>`;
  }
  function choose(eventId, option) {
    orders = orders.filter((o) => !(o.type === "choose_option" && o.event_id === eventId));
    queue({type: "choose_option", event_id: eventId, option});
  }
  function eventSheet() {
    const e = V.me.pending_events.find((x) => !chosen(x.id));
    if (!e || G.finished) return;
    $("sheet").innerHTML = `<h2 id="modaltitle">For the crown to decide</h2>${eventCard(e, true)}
      <button class="btn" id="closemodal">Decide later</button>`;
    $("modal").classList.add("open");
    $("sheet").querySelectorAll("[data-option]").forEach((b) => b.onclick = () => {
      choose(+b.dataset.event, +b.dataset.option); $("modal").classList.remove("open"); eventSheet(); });
    $("closemodal").onclick = () => $("modal").classList.remove("open");
  }

  // ------------------------------------------------------------------ the map
  function world() {
    const alive = N.map((n, k) => k === me ? V.me.provinces.length > 0 : !!V.nations.find((x) => x.id === n.id)?.alive);
    const capitals = new Set([...V.nations.filter((n) => n.alive).map((n) => pIndex[n.capital]), pIndex[V.me.capital]]);
    const f = focus >= 0 ? focus : me;
    let relations;
    if (f === me) relations = {wars: V.me.at_war_with.map((x) => nIndex[x]),
      allies: V.me.treaties.filter((t) => t.kind === "alliance").map((t) => nIndex[t.partner]),
      pacts: V.me.treaties.filter((t) => t.kind !== "alliance").map((t) => nIndex[t.partner])};
    else { const n = V.nations.find((x) => x.id === N[f].id); relations = {wars: n.at_war_with.map((x) => nIndex[x]), allies: n.allies.map((x) => nIndex[x]), pacts: []}; }
    let diplo = null; // how every court stands with you, for the diplomacy map
    if (f === me) {
      diplo = {};
      V.nations.forEach((n) => { const k = nIndex[n.id], kinds = V.me.treaties.filter((t) => t.partner === n.id).map((t) => t.kind);
        diplo[k] = {opinion: n.opinion_of_you, war: V.me.at_war_with.includes(n.id), ally: kinds.includes("alliance"),
          pact: kinds.some((x) => x !== "alliance"), rival: n.stances[G.human] === "rival" || V.me.stances[n.id] === "rival",
          friend: n.stances[G.human] === "friend"}; });
    }
    const generals = new Map();
    V.provinces.forEach((p, i) => { if (p.general) generals.set(i, {nation: nIndex[p.general.nation], name: p.general.name, skill: p.general.skill}); });
    return {
      mode, focus: f, relations, diplo, alive, workings: V.provinces.map((p) => p.workings || 0), capitals, generals,
      owner: V.provinces.map((p) => (p.owner === null ? -1 : nIndex[p.owner])),
      controller: V.provinces.map((p) => (p.controller ? nIndex[p.controller] : -1)),
      troops: V.provinces.map((p) => p.troops), dev: V.provinces.map((p) => p.development),
      buildings: V.provinces.map((p) => p.buildings.map((b) => bIndex[b])),
      events: V.last_turn_events.filter((e) => e.province).map((e) => [e.kind, pIndex[e.province], e.nations.map((x) => nIndex[x])]),
    };
  }
  const MODES = [["political", "Political"], ["terrain", "Terrain"], ["development", "Development"], ["goods", "Goods"], ["diplomacy", "Diplomacy"]];
  MODES.forEach(([id, label], k) => { const b = document.createElement("button"); b.className = "btn"; b.textContent = label;
    b.title = `${label} map mode (${k + 1})`; b.dataset.mode = id; b.onclick = () => { mode = id; render(); };
    document.querySelector(".modes").appendChild(b); });
  function legend() {
    const L = $("legend");
    L.classList.toggle("wide", mode === "terrain" || mode === "goods" || mode === "diplomacy");
    if (mode === "terrain") L.innerHTML = `<b class="lh">What the land does</b>` + Object.entries(TERRAIN).map(([t, c]) => `<div class="trow"><i style="background:${c}"></i>
      <div><b>${PaxMap.TERRAIN_ICON[t]} ${cap(t)}</b><small>${PaxMap.terrainLines(S, t).join(" · ")}</small></div></div>`).join("");
    else if (mode === "development") L.innerHTML = `Development<div class="ramp" style="background:linear-gradient(90deg,${[1, 4, 6, 8, 10].map(devColor).join(",")})"></div>`;
    else if (mode === "goods") {
      // richest first: what one level of development brings, valued at the market's prices
      const price = (k) => k === "ducats" ? 1 : k === "manpower" ? 3 : (V.market?.[k]?.sell ?? R.marketBase?.[k] ?? 2);
      const worth = (y) => Object.entries(y).reduce((a, [k, v]) => a + v * price(k), 0);
      const held = new Set(V.me.provinces.map((x) => P[pIndex[x]].good));
      const rows = Object.entries(S.goods).sort(([, a], [, b]) => worth(b.yield) - worth(a.yield));
      L.innerHTML = `<b class="lh">Trade goods <small>per level of development</small></b>` + rows.map(([g, x]) => `<div class="grow ${held.has(g) ? "mine" : ""}">
        <i style="background:${PaxMap.GOOD_COLOR[g]}"></i><span>${x.icon} ${esc(x.name)}</span><small>${esc(PaxMap.yieldWords(x.yield))}</small><b class="num">≈${worth(x.yield).toFixed(1)}</b></div>`).join("")
        + `<p class="sub">≈ ducats a year at today's prices. <b>+</b> marks raised workings. Bold: goods you hold.</p>`;
    }
    else if (mode === "diplomacy" && focus < 0 || mode === "diplomacy" && focus === me) L.innerHTML = `<b class="lh">How the courts stand with you</b>
      <div class="ramp" style="background:linear-gradient(90deg,${[-60, -30, 0, 30, 60].map(PaxMap.OPINION).join(",")})"></div>
      <div class="rampends"><span>hostile −60</span><span>neutral</span><span>friendly +60</span></div>
      <div class="row"><i style="background:#e3bd5c"></i>You</div><div class="row"><i style="background:#2f5f9a"></i>Allied</div>
      <div class="row"><i style="background:#5c1712"></i>At war</div><div class="row"><i style="background:#cfc6ae"></i>Independent minor</div>
      <p class="sub">Over each capital: ⚔ war · 🤝 alliance · 📜 pact, truce or tribute · ✖ rival · ♥ calls you friend. Click a nation to see its own wars and allies.</p>`;
    else if (mode === "diplomacy") {
      L.innerHTML = `<b class="lh">Seen from ${esc(N[focus].name)}</b><div class="row"><i style="background:#e3bd5c"></i>${esc(N[focus].name)}</div>
        <div class="row"><i style="background:#2f5f9a"></i>Its allies</div><div class="row"><i style="background:#5c1712"></i>Its enemies</div>
        <div class="row"><i style="background:#8f897c"></i>Neither</div><button class="btn" id="dipback">Back to how the courts see you</button>`;
      $("dipback").onclick = () => { focus = -1; picked = -1; render(); };
    }
    else L.innerHTML = `<div class="row"><i style="background:var(--free)"></i>Independent minor</div><div class="row">? Hidden by the fog of war</div>
      <div class="row"><span style="color:#8a6420">★</span> Capital <span style="margin-left:8px">⚑</span> General</div>
      <div class="row"><i style="border:2px solid #3f8f55"></i>March <i style="border:2px solid #b8392b"></i>Attack</div>`;
  }
  function tooltip(i, evt) {
    const p = prov(i), out = unbundle(p.output_per_turn).map((v, k) => `${RES[k][2]} ${v}`).join("&ensp;");
    let extra = mode === "terrain" ? `${PaxMap.TERRAIN_ICON[P[i].terrain]} ${cap(P[i].terrain)}: ${PaxMap.terrainLines(S, P[i].terrain).join(" · ")}` : "Click to select";
    if (picked >= 0 && owned(picked) && i !== picked) {
      const t = targetsFrom(picked).find(([j]) => j === i), n = KINDS.reduce((sum, k) => sum + force(picked)[k], 0);
      if (t && t[1] === "move") extra = `Right-click to march ${n} regiments here`;
      if (t && t[1] === "attack") { const c = odds(picked, i); extra = `Right-click to attack with ${n}${c !== null ? `: ${Math.round(c * 100)}% to win` : ""}`; }
    }
    $("tip").innerHTML = `<b class="t">${esc(P[i].name)}</b><div class="kv">
      <span>Owner</span><b>${p.owner ? esc(nameOf(p.owner)) : "Independent"}</b>
      <span>Development</span><b>${p.development}</b><span>Regiments</span><b>${p.troops === null ? "hidden" : `${p.troops}${p.army && p.troops ? ` <small>${KINDS.filter((k) => p.army[k]).map((k) => `${UICON[k]}${p.army[k]}`).join(" ")}</small>` : ""}`}</b>
      ${M[p.id] && p.monument !== null ? `<span>Monument</span><b>${esc(M[p.id].name)} ${p.monument ? "★".repeat(p.monument) : "(a site)"}</b>` : ""}
      ${p.general ? `<span>General</span><b>${esc(p.general.name)} ${stars(p.general.skill)}</b>` : ""}
      <span>Per year</span><b class="num">${out}</b></div><div class="hint">${extra}</div>`;
    const tip = $("tip"), r = $("mapwrap").getBoundingClientRect();
    let x = evt.clientX - r.left + 16, y = evt.clientY - r.top + 16;
    if (x + 280 > r.width) x -= 300; if (y + 160 > r.height) y -= 180;
    tip.style.left = x + "px"; tip.style.top = y + "px"; tip.style.display = "block";
  }

  // ------------------------------------------------------------------ render
  function render() {
    $("myshield").innerHTML = PaxMap.flag(N[me].id, N[me].color, 34);
    $("myname").textContent = N[me].name;
    $("year").textContent = V.year;
    $("turnlabel").textContent = `Turn ${V.turn} of ${V.max_turns}`;
    document.querySelectorAll(".modes .btn").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === mode));
    const fallen = !V.me.provinces.length;
    banner();
    $("endturn").textContent = G.finished ? "Game over" : fallen ? "Next year" : G.submitted ? "Send again" : "End the year";
    $("endturn").disabled = G.finished || !!(TABLE && G.table && G.table.closed);
    treasury(); map.paint(world()); map.pick(picked);
    map.setArrows(orders.filter((o) => o.type === "move" || o.type === "attack").map((o) => [pIndex[o.origin], pIndex[o.target], o.type, o.regiments]));
    deed(); office(); ordersBox(); legend();
  }

  $("endturn").onclick = endTurn;
  $("zin").onclick = () => map.zoomAt(1 / 1.4); $("zout").onclick = () => map.zoomAt(1.4);
  $("zhome").onclick = () => map.home(V.me.provinces.map((p) => pIndex[p]));
  window.addEventListener("keydown", (e) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
    if (e.key >= "1" && e.key <= String(MODES.length)) { mode = MODES[+e.key - 1][0]; render(); }
    if (e.key === "Escape") { if ($("modal").classList.contains("open")) $("modal").classList.remove("open"); else { picked = -1; if (mode === "diplomacy") focus = -1; render(); } }
  });
  await load();
  requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add("ready")));
})();
