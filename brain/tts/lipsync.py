r"""Lip sync (PC): reply audio (+ its text) -> a 30 fps vowel track for Lain's mouth ("A" "I" "U" "E" "O"; closed = all 0).
lain_say.py turns it into the <id>.vis.json the headset plays.

    python brain	ts\lipsync.py reply.wav "the reply text" track.json [--audio-only]

How it works:
  1. word timings: whisper.cpp (the same one the voice loop uses, path from config.json) transcribes the reply wav with
     one word per segment (-ml 1 -sow -oj); its words are matched to the reply text (whisper only supplies the timing).
  2. phonemes: espeak-ng (phonemizer + espeakng_loader, installed with kokoro-onnx) turns every word into IPA phones;
     they share the word's time, vowels weighted 2x consonants.
  3. visemes: each phone maps to a mouth shape (VISEME): open vowels -> A, front -> I / E, rounded -> U / O,
     m / b / p -> closed, f / v -> a near-closed I, other consonants keep the neighbouring vowel at 40 %.
  4. the track: per 1/30 s frame a weight dict, eased (open over ~2 frames, close over ~3), scaled by the audio's loudness
     envelope (silence = closed), max weight 0.9 so she never gapes.
Without text (or without espeak), --audio-only falls back to loudness -> A/O opening."""
import json, math, os, re, subprocess, sys, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import config  # noqa: E402
_V = config.load()["voice"]
WHISPER = config.path(_V.get("whisper_exe"))
WMODEL = config.path(_V.get("whisper_model"))
FPS = 30
KEYS = ("A", "I", "U", "E", "O")

# IPA (espeak-ng en-us) -> viseme. Longest match first. None = closed lips, "keep" = coarticulate with neighbours.
VISEME = [("aɪ", "A"), ("aʊ", "A"), ("eɪ", "E"), ("oʊ", "O"), ("ɔɪ", "O"), ("ɑː", "A"), ("iː", "I"), ("uː", "U"), ("ɜː", "E"),
          ("ɔː", "O"), ("ɑ", "A"), ("a", "A"), ("æ", "A"), ("ʌ", "A"), ("ə", "E"), ("ɚ", "E"), ("ɐ", "A"), ("ɛ", "E"), ("e", "E"),
          ("ɜ", "E"), ("i", "I"), ("ɪ", "I"), ("ᵻ", "I"), ("j", "I"), ("u", "U"), ("ʊ", "U"), ("w", "U"), ("o", "O"), ("ɔ", "O"),
          ("ɒ", "O"), ("m", None), ("b", None), ("p", None), ("f", "fv"), ("v", "fv")]
VOWELS = set("aɑæʌəɚɐɛeɜiɪᵻuʊoɔɒ")
OPEN = {"A": 0.85, "O": 0.7, "E": 0.55, "I": 0.45, "U": 0.5}       # how open each vowel is at full loudness


def load_wav(path):
    import soundfile as sf
    a, sr = sf.read(path); a = a if a.ndim == 1 else a.mean(1)
    return a.astype(np.float32), sr


def envelope(a, sr, n):
    """loudness per 1/30 s frame, 0..1 (95th percentile = 1)"""
    hop = sr / FPS; e = np.zeros(n)
    for k in range(n):
        s = a[int(k * hop): int((k + 1) * hop)]
        e[k] = math.sqrt(float((s ** 2).mean())) if len(s) else 0.0
    ref = np.percentile(e[e > 0], 95) if (e > 0).any() else 1.0
    return np.clip(e / max(ref, 1e-6), 0, 1)


def whisper_words(wav, sr_audio, a):
    """[(word, t0, t1)] in seconds from whisper.cpp, one word per segment"""
    tmpd = tempfile.mkdtemp(); w16 = os.path.join(tmpd, "w16.wav")
    import soundfile as sf
    n16 = int(len(a) * 16000 / sr_audio); sf.write(w16, np.interp(np.linspace(0, len(a) - 1, n16), np.arange(len(a)), a), 16000, subtype="PCM_16")
    base = os.path.join(tmpd, "out")
    subprocess.run([WHISPER, "-m", WMODEL, "-f", w16, "-ml", "1", "-sow", "-oj", "-of", base, "-np"], capture_output=True)
    js = json.load(open(base + ".json", encoding="utf-8"))
    out = []
    for seg in js.get("transcription", []):
        w = re.sub(r"[^\w']", "", seg["text"]).strip()
        if w: out.append((w, seg["offsets"]["from"] / 1000.0, seg["offsets"]["to"] / 1000.0))
    return out


