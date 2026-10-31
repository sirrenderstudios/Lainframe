r"""Lain's spoken reply (PC): text -> <out>.wav (Kokoro; voice mix, semitones, speed and model folder from
%APPDATA%\Lainframe\config.json "voice") + <out>.vis.json (timed mouth track for the headset's lip sync).
Run with the repo's .venv python:

    python brain\tts\lain_say.py --text-file reply.txt out.wav [--no-lips] [--vis track.json] [--spawn] [--local]
    python brain\tts\lain_say.py "some text" out.wav
    pythonw brain\tts\lain_say.py --serve        (persistent helper, keeps the model loaded; the bridge starts it)
    python brain\tts\lain_say.py --ping          (exit 0 if the helper is up)

The CLI first hands the job to the helper on 127.0.0.1:PORT (model already loaded: fast); if the helper isn't running it
does the work itself (loads Kokoro, ~1.5 s extra) and, with --spawn, starts the helper for next time.
The bridge passes the text in a UTF-8 file (PowerShell 5.1 mangles quotes in native arguments).
The helper reads the voice settings once at start; after changing them, end it (lain_brain.py stop) or it keeps the old ones.

Mouth track (<out>.vis.json, written next to the wav: out.wav -> out.vis.json):
  {"v": 1, "fps": 30, "seconds": 3.42, "mode": "phonemes" | "audio",
   "shapes": ["closed","small","open","A","I","U","E","O"],
   "fallback": {"A":"open","O":"open","E":"small","I":"small","U":"small"},   # if a sprite set only has closed/small/open
   "events": [{"t": 0.0, "shape": "closed"}, {"t": 0.133, "shape": "E"}, ...],  # only the changes, t = seconds from audio start
   "frames": "--EEAA..."}                                                     # same track, one char per 1/30 s (see CODE)
The vowel shapes come from lipsync.py (whisper.cpp word timings + espeak-ng phonemes, loudness-gated).
"small" = a vowel/consonant that is only slightly open (weak syllable), "open" = loud but no phoneme info (audio-only mode).
"""
import io, json, os, socket, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import config  # noqa: E402

_V = config.load()["voice"]
MODELS = config.path(_V.get("kokoro_dir")) or os.path.join(config.DATA_DIR, "kokoro")
LOGF = config.log_file("lain_say.log")
PORT = 59731
SHAPES = ["closed", "small", "open", "A", "I", "U", "E", "O"]
CODE = {"closed": "-", "small": "s", "open": "o", "A": "A", "I": "I", "U": "U", "E": "E", "O": "O"}
MIX = tuple((str(v), float(w)) for v, w in (_V.get("voice_mix") or [["af_nicole", 1.0]]))
SEMITONES = float(_V.get("semitones", 2.5)); SPEED = float(_V.get("speed", 0.86))
THREADS = max(2, min(12, (os.cpu_count() or 4) - 2))
CLOSED_BELOW = 0.12; SMALL_BELOW = 0.30          # lipsync weights (0..0.9) -> closed / small / full vowel


def log(m):
    try:
        with open(LOGF, "a", encoding="utf-8") as f: f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")
    except OSError: pass


