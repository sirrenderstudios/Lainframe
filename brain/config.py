"""Lainframe PC config: %APPDATA%\\Lainframe\\config.json (schema in docs/BUILD_SPEC.md). Every PC script reads its
paths, the headset address and the voice settings from here; nothing personal lives in the repo.
    import config; cfg = config.load(); config.save(cfg); config.path(cfg["art"]["local_dir"])
Big things (art, whisper, Kokoro, logs, the voice exchange folder) live under %LOCALAPPDATA%\\Lainframe (not roamed)."""
import copy, json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # the repo folder (LainBrain.bat lives here)
BRAIN = os.path.join(ROOT, "brain")
CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Lainframe")
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Lainframe")
CONFIG = os.path.join(CONFIG_DIR, "config.json")
LOGS = os.path.join(DATA_DIR, "logs")
MEMORY = os.path.join(CONFIG_DIR, "lain_memory.md")

# GitHub repo that hosts the art release zips. Placeholder until the public repo exists: a URL that still contains
# OWNER counts as "not set" and setup asks for the zips (or their URLs) instead.
GITHUB_REPO = "sirrenderstudios/Lainframe"
RELEASE = "https://github.com/%s/releases/latest/download/" % GITHUB_REPO
LAIN_CLIPS_PARTS = 2                       # from release.json of the published release
RELEASE_SHA256 = {"lainframe-lain-clips-1.zip": "3fe9dff723108d93840ff9d186e2377b23b9bc94620b216dc47d44e2197c1579",
                  "lainframe-lain-clips-2.zip": "979ed6ef0798b93d364ee0bf66297c0b8beb9aaba10d115185bda81df86a5168",
                  "lainframe-skies.zip": "a5ba58f4f9c7ceb2c5b464c2087aa47adf7a3117f3423d2ea646eeadac516306"}   # from release.json (v0.1.0 art)


def art_packs(cfg):
    """[(kind, file name)] of every release zip: the clips parts, then the skies pack."""
    n = int(cfg["art"].get("lain_clips_parts") or LAIN_CLIPS_PARTS)
    return [("clips", "lainframe-lain-clips-%d.zip" % i) for i in range(1, n + 1)] + [("skies", "lainframe-skies.zip")]

STEPS = ["welcome", "prereqs", "headset", "art", "extras", "deploy", "background", "voice", "autostart", "doctor"]

DEFAULTS = {
    "version": 1,
    "headset": {"host": "", "user": "steamos", "ssh_key": "%USERPROFILE%\\.ssh\\lainframe_ed25519",
                "voice_dir": "~/.local/state/lainframe/voice", "clicks": "~/.local/state/lainframe/clicks"},
    # Lain's clips ship in parts (GitHub caps a release file at 2 GiB): lainframe-lain-clips-1.zip .. -N.zip; sha256 by file
    # name (art_pipeline/make_release.py writes release.json with both values)
    "art": {"release": RELEASE, "lain_clips_parts": LAIN_CLIPS_PARTS, "sha256": dict(RELEASE_SHA256),
            "local_dir": "%LOCALAPPDATA%\\Lainframe\\art"},
    "extras": {"guard": False, "worn": False, "brightness": False, "mic": False},
    "voice": {"enabled": False, "brain": "claude", "model": "claude-sonnet-5-5", "chat_model": "claude-haiku-5-5",
              "whisper_exe": "", "whisper_model": "", "kokoro_dir": "", "voice_mix": [["af_nicole", 1.0]],
              "semitones": 2.5, "speed": 0.86, "wake_phrase": False, "hands": True},
    "autostart": False,
    "user_name": "",
    "skybox_as_steamvr_background": False,
    "background_mood": "lain_night",
    "setup": {"done": []},
}


def path(p):
    """%VARS% and ~ expanded (config stores portable forms like %LOCALAPPDATA%\\Lainframe\\art)."""
    return os.path.normpath(os.path.expanduser(os.path.expandvars(p))) if p else ""


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load():
    """config.json merged over the defaults (missing keys = defaults, so older files keep working)."""
    data = {}
    try:
        with open(CONFIG, encoding="utf-8-sig") as f: data = json.load(f)
    except FileNotFoundError: pass
    except (OSError, ValueError) as e:
        print("warning: %s is unreadable (%s); using defaults" % (CONFIG, e), file=sys.stderr)
    return _merge(DEFAULTS, data)


def save(cfg):
    """atomic write (the bridge / find_frame may read it at any moment)."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".config.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG)


def exists():
    return os.path.exists(CONFIG)


def is_set_up(cfg=None):
    cfg = cfg or load()
    return exists() and "deploy" in cfg["setup"]["done"] and bool(cfg["headset"]["host"])


def mark(cfg, step, done=True):
    d = cfg["setup"]["done"]
    if done and step not in d: d.append(step)
    if not done and step in d: d.remove(step)
    save(cfg)


def url_set(u):
    return bool(u) and "OWNER/" not in u


def validate(cfg):
    """list of human-readable problems (empty = fine)."""
    p = []
    h = cfg["headset"]
    if not h["host"]: p.append("no headset address yet (run setup)")
    if not h["user"]: p.append("headset user name is empty")
    if not os.path.exists(path(h["ssh_key"])): p.append("ssh key %s is missing" % path(h["ssh_key"]))
    v = cfg["voice"]
    if v["enabled"]:
        for k in ("whisper_exe", "whisper_model"):
            if not os.path.exists(path(v[k])): p.append("voice: %s not found (%s)" % (k, v[k] or "not set"))
        kd = path(v["kokoro_dir"])
        for f in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
            if not os.path.exists(os.path.join(kd, f)): p.append("voice: Kokoro file %s missing in %s" % (f, kd or "(not set)"))
        try:
            if not v["voice_mix"] or abs(sum(float(w) for _, w in v["voice_mix"])) < 1e-6: p.append("voice: voice_mix is empty")
        except (TypeError, ValueError): p.append("voice: voice_mix must be [[name, weight], ...]")
    return p


def venv_python(windowless=False):
    """the repo's .venv python (LainBrain.bat makes it); falls back to the running interpreter."""
    exe = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe" if windowless else "python.exe")
    if os.path.exists(exe): return exe
    if windowless:
        w = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.exists(w): return w
    return sys.executable


def log_file(name):
    os.makedirs(LOGS, exist_ok=True)
    return os.path.join(LOGS, name)


if __name__ == "__main__":                                   # python config.py -> prints the effective config
    c = load(); print(CONFIG); print(json.dumps(c, indent=2))
    for x in validate(c): print("problem:", x)
