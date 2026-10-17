// Translations. The game is written in English, and so is everything the engine says (the AI
// rulers read it). This translates what the page shows, as it shows it: every text node and the
// titles, labels and tips of every element, by a dictionary of whole phrases and of patterns
// with holes ("{0} moves {1} regiments from {2} to {3}"), whose holes are translated in turn
// (names of provinces, crowns, works). What players write (letters, proclamations, the names they
// choose) sits inside translate="no" and is left as it is.
//
// The dictionaries are web/i18n/<lang>.json: {"phrase or pattern": "translation"}. A phrase not in
// them stays in English; PaxI18n.missing() lists the ones seen, to translate next.
"use strict";
window.PaxI18n = (() => {
  const KEY = "pax-lang";
  const LANGS = {en: "English", es: "Español"};
  const chosen = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
  const browser = () => (navigator.language || "en").slice(0, 2);
  const lang = (() => { const c = chosen(); return LANGS[c] ? c : LANGS[browser()] ? browser() : "en"; })();
  let exact = new Map(), patterns = [], ready = Promise.resolve();
  const cache = new Map(), seen = new Set(), outputs = new Set(); // outputs: what we wrote, never to translate again
  const ATTRS = ["title", "aria-label", "placeholder", "alt", "data-tip"];

  // "{0} moves {1} regiments" -> /^(.+?) moves (.+?) regiments$/ with the holes' order
  function compile(en, out) {
    const holes = [], parts = en.split(/(\{\d+\})/);
    const src = parts.map((p) => { const m = p.match(/^\{(\d+)\}$/); if (m) { holes.push(+m[1]); return "(.*?)"; }
      return p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }).join("");
    const literal = parts.filter((p) => !/^\{\d+\}$/.test(p)).sort((a, b) => b.length - a.length)[0] || "";
    // holes with only a space between them ("{1} {2}"): where to cut is decided by what translates
    const joins = []; for (let k = 1; k < parts.length - 1; k += 2) if (parts[k + 1] === " " && /^\{\d+\}$/.test(parts[k + 2] || "")) joins.push((k - 1) / 2);
    return {re: new RegExp(`^${src}$`, "s"), holes, out, literal, joins, weight: literal.length};
  }
  async function load() {
    if (lang === "en") return;
    try {
      const dict = await fetch(`/i18n/${lang}.json`).then((r) => r.json());
      for (const [en, tr] of Object.entries(dict)) {
        if (/\{\d+\}/.test(en)) patterns.push(compile(en, tr)); else exact.set(en, tr);
      }
      // the same words as the page also writes them: "FRANCE" on the map, "the nobles grumble" in
      // a sentence, "Farm estates" at the head of a line
      const first = (s, f) => s.charAt(0)[f]() + s.slice(1);
      for (const [en, tr] of [...exact]) {
        const up = en.toUpperCase(), low = first(en, "toLowerCase"), cap = first(en, "toUpperCase");
        if (en.length <= 40 && !exact.has(up)) exact.set(up, tr.toUpperCase());
        if (!exact.has(low)) exact.set(low, first(tr, "toLowerCase"));
        if (!exact.has(cap)) exact.set(cap, first(tr, "toUpperCase"));
      }
      patterns.sort((a, b) => b.weight - a.weight); // the most specific first
    } catch { exact = new Map(); patterns = []; }
  }
  // a proper name the dictionary leaves as it is ("Louis de La Trémoille"): short, capitalised words
  const isName = (v) => v.length < 48 && /^\p{Lu}[\p{L}'’.\- ]*$/u.test(v) && v.split(" ").length <= 5;
  // one phrase, without its surrounding spaces; null when there is nothing to do
  const plain = (v) => !/[A-Za-z]{2}/.test(v);
  const known = (v, depth) => plain(v) || isName(v.trim()) || whole(v.trim(), depth + 1) !== null;
  function phrase(s, depth = 0) {
    if (cache.has(s)) return cache.get(s);
    let out = exact.get(s);
    if (out === undefined && depth < 4) for (const p of patterns) {
      if (p.literal && !s.includes(p.literal)) continue;
      const m = s.match(p.re); if (!m) continue;
      let vals = p.holes.map((_, k) => m[k + 1]);
      // two holes side by side: try every cut at a space, keep the one whose halves both translate
      for (const j of p.joins) {
        if (known(vals[j], depth) && known(vals[j + 1], depth)) continue;
        const both = `${vals[j]} ${vals[j + 1]}`, words = both.split(" ");
        for (let c = 1; c < words.length; c++) {
          const a = words.slice(0, c).join(" "), b = words.slice(c).join(" ");
          if (known(a, depth) && known(b, depth)) { vals = [...vals]; vals[j] = a; vals[j + 1] = b; break; }
        }
      }
      // a pattern with little fixed text ("{0} and {1}") only joins pieces it can translate too:
      // else it would cut a sentence it does not know in two and leave it half in English
      if (p.weight < 9 && !vals.every((v) => v === "" || known(v, depth))) continue;
      const byHole = {};
      p.holes.forEach((h, k) => { const v = vals[k]; byHole[h] = v.trim() ? (whole(v.trim(), depth + 1) ?? v) : v; });
      out = p.out.replace(/\{(\d+)\}/g, (_, h) => byHole[h] ?? "");
      break;
    }
    if (out === undefined) out = null;
    cache.set(s, out);
    return out;
  }
  // a phrase as it stands: itself, or in quotes, or with a full stop, or with an icon or a mark
  function whole(key, depth = 0) {
    // an icon in front goes first: "⌛ coalition proposal #4..." is a sentence behind an icon
    const icon = key.match(/^([^\p{L}\p{N}"“«(¿¡'+\-−]+)(\p{L}[\s\S]*)$/u);
    if (icon) { const core = phrase(icon[2], depth); if (core !== null) return icon[1] + core; }
    let tr = phrase(key, depth);
    if (tr === null) {
      const q = key.match(/^([“«"])([\s\S]+)([”»"])$/) || key.match(/^()([\s\S]+?)(\.)$/);
      if (q) { const core = phrase(q[2], depth); if (core !== null) tr = (q[1] === '"' || q[1] === "“" ? "«" : q[1]) + core + (q[3] === '"' || q[3] === "”" ? "»" : q[3]); }
    }
    if (tr === null) {
      const parts = key.match(/^([^\p{L}\p{N}"“«(¿¡'+\-−]*)([\s\S]*?)(\s*[^\p{L}\p{N}\s.,:;!?)\]»”'%]*)$/u);
      if (parts && (parts[1] || parts[3]) && parts[2]) { const core = phrase(parts[2], depth); if (core !== null) tr = parts[1] + core + parts[3]; }
    }
    if (tr === null && depth === 0 && /[.!?] \S/.test(key)) { // a paragraph: sentence by sentence
      const parts = key.split(/(?<=[.!?])\s+(?=[\p{Lu}"“«])/u);
      if (parts.length > 1) { const done = parts.map((s) => whole(s, 1)); if (done.some((s) => s !== null)) tr = done.map((s, k) => s ?? parts[k]).join(" "); }
    }
    return tr;
  }
  // a text as it stands in the page: keep its spaces, translate what is between them
  function t(text, params) {
    let s = String(text);
    if (params) s = s.replace(/\{(\w+)\}/g, (_, k) => (k in params ? params[k] : `{${k}}`));
    if (lang === "en") return s;
    const m = s.match(/^(\s*)([\s\S]*?)(\s*)$/);
    if (!m[2] || !/[A-Za-z]/.test(m[2])) return s;
    const key = m[2].replace(/\s+/g, " ");
    if (outputs.has(key)) return s;
    const tr = whole(key);
    if (tr === null) { if (/[A-Za-z]{3}/.test(key)) seen.add(key); return s; }
    outputs.add(tr);
    return m[1] + tr + m[3];
  }
  // what players write is left alone: anything inside translate="no", and the text of a textarea;
  // a field's placeholder and title are the game's own words, and are translated
  const skip = (node) => { const el = node.nodeType === 1 ? node : node.parentElement;
    return !el || !!el.closest(node.nodeType === 1 ? "[translate=no], script, style, code" : "[translate=no], script, style, code, textarea"); };
  function walk(root) {
    if (lang === "en" || !root) return;
    if (root.nodeType === 3) { if (!skip(root)) { const v = t(root.nodeValue); if (v !== root.nodeValue) root.nodeValue = v; } return; }
    if (root.nodeType !== 1 || skip(root)) return;
    attrs(root);
    const it = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = it.nextNode(); n; n = it.nextNode()) {
      if (skip(n)) continue;
      if (n.nodeType === 3) { const v = t(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v; } else attrs(n);
    }
  }
  function attrs(el) {
    for (const a of ATTRS) {
      const v = el.getAttribute && el.getAttribute(a);
      if (!v) continue;
      if (a === "data-tip") { // a tip is HTML: translate its text, keep its tags
        const box = document.createElement("div"); box.innerHTML = v; walk(box);
        if (box.innerHTML !== v) el.setAttribute(a, box.innerHTML);
      } else { const tr = t(v); if (tr !== v) el.setAttribute(a, tr); }
    }
  }
  // translate the page as it is, then everything that is added or changed in it
  function watch() {
    if (lang === "en") return;
    document.documentElement.lang = lang;
    walk(document.body);
    const obs = new MutationObserver((list) => {
      for (const r of list) {
        if (r.type === "childList") r.addedNodes.forEach(walk);
        else if (r.type === "characterData") walk(r.target);
        else if (r.type === "attributes" && !skip(r.target)) attrs(r.target);
      }
      obs.takeRecords(); // the changes just made are ours
    });
    obs.observe(document.body, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS});
  }
  function setLang(l) { try { localStorage.setItem(KEY, l); } catch {} location.reload(); }
  ready = load();
  return {lang, LANGS, ready, t, watch, setLang, missing: () => [...seen].sort(),
    name: (s) => (lang === "en" ? s : exact.get(s) ?? s)};
})();