class Engine:
    """Kokoro + espeak loaded once."""
    def __init__(self):
        import numpy as np
        from kokoro_onnx import Kokoro
        import lipsync
        self.np, self.L = np, lipsync
        self.k = Kokoro(os.path.join(MODELS, "kokoro-v1.0.onnx"), os.path.join(MODELS, "voices-v1.0.bin"))
        self.style = sum(w * self.k.get_voice_style(v) for v, w in MIX)
        self._be = None; self.lock = threading.Lock()
        lipsync.phonemes = self.phonemes                       # reuse one espeak backend instead of one per reply
        lipsync.whisper_words = self.whisper_words             # same as lipsync's, but greedy + 12 threads + short context
        self.k.create("warm up.", voice=self.style, speed=1.0, lang="en-us")

    def whisper_words(self, wav, sr_audio, a):
        """[(word, t0, t1)] from whisper.cpp, one word per segment. Greedy decoding, several threads and an audio context
        sized to the clip (whisper's default window is 30 s): 0.9 s -> ~0.4 s for an 8 s reply, same words."""
        import re, soundfile as sf
        np, L = self.np, self.L
        tmpd = tempfile.mkdtemp(); w16 = os.path.join(tmpd, "w16.wav"); base = os.path.join(tmpd, "out")
        n16 = int(len(a) * 16000 / sr_audio)
        sf.write(w16, np.interp(np.linspace(0, len(a) - 1, n16), np.arange(len(a)), a), 16000, subtype="PCM_16")
        sec = len(a) / sr_audio; ac = 1500 if sec > 24 else min(1500, int(sec * 50 * 1.2) + 160)
        subprocess.run([L.WHISPER, "-m", L.WMODEL, "-f", w16, "-ml", "1", "-sow", "-oj", "-of", base, "-np",
                        "-t", str(THREADS), "-bs", "1", "-bo", "1", "-ac", str(ac)], capture_output=True, creationflags=0x08000000)
        js = json.load(open(base + ".json", encoding="utf-8")); out = []
        for seg in js.get("transcription", []):
            w = re.sub(r"[^\w']", "", seg["text"]).strip()
            if w: out.append((w, seg["offsets"]["from"] / 1000.0, seg["offsets"]["to"] / 1000.0))
        for f in (w16, base + ".json"):
            try: os.remove(f)
            except OSError: pass
        try: os.rmdir(tmpd)
        except OSError: pass
        return out

    def phonemes(self, words):
        if self._be is None:
            from phonemizer.backend.espeak.wrapper import EspeakWrapper
            import espeakng_loader
            EspeakWrapper.set_library(espeakng_loader.get_library_path())
            try: EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
            except Exception: pass
            from phonemizer.backend import EspeakBackend
            self._be = EspeakBackend("en-us", preserve_punctuation=False, with_stress=False)
        return [p.strip() for p in self._be.phonemize(list(words), strip=True)]

    def say(self, text, wav, lips=True):
        import soundfile as sf
        np = self.np; t0 = time.time()
        with self.lock:
            r = 2 ** (SEMITONES / 12.0)
            a, sr = self.k.create(text, voice=self.style, speed=SPEED / r, lang="en-us")
            n = int(len(a) / r); a2 = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a)   # play r x faster = pitch up
            sf.write(wav, a2.astype(np.float32), sr, subtype="PCM_16")                  # 16-bit PCM: plays with pw-play on the headset
            t_tts = time.time() - t0
            vis = None
            if lips:
                try: vis = mouth_track(self.L.track(wav, text), "phonemes")
                except Exception as e:
                    log("lips (phonemes) failed: %r, audio only" % (e,))
                    try: vis = mouth_track(self.L.track(wav, None, audio_only=True), "audio")
                    except Exception as e2: log("lips (audio) failed: %r" % (e2,))
                if vis: json.dump(vis, open(vis_path(wav), "w"), separators=(",", ":"))
        dt = time.time() - t0
        log("say %.1f s audio: tts %.2f s, total %.2f s, %s | %s" % (n / sr, t_tts, dt, vis and vis["mode"], text[:80]))
        return dict(seconds=round(n / sr, 2), tts_s=round(t_tts, 2), total_s=round(dt, 2), lips=bool(vis))


def vis_path(wav):
    return (wav[:-4] if wav.lower().endswith(".wav") else wav) + ".vis.json"


def mouth_track(trk, mode):
    """lipsync.py weights per 1/30 s -> one shape per frame + change events"""
    fps = trk["fps"]; frames = []
    for w in trk["frames"]:
        k = max(w, key=w.get); v = w[k]
        if v < CLOSED_BELOW: s = "closed"
        elif mode == "audio": s = "open" if v >= SMALL_BELOW else "small"
        else: s = k if v >= SMALL_BELOW else "small"
        frames.append(s)
    if frames: frames[-1] = "closed"                           # always ends shut
    ev = []
    for i, s in enumerate(frames):
        if not ev or ev[-1]["shape"] != s: ev.append({"t": round(i / fps, 3), "shape": s})
    return {"v": 1, "fps": fps, "seconds": round(trk["seconds"], 3), "mode": mode, "shapes": SHAPES,
            "fallback": {"A": "open", "O": "open", "E": "small", "I": "small", "U": "small"},
            "events": ev, "frames": "".join(CODE[s] for s in frames)}


