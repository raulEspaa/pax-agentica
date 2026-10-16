// Pax Agentica: play one nation. You see your NationView (fog of war included), queue Orders,
// and end the year. The server resolves the turn with every other ruler and sends the new view.
"use strict";

(async () => {
  const {esc, mix, devColor, cap, costText, RES, BICON, UICON, ICON, BAD, TERRAIN} = PaxMap;
  const $ = (id) => document.getElementById(id);
  const S = await (await fetch("/api/static")).json();
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
  async function load() { G = await (await fetch("/api/game")).json(); afterLoad(); }
  async function endTurn() {
    const button = $("endturn"); button.disabled = true; button.textContent = "The year passes…";
    try {
      const r = await fetch("/api/turn", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({actions: orders})});
      if (!r.ok) { const body = await r.json().catch(() => ({})); throw new Error(body.detail ? JSON.stringify(body.detail) : r.statusText); }
      const before = V;
      G = await r.json(); orders = []; picked = -1; afterLoad(); report(before);
    } catch (err) { flash(`The orders could not be sent: ${err.message}`); render(); }
  }
  function afterLoad() {
    V = G.view; me = nIndex[G.human];
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
  const owned = (i) => prov(i).owner === G.human;
  const nameOf = (nid) => N[nIndex[nid]].name;
  const relation = (nid) => {
    const war = V.me.wars.find((w) => w.enemy === nid);
    const t = (kind) => V.me.treaties.find((x) => x.partner === nid && x.kind === kind);
    return {war, alliance: t("alliance"), pact: t("non_aggression"), truce: t("truce")};
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
      if (o.type === "develop") sub(unbundle(prov(pIndex[o.province]).develop_cost));
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
    if (P[origin].sea.includes(target)) bonus += R.sea;
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
      const o = prov(j).owner;
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
    barracks: "higher manpower cap"};
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
    const i = picked, p = prov(i), o = p.owner === null ? -1 : nIndex[p.owner], mine = owned(i);
    const out = unbundle(p.output_per_turn), extra = unbundle(p.building_output_per_turn);
    const queued = orders.filter((x) => x.type === "build" && pIndex[x.province] === i).map((x) => bIndex[x.building]);
    const info = PaxMap.deedInfo(S, i, {owner: o, isCapital: p.is_capital, dev: p.development, troops: p.troops, monument: p.monument,
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
      const tabs = [["economy", "💰 Economy"], ["buildings", `🏗 Buildings <small>${p.buildings.length + queued.length}/${info.slots}</small>`],
        ["army", `⚔ Army <small>${here}</small>`]];
      body += `<nav class="deedtabs" role="tablist">${tabs.map(([id, label]) =>
        `<button role="tab" aria-selected="${ownTab === id}" class="${ownTab === id ? "on" : ""}" data-dtab="${id}">${label}</button>`).join("")}</nav>`;
      if (ownTab === "economy") {
        const dev = unbundle(p.develop_cost), maxDev = V.me.modifiers.max_development;
        const devQueued = orders.some((x) => x.type === "develop" && pIndex[x.province] === i);
        const next = p.development + 1, slotOpens = next % R.slotEvery === 0;
        const devWhy = p.development >= maxDev ? `development is at its ceiling (${maxDev})` : devQueued ? "already ordered this year" : !affordable(dev, t) ? "too costly for now" : "";
        body += info.production + `<section><div class="card ${devWhy ? "blocked" : "ready"}">
            <div class="cardhead"><span class="ic">🏛</span><div><b>Develop to ${Math.min(next, maxDev)}</b>
              <div class="gain">${p.development < maxDev ? gainText(preview.develop) || "<span>more score</span>" : ""}<span>+1 score</span></div></div></div>
            <p class="note">${slotOpens ? "<b>Opens a new building slot.</b> " : `Next building slot at development ${Math.ceil(next / R.slotEvery) * R.slotEvery}. `}Score is what wins the game.</p>
            <div class="act"><button class="btn" data-act="develop" ${devWhy ? "disabled" : ""}>${devWhy ? cap(devWhy) : "Develop"}</button><span class="cost">${costText(dev)}</span></div></div></section>`;
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
          const gives = gainText((built ? preview.built || {} : preview.buildings || {})[b.id]);
          const what = [gives, PERK[b.id] ? `<span>${esc(PERK[b.id])}</span>` : ""].filter(Boolean).join("") || "<span>—</span>";
          const state = built ? "built" : ordered ? "ordered" : tech ? "locked" : why ? "blocked" : "ready";
          return [["built", "ordered", "ready", "blocked", "locked"].indexOf(state), `<div class="tile ${b.category} ${state}" title="${esc(b.name)}: ${esc(b.effect)}.${b.tech ? ` Needs ${b.tech[0]} technology ${b.tech[1]}.` : ""}">
            <span class="gain top">${what}</span><span class="ic">${BICON[b.id]}</span><b>${esc(b.name)}${built ? " ✓" : ordered ? " ⏳" : ""}${b.unique ? ` <small title="A great work: one per realm">★</small>` : ""}</b>
            ${built || ordered ? "" : `<span class="cost">${costText(cost)}</span><button class="btn" data-build="${b.id}" ${why ? "disabled" : ""}>${why || "Build"}</button>`}</div>`];
        }).sort((x, y) => x[0] - y[0]).map((x) => x[1]).join("");
        body += `<section>${info.slotsHtml}<div class="tiles">${tiles}</div>
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
          const why = !price ? `needs ${B[u.requires].name.toLowerCase()}` : !affordable(cost, t) ? "too costly" : "";
          return `<div class="levy ${price ? "" : "blocked"}"><span class="ic">${UICON[u.id]}</span>
            <div><b>${esc(u.name)}</b><small>attack ${u.attack}, defence ${u.defence}${terrainNote(u) ? `; ${terrainNote(u)}` : ""}</small></div>
            ${price ? stepper(`recruit_${u.id}`, n, 99) : ""}
            <button class="btn" data-recruit="${u.id}" ${why ? "disabled" : ""}>${why ? cap(why) : "Recruit"}</button>
            ${price ? `<span class="cost">${costText(cost)}</span>` : ""}</div>`;
        }).join("");
        body += `<section><h4>The garrison</h4><div class="units">${comp}</div>
          <p class="note">On ${esc(ground)} they defend with a strength of ${strength(now, ground, false).toFixed(1)}${mixed >= 3 ? `, and fight ${Math.round((R.combinedBonus[mixed] || R.combinedBonus[3]) * 100)}% harder for their combined arms` : ""}.</p></section>
          <section><h4>March</h4><div class="actions">
          <div class="row"><button class="btn" id="mixmode">${pickMix ? "Send a fair share instead" : "Choose regiments by kind"}</button></div>
          ${chooser}
          ${leader}
          ${here > 0 && marches ? `<div class="row">${marches}</div>` : `<p class="note">${here > 0 ? "No province to march to." : "No regiments here."}</p>`}
          <p class="note">Cavalry charges best on plains; every tenth of an attacking army in guns knocks a fort level off.</p></div></section>
          <section><h4>Levy</h4><div class="levies">${levy}</div>
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
    const scroll = box.scrollTop;
    box.innerHTML = info.header + info.facts + body;
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
    box.querySelectorAll("[data-monument]").forEach((b) => b.onclick = () => queue({type: "upgrade_monument", province: P[i].id}));
    box.querySelectorAll("[data-march]").forEach((b) => b.onclick = () => march(i, +b.dataset.march, b.dataset.kind));
    box.querySelectorAll("[data-act]").forEach((b) => b.onclick = () => {
      const id = P[i].id, act = b.dataset.act;
      if (act === "develop") queue({type: "develop", province: id});
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
      else { box.dataset[name] = v; if (name.startsWith("recruit")) deed(); } };
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
  function realmTab() {
    const inc = unbundle(V.me.income_per_turn), up = unbundle(V.me.army_upkeep_per_turn), now = unbundle(V.me.resources), after = projected();
    const mine = V.me.provinces.map((id) => pIndex[id]);
    const land = [0, 0, 0, 0, 0];
    mine.forEach((i) => unbundle(prov(i).output_per_turn).forEach((v, k) => (land[k] += v)));
    const rows = RES.map(([, label, ic], k) => {
      const mod = inc[k] - land[k], net = inc[k] - up[k];
      return `<tr><td>${ic} ${label}</td><td>${land[k]}</td><td>${mod ? sign(mod) : ""}</td><td class="${up[k] ? "neg" : ""}">${up[k] ? "−" + up[k] : ""}</td>
        <td class="${net < 0 ? "neg" : "pos"}">${sign(net)}</td><td>${now[k]}${after[k] !== now[k] ? ` → ${after[k]}` : ""}</td></tr>`; }).join("");
    const short = [];
    if (now[3] + inc[3] < up[3]) short.push("Your granaries will not feed the army next year: some regiments will desert.");
    if (now[0] + inc[0] < up[0]) short.push("The treasury cannot pay the army next year: some regiments will desert.");
    const table = mine.sort((a, b) => prov(b).development - prov(a).development).map((i) => {
      const p = prov(i), out = unbundle(p.output_per_turn);
      return `<tr class="click" data-p="${i}"><td>${esc(P[i].name)}${p.is_capital ? " ★" : ""}${p.unrest ? " 🔥" : ""}</td><td>${p.development}</td>
        <td>${p.buildings.length}/${p.building_slots}</td>${out.map((v) => `<td>${v}</td>`).join("")}</tr>`; }).join("");
    return `<div class="pad"><h4>The year's balance</h4>
      <table class="grid num"><thead><tr><th></th><th title="What your provinces yield">Land</th><th title="Stability and economy technology">Mods</th><th title="Army pay and grain">Army</th><th>Net</th><th>Treasury</th></tr></thead><tbody>${rows}</tbody></table>
      ${short.map((s) => `<p class="warn">${s}</p>`).join("")}
      ${threats().map((t) => `<p class="warn">${threatText(t)}</p>`).join("")}
      <p class="sub">Stability ${sign(V.me.stability)} and economy technology ${V.me.technology.economy} raise ducats; economy technology raises grain too.
        The manpower pool stops at ${V.me.manpower_cap}.</p>
      <h4>Provinces</h4>
      <table class="grid num"><thead><tr><th>Province</th><th>Dev.</th><th>Bldg.</th>${RES.map(([, label, ic]) => `<th title="${label}">${ic}</th>`).join("")}</tr></thead><tbody>${table}</tbody></table>
      <p class="sub">★ capital. 🔥 in unrest: a conquered province yields nothing for a few years.</p></div>`;
  }
  function armyTab() {
    const mine = V.me.provinces.map((id) => pIndex[id]);
    const options = (sel) => mine.map((i) => `<option value="${P[i].id}" ${i === sel ? "selected" : ""}>${esc(P[i].name)}</option>`).join("");
    const generals = V.me.generals.map((g) => {
      const goes = generalPositions().get(g.id), from = pIndex[g.province];
      const plan = goes === from ? "" : goes === -1 ? ", leading an attack" : `, going to ${esc(P[goes].name)}`;
      return `<div class="general-card"><span class="stars" title="Skill ${g.skill} of 3: +${Math.round(R.generalBonus * 100 * g.skill)}% battle power">${stars(g.skill)}</span>
        <div><b>${esc(g.name)}</b> <span class="sub">in ${esc(P[from].name)}${plan}</span>
        <div class="row"><select class="field" data-gsel="${g.id}" aria-label="Send ${esc(g.name)} to">${options(pIndex[g.province])}</select>
        <button class="btn" data-assign="${g.id}">Send</button><button class="btn" data-goto="${pIndex[g.province]}">Show</button></div></div></div>`; }).join("");
    const armies = mine.filter((i) => troopsAfter(i) > 0).sort((a, b) => troopsAfter(b) - troopsAfter(a)).map((i) => {
      const g = generalAt(i);
      return `<tr class="click" data-p="${i}"><td>${esc(P[i].name)}</td><td>${troopsAfter(i)}</td><td>${g ? esc(g.name) : ""}</td></tr>`; }).join("");
    const wars = V.me.wars.map((w) => `<span class="chip war">${esc(nameOf(w.enemy))}${w.attacks_allowed_from_turn > V.turn ? ", mobilising" : ""}</span>`).join("");
    return `<div class="pad"><h4>The army</h4>
      <div class="units office-units">${U.map((u) => `<div class="unit ${V.me.army[u.id] ? "" : "none"}" title="${esc(u.name)}: ${esc(u.role)}"><span class="ic">${UICON[u.id]}</span><b>${V.me.army[u.id]}</b><small>${esc(u.id)}</small></div>`).join("")}</div>
      <p class="sub">${V.me.regiments} regiments, costing ${costText(unbundle(V.me.army_upkeep_per_turn))} a year. Manpower ${V.me.resources.manpower} of ${V.me.manpower_cap}.
        Military technology ${V.me.technology.military}: +${Math.round(T[0].perLevel * 100 * V.me.technology.military)}% battle power.</p>
      <div class="chips">${wars || `<span class="muted">At peace.</span>`}</div>
      <h4>Generals, ${V.me.generals.length} of ${V.me.modifiers.max_generals}</h4>${generals || `<p class="muted">No general serves you.</p>`}
      ${V.me.generals.length < V.me.modifiers.max_generals ? `<div class="row"><select class="field" id="hireat" aria-label="Appoint a general in">${options(pIndex[V.me.capital])}</select>
        <button class="btn" id="hire" ${affordable(R.generalCost) ? "" : "disabled"}>Appoint a general</button><span class="sub">${costText(R.generalCost)}</span></div>` : ""}
      <p class="sub">A general adds ${Math.round(R.generalBonus * 100)}% battle power per star to the regiments he leads or defends with. He falls if his province is taken.</p>
      <h4>Armies</h4><table class="grid num"><thead><tr><th>Province</th><th>Regiments</th><th>General</th></tr></thead><tbody>${armies}</tbody></table>
      <p class="sub">Click an army to select it, then right-click on the map where it should go.</p></div>`;
  }
  const BRANCH_IC = {military: "⚔", economy: "💰", engineering: "⚒"};
  function techTab() {
    const doing = researching();
    const columns = T.map((b) => {
      const level = V.me.technology[b.id], cost = V.me.research_costs[b.id];
      const nodes = b.levels.map((step, k) => {
        const n = k + 1, done = n <= level, next = n === level + 1;
        const unlocked = B.filter((x) => x.tech && x.tech[0] === b.id && x.tech[1] === n);
        const state = done ? "done" : next ? (doing && doing.branch === b.id ? "doing" : "next") : "locked";
        const button = next && cost ? (doing && doing.branch === b.id ? `<div class="sub">Researching this year</div>`
          : `<button class="btn" data-research="${b.id}" ${doing || !affordable(unbundle(cost)) ? "disabled" : ""}>Research</button><div class="sub">${costText(unbundle(cost))}</div>`) : "";
        return `<div class="node ${state}" title="${esc(step.name)}: ${esc(step.unlocks)}. ${esc(step.lore || "")}">
          <div class="lvl">${done ? "✓" : n}</div><b>${esc(step.name)}</b>
          <div class="unl">${unlocked.map((x) => `<span class="chipb">${BICON[x.id]} ${esc(x.name)}</span>`).join("") || esc(cap(step.unlocks))}</div>
          <div class="sub">+${Math.round(b.perLevel * 100)}% ${b.id === "engineering" ? "cheaper works" : b.id === "economy" ? "income" : "battle power"}</div>
          ${next && step.lore ? `<div class="lore">${esc(step.lore)}</div>` : ""}${button}</div>`;
      }).join(`<div class="link"></div>`);
      return `<div class="branch"><h5>${BRANCH_IC[b.id]} ${b.name}<small>${level} of ${R.maxTech}</small></h5>${nodes}</div>`;
    }).join("");
    const rivals = V.nations.filter((n) => n.alive).map((n) => `<tr><td>${esc(n.name)}</td>${T.map((b) => `<td>${n.technology[b.id]}</td>`).join("")}</tr>`).join("");
    return `<div class="pad"><h4>The tree of learning</h4>
      <p class="sub">One research a year. Each level gives its branch's bonus and a milestone: new buildings, new powers.
        ${V.me.modifiers.research_discount ? `Your chancellor makes research ${Math.round(V.me.modifiers.research_discount * 100)}% cheaper.` : "A chancellor would make it cheaper."}</p>
      <div class="tree">${columns}</div>
      <h4>Other courts</h4><table class="grid num"><thead><tr><th>Nation</th>${T.map((b) => `<th>${b.name}</th>`).join("")}</tr></thead><tbody>${rivals}</tbody></table></div>`;
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
    return `<div class="pad"><h4>The crown</h4>${rulerHtml}
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
      : `${from} calls you to arms against ${esc(nameOf(p.enemy))}. Ignoring it ends the alliance.`;
    const state = answered ? (answered.accept ? `<span class="ok">You accept.</span>` : answered.counter ? `<span class="ok">You counter.</span>` : `<span class="warn">You refuse.</span>`) : "";
    const canCounter = p.kind === "peace" || p.kind === "trade";
    return `<div class="proposal"><div>${what} ${state}</div>${p.note ? `<blockquote>“${esc(p.note)}”</blockquote>` : ""}
      <div class="row"><button class="btn" data-answer="${p.id}" data-accept="1">Accept</button><button class="btn" data-answer="${p.id}" data-accept="0">Refuse</button>
      ${canCounter ? `<button class="btn" data-counter="${p.id}">Counter-offer…</button>` : ""}</div></div>`;
  }
  function diplomacyTab() {
    const list = V.nations.filter((n) => n.alive).map((n) => {
      const color = N[nIndex[n.id]].color, waiting = V.proposals_to_answer.filter((p) => p.sender === n.id).length;
      return `<div class="nrow court ${nIndex[n.id] === focus ? "sel" : ""}" data-n="${n.id}" tabindex="0">
        ${n.ruler ? portrait(n.ruler, color, 38) : `<span class="shield" style="background:${color}"></span>`}
        <div><b>${esc(n.name)}</b>${waiting ? ` <span class="count">${waiting}</span>` : ""}<small>${n.ruler ? `${esc(n.ruler.title)} ${esc(n.ruler.name)}` : ""}</small>
          <div class="chips">${opinionBadge(n.opinion_of_you, "Their opinion of you: ")}${stanceChip(n.stances[G.human], "toward you")}${stanceChip(V.me.stances[n.id], "yours")}${chipsFor(n.id)}</div></div></div>`;
    }).join("");
    const alive = focus >= 0 && focus !== me && V.nations.find((n) => n.id === N[focus].id)?.alive;
    const voices = G.chronicle.flatMap((y) => y.events.filter((e) => e.kind === "proclamation").map((e) => [y.year, e])).slice(0, 5)
      .map(([year, e]) => `<li><span class="yr">${year}</span> <b>${esc(nameOf(e.data.sender))}</b>: <q>${esc(e.data.text)}</q></li>`).join("");
    return `${voices ? `<div class="pad voices"><h4>Voices of Europe</h4><ul class="history">${voices}</ul></div>` : ""}
      <div class="courts">${list}</div>${alive ? desk(N[focus].id) : `<p class="muted pad">Pick a court to treat with it.</p>`}`;
  }
  const stanceChip = (stance, whose) => stance && stance !== "neutral"
    ? `<span class="chip stance ${stance}" title="${whose === "yours" ? "Your declared stance" : "Their declared stance toward you"}">${whose === "yours" ? "your " : ""}${stance}${whose === "yours" ? "" : " of yours"}</span>` : "";
  const borderOf = (owner, other) => V.provinces.filter((p) => p.owner === owner && !p.is_capital
    && [...p.neighbors, ...p.sea_neighbors].some((x) => prov(pIndex[x]).owner === other));
  function desk(nid) {
    const n = V.nations.find((x) => x.id === nid), r = relation(nid), name = esc(n.name), color = N[nIndex[nid]].color;
    const pending = (...kinds) => V.proposals_sent.some((p) => p.recipient === nid && kinds.includes(p.kind)) || orders.some((o) => o.target === nid && kinds.includes(o.type));
    const treaties = [r.alliance && "your alliance", r.pact && "your non-aggression pact", r.truce && "the truce"].filter(Boolean);
    const allies = V.me.treaties.filter((t) => t.kind === "alliance").map((t) => t.partner).filter((a) => !V.nations.find((x) => x.id === a).at_war_with.includes(nid));
    const ruler = n.ruler, mine = V.me.opinions[nid] || 0;
    const tech = (t) => T.reduce((sum, b) => sum + t[b.id], 0);
    const bound = V.me.treaties.filter((t) => t.partner === nid && (t.kind === "tribute" || t.kind === "army_limit")).map((t) =>
      t.kind === "tribute" ? `${t.payer === G.human ? "You pay" : `${name} pays`} ${t.amount} ducats a year until ${R.startYear + t.until_turn - 1}`
        : `${t.payer === G.human ? "Your" : `${name}'s`} army is limited to ${t.amount} regiments until ${R.startYear + t.until_turn - 1}`);
    const theirs = V.proposals_to_answer.filter((p) => p.sender === nid).map(proposalCard).join("");
    const sent = V.proposals_sent.filter((p) => p.recipient === nid).map((p) => `<div class="sub">You await their answer to your ${p.kind.replace("_", " ")} proposal.</div>`).join("");
    const history = G.chronicle.flatMap((y) => y.events.filter((e) => e.nations.includes(nid) && e.nations.includes(G.human) && !["moved", "recruited"].includes(e.kind))
      .map((e) => `<li><span class="yr">${y.year}</span> ${ICON[e.kind] || "•"} ${esc(e.kind === "message" ? `${e.data.sender === G.human ? "You wrote" : "They wrote"}: “${e.data.text}”` : e.summary)}</li>`)).slice(0, 8).join("");
    let html = `<div class="pad desk">
      <div class="audience">${ruler ? portrait(ruler, color, 84) : ""}
        <div><b>${ruler ? `${esc(ruler.title)} ${esc(ruler.name)}` : name}</b><div class="sub">of ${name}${ruler ? `, aged ${ruler.age}` : ""}</div>
          ${ruler && ruler.bio ? `<p class="lore">${esc(ruler.bio)}</p>` : ""}${ruler ? traitChips(ruler.traits) : ""}</div></div>
      <div class="moods"><div><span class="sub">They think of you</span>${opinionBadge(n.opinion_of_you)}<i class="bar"><b style="left:${50 + n.opinion_of_you / 2}%"></b></i></div>
        <div><span class="sub">You think of them</span>${opinionBadge(mine)}<i class="bar"><b style="left:${50 + mine / 2}%"></b></i></div></div>
      <table class="grid num versus"><thead><tr><th></th><th>You</th><th>${name}</th></tr></thead><tbody>
        <tr><td>Provinces</td><td>${V.me.provinces.length}</td><td>${n.provinces}</td></tr>
        <tr><td>Score</td><td>${V.me.score}</td><td>${n.score}</td></tr>
        <tr><td>Generals</td><td>${V.me.generals.length}</td><td>${n.generals}</td></tr>
        <tr><td>Technology</td><td>${tech(V.me.technology)}</td><td>${tech(n.technology)}</td></tr></tbody></table>
      <div class="chips" style="margin-top:6px">${chipsFor(nid) || `<span class="muted">No treaty.</span>`}</div>
      <div class="stances"><span class="sub">${name} counts as friends ${listOf(n.stances, "friend")}, as rivals ${listOf(n.stances, "rival")}.</span>
        <div class="row"><span class="sub">You count them</span>${["friend", "neutral", "rival"].map((st) => {
          const now = (V.me.stances[nid] || "neutral") === st, queued = orders.some((o) => o.type === "set_stance" && o.target === nid && o.stance === st);
          return `<button class="btn ${now ? "on" : ""}" data-stance="${st}" ${now || queued ? "disabled" : ""}>${cap(st)}</button>`; }).join("")}</div>
        <p class="sub">Stances are public. A friend warms to you every year, a rival cools, and your regiments fight 5% harder against a declared rival.</p></div>
      ${bound.map((b) => `<p class="sub">⚖ ${b}.</p>`).join("")}
      <p class="sub">At war with ${n.at_war_with.map((x) => esc(nameOf(x))).join(", ") || "no one"}; allied with ${n.allies.map((x) => esc(nameOf(x))).join(", ") || "no one"}.</p>
      ${theirs ? `<h4>They propose</h4>${theirs}` : ""}${sent}`;
    const counter = countering && countering.sender === nid ? countering : null;
    if (r.war || (counter && counter.kind === "peace")) html += peaceBuilder(nid, counter && counter.kind === "peace" ? counter : null);
    if (r.war) {
      if (allies.length) html += `<h4>Call your allies</h4><div class="row">${allies.map((a) => `<button class="btn" data-call="${a}">Call ${esc(nameOf(a))}</button>`).join("")}</div>`;
    } else {
      const tradeCounter = counter && counter.kind === "trade" ? counter : null;
      html += `<details ${tradeCounter ? "open" : ""}><summary>${tradeCounter ? "Your counter-offer" : "Trade, gifts and tribute"}</summary>
        <div class="sub">You give</div>${bundleInputs("trade-give", tradeCounter ? tradeCounter.receive : null)}
        <div class="sub">You ask for</div>${bundleInputs("trade-receive", tradeCounter ? tradeCounter.give : null)}
        <textarea id="trade-note" maxlength="300" placeholder="A word to go with it (optional)"></textarea>
        <div class="row">${tradeCounter ? `<button class="btn" data-dip="counter_trade">Send the counter-offer</button><button class="btn" data-dip="drop_counter">Never mind</button>`
          : `<button class="btn" data-dip="propose_trade">Offer the trade</button><button class="btn" data-dip="gift">Send what you give as a gift</button>`}</div>
        <p class="sub">A gift warms them: +1 opinion for every 4 ducats' worth, up to +25.</p></details>
        <details><summary>Treaties</summary><div class="row">
        ${r.alliance ? `<button class="btn" data-cancel="alliance">End the alliance</button>` : `<button class="btn" data-dip="propose_alliance" ${pending("propose_alliance", "alliance") ? "disabled" : ""}>Propose an alliance</button>`}
        ${r.pact ? `<button class="btn" data-cancel="non_aggression">End the pact</button>` : `<button class="btn" data-dip="propose_non_aggression" ${pending("propose_non_aggression", "non_aggression") ? "disabled" : ""}>Propose a pact</button>`}</div>
        <p class="sub">An alliance pleases them (+20), a pact too (+10). Their answer weighs how they see you.</p></details>
        <details><summary>War</summary>${treaties.length ? `<p class="warn">War breaks ${treaties.join(" and ")}: −${R.breakPenalty} stability, and every court in Europe will think less of you.</p>` : ""}
        <p class="sub">Armies mobilise for ${R.mobilization} year before they can attack. ${name}'s allies will be called to arms.</p>
        <div class="row"><button class="btn danger" data-dip="declare_war" ${pending("declare_war") ? "disabled" : ""}>Declare war on ${name}</button></div></details>`;
    }
    return html + `<details><summary>A letter</summary><textarea id="letter" maxlength="500" placeholder="Words do not change the rules, but rulers read them."></textarea>
      <div class="row"><button class="btn" data-dip="send_message">Seal and send</button></div></details>
      ${history ? `<h4>Between your courts</h4><ul class="history">${history}</ul>` : ""}</div>`;
  }
  const listOf = (stances, kind) => { const xs = Object.entries(stances || {}).filter(([, v]) => v === kind).map(([k]) => k === G.human ? "you" : esc(nameOf(k)));
    return xs.length ? xs.join(", ") : "no one"; };
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
    const proposals = V.proposals_to_answer.map(proposalCard).join("");
    const letters = V.last_turn_events.filter((e) => e.kind === "message" && e.data.sender !== G.human)
      .map((e) => `<div class="item">From <b>${esc(nameOf(e.data.sender))}</b><div class="letter">${esc(e.data.text)}</div></div>`).join("");
    const replies = V.last_turn_events.filter((e) => ["proposal_rejected", "proposal_expired", "proposal_countered", "treaty_signed", "trade_completed", "trade_failed", "peace_signed", "province_ceded", "tribute_paid"].includes(e.kind) && e.nations.includes(G.human))
      .map((e) => `<div class="item">${ICON[e.kind] || "•"} ${esc(e.summary)}</div>`).join("");
    return `${proposals ? `<div class="pad">${proposals}</div>` : `<p class="muted pad">No proposal waits for your answer.</p>`}
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
      const count = b.dataset.tab === "letters" ? V.proposals_to_answer.filter((p) => !orders.some((o) => o.type === "respond" && o.proposal_id === p.id)).length : 0;
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
      if (kind === "declare_war" && !confirm(`Declare war on ${nameOf(nid)}?`)) return;
      queue({type: kind, target: nid});
    });
    panel.querySelectorAll("[data-stance]").forEach((b) => b.onclick = () => {
      orders = orders.filter((o) => !(o.type === "set_stance" && o.target === nid));
      queue({type: "set_stance", target: nid, stance: b.dataset.stance});
    });
    panel.querySelectorAll("[data-cancel]").forEach((b) => b.onclick = () => queue({type: "cancel_treaty", target: nid, kind: b.dataset.cancel}));
    panel.querySelectorAll("[data-call]").forEach((b) => b.onclick = () => queue({type: "call_to_arms", target: b.dataset.call, enemy: nid}));
    panel.querySelectorAll("[data-counter]").forEach((b) => b.onclick = () => {
      countering = V.proposals_to_answer.find((p) => p.id === +b.dataset.counter);
      focus = nIndex[countering.sender]; tab = "diplomacy"; render();
    });
    panel.querySelectorAll("[data-answer]").forEach((b) => b.onclick = () => {
      const id = +b.dataset.answer;
      orders = orders.filter((o) => !(o.type === "respond" && o.proposal_id === id));
      queue({type: "respond", proposal_id: id, accept: b.dataset.accept === "1"});
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
      case "build": return `Build ${B[bIndex[o.building]].name.toLowerCase()} in ${pn(o.province)}`;
      case "boost_stability": return "Raise stability";
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
      case "propose_peace": { const t = termsText(o, G.human); return `🕊 Offer peace to ${nn(o.target)}${t ? `: ${t}` : ", white peace"}`; }
      case "propose_trade": return `Offer ${nn(o.target)} ${costText(unbundle(o.give))} for ${costText(unbundle(o.receive))}`;
      case "gift": return `Give ${nn(o.target)} ${costText(unbundle(o.resources))}`;
      case "cancel_treaty": return `End the ${o.kind.replace("_", "-")} treaty with ${nn(o.target)}`;
      case "call_to_arms": return `Call ${nn(o.target)} to arms against ${nn(o.enemy)}`;
      case "send_message": return `Letter to ${nn(o.target)}`;
      case "proclaim": return `📣 Proclaim to Europe`;
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
      .filter((e) => e.nations.includes(G.human) || ["war_declared", "nation_eliminated", "treaty_broken", "game_over", "proclamation"].includes(e.kind))
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
        <p><a href="/replay" target="_blank">Watch the whole game as a replay</a></p></div>` : "";
    $("sheet").innerHTML = `<h2 id="modaltitle">${G.finished ? "The end of an age" : `The year ${V.year - 1}`}</h2>${ending}${crowned}${discoveries}${works}${G.finished ? "" : danger}
      ${won.length ? `<p>Your realm gained ${won.map((p) => esc(P[pIndex[p]].name)).join(", ")}.</p>` : ""}
      ${lost.length ? `<p style="color:#8f2f22">You lost ${lost.map((p) => esc(P[pIndex[p]].name)).join(", ")}.</p>` : ""}
      <ul>${items || "<li>A quiet year for your realm.</li>"}</ul>
      <button class="btn" id="closemodal">Continue</button>`;
    $("modal").classList.add("open"); $("closemodal").focus();
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
    const generals = new Map();
    V.provinces.forEach((p, i) => { if (p.general) generals.set(i, {nation: nIndex[p.general.nation], name: p.general.name, skill: p.general.skill}); });
    return {
      mode, focus: f, relations, alive, capitals, generals,
      owner: V.provinces.map((p) => (p.owner === null ? -1 : nIndex[p.owner])),
      troops: V.provinces.map((p) => p.troops), dev: V.provinces.map((p) => p.development),
      buildings: V.provinces.map((p) => p.buildings.map((b) => bIndex[b])),
      events: V.last_turn_events.filter((e) => e.province).map((e) => [e.kind, pIndex[e.province], e.nations.map((x) => nIndex[x])]),
    };
  }
  const MODES = [["political", "Political"], ["terrain", "Terrain"], ["development", "Development"], ["diplomacy", "Diplomacy"]];
  MODES.forEach(([id, label], k) => { const b = document.createElement("button"); b.className = "btn"; b.textContent = label;
    b.title = `${label} map mode (${k + 1})`; b.dataset.mode = id; b.onclick = () => { mode = id; render(); };
    document.querySelector(".modes").appendChild(b); });
  function legend() {
    const L = $("legend");
    if (mode === "terrain") L.innerHTML = Object.entries(TERRAIN).map(([t, c]) => `<div class="row"><i style="background:${c}"></i>${cap(t)}</div>`).join("");
    else if (mode === "development") L.innerHTML = `Development<div class="ramp" style="background:linear-gradient(90deg,${[1, 4, 6, 8, 10].map(devColor).join(",")})"></div>`;
    else if (mode === "diplomacy") L.innerHTML = `<div class="row"><i style="background:#e3bd5c"></i>${esc(N[focus >= 0 ? focus : me].name)}</div>
      <div class="row"><i style="background:#5aa56f"></i>Allies</div><div class="row"><i style="background:#c9a54a"></i>Pacts and truces</div><div class="row"><i style="background:#c4473b"></i>At war</div>`;
    else L.innerHTML = `<div class="row"><i style="background:var(--free)"></i>Independent minor</div><div class="row">? Hidden by the fog of war</div>
      <div class="row"><span style="color:#8a6420">★</span> Capital <span style="margin-left:8px">⚑</span> General</div>
      <div class="row"><i style="border:2px solid #3f8f55"></i>March <i style="border:2px solid #b8392b"></i>Attack</div>`;
  }
  function tooltip(i, evt) {
    const p = prov(i), out = unbundle(p.output_per_turn).map((v, k) => `${RES[k][2]} ${v}`).join("&ensp;");
    let extra = "Click to select";
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
    $("myshield").style.background = N[me].color;
    $("myname").textContent = N[me].name;
    $("year").textContent = V.year;
    $("turnlabel").textContent = `Turn ${V.turn} of ${V.max_turns}`;
    document.querySelectorAll(".modes .btn").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === mode));
    const fallen = !V.me.provinces.length;
    $("banner").innerHTML = G.finished ? `<div class="over">👑 ${esc(G.winner ? nameOf(G.winner) + " wins." : "The game is over.")} <a href="/replay" target="_blank">Watch the replay</a></div>`
      : fallen ? `<div class="banner">Your realm has fallen. You can watch the rest of the game year by year.</div>` : "";
    $("endturn").textContent = G.finished ? "Game over" : fallen ? "Next year" : "End the year";
    $("endturn").disabled = G.finished;
    treasury(); map.paint(world()); map.pick(picked);
    map.setArrows(orders.filter((o) => o.type === "move" || o.type === "attack").map((o) => [pIndex[o.origin], pIndex[o.target], o.type, o.regiments]));
    deed(); office(); ordersBox(); legend();
  }

  $("endturn").onclick = endTurn;
  $("zin").onclick = () => map.zoomAt(1 / 1.4); $("zout").onclick = () => map.zoomAt(1.4);
  $("zhome").onclick = () => map.home(V.me.provinces.map((p) => pIndex[p]));
  window.addEventListener("keydown", (e) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
    if (e.key >= "1" && e.key <= "4") { mode = MODES[+e.key - 1][0]; render(); }
    if (e.key === "Escape") { if ($("modal").classList.contains("open")) $("modal").classList.remove("open"); else { picked = -1; render(); } }
  });
  await load();
  requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add("ready")));
})();
