// ---- Pitch core (pure functions, no DOM) ----
var NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

function freqToMidi(f) { return 69 + 12 * Math.log2(f / 440); }
function midiToFreq(m) { return 440 * Math.pow(2, (m - 69) / 12); }
function midiName(m) { var r = Math.round(m); return NOTE_NAMES[((r % 12) + 12) % 12] + (Math.floor(r / 12) - 1); }
function noteInfo(f) {
  var m = freqToMidi(f), r = Math.round(m);
  return { freq: f, midi: r, name: midiName(r), cents: Math.round((m - r) * 100) };
}

function rms(buf) { var s = 0; for (var i = 0; i < buf.length; i++) s += buf[i] * buf[i]; return Math.sqrt(s / buf.length); }

// YIN pitch detector. Returns {freq, clarity} or null.
function yin(buf, sr, minF, maxF) {
  minF = minF || 50; maxF = maxF || 1600;
  var n = buf.length, half = Math.floor(n / 2);
  var tauMin = Math.max(2, Math.floor(sr / maxF)), tauMax = Math.min(half - 1, Math.ceil(sr / minF));
  var d = new Float32Array(tauMax + 2);
  for (var tau = 1; tau <= tauMax + 1; tau++) {
    var sum = 0;
    for (var i = 0; i < half; i++) { var x = buf[i] - buf[i + tau]; sum += x * x; }
    d[tau] = sum;
  }
  // cumulative mean normalized difference
  var cm = new Float32Array(tauMax + 2); cm[0] = 1; var run = 0;
  for (tau = 1; tau <= tauMax + 1; tau++) { run += d[tau]; cm[tau] = run > 0 ? d[tau] * tau / run : 1; }
  var thr = 0.15, best = -1;
  for (tau = tauMin; tau <= tauMax; tau++) {
    if (cm[tau] < thr) { while (tau + 1 <= tauMax && cm[tau + 1] < cm[tau]) tau++; best = tau; break; }
  }
  if (best < 0) { // fall back to global minimum if it is reasonably clear
    var mv = 1e9;
    for (tau = tauMin; tau <= tauMax; tau++) if (cm[tau] < mv) { mv = cm[tau]; best = tau; }
    if (mv > 0.35) return null;
  }
  var t = best;
  var x0 = t > 1 ? cm[t - 1] : cm[t], x2 = t + 1 < cm.length ? cm[t + 1] : cm[t];
  var denom = x0 - 2 * cm[t] + x2, shift = denom !== 0 ? 0.5 * (x0 - x2) / denom : 0;
  if (Math.abs(shift) > 1) shift = 0;
  var f = sr / (t + shift);
  if (f < minF || f > maxF) return null;
  return { freq: f, clarity: Math.max(0, 1 - cm[t]) };
}

// Turns a stream of frames [{t, midiFloat|null}] into held notes.
// A held note: same rounded semitone for at least minDur seconds.
function segmentNotes(frames, hop, minDur) {
  minDur = minDur || 0.2;
  var out = [], cur = null;
  function close() {
    if (cur && cur.n * hop >= minDur) {
      var avg = cur.sum / cur.n, r = Math.round(avg);
      out.push({ midi: r, name: midiName(r), cents: Math.round((avg - r) * 100), start: cur.start, dur: cur.n * hop, freq: midiToFreq(avg) });
    }
    cur = null;
  }
  var gap = 0;
  for (var i = 0; i < frames.length; i++) {
    var fr = frames[i];
    if (fr.m == null) { gap++; if (gap > 2) close(); continue; }
    var r = Math.round(fr.m);
    if (cur && r === cur.midi) { cur.n++; cur.sum += fr.m; gap = 0; }
    else if (cur && Math.abs(fr.m - cur.sum / cur.n) < 0.7 && gap === 0) { cur.n++; cur.sum += fr.m; } // vibrato tolerance
    else { close(); cur = { midi: r, n: 1, sum: fr.m, start: fr.t }; gap = 0; }
  }
  close();
  // merge neighbours that are the same note (split by a dropout)
  var merged = [];
  for (i = 0; i < out.length; i++) {
    var p = merged[merged.length - 1];
    if (p && p.midi === out[i].midi && out[i].start - (p.start + p.dur) < 0.15) { p.dur = out[i].start + out[i].dur - p.start; }
    else merged.push(out[i]);
  }
  return merged;
}

// Analyse a whole mono signal (Float32Array) -> {frames, notes}
// Cheap downsampling to ~16 kHz (two passes of a moving average, then pick every k-th sample).
function decimate(sig, sr, target) {
  var k = Math.max(1, Math.floor(sr / (target || 16000)));
  if (k === 1) return { sig: sig, sr: sr };
  var n = Math.floor(sig.length / k), out = new Float32Array(n), a = new Float32Array(sig.length), acc = 0, i;
  for (i = 0; i < sig.length; i++) { acc += sig[i]; if (i >= k) acc -= sig[i - k]; a[i] = acc / k; }
  acc = 0; var b = new Float32Array(sig.length);
  for (i = 0; i < a.length; i++) { acc += a[i]; if (i >= k) acc -= a[i - k]; b[i] = acc / k; }
  for (i = 0; i < n; i++) out[i] = b[i * k + k - 1];
  return { sig: out, sr: sr / k };
}

