// Juice: the sounds and small motions that make a year feel like a year. Every sound is made
// here with the Web Audio API, from oscillators and noise: no files to download or license.
// Everything respects the player's mute switch and their "reduce motion" setting.
"use strict";
window.PaxJuice = (() => {
  // the player's options, kept by this browser: animations (full, quick or off) and the size of
  // the interface; the volumes are below, with the sound
  const OKEY = "pax-options";
  const options = (() => { try { return {anim: "full", scale: 1, ...JSON.parse(localStorage.getItem(OKEY) || "{}")}; } catch { return {anim: "full", scale: 1}; } })();
  window.PaxOptions = {
    get: (k) => options[k],
    set(k, v) { options[k] = v; try { localStorage.setItem(OKEY, JSON.stringify(options)); } catch {} },
    speed: () => (options.anim === "quick" ? 0.5 : 1), // times every animation's length
  };
  const still = () => options.anim === "off" || (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  const KEY = "pax-sound";
  let ctx = null, master = null, sfx = null;
  // the player's volumes, 0 to 1, kept by the options window
  const VKEY = "pax-volumes";
  let volumes = (() => { try { return {music: 0.7, sfx: 0.8, ...JSON.parse(localStorage.getItem(VKEY) || "{}")}; } catch { return {music: 0.7, sfx: 0.8}; } })();
  let muted = (() => { try { return localStorage.getItem(KEY) === "off"; } catch { return false; } })();

  function audio() { // created on the first gesture: browsers refuse sound before one
    if (muted) return null;
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC(); master = ctx.createGain(); master.gain.value = 0.32; master.connect(ctx.destination);
      sfx = ctx.createGain(); sfx.gain.value = volumes.sfx * 1.25; sfx.connect(master);
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
    o.connect(g); g.connect(sfx); o.start(t); o.stop(t + dur + 0.05);
  }
  // a burst of filtered noise: drums, gunpowder, the scratch of a quill
  function noise({at = 0, dur = 0.3, freq = 900, q = 0.8, gain = 0.6, type = "lowpass"} = {}) {
    const a = audio(); if (!a) return;
    const t = a.currentTime + at, n = Math.ceil(a.sampleRate * dur), buf = a.createBuffer(1, n, a.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 2);
    const src = a.createBufferSource(), f = a.createBiquadFilter(), g = a.createGain();
    src.buffer = buf; f.type = type; f.frequency.value = freq; f.Q.value = q; g.gain.value = gain;
    src.connect(f); f.connect(g); g.connect(sfx); src.start(t);
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
    coronation: () => { bell(523.25, 0, 0.22); bell(659.25, 0.25, 0.2); bell(783.99, 0.5, 0.2); bell(1046.5, 0.9, 0.24);
      [392, 523.25, 659.25, 783.99, 1046.5].forEach((f, k) => tone(f, {at: 1.2 + k * 0.12, dur: 0.7, type: "triangle", gain: 0.16})); },
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
      setTimeout(() => { card.classList.add("out"); setTimeout(() => { card.remove(); done(); }, 380); }, 1250 * PaxOptions.speed());
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
  // a ceremony: a card built by the page (trusted, already escaped), with gold falling
  function ceremony(html) {
    const box = document.createElement("div");
    box.className = "triumph ceremony";
    box.innerHTML = `<div class="tcard">${html}<small class="go">Click to go on</small></div>`;
    if (!still()) for (let i = 0; i < 40; i++) {
      const s = document.createElement("i");
      s.style.left = `${Math.random() * 100}%`; s.style.background = ["#ecd08c", "#c49a52", "#fff3cf"][i % 3];
      s.style.animationDelay = `${0.4 + Math.random() * 1.2}s`; s.style.animationDuration = `${2.2 + Math.random() * 1.6}s`;
      s.style.setProperty("--drift", `${(Math.random() - 0.5) * 120}px`); s.style.setProperty("--spin", `${(Math.random() - 0.5) * 700}deg`);
      box.appendChild(s);
    }
    document.body.appendChild(box);
    const go = () => { box.classList.add("out"); setTimeout(() => box.remove(), 450); };
    box.onclick = go; setTimeout(go, 12000);
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
  // The music of the age, played by a small consort that improvises, as players then did: over
  // the grounds every musician knew (the passamezzo antico and moderno, the romanesca, the folia,
  // the bergamasca, the ruggiero; all of them anonymous and centuries old), in the dances of the
  // time (a slow pavane, a galliard in three, a quick saltarello), a theme and then divisions on
  // it, each one busier than the last. Lute, recorder, bass viol and tabor are all synthesised
  // here; nothing is recorded or licensed. "Greensleeves" (anonymous, c. 1580) is played as
  // written. No two pieces in a row are alike, and the mood follows the realm: peace, war or a
  // crisis of the age.
  const MKEY = "pax-music";
  let musicOn = (() => { try { return localStorage.getItem(MKEY) !== "off"; } catch { return true; } })();
  let mbus = null, room = null, timer = 0, queueAt = 0, mood = "peace", last = [];
  const strings = new Map();
  const midi = (m) => 440 * Math.pow(2, (m - 69) / 12);
  const rnd = (n) => Math.floor(Math.random() * n), pickOne = (xs) => xs[rnd(xs.length)];
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
  // a hall: a short tail of decaying noise, so the consort sounds in a room and not in a box
  function hall() {
    const a = ctx, n = Math.floor(a.sampleRate * 2.2), ir = a.createBuffer(2, n, a.sampleRate);
    for (let c = 0; c < 2; c++) { const d = ir.getChannelData(c); for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 3.2); }
    const conv = a.createConvolver(), wet = a.createGain(); conv.buffer = ir; wet.gain.value = 0.28;
    conv.connect(wet); wet.connect(mbus); return conv;
  }
  function out(node, pan) {
    let o = node;
    if (ctx.createStereoPanner) { const p = ctx.createStereoPanner(); p.pan.value = pan; node.connect(p); o = p; }
    o.connect(mbus); if (room) o.connect(room);
  }
  // the lute: a plucked string
  function note(m, at, gain = 0.5, pan = 0) {
    if (!ctx || !mbus) return;
    const src = ctx.createBufferSource(), g = ctx.createGain(), f = ctx.createBiquadFilter();
    src.buffer = pluck(midi(m)); f.type = "lowpass"; f.frequency.value = 2600; g.gain.value = gain;
    src.connect(f); f.connect(g); out(g, pan); src.start(at); src.stop(at + 2.4);
  }
  // the recorder: a soft breathy tone with a little vibrato
  function recorder(m, at, dur, gain = 0.16, pan = 0.25) {
    if (!ctx || !mbus) return;
    const o = ctx.createOscillator(), o2 = ctx.createOscillator(), g = ctx.createGain(), f = ctx.createBiquadFilter(), lfo = ctx.createOscillator(), lg = ctx.createGain();
    o.type = "triangle"; o2.type = "sine"; o.frequency.value = midi(m); o2.frequency.value = midi(m) * 2;
    lfo.frequency.value = 5.2; lg.gain.value = midi(m) * 0.004; lfo.connect(lg); lg.connect(o.frequency); lg.connect(o2.frequency);
    const g2 = ctx.createGain(); g2.gain.value = 0.18; o2.connect(g2); g2.connect(f);
    f.type = "lowpass"; f.frequency.value = 3200; o.connect(f); f.connect(g);
    g.gain.setValueAtTime(0.0001, at); g.gain.linearRampToValueAtTime(gain, at + 0.05); g.gain.setValueAtTime(gain * 0.85, at + Math.max(0.06, dur - 0.08));
    g.gain.linearRampToValueAtTime(0.0001, at + dur);
    out(g, pan); [o, o2, lfo].forEach((x) => { x.start(at); x.stop(at + dur + 0.05); });
  }
  // the bass viol: a bowed low string
  function viol(m, at, dur, gain = 0.1, pan = -0.35) {
    if (!ctx || !mbus) return;
    const o = ctx.createOscillator(), g = ctx.createGain(), f = ctx.createBiquadFilter();
    o.type = "sawtooth"; o.frequency.value = midi(m); f.type = "lowpass"; f.frequency.value = 700; f.Q.value = 0.7;
    g.gain.setValueAtTime(0.0001, at); g.gain.linearRampToValueAtTime(gain, at + 0.12); g.gain.setValueAtTime(gain * 0.8, at + Math.max(0.13, dur - 0.15));
    g.gain.linearRampToValueAtTime(0.0001, at + dur);
    o.connect(f); f.connect(g); out(g, pan); o.start(at); o.stop(at + dur + 0.05);
  }
  // the tabor: a small skin drum for the dances
  function tabor(at, gain = 0.22) {
    if (!ctx || !mbus) return;
    const n = Math.ceil(ctx.sampleRate * 0.18), buf = ctx.createBuffer(1, n, ctx.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 4);
    const src = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    src.buffer = buf; f.type = "bandpass"; f.frequency.value = 190; f.Q.value = 1.4; g.gain.value = gain;
    src.connect(f); f.connect(g); out(g, -0.1); src.start(at);
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
    let t = t0;
    const sung = Math.random() < 0.5; // now on the lute, now on the recorder over it
    GREEN.forEach(([n, b], k) => { if (sung) recorder(N[n], t, b * beat * 0.95, 0.15); else note(N[n], t, 0.42, 0.15 * Math.sin(k)); t += b * beat; });
    GREEN_BASS.forEach((n, bar) => { note(N[n], t0 + beat * (1 + bar * 3), 0.32, -0.3); if (sung) note(N[n] + 12, t0 + beat * (2 + bar * 3), 0.16, -0.1); });
    return t - t0 + 2.5;
  }
  // The grounds: a chord a bar, as [degree in semitones above the key, major (M) or minor (m)].
  const GROUNDS = {
    passamezzo_antico: {minor: true, bars: [[0, "m"], [10, "M"], [0, "m"], [7, "M"], [3, "M"], [10, "M"], [0, "m"], [7, "M"]]},
    passamezzo_moderno: {minor: false, bars: [[0, "M"], [5, "M"], [0, "M"], [7, "M"], [0, "M"], [5, "M"], [0, "M"], [7, "M"]]},
    romanesca: {minor: true, bars: [[3, "M"], [10, "M"], [0, "m"], [7, "M"], [3, "M"], [10, "M"], [0, "m"], [7, "M"]]},
    folia: {minor: true, bars: [[0, "m"], [7, "M"], [0, "m"], [10, "M"], [3, "M"], [10, "M"], [0, "m"], [7, "M"]]},
    bergamasca: {minor: false, bars: [[0, "M"], [5, "M"], [7, "M"], [0, "M"], [0, "M"], [5, "M"], [7, "M"], [0, "M"]]},
    ruggiero: {minor: false, bars: [[0, "M"], [7, "M"], [0, "M"], [5, "M"], [0, "M"], [7, "M"], [0, "M"], [7, "M"]]},
  };
  const DANCES = {pavane: {beats: 4, beat: 0.52}, galliard: {beats: 3, beat: 0.36}, saltarello: {beats: 6, beat: 0.2}};
  const MOODS = { // which grounds, dances and textures suit the realm's state
    peace: {grounds: ["passamezzo_moderno", "bergamasca", "ruggiero", "romanesca", "passamezzo_antico"], dances: ["pavane", "galliard", "pavane"], drum: 0.2},
    war: {grounds: ["folia", "passamezzo_antico", "romanesca", "ruggiero"], dances: ["saltarello", "galliard"], drum: 0.85},
    crisis: {grounds: ["folia", "passamezzo_antico", "romanesca"], dances: ["pavane"], drum: 0},
  };
  const chordTones = (key, [deg, q]) => [key + deg, key + deg + (q === "M" ? 4 : 3), key + deg + 7];
  // the notes a melody may use over a chord: the key's scale, with the leading note raised over V
  function scaleFor(key, minor, [deg]) {
    const steps = minor ? [0, 2, 3, 5, 7, 8, 10] : [0, 2, 4, 5, 7, 9, 11];
    const s = steps.map((x) => key + x);
    if (minor && deg === 7) s[6] = key + 11;
    const all = []; for (const o of [0, 12, 24]) s.forEach((x) => all.push(x + o)); return all;
  }
  // one statement of the ground: lute chords, a bass, and a melody whose divisions grow busier
  function statement(t0, ground, key, dance, division, voice, drum) {
    const {beats, beat} = DANCES[dance], g = GROUNDS[ground];
    let t = t0, prev = key + 12 + 7;
    g.bars.forEach((bar, k) => {
      const [r, th, fi] = chordTones(key, bar), last = k === g.bars.length - 1;
      // the bass: on the lute, or bowed by the viol in the consort
      if (voice === "consort") viol(r - 12, t, beats * beat * 0.98, 0.09); else note(r - 12, t, 0.34, -0.3);
      // the lute's chord, strummed on the first beat and touched again in the bar
      [r, th, fi].forEach((m, i) => note(m, t + i * 0.018, i ? 0.17 : 0.22, -0.05 + i * 0.05));
      if (beats >= 4) [th, fi].forEach((m, i) => note(m + 12, t + beat * Math.floor(beats / 2) + i * 0.02, 0.12, 0.1));
      // the melody: a chord tone on the downbeat near the last note, then passing notes
      const sc = scaleFor(key + 12, g.minor, bar), targets = [r, th, fi].map((m) => m + 12).flatMap((m) => [m, m + 12]).filter((m) => m >= key + 9 && m <= key + 31);
      const target = last ? key + 12 + (Math.random() < 0.5 ? 12 : 0) : targets.reduce((a, b) => (Math.abs(b - prev) < Math.abs(a - prev) ? b : a));
      const per = division === 0 ? 1 : division === 1 ? 2 : 4; // notes per beat
      const n = last ? 1 : beats * per, step = beat / per;
      let cur = target;
      for (let i = 0; i < n; i++) {
        const at = t + i * step, len = last ? beats * beat : step * 0.95, accent = i % per === 0;
        if (voice === "recorder" || (voice === "consort" && division < 2)) recorder(cur, at, len, accent ? 0.15 : 0.11);
        else note(cur, at, accent ? 0.3 : 0.2, 0.2);
        if (last) break;
        // move by step towards the next bar's chord, now and then leaping within the chord
        const idx = sc.indexOf(sc.reduce((a, b) => (Math.abs(b - cur) < Math.abs(a - cur) ? b : a)));
        const dir = Math.random() < 0.5 ? 1 : -1, leap = Math.random() < 0.15;
        cur = leap ? pickOne([r, th, fi].map((m) => m + 12)) : sc[Math.max(0, Math.min(sc.length - 1, idx + dir))];
      }
      prev = target;
      if (drum > 0) for (let b = 0; b < beats; b++) if (b === 0 || (Math.random() < drum * 0.6 && b % (dance === "saltarello" ? 3 : 2) === 0)) tabor(t + b * beat, b === 0 ? 0.24 : 0.15);
      t += beats * beat;
    });
    return t - t0;
  }
  // a whole piece: a fresh ground, dance, key and texture, the theme and two or three divisions
  function piece(t0) {
    const m = MOODS[mood] || MOODS.peace;
    let ground, dance, tries = 0;
    do { ground = pickOne(m.grounds); dance = pickOne(m.dances); tries++; } while (last.includes(`${ground}/${dance}`) && tries < 12);
    last = [...last.slice(-3), `${ground}/${dance}`];
    const key = pickOne(GROUNDS[ground].minor ? [50, 52, 55, 57] : [48, 50, 53, 55]); // D, E, G, A minor; C, D, F, G major
    const voice = pickOne(["lute", "recorder", "consort"]), drum = Math.random() < m.drum ? (mood === "war" ? 1 : 0.5) : 0;
    let t = t0;
    const rounds = dance === "pavane" ? 3 : 4;
    for (let d = 0; d < rounds; d++) t += statement(t, ground, key, dance, Math.min(2, d), voice, d === 0 ? drum * 0.5 : drum);
    return t - t0 + 3;
  }
  function schedule() {
    if (!ctx || !musicOn || muted) return;
    if (ctx.currentTime + 1 < queueAt) return; // the next piece is already waiting
    const start = Math.max(ctx.currentTime + 0.2, queueAt);
    // Greensleeves now and then, in peace; else a new improvisation
    const length = mood === "peace" && Math.random() < 0.15 && !last.includes("green") ? (last = [...last.slice(-3), "green"], greensleeves(start)) : piece(start);
    queueAt = start + length + 4; // a breath of silence between pieces
  }
  function startMusic() {
    if (!musicOn || muted) return;
    const a = audio(); if (!a) return;
    if (!mbus) { mbus = a.createGain(); mbus.gain.value = 0.0001; mbus.connect(master); room = hall(); }
    mbus.gain.setTargetAtTime(0.3 * volumes.music, a.currentTime, 0.5);
    if (!timer) { schedule(); timer = setInterval(schedule, 1000); }
  }
  function stopMusic() {
    clearInterval(timer); timer = 0; queueAt = 0;
    if (mbus && ctx) { mbus.gain.setTargetAtTime(0, ctx.currentTime, 0.3); const old = mbus; mbus = null; room = null; setTimeout(() => old.disconnect(), 1500); }
  }
  function setMusic(on) { musicOn = on; try { localStorage.setItem(MKEY, on ? "on" : "off"); } catch {} if (on) startMusic(); else stopMusic(); }
  // the realm's state, for the next piece: "peace", "war" or "crisis"
  function setMood(m) { mood = MOODS[m] ? m : "peace"; }
  function setVolumes(v) {
    volumes = {...volumes, ...v};
    try { localStorage.setItem(VKEY, JSON.stringify(volumes)); } catch {}
    if (sfx) sfx.gain.setTargetAtTime(volumes.sfx * 1.25, ctx.currentTime, 0.05);
    if (mbus) mbus.gain.setTargetAtTime(0.3 * volumes.music, ctx.currentTime, 0.1);
  }
  document.addEventListener("pointerdown", function first() { document.removeEventListener("pointerdown", first); startMusic(); });

  return {play, muted: () => muted, setMuted, countTo, floatText, celebrate, omen, ceremony, yearCard, vignette, still,
    music: () => musicOn, setMusic, setMood, setVolumes, volumes: () => ({...volumes})};
})();
