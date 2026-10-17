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
    omen: () => { bell(130.81, 0, 0.35); bell(123.47, 0.9, 0.3); tone(65.4, {dur: 3, type: "sawtooth", gain: 0.05}); },
  };
  function play(name) { if (!muted && SOUNDS[name]) try { SOUNDS[name](); } catch {} }
  function setMuted(m) { muted = m; try { localStorage.setItem(KEY, m ? "off" : "on"); } catch {} if (m && ctx) ctx.suspend(); if (!m && musicOn) setTimeout(() => startMusic(), 50); }

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
  // an omen: a dark card for a great trouble falling on the age, slower and graver than a triumph
  function omen(icon, title, text) {
    const box = document.createElement("div");
    box.className = "triumph omen";
    box.innerHTML = `<div class="tcard"><div class="oic"></div><div class="tbig"></div><div class="tsub"></div><small>Click to go on</small></div>`;
    box.querySelector(".oic").textContent = icon; box.querySelector(".tbig").textContent = title; box.querySelector(".tsub").textContent = text;
    document.body.appendChild(box);
    const go = () => { box.classList.add("out"); setTimeout(() => box.remove(), 450); };
    box.onclick = go; setTimeout(go, 9000);
  }
  // a red (or gold) breath at the edges of the screen
  function vignette(cls = "war") {
    if (still()) return;
    const v = document.createElement("div"); v.className = `vignette ${cls}`;
    document.body.appendChild(v); setTimeout(() => v.remove(), 1300);
  }
  // ------------------------------------------------------------------ music
  // A lute and a bass, synthesised: the plucked string is the Karplus-Strong algorithm (a burst
  // of noise fed through a short, decaying delay line), rendered once per pitch and cached.
  // The tunes are of the age and in the public domain: "Greensleeves" (anonymous, c. 1580), and
  // pavanes and galliards improvised, as players then did, over two grounds every lutenist
  // knew, the passamezzo antico and the romanesca.
  const MKEY = "pax-music";
  let musicOn = (() => { try { return localStorage.getItem(MKEY) !== "off"; } catch { return true; } })();
  let mbus = null, timer = 0, queueAt = 0, piece = 0;
  const strings = new Map();
  const midi = (m) => 440 * Math.pow(2, (m - 69) / 12);
  function pluck(freq) {
    const a = ctx, key = Math.round(freq * 10);
    if (strings.has(key)) return strings.get(key);
    const rate = a.sampleRate, n = Math.floor(rate * 2.4), period = Math.max(2, Math.round(rate / freq));
    const buf = a.createBuffer(1, n, rate), d = buf.getChannelData(0), line = new Float32Array(period);
    for (let i = 0; i < period; i++) line[i] = Math.random() * 2 - 1;
    let k = 0;
    for (let i = 0; i < n; i++) { const next = (k + 1) % period, v = 0.4975 * (line[k] + line[next]); d[i] = line[k]; line[k] = v; k = next; }
    strings.set(key, buf); return buf;
  }
  function note(m, at, gain = 0.5, pan = 0) {
    if (!ctx || !mbus) return;
    const src = ctx.createBufferSource(), g = ctx.createGain(), f = ctx.createBiquadFilter();
    src.buffer = pluck(midi(m)); f.type = "lowpass"; f.frequency.value = 2600; g.gain.value = gain;
    let out = g;
    if (ctx.createStereoPanner) { const p = ctx.createStereoPanner(); p.pan.value = pan; g.connect(p); out = p; }
    src.connect(f); f.connect(g); out.connect(mbus); src.start(at); src.stop(at + 2.4);
  }
  const N = {C3: 48, D3: 50, E3: 52, F3: 53, G3: 55, A3: 57, Bb3: 58, B3: 59, C4: 60, D4: 62, E4: 64, F4: 65, Fs4: 66, G4: 67, Gs4: 68, A4: 69, Bb4: 70, B4: 71,
    C5: 72, D5: 74, E5: 76, F5: 77, Fs5: 78, G5: 79, A5: 81};
  // Greensleeves in A minor, three beats a bar: [note, beats], with a bass note at each bar
  const GREEN = [["A4", 1], ["C5", 2], ["D5", 1], ["E5", 1.5], ["F5", 0.5], ["E5", 1], ["D5", 2], ["B4", 1], ["G4", 1.5], ["A4", 0.5], ["B4", 1],
    ["C5", 2], ["A4", 1], ["A4", 1.5], ["Gs4", 0.5], ["A4", 1], ["B4", 2], ["Gs4", 1], ["E4", 2], ["A4", 1], ["C5", 2], ["D5", 1],
    ["E5", 1.5], ["F5", 0.5], ["E5", 1], ["D5", 2], ["B4", 1], ["G4", 1.5], ["A4", 0.5], ["B4", 1], ["C5", 1.5], ["B4", 0.5], ["A4", 1],
    ["Gs4", 1.5], ["Fs4", 0.5], ["Gs4", 1], ["A4", 3], ["G5", 3], ["G5", 1.5], ["Fs5", 0.5], ["E5", 1], ["D5", 2], ["B4", 1],
    ["G4", 1.5], ["A4", 0.5], ["B4", 1], ["C5", 2], ["A4", 1], ["A4", 1.5], ["Gs4", 0.5], ["A4", 1], ["B4", 2], ["Gs4", 1], ["E4", 3],
    ["G5", 3], ["G5", 1.5], ["Fs5", 0.5], ["E5", 1], ["D5", 2], ["B4", 1], ["G4", 1.5], ["A4", 0.5], ["B4", 1], ["C5", 1.5], ["B4", 0.5], ["A4", 1],
    ["Gs4", 1.5], ["Fs4", 0.5], ["Gs4", 1], ["A4", 3]];
  const GREEN_BASS = ["A3", "A3", "F3", "G3", "C3", "A3", "E3", "E3", "A3", "A3", "F3", "G3", "A3", "E3", "A3",
    "C4", "C4", "G3", "G3", "A3", "A3", "E3", "E3", "C4", "C4", "G3", "G3", "A3", "E3", "A3"];
  function greensleeves(t0, beat = 0.42) {
    let t = t0 + beat * 0; // the pickup note before the first bar
    GREEN.forEach(([n, b], k) => { note(N[n], t, 0.42, 0.15 * Math.sin(k)); t += b * beat; });
    GREEN_BASS.forEach((n, bar) => note(N[n], t0 + beat * (1 + bar * 3), 0.32, -0.3));
    return t - t0 + 2.5;
  }
  // a ground: chords (root, third, fifth as MIDI) a bar each, improvised over with arpeggios
  const GROUNDS = {
    passamezzo: [[55, 58, 62], [53, 57, 60], [55, 58, 62], [50, 54, 57], [58, 62, 65], [53, 57, 60], [55, 58, 62], [50, 54, 57], [55, 58, 62]],
    romanesca: [[58, 62, 65], [53, 57, 60], [55, 58, 62], [50, 54, 57], [58, 62, 65], [53, 57, 60], [55, 58, 62], [50, 54, 57], [55, 58, 62]],
  };
  function ground(t0, name, galliard) {
    const chords = GROUNDS[name], beat = galliard ? 0.3 : 0.5, beats = galliard ? 6 : 4;
    let t = t0;
    for (let round = 0; round < 2; round++) chords.forEach(([r, th, fi], bar) => {
      note(r - 12, t, 0.34, -0.3);
      const tones = [r, th, fi, r + 12, fi, th, th + 12, fi + 12];
      for (let b = 0; b < beats; b++) {
        const up = (bar + b + round) % 3 === 0, pick = tones[(b * (galliard ? 2 : 3) + bar + round * 2) % tones.length] + (up ? 12 : 0);
        note(pick, t + b * beat, b === 0 ? 0.36 : 0.22, 0.2);
      }
      t += beats * beat;
    });
    note(chords[chords.length - 1][0] - 12, t, 0.3, -0.3); note(chords[chords.length - 1][0], t, 0.28, 0.2);
    return t - t0 + 3;
  }
  const PIECES = [(t) => greensleeves(t), (t) => ground(t, "passamezzo", false), (t) => ground(t, "romanesca", true), (t) => ground(t, "passamezzo", true)];
  function schedule() {
    if (!ctx || !musicOn || muted) return;
    if (ctx.currentTime + 1 < queueAt) return; // the next piece is already waiting
    const start = Math.max(ctx.currentTime + 0.2, queueAt);
    const length = PIECES[piece % PIECES.length](start);
    piece++; queueAt = start + length + 4; // a breath of silence between pieces
  }
  function startMusic() {
    if (!musicOn || muted) return;
    const a = audio(); if (!a) return;
    if (!mbus) { mbus = a.createGain(); mbus.gain.value = 0.22; mbus.connect(master); }
    mbus.gain.setTargetAtTime(0.22, a.currentTime, 0.5);
    if (!timer) { schedule(); timer = setInterval(schedule, 1000); }
  }
  function stopMusic() {
    clearInterval(timer); timer = 0; queueAt = 0;
    if (mbus && ctx) { mbus.gain.setTargetAtTime(0, ctx.currentTime, 0.3); const old = mbus; mbus = null; setTimeout(() => old.disconnect(), 1500); }
  }
  function setMusic(on) { musicOn = on; try { localStorage.setItem(MKEY, on ? "on" : "off"); } catch {} if (on) startMusic(); else stopMusic(); }
  // browsers allow sound only after a gesture: the first click on the page starts the music
  document.addEventListener("pointerdown", function first() { document.removeEventListener("pointerdown", first); startMusic(); });

  return {play, muted: () => muted, setMuted, countTo, floatText, celebrate, omen, yearCard, vignette, still,
    music: () => musicOn, setMusic};
})();
