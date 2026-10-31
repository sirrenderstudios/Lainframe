r"""Optional "Wake up, Lain" phrase, PC side. Free and local: whisper.cpp (the voice setup's copy) on this PC; no audio
ever leaves the PC/headset link. Separate from the voice bridge.

Loop: ssh to the Frame (outbound) running `python3 -u ~/lainframe/lain/wake_link.py`. The Frame only opens the mic while
Lain is on the open Steam menu and idle, and sends each short speech burst (<= 3.2 s) as "seg <n> <base64 pcm>".
Here: whisper-cli transcribes it (~0.5 s), match_wake() looks for the phrase; on a hit -> "wake <n>" back over the same
link -> the Frame touches ~/.local/state/lainframe/wake.req -> Lain starts a normal listening round, exactly like a click.

False triggers: the Frame's energy gate (a TV in the room stays below it); "wake" + "up" + a Lain-sounding word
right after it (or "Lain, wake up"); the phrase must open the utterance (at most 2 filler words before it); no
whisper prompt (a prompt with "Lain" makes whisper hear her name in noise); 4 s cooldown after a trigger.
One copy only (mutex Local\LainWake). Started hidden by `lain_brain.py run` when voice.wake_phrase is on.
Log: %LOCALAPPDATA%\Lainframe\logs\lain_wake.log.
Test: python lain_wake.py --test <dir with .wav files>  (prints transcript + verdict per file; names pos_* should
trigger, everything else shouldn't)."""
import base64, ctypes, os, re, subprocess, sys, tempfile, threading, time, wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config, frame  # noqa: E402

_CFG = config.load()
LOG = config.log_file("lain_wake.log")
WHISPER = config.path(_CFG["voice"]["whisper_exe"])
MODEL = config.path(_CFG["voice"]["whisper_model"])
KEEP = os.path.join(config.DATA_DIR, "wake_recent")           # last 30 segments, local only, for tuning
KEEP_N = 30
NW = frame.NW
COOLDOWN_S = 4.0
JOIN_S = 2.5                                  # bursts closer than this are also matched joined
THREADS = str(max(2, min(8, (os.cpu_count() or 4) - 2)))

# words whisper writes for "Lain" (heard as lane / laine / layne / lean / line / lay in ...). Not "elaine": "wait up,
# Elaine" came out as "wake up, Elaine" once in the tests.
LAIN = r"(?:lain|laine|lane|layne|lainy|laney|lanie|lean|line|layin|lay\s+in|lain's|lane's|leyne|rain|lame|lay)"
# NB "rain", "lame", "lay": with TV noise underneath whisper sometimes hears "wake up, rain" for "wake up Lain"
FILL = r"(?:hey|okay|ok|oh|so|um|uh|hmm|please|now|come\s+on|yo|alright|all\s+right)"
WAKE_RE = re.compile(r"^(?:" + FILL + r"\s+){0,2}wake\s*up\s*" + LAIN + r"\b")     # \s*: "Wake Uplane"
WAKE_RE2 = re.compile(r"^(?:" + FILL + r"\s+){0,2}" + LAIN + r"\s+wake\s*up\b")


def log(*a):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 1024 * 1024: os.replace(LOG, LOG + ".1")
        with open(LOG, "a", encoding="utf-8") as f: f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
    except OSError: pass


