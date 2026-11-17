"""Tests for pitch.py (run: python3 test_pitch.py). Same cases as ../test.js."""
import math, random, sys, time
import pitch as P

SR = P.SR
fails = []
def check(label, got, want):
    ok = got == want
    print(("ok  " if ok else "FAIL"), label, "->", got, "" if ok else "(want %s)" % want)
    if not ok: fails.append(label)

def tone(f, sec, harm=(1, .6, .4, .3), vib=0.0):
    n = int(sec * SR); out = [0.0] * n; ph = 0.0
    for i in range(n):
        ff = f * 2 ** (vib / 12 * math.sin(2 * math.pi * 5.5 * i / SR)) if vib else f
        ph += 2 * math.pi * ff / SR
        out[i] = 0.5 * sum(h * math.sin((k + 1) * ph) for k, h in enumerate(harm))
    return out

for f, want in [(82.41, "E2"), (110, "A2"), (261.63, "C4"), (440, "A4"), (1046.5, "C6"), (155.56, "D#3")]:
    p = P.yin(tone(f, 0.07)[:1024], SR)
    check("yin %.2f Hz" % f, P.midi_name(P.freq_to_midi(p[0])), want)

for f, want in [(110, "A2"), (261.63, "C4"), (440, "A4"), (880, "A5")]:
    notes = P.analyse_notes(tone(f, 0.8, vib=0.3))
    check("vibrato %g Hz" % f, [n["name"] for n in notes], [want])

for f in [82.41, 261.63, 440, 880, 1046.5, 1318.5]:  # in-tune notes must read within 3 cents
    n = P.analyse_notes(tone(f, 1.0))
    check("cents %g Hz" % f, len(n) == 1 and abs(n[0]["cents"]) <= 3, True)

seq = [(220, .6), (0, .2), (261.63, .5), (329.63, .7), (0, .3), (110, .4)]
sig = []
for f, d in seq: sig += tone(f, d) if f else [0.0] * int(d * SR)
check("melody", [n["name"] for n in P.analyse_notes(sig)], ["A3", "C4", "E4", "A2"])
random.seed(1)
check("melody + noise", [n["name"] for n in P.analyse_notes([x + (random.random() - .5) * .05 for x in sig])], ["A3", "C4", "E4", "A2"])

def chord(midis, sec=1.2):
    n = int(sec * SR)
    fs = [440 * 2 ** ((m - 69) / 12) for m in midis]
    return [sum(math.sin(2 * math.pi * f * h * i / SR) / (h * h) for f in fs for h in range(1, 5)) / len(fs) for i in range(n)]

for name, ms in [("C", [48, 52, 55, 60]), ("Am", [45, 52, 57, 60, 64]), ("G7", [43, 47, 50, 53]), ("E5", [40, 47, 52]), ("D", [50, 57, 62, 66])]:
    check("chord " + name, P.clip_chord(chord(ms))["name"], name)

check("parse empty silence", P.analyse([0.0] * SR).get("main_note"), None)
t0 = time.time(); P.analyse(tone(220, 4.0)); t = time.time() - t0
print("4 s clip analysed in %.1f s%s" % (t, " (slow: the Mac may be busy)" if t > 8 else ""))
res = P.analyse(chord([48, 52, 55, 60]))
check("summary text names the chord", "Chord guess (rough): C," in P.describe(res), True)
print("\nALL PASSED" if not fails else "\nFAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