function analyseSignal(sig0, sr0, opts) {
  opts = opts || {};
  var dd = decimate(sig0, sr0, 22000), sig = dd.sig, sr = dd.sr;
  var win = 1024, hop = 352, frames = [];
  var buf = new Float32Array(win);
  var peak = 0; for (var k = 0; k < sig.length; k++) { var a = Math.abs(sig[k]); if (a > peak) peak = a; }
  var gate = Math.max(0.005, peak * 0.06);
  for (var s = 0; s + win <= sig.length; s += hop) {
    for (var j = 0; j < win; j++) buf[j] = sig[s + j];
    var m = null;
    if (rms(buf) > gate) {
      var p = yin(buf, sr, opts.minF, opts.maxF);
      if (p && p.clarity > 0.8) m = freqToMidi(p.freq);
    }
    frames.push({ t: s / sr, m: m });
  }
  return { frames: frames, notes: segmentNotes(frames, hop / sr, opts.minDur || 0.2) };
}

// ---- Chord guess from a magnitude spectrum (approximate) ----
var CHORDS = [
  ["", [0, 4, 7]], ["m", [0, 3, 7]], ["7", [0, 4, 7, 10]], ["maj7", [0, 4, 7, 11]], ["m7", [0, 3, 7, 10]],
  ["sus2", [0, 2, 7]], ["sus4", [0, 5, 7]], ["dim", [0, 3, 6]], ["aug", [0, 4, 8]], ["5", [0, 7]], ["6", [0, 4, 7, 9]], ["m6", [0, 3, 7, 9]], ["add9", [0, 2, 4, 7]]
];
function chromaFromSpectrum(mag, sr, fftSize) {
  var c = new Float32Array(12), bin = sr / fftSize;
  for (var i = 1; i < mag.length; i++) {
    var f = i * bin; if (f < 70 || f > 2100) continue;
    var v = mag[i]; if (v <= 0) continue;
    var m = freqToMidi(f), r = Math.round(m);
    if (Math.abs(m - r) > 0.35) continue;
    c[((r % 12) + 12) % 12] += v * v;
  }
  return c;
}
function guessChord(chroma) {
  var tot = 0, i; for (i = 0; i < 12; i++) tot += chroma[i];
  if (tot <= 0) return null;
  var c = []; for (i = 0; i < 12; i++) c.push(chroma[i] / tot);
  var best = null;
  for (var root = 0; root < 12; root++) for (var k = 0; k < CHORDS.length; k++) {
    var ivs = CHORDS[k][1], inS = 0, set = {};
    ivs.forEach(function (iv) { var pc = (root + iv) % 12; set[pc] = 1; inS += c[pc]; });
    var out = 1 - inS, minTone = 1;
    ivs.forEach(function (iv) { minTone = Math.min(minTone, c[(root + iv) % 12]); });
    // reward coverage, punish energy outside the chord and missing tones, slight bias to simpler chords
    var score = inS - 0.6 * out + 0.8 * Math.min(minTone * ivs.length, 0.5) - 0.02 * ivs.length + (root === strongest(c) ? 0.05 : 0);
    if (!best || score > best.score) best = { score: score, name: NOTE_NAMES[root] + CHORDS[k][0], root: NOTE_NAMES[root], quality: CHORDS[k][0] };
  }
  var top = c.map(function (v, idx) { return [v, idx]; }).sort(function (a, b) { return b[0] - a[0]; })
    .filter(function (x) { return x[0] > 0.06; }).slice(0, 5).map(function (x) { return NOTE_NAMES[x[1]]; });
  best.notes = top;
  return best;
}
function strongest(c) { var b = 0; for (var i = 1; i < 12; i++) if (c[i] > c[b]) b = i; return b; }

// ---- Voice type (rough guide) from a range in MIDI numbers ----
var VOICE_TYPES = [
  { name: "Bass", lo: 40, hi: 64 },        // E2-E4
  { name: "Baritone", lo: 45, hi: 69 },    // A2-A4
  { name: "Tenor", lo: 48, hi: 72 },       // C3-C5
  { name: "Countertenor", lo: 52, hi: 76 },// E3-E5
  { name: "Alto", lo: 53, hi: 77 },        // F3-F5
  { name: "Mezzo-soprano", lo: 57, hi: 81 },// A3-A5
  { name: "Soprano", lo: 60, hi: 84 }      // C4-C6
];
function guessVoice(lo, hi) {
  if (lo == null || hi == null || hi <= lo) return null;
  var scored = VOICE_TYPES.map(function (v) {
    var ov = Math.max(0, Math.min(hi, v.hi) - Math.max(lo, v.lo));
    var span = Math.max(hi, v.hi) - Math.min(lo, v.lo);
    return { name: v.name, score: ov / span - 0.02 * Math.abs((lo + hi) / 2 - (v.lo + v.hi) / 2) };
  }).sort(function (a, b) { return b.score - a.score; });
  return scored[0].name;
}

if (typeof module !== "undefined" && module.exports) module.exports = { decimate: decimate, yin: yin, noteInfo: noteInfo, analyseSignal: analyseSignal, segmentNotes: segmentNotes, chromaFromSpectrum: chromaFromSpectrum, guessChord: guessChord, guessVoice: guessVoice, midiName: midiName, freqToMidi: freqToMidi };
