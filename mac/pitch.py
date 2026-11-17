"""Note and chord detection for the Mac, standard library only.

Records from the Mac's default input device with ffmpeg (or reads an audio file),
then finds held notes (YIN pitch detection) and a rough chord guess (chroma from FFT).
Ported from ../pitchcore.js so the web page and the Mac give the same answers.

CLI:
  python3 pitch.py listen [seconds]     record from the default input and print the result
  python3 pitch.py file <path>          read an audio or video file
  python3 pitch.py devices              list input devices
"""
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys

SR = 16000  # analysis sample rate; ffmpeg resamples to this
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAX_SECONDS = 15
MAX_FILE_SECONDS = 600
MAX_FILE_BYTES = 500 * 1024 * 1024


# ---------- notes ----------
def freq_to_midi(f):
    return 69 + 12 * math.log2(f / 440.0)


def midi_to_freq(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def midi_name(m):
    r = int(round(m))
    return NOTE_NAMES[r % 12] + str(r // 12 - 1)


def rms(buf):
    return math.sqrt(sum(x * x for x in buf) / len(buf)) if buf else 0.0


# ---------- YIN pitch detector ----------
def yin(buf, sr, min_f=50.0, max_f=1600.0):
    """Returns (freq, clarity) or None."""
    n = len(buf)
    half = n // 2
    tau_min = max(2, int(sr // max_f))
    tau_max = min(half - 1, int(math.ceil(sr / min_f)))
    head = buf[:half]
    d = [0.0] * (tau_max + 2)
    for tau in range(1, tau_max + 2):
        seg = buf[tau:tau + half]
        d[tau] = sum((a - b) * (a - b) for a, b in zip(head, seg))
    cm = [1.0] * (tau_max + 2)
    run = 0.0
    for tau in range(1, tau_max + 2):
        run += d[tau]
        cm[tau] = d[tau] * tau / run if run > 0 else 1.0
    best = -1
    tau = tau_min
    while tau <= tau_max:
        if cm[tau] < 0.15:
            while tau + 1 <= tau_max and cm[tau + 1] < cm[tau]:
                tau += 1
            best = tau
            break
        tau += 1
    if best < 0:
        mv = min(range(tau_min, tau_max + 1), key=lambda t: cm[t])
        if cm[mv] > 0.35:
            return None
        best = mv
    t = best
    x0 = cm[t - 1] if t > 1 else cm[t]
    x2 = cm[t + 1] if t + 1 < len(cm) else cm[t]
    denom = x0 - 2 * cm[t] + x2
    shift = 0.5 * (x0 - x2) / denom if denom != 0 else 0.0
    if abs(shift) > 1:
        shift = 0.0
    f = sr / (t + shift)
    if f < min_f or f > max_f:
        return None
    return f, max(0.0, 1 - cm[t])


def segment_notes(frames, hop, min_dur=0.2):
    """frames: list of (t, midi_float or None) -> held notes."""
    out = []
    cur = None

    def close():
        nonlocal cur
        if cur and cur["n"] * hop >= min_dur:
            avg = cur["sum"] / cur["n"]
            r = int(round(avg))
            out.append({"midi": r, "name": midi_name(r), "cents": int(round((avg - r) * 100)),
                        "start": cur["start"], "dur": cur["n"] * hop, "freq": midi_to_freq(avg)})
        cur = None

    gap = 0
    for t, m in frames:
        if m is None:
            gap += 1
            if gap > 2:
                close()
            continue
        r = int(round(m))
        if cur and r == cur["midi"]:
            cur["n"] += 1; cur["sum"] += m; gap = 0
        elif cur and abs(m - cur["sum"] / cur["n"]) < 0.7 and gap == 0:
            cur["n"] += 1; cur["sum"] += m  # vibrato tolerance
        else:
            close()
            cur = {"midi": r, "n": 1, "sum": m, "start": t}
            gap = 0
    close()
    merged = []
    for nt in out:
        p = merged[-1] if merged else None
        if p and p["midi"] == nt["midi"] and nt["start"] - (p["start"] + p["dur"]) < 0.15:
            p["dur"] = nt["start"] + nt["dur"] - p["start"]
        else:
            merged.append(nt)
    return merged


def decimate2(sig):
    """Halve the sample rate (light low-pass, then every 2nd sample). Pitch tracking only needs up to ~1.6 kHz."""
    n = len(sig)
    return [(sig[i - 1] + 2 * sig[i] + sig[i + 1]) * 0.25 if 0 < i < n - 1 else sig[i] for i in range(0, n, 2)]


def refine(buf, sr, f0):
    """Sharpen a pitch estimate on the full-rate signal: local minimum of the difference function near sr/f0."""
    half = len(buf) // 2
    head = buf[:half]
    t0 = int(round(sr / f0))
    lo, hi = max(2, t0 - 3), min(half - 1, t0 + 3)
    if hi - lo < 2:
        return f0
    d = {}
    for tau in range(lo - 1, hi + 2):
        d[tau] = sum((a - b) * (a - b) for a, b in zip(head, buf[tau:tau + half]))
    t = min(range(lo, hi + 1), key=lambda k: d[k])
    denom = d[t - 1] - 2 * d[t] + d[t + 1]
    shift = 0.5 * (d[t - 1] - d[t + 1]) / denom if denom > 0 else 0.0
    return sr / (t + max(-1.0, min(1.0, shift)))


def analyse_notes(sig, sr=SR, min_dur=0.2):
    full, full_sr = sig, sr
    sig, sr = decimate2(sig), sr / 2
    win, hop = 512, 256
    peak = max((abs(x) for x in sig), default=0.0)
    gate = max(0.005, peak * 0.06)
    frames = []
    for s in range(0, len(sig) - win + 1, hop):
        buf = sig[s:s + win]
        m = None
        if rms(buf) > gate:
            p = yin(buf, sr)
            if p and p[1] > 0.8:
                f = refine(full[2 * s:2 * s + 2 * win], full_sr, p[0])
                m = freq_to_midi(f)
        frames.append((s / sr, m))
    return segment_notes(frames, hop / sr, min_dur)


# ---------- chord guess ----------
CHORDS = [("", [0, 4, 7]), ("m", [0, 3, 7]), ("7", [0, 4, 7, 10]), ("maj7", [0, 4, 7, 11]), ("m7", [0, 3, 7, 10]),
          ("sus2", [0, 2, 7]), ("sus4", [0, 5, 7]), ("dim", [0, 3, 6]), ("aug", [0, 4, 8]), ("5", [0, 7]),
          ("6", [0, 4, 7, 9]), ("m6", [0, 3, 7, 9]), ("add9", [0, 2, 4, 7])]


def fft(re_, im):
    n = len(re_)
    j = 0
    for i in range(1, n):
        b = n >> 1
        while j & b:
            j ^= b
            b >>= 1
        j ^= b
        if i < j:
            re_[i], re_[j] = re_[j], re_[i]
            im[i], im[j] = im[j], im[i]
    length = 2
    while length <= n:
        ang = -2 * math.pi / length
        half = length // 2
        tw = [(math.cos(ang * k), math.sin(ang * k)) for k in range(half)]
        for i in range(0, n, length):
            for k in range(half):
                c, s = tw[k]
                a, b2 = i + k, i + k + half
                vr = re_[b2] * c - im[b2] * s
                vi = re_[b2] * s + im[b2] * c
                re_[b2] = re_[a] - vr; im[b2] = im[a] - vi
                re_[a] += vr; im[a] += vi
        length <<= 1


def chroma_from_spectrum(mag, sr, n_fft):
    c = [0.0] * 12
    bin_hz = sr / n_fft
    for i in range(1, len(mag)):
        f = i * bin_hz
        if f < 70 or f > 2100:
            continue
        v = mag[i]
        if v <= 0:
            continue
        m = freq_to_midi(f)
        r = int(round(m))
        if abs(m - r) > 0.35:
            continue
        c[r % 12] += v * v
    return c


def guess_chord(chroma):
    tot = sum(chroma)
    if tot <= 0:
        return None
    c = [x / tot for x in chroma]
    strongest = max(range(12), key=lambda i: c[i])
    best = None
    for root in range(12):
        for qual, ivs in CHORDS:
            pcs = [(root + iv) % 12 for iv in ivs]
            in_s = sum(c[pc] for pc in pcs)
            min_tone = min(c[pc] for pc in pcs)
            score = in_s - 0.6 * (1 - in_s) + 0.8 * min(min_tone * len(ivs), 0.5) - 0.02 * len(ivs) + (0.05 if root == strongest else 0)
            if best is None or score > best["score"]:
                best = {"score": score, "name": NOTE_NAMES[root] + qual}
    top = sorted(((v, i) for i, v in enumerate(c)), reverse=True)
    best["notes"] = [NOTE_NAMES[i] for v, i in top if v > 0.06][:5]
    return best


def clip_chord(sig, sr=SR, n_fft=8192, max_frames=8):
    if len(sig) < n_fft:
        return None
    peak = max(abs(x) for x in sig)
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n_fft - 1)) for i in range(n_fft)]
    starts = list(range(0, len(sig) - n_fft + 1, n_fft // 2))
    starts = [s for s in starts if rms(sig[s:s + n_fft]) >= peak * 0.08]
    if len(starts) > max_frames:  # spread the frames over the clip
        step = len(starts) / max_frames
        starts = [starts[int(i * step)] for i in range(max_frames)]
    chroma = [0.0] * 12
    for s in starts:
        re_ = [sig[s + i] * win[i] for i in range(n_fft)]
        im = [0.0] * n_fft
        fft(re_, im)
        mag = [math.hypot(re_[i], im[i]) for i in range(n_fft // 2)]
        for i, v in enumerate(chroma_from_spectrum(mag, sr, n_fft)):
            chroma[i] += v
    return guess_chord(chroma) if starts else None


# ---------- audio in ----------
class AudioError(Exception):
    pass


def _ffmpeg():
    exe = shutil.which("ffmpeg") or next((p for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg") if os.path.exists(p)), None)
    if not exe:
        raise AudioError("ffmpeg isn't installed, so the Mac can't record. Install it with Homebrew: brew install ffmpeg")
    return exe


def _pcm_to_floats(raw):
    n = len(raw) // 2
    return [v / 32768.0 for v in struct.unpack("<%dh" % n, raw[:n * 2])]


def default_input_name():
    """Name of macOS's default input device, or None if it can't be read."""
    try:
        out = subprocess.run(["system_profiler", "SPAudioDataType", "-json"], capture_output=True, timeout=10, text=True).stdout
        for dev in json.loads(out).get("SPAudioDataType", [{}])[0].get("_items", []):
            if dev.get("coreaudio_default_audio_input_device") == "spaudio_yes":
                return dev.get("_name")
    except Exception:
        pass
    return None


def list_devices():
    r = subprocess.run([_ffmpeg(), "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                       capture_output=True, text=True, timeout=15)
    lines = r.stderr.splitlines()
    names, on = [], False
    for ln in lines:
        if "audio devices" in ln:
            on = True
            continue
        if on:
            mm = re.search(r"\]\s*\[(\d+)\]\s*(.+)$", ln)
            if mm:
                names.append(mm.group(2).strip())
            else:
                break
    return names


QUIET_PEAK = 0.02  # a quiet room on the MacBook mic peaks near 0.013; a sung or played note is well above this


def record(seconds):
    """Record mono audio from the default input. Raises AudioError with a plain explanation."""
    seconds = max(1.0, min(float(seconds), MAX_SECONDS))
    cmd = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "avfoundation", "-i", ":default",
           "-t", str(seconds), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=seconds + 12)
    except subprocess.TimeoutExpired:
        raise AudioError("No sound arrived from the input device. If macOS is showing a microphone permission prompt, allow it "
                         "(System Settings > Privacy & Security > Microphone, for the app running Claude Code), then try again. "
                         "Otherwise connect the iPhone as the Mac's microphone and pick it in System Settings > Sound > Input.")
    if r.returncode != 0 or not r.stdout:
        msg = r.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["unknown error"]
        raise AudioError("Recording failed: " + msg[0] + ". Check System Settings > Privacy & Security > Microphone for the app running Claude Code.")
    sig = _pcm_to_floats(r.stdout)
    peak = max((abs(x) for x in sig), default=0.0)
    if peak < QUIET_PEAK:
        raise AudioError(("Only silence came in" if peak < 0.001 else "Only quiet background noise came in") +
                         ", so there's no note to report. The MacBook's own mic doesn't work: "
                         "connect the iPhone as the Mac's microphone (Continuity) and choose it in System Settings > Sound > Input, "
                         "then sing or play close to it while it listens. If the right device is already chosen, macOS may have blocked the "
                         "microphone for the app running Claude Code (Privacy & Security > Microphone).")
    return sig


def read_file(path):
    path = os.path.abspath(os.path.expanduser(str(path)))
    if not os.path.isfile(path):
        raise AudioError("No file at " + path)
    if os.path.getsize(path) > MAX_FILE_BYTES:
        raise AudioError("That file is over 500 MB. Trim it first.")
    cmd = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", path, "-vn", "-t", str(MAX_FILE_SECONDS),
           "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise AudioError("Reading the file took too long.")
    if r.returncode != 0 or not r.stdout:
        raise AudioError("ffmpeg couldn't read audio from that file.")
    return _pcm_to_floats(r.stdout)


# ---------- results ----------
def analyse(sig, want_chord=True):
    notes = analyse_notes(sig)
    res = {"seconds": round(len(sig) / SR, 1), "reference": "A4 = 440 Hz", "notes": [
        {"note": n["name"], "cents": n["cents"], "hz": round(n["freq"], 1), "start_s": round(n["start"], 2), "held_s": round(n["dur"], 2)}
        for n in notes]}
    if notes:
        main = max(notes, key=lambda n: n["dur"])
        res["main_note"] = {"note": main["name"], "cents": main["cents"], "hz": round(main["freq"], 1), "held_s": round(main["dur"], 2)}
        mids = [n["midi"] for n in notes]
        res["lowest"], res["highest"] = midi_name(min(mids)), midi_name(max(mids))
    if want_chord:
        ch = clip_chord(sig)
        if ch:
            res["chord_guess"] = {"chord": ch["name"], "strongest_notes": ch["notes"], "approximate": True}
    return res


def cents_str(c):
    return ("+" if c > 0 else "−" if c < 0 else "±") + str(abs(c))


def listen(seconds, want_chord=True):
    """Record from the default input (looking up its name at the same time) and analyse it."""
    import threading
    box = {}
    th = threading.Thread(target=lambda: box.update(name=default_input_name()), daemon=True)
    th.start()
    try:
        sig = record(seconds)
    except AudioError as e:
        th.join(12)
        name = box.get("name")
        if name and "came in, so" in str(e):  # quiet/silent message: name the device
            raise AudioError(str(e).replace("came in, so", "came in from \"%s\", so" % name, 1))
        raise
    res = analyse(sig, want_chord)
    th.join(12)
    if box.get("name"):
        res["input_device"] = box["name"]
    return res


def describe(res):
    """Short plain-text summary for people."""
    lines = []
    if res.get("input_device"):
        lines.append("Recorded from: %s." % res["input_device"])
    if "main_note" in res:
        m = res["main_note"]
        lines.append("Main note: %s, %s cents (%.1f Hz), held %.1f s." % (m["note"], cents_str(m["cents"]), m["hz"], m["held_s"]))
        if len(res["notes"]) > 1:
            lines.append("Notes in order: " + ", ".join("%s %s" % (n["note"], cents_str(n["cents"])) for n in res["notes"][:40]) + ".")
            lines.append("Lowest %s, highest %s." % (res["lowest"], res["highest"]))
    else:
        lines.append("No single held note was clear (a chord, a slide, or too quiet).")
    if "chord_guess" in res:
        c = res["chord_guess"]
        lines.append("Chord guess (rough): %s, strongest notes %s." % (c["chord"], ", ".join(c["strongest_notes"])))
    lines.append("Listened to %.1f s, A4 = 440 Hz." % res["seconds"])
    return "\n".join(lines)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "listen"
    try:
        if cmd == "listen":
            secs = float(argv[2]) if len(argv) > 2 else 4
            print("Listening for %g seconds on the default input..." % min(max(secs, 1), MAX_SECONDS), file=sys.stderr)
            print(describe(listen(secs)))
        elif cmd == "file" and len(argv) > 2:
            print(describe(analyse(read_file(argv[2]))))
        elif cmd == "devices":
            print("Default input: %s" % (default_input_name() or "unknown"))
            for i, n in enumerate(list_devices()):
                print("[%d] %s" % (i, n))
        else:
            print(__doc__)
            return 2
    except AudioError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
