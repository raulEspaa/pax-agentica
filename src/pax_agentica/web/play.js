// Pax Agentica: play one nation. You see your NationView (fog of war included), queue Orders,
// and end the year. The server resolves the turn with every other ruler and sends the new view.
"use strict";

(async () => {
  const {esc, mix, devColor, cap, costText, RES, BICON, ICON, BAD, TERRAIN} = PaxMap;
  const $ = (id) => document.getElementById(id);
  const S = await (await fetch("/api/static")).json();
  const P = S.provinces, N = S.nations, B = S.buildings, R = S.rules, T = S.tech;
  const pIndex = Object.fromEntries(P.map((p, i) => [p.id, i]));
  const nIndex = Object.fromEntries(N.map((n, i) => [n.id, i]));
  const bIndex = Object.fromEntries(B.map((b, i) => [b.id, i]));
  const unbundle = (obj) => S.resources.map((r) => (obj && obj[r]) || 0);
  const sign = (v) => (v > 0 ? "+" : "") + v;
  const stars = (n) => "★".repeat(n) + "☆".repeat(3 - n);
  const MAX_ORDERS = 50;

  let G = null, V = null, me = -1;                // game payload, my view, my nation index
  let orders = [], mode = "political", picked = -1, focus = -1, tab = "realm", send = Infinity, lead = true;

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
      if (o.type === "recruit") sub(unbundle(prov(pIndex[o.province]).recruit_cost).map((v) => v * o.regiments));
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
  function defence(origin, target) {
    const p = prov(target);
    let bonus = R.fort * p.fort + (p.is_capital ? R.capital : 0);
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
  function odds(from, to) {
    const p = prov(to), n = Math.min(send, troopsAfter(from)), g = lead ? generalAt(from) : null;
    if (p.troops === null) return null;
    return winChance(n * myFactor(g), p.troops, defence(from, to));
  }

  // ------------------------------------------------------------------ selecting and commanding
  function select(i) {
    if (i < 0) return;
    picked = i === picked ? -1 : i;
    send = Infinity; lead = true;
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
    const n = Math.min(send, troopsAfter(from));
    if (n <= 0) return flash(`No regiments left in ${P[from].name}.`);
    const g = lead ? generalAt(from) : null;
    const order = {type: kind, origin: P[from].id, target: P[to].id, regiments: n};
    if (g) order.general = g.id;
    queue(order);
  }

  // ------------------------------------------------------------------ the province deed
  // What a work without a yield does, in a few words for its tile.
  const PERK = {university: "develop 30% cheaper here", armory: "regiments need half the iron", fort: "defenders +25%",
    citadel: "defenders +25% more", training_grounds: "garrison +20%"};
  const gainText = (g) => RES.map(([key, , ic]) => g && g[key] ? `<span>+${g[key]} ${ic}</span>` : "").join("");
  let ownTab = "economy";
  function deed() {
    const box = $("deed");
    if (picked < 0) { box.classList.remove("open"); map.setTargets([]); hint(""); return; }
    const i = picked, p = prov(i), o = p.owner === null ? -1 : nIndex[p.owner], mine = owned(i);
    const out = unbundle(p.output_per_turn), extra = unbundle(p.building_output_per_turn);
    const queued = orders.filter((x) => x.type === "build" && pIndex[x.province] === i).map((x) => bIndex[x.building]);
    const info = PaxMap.deedInfo(S, i, {owner: o, isCapital: p.is_capital, dev: p.development, troops: p.troops,
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
        if (best.length && free > 0) body += `<section><h4>Best works here</h4>${best.map(([b, gain]) =>
          `<div class="act"><span class="ic">${BICON[b.id]}</span><b>${esc(b.name)}</b><span class="gain">${gainText(gain)}</span>
            <button class="btn" data-build="${b.id}" ${affordable(buildCost(b.id), t) ? "" : "disabled"}>Build</button><span class="cost">${costText(buildCost(b.id))}</span></div>`).join("")}</section>`;
      } else if (ownTab === "buildings") {
        const tiles = B.map((b, k) => {
          const built = p.buildings.includes(b.id), ordered = queued.includes(k), cost = buildCost(b.id);
          const needs = b.requires >= 0 && !p.buildings.includes(B[b.requires].id) && !queued.includes(b.requires);
          const tech = b.tech && V.me.technology[b.tech[0]] < b.tech[1];
          const why = built || ordered ? "" : tech ? `🔒 ${cap(b.tech[0])} ${b.tech[1]}` : needs ? `needs a ${B[b.requires].name.toLowerCase()}` : free <= 0 ? "no free slot" : !affordable(cost, t) ? "too costly" : "";
          const gain = gainText((preview.buildings || {})[b.id]);
          const what = built ? "Built" : ordered ? "Ordered" : gain || esc(PERK[b.id] || "");
          const state = built ? "built" : ordered ? "ordered" : tech ? "locked" : why ? "blocked" : "ready";
          return [["built", "ordered", "ready", "blocked", "locked"].indexOf(state), `<div class="tile ${b.category} ${state}" title="${esc(b.name)}: ${esc(b.effect)}.${b.tech ? ` Needs ${b.tech[0]} technology ${b.tech[1]}.` : ""}">
            <span class="ic">${BICON[b.id]}</span><b>${esc(b.name)}</b><span class="gain">${what}</span>
            ${built || ordered ? "" : `<span class="cost">${costText(cost)}</span><button class="btn" data-build="${b.id}" ${why ? "disabled" : ""}>${why || "Build"}</button>`}</div>`];
        }).sort((x, y) => x[0] - y[0]).map((x) => x[1]).join("");
        body += `<section>${info.slotsHtml}<div class="tiles">${tiles}</div>
          <p class="note">A new slot opens every ${R.slotEvery} development. Hover a work to read what it does.</p></section>`;
      } else {
        const recruitN = Math.max(1, +(box.dataset.recruit || 1)), rc = unbundle(p.recruit_cost).map((v) => v * recruitN);
        const marches = targets.map(([j, kind]) => {
          const chance = kind === "attack" ? odds(i, j) : null;
          return `<button class="btn" data-march="${j}" data-kind="${kind}">${kind === "move" ? "➜" : "⚔"} ${esc(P[j].name)}${chance !== null ? ` ${Math.round(chance * 100)}%` : ""}</button>`;
        }).join("");
        const leader = g ? `<label class="leader"><input type="checkbox" id="lead" ${lead ? "checked" : ""}> led by ${esc(g.name)} <span class="stars">${stars(g.skill)}</span></label>`
          : V.me.generals.length < V.me.modifiers.max_generals ? `<div class="act"><button class="btn" data-act="hire" ${affordable(R.generalCost, t) ? "" : "disabled"}>Appoint a general here</button><span class="cost">${costText(R.generalCost)}</span></div>` : "";
        body += `<section><h4>March</h4><div class="actions">
          <div class="act">${stepper("send", Math.min(send, Math.max(here, 1)), Math.max(here, 1))}<span>of ${here} regiments</span></div>
          ${leader}
          ${here > 0 && marches ? `<div class="row">${marches}</div>` : `<p class="note">${here > 0 ? "No province to march to." : "No regiments here."}</p>`}</div></section>
          <section><h4>Levy</h4><div class="actions">
          <div class="act">${stepper("recruit", recruitN, 99)}<button class="btn" data-act="recruit" ${affordable(rc, t) ? "" : "disabled"}>Recruit</button><span class="cost">${costText(rc)}</span></div>
          <div class="act">${stepper("disband", Math.max(1, +(box.dataset.disband || 1)), Math.max(here, 1))}<button class="btn" data-act="disband" ${here > 0 ? "" : "disabled"}>Disband</button><span class="cost">returns ${costText(R.disband)} each</span></div>
          <p class="note">Each regiment eats ${R.grainUpkeep} grain and costs ${R.pay} ducats a year.</p></div></section>`;
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
        const chance = winChance(troopsAfter(best) * myFactor(g), p.troops, defence(best, i));
        const war = p.owner === null || relation(p.owner).war;
        body += `<section><h4>Attack</h4><p class="note" style="font-style:normal">All ${troopsAfter(best)} regiments of ${esc(P[best].name)}${g ? ` under ${esc(g.name)}` : ""}
          against ${p.troops}: <b>${Math.round(chance * 100)}% to win</b>.
          ${war ? `Select ${esc(P[best].name)} and right-click here.` : `You must declare war on ${esc(N[o].name)} first.`}</p></section>`;
      }
      body += info.production + `<section>${info.slotsHtml}</section>`;
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
    box.querySelectorAll("[data-march]").forEach((b) => b.onclick = () => march(i, +b.dataset.march, b.dataset.kind));
    box.querySelectorAll("[data-act]").forEach((b) => b.onclick = () => {
      const id = P[i].id, act = b.dataset.act;
      if (act === "recruit") queue({type: "recruit", province: id, regiments: +(box.dataset.recruit || 1)});
      if (act === "develop") queue({type: "develop", province: id});
      if (act === "disband") queue({type: "disband", province: id, regiments: Math.min(+(box.dataset.disband || 1), troopsAfter(i))});
      if (act === "hire") queue({type: "hire_general", province: id});
    });
    box.querySelectorAll("[data-build]").forEach((b) => b.onclick = () => queue({type: "build", province: P[i].id, building: b.dataset.build}));
  }
  function hint(text) { const h = $("hintbar"); h.textContent = text; h.classList.toggle("show", !!text); }
  function stepper(name, value, max) {
    return `<span class="stepper" data-name="${name}" data-max="${max}"><button type="button" data-d="-1" aria-label="Fewer">−</button>
      <input type="number" min="1" max="${max}" value="${value}" aria-label="${name}"><button type="button" data-d="1" aria-label="More">+</button></span>`;
  }
  function wireStepper(st) {
    const box = $("deed"), input = st.querySelector("input"), name = st.dataset.name, max = +st.dataset.max;
    const set = (v) => { v = Math.max(1, Math.min(max, v || 1)); input.value = v;
      if (name === "send") { send = v; deed(); } else { box.dataset[name] = v; if (name === "recruit") deed(); } };
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
        return `<div class="node ${state}" title="${esc(step.name)}: ${esc(step.unlocks)}">
          <div class="lvl">${done ? "✓" : n}</div><b>${esc(step.name)}</b>
          <div class="unl">${unlocked.map((x) => `<span class="chipb">${BICON[x.id]} ${esc(x.name)}</span>`).join("") || esc(cap(step.unlocks))}</div>
          <div class="sub">+${Math.round(b.perLevel * 100)}% ${b.id === "engineering" ? "cheaper works" : b.id === "economy" ? "income" : "battle power"}</div>${button}</div>`;
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
  function portrait(seed, color, crown, size = 64) { // a bust in silhouette, the court's colours behind
    const r = (() => { let h = 0; for (const c of seed) h = (h * 31 + c.charCodeAt(0)) >>> 0; return (k) => ((h >> k) & 7) / 7; })();
    const hair = ["#2b1a0e", "#5a3a1c", "#7a5a32", "#c9b48a", "#3a2a1c"][Math.floor(r(1) * 4.99)];
    const beard = r(4) > .45;
    return `<svg class="portrait" viewBox="0 0 64 64" width="${size}" height="${size}" aria-hidden="true">
      <rect width="64" height="64" fill="${color}"/>
      <circle cx="32" cy="70" r="30" fill="#2a1f16"/><path d="M14 64 q18 -22 36 0" fill="${mix(color, "#000000", .35)}"/>
      <ellipse cx="32" cy="30" rx="11" ry="13" fill="#e9c9a3" stroke="#3a2a18" stroke-width=".8"/>
      <path d="M21 28 q11 -16 22 0 q-2 -10 -11 -11 q-9 1 -11 11" fill="${hair}"/>
      ${beard ? `<path d="M23 34 q9 14 18 0 q-3 7 -9 7 q-6 0 -9 -7" fill="${hair}"/>` : ""}
      ${crown ? `<path d="M21 19 l3 -8 l4 5 l4 -7 l4 7 l4 -5 l3 8 z" fill="#e6c27e" stroke="#5a3f17" stroke-width=".8"/>` : ""}
      <rect x=".5" y=".5" width="63" height="63" fill="none" stroke="#3a2a18"/></svg>`;
  }
  function pips(n, max = 6) { return `<span class="statpips">${Array.from({length: max}, (_, k) => `<i class="${k < n ? "on" : ""}"></i>`).join("")}</span>`; }
  function crownTab() {
    const ruler = V.me.ruler, color = N[me].color;
    const reign = ruler ? R.startYear + ruler.since - 1 : 0;
    const rulerHtml = ruler ? `<div class="throne">${portrait(ruler.name, color, true, 84)}
      <div><b>${esc(ruler.title)} ${esc(ruler.name)}</b><div class="sub">Aged ${ruler.age}, reigning since ${reign}.</div>
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
      const head = sitting ? `<div class="seat-who">${portrait(sitting.name, mix(color, "#efe2c2", .5), false, 48)}
          <div><b>${esc(sitting.name)}</b> <span class="stars">${stars(sitting.skill)}</span>
          <div class="sub">${esc(role.effect.replace("per star", `× ${sitting.skill}`))}; paid ${R.advisorSalary * sitting.skill} ducats a year.</div>
          <button class="btn" data-dismiss="${role.id}" ${dismissed ? "disabled" : ""}>${dismissed ? "Leaving" : "Dismiss"}</button></div></div>`
        : `<div class="seat-who empty"><div class="vacant">?</div><div><b>The seat is empty</b><div class="sub">${esc(role.effect)}.</div></div></div>`;
      const list = offers.map((c) => `<div class="offer"><span>${esc(c.name)} <span class="stars">${stars(c.skill)}</span></span>
        <span class="sub">${c.hire_cost} ducats, then ${c.salary} a year</span>
        <button class="btn" data-hire="${c.id}" ${hiring.has(role.id) || !affordable([c.hire_cost, 0, 0, 0, 0]) ? "disabled" : ""}>${hiring.has(role.id) && orders.some((o) => o.candidate === c.id) ? "Summoned" : "Hire"}</button></div>`).join("");
      return `<div class="seat"><h5>${role.name}</h5>${head}${list ? `<div class="sub" style="margin-top:6px">Seeking a place at court:</div>${list}` : ""}</div>`;
    }).join("");
    const enjoys = V.me.modifiers.sources.map((line) => `<li>${esc(line)}</li>`).join("");
    return `<div class="pad"><h4>The crown</h4>${rulerHtml}
      <h4>The council</h4><div class="council">${seats}</div>
      <p class="sub">New candidates come to court every ${R.advisorYears} years. Unpaid advisors leave.</p>
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
  function diplomacyTab() {
    const list = V.nations.filter((n) => n.alive).map((n) => `<div class="nrow ${nIndex[n.id] === focus ? "sel" : ""}" data-n="${n.id}" tabindex="0">
      <span class="shield" style="background:${N[nIndex[n.id]].color}"></span>
      <div><b>${esc(n.name)}</b> <small>${n.provinces} provinces, score ${n.score}</small><div class="chips">${chipsFor(n.id)}</div></div>
      <small>${esc(G.rulers[n.id] || "")}</small></div>`).join("");
    const alive = focus >= 0 && focus !== me && V.nations.find((n) => n.id === N[focus].id)?.alive;
    return `<div>${list}</div>${alive ? desk(N[focus].id) : `<p class="muted pad">Pick a court to treat with it.</p>`}`;
  }
  function desk(nid) {
    const n = V.nations.find((x) => x.id === nid), r = relation(nid), name = esc(n.name);
    const pending = (...kinds) => V.proposals_sent.some((p) => p.recipient === nid && kinds.includes(p.kind)) || orders.some((o) => o.target === nid && kinds.includes(o.type));
    const treaties = [r.alliance && "your alliance", r.pact && "your non-aggression pact", r.truce && "the truce"].filter(Boolean);
    const allies = V.me.treaties.filter((t) => t.kind === "alliance").map((t) => t.partner).filter((a) => !V.nations.find((x) => x.id === a).at_war_with.includes(nid));
    let html = `<div class="pad"><div class="who"><span class="shield" style="background:${N[nIndex[nid]].color}"></span>
      <div><b>${name}</b><span>Capital ${esc(P[pIndex[n.capital]].name)}. ${n.generals} generals. Technology ${T.map((b) => `${b.name.toLowerCase()} ${n.technology[b.id]}`).join(", ")}.</span></div></div>
      <div class="chips" style="margin-top:6px">${chipsFor(nid) || `<span class="muted">No treaty.</span>`}</div>
      <p class="sub">At war with ${n.at_war_with.map((x) => esc(nameOf(x))).join(", ") || "no one"}; allied with ${n.allies.map((x) => esc(nameOf(x))).join(", ") || "no one"}.</p>`;
    if (r.war) {
      html += `<h4>Make peace</h4><p class="sub">Leave both empty for a white peace, or demand (or offer) reparations.</p>
        <div class="sub">You demand</div>${bundleInputs("peace-receive")}<div class="sub">You offer</div>${bundleInputs("peace-give")}
        <div class="row"><button class="btn" data-dip="propose_peace" ${pending("propose_peace", "peace") ? "disabled" : ""}>Propose peace</button></div>`;
      if (allies.length) html += `<h4>Call your allies</h4><div class="row">${allies.map((a) => `<button class="btn" data-call="${a}">Call ${esc(nameOf(a))}</button>`).join("")}</div>`;
    } else {
      html += `<h4>Treaties</h4><div class="row">
        ${r.alliance ? `<button class="btn" data-cancel="alliance">End the alliance</button>` : `<button class="btn" data-dip="propose_alliance" ${pending("propose_alliance", "alliance") ? "disabled" : ""}>Propose an alliance</button>`}
        ${r.pact ? `<button class="btn" data-cancel="non_aggression">End the pact</button>` : `<button class="btn" data-dip="propose_non_aggression" ${pending("propose_non_aggression", "non_aggression") ? "disabled" : ""}>Propose a pact</button>`}</div>
        <h4>Trade and tribute</h4><div class="sub">You give</div>${bundleInputs("trade-give")}<div class="sub">You ask for</div>${bundleInputs("trade-receive")}
        <div class="row"><button class="btn" data-dip="propose_trade">Offer the trade</button><button class="btn" data-dip="gift">Send what you give as a gift</button></div>
        <h4>War</h4>${treaties.length ? `<p class="warn">War breaks ${treaties.join(" and ")}: −${R.breakPenalty} stability, and all Europe will know.</p>` : ""}
        <p class="sub">Armies mobilise for ${R.mobilization} year before they can attack. ${name}'s allies will be called to arms.</p>
        <div class="row"><button class="btn danger" data-dip="declare_war" ${pending("declare_war") ? "disabled" : ""}>Declare war on ${name}</button></div>`;
    }
    return html + `<h4>A letter</h4><textarea id="letter" maxlength="500" placeholder="Words do not change the rules, but rulers read them."></textarea>
      <div class="row"><button class="btn" data-dip="send_message">Seal and send</button></div></div>`;
  }
  function bundleInputs(id) {
    return `<div class="bundle" id="${id}">${RES.map(([key, label, ic]) => `<label>${ic}<input type="number" min="0" value="0" data-r="${key}" aria-label="${label}"></label>`).join("")}</div>`;
  }
  function readBundle(id) { const b = {}; document.querySelectorAll(`#${id} input`).forEach((i) => (b[i.dataset.r] = Math.max(0, +i.value || 0))); return b; }
  const emptyBundle = (b) => Object.values(b).every((v) => !v);
  function lettersTab() {
    const answered = Object.fromEntries(orders.filter((o) => o.type === "respond").map((o) => [o.proposal_id, o.accept]));
    const proposals = V.proposals_to_answer.map((p) => {
      const from = esc(nameOf(p.sender)), give = costText(unbundle(p.give)), ask = costText(unbundle(p.receive));
      const what = p.kind === "alliance" ? `${from} proposes an alliance.`
        : p.kind === "non_aggression" ? `${from} proposes a non-aggression pact.`
        : p.kind === "peace" ? `${from} offers peace${give !== "nothing" ? `, paying ${give}` : ""}${ask !== "nothing" ? `, demanding ${ask}` : ""}.`
        : p.kind === "trade" ? `${from} offers ${give} for ${ask}.`
        : `${from} calls you to arms against ${esc(nameOf(p.enemy))}. Ignoring it ends the alliance.`;
      const state = p.id in answered ? (answered[p.id] ? ` <span class="ok">You accept.</span>` : ` <span class="warn">You refuse.</span>`) : "";
      return `<div class="item">${what}${state}<div class="row"><button class="btn" data-answer="${p.id}" data-accept="1">Accept</button><button class="btn" data-answer="${p.id}" data-accept="0">Refuse</button></div></div>`;
    }).join("");
    const letters = V.last_turn_events.filter((e) => e.kind === "message" && e.data.sender !== G.human)
      .map((e) => `<div class="item">From <b>${esc(nameOf(e.data.sender))}</b><div class="letter">${esc(e.data.text)}</div></div>`).join("");
    const replies = V.last_turn_events.filter((e) => ["proposal_rejected", "proposal_expired", "treaty_signed", "trade_completed", "trade_failed", "peace_signed"].includes(e.kind) && e.nations.includes(G.human))
      .map((e) => `<div class="item">${ICON[e.kind] || "•"} ${esc(e.summary)}</div>`).join("");
    return `${proposals || `<p class="muted pad">No proposal waits for your answer.</p>`}
      ${letters ? `<div class="pad" style="padding-bottom:0"><h4>Letters</h4></div>${letters}` : ""}${replies ? `<div class="pad" style="padding-bottom:0"><h4>Replies</h4></div>${replies}` : ""}`;
  }
  function chronicleTab() {
    if (!G.chronicle.length) return `<p class="muted pad">History begins when you end the first year.</p>`;
    const names = new RegExp(N.map((n) => n.name).join("|"), "g");
    const paint = (text) => esc(text).replace(names, (m) => `<span class="nn" style="color:${mix(N.find((n) => n.name === m).color, "#ffffff", .35)}">${m}</span>`);
    return `<ol class="chron" style="max-height:none">${G.chronicle.map((y) => `<li class="year">${y.year}</li>` + y.events
      .filter((e) => !["moved", "proposal_made"].includes(e.kind))
      .map((e) => `<li class="${BAD.has(e.kind) ? "bad" : ""}"><span class="ic">${ICON[e.kind] || "•"}</span><span>${paint(e.kind === "order_rejected" ? "Your order failed: " + e.data.reason : e.summary)}</span></li>`).join("")).join("")}</ol>`;
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
    const hire = panel.querySelector("#hire"); if (hire) hire.onclick = () => queue({type: "hire_general", province: panel.querySelector("#hireat").value});
    panel.querySelectorAll(".nrow").forEach((row) => { const go = () => { focus = nIndex[row.dataset.n]; render(); };
      row.onclick = go; row.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
    const nid = focus >= 0 ? N[focus].id : null;
    panel.querySelectorAll("[data-dip]").forEach((b) => b.onclick = () => {
      const kind = b.dataset.dip;
      if (kind === "propose_peace") return queue({type: kind, target: nid, give: readBundle("peace-give"), receive: readBundle("peace-receive")});
      if (kind === "propose_trade") { const give = readBundle("trade-give"), receive = readBundle("trade-receive");
        if (emptyBundle(give) && emptyBundle(receive)) return flash("Fill in what you give or what you ask for.");
        if (!affordable(unbundle(give))) return flash("You cannot afford what you offer.");
        return queue({type: kind, target: nid, give, receive}); }
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
    panel.querySelectorAll("[data-cancel]").forEach((b) => b.onclick = () => queue({type: "cancel_treaty", target: nid, kind: b.dataset.cancel}));
    panel.querySelectorAll("[data-call]").forEach((b) => b.onclick = () => queue({type: "call_to_arms", target: b.dataset.call, enemy: nid}));
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
      case "recruit": return `Recruit ${o.regiments} in ${pn(o.province)}`;
      case "disband": return `Disband ${o.regiments} in ${pn(o.province)}`;
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
      case "propose_peace": return `Offer peace to ${nn(o.target)}`;
      case "propose_trade": return `Offer ${nn(o.target)} ${costText(unbundle(o.give))} for ${costText(unbundle(o.receive))}`;
      case "gift": return `Give ${nn(o.target)} ${costText(unbundle(o.resources))}`;
      case "cancel_treaty": return `End the ${o.kind.replace("_", "-")} treaty with ${nn(o.target)}`;
      case "call_to_arms": return `Call ${nn(o.target)} to arms against ${nn(o.enemy)}`;
      case "send_message": return `Letter to ${nn(o.target)}`;
      case "respond": return `${o.accept ? "Accept" : "Refuse"} proposal #${o.proposal_id}`;
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
      .filter((e) => e.nations.includes(G.human) || ["war_declared", "nation_eliminated", "treaty_broken", "game_over"].includes(e.kind))
      .map((e) => `<li class="${BAD.has(e.kind) ? "bad" : ""}">${ICON[e.kind] || "•"} ${esc(e.kind === "order_rejected" ? "Your order failed: " + e.data.reason : e.summary)}</li>`).join("");
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
      const t = targetsFrom(picked).find(([j]) => j === i), n = Math.min(send, troopsAfter(picked));
      if (t && t[1] === "move") extra = `Right-click to march ${n} regiments here`;
      if (t && t[1] === "attack") { const c = odds(picked, i); extra = `Right-click to attack with ${n}${c !== null ? `: ${Math.round(c * 100)}% to win` : ""}`; }
    }
    $("tip").innerHTML = `<b class="t">${esc(P[i].name)}</b><div class="kv">
      <span>Owner</span><b>${p.owner ? esc(nameOf(p.owner)) : "Independent"}</b>
      <span>Development</span><b>${p.development}</b><span>Regiments</span><b>${p.troops === null ? "hidden" : p.troops}</b>
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
