// The press kit's common ground: the map of a game of bots, year by year, for the capsule
// painter (press.html) and the trailer (trailer.html). Served by `pax press` only.
"use strict";
window.PaxPress = (() => {
  async function boot(svg) {
    const q = new URLSearchParams(location.search), args = new URLSearchParams();
    for (const k of ["seed", "turns"]) if (q.get(k)) args.set(k, q.get(k));
    const [S, R] = await Promise.all([fetch("/api/static").then((r) => r.json()), fetch(`/api/reel?${args}`).then((r) => r.json())]);
    const P = S.provinces, N = S.nations;
    const pIndex = Object.fromEntries(P.map((p, i) => [p.id, i])), nIndex = Object.fromEntries(N.map((n, i) => [n.id, i]));
    const map = PaxMap.create(svg, S, {});
    const order = R.provinces.map((id) => pIndex[id]);
    const color = (nid) => (nid in nIndex ? N[nIndex[nid]].color : "#9a8f78");
    const name = (nid) => (nid in nIndex ? N[nIndex[nid]].name : nid);
    function ownersAt(i) {
      const owner = new Array(P.length).fill(-1);
      R.owners[i].forEach((nid, k) => { if (order[k] !== undefined) owner[order[k]] = nid in nIndex ? nIndex[nid] : -1; });
      return owner;
    }
    // the world as the map paints it, with nothing on it but borders and banners
    function worldAt(i) {
      const owner = ownersAt(i), zero = owner.map(() => 0);
      return {mode: "political", focus: -1, relations: {wars: [], allies: [], pacts: []}, diplo: null, alive: N.map((_, k) => owner.includes(k)),
        faiths: P.map((p) => p.faith), workings: zero, capitals: new Set(), generals: new Map(), owner, controller: owner.map(() => -1),
        troops: zero, dev: zero, planned: [], forts: zero, sieges: owner.map(() => null), buildings: owner.map(() => []), events: []};
    }
    // the armies that marched in year i (from the map of year i-1 to that of year i)
    const marchesAt = (i) => (R.marches[i - 1] || []).filter((m) => m.from in pIndex && m.to in pIndex)
      .map((m) => ({from: pIndex[m.from], to: pIndex[m.to], color: color(m.nation), fight: m.fight, won: m.won, took: !!m.took, takerColor: color(m.took)}));
    // the view that frames these provinces, as the map's own "home" would
    function frame(ids, minW = S.map.width / 3.2) {
      const set = ids.length ? ids : P.map((_, i) => i), xs = set.map((i) => P[i].x), ys = set.map((i) => P[i].y);
      const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
      const w = Math.min(Math.min(S.map.width, S.map.height * map.aspect()), Math.max(minW, (Math.max(...xs) - Math.min(...xs)) * 2.2));
      return {x: cx - w / 2, y: cy - w / map.aspect() / 2, w};
    }
    return {S, R, P, N, map, pIndex, nIndex, color, name, worldAt, marchesAt, frame};
  }
  return {boot};
})();