def norm(text):
    t = text.lower().replace("wake-up", "wake up").replace("wakeup", "wake up")
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t)                      # [BLANK_AUDIO], (music) ...
    t = re.sub(r"[^a-z' ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def match_wake(text, prev=""):
    """the phrase opens the utterance. prev = the transcript of a burst that ended just before this one (the gate
    splits "Wake up. ... Lain." at a long pause): the pair is checked joined too. Mentions mid-sentence never count
    ("I said wake up Lain"), so talking about her or a TV line running into it does not wake her."""
    cands = [text] + ([prev + " " + text] if prev else [])
    cands += [p for c in list(cands) for p in re.split(r"[.!?]+", c)[1:]]   # or opens any sentence ("...later. Wake up, Lain.")
    for c in cands:
        t = norm(c)
        if WAKE_RE.search(t) or WAKE_RE2.search(t): return True
    return False


PROMPT = os.environ.get("LAIN_WAKE_PROMPT") or None          # tests only; default: no prompt


def transcribe(wav):
    try:
        r = subprocess.run([WHISPER, "-m", MODEL, "-f", wav, "-nt", "-np", "-l", "en", "-t", THREADS] + (["--prompt", PROMPT] if PROMPT else []),
                           capture_output=True, timeout=20, creationflags=NW)
        return re.sub(r"\s+", " ", r.stdout.decode("utf-8", errors="replace")).strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        log("whisper failed:", repr(e)); return ""


def write_wav(path, pcm):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(pcm)


def keep(n, pcm, text, hit):
    try:
        os.makedirs(KEEP, exist_ok=True)
        base = os.path.join(KEEP, time.strftime("%Y%m%d-%H%M%S") + "_%s%s" % (n, "_WAKE" if hit else ""))
        write_wav(base + ".wav", pcm)
        with open(base + ".txt", "w", encoding="utf-8") as f: f.write(text)
        files = sorted(os.listdir(KEEP))
        stems = sorted({f.rsplit(".", 1)[0] for f in files})
        for s in stems[:-KEEP_N]:
            for ext in (".wav", ".txt"):
                try: os.remove(os.path.join(KEEP, s + ext))
                except OSError: pass
    except OSError: pass


def session(cfg):
    """one ssh link to the Frame; returns when it drops."""
    H = frame.target(cfg)
    p = subprocess.Popen(["ssh", *frame.opts(cfg, 10), H,
                          "test -f ~/lainframe/lain/wake_link.py && exec python3 -u ~/lainframe/lain/wake_link.py || echo missing"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NW)
    last_wake = 0.0; tmp = tempfile.mkdtemp(prefix="lain_wake_"); prev = ""; prev_t = 0.0
    try:
        for raw in p.stdout:
            line = raw.decode("ascii", errors="replace").strip()
            if line == "missing":
                log("wake_link.py not on the Frame yet (run LainBrain.bat deploy)"); return "missing"
            if line.startswith("hello"):
                log("linked to", H, "(" + line + ")"); continue
            if not line.startswith("seg "): continue
            try:
                _, n, b64 = line.split(" ", 2); pcm = base64.b64decode(b64)
            except ValueError: continue
            wav = os.path.join(tmp, "seg.wav"); write_wav(wav, pcm)
            t0 = time.time(); text = transcribe(wav)
            hit = match_wake(text, prev if t0 - prev_t < JOIN_S else "")
            dt = time.time() - t0; prev, prev_t = ("", 0.0) if hit else (text, time.time())
            if hit and time.time() - last_wake < COOLDOWN_S:
                log("seg %s: '%s' (%.1fs) -> wake, but in cooldown" % (n, text, dt)); hit = False
            elif hit:
                last_wake = time.time()
                try:
                    p.stdin.write(("wake %s\n" % n).encode()); p.stdin.flush()
                    log("seg %s: '%s' (%.1fs) -> WAKE sent" % (n, text, dt))
                except OSError as e: log("wake send failed:", repr(e))
            else:
                log("seg %s: '%s' (%.1fs, %.1f s audio)" % (n, text, dt, len(pcm) / 32000))
            keep(n, pcm, text, hit)
    finally:
        try: p.kill()
        except Exception: pass
    return "dropped"


def run():
    m = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\LainWake")
    if ctypes.windll.kernel32.GetLastError() == 183:                   # ERROR_ALREADY_EXISTS
        log("already running, this copy exits"); return
    log("lain_wake started")
    if not (WHISPER and os.path.exists(WHISPER) and os.path.exists(MODEL)):
        log("whisper is not set up (run setup, voice step); exiting"); return
    while True:
        cfg = config.load()
        why = session(cfg) if cfg["headset"]["host"] else "no host"
        # missing script: check again in 5 min; dropped / unreachable: 20 s (the bridge's find_frame.py updates the address)
        time.sleep(300 if why == "missing" else 20)


def test(d):
    ok = bad = 0; t_all = 0.0
    for f in sorted(os.listdir(d)):
        if not f.endswith(".wav"): continue
        t0 = time.time(); text = transcribe(os.path.join(d, f)); t_all += time.time() - t0
        hit = match_wake(text); want = f.startswith("pos")
        ok += hit == want; bad += hit != want
        print("%-4s %-28s %-5s %s" % ("ok" if hit == want else "FAIL", f, "WAKE" if hit else "-", text))
    print("\n%d ok, %d wrong, %.2f s per clip" % (ok, bad, t_all / max(1, ok + bad)))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--test": test(sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "--match": print(match_wake(" ".join(sys.argv[2:])))
    else: run()