def phonemes(words):
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    import espeakng_loader
    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    try: EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
    except Exception: pass
    from phonemizer.backend import EspeakBackend
    be = EspeakBackend("en-us", preserve_punctuation=False, with_stress=False)
    return [p.strip() for p in be.phonemize(list(words), strip=True)]


def split_phones(ipa):
    out = []; i = 0
    while i < len(ipa):
        if ipa[i] in " ˈˌː": i += 1; continue
        for k, v in VISEME:
            if ipa.startswith(k, i): out.append((k, v)); i += len(k); break
        else: out.append((ipa[i], "keep")); i += 1
    return out


def track(wav, text=None, audio_only=False):
    a, sr = load_wav(wav); n = int(math.ceil(len(a) / sr * FPS)); env = envelope(a, sr, n)
    tgt = [dict.fromkeys(KEYS, 0.0) for _ in range(n)]; labels = ["-"] * n
    words = [] if audio_only else whisper_words(wav, sr, a)
    if words:
        if text:                                                  # prefer the real reply words (whisper may mishear)
            tw = [re.sub(r"[^\w']", "", w) for w in text.split()]; tw = [w for w in tw if w]
            if len(tw) == len(words): words = [(t, t0, t1) for t, (_, t0, t1) in zip(tw, words)]
        try: ipas = phonemes([w for w, _, _ in words])
        except Exception as ex: print("espeak failed, audio only:", ex); words = []
    if words:
        for (w, t0, t1), ipa in zip(words, ipas):
            ph = split_phones(ipa) or [("ə", "E")]
            wts = [2.0 if any(c in VOWELS for c in k) else 1.0 for k, _ in ph]; tot = sum(wts); t = t0
            prev_v = None
            for (k, v), wt in zip(ph, wts):
                d = (t1 - t0) * wt / tot; f0, f1 = int(t * FPS), max(int(t * FPS) + 1, int((t + d) * FPS)); t += d
                for f in range(f0, min(n, f1)):
                    if v is None: tgt[f] = dict.fromkeys(KEYS, 0.0); labels[f] = "m"
                    elif v == "fv": tgt[f] = dict(dict.fromkeys(KEYS, 0.0), I=0.2); labels[f] = "f"
                    elif v == "keep":
                        if prev_v: tgt[f] = dict(dict.fromkeys(KEYS, 0.0), **{prev_v: 0.4 * OPEN[prev_v]}); labels[f] = prev_v.lower()
                    else: tgt[f] = dict(dict.fromkeys(KEYS, 0.0), **{v: OPEN[v]}); labels[f] = v
                if v in KEYS: prev_v = v
    else:                                                         # audio only: loudness opens the mouth (A / O alternate)
        for f in range(n):
            if env[f] > 0.15: v = "A" if (f // 5) % 3 else "O"; tgt[f] = dict(dict.fromkeys(KEYS, 0.0), **{v: OPEN[v]}); labels[f] = v
    # loudness gate + easing (open quickly, close a bit slower), never wider than 0.9
    cur = dict.fromkeys(KEYS, 0.0); frames = []
    for f in range(n):
        g = min(1.0, 0.35 + 0.9 * env[f]) if env[f] > 0.06 else 0.0
        for k in KEYS:
            want = min(0.9, tgt[f][k] * g); r = 0.65 if want > cur[k] else 0.45
            cur[k] += (want - cur[k]) * r
        frames.append({k: round(v, 3) for k, v in cur.items()})
    return dict(fps=FPS, seconds=len(a) / sr, frames=frames, labels="".join(labels), words=[(w, t0, t1) for w, t0, t1 in words])


if __name__ == "__main__":
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    wav, text = args[0], (args[1] if len(args) > 2 else None); out = args[-1]
    trk = track(wav, text, audio_only="--audio-only" in sys.argv)
    json.dump(trk, open(out, "w"), indent=0)
    print("%.1f s, %d frames, %d words | %s" % (trk["seconds"], len(trk["frames"]), len(trk["words"]), trk["labels"]))