# ---------------- persistent helper: one JSON line in, one JSON line out, localhost only
def _priority(cls):
    try:
        import ctypes
        k = ctypes.windll.kernel32; k.SetPriorityClass(k.GetCurrentProcess(), cls)
    except Exception: pass


def serve():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try: s.bind(("127.0.0.1", PORT))
    except OSError: log("helper already running"); return 0
    s.listen(8)
    # started hidden by the bridge: load + warm up at below-normal priority so login and games
    # aren't slowed, then back to normal so a reply isn't starved while a VR game loads the CPU
    _priority(0x4000)                                          # BELOW_NORMAL_PRIORITY_CLASS
    log("helper loading"); t0 = time.time(); eng = Engine(); log("helper ready (%.1f s load)" % (time.time() - t0))
    # one tiny reply with the mouth track: the first real reply otherwise pays espeak's start-up and whisper.cpp's
    # first run (~0.9 s extra: cold ~2 s, warm ~1.1 s for a 3 s reply)
    try:
        t1 = time.time(); d = tempfile.mkdtemp(); w = os.path.join(d, "warm.wav")
        eng.say("Hi.", w, True)
        for f in (w, vis_path(w)):
            try: os.remove(f)
            except OSError: pass
        try: os.rmdir(d)
        except OSError: pass
        log("helper warm (%.1f s)" % (time.time() - t1))
    except Exception as e: log("helper warm-up failed: %r" % (e,))
    _priority(0x0020)                                          # NORMAL_PRIORITY_CLASS

    def handle(c):
        try:
            c.settimeout(120); f = c.makefile("rwb")
            req = json.loads(f.readline().decode("utf-8"))
            if req.get("ping"): out = {"ok": True}
            else: out = dict(ok=True, **eng.say(req["text"], req["wav"], req.get("lips", True)))
        except Exception as e: out = {"ok": False, "error": repr(e)}; log("helper error: %r" % (e,))
        try: f.write((json.dumps(out) + "\n").encode("utf-8")); f.flush()
        except Exception: pass
        try: c.close()
        except Exception: pass
    while True:
        c, _ = s.accept(); threading.Thread(target=handle, args=(c,), daemon=True).start()


def ask_helper(req, timeout=120):
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=2) as c:
            c.settimeout(timeout); c.sendall((json.dumps(req) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                d = c.recv(65536)
                if not d: break
                buf += d
            return json.loads(buf.decode("utf-8"))
    except (OSError, ValueError): return None


def spawn_helper():
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    subprocess.Popen([pyw if os.path.exists(pyw) else sys.executable, os.path.abspath(__file__), "--serve"],
                     creationflags=0x08000000 | 0x00000008, close_fds=True)   # no window, detached


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--serve"]: sys.exit(serve())
    if a[:1] == ["--ping"]: sys.exit(0 if (ask_helper({"ping": True}, 5) or {}).get("ok") else 1)
    lips = "--no-lips" not in a; spawn = "--spawn" in a; local = "--local" in a; vis_to = None
    if "--vis" in a: i = a.index("--vis"); vis_to = os.path.abspath(a[i + 1]); del a[i:i + 2]   # put the track here instead
    a = [x for x in a if x not in ("--no-lips", "--spawn", "--local")]
    if a[0] == "--text-file": text = open(a[1], encoding="utf-8-sig").read(); wav = a[2]
    else: text, wav = a[0], a[1]
    text = " ".join(text.split()); wav = os.path.abspath(wav)
    if not text: sys.exit(2)
    t0 = time.time()
    r = None if local else ask_helper({"text": text, "wav": wav, "lips": lips})
    if r and r.get("ok"): r["via"] = "helper"
    else:
        if r: log("helper failed (%s), doing it here" % r.get("error"))
        if spawn and not local and r is None: spawn_helper()
        r = dict(ok=True, via="local", **Engine().say(text, wav, lips))
    if vis_to and r.get("lips") and os.path.abspath(vis_path(wav)) != vis_to:
        try: os.replace(vis_path(wav), vis_to)
        except OSError as e: r["lips"] = False; log("vis move failed: %r" % (e,))
    r["wall_s"] = round(time.time() - t0, 2)
    print(json.dumps(r))
