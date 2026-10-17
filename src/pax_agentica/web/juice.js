// Juice: the sounds and small motions that make a year feel like a year. Every sound is made
// here with the Web Audio API, from oscillators and noise: no files to download or license.
// Everything respects the player's mute switch and their "reduce motion" setting.
"use strict";
window.PaxJuice = (() => {
  const still = () => window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const KEY = "pax-sound";
  let ctx = null, master = null;
  let muted = (() => { try { return localStorage.getItem(KEY) === "off"; } catch { return false; } })();

  function audio() { // created on the first gesture: browsers refuse sound before one
    if (muted) return null;
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC(); master = ctx.createGain(); master.gain.value = 0.32; master.connect(ctx.destination);
    }
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }
  // one note: an oscillator shaped by a quick attack and an exponential fall
  function tone(freq, {at = 0, dur = 0.25, type = "sine", gain = 0.5, slide = 0} = {}) {
    const a = audio(); if (!a) return;
    const t = a.currentTime + at, o = a.createOscillator(), g = a.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, t);
    if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, freq * slide), t + dur);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain, t + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g); g.connect(master); o.start(t); o.stop(t + dur + 0.05);
  }
  // a burst of filtered noise: drums, gunpowder, the scratch of a quill
  function noise({at = 0, dur = 0.3, freq = 900, q = 0.8, gain = 0.6, type = "lowpass"} = {}) {
    const a = audio(); if (!a) return;
    const t = a.currentTime + at, n = Math.ceil(a.sampleRate * dur), buf = a.createBuffer(1, n, a.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 2);
    const src = a.createBufferSource(), f = a.createBiquadFilter(), g = a.createGain();
    src.buffer = buf; f.type = type; f.frequency.value = freq; f.Q.value = q; g.gain.value = gain;
    src.connect(f); f.connect(g); g.connect(master); src.start(t);
  }
  const bell = (f, at = 0, gain = 0.35) => { tone(f, {at, dur: 2.2, gain}); tone(f * 2.01, {at, dur: 1.4, gain: gain * 0.45}); tone(f * 3.02, {at, dur: 0.9, gain: gain * 0.2}); };
  const SOUNDS = {
    click: () => tone(1250, {dur: 0.05, type: "triangle", gain: 0.12}),
    order: () => { tone(660, {dur: 0.09, type: "triangle", gain: 0.22}); tone(990, {at: 0.06, dur: 0.12, type: "triangle", gain: 0.18}); },
    unorder: () => tone(520, {dur: 0.12, type: "triangle", gain: 0.18, slide: 0.7}),
    coins: () => [0, 0.07, 0.15].forEach((at, k) => tone(2100 + k * 260, {at, dur: 0.16, type: "square", gain: 0.05})),
    build: () => { noise({dur: 0.08, freq: 2600, type: "bandpass", gain: 0.5}); noise({at: 0.16, dur: 0.08, freq: 2400, type: "bandpass", gain: 0.45}); },
    year: () => { bell(392, 0, 0.3); bell(523.25, 0.45, 0.24); },
    battle: () => { noise({dur: 0.7, freq: 180, gain: 1.1}); tone(70, {dur: 0.6, gain: 0.5, slide: 0.5}); noise({at: 0.22, dur: 0.4, freq: 300, gain: 0.6}); },
    triumph: () => [523.25, 659.25, 783.99, 1046.5].forEach((f, k) => { tone(f, {at: k * 0.13, dur: 0.5, type: "sawtooth", gain: 0.07}); tone(f, {at: k * 0.13, dur: 0.6, type: "triangle", gain: 0.2}); }),
    loss: () => [392, 349.23, 311.13].forEach((f, k) => tone(f, {at: k * 0.22, dur: 0.6, type: "triangle", gain: 0.2})),
    war: () => { [0, 0.18, 0.36, 0.54].forEach((at) => noise({at, dur: 0.25, freq: 140, gain: 0.9})); tone(98, {at: 0.54, dur: 0.9, type: "sawtooth", gain: 0.08}); },
    peace: () => { noise({dur: 0.12, freq: 400, gain: 0.7}); bell(659.25, 0.12, 0.2); bell(880, 0.3, 0.14); },
    letter: () => { tone(880, {dur: 0.18, gain: 0.18}); tone(1174.7, {at: 0.12, dur: 0.3, gain: 0.16}); },
    seal: () => { noise({dur: 0.1, freq: 500, gain: 0.8}); tone(196, {dur: 0.25, gain: 0.3, slide: 0.8}); },
  };
  function play(name) { if (!muted && SOUNDS[name]) try { SOUNDS[name](); } catch {} }
  function setMuted(m) { muted = m; try { localStorage.setItem(KEY, m ? "off" : "on"); } catch {} if (m && ctx) ctx.suspend(); }

  // numbers that count up (or down) to their new value
  function countTo(el, to, ms = 900) {
    if (!el) return;
    const from = +(el.dataset.v ?? el.textContent.replace(/[^\d-]/g, "")) || 0;
    el.dataset.v = to;
    if (still() || from === to) { el.textContent = to; return; }
    const t0 = performance.now();
    const step = (now) => { const f = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - f, 3);
      el.textContent = Math.round(from + (to - from) * e); if (f < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }
  // a "+23" that rises from an element and fades
  function floatText(anchor, text, cls = "") {
    if (!anchor || still()) return;
    const r = anchor.getBoundingClientRect(), f = document.createElement("div");
    f.className = `floater ${cls}`; f.textContent = text;
    f.style.left = `${r.left + r.width / 2}px`; f.style.top = `${r.top + r.height * 0.2}px`;
    document.body.appendChild(f); setTimeout(() => f.remove(), 1700);
  }
  // a triumph across the screen, with gold and banner colours falling
  function celebrate(title, subtitle = "", colors = ["#ecd08c", "#c49a52", "#fff3cf"]) {
    const box = document.createElement("div");
    box.className = "triumph";
    box.innerHTML = `<div class="tcard"><div class="tbig"></div><div class="tsub"></div></div>`;
    box.querySelector(".tbig").textContent = title; box.querySelector(".tsub").textContent = subtitle;
    if (!still()) for (let i = 0; i < 70; i++) {
      const s = document.createElement("i");
      s.style.left = `${Math.random() * 100}%`; s.style.background = colors[i % colors.length];
      s.style.animationDelay = `${Math.random() * 0.6}s`; s.style.animationDuration = `${1.6 + Math.random() * 1.4}s`;
      s.style.setProperty("--drift", `${(Math.random() - 0.5) * 160}px`); s.style.setProperty("--spin", `${(Math.random() - 0.5) * 900}deg`);
      box.appendChild(s);
    }
    document.body.appendChild(box);
    const go = () => { box.classList.add("out"); setTimeout(() => box.remove(), 450); };
    box.onclick = go; setTimeout(go, 3200);
  }
  // the turn of the year: the new date written large, for a breath
  function yearCard(year, line = "") {
    return new Promise((done) => {
      if (still()) return done();
      const card = document.createElement("div");
      card.className = "yearcard"; card.innerHTML = `<div><small>Anno Domini</small><b></b><span></span></div>`;
      card.querySelector("b").textContent = year; card.querySelector("span").textContent = line;
      document.body.appendChild(card);
      setTimeout(() => { card.classList.add("out"); setTimeout(() => { card.remove(); done(); }, 380); }, 1250);
      card.onclick = () => { card.classList.add("out"); setTimeout(() => { card.remove(); done(); }, 200); };
    });
  }
  // a red (or gold) breath at the edges of the screen
  function vignette(cls = "war") {
    if (still()) return;
    const v = document.createElement("div"); v.className = `vignette ${cls}`;
    document.body.appendChild(v); setTimeout(() => v.remove(), 1300);
  }
  return {play, muted: () => muted, setMuted, countTo, floatText, celebrate, yearCard, vignette, still};
})();
