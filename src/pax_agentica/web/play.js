// Pax Agentica: play one nation. You see your NationView (fog of war included), queue Orders,
// and end the year. The server resolves the turn with every other ruler and sends the new view.
"use strict";

(async () => {
  const {esc, mix, devColor, cap, costText, RES, BICON, UICON, ICON, BAD, TERRAIN} = PaxMap;
  const I = PaxIcons.icon;
  const RICON = {ducats: "ducats", manpower: "manpower", iron: "iron", grain: "grain", timber: "timber", goods: "goods"};
  // a tooltip attribute: any HTML, shown by the rich tooltip below
  const tip = (html) => ` data-tip="${esc(html)}"`;
  const tline = (label, v, suffix = "") => `<div class="tl"><span>${label}</span><b class="${v > 0 ? "pos" : v < 0 ? "neg" : ""}">${v > 0 ? "+" : ""}${v}${suffix}</b></div>`;
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
  const J = window.PaxJuice || {play() {}, countTo() {}, floatText() {}, celebrate() {}, omen() {}, ceremony() {}, yearCard: async () => {}, vignette() {}, muted: () => true, setMuted() {}};
  const CRISIS_ICON = {plague: "☠", ice_age: "❄", price_revolution: "⚖"};
  const CRISIS_EFFECT = {plague: "Every town may lose a level of development each year; closed towns far less often, at a price.",
    ice_age: "Grain from every field −35%; bread dearer on the market.", price_revolution: "Market prices +40%, works and development 20% dearer, ducats +10%."};
  await window.PaxI18n?.ready; window.PaxI18n?.watch(); // the page in the player's language
  const S = await (await api("/static")).json();
  const P = S.provinces, N = S.nations, B = S.buildings, R = S.rules, T = S.tech, U = S.units, M = S.monuments;
  const KINDS = U.map((u) => u.id);
  // each crown's own regiments: one kind fights under its own name, harder (and maybe cheaper)
  const NU = S.nationalUnits || {}, U0 = U.map((u) => ({...u, terrain: {...u.terrain}}));
  function fielded(u, nid) {
    const own = NU[nid];
    if (!own || own.kind !== u.id) return u;
    const cost = own.cost === 1 ? u.cost : u.cost.map((v) => Math.ceil(v * own.cost));
    return {...u, name: own.name, attack: +(u.attack * own.attack).toFixed(2), defence: +(u.defence * own.defence).toFixed(2),
      terrain: {...u.terrain, ...own.terrain}, cost, lore: own.lore, national: true};
  }
  PaxMap.usePortraits(S.portraits, "/portraits/"); PaxMap.useFaces(S.faces, "/faces/"); window.PaxScenes?.use(S.scenes);
  const pIndex = Object.fromEntries(P.map((p, i) => [p.id, i]));
  const nIndex = Object.fromEntries(N.map((n, i) => [n.id, i]));
  const bIndex = Object.fromEntries(B.map((b, i) => [b.id, i]));
  const unbundle = (obj) => S.resources.map((r) => (obj && obj[r]) || 0);
  const sign = (v) => (v > 0 ? "+" : "") + v;
  const stars = (n) => "★".repeat(n) + "☆".repeat(3 - n);
  const MAX_ORDERS = 50;

  let G = null, V = null, me = -1;                // game payload, my view, my nation index
  let orders = [], mode = "political", picked = -1, focus = -1, tab = "realm", send = Infinity, lead = true, tactic = "best";
  let pickMix = null; // regiments chosen by kind for the next march, or null for a proportional draw

  const map = PaxMap.create($("map"), S, {
    hover: (i, e) => tooltip(i, e),
    leave: () => { $("tip").style.display = "none"; },
    click: (i) => { pickedSea = -1; select(i); },
    command: (i) => command(i),
    seaClick: (z) => { pickedSea = pickedSea === z ? -1 : z; picked = -1; render(); },
    seaCommand: (z) => { if (pickedSea < 0) return flash("Click a sea with ships of yours first, then right-click where they should sail.");
      sail(SEAS[pickedSea].id, SEAS[z].id); },
    seaHover: (z, e) => seaTip(z, e),
  });

  // ------------------------------------------------------------------ server
  async function load() {
    const r = await api("/game");
    if (r.status === 403 && TABLE) { location.href = `/?table=${TABLE}`; return; }
    G = await r.json(); afterLoad(); watch();
  }
  async function endTurn() {
    const failing = shortfalls();
    if (failing.size && !endTurn.warned) {
      endTurn.warned = true; $("ordersbtn").parentElement.classList.add("open"); render();
      return flash(`${failing.size} of your orders cannot be paid and will fail (marked in red). End the year again to go on anyway.`);
    }
    endTurn.warned = false;
    J.play("click");
    const button = $("endturn"); button.disabled = true; button.textContent = "The year passes…";
    try {
      const r = await api("/turn", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({actions: orders})});
      if (!r.ok) { const body = await r.json().catch(() => ({})); throw new Error(body.detail ? JSON.stringify(body.detail) : r.statusText); }
      const before = V, next = await r.json();
      if (next.view.turn === V.turn && !next.finished) { G = next; afterLoad(); watch(); return; } // the others are still deciding
      G = next; orders = []; draftSent = "[]"; picked = -1; afterLoad(); report(before); watch();
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
          const before = V, unsent = orders.length && !G.submitted, kept = JSON.stringify(orders) === draftSent;
          G = await (await api("/game")).json();
          orders = []; draftSent = "[]"; picked = -1; afterLoad(); report(before);
          if (unsent) flash(kept ? "The year ended before you pressed “End the year”: the orders you had prepared were carried out."
            : "The year ended before your last orders reached the court: some were not carried out.");
          if (document.hidden) document.title = window.PaxI18n ? PaxI18n.t(`⚑ ${V.year}: your turn · Pax Agentica`) : `⚑ ${V.year}: your turn · Pax Agentica`;
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
    const force = G.force_in === 0 ? `<button class="btn" id="forceyear">Don't wait for them</button>`
      : G.force_in ? ` You may go on without them in ${Math.ceil(G.force_in / 60)} min.` : "";
    const leave = TABLE && !closed && !G.finished ? `<button class="btn quiet" id="leavetable" title="Give your throne back to a bot">Leave the table</button>` : "";
    const late = G.seconds_left != null && G.seconds_left < 60;
    const timer = G.seconds_left != null && !G.finished ? `${Math.floor(G.seconds_left / 60)}:${String(G.seconds_left % 60).padStart(2, "0")}` : "";
    const pill = $("tablestatus");
    pill.hidden = !(TABLE && !closed && !G.finished && !fallen);
    if (!pill.hidden) {
      const status = G.submitted ? `✓ sent${others.length ? ` · ${others.length} deciding` : ""}` : others.length ? `${others.length} deciding` : "your move";
      pill.innerHTML = `<button class="tablepill ${G.submitted ? "sent" : ""} ${late && !G.submitted ? "late" : ""}" type="button">${timer ? `⏳ <span class="num">${timer}</span> · ` : ""}${status}</button>
        <div class="tablebox"><p>${G.submitted ? "📜 Your orders are sent; you may still change them and send again." : "Your court awaits your orders. What you prepare is kept: if the year ends before you press “End the year”, it is carried out."}</p>
          ${others.length ? `<p>Still deciding: ${others.map(who).join(", ")}.</p>` : ""}
          ${timer ? `<p>⏳ ${timer} left this year.</p>` : ""}${force ? `<p>${force}</p>` : ""}<div class="row">${leave}</div></div>`;
      pill.querySelector(".tablepill").onclick = () => pill.classList.toggle("open");
    }
    const table = closed ? `<div class="banner">This table is closed (${esc(closed)}). <a href="${REPLAY}" target="_blank">Watch the replay</a> · <a href="/">Back to the tables</a></div>` : "";
    $("banner").innerHTML = G.finished ? `<div class="over">👑 ${esc(G.winner ? nameOf(G.winner) + " wins." : "The game is over.")} <a href="#" id="theend">How the age ended</a> · <a href="${REPLAY}" target="_blank">Watch the replay</a></div>`
      : fallen ? `<div class="banner">Your realm has fallen. You can watch the rest of the game year by year.</div>` : table;
    const te = $("theend"); if (te) te.onclick = (e) => { e.preventDefault(); report(null); };
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
    if (!afterLoad.units) { afterLoad.units = true; U.forEach((u, k) => Object.assign(u, fielded(U0[k], G.human))); } // my regiments, as my crown fields them
    // the music follows the realm: a crisis raging, a war, or peace
    J.setMood?.(V.crisis && V.crisis.raging ? "crisis" : V.me.at_war_with.length ? "war" : "peace");
    if (!afterLoad.done) { afterLoad.done = true;
      let seen = false; try { seen = !!localStorage.getItem("pax-guided"); localStorage.setItem("pax-guided", "1"); } catch {}
      setTimeout(() => (seen || V.turn > 1 ? eventSheet() : guide(0)), 400); }
    if (!map.homed) { map.home(V.me.provinces.map((p) => pIndex[p])); map.homed = true; }
    render();
  }
  function flash(text) { const e = $("error"); e.textContent = text; e.style.display = "block"; clearTimeout(flash.t); flash.t = setTimeout(() => (e.style.display = "none"), 5000); }
  // What an order sounds like, and the word it leaves rising over its province.
  const ORDER_FEEL = {build: ["build", "🏗"], upgrade_building: ["build", "⬆"], develop: ["build", "+1"], improve: ["build", "⛏"],
    upgrade_monument: ["build", "🏛"], recruit: ["order", (o) => `+${o.regiments} ⚔`], hire_mercenaries: ["coins", (o) => `+${o.regiments} ⚔`],
    attack: ["order", "⚔"], move: ["order", "➜"], buy: ["coins", null], sell: ["coins", null], gift: ["coins", null], convert: ["order", "✝"],
    lift_siege: ["unorder", "🏳"], declare_war: ["war", null], send_message: ["seal", null], respond: ["seal", null],
    choose_option: ["seal", null], set_taxes: ["coins", null], boost_stability: ["coins", null], patronize: ["coins", null],
    hire_general: ["order", "★"], assign_general: ["order", "★"], build_ships: ["build", null], send_expedition: ["seal", null], seize_colony: ["war", null], sail_fleet: ["order", null], seek_battle: ["war", null], scrap_ships: ["unorder", null]};
  function queue(order) {
    if (orders.length >= MAX_ORDERS) return flash(`A realm can give at most ${MAX_ORDERS} orders a year.`);
    orders.push(order);
    const [sound, mark] = ORDER_FEEL[order.type] || [order.type.startsWith("propose") ? "seal" : "order", null];
    J.play(sound);
    if (order.type === "declare_war") J.vignette("war");
    const where = pIndex[order.province ?? (order.type === "attack" || order.type === "move" ? order.target : null)];
    if (mark && where !== undefined) map.ping(where, typeof mark === "function" ? mark(order) : mark, order.type === "attack" ? "war" : "");
    render();
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
  // raising a building to `level`: its own cost times the rules' factor, then engineering's discount
  const upgradeCost = (id, level) => { const b = B[bIndex[id]], f = R.upgradeCosts[Math.min(level, R.upgradeCosts.length) - 1], off = V.me.modifiers.building_discount;
    return b.cost.map((v, k) => { const c = Math.ceil(v * f); return RES[k][0] === "ducats" || RES[k][0] === "timber" ? Math.ceil(c * (1 - off)) : c; }); };
  const levelOf = (i, id) => (prov(i).building_levels || {})[id] || 1;
  const researching = () => orders.find((o) => o.type === "research");
  // what one order takes from (negative) or gives to (positive) the treasury, resource by resource
  function delta(o) {
    const d = RES.map(() => 0), sub = (c) => c.forEach((v, k) => (d[k] -= v));
    if (o.type === "recruit") { const p = prov(pIndex[o.province]); sub(unbundle((p.recruit_costs || {})[o.unit || "infantry"] || p.recruit_cost).map((v) => v * o.regiments)); }
    if (o.type === "upgrade_monument") sub(R.monumentCost.map((v) => v * ((prov(pIndex[o.province]).monument || 0) + 1)));
    if (o.type === "propose_peace") sub(unbundle(o.give));
    if (o.type === "buy") { const k = RES.findIndex(([key]) => key === o.resource); d[k] += o.amount; d[0] -= Math.ceil(o.amount * V.market[o.resource].buy); }
    if (o.type === "sell") { const k = RES.findIndex(([key]) => key === o.resource); d[k] -= o.amount; d[0] += Math.floor(o.amount * V.market[o.resource].sell); }
    if (o.type === "develop") sub(unbundle(prov(pIndex[o.province]).develop_cost));
    if (o.type === "set_focus") sub(R.focus.cost);
    if (o.type === "build_ships") sub(R.ships[o.ship].cost.map((v) => v * o.count));
    if (o.type === "send_expedition") sub(R.colonial.cost);
    if (o.type === "improve" && prov(pIndex[o.province]).improve_cost) sub(unbundle(prov(pIndex[o.province]).improve_cost));
    if (o.type === "hire_mercenaries") d[0] -= o.regiments * R.mercenaryCost;
    if (o.type === "patronize") d[0] -= V.me.patronage_cost;
    if (o.type === "convert" && prov(pIndex[o.province]).convert_cost) sub(unbundle(prov(pIndex[o.province]).convert_cost));
    if (o.type === "build") sub(buildCost(o.building));
    if (o.type === "upgrade_building") sub(upgradeCost(o.building, levelOf(pIndex[o.province], o.building) + 1));
    if (o.type === "boost_stability") d[0] -= stabilityCost();
    if (o.type === "research" && V.me.research_costs[o.branch]) sub(unbundle(V.me.research_costs[o.branch]));
    if (o.type === "hire_general") sub(R.generalCost);
    if (o.type === "hire_advisor") { const c = V.me.advisor_candidates.find((x) => x.id === o.candidate); if (c) d[0] -= c.hire_cost; }
    if (o.type === "gift") sub(unbundle(o.resources));
    if (o.type === "disband") R.disband.forEach((v, k) => (d[k] += v * o.regiments));
    return d;
  }
  function projected() {
    const t = unbundle(V.me.resources);
    for (const o of orders) delta(o).forEach((v, k) => (t[k] += v));
    return t;
  }
  // the orders the treasury cannot pay, as the engine will meet them: gifts and peace offers
  // first, then the market, then the rest in the order given
  const PHASE = (o) => ["gift", "propose_peace"].includes(o.type) ? 0 : ["buy", "sell"].includes(o.type) ? 1 : 2;
  function shortfalls() {
    const t = unbundle(V.me.resources), out = new Map();
    orders.map((o, k) => [o, k]).sort((a, b) => PHASE(a[0]) - PHASE(b[0]) || a[1] - b[1]).forEach(([o, k]) => {
      const d = delta(o);
      const short = d.map((v, j) => (v < 0 && t[j] + v < 0 ? RES[j][1].toLowerCase() : null)).filter(Boolean);
      if (short.length) { out.set(k, short); return; }  // the engine skips it and keeps the money
      d.forEach((v, j) => (t[j] += v));
    });
    return out;
  }
  const affordable = (cost, t = projected()) => cost.every((v, k) => t[k] >= v);
  const stabilityCost = () => Math.ceil(R.stabilityCost * (1 - V.me.modifiers.stability_discount));
  function troopsAfter(i) {
    let t = prov(i).troops || 0;
    for (const o of orders) {
      if ((o.type === "recruit" || o.type === "hire_mercenaries") && pIndex[o.province] === i) t += o.regiments;
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
      if ((o.type === "recruit" || o.type === "hire_mercenaries") && pIndex[o.province] === i) a[o.unit || "infantry"] += o.regiments;
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
  function strength(army, terrain, attacking, nid = G.human) {
    const total = KINDS.reduce((t, k) => t + (army[k] || 0), 0);
    if (!total) return 0;
    let power = 0, kinds = 0;
    U0.forEach((u0) => { const u = fielded(u0, nid), n = army[u.id] || 0; power += n * (attacking ? u.attack : u.defence) * (u.terrain[terrain] || 1);
      if (n && n / total >= R.combinedShare) kinds++; });
    const bonus = Math.max(0, ...Object.entries(R.combinedBonus).filter(([k]) => kinds >= +k).map(([, b]) => b));
    return power * (1 + bonus);
  }
  // ------------------------------------------------------------------ tactics, postures, veterans
  // [id, icon, name, what it is, the kind that carries it]
  const TACTICS = [["assault", "🔱", "Assault", "the pikes push straight in", "infantry"],
    ["flank", "🐎", "Flank", "the horse rides round", "cavalry"], ["bombard", "💣", "Bombard", "the guns open first", "artillery"]];
  const POSTURES = [["hold", "🛡", "Hold the line", "a line of pikes behind what cover there is", "infantry"],
    ["skirmish", "🏹", "Skirmish", "shot and bows thrown forward to harry", "archers"], ["sally", "🏇", "Sally", "horse kept back to charge whoever comes", "cavalry"]];
  const BEATS = {assault: "skirmish", flank: "hold", bombard: "sally"}, LOSES = {assault: "hold", flank: "sally", bombard: "skirmish"};
  const BROKEN = new Set(["forest", "hills", "marsh", "mountains"]);
  const tacticOf = (id) => TACTICS.find(([k]) => k === id), postureOf = (id) => POSTURES.find(([k]) => k === id) || POSTURES[0];
  function carried(kind, army) {
    const total = KINDS.reduce((t, k) => t + (army[k] || 0), 0);
    return total ? Math.min(1, (army[kind] || 0) / total / R.tactics.share[kind]) : 0;
  }
  function tacticFactor(t, posture, attackers, defenders, terrain) { // as the engine's tactic_factor
    const ours = carried(tacticOf(t)[4], attackers), theirs = carried(postureOf(posture)[4], defenders);
    let swing = (1 - theirs) - (1 - ours);
    if (BEATS[t] === posture) swing += ours; else if (LOSES[t] === posture) swing -= theirs;
    swing = Math.max(-1, Math.min(1, swing));
    if (t === "flank" && BROKEN.has(terrain) && swing > 0) swing /= 2; // horse cannot ride round in broken ground
    return 1 + R.tactics.edge * swing;
  }
  const veteranFactor = (v) => 1 + R.tactics.veteranBonus * (v || 0);
  const myMorale = () => V.me.morale ?? 1;
  const seasoning = (v) => (v >= 0.75 ? "veterans" : v >= 0.5 ? "seasoned" : v >= 0.25 ? "blooded" : "raw");
  // the garrison a tactic meets: its posture (dug-in lines hold), and who carries it
  function facing(to) {
    const p = prov(to);
    if (p.siege_by && p.siege_by !== G.human) return {posture: "hold", army: {infantry: p.besiegers || 0}, vet: p.siege_veterancy || 0, seen: true};
    return {posture: p.posture || "hold", army: p.army || {infantry: p.troops || 0}, vet: p.veterancy || 0, seen: p.posture != null};
  }
  function bestTactic(to, army) {
    const f = facing(to);
    if (!f.seen) return "assault";
    return TACTICS.map(([k]) => k).reduce((a, b) => (tacticFactor(b, f.posture, army, f.army, P[to].terrain) > tacticFactor(a, f.posture, army, f.army, P[to].terrain) + 1e-9 ? b : a), "assault");
  }
  const chosenTactic = (to, army) => (tactic === "best" ? bestTactic(to, army) : tactic);
  // ------------------------------------------------------------------ fleets on the sea zones
  const WATER = {atlantic: ["🌊", "the ocean"], baltic: ["❄", "the Baltic"], mediterranean: ["☀", "an inland sea"]};
  const SEAS = S.seas || [], ZI = Object.fromEntries(SEAS.map((z, k) => [z.id, k]));
  const seaOf = (id) => SEAS[ZI[id]], seaName = (id) => (seaOf(id) ? seaOf(id).name : id);
  const seaView = (id) => (V.seas || []).find((z) => z.id === id);
  const SHIPS = ["galley", "galleon"], SICON = {galley: "🚣", galleon: "⛵"};
  function navalPower(nid, z) { const s = seaView(z); return s && nid ? s.power[nid] || 0 : 0; }
  const holderAt = (j) => { const p = prov(j); return p.siege_by && p.siege_by !== G.human ? p.siege_by : p.controller || p.owner; };
  // who holds the sea an attack from `origin` crosses to `target`, as the engine judges it
  function seaCommand(origin, target) {
    const z = (P[origin].straits || {})[target];
    if (!z) return "land";
    const reach = (nid) => nid ? navalPower(nid, z) + R.navy.reach * seaOf(z).neighbors.reduce((t, x) => t + navalPower(nid, x), 0) : 0;
    const enemy = holderAt(target), mine = reach(G.human), theirs = reach(enemy);
    if (theirs > 0 && theirs >= R.navy.command * mine) return "closed";
    return mine > theirs ? "ours" : "contested";
  }
  const shipsIn = (z) => ({galley: 0, galleon: 0, ...((V.me.fleets || {})[z] || {})});
  const carry = (ships) => SHIPS.reduce((t, k) => t + (ships[k] || 0) * R.ships[k].carries, 0);
  // how many regiments my ships could carry from i to j over a sea both look onto (0: none)
  function landingRoom(i, j) {
    const enemy = holderAt(j), there = new Set(P[j].seas || []);
    let best = 0;
    for (const z of P[i].seas || []) {
      if (!there.has(z)) continue;
      const mine = navalPower(G.human, z);
      if (enemy && enemy !== G.human) { if (mine <= navalPower(enemy, z)) continue; }
      else if (V.me.at_war_with.some((e) => navalPower(e, z) > 0 && navalPower(e, z) >= R.navy.command * mine)) continue;
      best = Math.max(best, carry(shipsIn(z)));
    }
    return best;
  }
  // the ships in a zone once this year's sailings are done
  function fleetAfter(z) {
    const f = shipsIn(z);
    for (const o of orders) if (o.type === "sail_fleet") for (const k of SHIPS) {
      if (o.origin === z) f[k] -= o.ships[k] || 0;
      if (o.target === z) f[k] += o.ships[k] || 0;
    }
    return f;
  }
  const buildSea = (o) => o.sea || (P[pIndex[o.province]].seas || [])[0];
  const launching = (z) => { const out = {galley: 0, galleon: 0}; orders.filter((o) => o.type === "build_ships" && buildSea(o) === z).forEach((o) => (out[o.ship] += o.count)); return out; };
  const myPorts = (z) => V.me.provinces.map((id) => pIndex[id]).filter((i) => (P[i].seas || []).includes(z) && !prov(i).controller && !prov(i).siege_by);
  let fleetPort = {}, fleetN = {}, pickedSea = -1;
  function seekOdds(z, e) {
    const ex = V.nations.find((x) => x.id === e)?.war_exhaustion || 0;
    const mine = SHIPS.reduce((t, k) => t + (fleetAfter(z)[k] || 0) * R.ships[k].strength[seaOf(z).water], 0) * (1 + (V.me.modifiers.navy || 0));
    return winChance(mine * myMorale(), navalPower(e, z) * (1 - R.tactics.perExhaustion * ex), 1);
  }
  // the launching yard of a zone: a port of yours on it, and how many of each kind
  function yardHtml(z) {
    const harbours = myPorts(z);
    if (!harbours.length) return `<p class="sub">No port of yours on ${esc(seaName(z))}.</p>`;
    if (!fleetPort[z] || !harbours.includes(pIndex[fleetPort[z]])) fleetPort[z] = P[harbours.sort((a, b) => prov(b).development - prov(a).development)[0]].id;
    const port = pIndex[fleetPort[z]];
    const used = orders.filter((o) => o.type === "build_ships" && o.province === fleetPort[z]).reduce((a, o) => a + o.count, 0);
    const room = R.navy.perPort + Math.floor(prov(port).development / 3) - used;
    const n = (k) => Math.min(fleetN[`${z}:${k}`] || 0, room);
    const cost = [0, 0, 0, 0, 0, 0]; SHIPS.forEach((k) => R.ships[k].cost.forEach((v, j) => (cost[j] += v * n(k))));
    const ok = SHIPS.some((k) => n(k) > 0) && affordable(cost) && SHIPS.reduce((a, k) => a + n(k), 0) <= room;
    const water = seaOf(z).water;
    const stepper = (k) => `<span class="stepper"><button type="button" data-fleetkind="${z}:${k}" data-d="-1">−</button><b class="num">${n(k)}</b><button type="button" data-fleetkind="${z}:${k}" data-d="1">+</button></span>`;
    return `<div class="row"><span class="sub">Launch from</span><select class="field" data-fport="${z}">${harbours.map((i) => `<option value="${P[i].id}" ${P[i].id === fleetPort[z] ? "selected" : ""}>${esc(P[i].name)}</option>`).join("")}</select><small class="sub">${room} more this year</small></div>
      <div class="row">${SHIPS.map((k) => `<span${tip(`<h5>${SICON[k]} ${esc(R.ships[k].name)}</h5><div>${esc(R.ships[k].role)}.</div><div class="dim">Strength here ${R.ships[k].strength[water]}; carries ${R.ships[k].carries} regiment${R.ships[k].carries > 1 ? "s" : ""}</div>`)}>${SICON[k]} ${esc(R.ships[k].name)}</span>${stepper(k)}`).join("")}<button class="btn" data-fbuild="${z}" ${ok ? "" : "disabled"}>Launch</button><span class="cost">${cost.some((v) => v) ? costText(cost) : ""}</span></div>`;
  }
  // the deed of a zone of the sea: every fleet in it, yours to sail or fight, your yards on it
  function seaDeed() {
    const z = SEAS[pickedSea].id, sea = seaOf(z), sv = seaView(z) || {fleets: {}, power: {}}, w = WATER[sea.water];
    const fleets = Object.entries(sv.fleets).sort((a, b) => (sv.power[b[0]] || 0) - (sv.power[a[0]] || 0)).map(([n, ships]) =>
      `<div class="fleetrow">${PaxMap.flag(n, N[nIndex[n]].color, 22)}<b>${esc(nameOf(n))}</b>${n !== G.human && relation(n).war ? `<span class="chip war">at war</span>` : ""}
        <span>${SHIPS.filter((k) => ships[k]).map((k) => `${SICON[k]} ${ships[k]}`).join(" ")}</span><span class="num">${(sv.power[n] || 0).toFixed(1)}</span></div>`).join("");
    const mine = fleetAfter(z), total = SHIPS.reduce((a, k) => a + mine[k], 0);
    const sails = orders.filter((o) => o.type === "sail_fleet" && o.origin === z);
    const sailTo = total ? sea.neighbors.map((t) => `<button class="btn" data-sailto="${z}:${t}">➜ ${esc(seaName(t))}</button>`).join("") : "";
    const enemies = V.me.wars.filter((x) => x.attacks_allowed_from_turn <= V.turn && navalPower(x.enemy, z) > 0).map((x) => x.enemy);
    const seeking = new Set(orders.filter((o) => o.type === "seek_battle" && o.sea === z).map((o) => o.enemy));
    const battles = total ? enemies.map((e) => `<button class="btn ${seeking.has(e) ? "on" : ""}" data-seek="${z}:${e}" ${seeking.has(e) ? "disabled" : ""}>⚔ Seek out the fleet of ${esc(nameOf(e))} · ${Math.round(seekOdds(z, e) * 100)}%</button>`).join("") : "";
    const held = (V.me.blockaded || []).includes(z);
    const box = $("deed");
    box.innerHTML = `<header class="deedhead seahead"><div class="seaband">${w[0]}</div>
        <div class="ribbon"><span class="shield" style="background:#2a5d8a"></span><div><h2 id="deedname">${esc(sea.name)}</h2><div class="owner">${cap(w[1])}: galleys ${R.ships.galley.strength[sea.water]}, galleons ${R.ships.galleon.strength[sea.water]}</div></div></div>
        <button class="x" data-close aria-label="Close" title="Close (Esc)">×</button></header>
      ${held ? `<section class="warnotes"><p class="note war">⚓ An enemy fleet holds these waters: your ports here earn ${Math.round(R.navy.blockadeShare * 100)}% fewer ducats.</p></section>` : ""}
      <section><h4>Fleets here</h4>${fleets || `<p class="muted">No fleet sails here.</p>`}</section>
      <section><h4>Your fleet</h4>
        <p class="shipline">${SHIPS.map((k) => `<span>${SICON[k]} <b>${mine[k]}</b> <span>${k}s</span></span>`).join("")}${total ? `<span>carries ${carry(mine)} regiments to a landing</span>` : ""}${sails.length ? `<span class="sub">(after this year's sailing)</span>` : ""}</p>
        ${sailTo ? `<div class="row"><span class="sub">Sail all ${total} ships to</span>${sailTo}</div><p class="note">Or right-click a neighbouring sea. Fleets sail a zone a year, before the battles.</p>` : ""}
        ${battles ? `<div class="row">${battles}</div>` : ""}</section>
      <section><h4>Shipyards</h4>${yardHtml(z)}</section>
      <section><p class="note"><b>Coasts</b>: ${sea.coasts.map((i) => `<span>${esc(P[i].name)}</span>`).join(", ")}.</p><p class="note">A fleet ${R.navy.command} times the enemy's here closes its straits to the enemy's armies and blockades its ports; any fleet stronger than the defender's lets your armies cross its straits freely and land on any of these coasts.</p></section>`;
    box.classList.add("open"); box.classList.remove("min", "compact");
    box.querySelector("[data-close]").onclick = () => { pickedSea = -1; render(); };
    box.querySelectorAll("[data-sailto]").forEach((b) => b.onclick = () => { const [from, to] = b.dataset.sailto.split(":"); sail(from, to); });
    box.querySelectorAll("[data-seek]").forEach((b) => b.onclick = () => { const [zz, e] = b.dataset.seek.split(":"); queue({type: "seek_battle", sea: zz, enemy: e}); });
    wireYards(box);
  }
  function sail(from, to) {
    const f = fleetAfter(from), ships = Object.fromEntries(SHIPS.filter((k) => f[k] > 0).map((k) => [k, f[k]]));
    if (!Object.keys(ships).length) return flash(`No ships of yours in ${seaName(from)}.`);
    if (!seaOf(from).neighbors.includes(to)) return flash(`${seaName(from)} does not open onto ${seaName(to)}.`);
    queue({type: "sail_fleet", origin: from, target: to, ships});
    pickedSea = ZI[to]; render();
  }
  function wireYards(root) {
    root.querySelectorAll("[data-fleetkind]").forEach((b) => b.onclick = () => { const k = b.dataset.fleetkind; fleetN[k] = Math.max(0, (fleetN[k] || 0) + +b.dataset.d); render(); });
    root.querySelectorAll("[data-fport]").forEach((x) => x.onchange = () => { fleetPort[x.dataset.fport] = x.value; render(); });
    root.querySelectorAll("[data-fbuild]").forEach((b) => b.onclick = () => { const z = b.dataset.fbuild;
      SHIPS.forEach((k) => { const n = fleetN[`${z}:${k}`] || 0; if (n > 0) queue({type: "build_ships", province: fleetPort[z], ship: k, count: n, sea: z}); fleetN[`${z}:${k}`] = 0; }); render(); });
  }
  // the army office's summary of the fleets: every zone where you have ships or ports
  function fleetsSection() {
    const zones = SEAS.filter((z) => myPorts(z.id).length || SHIPS.some((k) => fleetAfter(z.id)[k]));
    if (!zones.length) return `<p class="muted">You hold no port: a realm without a coast keeps no fleet.</p>`;
    const rows = zones.map((z) => {
      const f = fleetAfter(z.id), coming = launching(z.id), sv = seaView(z.id) || {power: {}};
      const top = Object.entries(sv.power).filter(([n]) => n !== G.human).sort((a, b) => b[1] - a[1])[0];
      const held = (V.me.blockaded || []).includes(z.id);
      return `<tr class="click" data-sea="${ZI[z.id]}"><td>${WATER[z.water][0]} ${esc(z.name)}</td><td>${SICON.galley} ${f.galley}${coming.galley ? `<small class="up">+${coming.galley}</small>` : ""}</td>
        <td>${SICON.galleon} ${f.galleon}${coming.galleon ? `<small class="up">+${coming.galleon}</small>` : ""}</td><td class="num">${navalPower(G.human, z.id).toFixed(1)}</td>
        <td>${top ? `${esc(nameOf(top[0]))} ${top[1].toFixed(1)}` : "—"}</td><td>${held ? `<span class="neg">⚓ blockaded</span>` : ""}</td></tr>`; }).join("");
    return `<table class="grid num"><thead><tr><th>Sea</th><th>Galleys</th><th>Galleons</th><th>Strength</th><th>Strongest other</th><th></th></tr></thead><tbody>${rows}</tbody></table>
      <p class="sub">Click a sea here or on the map to sail its fleet, seek battle or launch ships. Galleys are cheap and rule calm seas; galleons cost more, rule the ocean and carry two regiments each to a landing. A fleet ${R.navy.command} times the enemy's closes the straits to its armies and blockades its ports; the beaten fleet in a sea battle loses ${Math.round(R.navy.loserLoss * 100)}% of its ships.</p>`;
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
    const held = p.controller || p.owner, holder = held ? V.nations.find((n) => n.id === held) : null;
    const perLevel = holder && holder.technology.engineering >= 4 ? 0.35 : R.fort; // star forts
    let bonus = perLevel * forts + (p.is_capital && held === p.owner ? R.capital : 0);
    if (p.buildings.includes("training_grounds")) bonus += 0.2 * (R.levelFactors[((p.building_levels || {}).training_grounds || 1) - 1] || 1);
    if (P[origin].sea.includes(target) && seaCommand(origin, target) !== "ours") bonus += R.sea; // unless your fleet holds the water
    else if (!P[origin].land.includes(target) && !P[origin].sea.includes(target)) bonus += R.sea + R.landing; // off the boats
    const tech = holder ? 1 + T[0].perLevel * holder.technology.military : 1;
    const guard = p.general && p.general.nation === held ? 1 + R.generalBonus * p.general.skill : 1;
    return R.defender * R.terrain[P[target].terrain] * (1 + bonus) * tech * guard;
  }
  const myFactor = (general) => (1 + V.me.modifiers.battle_power) * (general ? 1 + R.generalBonus * general.skill : 1);
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
      const o = holder(j), sieged = prov(j).siege_by;
      if (sieged && sieged !== G.human && o === G.human) { if (relation(sieged).war) out.push([j, "attack"]); } // break the siege
      else if (o === G.human) out.push([j, "move"]);
      else if (seaCommand(i, j) === "closed") continue; // their fleet bars the strait
      else if (o === null) out.push([j, "attack"]);
      else { const w = relation(o).war; if (w && w.attacks_allowed_from_turn <= V.turn) out.push([j, "attack"]); }
    }
    // by sea: any shore of a sea your fleet holds, as many regiments as its ships carry
    const near = new Set([i, ...P[i].land, ...P[i].sea]), shores = new Set();
    for (const z of P[i].seas || []) for (const j of seaOf(z).coasts) if (!near.has(j)) shores.add(j);
    for (const j of shores) {
      const room = landingRoom(i, j); if (!room) continue;
      const o = holder(j);
      if (o === G.human) out.push([j, "move", room]);
      else if (o === null) out.push([j, "attack", room]);
      else { const w = relation(o).war; if (w && w.attacks_allowed_from_turn <= V.turn) out.push([j, "attack", room]); }
    }
    return out;
  }
  // Who marches: the regiments chosen by kind, or a proportional draw of `send`.
  function force(from) {
    const here = armyAfter(from);
    if (pickMix) { const out = {}; KINDS.forEach((k) => (out[k] = Math.min(pickMix[k] || 0, here[k]))); return out; }
    return share(here, Math.min(send, troopsAfter(from)));
  }
  // The armies already ordered against `to` this year from other provinces: the engine joins
  // them all into one battle, so the odds count them together.
  function jointWith(from, to, army) {
    const joint = {...army};
    for (const o of orders) {
      if (o.type !== "attack" || pIndex[o.target] !== to || pIndex[o.origin] === from) continue;
      const src = prov(pIndex[o.origin]), c = o.units || share(src.army || {infantry: src.troops || 0}, o.regiments);
      KINDS.forEach((k) => (joint[k] = (joint[k] || 0) + (c[k] || 0)));
    }
    return joint;
  }
  function odds(from, to, alone = force(from), extraArmies = 0, how = null) {
    const army = jointWith(from, to, alone);
    const armies = 1 + extraArmies + new Set(orders.filter((o) => o.type === "attack" && pIndex[o.target] === to && pIndex[o.origin] !== from).map((o) => o.origin)).size;
    const coordination = 1 - Math.min(R.jointPenaltyMax || 0, (R.jointPenalty || 0) * (armies - 1));
    const p = prov(to), g = lead ? generalAt(from) : null;
    const n = KINDS.reduce((t, k) => t + army[k], 0);
    const ground = P[to].terrain;
    if (p.siege_by === G.human) return null; // reinforcements for your own lines: no battle
    const f = facing(to), t = how || chosenTactic(to, army);
    const drill = tacticFactor(t, f.posture, army, f.army, ground) * veteranFactor(prov(from).veterancy) * myMorale();
    const holderOf = V.nations.find((x) => x.id === (p.siege_by || p.controller || p.owner));
    const tired = holderOf ? 1 - R.tactics.perExhaustion * holderOf.war_exhaustion : 1; // their stability is their secret
    if (p.siege_by) { // a relief army against the siege lines
      if (!p.besiegers || !n) return p.besiegers === 0 ? 1 : null;
      return winChance(strength(army, ground, true) * myFactor(g) * coordination * drill, p.besiegers * veteranFactor(f.vet) * tired, R.defender * R.terrain[ground]);
    }
    if (p.troops === null || !n) return null;
    if (!p.troops) return 1;
    const mine = strength(army, ground, true) * myFactor(g) * coordination * drill; // joint armies coordinate poorly
    const theirs = (p.army ? strength(p.army, ground, false, p.controller || p.owner) : p.troops) * veteranFactor(f.vet) * tired;
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
    let army = force(from), n = KINDS.reduce((t, k) => t + army[k], 0);
    if (n <= 0) return flash(`No regiments left in ${P[from].name}.`);
    const room = (targetsFrom(from).find(([j]) => j === to) || [])[2];
    if (room !== undefined && n > room) { army = share(army, room); n = room; flash(`Your ships carry only ${room} regiments: ${room} sail.`); }
    const g = lead ? generalAt(from) : null;
    const order = {type: kind, origin: P[from].id, target: P[to].id, regiments: n};
    if (pickMix) order.units = Object.fromEntries(KINDS.filter((k) => army[k]).map((k) => [k, army[k]]));
    if (g) order.general = g.id;
    if (kind === "attack") order.tactic = chosenTactic(to, army);
    queue(order);
  }

  // ------------------------------------------------------------------ the province deed
  // What a work without a yield does, in a few words for its tile.
  const PERK = {university: "develop −30% here", armory: "½ iron per regiment", fort: "🏰 walls, +25% defence",
    citadel: "+25% more defence", training_grounds: "+20% garrison", stables: "🐎 cavalry here", cannon_foundry: "💣 artillery here",
    military_academy: "+1 general", royal_exchange: "+10% ducats, all realm", observatory: "−15% research", cathedral: "unrest ends ×2",
    barracks: "higher manpower cap", arms_manufactory: "levies need ½ iron, no goods", powder_mill: "+5% power, breaches a fort level",
    workshop: "makes goods"};
  const icons = (c) => RES.map(([, , ic], k) => c[k] ? `${c[k]}${ic}` : "").filter(Boolean).join(" ");
  const gainText = (g) => RES.map(([key, , ic]) => g && g[key] ? `<span>+${g[key]} ${ic}</span>` : "").join("");
  let ownTab = "economy", deedMin = false;
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
  // A siege, as the dice see it: progress, the modifiers on next year's roll, and what each score buys.
  function siegeCard(i) {
    const p = prov(i);
    if (!p.siege_by) return "";
    const ours = p.siege_by === G.human, theirs = holder(i) === G.human;
    const mods = p.siege_modifiers || [], sum = mods.reduce((a, [, v]) => a + v, 0);
    const chances = R.siegeResults.map(([least, gain, name], k) => {
      const next = R.siegeResults[k + 1], hi = next ? next[0] - 1 : 99;
      const n = [1, 2, 3, 4, 5, 6].filter((d) => d + sum >= least && d + sum <= hi).length;
      return n ? `<li><span>${esc(cap(name))}</span><b>+${gain}%</b><small>${n} in 6</small></li>` : ""; }).join("");
    const who = ours ? "Your army" : esc(nameOf(p.siege_by));
    let relief = "";
    if (theirs && relation(p.siege_by).war) {
      const near = [...P[i].land, ...P[i].sea].filter((j) => owned(j) && !prov(j).siege_by && troopsAfter(j) > 0).sort((a, b) => troopsAfter(b) - troopsAfter(a));
      if (near.length) {
        const best = near[0], chance = odds(best, i, armyAfter(best));
        relief = `<div class="act"><button class="btn" data-march="${i}" data-from="${best}">⚔ Break the siege with ${troopsAfter(best)} from ${esc(P[best].name)}</button>
          ${chance !== null ? `<span class="sub">${Math.round(chance * 100)}% to win</span>` : ""}</div>`;
      } else relief = `<p class="note">None of your provinces next door has regiments to send.</p>`;
    }
    return `<section class="siege"><h4>${I("castle")} The siege of ${esc(P[i].name)}</h4>
      <div class="sbar"><i style="width:${p.siege_progress}%"></i><span>${p.siege_progress}%</span></div>
      <p class="note">${who} has camped before the walls for ${p.siege_years} year${p.siege_years === 1 ? "" : "s"}${p.besiegers !== null ? ` with ${p.besiegers} regiments` : ""}. The town falls at 100%.</p>
      <div class="cols2"><div><h5>Next year's roll: a die (1–6)</h5><ul class="mods">${mods.map(([label, v]) => `<li><span>${esc(cap(label))}</span><b class="${v > 0 ? "up" : "down"}">${v > 0 ? "+" : "−"}${Math.abs(v)}</b></li>`).join("") || "<li><span>No modifiers</span></li>"}</ul></div>
        <div><h5>What it may bring</h5><ul class="mods">${chances}</ul></div></div>
      <p class="note">${ours ? `Send more regiments by attacking ${esc(P[i].name)} again; bring guns to batter the walls. ${R.siegeDisease ? "The worst roll brings disease into the camp." : ""}`
        : theirs ? "Attack the siege lines from a province next door to break the siege; you cannot march in or raise levies while it lasts."
        : ""}</p>
      ${relief}${ours ? `<div class="act"><button class="btn" data-act="liftsiege">Lift the siege</button><span class="sub">the army marches back next door</span></div>` : ""}</section>`;
  }
  function deed() {
    const box = $("deed");
    if (picked < 0) { box.classList.remove("open"); map.setTargets([]); hint(""); return; }
    const i = picked, p = prov(i), o = p.owner === null ? -1 : nIndex[p.owner], mine = owned(i), works = ruled(i);
    if (mine && !works) ownTab = "army"; // land you occupy: only your regiments act there
    const out = unbundle(p.output_per_turn), extra = unbundle(p.building_output_per_turn);
    const queued = orders.filter((x) => x.type === "build" && pIndex[x.province] === i).map((x) => bIndex[x.building]);
    const info = PaxMap.deedInfo(S, i, {owner: o, isCapital: p.is_capital, dev: p.development, troops: p.troops, monument: p.monument, view: S.views[p.id] ? {...S.views[p.id], src: `/views/${p.id}.jpg`} : null,
      fort: p.fort, unrest: p.unrest, base: out.map((v, k) => v - extra[k]), bonus: extra, slots: p.building_slots, settlement: p.settlement,
      faith: p.faith, heretic: !!(p.faith && p.owner && p.faith !== (p.owner === G.human ? V.me.faith : V.nations.find((n) => n.id === p.owner)?.faith)),
      maxDev: mine ? V.me.modifiers.max_development : R.maxDevelopment, general: p.general,
      built: p.buildings.map((b) => bIndex[b]), levels: p.buildings.map((b) => (p.building_levels || {})[b] || 1), queued: mine ? queued : []});
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
        const next = p.development + 1;
        const devWhy = p.development >= maxDev ? `development is at its ceiling (${maxDev})` : devQueued ? "already ordered this year" : !affordable(dev, t) ? "too costly for now" : "";
        const ground = P[i].terrain;
        body += info.production + `<section><div class="land"><span class="ic">${PaxMap.TERRAIN_ICON[ground]}</span><div><b>${cap(ground)}</b>
            <p class="lore">${esc(PaxMap.TERRAIN_LORE[ground])}</p><div class="effects">${PaxMap.terrainLines(S, ground).map((x) => `<span>${x}</span>`).join("")}</div></div></div></section>
          <section><div class="card ${devWhy ? "blocked" : "ready"}">
            <div class="cardhead"><span class="ic">🏛</span><div><b>Develop to ${Math.min(next, maxDev)}</b>
              <div class="gain">${p.development < maxDev ? gainText(preview.develop) || "<span>more score</span>" : ""}<span>+1 score</span></div></div></div>
            <p class="note">Development raises every yield and the score, which is what wins the game.</p>
            <div class="act"><button class="btn" data-act="develop" ${devWhy ? "disabled" : ""}>${devWhy ? cap(devWhy) : "Develop"}</button><span class="cost">${costText(dev)}</span></div></div></section>`;
        // its people's faith: another than yours costs a quarter of what it yields
        if (p.convert_cost) {
          const cc = unbundle(p.convert_cost), queuedC = orders.some((x) => x.type === "convert");
          const why = queuedC ? (orders.some((x) => x.type === "convert" && pIndex[x.province] === i) ? "ordered this year" : "your preachers are busy this year") : !affordable(cc, t) ? "too costly for now" : "";
          body += `<section><div class="card ${why ? "blocked" : "ready"} heretic"><div class="cardhead"><span class="ic">${PaxMap.FAITH_ICON[p.faith]}</span><div><b>A ${esc(p.faith)} province</b>
              <div class="gain"><span class="neg">−${Math.round(R.faithPenalty * (1 - (V.me.modifiers.faith_tolerance || 0)) * 100)}% of what it yields</span></div></div></div>
            <p class="note">Its people keep another faith than yours. Preachers can turn it ${esc(V.me.faith)} at once; otherwise it may come round by itself, slowly.</p>
            <div class="act"><button class="btn" data-act="convert" ${why ? "disabled" : ""}>${why ? cap(why) : "Send preachers"}</button><span class="cost">${costText(cc)}</span></div></div></section>`;
        }
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
        body += focusCard(i, t);
        const best = B.filter((b) => !p.buildings.includes(b.id) && !queued.includes(bIndex[b.id]) && !(b.tech && V.me.technology[b.tech[0]] < b.tech[1])
            && !(b.requires >= 0 && !p.buildings.includes(B[b.requires].id)))
          .map((b) => [b, preview.buildings[b.id] || {}]).filter(([, gain]) => gain.ducats > 0)
          .sort((a, b) => b[1].ducats - a[1].ducats).slice(0, 2);
        body += monumentCard(i, true, t);
        if (best.length && free > 0) body += `<section><h4>Best works here</h4>${best.map(([b, gain]) =>
          `<div class="act"><span class="ic">${BICON[b.id]}</span><b>${esc(b.name)}</b><span class="gain">${gainText(gain)}</span>
            <button class="btn" data-build="${b.id}" ${affordable(buildCost(b.id), t) ? "" : "disabled"}>Build</button><span class="cost">${costText(buildCost(b.id))}</span></div>`).join("")}</section>`;
      } else if (ownTab === "buildings") {
        // one row per work, in four shelves: built, ordered this year, ready to build, not yet
        const amounts = (c, sign) => RES.map(([, label, ic], k) => c[k] ? `<span class="amt" title="${label}">${sign}${c[k]}${ic}</span>` : "").join("");
        const rows = {built: [], ordered: [], ready: [], later: []};
        B.forEach((b, k) => {
          const built = p.buildings.includes(b.id), ordered = queued.includes(k), cost = buildCost(b.id);
          const needs = b.requires >= 0 && !p.buildings.includes(B[b.requires].id) && !queued.includes(b.requires);
          const tech = b.tech && V.me.technology[b.tech[0]] < b.tech[1];
          const why = built || ordered ? "" : tech ? `needs ${cap(b.tech[0])} ${b.tech[1]}` : needs ? `needs a ${B[b.requires].name.toLowerCase()} first` : free <= 0 ? "no free slot" : !affordable(cost, t) ? "too costly for now" : "";
          const gain = (built ? preview.built || {} : preview.buildings || {})[b.id] || {};
          const plus = RES.map(([key]) => Math.max(0, gain[key] || 0));
          const yields = plus.some((v) => v) ? `<span class="in">${amounts(plus, "+")}</span>` : "";
          const eats = (b.consumes || []).some((v) => v) ? `<span class="out">${amounts(b.consumes, "−")}<small>a year</small></span>` : "";
          const isIdle = built && p.idle.includes(b.id);
          const shelf = built ? "built" : ordered ? "ordered" : why && why !== "too costly for now" ? "later" : "ready";
          const lvl = built ? levelOf(i, b.id) : 0, upOrdered = orders.some((o) => o.type === "upgrade_building" && o.province === p.id && o.building === b.id);
          const upCost = built && lvl < b.maxLevel ? upgradeCost(b.id, lvl + 1) : null;
          const upGain = upCost ? RES.map(([key]) => Math.max(0, ((preview.upgrades || {})[b.id] || {})[key] || 0)) : null;
          const upgrade = !upCost ? "" : upOrdered ? `<span class="badge">⏳ level ${lvl + 1} next year</span>`
            : `<span class="price">${amounts(upCost, "")}</span><button class="btn" data-upgrade="${b.id}" ${affordable(upCost, t) ? "" : `disabled title="Too costly for now"`}>⬆ Level ${lvl + 1}</button>`;
          const right = built ? (isIdle ? `<span class="badge bad" title="Its inputs went unpaid last year">idle</span>` : "") + (upgrade || (b.maxLevel > 1 ? `<span class="badge ok">✓ highest level</span>` : `<span class="badge ok">✓ built</span>`))
            : ordered ? `<span class="badge">⏳ ready next year</span>`
            : shelf === "later" ? `<span class="why">${esc(why)}</span>`
            : `<span class="price">${amounts(cost, "")}</span><button class="btn" data-build="${b.id}" ${why ? `disabled title="${esc(why)}"` : ""}>${why ? "Too costly" : "Build"}</button>`;
          rows[shelf].push(`<div class="brow ${b.category} ${shelf}" title="${esc(`${b.name}: ${b.effect}.`)}">
            <span class="ic">${BICON[b.id]}</span>
            <div class="bmain"><b>${esc(b.name)}${b.unique ? ` <small class="star" title="A great work: one per realm">★</small>` : ""}${built && b.maxLevel > 1 ? ` <small class="lvl" title="Level ${lvl} of ${b.maxLevel}">${"★".repeat(lvl)}${"☆".repeat(b.maxLevel - lvl)}</small>` : !built && b.maxLevel > 1 ? ` <small class="lvl" title="Can be upgraded to level ${b.maxLevel}">up to level ${b.maxLevel}</small>` : ""}</b>
              <div class="bfx">${yields}${eats}${PERK[b.id] ? `<span class="perk">${esc(PERK[b.id])}</span>` : ""}${!yields && !eats && !PERK[b.id] ? `<span class="perk">${esc(b.effect)}</span>` : ""}
                ${upGain && upGain.some((v) => v) ? `<span class="next">next level: ${amounts(upGain, "+")}${(b.consumes || []).some((v) => v) ? " and eats more" : ""}</span>` : ""}</div></div>
            <div class="bside">${right}</div></div>`);
        });
        const shelf = (key, title) => rows[key].length ? `<h5 class="bshelf">${title} <small>${rows[key].length}</small></h5><div class="blist">${rows[key].join("")}</div>` : "";
        body += `<section>${info.slotsHtml}
          ${shelf("built", "Built here")}${shelf("ordered", "Ordered this year")}
          ${free > 0 ? shelf("ready", "You can build") : `<p class="note">All ${info.slots} slots are taken: upgrade what stands here to get more from it.</p>`}
          ${rows.later.length ? `<details class="blater"><summary>Not yet <small>${rows.later.length}</small></summary><div class="blist">${rows.later.join("")}</div></details>` : ""}
          <p class="note">Green: what a work yields here each year. Red: what it eats; unfed, it stands idle. A ${esc((p.settlement || "town").toLowerCase())} has room for ${p.building_slots} works; develop it into a larger town for more. Most works can be raised to level 2 or 3, doing (and eating) more.</p></section>`;
      } else {
        const now = armyAfter(i), ground = P[i].terrain;
        const comp = U.map((u) => `<div class="unit ${now[u.id] ? "" : "none"}" title="${esc(u.name)}: ${esc(u.role)}">
          <span class="ic">${UICON[u.id]}</span><b>${now[u.id]}</b><small>${esc(u.id)}</small></div>`).join("");
        const mixed = U.filter((u) => now[u.id] / Math.max(1, here) >= R.combinedShare).length;
        const marches = targets.map(([j, kind, room]) => {
          const chance = kind === "attack" ? odds(i, j) : null, how = kind === "attack" && prov(j).siege_by !== G.human ? tacticOf(chosenTactic(j, force(i))) : null;
          return `<button class="btn" data-march="${j}" data-kind="${kind}" ${how ? `title="${esc(`${how[2]}: ${how[3]}`)}"` : ""}>${room !== undefined ? "⚓" : kind === "move" ? "➜" : "⚔"} ${esc(P[j].name)}${how ? ` ${how[1]}` : ""}${chance !== null ? ` ${Math.round(chance * 100)}%` : ""}${room !== undefined ? ` <small>(${room})</small>` : ""}</button>`;
        }).join("");
        const tacticChips = `<div class="foci tactics"><button class="btn ${tactic === "best" ? "on" : ""}" data-tactic="best" title="The tactic that does most against each garrison's posture, where you can see it">✦ Best</button>${TACTICS.map(([k, ic, name, what, kind]) =>
          `<button class="btn ${tactic === k ? "on" : ""}" data-tactic="${k}" title="${esc(`${name}: ${what}. Carried by ${kind}; beats ${postureOf(BEATS[k])[2].toLowerCase()}, breaks on ${postureOf(LOSES[k])[2].toLowerCase()}.`)}">${ic} ${name}</button>`).join("")}</div>`;
        const vet = p.veterancy || 0, queuedPosture = orders.find((o) => o.type === "set_posture" && o.province === P[i].id);
        const stance = queuedPosture ? queuedPosture.posture : p.posture || "hold";
        const postureChips = `<div class="foci postures">${POSTURES.map(([k, ic, name, what, kind]) => {
          const beats = TACTICS.find(([t]) => LOSES[t] === k), loses = TACTICS.find(([t]) => BEATS[t] === k);
          return `<button class="btn ${stance === k ? "on" : ""} ${queuedPosture && queuedPosture.posture === k ? "queued" : ""}" data-posture="${k}" title="${esc(`${name}: ${what}. Carried by ${kind}; beats ${beats[2].toLowerCase()}, falls to ${loses[2].toLowerCase()}.`)}">${ic} ${name}</button>`; }).join("")}</div>`;
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
        const standing = prov(i).troops || 0;
        const raising = orders.filter((o) => (o.type === "recruit" || o.type === "hire_mercenaries") && pIndex[o.province] === i).reduce((a, o) => a + o.regiments, 0);
        const leaving = standing + raising - here;
        const tally = raising || leaving ? `<div class="tally"><span><b>${standing}</b> here now</span>${raising ? `<span class="up"><b>+${raising}</b> being raised</span>` : ""}${leaving > 0 ? `<span class="down"><b>−${leaving}</b> marching or disbanded</span>` : ""}<span>= <b>${here}</b> this year</span></div>
          ${raising ? `<p class="note">New regiments are raised before armies move, so they can march or attack this same year. On the map they show as <b class="up">+${raising}</b> until the year ends.</p>` : ""}` : "";
        body += `<section><h4>The garrison${raising || leaving ? " after your orders" : ""}</h4>${tally}<div class="units">${comp}</div>
          <p class="note">On ${esc(ground)} they defend with a strength of ${strength(now, ground, false).toFixed(1)}${mixed >= 3 ? `, and fight ${Math.round((R.combinedBonus[mixed] || R.combinedBonus[3]) * 100)}% harder for their combined arms` : ""}.</p>
          ${here > 0 ? `<p class="note veterancy"><b>${cap(seasoning(vet))}</b>: ${Math.round(vet * 100)}% veterancy, +${Math.round((veteranFactor(vet) - 1) * 100)}% in battle. Victories season them; raw recruits dilute them; the years send them home.</p>` : ""}
          <h5 class="bshelf">How they wait for an attack</h5>${postureChips}
          <p class="note">Whoever can see the garrison sees its posture, and may choose the tactic that beats it. A posture its regiments cannot carry is as bad as one outguessed.</p></section>
          <section><h4>March</h4><div class="actions">
          <div class="row"><button class="btn" id="mixmode">${pickMix ? "Send a fair share instead" : "Choose regiments by kind"}</button></div>
          ${chooser}
          ${leader}
          ${here > 0 && targets.some(([, k]) => k === "attack") ? `<h5 class="bshelf">How they attack</h5>${tacticChips}` : ""}
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
        const all = {}; near.forEach((j) => { const a = armyAfter(j); KINDS.forEach((k) => (all[k] = (all[k] || 0) + (a[k] || 0))); });
        const total = near.reduce((a, j) => a + troopsAfter(j), 0), together = near.length > 1 ? odds(best, i, all, near.length - 1) ?? 0 : null;
        const war = p.owner === null || relation(p.owner).war;
        const f = facing(i), how = tacticOf(bestTactic(i, armyAfter(best))), seen = postureOf(f.posture);
        const watch = f.seen && p.troops ? `<p class="note">${seen[1]} The garrison waits: <b>${seen[2].toLowerCase()}</b> (${seen[3]}); ${seasoning(f.vet)}, ${Math.round(f.vet * 100)}% veterancy. Best answer from ${esc(P[best].name)}: <b>${how[1]} ${how[2].toLowerCase()}</b>.</p>` : "";
        body += `<section><h4>Attack</h4>${watch}<p class="note" style="font-style:normal">All ${troopsAfter(best)} regiments of ${esc(P[best].name)}${g ? ` under ${esc(g.name)}` : ""}
          against ${p.troops}: <b>${Math.round(chance * 100)}% to win</b>.${together !== null ? ` With all ${total} from the ${near.length} provinces next door, in one battle: <b>${Math.round(together * 100)}%</b>.` : ""}
          ${war ? `Select ${esc(P[best].name)} and right-click here.` : `You must declare war on ${esc(N[o].name)} first.`}</p></section>`;
      }
      body += monumentCard(i, false, projected()) + info.production + `<section>${info.slotsHtml}</section>`;
    }
    const warNotes = [];
    if (p.controller) warNotes.push(`🏴 Occupied by ${esc(nameOf(p.controller))}: it yields nothing to ${p.owner === G.human ? "you" : esc(nameOf(p.owner))} until a peace says whose it is.`);
    const scroll = box.scrollTop;
    box.innerHTML = info.header + info.facts + (warNotes.length ? `<section class="warnotes">${warNotes.map((n) => `<p class="note war">${n}</p>`).join("")}</section>` : "") + siegeCard(i) + body;
    // fold the deed to its ribbon, or drop the picture on the Army tab, to keep the map in sight
    box.classList.toggle("min", deedMin);
    box.classList.toggle("compact", deedMin || (mine && ownTab === "army"));
    box.querySelector(".deedhead").insertAdjacentHTML("beforeend", `<button class="mini" data-min title="${deedMin ? "Unfold the deed" : "Fold the deed to see the map"}" aria-label="${deedMin ? "Unfold" : "Fold"}">${deedMin ? "▾" : "▴"}</button>`);
    box.querySelector("[data-min]").onclick = () => { deedMin = !deedMin; deed(); };
    box.scrollTop = scroll;
    box.classList.add("open");
    box.querySelector("[data-close]").onclick = () => { picked = -1; render(); };
    box.querySelectorAll("[data-dtab]").forEach((b) => b.onclick = () => { ownTab = b.dataset.dtab; deedMin = false; deed(); });
    box.querySelectorAll("[data-envoy]").forEach((b) => b.onclick = () => { focus = nIndex[b.dataset.envoy]; openOffice("diplomacy"); });
    box.querySelectorAll(".stepper").forEach(wireStepper);
    const leadBox = box.querySelector("#lead"); if (leadBox) leadBox.onchange = () => { lead = leadBox.checked; deed(); };
    box.querySelectorAll("[data-tactic]").forEach((b) => b.onclick = () => { tactic = b.dataset.tactic; deed(); });
    box.querySelectorAll("[data-posture]").forEach((b) => b.onclick = () => {
      const id = P[i].id; orders = orders.filter((x) => !(x.type === "set_posture" && x.province === id));
      if (b.dataset.posture !== (prov(i).posture || "hold")) queue({type: "set_posture", province: id, posture: b.dataset.posture}); else { render(); }
    });
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
    box.querySelectorAll("[data-march]").forEach((b) => b.onclick = () => (b.dataset.from ? march(+b.dataset.from, +b.dataset.march, "attack") : march(i, +b.dataset.march, b.dataset.kind)));
    box.querySelectorAll("[data-act]").forEach((b) => b.onclick = () => {
      const id = P[i].id, act = b.dataset.act;
      if (act === "develop") queue({type: "develop", province: id});
      if (act === "improve") queue({type: "improve", province: id});
      if (act.startsWith("focus:")) { orders = orders.filter((x) => !(x.type === "set_focus" && x.province === id)); queue({type: "set_focus", province: id, focus: act.slice(6)}); }
      if (act === "convert") queue({type: "convert", province: id});
      if (act === "disband") {
        const unit = box.dataset.disbandkind || null, most = unit ? armyAfter(i)[unit] : troopsAfter(i);
        const order = {type: "disband", province: id, regiments: Math.min(+(box.dataset.disband || 1), most)};
        if (unit) order.unit = unit;
        if (order.regiments > 0) queue(order);
      }
      if (act === "hire") queue({type: "hire_general", province: id});
      if (act === "liftsiege") queue({type: "lift_siege", province: id});
    });
    box.querySelectorAll("[data-build]").forEach((b) => b.onclick = () => queue({type: "build", province: P[i].id, building: b.dataset.build}));
    box.querySelectorAll("[data-upgrade]").forEach((b) => b.onclick = () => queue({type: "upgrade_building", province: P[i].id, building: b.dataset.upgrade}));
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
    const t = projected(), now = unbundle(V.me.resources), inc = unbundle(V.me.income_per_turn);
    const net = RES.map(() => 0), lines = RES.map(() => []);
    for (const l of V.me.ledger) RES.forEach(([key], k) => { const v = l.amount[key] || 0; if (!v) return;
      const signed = l.kind === "income" ? v : -v; net[k] += signed; lines[k].push(tline(esc(cap(l.source)), signed)); });
    const stats = RES.map(([key, label], k) => {
      const head = `<h5>${I(RICON[key])} ${label}: ${now[k]}${t[k] !== now[k] ? ` → ${t[k]} after your orders` : ""}</h5>`;
      const extra = key === "manpower" ? `<div class="dim">The pool fills up to ${V.me.manpower_cap}.</div>` : "";
      return `<div class="stat ${net[k] < 0 && now[k] + net[k] < 0 ? "alarm" : ""}" data-res="${key}"${tip(head + (lines[k].join("") || `<div class="dim">Nothing comes or goes.</div>`) + tline("A year", net[k]).replace('class="tl"', 'class="tl sum"') + extra)}>
        ${I(RICON[key])}<span class="val"><b>${t[k]}</b><i class="${net[k] > 0 ? "pos" : net[k] < 0 ? "neg" : ""}">${sign(net[k])}</i></span></div>`; }).join("");
    const src = (words) => V.me.modifiers.sources.filter((l) => words.some((w) => l.includes(w)))
      .map((l) => `<div class="tl"><span>${esc(l)}</span></div>`).join("") || `<div class="dim">Nothing yet.</div>`;
    const power = Math.round(V.me.modifiers.battle_power * 100), ducatBonus = Math.round((V.me.modifiers.ducat_income + R.stabilityBonus * V.me.stability) * 100);
    const raise = V.me.stability >= R.maxStability || !affordable([stabilityCost(), 0, 0, 0, 0]) || orders.some((o) => o.type === "boost_stability");
    const FAITH = {catholic: "✝", protestant: "✠", orthodox: "☦", sunni: "☪"};
    $("treasury").innerHTML = stats + `
      <div class="stat"${tip(`<h5>${I("scale")} Stability ${sign(V.me.stability)}</h5>${tline("Ducat income", Math.round(R.stabilityBonus * 100 * V.me.stability), "%")}<div class="dim">From −3 to +3. Raising it costs ${stabilityCost()} ducats${V.me.tax > 0 ? ", dearer with high taxes" : ""}.</div>`)}>
        ${I("scale")}<span class="val"><b>${sign(V.me.stability)}</b><i>stability</i></span><button class="btn mini" id="stab" ${raise ? "disabled" : ""}>+</button></div>
      <div class="stat"${tip(`<h5>${I("coins")} Ducat income ${sign(ducatBonus)}%</h5>${tline("Stability", Math.round(R.stabilityBonus * 100 * V.me.stability), "%")}${src(["ducats"])}`)}>
        ${I("landmark")}<span class="val"><b class="${ducatBonus >= 0 ? "" : "neg"}">${sign(ducatBonus)}%</b><i>income</i></span></div>
      <div class="stat"${tip(`<h5>${I("swords")} Battle power ${sign(power)}%</h5>${src(["battle power"])}`)}>
        ${I("swords")}<span class="val"><b>${sign(power)}%</b><i>power</i></span></div>
      <div class="stat"${tip(`<h5>${I("award")} Prestige ${V.me.prestige} of 100</h5>${tline("Ducat income", +(V.me.prestige * 0.1).toFixed(1), "%")}<div class="dim">Half of it counts in your standing (${V.me.standing}), which wins when time runs out. It fades by ${R.prestigeDecay || 1} a year.</div>`)}>
        ${I("award")}<span class="val"><b>${V.me.prestige}</b><i>prestige</i></span></div>
      <div class="stat ${V.me.infamy >= R.coalitionInfamy ? "alarm" : ""}"${tip(`<h5>${I("flame")} Infamy ${V.me.infamy}</h5><div class="dim">Every province taken adds its development. From ${R.coalitionInfamy}, courts may league against you. Fades by ${R.infamyDecay} a year.</div>`)}>
        ${I("flame")}<span class="val"><b>${Math.round(V.me.infamy)}</b><i>infamy</i></span></div>
      ${V.me.war_exhaustion > 0 ? `<div class="stat ${V.me.war_exhaustion >= 10 ? "alarm" : ""}"${tip(`<h5>${I("hourglass")} War exhaustion ${V.me.war_exhaustion.toFixed(1)} of 20</h5>${tline("Ducat income", -Math.round(V.me.war_exhaustion), "%")}<div class="dim">From 10, a point of stability a year. Peace heals it.</div>`)}>
        ${I("hourglass")}<span class="val"><b>${V.me.war_exhaustion.toFixed(1)}</b><i>weariness</i></span></div>` : ""}
      <div class="stat"${tip(`<h5>${FAITH[V.me.faith] || "✝"} ${cap(V.me.faith)}</h5><div class="dim">Courts of the same faith warm to you each year; of other faiths, they cool.</div>`)}>
        <span class="faith">${FAITH[V.me.faith] || "✝"}</span></div>`;
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
      <p class="sub">Trades happen first, so what you buy can be spent this year. What all Europe buys and sells moves next year's prices; the merchants keep ${Math.round(R.marketSpread * (1 - (V.me.modifiers.trade_bonus || 0)) * 100)}% of each deal${V.me.modifiers.trade_bonus ? ` (${Math.round(R.marketSpread * 100)}% before your trade bonuses: economy technology, marketplaces, a treasurer, a royal exchange)` : "; economy technology, marketplaces, a treasurer and a royal exchange lower that cut"}.</p>`;
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
  let recruitAt = null, recruitN = {};
  function recruitBox() {
    const where = V.me.provinces.map((id) => pIndex[id]).filter((i) => ruled(i));
    if (!where.length) return "";
    if (!recruitAt || !where.includes(pIndex[recruitAt])) recruitAt = V.me.capital && where.includes(pIndex[V.me.capital]) ? V.me.capital : P[where[0]].id;
    const i = pIndex[recruitAt], costs = prov(i).recruit_costs || {};
    let total = RES.map(() => 0);
    const rows = U.map((u) => { const price = costs[u.id], n = recruitN[u.id] || 0;
      if (price && n) total = total.map((v, k) => v + unbundle(price)[k] * n);
      const why = price ? "" : u.requires >= 0 ? `needs ${B[u.requires].name.toLowerCase()}` : "not here";
      return `<div class="rrow ${price ? "" : "off"}"${tip(`<h5>${UICON[u.id]} ${esc(u.name)}</h5><div class="dim">${esc(u.lore || u.role)}</div>${tline("Attack", u.attack)}${tline("Defence", u.defence)}<div class="dim">A year: ${u.pay} ducats, ${u.rations} grain</div>`)}>
        <span class="uic">${UICON[u.id]}</span><b>${esc(u.name)}</b><small>${price ? costText(unbundle(price)) : why}</small>
        ${price ? `<span class="stepper"><button type="button" data-recruitkind="${u.id}" data-d="-1">−</button><b class="num">${n}</b><button type="button" data-recruitkind="${u.id}" data-d="1">+</button></span>` : ""}</div>`; }).join("");
    const hired = orders.filter((o) => o.type === "hire_mercenaries").reduce((a, o) => a + o.regiments, 0), left = R.mercenaryLimit - hired, m = Math.min(recruitN.mercs || 0, left);
    const ok = affordable(total) && total.some((v) => v);
    return `<div class="recruit"><div class="row"><span class="sub">Raise in</span><select class="field" id="recruitat">${where.map((j) => `<option value="${P[j].id}" ${P[j].id === recruitAt ? "selected" : ""}>${esc(P[j].name)}</option>`).join("")}</select></div>
      ${rows}<div class="row"><button class="btn" id="recruitgo" ${ok ? "" : "disabled"}>Recruit</button><span class="cost">${total.some((v) => v) ? costText(total) : "choose the regiments"}</span></div>
      <div class="rrow merc"${tip(`<h5>Mercenaries</h5><div class="dim">Landsknechte and Swiss pikes for ducats alone: no manpower, no iron. ${left} of ${R.mercenaryLimit} left this year.</div>`)}><span class="uic">💰</span><b>Mercenaries</b><small>${R.mercenaryCost} ducats each, ${left} left</small>
        <span class="stepper"><button type="button" data-recruitkind="mercs" data-d="-1">−</button><b class="num">${m}</b><button type="button" data-recruitkind="mercs" data-d="1">+</button></span></div>
      <div class="row"><button class="btn" id="mercgo" ${m > 0 && affordable([m * R.mercenaryCost, 0, 0, 0, 0, 0]) ? "" : "disabled"}>Hire</button><span class="cost">${m ? `${m * R.mercenaryCost} ducats` : ""}</span></div></div>`;
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
        <div class="stock"><span class="ic">💪</span><div><b class="num">${sign(Math.round(power * 100))}%</b><span class="label">battle power</span></div><div class="flow"><small>technology, ruler, council</small></div></div>
        <div class="stock"><span class="ic">🚩</span><div><b class="num">${sign(Math.round((myMorale() - 1) * 100))}%</b><span class="label">morale</span></div><div class="flow"><small>stability steadies, war exhaustion tires</small></div></div>
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
      <h4>${I("swords")} Raise regiments</h4>${recruitBox()}
      <h4>Fronts</h4>${fronts || `<p class="muted">No war, and no court masses troops against you.</p>`}
      <h4>⛵ The fleets</h4>${fleetsSection()}
      <h4>Armies</h4><table class="grid num"><thead><tr><th>Province</th><th>Regiments</th><th>Kinds</th><th>General</th><th>Best attack</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="sub">Click an army to select it, then right-click on the map where it should go. The odds count what you can see.</p>
      <h4>Generals, ${V.me.generals.length} of ${V.me.modifiers.max_generals}</h4>${generals || `<p class="muted">No general serves you.</p>`}
      ${V.me.generals.length < V.me.modifiers.max_generals ? `<div class="row"><select class="field" id="hireat" aria-label="Appoint a general in">${options(pIndex[V.me.capital])}</select>
        <button class="btn" id="hire" ${affordable(R.generalCost) ? "" : "disabled"}>Appoint a general</button><span class="sub">${costText(R.generalCost)}</span></div>` : ""}
      <p class="sub">A general adds ${Math.round(R.generalBonus * 100)}% battle power per star to the regiments he leads or defends with. He falls if his province is taken.</p>
      <h4>The regiments of the age</h4><table class="grid num units-book"><thead><tr><th>Kind</th><th>Att/Def</th><th>Cost</th><th>A year</th><th class="left">Raised in</th></tr></thead><tbody>${book}</tbody></table>
      <p class="sub">Two or more kinds, each a fifth of an army, fight harder together. Every tenth of an attacking army in guns knocks a fort level off.</p></div>`;
  }
  // ------------------------------------------------------------------ the New World
  const REGION_IC = {caribbean: "🏝", brazil: "🌴", guinea: "🐘", east_indies: "🌶", new_spain: "🥈", peru: "⛰", north_america: "🦫"};
  const regionName = (id) => R.regions[id]?.name || id;
  function worldTab() {
    const C = R.colonial, mine = V.me.colonies || {}, sent = V.me.expeditions || [];
    const total = Object.values(mine).reduce((a, b) => a + b, 0), dues = V.me.colonial_dues || {};
    const dueArr = RES.map(([k]) => dues[k] || 0);
    const yieldText = (arr, sign = "+") => RES.map(([, label, ic], k) => arr[k] ? `<span class="amt" title="${label}">${sign}${arr[k]}${ic}</span>` : "").join(" ");
    const spirit = C.spirits[G.human], seizeAt = spirit && spirit.seize ? spirit.seize : C.seize;
    const ocean = navalPower(G.human, "atlantic");
    const queued = (r) => orders.some((o) => o.type === "send_expedition" && o.region === r);
    const blockade = (V.me.blockaded || []).includes("atlantic");
    const cards = [...V.new_world].sort((a, b) => a.opens - b.opens).map((r) => {
      const spec = R.regions[r.id], have = mine[r.id] || 0, taken = Object.values(r.held).reduce((a, b) => a + b, 0);
      const dots = [...Object.entries(r.held).flatMap(([n, c]) => Array(c).fill(n))].map((n) => `<i class="place" style="background:${N[nIndex[n]].color}" title="${esc(nameOf(n))}"></i>`).join("")
        + `<i class="place free"></i>`.repeat(Math.max(0, r.slots - taken));
      const exp = sent.find((e) => e.region === r.id);
      const years = Math.max(1, Math.ceil(100 / Math.max(5, r.your_progress + 17.5)));
      const why = queued(r.id) ? "" : r.send_error;
      const send = exp ? `<div class="expedition"><span>⛵ Your expedition: ${exp.progress}%</span><i class="bar"><b style="width:${exp.progress}%"></b></i></div>`
        : queued(r.id) ? `<p class="ok">⛵ The expedition sails this year.</p>`
        : `<div class="act"><button class="btn" data-expedition="${r.id}" ${why || !affordable(C.cost) ? "disabled" : ""} ${why ? `title="${esc(cap(why))}"` : ""}>⛵ Send an expedition</button><span class="cost">${why ? esc(cap(why)) : `${costText(C.cost)}; about ${years} year${years > 1 ? "s" : ""}`}</span></div>`;
      const seize = V.me.wars.filter((w) => w.attacks_allowed_from_turn <= V.turn && r.held[w.enemy]).map((w) => {
        const theirs = navalPower(w.enemy, "atlantic"), ok = ocean >= C.ships && ocean >= seizeAt * theirs;
        const already = orders.some((o) => o.type === "seize_colony" && o.region === r.id && o.enemy === w.enemy);
        return `<button class="btn" data-seize="${r.id}:${w.enemy}" ${ok && !already ? "" : "disabled"} title="${esc(`Your Atlantic fleet ${ocean.toFixed(1)} against ${nameOf(w.enemy)}'s ${theirs.toFixed(1)}: you need ${seizeAt} times theirs`)}">⚔ Take a colony from ${esc(nameOf(w.enemy))}</button>`; }).join("");
      return `<div class="regioncard ${r.open ? "" : "closed"} ${have ? "ours" : ""}"><div class="rhead"><span class="ic">${REGION_IC[r.id] || "🌎"}</span><b>${esc(r.name)}</b>${have ? `<span class="chip">${have} yours</span>` : ""}</div>
        <p class="lore">${esc(r.lore)}</p>
        <div class="rfacts"><span>${esc(cap(r.goods))}: ${yieldText(spec.yields)} a colony</span><span class="slots" title="${taken} of ${r.slots} places taken; at most ${spec.cap} for one crown">${dots}</span></div>
        ${r.open ? send + (seize ? `<div class="row">${seize}</div>` : "") : `<p class="sub">The way there is known from ${r.opens}.</p>`}</div>`;
    }).join("");
    return `<div class="pad"><h4>${I("globe")} The New World</h4>
      <div class="stocks">
        <div class="stock"><span class="ic">🏝</span><div><b class="num">${total}</b><span class="label">colonies</span></div><div class="flow">${yieldText(dueArr) || "<small>none yet</small>"}<small>a year</small></div></div>
        <div class="stock"><span class="ic">⛵</span><div><b class="num">${sent.length + orders.filter((o) => o.type === "send_expedition").length}</b><span class="label">expeditions of ${C.atOnce}</span></div></div>
        <div class="stock"><span class="ic">🌊</span><div><b class="num">${ocean.toFixed(1)}</b><span class="label">Atlantic fleet</span></div><div class="flow"><small>${C.ships} escorts an expedition</small></div></div>
      </div>
      ${spirit ? `<p class="cspirit"><b>${esc(spirit.title)}</b>: ${esc(spirit.words)}.</p>` : ""}
      ${blockade ? `<p class="note war">⚓ An enemy fleet blockades the Atlantic: the colonies send home ${Math.round(C.blockade * 100)}% less.</p>` : ""}
      <div class="regions">${cards}</div>
      <p class="sub">An expedition needs a port of yours on the Atlantic or the Baltic and a fleet to escort it. Each year it makes progress by a die, your fleet and your crown's way, less the region's hardness; at 100% it founds a colony, unless every place was taken first. At war, an Atlantic fleet ${C.seize} times the enemy's takes its colonies; an enemy that rules the Atlantic halves what they send home.</p></div>`;
  }
  const BRANCH_IC = {military: "⚔", economy: "💰", engineering: "⚒", naval: "⚓", administration: "📜"};
  const branchName = (id) => (T.find((b) => b.id === id) || {name: id}).name;
  function techTab() {
    const doing = researching();
    const net = V.me.income_per_turn.ducats - V.me.army_upkeep_per_turn.ducats - V.me.inputs_per_turn.ducats;
    const yearsFor = (cost) => { const short = Math.max(0, cost.ducats - V.me.resources.ducats);
      return !short ? "affordable now" : net > 0 ? `in about ${Math.ceil(short / net)} year${Math.ceil(short / net) === 1 ? "" : "s"}` : "not on this income"; };
    const chosenAt = (id, k) => ((V.me.doctrines || {})[id] || [])[k];
    const cards = T.map((b) => {
      const level = V.me.technology[b.id], cost = V.me.research_costs[b.id], next = b.levels[level];
      const word = b.id === "engineering" ? "cheaper buildings and development" : b.id === "economy" ? "ducats and grain" : b.id === "military" ? "battle power" : "";
      const unlocked = next ? B.filter((x) => x.tech && x.tech[0] === b.id && x.tech[1] === level + 1) : [];
      const busy = doing && doing.branch === b.id;
      const need = next && next.requires && V.me.technology[next.requires[0]] < next.requires[1] ? next.requires : null;
      const can = !doing && cost && affordable(unbundle(cost)) && !need;
      const doctrines = next ? (next.options.length ? next.options : [{name: "Research", effect: ""}]).map((o, k) =>
        `<button class="btn doctrine ${busy && doing.choice === k ? "on" : ""}" data-research="${b.id}" data-choice="${k}" ${can ? "" : "disabled"}${o.lore ? ` title="${esc(o.lore)}"` : ""}><b>${esc(o.name)}</b>${o.effect ? `<small>${esc(o.effect)}</small>` : ""}</button>`).join("") : "";
      const taken = b.levels.slice(0, level).map((step, k) => step.options[chosenAt(b.id, k)]).filter(Boolean);
      return `<div class="studycard ${busy ? "doing" : ""}"><div class="shead"><span class="ic">${BRANCH_IC[b.id]}</span><b>${b.name}</b><span class="num">${level} / ${R.maxTech}</span></div>
        <i class="bar"><b style="width:${Math.round(100 * level / R.maxTech)}%"></b></i>
        ${word ? `<p class="sub">Now: +${Math.round(b.perLevel * 100 * level)}% ${word}.${next ? ` Next: +${Math.round(b.perLevel * 100 * (level + 1))}%.` : ""}</p>` : `<p class="sub">${esc(cap(b.effect))}.</p>`}
        ${taken.length ? `<p class="sub">Doctrines: ${taken.map((o) => `<span class="chip">${esc(o.name)}</span>`).join(" ")}</p>` : ""}
        ${next ? `<p><b>${esc(next.name)}</b>: ${esc(next.unlocks)}</p>${unlocked.length ? `<div class="unlocks"><span class="sub">Unlocks</span>${unlocked.map((x) => `<span class="chipb"${tip(`<h5>${BICON[x.id]} ${esc(x.name)}</h5><div>${esc(x.effect)}</div><div class="dim">Costs ${costText(x.cost)}${(x.consumes || []).some((v) => v) ? `; eats ${costText(x.consumes)} a year` : ""}</div>`)}>${BICON[x.id]} ${esc(x.name)}</span>`).join("")}</div>` : ""}
          ${next.lore ? `<p class="lore">${esc(next.lore)}</p>` : ""}
          ${need ? `<p class="note war">Needs ${esc(branchName(need[0]).toLowerCase())} ${need[1]} first.</p>` : ""}
          ${busy ? `<p class="ok">Researching this year: ${esc((next.options[doing.choice] || {name: next.name}).name)}</p>` : `<p class="sub">Choose a doctrine: the other is lost for good.</p>`}
          <div class="doctrines">${doctrines}</div>
          ${cost ? `<p class="cost">${costText(unbundle(cost))}, ${yearsFor(cost)}</p>` : ""}` : `<p class="ok">Mastered.</p>`}</div>`;
    }).join("");
    const columns = T.map((b) => {
      const level = V.me.technology[b.id];
      const nodes = b.levels.map((step, k) => {
        const n = k + 1, done = n <= level, nxt = n === level + 1;
        const state = done ? "done" : nxt ? (doing && doing.branch === b.id ? "doing" : "next") : "locked";
        const pickedDoc = done ? step.options[chosenAt(b.id, k)] : null;
        return `<div class="node ${state}" title="${esc(step.name)}: ${esc(step.unlocks)}. ${esc(step.lore || "")}"><div class="lvl">${done ? "✓" : n}</div><b>${esc(step.name)}</b>
          <div class="unl">${esc(cap(step.unlocks))}</div>${step.requires ? `<div class="req">needs ${esc(branchName(step.requires[0]).toLowerCase())} ${step.requires[1]}</div>` : ""}
          <div class="opts">${step.options.map((o) => `<span class="opt ${pickedDoc === o ? "on" : pickedDoc ? "lost" : ""}" title="${esc(o.effect)}">${esc(o.name)}</span>`).join("")}</div></div>`;
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
  // the court a sitter belongs to, from its colour (a council's own colour is mixed: then it is yours)
  const CULTURE = {ottomans: "ottoman", russia: "russian"};
  const portrait = (person, color, size) => PaxMap.portrait(person, color, size, CULTURE[N.find((n) => n.color === color)?.id ?? G.human] || "");
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
    const spirits = (S.traditions || {})[G.human] || [], own = NU[G.human];
    const spirit = spirits.length || own ? `<h4>The spirit of the nation</h4><div class="spirits">
      ${spirits.map(([title, words]) => `<div class="spirit"><b>${esc(title)}</b><small>${esc(words)}</small></div>`).join("")}
      ${own ? `<div class="spirit unit"><b>${UICON[own.kind]} ${esc(own.name)}</b><small>${esc(own.lore)} ${[own.attack !== 1 && `attack ×${own.attack}`, own.defence !== 1 && `defence ×${own.defence}`,
        ...Object.entries(own.terrain).map(([g, v]) => `×${v} on ${g}`), own.cost !== 1 && `${Math.round((1 - own.cost) * 100)}% cheaper`].filter(Boolean).join(", ")}.</small></div>` : ""}</div>` : "";
    return `<div class="pad"><h4>Glory</h4>${patronage}${spirit}
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
    if (theirGrudges(nid).length) out.push(`<span class="chip war" title="${esc(theirGrudges(nid).map((g) => `${g.reason} (${g.since_year}), until ${g.until_year}`).join("; "))}">💢 remembers</span>`);
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
  function proposalText(p) {
    const from = esc(nameOf(p.sender));
    return p.kind === "alliance" ? `${from} proposes an alliance.`
      : p.kind === "non_aggression" ? `${from} proposes a non-aggression pact for ten years.`
      : p.kind === "peace" ? `${from} offers peace${p.reply_to ? " (a counter-offer)" : ""}: ${termsText(p, p.sender) || "a white peace"}.`
      : p.kind === "trade" ? `${from} offers ${costText(unbundle(p.give))} for ${costText(unbundle(p.receive))}${p.reply_to ? " (a counter-offer)" : ""}.`
      : p.kind === "marriage" ? `${from} proposes a royal marriage between your houses.`
      : p.kind === "coalition" ? `${from} invites you into a league against ${esc(nameOf(p.enemy))}: if it attacks either of you, both go to war.`
      : `${from} calls you to arms against ${esc(nameOf(p.enemy))}. Ignoring it ends the alliance.`;
  }
  function proposalCard(p) {
    const answered = orders.find((o) => o.type === "respond" && o.proposal_id === p.id), what = proposalText(p);
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
      ${grudgeWeight(nid) >= R.grudgeRefuses ? `<p class="sub warn">💢 ${esc(nameOf(nid))} has not forgotten what you did (see the Dossier): it will refuse an alliance, pact or marriage.</p>` : ""}
      <p class="sub">Words do not change the rules; rulers read them. A proposal must be answered next year or it lapses.</p></div>`;
  }
  // What one court will not forget of the other, both ways.
  const theirGrudges = (nid) => (V.nations.find((x) => x.id === nid)?.remembers || []);
  const myGrudges = (nid) => (V.me.grudges || []).filter((g) => g.against === nid);
  const grudgeWeight = (nid) => theirGrudges(nid).reduce((a, g) => a + g.weight, 0);
  function memories(nid) {
    const them = theirGrudges(nid), mine = myGrudges(nid), name = esc(nameOf(nid));
    if (!them.length && !mine.length) return "";
    const line = (g, who) => `<li><span class="yr">${g.since_year}</span> ${who} ${esc(g.reason.replace(/ it\b/, who === "You" ? " them" : " you"))} <small>· remembered until ${g.until_year}, −${g.weight} a year</small></li>`;
    return `<h4>💢 What is not forgotten</h4><ul class="history grudges">${them.map((g) => line(g, "You")).join("")}${mine.map((g) => line(g, name)).join("")}</ul>
      ${grudgeWeight(nid) >= R.grudgeRefuses ? `<p class="sub warn">${name} will sign no alliance, pact or marriage with you while this weighs on it.</p>` : ""}`;
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
      ${memories(nid)}
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
  // what a peace may move from `owner` to `taker`, by the engine's rules: land the taker occupies,
  // or land next to what it holds; a capital only if the taker occupies it
  const transferable = (owner, taker) => {
    const held = new Set(V.provinces.filter((p) => (p.controller || p.owner) === taker).map((p) => p.id));
    return V.provinces.filter((p) => p.owner === owner && (p.controller === taker
      || (!p.is_capital && [...p.neighbors, ...p.sea_neighbors].some((x) => held.has(x)))))
      .sort((a, b) => (b.controller === taker) - (a.controller === taker) || b.development - a.development);
  };
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
  // Python rounds halves to the even number; the page must too, or a demand the engine allows
  // (an occupied province worth exactly the war score it gave) would look too dear.
  const pyRound = (x) => { const f = Math.floor(x), d = x - f; return Math.abs(d - 0.5) < 1e-9 ? (f % 2 === 0 ? f : f + 1) : Math.round(x); };
  function warCost(payer, terms) {
    const owned = V.provinces.filter((p) => p.owner === payer);
    const total = Math.max(1, owned.reduce((t, p) => t + p.development, 0));
    const income = Math.max(10, payer === G.human ? V.me.income_per_turn.ducats : owned.reduce((t, p) => t + p.output_per_turn.ducats, 0));
    let cost = (terms.demand || []).reduce((t, id) => { const p = prov(pIndex[id]), share = pyRound(100 * p.development / total);
      return t + (p.controller ? share : Math.max(5, share)); }, 0);
    const r = terms.receive || {};
    const worth = (r.ducats || 0) + 2 * ((r.iron || 0) + (r.timber || 0)) + 3 * (r.manpower || 0) + (r.grain || 0);
    if (worth) cost += pyRound(10 * worth / income);
    if (terms.ask_tribute) cost += pyRound(10 * terms.ask_tribute * R.tributeYears / income / 2);
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
    const score = warOf(nid)?.war_score ?? 0, them = esc(nameOf(nid));
    const sent = V.proposals_sent.find((p) => p.recipient === nid && p.kind === "peace");
    const queued = orders.some((o) => o.type === "propose_peace" && o.target === nid);
    const row = (p, chosen, id, payer) => `<label class="tpick"><input type="checkbox" data-${id}="${p.id}" ${(chosen || []).includes(p.id) ? "checked" : ""}>
      <span class="nm">${esc(p.name)}</span><small>${p.development} dev.${p.controller && p.controller !== p.owner ? ", occupied" : ""}${p.is_capital ? ", capital" : ""}</small>
      ${id === "demand" ? `<b class="wc" title="War score this costs">${warCost(payer, {demand: [p.id]})}</b>` : ""}</label>`;
    const list = (ps, chosen, id, payer, none) => ps.length ? ps.map((p) => row(p, chosen, id, payer)).join("") : `<p class="muted">${none}</p>`;
    const money = RES.map(([key, label, ic]) => `<tr><td>${ic} ${label}</td>
      <td><input type="number" class="field" min="0" data-side="receive" data-r="${key}" value="${(c.receive || {})[key] || 0}" aria-label="${label} they pay"></td>
      <td><input type="number" class="field" min="0" data-side="give" data-r="${key}" value="${(c.give || {})[key] || 0}" aria-label="${label} you pay"></td></tr>`).join("");
    const status = sent ? `<p class="pstatus">📜 Your offer is with ${them}'s envoys: they answer when the coming year ends. You will read their answer in the year's report and the Correspondence.</p>`
      : queued ? `<p class="pstatus">📜 Your offer leaves when you end the year; ${them} answers the year after.</p>` : "";
    return `<details open class="peace"><summary>${counter ? "Your counter-offer" : "Terms of peace"}</summary>
      ${status}
      <div class="pscore"><div><span class="sub">Your war score</span><b class="${score > 0 ? "pos" : score < 0 ? "neg" : ""}">${sign(score)}</b></div>
        <i class="meter"><b id="peace-meter" style="width:0%"></b></i><span class="sub" id="peace-cost"></span></div>
      <p class="sub">${counter ? "Their offer, turned to face you. Change what you will and send it back." : "Leave everything empty for a white peace. What you demand must fit in your war score; what you offer is never limited."}</p>
      <h5 class="tsec">Provinces they give you</h5><div class="tlist">${list(transferable(nid, G.human), c.demand, "demand", nid, "None you could take: occupy their land first.")}</div>
      <h5 class="tsec">Provinces you give them</h5><div class="tlist">${list(transferable(G.human, nid), c.cede, "cede", G.human, "None of yours borders them or is in their hands.")}</div>
      <h5 class="tsec">Gold and goods</h5>
      <table class="tmoney"><thead><tr><th></th><th>They pay you</th><th>You pay them</th></tr></thead><tbody>${money}
        <tr><td>Tribute <small>a year, ${R.tributeYears} years</small></td><td><input type="number" class="field" min="0" max="500" id="ask-tribute" value="${c.ask_tribute || 0}"></td>
          <td><input type="number" class="field" min="0" max="500" id="pay-tribute" value="${c.pay_tribute || 0}"></td></tr></tbody></table>
      <label class="tlimit"><input type="checkbox" id="limit-on"> Limit their army during the truce to <input type="number" class="field" min="0" id="limit-army" value="10"> regiments</label>
      <textarea id="peace-note" maxlength="300" placeholder="Your words to their envoy (optional)"></textarea>
      <div class="row">${counter ? `<button class="btn" data-dip="counter_peace">Send the counter-offer</button><button class="btn" data-dip="drop_counter">Never mind</button>`
        : `<button class="btn primary" data-dip="propose_peace" ${sent || queued ? 'disabled data-locked="1"' : ""}>Propose peace</button>`}</div></details>`;
  }
  function bundleInputs(id, values = null) {
    return `<div class="bundle" id="${id}">${RES.map(([key, label, ic]) => `<label>${ic}<input type="number" min="0" value="${(values && values[key]) || 0}" data-r="${key}" aria-label="${label}"></label>`).join("")}</div>`;
  }
  function readBundle(id) { const b = {}; document.querySelectorAll(`#${id} input`).forEach((i) => (b[i.dataset.r] = Math.max(0, +i.value || 0))); return b; }
  const emptyBundle = (b) => Object.values(b).every((v) => !v);
  function readPeace() {
    const ids = (attr) => [...document.querySelectorAll(`[data-${attr}]:checked`)].map((x) => x.dataset[attr]);
    const side = (s) => { const b = {}; document.querySelectorAll(`details.peace [data-side="${s}"]`).forEach((i) => (b[i.dataset.r] = Math.max(0, +i.value || 0))); return b; };
    const terms = {give: side("give"), receive: side("receive"), cede: ids("cede"), demand: ids("demand"),
      pay_tribute: Math.max(0, +$("pay-tribute").value || 0), ask_tribute: Math.max(0, +$("ask-tribute").value || 0)};
    if ($("limit-on").checked) terms.limit_army = Math.max(0, +$("limit-army").value || 0);
    const note = $("peace-note").value.trim(); if (note) terms.note = note;
    return terms;
  }
  // ------------------------------------------------------------------ missions: a vertical tree, one column per chain
  function missionsTab() {
    const ms = V.me.missions || [];
    if (!ms.length) return `<p class="muted pad">This crown has no ambitions of its own.</p>`;
    const roots = ms.filter((m) => !m.after || !ms.some((x) => x.id === m.after));
    const chain = (m) => [m, ...ms.filter((x) => x.after === m.id).flatMap(chain)];
    const ICON_OF = {done: "award", open: "target", locked: "castle"};
    const node = (m) => {
      const goals = m.goals.map((g) => `<div class="tl"><span>${g.have >= g.need ? "✓" : "○"} ${esc(g.text)}</span><b class="${g.have >= g.need ? "pos" : ""}">${g.have}/${g.need}</b></div>`).join("");
      const share = m.goals.reduce((a, g) => a + Math.min(1, g.have / Math.max(1, g.need)), 0) / Math.max(1, m.goals.length);
      const after = m.after ? ms.find((x) => x.id === m.after) : null;
      const tipHtml = `<h5>${esc(m.title)}</h5><div class="dim">${esc(m.lore)}</div>${goals}<div class="tl sum"><span>Reward</span><b class="pos">${esc(m.reward)}</b></div>${m.status === "locked" && after ? `<div class="dim">Opens after “${esc(after.title)}”.</div>` : ""}`;
      return `<div class="mnode ${m.status}"${tip(tipHtml)}><span class="mic">${I(ICON_OF[m.status])}</span>
        <b>${esc(m.title)}</b>${m.status === "open" ? `<i class="bar"><b style="width:${Math.round(share * 100)}%"></b></i>` : `<small>${m.status === "done" ? "fulfilled" : "locked"}</small>`}</div>`;
    };
    const cols = roots.map((r) => `<div class="mcol">${chain(r).map(node).join(`<div class="mlink"></div>`)}</div>`).join("");
    const open = ms.filter((m) => m.status === "open").map((m) => `<div class="mission open"><div class="mhead">${I("target")}<b>${esc(m.title)}</b></div>
      <ul class="goals">${m.goals.map((g) => `<li class="${g.have >= g.need ? "met" : ""}"><span>${g.have >= g.need ? "✓" : "○"} ${esc(g.text)}</span>
        <i class="bar"><b style="width:${Math.round(100 * Math.min(1, g.have / Math.max(1, g.need)))}%"></b></i><small class="num">${g.have}/${g.need}</small></li>`).join("")}</ul>
      <div class="sub">Reward: <span class="pos">${esc(m.reward)}</span></div></div>`).join("");
    const done = ms.filter((m) => m.status === "done").length;
    const destiny = R.ambitionVictory ? `<div class="destiny"><span class="ic">🏆</span><div><b>${done} of ${ms.length} ambitions fulfilled</b>
      <small>Fulfil them all and your crown wins the game outright, whatever its size.</small><i class="bar"><b style="width:${Math.round(100 * done / Math.max(1, ms.length))}%"></b></i></div></div>` : "";
    return `<div class="pad">${destiny}<div class="mtree">${cols}</div>
      <p class="sub">Hover a mission for its goals and reward. A mission is fulfilled by itself at the end of a year in which all its goals hold.</p>
      ${open ? `<h4>${I("target")} Open now</h4><div class="missions">${open}</div>` : ""}</div>`;
  }
  // ------------------------------------------------------------------ the ledger: every court side by side
  let ledgerSort = "standing", ledgerDesc = true, ledgerFilter = "all";
  function ledgerTab() {
    const rows = [{id: G.human, name: V.me.name, me: true, standing: V.me.standing, provinces: V.me.provinces.length, technology: V.me.technology,
        prestige: V.me.prestige, infamy: V.me.infamy, opinion: null, generals: V.me.generals.length, alive: true},
      ...V.nations.filter((n) => n.alive).map((n) => ({...n, opinion: n.opinion_of_you}))].map((n) => {
      const land = V.provinces.filter((p) => p.owner === n.id);
      const seen = land.filter((p) => p.troops !== null);
      return {...n, development: land.reduce((a, p) => a + p.development, 0), seen: seen.reduce((a, p) => a + (p.troops || 0), 0), hidden: seen.length < land.length,
        mil: n.technology.military, eco: n.technology.economy, eng: n.technology.engineering};
    });
    const near = new Set(V.provinces.filter((p) => p.owner && p.owner !== G.human && [...p.neighbors, ...p.sea_neighbors].some((x) => prov(pIndex[x]).owner === G.human)).map((p) => p.owner));
    const keep = {all: () => true, neighbours: (n) => n.me || near.has(n.id), war: (n) => n.me || V.me.at_war_with.includes(n.id),
      friends: (n) => n.me || V.me.treaties.some((t) => t.partner === n.id && ["alliance", "marriage", "non_aggression", "coalition"].includes(t.kind)),
      players: (n) => n.me || (G.humans && G.humans[n.id])}[ledgerFilter];
    const COLS = [["standing", "award", "Standing: development plus half the prestige"], ["provinces", "map", "Provinces"], ["development", "building-2", "Development"],
      ["seen", "swords", "Regiments seen (a + means some are hidden by the fog of war)"], ["generals", "flag", "Generals"],
      ["mil", "shield", "Military technology"], ["eco", "coins", "Economy technology"], ["eng", "hammer", "Engineering technology"],
      ["prestige", "sparkles", "Prestige"], ["infamy", "flame", "Infamy"], ["opinion", "heart", "What they think of you"]];
    const list = rows.filter(keep).sort((a, b) => ((a[ledgerSort] ?? -999) - (b[ledgerSort] ?? -999)) * (ledgerDesc ? -1 : 1));
    const best = Object.fromEntries(COLS.map(([k]) => [k, Math.max(...list.map((n) => n[k] ?? -999))]));
    const cell = (n, k) => { const v = n[k]; if (v === null || v === undefined) return "<td>·</td>";
      const shown = k === "opinion" ? sign(v) : k === "infamy" ? Math.round(v) : k === "seen" && n.hidden ? `${v}+` : v;
      const cls = k === "opinion" ? (v > 0 ? "pos" : v < 0 ? "neg" : "") : k === "infamy" && v >= R.coalitionInfamy ? "neg" : v === best[k] && list.length > 1 ? "lead" : "";
      return `<td class="${cls}">${shown}</td>`; };
    return `<div class="pad"><div class="filters">${[["all", "All"], ["neighbours", "Neighbours"], ["war", "At war"], ["friends", "Friends"], ["players", "Players"]].map(([id, label]) =>
        `<button class="btn ${ledgerFilter === id ? "on" : ""}" data-lfilter="${id}">${label}</button>`).join("")}</div>
      <div class="ledgerwrap"><table class="grid num ledgertab"><thead><tr><th class="left">Court</th>${COLS.map(([k, icon, label]) =>
        `<th data-lsort="${k}" class="${ledgerSort === k ? "sorted" : ""}"${tip(`<h5>${label}</h5><div class="dim">Click to sort</div>`)}>${I(icon)}${ledgerSort === k ? (ledgerDesc ? "▾" : "▴") : ""}</th>`).join("")}</tr></thead>
        <tbody>${list.map((n) => `<tr class="${n.me ? "me" : "court"}" data-court="${n.id}"><td class="left">${PaxMap.flag(n.id, N[nIndex[n.id]].color, 20, "flag inline")} ${esc(n.name)}${G.humans && G.humans[n.id] && !n.me ? " 👤" : ""}</td>${COLS.map(([k]) => cell(n, k)).join("")}</tr>`).join("")}</tbody></table></div>
      <p class="sub">The best in each column is in gold. Armies count only what your scouts can see. Click a court to treat with it.</p></div>`;
  }
  // ------------------------------------------------------------------ correspondence: everything addressed to you, filtered
  let corrCourt = "", corrKind = "all";
  const CORR_KINDS = {letters: ["message"], proposals: ["proposal_made", "proposal_rejected", "proposal_expired", "proposal_countered"],
    treaties: ["treaty_signed", "treaty_broken", "treaty_cancelled", "treaty_expired", "coalition_joined", "coalition_dissolved", "gift", "trade_completed", "trade_failed"],
    wars: ["war_declared", "joined_war", "call_to_arms_ignored", "peace_signed", "province_ceded"]};
  function lettersTab() {
    const decisions = V.me.pending_events.map((e) => eventCard(e)).join("");
    const proposals = V.proposals_to_answer.filter((p) => !corrCourt || p.sender === corrCourt).map(proposalCard).join("");
    const all = V.nations.flatMap((n) => n.correspondence.map((e) => ({e, court: n.id})));
    const seen = new Set();
    const items = all.filter(({e}) => { const key = `${e.turn}:${e.kind}:${e.summary}`; if (seen.has(key)) return false; seen.add(key); return true; })
      .filter(({court}) => !corrCourt || court === corrCourt)
      .filter(({e}) => corrKind === "all" || (CORR_KINDS[corrKind] || []).includes(e.kind))
      .sort((a, b) => b.e.turn - a.e.turn).slice(0, 60)
      .map(({e, court}) => { const mine = (e.data.sender || e.nations[0]) === G.human;
        const body = e.kind === "message" ? `<div class="letter">${esc(e.data.text)}</div>` : `<div>${ICON[e.kind] || "•"} ${esc(e.summary)}</div>${e.data.note ? `<q>${esc(e.data.note)}</q>` : ""}`;
        return `<div class="item corr ${mine ? "mine" : ""}"><small>${yearOf(e.turn)} · ${PaxMap.flag(court, N[nIndex[court]].color, 16, "flag inline")} ${mine ? `you → ${esc(nameOf(court))}` : esc(nameOf(court))}</small>${body}</div>`; }).join("");
    const courts = V.nations.filter((n) => n.alive && n.correspondence.length);
    return `${decisions ? `<div class="pad"><h4>${I("crown")} For the crown to decide</h4>${decisions}</div>` : ""}
      <div class="pad"><div class="filters"><select class="field" id="corrcourt" aria-label="Court"><option value="">Every court</option>${courts.map((n) => `<option value="${n.id}" ${corrCourt === n.id ? "selected" : ""}>${esc(n.name)}</option>`).join("")}</select>
        ${[["all", "All"], ["letters", "Letters"], ["proposals", "Proposals"], ["treaties", "Treaties"], ["wars", "Wars"]].map(([id, label]) => `<button class="btn ${corrKind === id ? "on" : ""}" data-ckind="${id}">${label}</button>`).join("")}</div>
      ${proposals ? `<h4>${I("scroll-text")} Awaiting your answer</h4>${proposals}` : ""}
      <h4>${I("mail")} Letters and dealings</h4>${items || `<p class="muted">Nothing here yet.</p>`}</div>`;
  }
  const failedOrder = (e) => { try { return describe(JSON.parse(e.data.action)).replace(/<[^>]+>/g, ""); } catch { return "An order"; } };
  const told = (e) => e.kind === "order_rejected" ? `✗ ${failedOrder(e)}: ${e.data.reason}`
    : ["proposal_rejected", "proposal_countered"].includes(e.kind) && e.data.note ? `${e.summary}: “${e.data.note}”`
    : e.kind === "proclamation" ? `${e.summary}: “${e.data.text}”` : e.summary;
  let chronCourt = "", chronKind = "all";
  const CHRON_KINDS = {war: ["battle", "naval_battle", "war_declared", "joined_war", "peace_signed", "province_captured", "province_occupied", "province_ceded", "province_liberated", "siege", "nation_eliminated", "capital_moved", "general_fell", "call_to_arms_ignored"],
    diplomacy: ["grudge", "treaty_signed", "treaty_broken", "treaty_cancelled", "treaty_expired", "coalition_joined", "coalition_dissolved", "gift", "trade_completed", "message", "proclamation", "stance_changed", "infamy"],
    realm: ["built", "developed", "improved", "researched", "mission_completed", "succession", "event_decided", "stability_changed", "prestige_changed", "general_appointed", "monument_raised"]};
  // ------------------------------------------------------------------ the reign: progress you can see
  const ordinal = (n) => `${n}${["th", "st", "nd", "rd"][(n % 100 - 20) % 10] || ["th", "st", "nd", "rd"][n % 100] || "th"}`;
  const rankIn = (row) => 1 + Object.entries(row.courts).filter(([n, v]) => n !== G.human && v[2] > row.me.standing).length;
  // A small line chart: thin lines, your own thicker, the latest value written at its end;
  // a hover band per year tells every line's value.
  function lineChart(years, series, {height = 120, invert = false, label = ""} = {}) {
    const W = 320, H = height, L = 6, R = 40, T = 10, B = 18;
    const all = series.flatMap((s) => s.values.filter((v) => v !== null && v !== undefined));
    let lo = Math.min(...all), hi = Math.max(...all);
    if (lo === hi) { lo -= 1; hi += 1; }
    const x = (k) => L + (W - L - R) * (years.length > 1 ? k / (years.length - 1) : 0);
    const y = (v) => { const f = (v - lo) / (hi - lo); return T + (H - T - B) * (invert ? f : 1 - f); };
    const lines = series.map((s) => {
      const pts = s.values.map((v, k) => (v === null || v === undefined ? null : `${x(k).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean).join(" ");
      const lastK = s.values.length - 1, last = s.values[lastK];
      return `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="${s.mine ? 2.6 : 1.4}" stroke-linejoin="round" stroke-linecap="round" opacity="${s.mine ? 1 : 0.8}"/>
        ${last !== null && last !== undefined ? `<circle cx="${x(lastK)}" cy="${y(last)}" r="${s.mine ? 3.2 : 2.2}" fill="${s.color}" stroke="var(--leather)" stroke-width="1.5"/>
        ${s.mine ? `<text x="${x(lastK) + 6}" y="${y(last) + 4}" class="cval">${label}${last}</text>` : ""}` : ""}`; }).join("");
    const bands = years.map((yr, k) => { const w = (W - L - R) / Math.max(1, years.length - 1);
      const vals = series.map((s) => `${s.name}: ${s.values[k] ?? "—"}`).join("\n");
      return `<rect x="${x(k) - w / 2}" y="${T}" width="${w}" height="${H - T - B}" class="band"><title>${yr}\n${vals}</title></rect>`; }).join("");
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">
      <line x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}" class="axis"/>
      <text x="${L}" y="${H - 4}" class="tick">${years[0]}</text><text x="${W - R}" y="${H - 4}" class="tick" text-anchor="end">${years[years.length - 1]}</text>
      ${lines}${bands}</svg>`;
  }
  // The reigns of your realm so far: who sat the throne, from when to when, and what became of it.
  function reignsOf(H) {
    const out = [];
    H.forEach((r, k) => { const cur = out[out.length - 1], rank = rankIn(r);
      if (!cur || cur.ruler !== r.me.ruler) out.push({ruler: r.me.ruler, from: r.year, to: r.year, a: r.me, b: r.me, ra: rank, rb: rank});
      else { cur.to = r.year; cur.b = r.me; cur.rb = rank; } });
    return out;
  }
  function reignLine(g) {
    const years = g.to - g.from, dev = g.b.development - g.a.development, land = g.b.provinces - g.a.provinces;
    const verdict = g.rb < g.ra ? "Europe looked up to the crown more than before" : g.rb > g.ra ? "the realm fell behind its rivals" : "the realm held its place";
    return `${esc(g.ruler || "A regency")} reigned ${years || "less than a"} year${years === 1 ? "" : "s"}: ${land > 0 ? `${land} province${land > 1 ? "s" : ""} won` : land < 0 ? `${-land} province${land < -1 ? "s" : ""} lost` : "no land won or lost"}, development ${dev >= 0 ? "+" : ""}${dev}, and ${verdict} (${ordinal(g.ra)} to ${ordinal(g.rb)}).`;
  }
  // Which provinces a year's events gave you, or took from you.
  function yearLand(evs) {
    const won = [], lost = [];
    for (const e of evs) {
      if (!e.province) continue;
      if (e.kind === "province_captured") (e.nations[0] === G.human ? won : e.nations[1] === G.human ? lost : []).push(e.province);
      if (e.kind === "province_ceded") (e.nations[1] === G.human ? won : e.nations[0] === G.human ? lost : []).push(e.province);
    }
    return [won, lost];
  }
  // The chronicle of a whole reign, as a chronicler would write it at the end.
  function chronicleOfReign() {
    const H = G.history || [], story = G.story || {milestones: [], bonds: {}};
    if (H.length < 2) return "";
    const a = H[0].me, b = H[H.length - 1].me, ranks = H.map(rankIn), name = nameOf(G.human);
    const miles = story.milestones || [], mine = (k) => miles.filter((m) => m.kind === k);
    const wars = mine("war_declared").length, peaces = mine("peace_signed").length, ambitions = mine("mission_completed").filter((m) => m.nations[0] === G.human).length;
    const conquests = miles.filter((m) => (m.kind === "province_captured" && m.nations[0] === G.human) || (m.kind === "province_ceded" && m.nations[1] === G.human));
    const bonds = Object.entries(story.bonds || {});
    const won = bonds.reduce((s, [, x]) => s + x.battles_won, 0), lost = bonds.reduce((s, [, x]) => s + x.battles_lost, 0);
    const enemy = bonds.sort((x, y) => (y[1].battles_won + y[1].battles_lost + 3 * y[1].wars) - (x[1].battles_won + x[1].battles_lost + 3 * x[1].wars))[0];
    const best = Math.min(...ranks), bestYear = H[ranks.indexOf(best)].year;
    const reigns = reignsOf(H);
    const WORD = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"];
    const say = (n, one, many = `${one}s`) => `${WORD[n] ?? n} ${n === 1 ? one : many}`;
    const cap1 = (s) => s.charAt(0).toUpperCase() + s.slice(1);
    const parts = [
      `${name} entered the age in ${H[0].year} with ${a.provinces} provinces and ${a.development} development, ${ordinal(ranks[0])} among the courts of Europe.`,
      `${reigns.length > 1 ? `${cap1(say(reigns.length, "ruler"))} sat its throne: ${reigns.map((g) => `${g.ruler} (${g.from}–${g.to})`).join(", ")}.` : `${reigns[0].ruler} ruled it all those years.`}`,
      wars || won || lost ? `It fought ${say(wars, "war")}${peaces ? ` and signed ${say(peaces, "peace")}` : ""}; its armies won ${say(won, "battle")} and lost ${WORD[lost] ?? lost}.`
        : "It kept its swords sheathed: no war darkened its years.",
      conquests.length ? `Its banners rose over ${conquests.slice(0, 6).map((m) => P[pIndex[m.province]]?.name).filter(Boolean).join(", ")}${conquests.length > 6 ? " and more" : ""}.` : "It won no land by the sword or the pen.",
      enemy && (enemy[1].wars || enemy[1].battles_won + enemy[1].battles_lost) ? `Its great rival was ${nameOf(enemy[0])}.` : "",
      ambitions ? `It fulfilled ${ambitions} of the crown's ambitions.` : "",
      `At its height, in ${bestYear}, it stood ${ordinal(best)} in Europe. In ${H[H.length - 1].year} it held ${b.provinces} provinces and ${b.development} development, ${ordinal(ranks[ranks.length - 1])} of all.`,
    ].filter(Boolean);
    return parts.join(" ");
  }
  function reignTab() {
    const H = G.history || [], story = G.story || {milestones: [], bonds: {}};
    if (H.length < 2) return `<div class="pad"><p class="muted">Your reign is young: end a year or two, and its story starts here.</p>${deedsShelf()}</div>`;
    const years = H.map((r) => r.year), first = H[0].me, last = H[H.length - 1].me, color = N[me].color;
    const ranks = H.map(rankIn), best = Math.min(...ranks), bestYear = years[ranks.indexOf(best)];
    // the three courts ahead of you, or closest behind, at the end
    const rivals = Object.entries(H[H.length - 1].courts).filter(([n]) => n !== G.human).sort((a, b) => b[1][2] - a[1][2]).slice(0, 3).map(([n]) => n);
    const standing = lineChart(years, [{name: nameOf(G.human), color, mine: true, values: H.map((r) => r.me.standing)},
      ...rivals.map((n) => ({name: nameOf(n), color: N[nIndex[n]].color, values: H.map((r) => r.courts[n]?.[2] ?? null)}))]);
    const tile = (title, key, unit = "") => { const vals = H.map((r) => r.me[key]), d = vals[vals.length - 1] - vals[0];
      return `<div class="rtile"><div class="rhead"><span>${title}</span><b>${vals[vals.length - 1]}${unit}</b><small class="${d > 0 ? "pos" : d < 0 ? "neg" : ""}">${d > 0 ? "▲" : d < 0 ? "▼" : ""}${d ? Math.abs(d) : "="} since ${years[0]}</small></div>
        ${lineChart(years, [{name: title, color, mine: true, values: vals}], {height: 70})}</div>`; };
    // reigns: who sat on the throne, and what the realm became under them
    const reigns = reignsOf(H);
    const sitter = (g) => { const [title, ...rest] = (g.ruler || "").split(" "); return {title, name: rest.join(" "), age: 40}; };
    const reignRows = reigns.map((g, k) => `<li><div class="gport">${portrait(k === reigns.length - 1 && V.me.ruler ? V.me.ruler : sitter(g), color, 52)}</div>
      <div><b>${esc(g.ruler || "A regency")}</b> <small>${g.from}–${g.to}${k === reigns.length - 1 ? ", reigning" : ""}</small>
      <span>development ${g.a.development} → ${g.b.development}, provinces ${g.a.provinces} → ${g.b.provinces}, ${ordinal(g.ra)} → ${ordinal(g.rb)} in Europe</span></div></li>`).join("");
    // nemesis and friend, from what passed between the courts
    const bonds = Object.entries(story.bonds || {}).filter(([n]) => N[nIndex[n]]);
    const enmity = (b) => b.battles_won + b.battles_lost + 3 * b.wars + 2 * (b.taken + b.lost) + 4 * b.betrayals;
    const nemesis = bonds.filter(([, b]) => enmity(b) > 0).sort((a, b) => enmity(b[1]) - enmity(a[1]))[0];
    const friend = bonds.filter(([, b]) => b.treaties > 0 && !b.wars).sort((a, b) => b[1].treaties - a[1].treaties)[0];
    const who = (n) => `<span class="who">${PaxMap.flag(n, N[nIndex[n]].color, 22, "flag inline")} <b>${esc(nameOf(n))}</b></span>`;
    const MILE = {province_captured: "⚑", province_ceded: "📜", province_liberated: "🛡", province_occupied: "🏴", mission_completed: "🏆", succession: "👑",
      war_declared: "⚔", peace_signed: "🕊", treaty_signed: "🤝", treaty_broken: "💔", monument_raised: "🏛", nation_eliminated: "☠", coalition_joined: "🛡"};
    const miles = (story.milestones || []).slice().reverse().slice(0, 40).map((m) => `<li><span class="my">${m.year}</span><span class="ic">${MILE[m.kind] || "•"}</span><span>${esc(m.summary)}</span></li>`).join("");
    return `<div class="pad reign">
      <div class="rtop"><div><span class="sub">Standing in Europe</span><b class="big">${ordinal(ranks[ranks.length - 1])}</b><small>best: ${ordinal(best)}, in ${bestYear}</small></div>
        <div><span class="sub">Years of your reign</span><b class="big">${years[years.length - 1] - years[0]}</b><small>of ${V.max_turns}</small></div>
        <div><span class="sub">Standing</span><b class="big">${last.standing}</b><small class="${last.standing >= first.standing ? "pos" : "neg"}">${sign(last.standing - first.standing)} since ${years[0]}</small></div></div>
      <div class="row"><button class="btn" id="sharereign" type="button">🖼 A picture of your reign, to keep or share</button></div>
      <h4>${I("trending-up")} Standing, against the leading courts</h4>${standing}
      <div class="legend2">${[[G.human, color], ...rivals.map((n) => [n, N[nIndex[n]].color])].map(([n, c]) => `<span><i style="background:${c}"></i>${esc(nameOf(n))}</span>`).join("")}</div>
      <div class="rtiles">${tile("Development", "development")}${tile("Provinces", "provinces")}${tile("Ducats a year", "income")}${tile("Regiments", "regiments")}${tile("Prestige", "prestige")}</div>
      ${nemesis || friend ? `<h4>${I("swords")} Between the courts</h4><div class="bonds">
        ${nemesis ? `<div><span class="sub">Your nemesis</span>${who(nemesis[0])}<small>${nemesis[1].wars} war${nemesis[1].wars === 1 ? "" : "s"}, battles ${nemesis[1].battles_won}–${nemesis[1].battles_lost}, land ${nemesis[1].taken} taken, ${nemesis[1].lost} lost${nemesis[1].betrayals ? `, ${nemesis[1].betrayals} betrayal${nemesis[1].betrayals > 1 ? "s" : ""}` : ""}</small></div>` : ""}
        ${friend ? `<div><span class="sub">Your firmest friend</span>${who(friend[0])}<small>${friend[1].treaties} treat${friend[1].treaties === 1 ? "y" : "ies"} signed, never at war</small></div>` : ""}</div>` : ""}
      <h4>${I("crown")} The dynasty</h4><ul class="reigns">${reignRows}</ul>
      <h4>${I("book-open")} Milestones</h4>${miles ? `<ol class="miles">${miles}</ol>` : `<p class="muted">Nothing worth the chronicler's ink yet.</p>`}
      ${deedsShelf()}</div>`;
  }
  function chronicleTab() {
    if (!G.chronicle.length) return `<p class="muted pad">History begins when you end the first year.</p>`;
    // each line in the reader's language first, then the crowns' names in their colours
    const L = window.PaxI18n || {t: (s) => s, name: (s) => s}, shown = new Map(N.map((n) => [L.name(n.name), n]));
    const names = new RegExp([...shown.keys()].sort((a, b) => b.length - a.length).join("|"), "g");
    const paint = (text) => esc(L.t(text)).replace(names, (m) => `<span class="nn" style="color:${mix(shown.get(m).color, "#ffffff", .35)}">${m}</span>`);
    const keep = (e) => !["moved", "proposal_made", "market_trade", "recruited"].includes(e.kind) && (!chronCourt || e.nations.includes(chronCourt))
      && (chronKind === "all" || (chronKind === "mine" ? e.nations.includes(G.human) : (CHRON_KINDS[chronKind] || []).includes(e.kind)));
    const years = G.chronicle.map((y) => [y, y.events.filter(keep)]).filter(([, es]) => es.length);
    return `<div class="pad"><div class="filters"><select class="field" id="chroncourt" aria-label="Court"><option value="">All Europe</option>${N.map((n) => `<option value="${n.id}" ${chronCourt === n.id ? "selected" : ""}>${esc(n.name)}</option>`).join("")}</select>
      ${[["all", "All"], ["mine", "My realm"], ["war", "War"], ["diplomacy", "Diplomacy"], ["realm", "Works"]].map(([id, label]) => `<button class="btn ${chronKind === id ? "on" : ""}" data-chkind="${id}">${label}</button>`).join("")}</div></div>
      <ol class="chron" style="max-height:none">${years.map(([y, es]) => { const [won, lost] = yearLand(y.events);
        return `<li class="year">${y.year} <em>${esc(headline(y.events, won, lost))}</em></li>`; }).map((head, k) => head + years[k][1]
      .map((e) => `<li class="${BAD.has(e.kind) ? "bad" : ""}"><span class="ic">${ICON[e.kind] || "•"}</span><span>${paint(told(e))}</span></li>`).join("")).join("") || `<li class="muted">Nothing of the kind.</li>`}</ol>`;
  }
  // ------------------------------------------------------------------ the rail of offices and its window
  const OFFICES = [["realm", "landmark", "Economy"], ["crown", "crown", "The Crown"], ["reign", "trending-up", "Your reign"], ["missions", "target", "Missions"],
    ["army", "swords", "Army"], ["world", "globe", "The New World"], ["tech", "flask-conical", "Learning"], ["diplomacy", "handshake", "Diplomacy"],
    ["letters", "mail", "Correspondence"], ["ledger", "chart-column", "Ledger of Europe"], ["chronicle", "book-open", "Chronicle"]];
  let panelOpen = false, pinned = false, peekTimer = 0, leaveTimer = 0;
  $("rail").innerHTML = OFFICES.map(([id, icon, label]) => `<button role="tab" data-tab="${id}" aria-label="${label}"${tip(`<h5>${label}</h5>`)}>${I(icon)}</button>`).join("");
  function openOffice(id, pin = true) {
    tab = id; panelOpen = true; pinned = pinned || pin;
    render();
  }
  function closeOffice() { panelOpen = false; pinned = false; render(); }
  const panelEl = $("panel");
  $("rail").querySelectorAll("button").forEach((b) => {
    b.onclick = () => { if (panelOpen && pinned && tab === b.dataset.tab) closeOffice(); else { pinned = true; openOffice(b.dataset.tab); } };
    b.onmouseenter = () => { clearTimeout(leaveTimer); clearTimeout(peekTimer);
      peekTimer = setTimeout(() => { if (!pinned || !panelOpen) { pinned = false; openOffice(b.dataset.tab, false); } else if (tab !== b.dataset.tab) openOffice(b.dataset.tab); }, 260); };
    b.onmouseleave = () => clearTimeout(peekTimer);
  });
  const maybeClose = () => { clearTimeout(leaveTimer); leaveTimer = setTimeout(() => { if (panelOpen && !pinned && !panelEl.matches(":hover") && !$("rail").matches(":hover")) closeOffice(); }, 450); };
  $("rail").onmouseleave = maybeClose; panelEl.onmouseleave = maybeClose; panelEl.onmouseenter = () => clearTimeout(leaveTimer);
  panelEl.onclick = () => { if (panelOpen && !pinned) { pinned = true; panelEl.classList.add("pinned"); } };
  $("panelclose").innerHTML = I("x"); $("panelclose").onclick = (e) => { e.stopPropagation(); closeOffice(); };
  $("panelpin").innerHTML = I("anchor"); $("panelpin").onclick = (e) => { e.stopPropagation(); pinned = !pinned; panelEl.classList.toggle("pinned", pinned); };
  $("realmbtn").onclick = () => { pinned = true; openOffice("crown"); };
  function office() {
    panelEl.classList.toggle("open", panelOpen);
    panelEl.parentElement.classList.toggle("paneled", panelOpen);
    panelEl.classList.toggle("pinned", pinned);
    const meta = OFFICES.find(([id]) => id === tab);
    $("paneltitle").textContent = meta[2]; $("panelicon").innerHTML = I(meta[1]);
    document.querySelectorAll(".offices button").forEach((b) => {
      b.setAttribute("aria-selected", panelOpen && b.dataset.tab === tab);
      const count = b.dataset.tab === "letters" ? V.proposals_to_answer.filter((p) => !orders.some((o) => o.type === "respond" && o.proposal_id === p.id)).length
        + V.me.pending_events.filter((e) => !chosen(e.id)).length : 0;
      const old = b.querySelector(".count"); if (old) old.remove();
      if (count) b.insertAdjacentHTML("beforeend", `<span class="count">${count}</span>`);
    });
    const panel = $("office");
    if (!panelOpen) { panel.innerHTML = ""; return; }
    const keep = panel.scrollTop, same = panel.dataset.tab === tab;
    panel.innerHTML = {realm: realmTab, crown: crownTab, reign: reignTab, missions: missionsTab, army: armyTab, world: worldTab, tech: techTab, diplomacy: diplomacyTab, letters: lettersTab, ledger: ledgerTab, chronicle: chronicleTab}[tab]();
    panel.dataset.tab = tab; if (same) panel.scrollTop = keep;
    const focusOn = (i) => { picked = i; send = Infinity; lead = true; if (!pinned) panelOpen = false; map.centerOn(i, 2.2, innerWidth > 960 ? 300 : 0); render(); };
    panel.querySelectorAll("tr.click").forEach((tr) => tr.onclick = () => focusOn(+tr.dataset.p));
    panel.querySelectorAll("[data-goto]").forEach((b) => b.onclick = () => focusOn(+b.dataset.goto));
    panel.querySelectorAll("[data-research]").forEach((b) => b.onclick = () => { orders = orders.filter((o) => o.type !== "research"); queue({type: "research", branch: b.dataset.research, choice: +(b.dataset.choice || 0)}); });
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
    panel.querySelectorAll("[data-lsort]").forEach((th) => th.onclick = () => { const k = th.dataset.lsort; ledgerDesc = ledgerSort === k ? !ledgerDesc : true; ledgerSort = k; render(); });
    panel.querySelectorAll("[data-lfilter]").forEach((b) => b.onclick = () => { ledgerFilter = b.dataset.lfilter; render(); });
    panel.querySelectorAll("tr[data-court]").forEach((tr) => tr.onclick = () => { if (tr.dataset.court === G.human) return; focus = nIndex[tr.dataset.court]; deskTab = "letters"; openOffice("diplomacy"); });
    panel.querySelectorAll("[data-ckind]").forEach((b) => b.onclick = () => { corrKind = b.dataset.ckind; render(); });
    const cc = panel.querySelector("#corrcourt"); if (cc) cc.onchange = () => { corrCourt = cc.value; render(); };
    panel.querySelectorAll("[data-chkind]").forEach((b) => b.onclick = () => { chronKind = b.dataset.chkind; render(); });
    const chc = panel.querySelector("#chroncourt"); if (chc) chc.onchange = () => { chronCourt = chc.value; render(); };
    panel.querySelectorAll("[data-recruitkind]").forEach((b) => b.onclick = () => { const k = b.dataset.recruitkind, d = +b.dataset.d;
      recruitN[k] = Math.max(0, (recruitN[k] || 0) + d); render(); });
    const ra = panel.querySelector("#recruitat"); if (ra) ra.onchange = () => { recruitAt = ra.value; render(); };
    wireYards(panel);
    panel.querySelectorAll("tr[data-sea]").forEach((tr) => tr.onclick = () => { pickedSea = +tr.dataset.sea; picked = -1; if (!pinned) panelOpen = false; render(); });
    panel.querySelectorAll("[data-expedition]").forEach((b) => b.onclick = () => queue({type: "send_expedition", region: b.dataset.expedition}));
    panel.querySelectorAll("[data-seize]").forEach((b) => b.onclick = () => { const [r, e] = b.dataset.seize.split(":"); queue({type: "seize_colony", region: r, enemy: e}); });
    const rgo = panel.querySelector("#recruitgo"); if (rgo) rgo.onclick = () => { U.forEach((u) => { const n = recruitN[u.id] || 0;
      if (n > 0) queue({type: "recruit", province: recruitAt, regiments: n, unit: u.id}); }); recruitN = {}; render(); };
    const mgo = panel.querySelector("#mercgo"); if (mgo) mgo.onclick = () => { const n = recruitN.mercs || 0;
      if (n > 0) queue({type: "hire_mercenaries", province: recruitAt, regiments: n}); recruitN.mercs = 0; render(); };
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
      if (kind === "declare_war") return confirmWar(nid);
      queue({type: kind, target: nid});
    });
    const costLine = panel.querySelector("#peace-cost");
    if (costLine) {
      const update = () => {
        const terms = readPeace(), score = warOf(nid)?.war_score ?? 0, cost = warCost(nid, terms);
        const send = panel.querySelector('[data-dip="propose_peace"], [data-dip="counter_peace"]');
        const room = Math.max(0, score), over = cost > room;
        if (send && !send.dataset.locked) send.disabled = over;
        const meter = panel.querySelector("#peace-meter");
        if (meter) { meter.style.width = `${room ? Math.min(100, Math.round(100 * cost / room)) : cost ? 100 : 0}%`; meter.className = over ? "over" : ""; }
        costLine.className = "sub" + (over ? " warn" : "");
        costLine.textContent = !cost ? "You demand nothing: a white peace, or what you offer."
          : over ? `Your demands cost ${cost}, more than your ${room}: ask for less, or win more first.` : `Your demands cost ${cost} of your ${room}.`;
      };
      panel.querySelectorAll("details.peace input, details.peace textarea").forEach((x) => (x.oninput = update));
      update();
    }
    panel.querySelectorAll("[data-desk]").forEach((b) => b.onclick = () => { deskTab = b.dataset.desk; render(); });
    const sr = panel.querySelector("#sharereign"); if (sr) sr.onclick = () => shareReign(sr);
    panel.querySelectorAll("[data-stance]").forEach((b) => b.onclick = () => {
      orders = orders.filter((o) => !(o.type === "set_stance" && o.target === nid));
      queue({type: "set_stance", target: nid, stance: b.dataset.stance});
    });
    panel.querySelectorAll("[data-cancel]").forEach((b) => b.onclick = () => queue({type: "cancel_treaty", target: nid, kind: b.dataset.cancel}));
    panel.querySelectorAll("[data-call]").forEach((b) => b.onclick = () => queue({type: "call_to_arms", target: b.dataset.call, enemy: nid}));
    panel.querySelectorAll("[data-counter]").forEach((b) => b.onclick = () => {
      countering = V.proposals_to_answer.find((p) => p.id === +b.dataset.counter);
      focus = nIndex[countering.sender]; deskTab = countering.kind === "peace" ? "war" : "treaties"; openOffice("diplomacy");
    });
    panel.querySelectorAll("[data-answer]").forEach((b) => b.onclick = () => {
      const id = +b.dataset.answer, note = (panel.querySelector(`[data-note="${id}"]`)?.value || "").trim();
      orders = orders.filter((o) => !(o.type === "respond" && o.proposal_id === id));
      queue({type: "respond", proposal_id: id, accept: b.dataset.accept === "1", ...(note ? {note} : {})});
    });
  }


  // ------------------------------------------------------------------ this year's orders, always in sight
  function describe(o) {
    const pn = (id) => esc(P[pIndex[id]].name), nn = (id) => esc(nameOf(id));
    const gname = (id) => esc(V.me.generals.find((g) => g.id === id)?.name || "a general");
    switch (o.type) {
      case "recruit": return `${UICON[o.unit || "infantry"]} Recruit ${o.regiments} ${o.unit || "infantry"} in ${pn(o.province)}`;
      case "upgrade_monument": return `🏛 Raise ${esc(M[o.province]?.name || "the monument")}`;
      case "disband": return `Disband ${o.regiments}${o.unit ? ` ${o.unit}` : ""} in ${pn(o.province)}`;
      case "develop": return `Develop ${pn(o.province)}`;
      case "send_expedition": return `⛵ Send an expedition to ${esc(regionName(o.region))}`;
      case "seize_colony": return `⚔ Take a colony in ${esc(regionName(o.region))} from ${nn(o.enemy)}`;
      case "build_ships": return `${SICON[o.ship]} Launch ${o.count} ${o.ship}${o.count > 1 ? "s" : ""} from ${pn(o.province)}`;
      case "scrap_ships": return `⚓ Lay up ${o.count} ${o.ship}${o.count > 1 ? "s" : ""} in the ${esc(seaName(o.sea))}`;
      case "sail_fleet": { const n = Object.values(o.ships).reduce((a, b) => a + b, 0); return `⛵ Sail ${n} ships from the ${esc(seaName(o.origin))} to the ${esc(seaName(o.target))}`; }
      case "seek_battle": return `⚔ Seek out the fleet of ${nn(o.enemy)} in the ${esc(seaName(o.sea))}`;
      case "set_posture": { const k = postureOf(o.posture); return `${k[1]} ${pn(o.province)}: ${k[2].toLowerCase()}`; }
      case "set_focus": { const f = FOCI.find(([k]) => k === o.focus); return `${f ? f[1] : "🎯"} Turn ${pn(o.province)} to ${f ? f[2].toLowerCase() : o.focus}`; }
      case "improve": return `${PaxMap.goodOf(S, P[pIndex[o.province]].good).icon} Raise the ${PaxMap.goodOf(S, P[pIndex[o.province]].good).workings.toLowerCase()} of ${pn(o.province)}`;
      case "build": return `Build ${B[bIndex[o.building]].name.toLowerCase()} in ${pn(o.province)}`;
      case "upgrade_building": return `⬆ Raise the ${B[bIndex[o.building]].name.toLowerCase()} of ${pn(o.province)} to level ${levelOf(pIndex[o.province], o.building) + 1}`;
      case "boost_stability": return "Raise stability";
      case "convert": return `✝ Send preachers to ${pn(o.province)}`;
      case "set_taxes": return `⚖ Set taxes ${TAX_WORDS[o.level + 2].toLowerCase()}`;
      case "patronize": return `🎨 Patronise the arts (+${R.patronagePrestige} prestige)`;
      case "hire_mercenaries": return `💰 Hire ${o.regiments} mercenary regiments in ${pn(o.province)}`;
      case "research": { const b = T.find((x) => x.id === o.branch), step = b.levels[V.me.technology[o.branch]], doc = step && step.options[o.choice || 0];
        return `${BRANCH_IC[o.branch] || ""} Research ${step?.name || o.branch}${doc ? `: ${doc.name}` : ""}`; }
      case "hire_advisor": { const c = V.me.advisor_candidates.find((x) => x.id === o.candidate); return c ? `Hire ${esc(c.name)} as ${c.role}` : "Hire an advisor"; }
      case "dismiss_advisor": return `Dismiss the ${o.role}`;
      case "hire_general": return `Appoint a general in ${pn(o.province)}`;
      case "assign_general": return `Send ${gname(o.general)} to ${pn(o.province)}`;
      case "move": return `➜ March ${o.regiments} from ${pn(o.origin)} to ${pn(o.target)}${o.general ? ` under ${gname(o.general)}` : ""}`;
      case "attack": { const s = prov(pIndex[o.target]).siege_by, verb = s === G.human ? "Reinforce the siege of" : s ? "Break the siege of" : "Attack";
        const together = orders.filter((x) => x.type === "attack" && x.target === o.target);
        const joint = together.length > 1 ? ` · one battle with ${together.reduce((a, x) => a + x.regiments, 0)} regiments from ${together.length} provinces` : "";
        const how = s === G.human ? null : tacticOf(o.tactic || "assault");
        return `⚔ ${verb} ${pn(o.target)} with ${o.regiments} from ${pn(o.origin)}${o.general ? ` under ${gname(o.general)}` : ""}${how ? ` · ${how[1]} ${how[2].toLowerCase()}` : ""}${joint}`; }
      case "lift_siege": return `🏳 Lift the siege of ${pn(o.province)}`;
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
    const failing = shortfalls().size;
    $("ordersbtn").innerHTML = I("scroll-text") + (orders.length ? `<span class="count ${failing ? "" : "ok"}">${failing ? `${failing}✗` : orders.length}</span>` : "");
    $("ordersbtn").setAttribute("data-tip", failing ? `<h5>This year's orders</h5><div class="neg">${failing} of them cannot be paid and will fail.</div>` : `<h5>This year's orders</h5><div class="dim">${orders.length} given. Hover to see them.</div>`);
    $("orders").innerHTML = `<h4>This year's orders <small>${orders.length} of ${MAX_ORDERS}</small></h4>` + (orders.length
      ? (() => { const short = shortfalls(); return orders.map((o, k) => `<div class="order ${short.has(k) ? "short" : ""}"><span>${describe(o)}${short.has(k) ? `<small>✗ not enough ${short.get(k).join(", ")}: it will fail</small>` : ""}</span><button data-drop="${k}" aria-label="Withdraw this order" title="Withdraw">✕</button></div>`).join(""); })()
      : `<p class="muted pad">No orders yet. Select a province on the map, or open an office above.</p>`);
    $("orders").querySelectorAll("[data-drop]").forEach((b) => b.onclick = () => { orders.splice(+b.dataset.drop, 1); J.play("unorder"); render(); });
  }

  // ------------------------------------------------------------------ the year's report
  // A battle as two armies facing each other: who brought what, who lost what, and what came of it.
  function battleCard(e) {
    const d = e.data, mineAttacking = d.attacker === G.human, won = mineAttacking === d.attacker_won;
    const side = (nid, name, regiments, army, lost, power, winner) => `<div class="bfight ${winner ? "winner" : ""}">
      <div class="bwho">${nid ? PaxMap.flag(nid, N[nIndex[nid]].color, 26) : "🛡"}<b>${esc(name)}</b>${winner ? `<span class="crownmark">won</span>` : ""}</div>
      <div class="bnums"><span><b>${regiments}</b> regiments</span><span class="neg"><b>−${lost}</b> lost</span><span><b>${power}</b> power</span></div>
      ${army ? `<small>${esc(army)}</small>` : ""}</div>`;
    return `<div class="battlecard ${won ? "won" : "lost"}">
      <div class="bhead"><span>⚔ Battle of ${esc(P[pIndex[e.province]].name)}</span><b>${won ? "Victory" : "Defeat"}</b></div>
      <div class="bsides">${side(d.attacker, d.attacker_name, d.attacker_regiments, d.attacker_army, d.attacker_losses, d.attacker_power, d.attacker_won)}
        <span class="vs">vs</span>${side(d.defender, d.defender_name, d.defender_regiments, d.defender_army, d.defender_losses, d.defender_power, !d.attacker_won)}</div>
      ${d.tactic ? `<p class="btactic">${tacticOf(d.tactic)[1]} ${tacticOf(d.tactic)[2]} against ${postureOf(d.posture)[1]} ${postureOf(d.posture)[2].toLowerCase()}: <b>${sign(Math.round((d.edge - 1) * 100))}%</b> to the attack${d.attacker_veterancy || d.defender_veterancy ? `. Veterancy ${Math.round((d.attacker_veterancy || 0) * 100)}% against ${Math.round((d.defender_veterancy || 0) * 100)}%` : ""}</p>` : ""}
      <p class="bthen">${esc(cap(String(d.then || "")))}. <small>Power is regiments × their kind on this ground × technology, generals, tactics, veterancy, morale and walls × the dice.</small></p></div>`;
  }
  // A sea battle: two fleets, what they were worth, and what went down.
  function navalCard(e) {
    const d = e.data, mine = d.attacker === G.human, won = mine === d.attacker_won, zone = seaOf(d.sea), w = [WATER[zone ? zone.water : "atlantic"][0], zone ? `the ${zone.name}` : "the sea"];
    const side = (nid, fleet, power, lost, winner) => `<div class="bfight ${winner ? "winner" : ""}">
      <div class="bwho">${PaxMap.flag(nid, N[nIndex[nid]].color, 26)}<b>${esc(nameOf(nid))}</b>${winner ? `<span class="crownmark">won</span>` : ""}</div>
      <div class="bnums"><span class="neg"><b>−${lost}</b> ships</span><span><b>${power}</b> power</span></div><small>${esc(fleet)}</small></div>`;
    return `<div class="battlecard ${won ? "won" : "lost"}">
      <div class="bhead"><span>${w[0]} ${d.great ? "A great sea battle" : "Sea battle"} in ${esc(w[1])}</span><b>${won ? "Victory" : "Defeat"}</b></div>
      <div class="bsides">${side(d.attacker, d.attacker_fleet, d.attacker_power, d.attacker_won ? d.winner_lost : d.loser_lost, d.attacker_won)}
        <span class="vs">vs</span>${side(d.defender, d.defender_fleet, d.defender_power, d.attacker_won ? d.loser_lost : d.winner_lost, !d.attacker_won)}</div>
      <p class="bthen">${d.attacker_won === mine ? "The sea is yours: its straits and its ports are in your hands while your fleet holds it." : "Their fleet holds the sea: your armies cannot cross where it commands, and your ports may be blockaded."}</p></div>`;
  }
  function siegeLine(e) {
    const d = e.data, where = esc(P[pIndex[e.province]].name);
    if (!("die" in d)) return `<div class="siegeline">🏰 ${esc(e.summary)}</div>`; // begun, reinforced or lifted
    const mods = String(d.modifiers || "").split("; ").filter(Boolean).map((m) => esc(m.replace(/ ([+-])(\d+)$/, " $1$2"))).join(", ");
    return `<div class="siegeline"><b>🏰 Siege of ${where}</b> by ${esc(nameOf(e.nations[0]))}: <b>${esc(cap(String(d.result)))}</b> (+${d.gain}%)${d.lost ? `, <span class="neg">${d.lost} regiments dead of disease</span>` : ""}
      <small>die ${d.die}${mods ? `, ${mods}` : ""}: score ${d.score}</small>
      <div class="sbar"><i style="width:${d.progress}%"></i><span>${d.progress}%${d.progress >= 100 ? ": the walls fall" : ""}</span></div></div>`;
  }
  // The year's headline: the one thing a chronicler would write down first.
  function headline(evs, won, lost) {
    const mine = evs.filter((e) => e.nations.includes(G.human));
    const pname = (pid) => P[pIndex[pid]]?.name || pid;
    const age = evs.find((e) => e.kind === "crisis" && e.data.begins);
    if (age) return `The year ${age.summary.split(",")[0]} fell on Europe`;
    const mission = mine.find((e) => e.kind === "mission_completed" && e.nations[0] === G.human);
    if (mission) return `The year ${nameOf(G.human)} ${mission.summary.split(": ").slice(1).join(": ") ? `fulfilled “${mission.summary.split(": ").slice(1).join(": ")}”` : "fulfilled an ambition"}`;
    if (won.length) return `The year ${won.map(pname).join(" and ")} ${won.length > 1 ? "were" : "was"} won`;
    if (lost.length) return `The year ${lost.map(pname).join(" and ")} ${lost.length > 1 ? "were" : "was"} lost`;
    const fell = mine.filter((e) => e.kind === "province_occupied" && e.nations[1] === G.human);
    if (fell.length) return `The year ${fell.map((e) => pname(e.province)).join(" and ")} fell to ${nameOf(fell[0].nations[0])}`;
    const rose = mine.filter((e) => e.kind === "province_occupied" && e.nations[0] === G.human);
    if (rose.length) return `The year your banners rose over ${rose.map((e) => pname(e.province)).join(" and ")}`;
    const war = mine.find((e) => e.kind === "war_declared");
    if (war) return `The year war came between ${nameOf(war.nations[0])} and ${nameOf(war.nations[1])}`;
    const peace = mine.find((e) => e.kind === "peace_signed");
    if (peace) return `The year of the peace with ${nameOf(peace.nations.find((n) => n !== G.human) || G.human)}`;
    const battle = mine.find((e) => e.kind === "battle");
    if (battle) return `The year of the battle of ${pname(battle.province)}`;
    const reign = mine.find((e) => e.kind === "succession");
    if (reign) return "The year of a new reign";
    const wed = mine.find((e) => e.kind === "treaty_signed" && e.summary.includes("marriage"));
    if (wed) return "The year of a royal wedding";
    // a quiet year at home: the most striking news from abroad
    const WEIGHT = {nation_eliminated: 6, war_declared: 5, peace_signed: 4, coalition_joined: 4, succession: 3, mission_completed: 3, province_ceded: 2, province_captured: 1};
    const far = evs.filter((e) => WEIGHT[e.kind]).sort((a, b) => WEIGHT[b.kind] - WEIGHT[a.kind])[0];
    if (far) return `Abroad, ${far.summary.replace(/\.$/, "")}`;
    return "A quiet year in the realm";
  }
  // The deed of the year: one picture for what mattered most, as a chronicle's woodcut would.
  function sceneOfYear(evs, won) {
    const art = window.PaxScenes, year = V.year - 1;
    if (!art) return "";
    const color = (nid) => (nid && N[nIndex[nid]] ? N[nIndex[nid]].color : "#9a8f78");
    const pname = (pid) => P[pIndex[pid]]?.name || pid;
    const fig = (svg, caption) => `<section class="deedofyear"><figure>${svg}<figcaption>${esc(caption)}</figcaption></figure></section>`;
    const age = evs.find((e) => e.kind === "crisis" && e.data.begins);
    if (age && V.crisis) {
      const pic = {plague: () => art.plague({color: color(G.human), seed: year}), ice_age: () => art.frost({seed: year}), price_revolution: () => art.galleon({seed: year})}[V.crisis.kind];
      if (pic) return fig(pic(), `${V.crisis.title}, ${V.crisis.first_year}`);
    }
    if (won.length) { // the town that changed hands, under its new banner
      const i = pIndex[won[0]], p = prov(i);
      const pic = S.views[p.id] ? `<img src="/views/${p.id}.jpg" alt="">` : PaxMap.vista(S, i, {owner: me, built: p.buildings.map((b) => bIndex[b]), dev: p.development, fort: p.fort, isCapital: false, monument: p.monument || 0, unrest: 0});
      return fig(pic, `${pname(won[0])} raises the banner of ${nameOf(G.human)}, ${year}`);
    }
    const battles = evs.filter((e) => e.kind === "battle" && e.nations.includes(G.human) && "attacker" in e.data)
      .sort((x, y) => (y.data.attacker_regiments + y.data.defender_regiments) - (x.data.attacker_regiments + x.data.defender_regiments));
    if (battles.length) { const b = battles[0], d = b.data;
      return fig(art.battle({a: color(d.attacker), b: color(d.defender), terrain: P[pIndex[b.province]].terrain, attackerWon: !!d.attacker_won, seed: b.summary}),
        `The battle of ${pname(b.province)}, ${year}: ${d.attacker_won ? nameOf(d.attacker) : d.defender ? nameOf(d.defender) : "the defenders"} carried the field`); }
    const siege = evs.find((e) => e.kind === "siege" && e.nations.includes(G.human) && e.data.started);
    if (siege) return fig(art.siege({by: color(siege.nations[0]), of: color(siege.nations[1]), terrain: P[pIndex[siege.province]].terrain, seed: siege.summary}),
      `The siege of ${pname(siege.province)} begins, ${year}`);
    const mission = evs.find((e) => e.kind === "mission_completed" && e.nations[0] === G.human);
    if (mission) return fig(art.laurels({color: color(G.human)}), `${mission.summary.split(": ").slice(1).join(": ") || "An ambition fulfilled"}, ${year}`);
    const peace = evs.find((e) => e.kind === "peace_signed" && e.nations.includes(G.human));
    const signed = peace || evs.find((e) => e.kind === "treaty_signed" && e.nations.includes(G.human));
    if (signed) { const other = signed.nations.find((n) => n !== G.human);
      return fig(art.treaty({a: color(G.human), b: color(other)}), `${peace ? "The peace" : "A treaty"} of ${nameOf(G.human)} and ${nameOf(other)}, ${year}`); }
    // else the news of the age the crown answered this year: a fair, a comet, a master at court
    const decided = evs.find((e) => e.kind === "event_decided" && e.nations[0] === G.human && art.ofEvent(e.data.event));
    if (decided) return fig(art.ofEvent(decided.data.event, {color: color(G.human), seed: `${decided.data.event}${year}`}),
      `${decided.summary.replace(/^[^,]+, /, "").replace(/^./, (c) => c.toUpperCase())}, ${year}`);
    return "";
  }
  // ------------------------------------------------------------------ first steps: a guided first game
  // Eight things every ruler does in the first years, each with a "Show me" that opens the
  // right window, crossed out by itself when done. Kept by the browser; it can be hidden, and
  // brought back from the guide.
  const STEPS_KEY = "pax-steps";
  const stepsKept = () => { try { return JSON.parse(localStorage.getItem(STEPS_KEY) || "{}"); } catch { return {}; } };
  const stepsSave = (s) => { try { localStorage.setItem(STEPS_KEY, JSON.stringify(s)); } catch {} };
  const queued = (type, test = () => true) => orders.some((o) => o.type === type && test(o));
  const happened = (kind, test = () => true) => (V.last_turn_events || []).some((e) => e.kind === kind && e.nations[0] === G.human && test(e));
  const capital = () => pIndex[V.me.capital];
  function showProvince(i, tabName) { // the deed opens on the left: keep the province in sight to its right
    if (i === undefined || i < 0) return; closeOffice(); picked = i; ownTab = tabName; deedMin = false; map.centerOn(i, 3, 220); render(); }
  function weakestMinor() { // the independent province next door with the fewest defenders
    const near = [];
    V.me.provinces.forEach((pid) => { const i = pIndex[pid]; [...P[i].land, ...P[i].sea].forEach((j) => { const q = prov(j);
      if (q.owner === null && q.troops !== null) near.push([q.troops, j, i]); }); });
    return near.sort((a, b) => a[0] - b[0])[0];
  }
  const STEPS = [
    ["develop", "🏛", "Develop your capital", "More development: more of everything, and more score.",
      () => queued("develop") || happened("developed"), () => showProvince(capital(), "economy")],
    ["build", "🏗", "Raise a building", "A marketplace doubles a town's ducats; farm estates its grain.",
      () => queued("build") || queued("upgrade_building") || happened("built"), () => showProvince(capital(), "buildings")],
    ["recruit", "⚔", "Raise regiments", "New regiments can march this very year.",
      () => queued("recruit") || queued("hire_mercenaries"), () => showProvince(capital(), "army")],
    ["research", "📜", "Study a technology", "Each branch opens new works and makes the realm stronger.",
      () => queued("research") || happened("researched"), () => { pinned = true; openOffice("tech"); }],
    ["envoy", "✉", "Write to a court", "Propose an alliance, a pact or a royal marriage.",
      () => ["propose_alliance", "propose_marriage", "propose_non_aggression"].some((k) => queued(k)) || V.proposals_sent.length > 0, () => { pinned = true; openOffice("diplomacy"); }],
    ["ambitions", "🎯", "Read your ambitions", "Five goals from your history: fulfil them all and you win.",
      (s) => !!s.sawMissions, () => { const s = stepsKept(); s.sawMissions = true; stepsSave(s); pinned = true; openOffice("missions"); }],
    ["conquer", "⚑", "Take a province", "Attack an independent province next door: no war needed.",
      () => queued("attack", (o) => prov(pIndex[o.target]).owner === null) || happened("province_captured"), () => {
        const w = weakestMinor(); if (!w) return flash("No independent province borders your realm.");
        showProvince(w[2], "army"); deedMin = true; deed(); hint(`Right-click ${P[w[1]].name} (${w[0]} defenders) to attack it with the regiments of ${P[w[2]].name}.`); }],
    ["endyear", "⏳", "End the year", "Your orders are carried out together, with everyone else's.",
      () => V.turn > 1, () => { $("endturn").classList.add("ready"); $("endturn").focus(); }],
  ];
  function firstSteps() {
    const box = $("steps"), kept = stepsKept();
    if (kept.hidden || kept.finished || G.finished) { box.hidden = true; return; }
    const fresh = [];
    for (const [id, icon, title, , test] of STEPS) {
      if (kept[id]) continue;
      let ok = false; try { ok = !!test(kept); } catch {}
      if (ok) { kept[id] = true; fresh.push([icon, title]); }
    }
    const done = STEPS.filter(([id]) => kept[id]).length;
    if (done === STEPS.length) { kept.finished = true; stepsSave(kept); box.hidden = true;
      J.play("triumph"); J.celebrate("Your first steps are done", "Now the age is yours: fulfil your ambitions, or rule half of Europe"); return; }
    stepsSave(kept);
    fresh.forEach(([icon, title], k) => setTimeout(() => { J.play("coins"); J.floatText(box, `✓ ${title}`, "gold"); }, k * 500));
    const next = STEPS.find(([id]) => !kept[id]);
    box.hidden = false;
    box.innerHTML = `<div class="shead"><b>First steps</b><span>${done} of ${STEPS.length}</span><button class="sx" data-hide title="Hide the first steps (bring them back from the guide)">×</button></div>
      <i class="bar"><b style="width:${Math.round(100 * done / STEPS.length)}%"></b></i>
      <ol>${STEPS.map(([id, icon, title, help]) => `<li class="${kept[id] ? "done" : id === next[0] ? "now" : ""}"><span class="ic">${kept[id] ? "✓" : icon}</span>
        <div><b>${esc(title)}</b>${id === next[0] ? `<small>${esc(help)}</small><button class="btn" data-show="${id}">Show me</button>` : ""}</div></li>`).join("")}</ol>`;
    box.querySelector("[data-hide]").onclick = () => { const s = stepsKept(); s.hidden = true; stepsSave(s); box.hidden = true; };
    box.querySelectorAll("[data-show]").forEach((b) => b.onclick = () => { J.play("click"); STEPS.find(([id]) => id === b.dataset.show)[5](); firstSteps(); });
  }
  // ------------------------------------------------------------------ the card of a reign, to share
  // A 1200 by 630 picture: the map with the realm in its colour, the standing over the years,
  // the opening of the chronicle and the deeds won. Drawn on a canvas from the province paths.
  async function reignCard() {
    try { await document.fonts.ready; } catch {}
    const Wc = 1200, Hc = 630, cv = document.createElement("canvas"), dpr = 1;
    cv.width = Wc * dpr; cv.height = Hc * dpr;
    const g = cv.getContext("2d"), color = N[me].color, H = G.history || [], ranks = H.map(rankIn);
    // parchment and frame
    const bg = g.createLinearGradient(0, 0, 0, Hc); bg.addColorStop(0, "#f3e6c4"); bg.addColorStop(1, "#e1cfa5");
    g.fillStyle = bg; g.fillRect(0, 0, Wc, Hc);
    g.strokeStyle = "#3a2414"; g.lineWidth = 10; g.strokeRect(5, 5, Wc - 10, Hc - 10);
    g.strokeStyle = "#c49a52"; g.lineWidth = 2; g.strokeRect(16, 16, Wc - 32, Hc - 32);
    // the map: the realm and its holdings bright, the rest of Europe muted
    const mine = new Set(V.me.provinces.map((x) => pIndex[x]));
    const box = [...mine].reduce((b, i) => { const q = P[i]; return [Math.min(b[0], q.x), Math.min(b[1], q.y), Math.max(b[2], q.x), Math.max(b[3], q.y)]; }, [1e9, 1e9, -1e9, -1e9]);
    const cx = (box[0] + box[2]) / 2 || S.map.width / 2, cy = (box[1] + box[3]) / 2 || S.map.height / 2;
    const span = Math.max(700, (box[2] - box[0]) * 2.2, (box[3] - box[1]) * 2.2 * 1.2);
    const mx = 40, my = 120, mw = 600, mh = 470, k = Math.min(mw / span, mh / (span / 1.25));
    g.save(); g.beginPath(); g.rect(mx, my, mw, mh); g.clip();
    g.fillStyle = "#8fb3c4"; g.fillRect(mx, my, mw, mh);
    g.translate(mx + mw / 2 - cx * k, my + mh / 2 - cy * k); g.scale(k, k);
    if (S.map.wasteland) { g.fillStyle = "#b8ab90"; g.fill(new Path2D(S.map.wasteland)); }
    P.forEach((q, i) => { const owner = V.provinces[i].owner, path = new Path2D(q.d);
      g.fillStyle = mine.has(i) ? color : owner ? mix(N[nIndex[owner]].color, "#efe2c2", 0.62) : "#ddd2b4";
      g.fill(path); g.strokeStyle = "rgba(58,42,24,.45)"; g.lineWidth = 1.2 / k; g.stroke(path); });
    g.restore();
    g.strokeStyle = "#3a2414"; g.lineWidth = 2; g.strokeRect(mx, my, mw, mh);
    // the title
    g.fillStyle = "#2b1d0f"; g.font = "700 46px Cinzel, Georgia, serif"; g.textBaseline = "alphabetic";
    const fillText = g.fillText.bind(g); // the card speaks the reader's language too
    g.fillText = (s, ...at) => fillText(window.PaxI18n ? PaxI18n.t(String(s)) : s, ...at);
    g.fillText(nameOf(G.human), 40, 78);
    g.font = "italic 22px 'EB Garamond', Georgia, serif"; g.fillStyle = "#6b5638";
    g.fillText(`${H.length ? H[0].year : R.startYear} to ${V.year - (G.finished ? 1 : 0)}${V.me.ruler ? `, under ${V.me.ruler.title} ${V.me.ruler.name}` : ""}`, 42, 106);
    // the standing, as a line over the years
    const px = 670, py = 120, pw = 490, ph = 170;
    g.fillStyle = "rgba(255,250,235,.55)"; g.fillRect(px, py, pw, ph); g.strokeStyle = "#8a6a3a"; g.lineWidth = 1; g.strokeRect(px, py, pw, ph);
    g.fillStyle = "#2b1d0f"; g.font = "700 20px Cinzel, Georgia, serif";
    g.fillText(G.finished && G.winner === G.human ? "Victor of the age" : `${ordinal(ranks[ranks.length - 1] || rankOf(V))} in Europe`, px + 14, py + 30);
    const vals = H.map((r) => r.me.standing);
    if (vals.length > 1) {
      const lo = Math.min(...vals), hi = Math.max(...vals) || 1, X = (i) => px + 14 + (pw - 28) * i / (vals.length - 1), Y = (v) => py + ph - 16 - (ph - 64) * (v - lo) / Math.max(1, hi - lo);
      g.strokeStyle = color; g.lineWidth = 4; g.lineJoin = "round"; g.beginPath(); vals.forEach((v, i) => (i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v)))); g.stroke();
      g.fillStyle = "#6b5638"; g.font = "15px 'EB Garamond', Georgia, serif"; g.fillText(`standing ${vals[0]} → ${vals[vals.length - 1]}`, px + pw - 170, py + 30);
    }
    // the opening of the chronicle, wrapped
    const words = (window.PaxI18n ? PaxI18n.t(chronicleOfReign()) : chronicleOfReign()).split(" "), lines = [];
    g.font = "italic 21px 'EB Garamond', Georgia, serif";
    let line = "";
    for (const w of words) { const tryLine = line ? `${line} ${w}` : w; if (g.measureText(tryLine).width > pw - 20) { lines.push(line); line = w; } else line = tryLine; if (lines.length >= 7) break; }
    if (line && lines.length < 7) lines.push(line);
    g.fillStyle = "#2b1d0f"; lines.forEach((l, i) => g.fillText(l + (i === 6 ? "…" : ""), px + 4, py + ph + 40 + i * 27));
    // deeds and signature
    const kept = deedsKept(), won = DEEDS.filter(([id]) => kept[id]);
    g.font = "22px 'EB Garamond', Georgia, serif"; g.fillStyle = "#6b5638";
    g.fillText(`${won.length} deeds of renown  ${won.slice(0, 10).map((d) => d[1]).join(" ")}`, px + 4, Hc - 42);
    g.font = "700 18px Cinzel, Georgia, serif"; g.fillStyle = "#8a6430"; g.textAlign = "right"; g.fillText("Pax Agentica", Wc - 40, Hc - 42); g.textAlign = "left";
    return cv;
  }
  async function shareReign(button) {
    const label = button.textContent; button.disabled = true; button.textContent = "Drawing…";
    let cv;
    try { cv = await reignCard(); } catch { button.disabled = false; button.textContent = label; return flash("The picture could not be drawn."); }
    button.disabled = false; button.textContent = label;
    const blob = await new Promise((ok) => cv.toBlob(ok, "image/png"));
    const name = `pax-agentica-${G.human}-${V.year}.png`, file = new File([blob], name, {type: "image/png"}), url = URL.createObjectURL(blob);
    const canShare = !!(navigator.canShare && navigator.canShare({files: [file]}));
    $("sheet").innerHTML = `<h2 id="modaltitle">A picture of your reign</h2><img class="reigncard" src="${url}" alt="The map of ${esc(nameOf(G.human))}, its standing over the years and its chronicle">
      <div class="row"><a class="btn" href="${url}" download="${name}">Save the picture</a>${canShare ? `<button class="btn" id="sharenow">Share…</button>` : ""}<button class="btn" id="cardback">Close</button></div>`;
    $("modal").classList.add("open");
    const back = () => { URL.revokeObjectURL(url); $("modal").classList.remove("open"); };
    $("cardback").onclick = back;
    const sn = $("sharenow"); if (sn) sn.onclick = () => navigator.share({files: [file], title: `${nameOf(G.human)}: the chronicle of a reign`}).catch(() => {});
  }
  // ------------------------------------------------------------------ deeds of renown
  // Achievements kept by this browser across games: each a test on the year just played.
  // ctx: {evs: this year's events, won/lost provinces, H: history, story, finished, winner}
  const holds = (...ids) => ids.every((id) => V.me.provinces.includes(id));
  const DEEDS = [
    ["first_blood", "⚔", "First blood", "Win a battle.", (c) => c.evs.some((e) => e.kind === "battle" && "attacker" in e.data && (e.data.attacker === G.human) === !!e.data.attacker_won)],
    ["banner", "⚑", "The banner rises", "Win a province, by the sword or the pen.", (c) => c.won.length > 0],
    ["walls_fall", "🏰", "The walls fall", "Take a town by siege.", (c) => c.evs.some((e) => e.kind === "siege" && e.nations[0] === G.human && e.data.progress >= 100)],
    ["vengeance", "💢", "Vengeance", "Win land from a court that wronged you.", (c) => c.evs.some((e) => e.kind === "province_ceded" && e.nations[1] === G.human && (V.me.grudges || []).some((g) => g.against === e.nations[0]))],
    ["first_crown", "👑", "First among crowns", "Stand first in Europe.", () => rankOf(V) === 1],
    ["pax", "🕊", "Pax", "Thirty years in a row without war.", (c) => { let run = 0, best = 0; c.H.forEach((r) => { run = r.me.at_war ? 0 : run + 1; best = Math.max(best, run); }); return best >= 31; }],
    ["wonders", "🏛", "Patron of wonders", "Raise a monument to its third level.", () => V.provinces.some((p) => p.owner === G.human && p.monument >= 3)],
    ["reason", "📜", "Light of reason", "Reach the fifth level of a technology.", () => Object.values(V.me.technology).some((v) => v >= 5)],
    ["stone", "🏗", "A realm of stone", "Hold buildings worth 25 levels in all.", () => V.provinces.filter((p) => p.owner === G.human).reduce((a, p) => a + Object.values(p.building_levels || {}).reduce((x, y) => x + y, 0), 0) >= 25],
    ["fugger", "💰", "The Fuggers' envy", "Hold a thousand ducats.", () => V.me.resources.ducats >= 1000],
    ["marriages", "💍", "The marriage market", "Be joined by marriage to three houses at once.", () => V.me.treaties.filter((t) => t.kind === "marriage").length >= 3],
    ["dynasty", "🌳", "A long dynasty", "See four rulers on your throne.", (c) => reignsOf(c.H).length >= 4],
    ["weathered", "☠", "The years of trial", "Come through the crisis of the age without losing a province.", (c) => {
      const end = c.evs.find((e) => e.kind === "crisis" && !e.data.begins); if (!end) return false;
      const at = c.H.find((r) => r.year === end.data.first), now = c.H[c.H.length - 1]; return !!at && now.me.provinces >= at.me.provinces; }],
    ["italy", "⚜", "The Italian Wars", "As France, hold Milan and Naples.", () => G.human === "france" && holds("milan", "naples")],
    ["iberia", "🏰", "One crown for Iberia", "As Spain, hold Lisbon and Porto.", () => G.human === "spain" && holds("lisbon", "porto")],
    ["gates", "☪", "The gates of Vienna", "As the Ottomans, take Vienna.", () => G.human === "ottomans" && holds("vienna")],
    ["isles", "⚓", "Lord of the isles", "As England, hold Scotland, the Highlands, Ireland and Ulster.", () => G.human === "england" && holds("scotland", "highlands", "ireland", "ulster")],
    ["third_rome", "☦", "The third Rome", "As Russia, hold Kiev and Novgorod and Pskov.", () => G.human === "russia" && holds("kiev", "novgorod", "pskov")],
    ["sands", "🦅", "From the sands of Brandenburg", "Win the game with Brandenburg-Prussia.", (c) => c.finished && c.winner === "brandenburg" && G.human === "brandenburg"],
    ["destiny", "🏆", "Destiny", "Win by fulfilling every ambition of your crown.", (c) => c.finished && c.winner === G.human && c.evs.some((e) => e.kind === "game_over" && /ambition/.test(e.summary))],
    ["hegemon", "🌍", "Hegemon", "Win by ruling half of Europe.", (c) => c.finished && c.winner === G.human && c.evs.some((e) => e.kind === "game_over" && /rules \d+ of/.test(e.summary))],
    ["victor", "⭐", "Victor", "Win a game.", (c) => c.finished && c.winner === G.human],
  ];
  const DEEDS_KEY = "pax-deeds";
  const deedsKept = () => { try { return JSON.parse(localStorage.getItem(DEEDS_KEY) || "{}"); } catch { return {}; } };
  // Test every deed against the year just played; new ones are kept and announced.
  function checkDeeds(evs, won) {
    const kept = deedsKept(), fresh = [];
    const c = {evs, won, H: G.history || [], story: G.story || {}, finished: G.finished, winner: G.winner};
    for (const [id, icon, title, , test] of DEEDS) {
      if (kept[id]) continue;
      let ok = false; try { ok = !!test(c); } catch {}
      if (ok) { kept[id] = {year: V.year - 1, nation: nameOf(G.human), date: new Date().toISOString().slice(0, 10)}; fresh.push([icon, title]); }
    }
    if (fresh.length) { try { localStorage.setItem(DEEDS_KEY, JSON.stringify(kept)); } catch {} }
    return fresh;
  }
  function deedsShelf() {
    const kept = deedsKept(), have = DEEDS.filter(([id]) => kept[id]).length;
    return `<h4>🎖 Deeds of renown <small class="sub">${have} of ${DEEDS.length}, kept by this browser across games</small></h4>
      <div class="deeds">${DEEDS.map(([id, icon, title, hint]) => { const k = kept[id];
        return `<div class="deed-item ${k ? "won" : ""}" title="${esc(hint)}${k ? ` Won in ${k.year} with ${k.nation}.` : ""}"><span class="ic">${k ? icon : "🔒"}</span><b>${esc(title)}</b><small>${k ? `${k.year}, ${esc(k.nation)}` : esc(hint)}</small></div>`; }).join("")}</div>`;
  }
  // A new reign: the heir crowned, with what they bring to the throne.
  function deedToast(icon, title) {
    const box = document.createElement("div"); box.className = "deedtoast";
    box.innerHTML = `<span class="ic"></span><div><small>A deed of renown</small><b></b></div>`;
    box.querySelector(".ic").textContent = icon; box.querySelector("b").textContent = title;
    document.body.appendChild(box); setTimeout(() => box.classList.add("out"), 4200); setTimeout(() => box.remove(), 4800);
  }
  function coronation(r) {
    const color = N[me].color, ended = reignsOf(G.history || []).slice(-2, -1)[0];
    const pip = (n) => `<span class="cpips">${"◆".repeat(n)}${"◇".repeat(Math.max(0, 6 - n))}</span>`;
    J.play("coronation");
    J.ceremony(`<div class="crown-top">👑</div><div class="cportrait">${portrait(r, color, 120)}</div>
      <div class="tbig">Long live ${esc(r.title)} ${esc(r.name)}</div>
      <div class="tsub">${esc(nameOf(G.human))} has a new ${esc(r.title.toLowerCase())}, aged ${r.age}.${ended ? ` ${reignLine(ended)}` : ""}</div>
      ${r.traits && r.traits.length ? `<div class="ctraits">${r.traits.map((tr) => `<span>${esc(cap(tr))}</span>`).join("")}</div>` : ""}
      <div class="cstats"><div>Administration ${pip(r.administration)}</div><div>Diplomacy ${pip(r.diplomacy)}</div><div>Military ${pip(r.military)}</div></div>`);
  }
  // The ambitions closest to fulfilment: a next step always in sight.
  function nextAmbitions() {
    const share = (m) => m.goals.reduce((a, g) => a + Math.min(1, g.have / Math.max(1, g.need)), 0) / Math.max(1, m.goals.length);
    const open = (V.me.missions || []).filter((m) => m.status === "open").sort((a, b) => share(b) - share(a)).slice(0, 2);
    if (!open.length || G.finished) return "";
    const done = (V.me.missions || []).filter((m) => m.status === "done").length, all = (V.me.missions || []).length;
    return `<section class="within"><h3>🎯 Within reach <small>${done} of ${all} ambitions fulfilled${R.ambitionVictory ? ": all of them win the game" : ""}</small></h3>${open.map((m) => { const s = Math.round(share(m) * 100), todo = m.goals.filter((g) => g.have < g.need);
      return `<div class="amb"><div class="amhead"><b>${esc(m.title)}</b><span>${s}%</span></div><i class="bar"><b style="width:${s}%"></b></i>
        <small>${todo.length ? `Still to do: ${todo.map((g) => esc(g.text)).join("; ")}` : "Every goal holds: it is fulfilled at the end of this year."}</small>
        <small class="rw">Reward: ${esc(m.reward)}</small></div>`; }).join("")}</section>`;
  }
  // Each year closes with the feeling it deserves: one sound, and a triumph when it earned one.
  function feelYear(before, evs, won, lost) {
    const fresh = checkDeeds(evs, won);
    fresh.forEach(([icon, title], k) => setTimeout(() => { J.play("triumph"); J.floatText($("endturn"), `${icon} ${title}`, "gold"); deedToast(icon, title); }, 4200 + k * 1800));
    const mine = evs.filter((e) => e.nations.includes(G.human));
    const missions = mine.filter((e) => e.kind === "mission_completed" && e.nations[0] === G.human);
    const attacked = mine.some((e) => e.kind === "war_declared" && e.nations[0] !== G.human);
    const fought = mine.some((e) => e.kind === "battle");
    const peace = mine.some((e) => e.kind === "peace_signed");
    const age = evs.find((e) => e.kind === "crisis" && e.data.begins);
    if (age && V.crisis) {
      setTimeout(() => { J.play("omen"); J.vignette("war"); J.omen(CRISIS_ICON[V.crisis.kind] || "☠", V.crisis.title, `${V.crisis.text} (${V.crisis.first_year} to ${V.crisis.last_year})`); }, 350);
      return;
    }
    const crowned = evs.find((e) => e.kind === "succession" && e.nations[0] === G.human);
    if (crowned && V.me.ruler) { setTimeout(() => coronation(V.me.ruler), 350); return; }
    setTimeout(() => {
      if (missions.length) { J.play("triumph"); J.celebrate(missions[0].summary.split(": ").slice(1).join(": ") || "Ambition fulfilled", "An ambition of the crown is fulfilled"); }
      else if (won.length) { J.play("triumph"); J.celebrate(`${won.map((x) => P[pIndex[x]].name).join(", ")} ${won.length > 1 ? "are" : "is"} ours`, "The realm grows", [N[me].color, "#ecd08c", "#fff3cf"]); }
      else if (lost.length) { J.play("loss"); J.vignette("war"); }
      else if (attacked) { J.play("war"); J.vignette("war"); }
      else if (peace) J.play("peace");
      else if (fought) J.play("battle");
    }, 350);
    // what the treasury gained or lost, rising over each resource
    if (before) requestAnimationFrame(() => RES.forEach(([key], k) => {
      const d = unbundle(V.me.resources)[k] - unbundle(before.me.resources)[k];
      const el = document.querySelector(`.stat[data-res="${key}"]`);
      if (!d || !el) return;
      setTimeout(() => { J.floatText(el, `${d > 0 ? "+" : "−"}${Math.abs(d)}`, d > 0 ? (key === "ducats" ? "gold" : "") : "neg");
        el.querySelector(".val b")?.classList.add("bump"); }, 200 + k * 90);
    }));
  }
  function rankOf(view) {
    const all = [...view.nations.filter((n) => n.alive && n.id !== G.human).map((n) => n.standing), view.me.standing];
    return 1 + all.filter((s) => s > view.me.standing).length;
  }
  // ------------------------------------------------------------------ a province's focus
  // What its people turn their hands to: a share more of one side of its output, the larger the
  // town the more; set for a price, and kept for some years.
  const FOCI = [["trade", "💰", "Trade", "more ducats"], ["farming", "🌾", "Farming", "more grain"], ["mining", "⛏", "Mining", "more iron and timber"],
    ["garrison", "🛡", "Garrison", "twice as much more manpower, and its own people defend it harder"], ["learning", "📚", "Learning", "cheaper to develop, and each one makes the realm's research cheaper"]];
  function focusShare(p) { // what a focus would give this province, by its town
    const steps = (R.settlements || []).map((s) => s.min_development).sort((a, b) => a - b);
    const step = Math.max(0, steps.filter((m) => p.development >= m).length - 1);
    return R.focus.base + R.focus.perSettlement * step;
  }
  function focusCard(i, t) {
    const p = prov(i), id = P[i].id, now = FOCI.find(([k]) => k === p.focus), share = Math.round(focusShare(p) * 100);
    const queued = orders.find((x) => x.type === "set_focus" && x.province === id);
    const locked = p.focus_locked_until != null && V.turn < p.focus_locked_until;
    const why = locked ? `kept until ${R.startYear + p.focus_locked_until - 1}` : !affordable(R.focus.cost, t) ? "too costly for now" : "";
    return `<section><div class="card ${why ? "blocked" : "ready"}">
      <div class="cardhead"><span class="ic">${now ? now[1] : "🎯"}</span><div><b>${now ? `Given to ${now[2].toLowerCase()}` : "No focus yet"}</b>
        <div class="gain">${now ? `<span>+${share}%: ${esc(now[3])}</span>` : `<span>a focus gives +${share}% here, more as the town grows</span>`}</div></div></div>
      <div class="foci">${FOCI.map(([k, ic, name, what]) => `<button class="btn ${p.focus === k ? "on" : ""} ${queued && queued.focus === k ? "queued" : ""}" data-act="focus:${k}"
        ${why || p.focus === k ? "disabled" : ""}${tip(`<h5>${ic} ${name}</h5><div>+${share}%: ${esc(what)}</div>`)}>${ic} ${name}</button>`).join("")}</div>
      <p class="note">${why ? cap(why) + ". " : ""}Costs ${costText(R.focus.cost)}; a province keeps its focus ${R.focus.years} years.</p></div></section>`;
  }
  // ------------------------------------------------------------------ the epilogue: the whole game, once it is over
  // Every court's course year by year in one chart (pick the measure), what each did in the
  // field and at the treaty table, and Europe's map replayed a year at a time.
  const MEASURES = [["standing", "Standing"], ["development", "Development"], ["provinces", "Provinces"], ["regiments", "Regiments"], ["income", "Income"]];
  let epiMeasure = "standing";
  const courtColor = (nid) => (nid in nIndex ? N[nIndex[nid]].color : "#9a8f78");
  function epilogueSection() {
    const E = G.epilogue, ids = Object.keys(E.courts).sort((a, b) => E.courts[b].series.standing.at(-1) - E.courts[a].series.standing.at(-1));
    const rows = ids.map((nid) => { const c = E.courts[nid], s = c.series, alive = s.provinces.at(-1) > 0;
      const peak = Math.max(...s.provinces), at = E.years[s.provinces.indexOf(peak)];
      return `<tr class="${nid === G.human ? "me" : ""}"><td><i class="sw" style="background:${courtColor(nid)}"></i>${esc(nameOf(nid))}${alive ? "" : " †"}</td>
        <td>${s.standing.at(-1)}</td><td>${peak} <small>in ${at}</small></td><td>${c.battles_won}–${c.battles_lost}</td><td>+${c.gained} / −${c.lost}</td><td>${c.wars}</td></tr>`; }).join("");
    return `<section class="epilogue"><h3>Europe, ${E.years[0]}–${E.years.at(-1)}</h3>
      <div class="epitabs" role="tablist">${MEASURES.map(([k, label]) => `<button type="button" class="btn ${k === epiMeasure ? "on" : ""}" data-measure="${k}" role="tab" aria-selected="${k === epiMeasure}">${label}</button>`).join("")}</div>
      <div class="epichart" id="epichart"></div>
      <div class="epilegend">${ids.map((nid) => `<span class="${nid === G.human ? "me" : ""}"><i class="sw" style="background:${courtColor(nid)}"></i>${esc(nameOf(nid))}</span>`).join("")}</div>
      <table class="grid num epitable"><thead><tr><th>Nation</th><th>Standing</th><th>Most land</th><th>Battles won–lost</th><th>Provinces won / lost</th><th>Wars declared</th></tr></thead><tbody>${rows}</tbody></table>
      <button class="btn" id="epireplay" type="button">▶ Watch Europe's map, year by year</button></section>`;
  }
  function epilogueChart() {
    const E = G.epilogue, box = $("epichart"); if (!box) return;
    const W = 540, H = 230, L = 38, R = 78, T = 10, B = 24, years = E.years, n = years.length;
    const ids = Object.keys(E.courts), data = ids.map((nid) => ({nid, v: E.courts[nid].series[epiMeasure]}));
    const top = Math.max(4, ...data.flatMap((d) => d.v)), mag = Math.pow(10, Math.floor(Math.log10(top / 4)));
    const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s * 4 >= top), nice = step * 4;
    const x = (i) => L + (W - L - R) * (n > 1 ? i / (n - 1) : 0), y = (v) => T + (H - T - B) * (1 - v / nice);
    const ticks = [0, 1, 2, 3, 4].map((k) => k * step);
    const yearTicks = years.filter((yr, i) => i === 0 || i === n - 1 || (yr % 10 === 0 && i > 2 && i < n - 3));
    // mine drawn last, so it is never under another court's line
    data.sort((a, b) => (a.nid === G.human) - (b.nid === G.human));
    // labels at the right end, nudged apart so none overlap
    const ends = data.map((d) => ({nid: d.nid, y: y(d.v.at(-1)), v: d.v.at(-1)})).sort((a, b) => a.y - b.y);
    for (let k = 1; k < ends.length; k++) ends[k].y = Math.max(ends[k].y, ends[k - 1].y + 11);
    const over = ends.length ? ends.at(-1).y - (H - B) : 0; if (over > 0) ends.forEach((e) => (e.y -= over));
    box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(MEASURES.find((m) => m[0] === epiMeasure)[1])} of every court, year by year">
      ${ticks.map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="gridline"/><text x="${L - 6}" y="${y(v) + 3.5}" class="ytick">${v}</text>`).join("")}
      ${yearTicks.map((yr) => `<text x="${x(years.indexOf(yr))}" y="${H - 6}" class="xtick">${yr}</text>`).join("")}
      ${data.map((d) => { const path = d.v.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(""), w = d.nid === G.human ? 3 : 2;
        // a thin dark casing, so a pale banner (Austria's white) still reads on parchment
        return `<path d="${path}" fill="none" stroke="rgba(58, 36, 20, .45)" stroke-width="${w + 1.4}" stroke-linejoin="round" stroke-linecap="round"/>
          <path d="${path}" fill="none" stroke="${courtColor(d.nid)}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round"/>`; }).join("")}
      ${ends.map((e) => `<text x="${W - R + 6}" y="${e.y + 3.5}" class="endlabel ${e.nid === G.human ? "me" : ""}">${esc(nameOf(e.nid).split(/[ -]/)[0])} ${e.v}</text>`).join("")}
      <line class="cross" x1="0" x2="0" y1="${T}" y2="${H - B}" style="display:none"/>
      <rect class="hit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/></svg><div class="epitip" hidden></div>`;
    const svg = box.querySelector("svg"), cross = svg.querySelector(".cross"), tip = box.querySelector(".epitip");
    const at = (evt) => { const r = svg.getBoundingClientRect(), sx = (evt.clientX - r.left) / r.width * W;
      return Math.max(0, Math.min(n - 1, Math.round((sx - L) / (W - L - R) * (n - 1)))); };
    svg.querySelector(".hit").addEventListener("pointermove", (evt) => {
      const i = at(evt), r = svg.getBoundingClientRect();
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.style.display = "";
      const list = data.map((d) => [d.nid, d.v[i]]).sort((a, b) => b[1] - a[1]);
      tip.innerHTML = `<b>${years[i]}</b>${list.map(([nid, v]) => `<div class="${nid === G.human ? "me" : ""}"><i class="sw" style="background:${courtColor(nid)}"></i>${esc(nameOf(nid))}<span>${v}</span></div>`).join("")}`;
      tip.hidden = false;
      const px = x(i) / W * r.width;
      tip.style.left = `${px > r.width / 2 ? px - tip.offsetWidth - 10 : px + 10}px`;
    });
    svg.querySelector(".hit").addEventListener("pointerleave", () => { cross.style.display = "none"; tip.hidden = true; });
  }
  function epilogueWire() {
    epilogueChart();
    document.querySelectorAll(".epitabs [data-measure]").forEach((b) => b.onclick = () => {
      epiMeasure = b.dataset.measure;
      document.querySelectorAll(".epitabs [data-measure]").forEach((o) => { o.classList.toggle("on", o === b); o.setAttribute("aria-selected", String(o === b)); });
      epilogueChart(); });
    $("epireplay").onclick = replayEurope;
  }
  // Europe's map from the first year to the last, a third of a second a year; the end report
  // comes back when it is over (or at a click on Skip).
  async function replayEurope() {
    const E = G.epilogue, base = world(), order = E.provinces.map((id) => pIndex[id]);
    $("modal").classList.remove("open");
    map.home();
    const bar = document.createElement("div");
    bar.className = "replaybar";
    bar.innerHTML = `<b class="ryear"></b><div class="rtrack"><i></i></div><button class="btn" type="button">Skip</button>`;
    $("map").parentElement.appendChild(bar);
    $("banner").style.visibility = "hidden";
    let stop = false;
    bar.querySelector("button").onclick = () => { stop = true; };
    const pace = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? 700 : 330 * O.speed();
    for (let i = 0; i < E.years.length && !stop; i++) {
      const owner = new Array(P.length).fill(-1);
      E.owners[i].forEach((nid, k) => { if (order[k] !== undefined) owner[order[k]] = nid && nid in nIndex ? nIndex[nid] : -1; });
      const none = owner.map(() => null);
      map.paint({...base, mode: "political", owner, controller: owner.map(() => -1), troops: owner.map(() => 0), planned: [], sieges: none,
        generals: new Map(), buildings: owner.map(() => []), forts: owner.map(() => 0), events: [], capitals: new Set(), alive: N.map((_, k) => owner.includes(k))});
      bar.querySelector(".ryear").textContent = E.years[i];
      bar.querySelector(".rtrack i").style.width = `${(i + 1) / E.years.length * 100}%`;
      if (i && E.owners[i].some((o, k) => o !== E.owners[i - 1][k])) J.play("click");
      await new Promise((r) => setTimeout(r, i === E.years.length - 1 ? 1200 : pace));
    }
    bar.remove();
    $("banner").style.visibility = "";
    render();
    $("modal").classList.add("open");
  }
  // The year's marches, for the map to play before the report: your own moves, every battle and
  // conquest you can see on screen, each drawn from where the army set out to where it arrived.
  function marches(events) {
    const v = map.view, seen = (i) => P[i].x >= v.x && P[i].x <= v.x + v.w && P[i].y >= v.y && P[i].y <= v.y + v.h;
    const colorOf = (id) => (id in nIndex ? N[nIndex[id]].color : "#9a8f78");
    const took = new Map(events.filter((e) => ["province_captured", "province_occupied", "province_liberated"].includes(e.kind) && e.province)
      .map((e) => [e.province, e.nations[0]]));
    const out = [];
    for (const e of events) {
      const to = pIndex[e.province];
      if (to === undefined) continue;
      const mine = e.nations.includes(G.human);
      if (e.kind === "moved" && mine && e.data.origin in pIndex) out.push({from: pIndex[e.data.origin], to, color: colorOf(e.nations[0])});
      if (e.kind === "battle" && "attacker" in e.data) {
        const won = e.summary.includes(`${e.data.attacker_name} wins.`);
        for (const o of String(e.data.origins || e.data.origin || "").split(", ").filter((x) => x in pIndex)) {
          if (!mine && !seen(to) && !seen(pIndex[o])) continue;
          out.push({from: pIndex[o], to, color: colorOf(e.data.attacker), fight: true, won,
            took: took.has(e.province), takerColor: colorOf(took.get(e.province))});
        }
      }
      if (["province_captured", "province_occupied", "province_liberated"].includes(e.kind) && e.data.origin in pIndex
          && !events.some((b) => b.kind === "battle" && b.province === e.province && "attacker" in b.data)
          && (mine || seen(to))) out.push({from: pIndex[e.data.origin], to, color: colorOf(e.nations[0]), took: true});
    }
    // yours first, so a crowded year never hides your own armies
    return out.sort((a, b) => (b.color === colorOf(G.human)) - (a.color === colorOf(G.human))).slice(0, 26);
  }
  async function report(before) {
    await J.yearCard(V.year, before ? headline(V.last_turn_events, V.me.provinces.filter((p) => !before.me.provinces.includes(p)), before.me.provinces.filter((p) => !V.me.provinces.includes(p))) : "");
    if (before) await map.motion(marches(V.last_turn_events || []));
    J.play("year");
    const lost = before ? before.me.provinces.filter((p) => !V.me.provinces.includes(p)) : [];
    const won = before ? V.me.provinces.filter((p) => !before.me.provinces.includes(p)) : [];
    const noise = ["moved", "recruited", "proposal_made", "market_trade", "prestige_changed", "taxes_set"];
    const line = (e) => `<li class="${BAD.has(e.kind) ? "bad" : ""}">${ICON[e.kind] || "•"} ${esc(told(e))}</li>`;
    const fought = (e) => (e.kind === "battle" && "attacker" in e.data) || e.kind === "naval_battle" || (e.kind === "siege" && ("progress" in e.data || "lifted" in e.data));
    const items = V.last_turn_events.filter((e) => !noise.includes(e.kind) && e.nations.includes(G.human) && !fought(e)).map(line).join("");
    const mineWar = V.last_turn_events.filter((e) => e.nations.includes(G.human) && fought(e));
    const war = mineWar.filter((e) => e.kind === "naval_battle").map(navalCard).join("") + mineWar.filter((e) => e.kind === "battle").map(battleCard).join("") + mineWar.filter((e) => e.kind === "siege").map(siegeLine).join("");
    const europe = V.last_turn_events.filter((e) => !noise.includes(e.kind) && !e.nations.includes(G.human)
      && ["war_declared", "joined_war", "peace_signed", "nation_eliminated", "treaty_broken", "coalition_joined", "coalition_dissolved", "infamy",
          "mission_completed", "proclamation", "province_captured", "province_ceded", "succession", "capital_moved", "treaty_signed", "game_over"].includes(e.kind))
      .slice(0, 16).map(line).join("");
    const discoveries = before ? T.filter((b) => V.me.technology[b.id] > before.me.technology[b.id]).map((b) => {
      const step = b.levels[V.me.technology[b.id] - 1];
      return `<div class="discovery">⚙ <b>${esc(step.name)}</b>: ${esc(step.unlocks)}.</div>`; }).join("") : "";
    // a town of yours that grew into a larger one this year: a step anyone feels
    const grown = before ? V.provinces.filter((p) => p.owner === G.human && p.settlement).map((p) => [p, before.provinces.find((q) => q.id === p.id)])
      .filter(([p, q]) => q && q.settlement && q.settlement !== p.settlement && p.development > q.development)
      .map(([p]) => `<div class="discovery">🏙 <b>${esc(p.name)}</b> has grown into a ${esc(p.settlement.toLowerCase())}: room for ${p.building_slots} works.</div>`).join("") : "";
    const works = V.last_turn_events.filter((e) => e.kind === "built" && e.nations[0] === G.human)
      .map((e) => `<div class="work">🏗 ${esc(e.summary.replace(/^\S+ builds /, "A new ").replace(" in ", " stands in "))}.</div>`).join("");
    const ended = reignsOf(G.history || []).slice(-2, -1)[0];
    const crowned = V.last_turn_events.filter((e) => e.kind === "succession" && e.nations[0] === G.human)
      .map((e) => `<div class="discovery">👑 ${esc(e.summary)}.${ended ? `<div class="reignend">${reignLine(ended)}</div>` : ""}</div>`).join("");
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
        <div class="chronicle-end"><h3>The chronicle of your reign</h3><p id="reigntext">${esc(chronicleOfReign())}</p>
          <button class="btn" id="copyreign" type="button">Copy the chronicle</button> <button class="btn" id="sharereign2" type="button">🖼 A picture of your reign</button></div>
        ${G.epilogue ? epilogueSection() : ""}
        <p><a href="${REPLAY}" target="_blank">Watch the whole game as a replay</a></p></div>` : "";
    const tiles = before ? [["Rank", rankOf(V), rankOf(before), true], ["Standing", V.me.standing, before.me.standing], ["Development", V.me.score, before.me.score],
      ["Provinces", V.me.provinces.length, before.me.provinces.length], ["Regiments", V.me.regiments, before.me.regiments]] : [];
    const deltas = tiles.length ? `<div class="deltas">${tiles.map(([label, now, was, lowIsGood]) => { const d = now - was, good = lowIsGood ? d < 0 : d > 0;
      return `<div><b class="num" data-to="${now}">${was}</b><small>${label}${d ? ` <span class="${good ? "up" : "down"}">${d > 0 ? "▲" : "▼"} ${Math.abs(d)}</span>` : ""}</small></div>`; }).join("")}</div>` : "";
    $("sheet").innerHTML = `<h2 id="modaltitle">${G.finished ? "The end of an age" : `The year ${V.year - 1}`}</h2>
      ${before ? `<p class="headline">${esc(headline(V.last_turn_events, won, lost))}</p>` : ""}${before ? sceneOfYear(V.last_turn_events, won) : ""}${deltas}${ending}${crowned}${grown}${discoveries}${works}${G.finished ? "" : danger}
      ${unanswered().length ? `<section class="awaiting"><h3>📜 Letters awaiting your answer</h3><ul>${unanswered().map((p) => `<li>${PROPOSAL_ICON[p.kind] || "📜"} ${proposalText(p)}</li>`).join("")}</ul>
        <button class="btn" id="toletters">Answer them</button></section>` : ""}
      ${war ? `<section class="warlog"><h3>⚔ Your battles and sieges</h3>${war}</section>` : ""}
      ${nextAmbitions()}
      <div class="yearcols"><section><h3>${PaxMap.flag(G.human, N[me].color, 22, "flag inline")} Your realm</h3>
        ${won.length ? `<p class="gain-line">Gained ${won.map((p) => esc(P[pIndex[p]].name)).join(", ")}.</p>` : ""}
        ${lost.length ? `<p class="loss-line">Lost ${lost.map((p) => esc(P[pIndex[p]].name)).join(", ")}.</p>` : ""}
        <ul>${items || "<li>A quiet year for your realm.</li>"}</ul></section>
      <section><h3>🌍 Europe</h3><ul>${europe || "<li>Europe holds its breath.</li>"}</ul></section></div>
      <button class="btn" id="closemodal">Continue</button>`;
    const sheet = $("sheet"); sheet.classList.add("reveal");
    sheet.querySelectorAll(".sheet.reveal li, .battlecard, .siegeline, .discovery, .work, .deltas > div").forEach((x, k) => (x.style.animationDelay = `${Math.min(k, 24) * 45}ms`));
    $("modal").classList.add("open"); $("closemodal").focus({preventScroll: true}); sheet.scrollTop = 0;
    sheet.querySelectorAll(".deltas b[data-to]").forEach((b, k) => setTimeout(() => J.countTo(b, +b.dataset.to), 250 + k * 80));
    feelYear(before, V.last_turn_events, won, lost);
    $("closemodal").onclick = () => { $("modal").classList.remove("open"); sheet.classList.remove("reveal"); eventSheet(); };
    const sr2 = $("sharereign2"); if (sr2) sr2.onclick = () => shareReign(sr2);
    if (G.epilogue && $("epichart")) epilogueWire();
    const cr = $("copyreign");
    if (cr) cr.onclick = () => { navigator.clipboard?.writeText(`${$("reigntext").textContent}\n— Pax Agentica`); cr.textContent = "Copied"; };
    const tl = $("toletters");
    if (tl) tl.onclick = () => { $("modal").classList.remove("open"); pinned = true; openOffice("letters"); };
  }
  // ------------------------------------------------------------------ the crown's decisions
  const EVENT_ICON = {reformation: "✝", plague: "☠", harvest: "🌾", fuggers: "💰", artist: "🎨", revolt: "🔥",
    silver: "🥈", comet: "☄", reformer: "⚔", nobles: "👑", fair: "🎪", mine: "⛏",
    great_plague: "☠", frozen_harvests: "❄", silver_flood: "⚖"};
  const GRAVE = new Set(["great_plague", "frozen_harvests", "silver_flood"]); // the age's crises come first
  const chosen = (id) => orders.find((o) => o.type === "choose_option" && o.event_id === id);
  const colourEffects = (text) => esc(text).replace(/([+−-]\d+(?:\.\d+)?%?)\s([a-z ]+?)(?=,|$)/g, (m, n, what) =>
    `<span class="${n.startsWith("+") ? "pos" : "neg"}">${n} ${what}</span>`).replace(/(repay [^,]+|[\d]+ regiments lost[^,]*|\d+ years of unrest[^,]*)/g, '<span class="neg">$1</span>');
  function eventCard(e, big = false) {
    const pick = chosen(e.id);
    const drawn = window.PaxScenes?.ofEvent(e.event);
    const scene = drawn ? `<div class="escene">${drawn}</div>`
      : e.province && S.views[e.province] ? `<img class="escene" src="/views/${e.province}.jpg" alt="">`
      : V.me.ruler ? `<div class="eruler">${portrait(V.me.ruler, N[me].color, big ? 72 : 48)}</div>` : "";
    return `<div class="eventcard ${big ? "big" : ""}">${big ? scene : ""}<div class="ehead"><span class="eic">${EVENT_ICON[e.event] || "📜"}</span>
        <div><b>${esc(e.title)}</b>${e.province ? `<small>${esc(P[pIndex[e.province]].name)}</small>` : ""}</div></div>
      <p class="etext">${esc(e.text)}</p>
      <div class="eoptions">${e.options.map((o, k) => `<button class="btn eoption ${pick && pick.option === k ? "on" : ""}" data-event="${e.id}" data-option="${k}">
        <b>${esc(o.label)}</b><small>${colourEffects(o.effects)}</small></button>`).join("")}</div>
      <p class="sub">${pick ? "Your decision is taken; it is carried out when the year ends." : `Undecided by the end of ${R.startYear + e.deadline_turn - 1}, the first answer is taken.`}</p></div>`;
  }
  // a declaration of war, weighed before it is sent
  function confirmWar(nid) {
    const n = V.nations.find((x) => x.id === nid), r = relation(nid);
    const broken = [r.alliance && "your alliance", r.pact && "your non-aggression pact", r.truce && "the truce", r.marriage && "the royal marriage"].filter(Boolean);
    const allies = n.allies.filter((a) => a !== G.human).map((a) => esc(nameOf(a)));
    const league = V.nations.filter((x) => x.alive && x.leagued_against.includes(G.human) && x.id !== nid && V.nations.find((y) => y.id === nid).leagued_against.includes(G.human)).map((x) => esc(x.name));
    const theirs = V.provinces.filter((p) => p.owner === nid).reduce((a, p) => a + (p.troops || 0), 0);
    $("sheet").innerHTML = `<h2 id="modaltitle">${I("swords")} War on ${esc(n.name)}?</h2>
      <div class="warconfirm">${PaxMap.flag(nid, N[nIndex[nid]].color, 54)}<div>
        <p><b>${esc(n.name)}</b>: standing ${n.standing}, ${n.provinces} provinces, at least ${theirs} regiments seen. They think ${sign(n.opinion_of_you)} of you.</p>
        <ul>${broken.length ? `<li class="bad">It breaks ${broken.join(" and ")}: −${R.breakPenalty} stability and every court thinks less of you.</li>` : ""}
          ${allies.length ? `<li class="bad">Their allies will be called to arms: ${allies.join(", ")}.</li>` : "<li>They have no allies to call.</li>"}
          ${league.length ? `<li class="bad">They are leagued against you with ${league.join(", ")}: the league marches too.</li>` : ""}
          <li>Your armies mobilise for ${R.mobilization} year before they can attack.</li>
          <li>Taken land is only occupied: a peace treaty moves borders, as far as your war score allows.</li></ul></div></div>
      <div class="row"><button class="btn danger" id="waryes">Declare war</button><button class="btn" id="warno">Not now</button></div>`;
    $("modal").classList.add("open");
    $("warno").onclick = () => $("modal").classList.remove("open");
    $("waryes").onclick = () => { $("modal").classList.remove("open"); queue({type: "declare_war", target: nid}); };
  }
  function choose(eventId, option) {
    orders = orders.filter((o) => !(o.type === "choose_option" && o.event_id === eventId));
    queue({type: "choose_option", event_id: eventId, option});
  }
  function eventSheet() {
    const open = V.me.pending_events.filter((x) => !chosen(x.id));
    const e = open.find((x) => GRAVE.has(x.event)) || open[0];
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
      mode, focus: f, relations, diplo, alive, faiths: V.provinces.map((p) => p.faith), workings: V.provinces.map((p) => p.workings || 0), capitals, generals,
      owner: V.provinces.map((p) => (p.owner === null ? -1 : nIndex[p.owner])),
      controller: V.provinces.map((p) => (p.controller ? nIndex[p.controller] : -1)),
      troops: V.provinces.map((p) => p.troops), dev: V.provinces.map((p) => p.development),
      veterans: V.provinces.map((p) => p.veterancy || 0),
      fleets: SEAS.map((z) => { const sv = seaView(z.id); return sv ? Object.entries(sv.fleets).sort((a, b) => (sv.power[b[0]] || 0) - (sv.power[a[0]] || 0))
        .map(([n, ships]) => [nIndex[n], Object.values(ships).reduce((a, b) => a + b, 0)]) : []; }),
      planned: V.provinces.map((p, i) => (owned(i) && p.troops !== null ? troopsAfter(i) - p.troops : 0)),
      forts: V.provinces.map((p) => p.fort || 0),
      sieges: V.provinces.map((p) => (p.siege_by ? {by: nIndex[p.siege_by], progress: p.siege_progress, besiegers: p.besiegers} : null)),
      buildings: V.provinces.map((p) => p.buildings.map((b) => bIndex[b])),
      events: V.last_turn_events.filter((e) => e.province).map((e) => [e.kind, pIndex[e.province], e.nations.map((x) => nIndex[x])]),
    };
  }
  const MODES = [["political", "Political", "flag"], ["terrain", "Terrain", "mountain-snow"], ["development", "Development", "building-2"],
    ["goods", "Trade goods", "package"], ["faith", "Religion", "church"], ["diplomacy", "Diplomacy", "handshake"]];
  MODES.forEach(([id, label, icon], k) => { const b = document.createElement("button"); b.className = "iconbtn"; b.innerHTML = I(icon);
    b.setAttribute("data-tip", `<h5>${label} map</h5><div class="dim">Key ${k + 1}</div>`); b.setAttribute("aria-label", `${label} map`);
    b.dataset.mode = id; b.onclick = () => { mode = id; render(); };
    document.querySelector(".modes").appendChild(b); });
  function legend() {
    const L = $("legend");
    L.classList.toggle("wide", mode === "terrain" || mode === "goods" || mode === "diplomacy");
    if (mode === "terrain") L.innerHTML = `<b class="lh">What the land does</b>` + Object.entries(TERRAIN).map(([t, c]) => `<div class="trow"><i style="background:${c}"></i>
      <div><b>${PaxMap.TERRAIN_ICON[t]} ${cap(t)}</b><small>${PaxMap.terrainLines(S, t).join(" · ")}</small></div></div>`).join("");
    else if (mode === "development") L.innerHTML = `Development<div class="ramp" style="background:linear-gradient(90deg,${[1, 4, 6, 8, 10].map(devColor).join(",")})"></div>`;
    else if (mode === "faith") {
      const count = {}; V.provinces.forEach((p) => { if (p.faith) count[p.faith] = (count[p.faith] || 0) + 1; });
      const mine = V.me.provinces.filter((id) => prov(pIndex[id]).faith !== V.me.faith).length;
      L.innerHTML = `<b class="lh">Faiths of Europe</b>` + Object.entries(PaxMap.FAITH_COLOR).map(([f, c]) => `<div class="row"><i style="background:${c}"></i>${PaxMap.FAITH_ICON[f]} ${cap(f)} <span class="sub">${count[f] || 0}</span></div>`).join("")
        + `<p class="sub">${mine ? `${mine} of your provinces keep another faith: each yields ${Math.round(R.faithPenalty * (1 - (V.me.modifiers.faith_tolerance || 0)) * 100)}% less until converted.` : "All your provinces share your faith."}</p>`;
    }
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
      <div class="row"><span style="color:#8a6420">★</span> Capital <span style="margin-left:8px">${PaxMap.HELM("#7a5a3a", 14)}</span> General (a pip per point of skill)</div>
      <div class="row"><i style="border:2px solid #3f8f55"></i>March <i style="border:2px solid #b8392b"></i>Attack</div>`;
  }
  function seaTip(z, evt) {
    const sea = SEAS[z], sv = seaView(sea.id) || {fleets: {}, power: {}};
    const lines = Object.entries(sv.fleets).map(([n, ships]) => `<span>${esc(nameOf(n))}</span><b>${SHIPS.filter((k) => ships[k]).map((k) => `${SICON[k]}${ships[k]}`).join(" ")} <small>· ${(sv.power[n] || 0).toFixed(1)}</small></b>`).join("");
    let extra = "Click to see its fleets";
    if (pickedSea >= 0 && pickedSea !== z && SEAS[pickedSea].neighbors.includes(sea.id) && SHIPS.some((k) => fleetAfter(SEAS[pickedSea].id)[k])) extra = "Right-click to sail your fleet here";
    $("tip").innerHTML = `<b class="t">${WATER[sea.water][0]} ${esc(sea.name)}</b><div class="kv">${lines || "<span>Fleets</span><b>none</b>"}</div><div class="hint">${extra}</div>`;
    const tip = $("tip"), r = $("mapwrap").getBoundingClientRect();
    let x = evt.clientX - r.left + 16, y = evt.clientY - r.top + 16;
    if (x + 280 > r.width) x -= 300; if (y + 160 > r.height) y -= 180;
    tip.style.left = x + "px"; tip.style.top = y + "px"; tip.style.display = "block";
  }
  function tooltip(i, evt) {
    const p = prov(i), out = unbundle(p.output_per_turn).map((v, k) => `${RES[k][2]} ${v}`).join("&ensp;");
    let extra = mode === "terrain" ? `${PaxMap.TERRAIN_ICON[P[i].terrain]} ${cap(P[i].terrain)}: ${PaxMap.terrainLines(S, P[i].terrain).join(" · ")}` : "Click to select";
    if (picked >= 0 && owned(picked) && i !== picked) {
      const t = targetsFrom(picked).find(([j]) => j === i), n = KINDS.reduce((sum, k) => sum + force(picked)[k], 0);
      if (t && t[1] === "move") extra = t[2] !== undefined ? `Right-click to ship ${Math.min(n, t[2])} regiments here by sea` : `Right-click to march ${n} regiments here`;
      if (t && t[1] === "attack") { const c = odds(picked, i), s = prov(i).siege_by;
        const verb = s === G.human ? "send them to the siege lines" : s ? "break the siege" : "attack";
        const joined = orders.filter((o) => o.type === "attack" && pIndex[o.target] === i && pIndex[o.origin] !== picked).reduce((a, o) => a + o.regiments, 0);
        extra = `Right-click to ${t[2] !== undefined ? "land" : verb} with ${t[2] !== undefined ? Math.min(n, t[2]) : n}${joined ? ` (with the ${joined} already sent: one battle)` : ""}${c !== null ? `: ${Math.round(c * 100)}% to win` : ""}`; }
    }
    $("tip").innerHTML = `<b class="t">${esc(P[i].name)}</b><div class="kv">
      <span>Owner</span><b>${p.owner ? esc(nameOf(p.owner)) : "Independent"}</b>
      <span>Development</span><b>${p.development}${p.settlement ? ` <small>· ${esc(p.settlement.toLowerCase())}</small>` : ""}</b>
      ${p.focus ? `<span>Focus</span><b>${(FOCI.find(([k]) => k === p.focus) || [])[1] || ""} ${esc(cap(p.focus))} +${Math.round((p.focus_bonus || 0) * 100)}%</b>` : ""}${p.faith ? `<span>Faith</span><b>${PaxMap.FAITH_ICON[p.faith]} ${cap(p.faith)}</b>` : ""}<span>Regiments</span><b>${p.troops === null ? "hidden" : `${p.troops}${p.army && p.troops ? ` <small>${KINDS.filter((k) => p.army[k]).map((k) => `${UICON[k]}${p.army[k]}`).join(" ")}</small>` : ""}`}</b>
      ${M[p.id] && p.monument !== null ? `<span>Monument</span><b>${esc(M[p.id].name)} ${p.monument ? "★".repeat(p.monument) : "(a site)"}</b>` : ""}
      ${p.general ? `<span>General</span><b>${esc(p.general.name)} ${stars(p.general.skill)}</b>` : ""}
      ${p.fort ? `<span>Walls</span><b>🏰 ${p.fort} level${p.fort > 1 ? "s" : ""}: must be besieged</b>` : ""}
      ${p.siege_by ? `<span>Siege</span><b>🏰 ${p.siege_by === G.human ? "yours" : esc(nameOf(p.siege_by))}: ${p.siege_progress}%${p.besiegers !== null ? `, ${p.besiegers} regiments` : ""}</b>` : ""}
      ${owned(i) && troopsAfter(i) !== (p.troops || 0) ? `<span>After orders</span><b>${troopsAfter(i)} regiments</b>` : ""}
      <span>Per year</span><b class="num">${out}</b></div><div class="hint">${extra}</div>`;
    const tip = $("tip"), r = $("mapwrap").getBoundingClientRect();
    let x = evt.clientX - r.left + 16, y = evt.clientY - r.top + 16;
    if (x + 280 > r.width) x -= 300; if (y + 160 > r.height) y -= 180;
    tip.style.left = x + "px"; tip.style.top = y + "px"; tip.style.display = "block";
  }

  // ------------------------------------------------------------------ render
  // At a table, the orders being drafted travel to the server as they change: if the clock (or
  // the others) end the year before "End the year", they are carried out instead of lost.
  let draftSent = "[]";
  function draft() {
    if (!TABLE || G.finished) return;
    clearTimeout(draft.t);
    draft.t = setTimeout(async () => {
      const body = JSON.stringify(orders);
      if (body === draftSent) return;
      try { const r = await api("/draft", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({actions: orders})});
        if (r.ok) draftSent = body; } catch {}
    }, 1200);
  }
  // Offers from other courts, at the top of the map until answered or put off: easy to miss in
  // the Correspondence alone.
  const PROPOSAL_ICON = {alliance: "🤝", non_aggression: "📜", peace: "🕊", trade: "⚖", marriage: "💍", coalition: "🛡", call_to_arms: "⚔"};
  const putOff = new Set();
  const unanswered = () => V.proposals_to_answer.filter((p) => !orders.some((o) => o.type === "respond" && o.proposal_id === p.id));
  const PROPOSAL_SHORT = (p) => p.kind === "coalition" ? `a league against ${nameOf(p.enemy)}`
    : p.kind === "call_to_arms" ? `a call to arms against ${nameOf(p.enemy)}`
    : {alliance: "an alliance", non_aggression: "a non-aggression pact", peace: "peace terms", trade: "a trade", marriage: "a royal marriage"}[p.kind] || "a proposal";
  function notices() {
    const box = $("notices");
    // out of the way while a window or a province is open; back when the map is clear
    const open = G.finished || panelOpen || picked >= 0 ? [] : unanswered().filter((p) => !putOff.has(p.id));
    box.innerHTML = open.length ? `<div class="notice"><span class="ic">📜</span><div>
        <b>${open.length === 1 ? "A letter awaits" : `${open.length} letters await`} your answer</b>
        <ul>${open.slice(0, 4).map((p) => `<li>${PROPOSAL_ICON[p.kind] || "📜"} ${esc(nameOf(p.sender))}: ${esc(PROPOSAL_SHORT(p))}</li>`).join("")}${open.length > 4 ? `<li>…and ${open.length - 4} more</li>` : ""}</ul>
        <div class="row"><button class="btn" data-answer>Read and answer</button><button class="btn quiet" data-putoff>Later</button></div></div></div>` : "";
    box.querySelectorAll("[data-answer]").forEach((b) => b.onclick = () => { pinned = true; openOffice("letters"); });
    box.querySelectorAll("[data-putoff]").forEach((b) => b.onclick = () => { open.forEach((p) => putOff.add(p.id)); notices(); });
    const letters = document.querySelector('#rail [data-tab="letters"]');
    if (letters) letters.classList.toggle("urgent", unanswered().length > 0);
    const count = unanswered().length;
    if (count > (notices.seen ?? count)) J.play("letter");
    notices.seen = count;
  }
  function render() {
    draft();
    firstSteps();
    $("endturn").classList.toggle("ready", orders.length > 0 && !G.submitted && !G.finished);
    const cb = $("crisisbadge"), c = V.crisis;
    cb.hidden = !c;
    if (c) { cb.innerHTML = `<span class="ic">${CRISIS_ICON[c.kind] || "☠"}</span><span>${esc(c.title)}<small>${c.first_year}–${c.last_year}</small></span>`;
      cb.setAttribute("data-tip", `<h5>${CRISIS_ICON[c.kind] || ""} ${esc(c.title)}, ${c.first_year} to ${c.last_year}</h5><div>${esc(c.text)}</div><div class="dim">${esc(CRISIS_EFFECT[c.kind] || "")}</div>`); }
    notices();
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
    map.setArrows([...orders.filter((o) => o.type === "move" || o.type === "attack").map((o) => [pIndex[o.origin], pIndex[o.target], o.type, o.regiments]),
      ...orders.filter((o) => o.type === "sail_fleet").map((o) => [ZI[o.origin], ZI[o.target], "sail", Object.values(o.ships).reduce((a, b) => a + b, 0)])]);
    map.pickSea(pickedSea, pickedSea >= 0 ? SEAS[pickedSea].neighbors.map((t) => ZI[t]) : []);
    if (pickedSea >= 0) { seaDeed(); map.setTargets([]); } else deed();
    office(); ordersBox(); legend();
  }

  $("endturn").onclick = endTurn;
  document.addEventListener("visibilitychange", () => { if (!document.hidden) document.title = "Pax Agentica"; });
  // A first-year guide, shown once and on demand
  const GUIDE = [
    ["👑 Your realm", "You rule one great power of Europe in 1500. Across the top: what your treasury holds and what it gains a year. The <b>Economy</b> office shows where every ducat comes from and goes, your taxes and your materials."],
    ["🏛 Your provinces", "Click one of your provinces to open its deed: <b>develop</b> it (more output and score), raise its <b>workings</b> (its mine, vineyard or looms) and <b>build</b> in its slots. Some buildings eat materials every year; without them they stand idle."],
    ["⚔ War", "Declare war in the <b>Envoys</b> office; armies need a year to mobilise. Select a province with regiments, then right-click (or use the March buttons on a phone) to march or attack. Taken land is occupied: only a <b>peace treaty</b> moves borders, and your war score sets what you may demand."],
    ["🤝 Diplomacy", "In <b>Envoys</b>, write to every court and attach proposals: alliances, pacts, royal marriages, trade, leagues against a feared conqueror. Courts marked 👤 are other players; the rest are bots that answer and remember. Conquest breeds <b>infamy</b>, and Europe may league against you."],
    ["📜 The year", "Queue your orders, then <b>End the year</b>: every ruler's orders are carried out together. Your <b>Crown</b> office holds your missions, your court and patronage. After the last year, the highest standing (development plus half your prestige) wins."],
  ];
  function guide(step = 0) {
    const [title, text] = GUIDE[step];
    $("sheet").innerHTML = `<h2 id="modaltitle">${title}</h2><p>${text}</p>
      <div class="row"><span class="sub">${step + 1} of ${GUIDE.length}</span>
      ${step > 0 ? `<button class="btn" id="gprev">Back</button>` : ""}
      <button class="btn" id="gnext">${step + 1 < GUIDE.length ? "Next" : "To the throne"}</button>
      <button class="btn quiet" id="gsteps" title="The guided first steps, from the beginning">First steps again</button></div>`;
    $("modal").classList.add("open");
    if (step > 0) $("gprev").onclick = () => guide(step - 1);
    $("gsteps").onclick = () => { stepsSave({}); $("modal").classList.remove("open"); firstSteps(); };
    $("gnext").onclick = () => { if (step + 1 < GUIDE.length) guide(step + 1); else { $("modal").classList.remove("open"); eventSheet(); } };
  }
  $("guide").onclick = () => guide(0);
  $("feedback").onclick = () => {
    $("sheet").innerHTML = `<h2 id="modaltitle">Tell us what to fix</h2>
      <p class="sub">A bug, something unclear, an idea. It is read by the people making the game, with the year and your realm attached.</p>
      <textarea id="fbtext" maxlength="2000" style="width:100%;min-height:120px;box-sizing:border-box"></textarea>
      <div class="row"><button class="btn" id="fbsend">Send</button><button class="btn" id="fbclose">Close</button></div>`;
    $("modal").classList.add("open");
    $("fbclose").onclick = () => $("modal").classList.remove("open");
    $("fbsend").onclick = async () => {
      const text = $("fbtext").value.trim(); if (!text) return;
      const r = await fetch("/api/feedback", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text, table: TABLE, nation: G.human, year: V.year})}).catch(() => null);
      $("modal").classList.remove("open"); flash(r && r.ok ? "Thank you: your note is on its way." : "The note could not be sent.");
    };
  };
  $("zin").innerHTML = I("zoom-in"); $("zout").innerHTML = I("zoom-out"); $("zhome").innerHTML = I("house");
  $("guide").innerHTML = I("circle-help"); $("feedback").innerHTML = I("message-square-text");
  const soundIcon = () => { $("soundbtn").innerHTML = I(J.muted() ? "volume-x" : "volume-2"); $("soundbtn").setAttribute("aria-pressed", String(!J.muted())); };
  soundIcon();
  $("soundbtn").onclick = () => { J.setMuted(!J.muted()); soundIcon(); musicIcon(); J.play("click"); };
  const musicIcon = () => { const on = J.music && J.music() && !J.muted(); $("musicbtn").innerHTML = I("music"); $("musicbtn").classList.toggle("off", !on); $("musicbtn").setAttribute("aria-pressed", String(on)); };
  musicIcon();
  $("musicbtn").onclick = () => {
    if (J.muted()) { J.setMuted(false); soundIcon(); J.setMusic(true); } else J.setMusic(!J.music());
    musicIcon(); };
  // ------------------------------------------------------------------ options
  // Sound and music with their volumes, the size of the interface, how much the years animate,
  // and the guides: kept by this browser.
  const O = window.PaxOptions || {get: () => null, set() {}, speed: () => 1};
  const applyScale = () => { const s = +O.get("scale") || 1; document.documentElement.style.zoom = s === 1 ? "" : String(s); };
  applyScale();
  function optionsSheet() {
    const vol = J.volumes ? J.volumes() : {music: .7, sfx: .8}, scale = +O.get("scale") || 1, anim = O.get("anim") || "full";
    const seg = (name, value, choices) => `<div class="seg" role="radiogroup" data-opt="${name}">${choices.map(([v, label]) =>
      `<button type="button" role="radio" aria-checked="${String(v) === String(value)}" class="${String(v) === String(value) ? "on" : ""}" data-v="${v}">${label}</button>`).join("")}</div>`;
    $("sheet").innerHTML = `<h2 id="modaltitle">${I("settings")} Options</h2>
      <section class="opts">
        <h3>Sound</h3>
        <div class="orow"><label><input type="checkbox" id="o-music" ${J.music && J.music() ? "checked" : ""}> Music of the age</label>
          <input type="range" id="o-mvol" min="0" max="100" value="${Math.round(vol.music * 100)}" aria-label="Music volume"></div>
        <div class="orow"><label><input type="checkbox" id="o-sfx" ${J.muted() ? "" : "checked"}> Sounds</label>
          <input type="range" id="o-svol" min="0" max="100" value="${Math.round(vol.sfx * 100)}" aria-label="Sound volume"></div>
        <p class="sub">The music is improvised anew each time over the grounds of the age; it turns grave in war and in a crisis.</p>
        <h3>Display</h3>
        <div class="orow"><span>Size of the interface</span>${seg("scale", scale, [[0.85, "Small"], [1, "Normal"], [1.15, "Large"], [1.3, "Larger"]])}</div>
        <div class="orow"><span>Animations</span>${seg("anim", anim, [["full", "Full"], ["quick", "Quick"], ["off", "Off"]])}</div>
        ${window.PaxI18n ? `<div class="orow"><span>Language</span><select class="field" id="o-lang" aria-label="Language" translate="no">${Object.entries(PaxI18n.LANGS).map(([k, v]) =>
          `<option value="${k}" ${k === PaxI18n.lang ? "selected" : ""}>${v}</option>`).join("")}</select></div>` : ""}
        <p class="sub">Quick halves the year's marches and cards; Off skips them, for a faster game.</p>
        <h3>Help</h3>
        <div class="orow"><label><input type="checkbox" id="o-steps" ${stepsKept().hidden ? "" : "checked"}> Show the "First steps" guide</label>
          <button class="btn" type="button" id="o-guide">How to play</button></div>
      </section>
      <button class="btn" id="closemodal">Done</button>`;
    $("modal").classList.add("open");
    $("o-music").onchange = (e) => { if (e.target.checked && J.muted()) J.setMuted(false); J.setMusic(e.target.checked); musicIcon(); soundIcon(); };
    $("o-sfx").onchange = (e) => { J.setMuted(!e.target.checked); soundIcon(); musicIcon(); };
    $("o-mvol").oninput = (e) => J.setVolumes?.({music: e.target.value / 100});
    $("o-svol").oninput = (e) => J.setVolumes?.({sfx: e.target.value / 100});
    $("o-svol").onchange = () => J.play("coins");
    document.querySelectorAll("#sheet .seg").forEach((g) => g.onclick = (e) => {
      const b = e.target.closest("button[data-v]"); if (!b) return;
      const v = g.dataset.opt === "scale" ? +b.dataset.v : b.dataset.v;
      O.set(g.dataset.opt, v); if (g.dataset.opt === "scale") applyScale();
      g.querySelectorAll("button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", String(x === b)); });
    });
    $("o-steps").onchange = (e) => { const s = stepsKept(); s.hidden = !e.target.checked; if (e.target.checked) s.finished = false; stepsSave(s); firstSteps(); };
    $("o-guide").onclick = () => { $("modal").classList.remove("open"); guide(0); };
    if ($("o-lang")) $("o-lang").onchange = (e) => PaxI18n.setLang(e.target.value); // the page reloads in the new language
    $("closemodal").onclick = () => $("modal").classList.remove("open");
  }
  $("optionsbtn").innerHTML = I("settings");
  $("optionsbtn").onclick = optionsSheet;
  $("rail").addEventListener("click", () => J.play("click"));
  $("ordersbtn").onclick = () => $("ordersbtn").parentElement.classList.toggle("open");
  // the rich tooltip: any element with data-tip shows its HTML next to the pointer
  const RT = $("richtip");
  document.addEventListener("mouseover", (e) => { const el = e.target.closest && e.target.closest("[data-tip]");
    if (!el) { RT.style.display = "none"; return; } RT.innerHTML = el.getAttribute("data-tip"); RT.style.display = "block"; });
  document.addEventListener("mousemove", (e) => { if (RT.style.display !== "block") return;
    const w = RT.offsetWidth, h = RT.offsetHeight;
    RT.style.left = Math.min(innerWidth - w - 8, e.clientX + 14) + "px"; RT.style.top = (e.clientY + 18 + h > innerHeight ? e.clientY - h - 12 : e.clientY + 18) + "px"; });
  document.addEventListener("mouseleave", () => (RT.style.display = "none"));
  $("zin").onclick = () => map.zoomAt(1 / 1.4); $("zout").onclick = () => map.zoomAt(1.4);
  $("zhome").onclick = () => map.home(V.me.provinces.map((p) => pIndex[p]));
  window.addEventListener("keydown", (e) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
    if (e.key >= "1" && e.key <= String(MODES.length)) { mode = MODES[+e.key - 1][0]; render(); }
    if (e.key === "Escape") { if ($("modal").classList.contains("open")) $("modal").classList.remove("open"); else if (panelOpen) closeOffice(); else { picked = -1; if (mode === "diplomacy") focus = -1; render(); } }
  });
  await load();
  requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add("ready")));
})();
