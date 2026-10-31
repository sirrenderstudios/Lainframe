#!/usr/bin/env python3
"""Lain on the Steam Frame menu (Lainframe, a non-commercial fan project; 2D "Grok Lain" player).
A flat panel (2D anime, no stereo) sitting on the TOP edge of the big Steam menu, playing the 30 fps clip library
~/lainframe/lain/clips_grok chained by POSE so no clip ever starts from the wrong pose: rest (front, eyes open), listen
(soft smile, eyes on you), wired (wires in, eyes closed), talk (wires in, eyes open), sleep, lean_l/r and llean_l/r
(leaning toward you while idle / while listening).
- Idle: random quiet behaviour (rest/still/look around/peek/sigh/doze/shy glance); at night (23:00-07:00) sleepier
  (rest_night, more dozing) and she falls asleep after SLEEP_NIGHT_S of nothing (SLEEP_DAY_S by day).
- Attention ("Wake up, Lain" or a click): enter_listen -> listen_loop, small reactions (nod / slow blink / tilt) at the
  pauses in your speech; exit_listen when listening ends.
- Thinking: think_open (eyes open, no wires) for the first 15 s; after that the wires come in (enter_think -> think_loop).
- Answer: from the wires: answer -> talk loops (closed-mouth *_lips twins under a live mouth track) -> wires_out.
  From think_open (answered within 15 s): no wires. She answers in the listen pose with the live mouth sprite placed
  by the frame's head transform (the library has no wire-less talk loop; this is its closest match).
- Live eyes: while a frame carries an eye transform (listen/talk/notice/leans), her irises follow your head
  (eye sprites drawn into her picture on the same tick as the body frame).
- Leans: your head > 15 cm to her side (released < 10 cm) while idle or listening. Nothing else follows your position.
- Lip sync: <id>.vis.json from the PC (brain/tts/lipsync.py); no track -> a synthetic one from the reply's length.
- connect clip when her panel appears, disconnect before it hides; notice_you if the menu was closed > 2 min.
- No on-screen text, no sound effects (only her voice). Shows only while streaming from the PC and the menu is really open.
Log: ~/.local/state/lainframe/lain.log. Config: ~/.config/lainframe/lain.json (see placement())."""
import bisect, ctypes, glob, json, math, os, random, struct, sys, time, zlib
from collections import deque, OrderedDict
from concurrent.futures import ThreadPoolExecutor

# ---- paths (Lainframe layout: code ~/lainframe/<part>, libs ~/lainframe/lib, config ~/.config/lainframe,
# state + logs ~/.local/state/lainframe)
HERE = os.path.dirname(os.path.abspath(__file__))                 # ~/lainframe/lain
ROOT = os.path.dirname(HERE)                                       # ~/lainframe
sys.path.insert(0, os.path.join(ROOT, "lib"))                     # vendored pyopenvr + Pillow (aarch64)
import openvr  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402
import voice   # noqa: E402  (the recorder + state machine, next to this file)

CONF_DIR = os.path.expanduser("~/.config/lainframe")
STATE = os.path.expanduser("~/.local/state/lainframe")
CONFIG = os.path.join(CONF_DIR, "lain.json")
CLIPS = os.path.join(HERE, "clips_grok")
BAKED = os.path.join(HERE, "clips_baked")
VOICE_DIR = os.path.join(STATE, "voice")                          # wav / reply / done exchange with the PC
CLICKS = os.path.join(STATE, "clicks")                            # "voice <id>" lines the PC bridge tails
LOG = os.path.join(STATE, "lain.log")
RESTART_REQ = os.path.join(STATE, "restart.req")                  # touch it: she restarts herself once idle
REL_FILE = os.path.join(STATE, "menu_rel.json")                   # where she sits relative to the dock bar
# "Wake up, Lain": wake_link.py records the mic ONLY while WAKE_ARMED is fresh (touched here every second while she's on
# the open menu and the voice loop is idle); on the phrase it touches WAKE_REQ = a click.
WAKE_ARMED = os.path.join(STATE, "wake_armed")
WAKE_REQ = os.path.join(STATE, "wake.req")
os.makedirs(STATE, exist_ok=True)

# ---- overlay keys: ours, and the Steam UI panels we read (the big menu has no readable transform: found by a ray fit)
KEY_PANEL, KEY_HIT = "lainframe.lain", "lainframe.lain.hit"
STEAM_MENU, STEAM_BAR = "valve.steam.gamepadui.main", "valve.steam.gamepadui.bar"

IDLE_DAY = {"rest_a": 12, "rest_b": 10, "rest_c": 10, "still_a": 9, "look_around_l": 6, "look_around_r": 6, "peek_l": 4, "peek_r": 4,
            "sigh": 5, "doze_short": 1, "shy_glance": 2}
IDLE_NIGHT = dict(IDLE_DAY, rest_night_a=10, rest_night_b=10, doze_short=3, look_around_l=3, look_around_r=3, peek_l=3, peek_r=3)
# Comfort: idle clips with the aqua Wired glitch flash baked in are never played (bright flashes hurt in a headset; the
# wire clips are fine). connect/disconnect/think_open are skipped too: she is always Wired-blue, no load-in/out glitch.
NO_FLASH = {"rest_b", "rest_c", "look_around_l", "look_around_r", "peek_l", "peek_r",
            "connect", "disconnect", "think_open"}
REACTIONS = ("listen_nod", "listen_blink", "listen_tilt")
THINK_OPEN_S = 15.0                 # eyes open, no wires for the first 15 s of thinking
SLEEP_DAY_S, SLEEP_NIGHT_S = 900.0, 480.0            # idle this long -> she sleeps (300 / 120 felt like too much); restarts when the menu opens
NOTICE_AFTER_S = 120.0              # menu closed this long -> she notices you when it reopens
LEAN_ON_M, LEAN_OFF_M = 0.15, 0.10
LISTEN_CUT_FRAMES = 30              # on attention: cut an idle clip at a calm frame within 1 s, else at once
HURRY = 24                          # frames of a head turn's way back kept when a clip is cut mid-turn
# Calm idles that may ship eyes[] in clips.json: they always play with their baked eyes (live eyes there roam).
BAKED_EYE_IDLES = ("still_a", "rest_a")
# Eye-jump fix: baked iris gaze of the idle clips per frame ([gx, gy] x100 in eye-sprite units, null = irises not cleanly
# visible), computed from the same motion laws the PNGs were rendered with. When a frame with live eyes follows a frame
# with baked eyes (you call her mid-glance -> enter_listen), the eyes start at the baked gaze and saccade to their target
# over SACCADE_FRAMES (100 ms) instead of jumping there in one frame.
SACCADE_FRAMES = 3
IDLE_GAZE = (
    "eNrtnN1uqzAMgN9l1yDhhNB2r1JNqNtQWxXB1HYX5xyddx9gZwNKK2ghC+Abf6nWtWl+bMd2+Pd0jE7ncPP0vF57jvfisGyQrkSAjxT0WgRjYPIZ"
    "x41iLD/AIBfEJdMq0ryAotc2qonr+4w1aLN8cdD8vI7b/OBqBDQKZBtIo1RwdYH0KBq/uD1MdJEFi/qiRf3eAeiJASBmpi/fbNGXK5wMhJRDwcga"
    "tL+LLFiwZ9lNX57O+zjm+EYlmiEcKA5T4AQUzQC/iHJ4DiyLBnCjWyMzgdjITqggc5fEKwY3c1fgx0I+BjOeWB89ZQyKbNXl+1X6uNSkwrVnPbPN"
    "ku8J8J1F4bTDXIxQnKaHcHNMP5P3MP59U5TpJjfAI79bzEg2Q64QDzfMuOn99NVop1kMuiRcuaI0zahpZqwyjwQ3wGAtXpMsmrcpZXGYHanTz0G3"
    "7FfN8zjafgh29e+jNLuk7J/vlWlmrVa/817yvp+Ec0GH/ek1AlPbSdLW7oe8MFk0Bq/QYHTAXNOIH1F0sCEUYXPZTq9RC6HDDj03eN+zGJGCtiKK"
    "rh5V+lqBWnyiglJlGh4f0dQFpboNPQJkBPFPQIMEZQNJQ6aLb5YTyFHxfmTBdR7D1l7st7vpuJgulKNv+kqIX4lcUcAK9H/Iatk66HJ2XYhBnyVU"
    "7RqCfp/OD+hrKFCjuMVbx3HR5gMmRMWRZCZzMIqaoptPJOU9/RuFp116PFufXoGqVdJW5j6laihuPCpDw2MyC/7so6KcTWH5bLad8sQKH1dYsJhD"
    "LFNVQmOMruDAySwu4Oz+hNt4k7xFdf/42x+9AdEasiv0kaUoQwdHFiHy3KAvnCUGx0GQeVc50byvhXAEYGRcSCyiFgpj4yJAN+CCqiX9Prm6j9Lr"
    "SDBP1cC8/8V8eHgrIhuGIgHi+k2QTRBNgGuQpdzK7Sugl2+tSNFCwhV5eTc42W931j3Qx9UBTuDnzBh4sE+/BeM81sNweSWoz2R+01BIqfbdtDar"
    "yf9gxhD64twcHzeCLsUrVwu2iq4HtZwuc4Q05FpNbOwo/UdePiUHGYxBYKZw+84uikqJ5Sht/3m3Tw5h+hElU7b8QNMWtISZVRd069Sv9ZQF15Ly"
    "g3fruvP/F9j2gws=")


def log(*a):
    with open(LOG, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")


def mat34(rows):
    m = openvr.HmdMatrix34_t()
    for r in range(3):
        for c in range(4): m.m[r][c] = rows[r][c]
    return m


def to_rows(m): return [[m.m[r][c] for c in range(4)] for r in range(3)]


def mul(a, b):
    out = [[0.0] * 4 for _ in range(3)]
    for r in range(3):
        for c in range(4): out[r][c] = sum(a[r][k] * b[k][c] for k in range(3)) + (a[r][3] if c == 3 else 0.0)
    return out


def aff_inv(M):
    a, b, c = M[0][:3]; d, e, f = M[1][:3]; g, h, i = M[2][:3]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    R = [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
         [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
         [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]
    t = [-sum(R[r][k] * M[k][3] for k in range(3)) for r in range(3)]
    return [R[r] + [t[r]] for r in range(3)]


def pc_linked():
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                if os.path.basename(os.readlink(f"/proc/{d}/exe")) == "vrlink": return True
            except OSError: pass
    return False


def png_size(path, _c={}):
    if path not in _c:
        try:
            with open(path, "rb") as f: hd = f.read(24)
            _c[path] = (int.from_bytes(hd[16:20], "big"), int.from_bytes(hd[20:24], "big"))
        except OSError: return (1, 1)
    return _c[path]


def hit_png(w, h):
    """nearly invisible click target (black, alpha 1: SteamVR blends premultiplied, so it never shows). No hover effect."""
    import zlib
    path = os.path.join(STATE, f"hit_{w}x{h}.png")
    if not os.path.exists(path):
        raw = b"".join(b"\x00" + bytes([0, 0, 0, 1]) * w for _ in range(h))
        def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
                               chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def wav_seconds(path):
    """length of a WAV (PCM or float) from its header, 0.0 if unreadable."""
    try:
        with open(path, "rb") as f: d = f.read(1 << 16)
        if d[:4] != b"RIFF" or d[8:12] != b"WAVE": return 0.0
        i = 12; rate = None; size = os.path.getsize(path)
        while i + 8 <= len(d):
            cid, n = d[i:i + 4], struct.unpack("<I", d[i + 4:i + 8])[0]
            if cid == b"fmt ": rate = struct.unpack("<I", d[i + 16:i + 20])[0]            # byte rate
            if cid == b"data" and rate: return min(n, size - i - 8) / float(rate)
            i += 8 + n + (n & 1)
    except (OSError, struct.error): pass
    return 0.0


def placement():
    # width: panel width as a fraction of the menu width (centred). drop_m: panel bottom below the menu's top edge
    # (0 = flush). bottom_pad_px: transparent rows under her silhouette. hit_box: her silhouette inside the panel as
    # fractions [left, top, right, bottom]. hit_forward_m: click target this far in front of her. lips / lips_offset_s:
    # lip sync on/off and its delay (bigger = mouth later). utc_offset_min: local time for the night mood if the Frame's
    # clock is in another timezone (optional). wake: the "Wake up, Lain" phrase. wired: her colours (see WIRED).
    p = {"width": 0.75, "drop_m": 0.0, "bottom_pad_px": 0, "toward_you": 0.0, "sort": 7, "hit_sort": 12,
         "hit_box": [0.12, 0.05, 0.91, 1.0], "hit_forward_m": 0.03, "wake": True, "lips": True, "lips_offset_s": 0.08}
    for f in (os.path.join(HERE, "lain.json"), CONFIG):           # shipped defaults, then the user's copy
        try: p.update(json.load(open(f)))
        except Exception: pass
    return p


def is_night(P):
    if P.get("utc_offset_min") is not None: h = time.gmtime(time.time() + 60 * float(P["utc_offset_min"])).tm_hour
    else: h = time.localtime().tm_hour
    return h >= 23 or h < 7


def menu_top(ov, hp, head_yaw):
    """the big Steam menu panel (valve.steam.gamepadui.main, no readable transform): fit world = O + u*U + v*V to ray
    hits from the head. Returns (centre of its top edge, x right, y up, z toward you, width, height) or None."""
    try: h = ov.findOverlay(STEAM_MENU)
    except openvr.OpenVRError: return None
    # The menu is CURVED: a flat fit tilts its x axis toward whichever side got more ray hits (one shoulder further away,
    # not flush). A (u - 0.5)^2 term takes the bend: U is then the exact tangent at the
    # menu's centre and O + 0.5 U + V its top centre.
    hits = []
    for yaw in range(-100, 101, 5):
        for pitch in range(-60, 41, 5):
            a, b = math.radians(yaw) + head_yaw, math.radians(pitch)
            d = (-math.sin(a) * math.cos(b), math.sin(b), -math.cos(a) * math.cos(b))
            q = openvr.VROverlayIntersectionParams_t()
            for k in range(3): q.vSource.v[k] = hp[k]; q.vDirection.v[k] = d[k]
            q.eOrigin = openvr.TrackingUniverseStanding
            ok, r = ov.computeOverlayIntersection(h, q)
            if not ok: continue
            hits.append((r.vUVs.v[0], r.vUVs.v[1], tuple(r.vPoint.v)))
    n = len(hits)
    if n < 8: return None
    us = [h_[0] for h_ in hits]
    M = 4 if n >= 12 and max(us) - min(us) > 0.45 else 3        # the bend term needs hits across the width
    S = [[0.0] * M for _ in range(M)]; T = [[0.0] * 3 for _ in range(M)]
    for u_, v_, pt in hits:
        f = (1.0, u_, v_, (u_ - 0.5) ** 2)[:M]
        for i in range(M):
            for j in range(M): S[i][j] += f[i] * f[j]
            for j in range(3): T[i][j] += f[i] * pt[j]
    A = [S[i] + T[i] for i in range(M)]
    for c in range(M):
        p = max(range(c, M), key=lambda r: abs(A[r][c])); A[c], A[p] = A[p], A[c]
        if abs(A[c][c]) < 1e-9: return None
        for r in range(M):
            if r != c: f = A[r][c] / A[c][c]; A[r] = [x - f * y for x, y in zip(A[r], A[c])]
    O, U, V = ([A[r][M + k] / A[r][r] for k in range(3)] for r in range(3))
    if V[1] < 0: O = [o + v for o, v in zip(O, V)]; V = [-v for v in V]
    nu = math.sqrt(sum(x * x for x in U)); nv = math.sqrt(sum(x * x for x in V))
    if not (0.5 < nu < 3.0 and 0.3 < nv < 2.5): return None
    x = [c / nu for c in U]; y = [c / nv for c in V]
    z = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]]
    top = [O[k] + U[k] * 0.5 + V[k] for k in range(3)]
    if sum(z[k] * (hp[k] - top[k]) for k in range(3)) < 0: z = [-c for c in z]; x = [-c for c in x]
    log("menu fit:", n, "hits" + (" (curved)" if M == 4 else " (flat)") + ", size", round(nu, 2), "x", round(nv, 2), "top centre", [round(c, 2) for c in top])
    return top, x, y, z, nu, nv


# ------------------------------------------------------------------ lip sync
class LipTrack:
    """mouth shapes over time for the reply now playing. From <id>.vis.json (brain/tts on the PC):
    {"fps": 30, "seconds": s, "events": [{"t": sec, "shape": "closed|small|open|A|I|U|E|O"}], "fallback": {...}},
    t = seconds from the start of the reply audio. voice.py starts pw-play inside vs.update() in the same call that
    switches thinking -> speaking; the player stamps that moment. lips_offset_s covers pw-play's start-up."""
    def __init__(self):
        self.t0 = None; self.ts = []; self.shapes = []; self.end = 0.0; self.fallback = {}

    def start(self, path, t_audio, offset):
        try: d = json.load(open(path))
        except (OSError, ValueError) as e: log("lips: no track", os.path.basename(path), repr(e)); self.t0 = None; return False
        ev = d.get("events") or []
        self.ts = [float(e["t"]) for e in ev]; self.shapes = [e["shape"] for e in ev]
        self.end = float(d.get("seconds", self.ts[-1] if self.ts else 0.0)); self.fallback = d.get("fallback", {})
        self.t0 = t_audio + offset
        log("lips: track", os.path.basename(path), len(ev), "events", round(self.end, 1), "s")
        return True

    def synth(self, seconds, t_audio, offset):
        """no track from the PC (fallback voice): plausible syllables for the length of the reply."""
        rng = random.Random(int(t_audio)); t = 0.0; self.ts = []; self.shapes = []
        while t < seconds:
            if rng.random() < 0.12: s, d = "closed", rng.uniform(0.15, 0.35)
            else: s, d = rng.choice(("small", "open", "A", "E", "O", "small", "open")), rng.uniform(0.08, 0.2)
            self.ts.append(round(t, 3)); self.shapes.append(s); t += d
        self.end = seconds; self.fallback = {"A": "open", "O": "open", "E": "small", "I": "small", "U": "small"}
        self.t0 = t_audio + offset
        log("lips: synthetic track", round(seconds, 1), "s")
        return seconds > 0

    def stop(self): self.t0 = None

    @property
    def active(self): return self.t0 is not None

    def shape_at(self, now):
        if self.t0 is None: return "closed"
        t = now - self.t0
        if t < 0 or t >= self.end or not self.ts: return "closed"
        return self.shapes[max(0, bisect.bisect_right(self.ts, t) - 1)]


_mouth_cache = {}


def mouth_sprite(clip, frame_png, shape, fallback):
    """the mouth sprite for `shape`: per-frame (clips_grok/<clip>/mouth/<shape>/<NNN>.png, the *_lips talk loops, placed
    already) or the shared rest-pose sprite (clips_grok/mouth/<shape>.png, moved by the frame's head transform).
    Returns (path, per_frame) or (None, False)."""
    key = (clip, os.path.basename(frame_png or ""), shape)
    if key not in _mouth_cache:
        out = (None, False)
        for s in (shape, fallback.get(shape), "open" if shape != "closed" else None):
            if not s: continue
            p = os.path.join(CLIPS, clip, "mouth", s, os.path.basename(frame_png or ""))
            if clip and os.path.isfile(p): out = (p, True); break
            p = os.path.join(CLIPS, "mouth", s + ".png")
            if os.path.isfile(p): out = (p, False); break
        _mouth_cache[key] = out
    return _mouth_cache[key]


# ------------------------------------------------------------------ the clip library + pose graph
def clip_poses(n):
    """(start pose, end pose) of a clip, or None for clips the player never uses."""
    if n.startswith("listen_to_think"): return None                       # wires straight from listening: breaks the 15 s rule
    if n == "enter_listen": return ("rest", "listen")
    if n == "exit_listen": return ("listen", "rest")
    if n == "listen_loop" or n in REACTIONS: return ("listen", "listen")
    for pre, base in (("listen_lean_", "listen"), ("lean_", "rest")):
        if n.startswith(pre):
            side, part = n[len(pre):].split("_", 1); lp = ("llean_" if base == "listen" else "lean_") + side
            return {"in": (base, lp), "loop": (lp, lp), "out": (lp, base)}.get(part)
    if n.startswith("enter_think"): return ("rest", "wired")
    if n.startswith("think_loop"): return ("wired", "wired")
    if n.startswith("answer"): return ("wired", "talk")
    if n.startswith("talk_"): return ("talk", "talk")
    if n.startswith("wires_out"): return ("talk", "rest")
    if n == "enter_sleep": return ("rest", "sleep")
    if n == "sleep_loop": return ("sleep", "sleep")
    if n == "wake": return ("sleep", "rest")
    return ("rest", "rest")                                                  # idles, think_open, connect, notice_you, ...


class Clips:
    """the clip library and the pose graph that chains it. mode (what the voice loop wants) -> target pose + loop."""
    def __init__(self, clips_dir=None):
        d = clips_dir or CLIPS
        meta = json.load(open(os.path.join(d, "clips.json")))
        self.files = {n: sorted(glob.glob(os.path.join(d, n, "*.png"))) for n in meta}
        self.meta = {n: m for n, m in meta.items() if self.files.get(n) and clip_poses(n) and n not in NO_FLASH}
        first = next(iter(self.meta))
        self.fps = float(self.meta[first].get("fps", 30)); self.w, self.h = png_size(self.files[first][0])
        try: self.cuts = json.load(open(os.path.join(d, "cuts.json")))     # per frame '1' = calm (close to the clip's start pose)
        except (OSError, ValueError): self.cuts = {}
        try: self.eyes = json.load(open(os.path.join(d, "eyes.json")))
        except (OSError, ValueError): self.eyes = None
        for n in BAKED_EYE_IDLES:                                            # baked eyes only (see BAKED_EYE_IDLES)
            if n in self.meta and self.meta[n].get("eyes"): self.meta[n] = {k: v for k, v in self.meta[n].items() if k != "eyes"}
        try:
            import base64
            self.bgaze = json.loads(zlib.decompress(base64.b64decode("".join(IDLE_GAZE))))
        except Exception as e: self.bgaze = {}; log("idle gaze table unusable:", repr(e))
        self.head = {}                                                       # per frame head transform (eye entries, gaps filled)
        for n, m in self.meta.items():
            ev = m.get("eyes")
            if ev and any(ev):
                known = [i for i, e in enumerate(ev) if e]
                self.head[n] = [ev[min(known, key=lambda k: abs(k - i))][:6] for i in range(len(ev))]
        self.pose = {n: clip_poses(n) for n in self.meta}
        self.families = sorted({m["family"] for m in self.meta.values() if m.get("family")})
        self.family = None; self.rng = random.Random()
        self.cur = None; self.i = 0; self.queue = []; self.prefix = []; self.hold = 0; self.pose_now = "rest"
        self.mode = "idle"; self.lean = None; self.react = None; self.lips = False; self.night = False
        self.cut = False; self.cut_left = None; self.closing = False; self.closed = False
        self.at = (None, None, None)                                          # (clip, frame index, file) now going up
        log("clips:", len(self.meta), "frames", sum(len(self.files[n]) for n in self.meta), "size", self.w, "x", self.h,
            "fps", self.fps, "cuts" if self.cuts else "no cuts.json", "eyes" if self.eyes else "no eyes.json")

    # ---- graph
    def fam_ok(self, n):
        f = self.meta[n].get("family")
        return not f or f == (self.family or (self.families[0] if self.families else None))

    def path(self, a, b):
        prev = {a: None}; dq = deque([a])
        while dq:
            p = dq.popleft()
            if p == b: break
            for n, (s, e) in self.pose.items():
                if s == p and e != s and e not in prev and self.fam_ok(n) and not n.endswith("_lips"):
                    prev[e] = (p, n); dq.append(e)
        if b not in prev: return None
        out = []; x = b
        while prev[x]: p, n = prev[x]; out.append(n); x = p
        return out[::-1]

    def want_pose(self):
        m = self.mode
        if m == "idle": return f"lean_{self.lean}" if self.lean else "rest"
        if m == "listen": return f"llean_{self.lean}" if self.lean else "listen"
        return {"talk_open": "listen", "think_open": "rest", "think": "wired", "talk": "talk", "sleep": "sleep"}.get(m, "rest")

    def F(self): return f"_{self.family}" if self.family else ""

    def talkname(self, k):
        """while a lip track plays, a talk loop's closed-mouth twin <name>_lips replaces it (the mouth sprites go on top)."""
        return k + "_lips" if self.lips and (k + "_lips") in self.meta else k

    def pick_idle(self):
        tab = IDLE_NIGHT if self.night else IDLE_DAY
        names = [n for n in tab if n in self.meta]
        return self.rng.choices(names, [tab[n] for n in names])[0] if names else None

    def loop_clip(self, pose):
        if pose == "rest":
            if self.mode == "think_open" and "think_open" in self.meta: return "think_open"
            return self.pick_idle()
        if pose == "listen":
            if self.react and self.mode == "listen": r = self.react; self.react = None; return r
            return "listen_loop"
        if pose == "wired": return f"think_loop{self.F()}"
        if pose == "talk":
            talks = [k for k in (f"talk_0{self.F()}", f"talk_1{self.F()}", f"talk_2{self.F()}") if k in self.meta]
            return self.talkname(self.rng.choice(talks)) if talks else None
        if pose == "sleep": return "sleep_loop"
        if pose.startswith("lean_"): return f"lean_{pose[5:]}_loop"
        if pose.startswith("llean_"): return f"listen_lean_{pose[6:]}_loop"
        return None

    def next_clip(self):
        if self.prefix: return self.prefix.pop(0)
        if self.queue: return self.queue.pop(0)
        want = self.want_pose()
        if want == "wired" and self.family is None and self.families: self.family = self.rng.choice(self.families)
        if self.pose_now != want:
            p = self.path(self.pose_now, want)
            if p: self.queue = p[1:]; return p[0]
            log("no clip path", self.pose_now, "->", want, ": jumping"); self.pose_now = want
        n = self.loop_clip(want)
        return n if n in self.meta else None

    # ---- control
    def cuttable(self, n):
        m = self.meta.get(n, {})
        return bool(m.get("loop")) or n in IDLE_NIGHT or n in REACTIONS or n == "notice_you"

    def request_cut(self, limit=None):
        if self.cur and self.cuttable(self.cur) and not self.closing:
            self.cut = True; self.cut_left = limit

    def set_mode(self, mode):
        if mode == self.mode: return
        log("mode", self.mode, "->", mode, "(pose", self.pose_now + ", clip", str(self.cur) + ")")
        self.mode = mode; self.queue = []
        if mode not in ("listen",): self.react = None
        if mode not in ("idle", "listen"): self.lean = None
        self.request_cut(LISTEN_CUT_FRAMES if mode == "listen" else None)

    def set_lean(self, side):
        if side == self.lean: return
        log("lean", self.lean, "->", side); self.lean = side; self.queue = []
        if self.cur and (self.cur in IDLE_NIGHT or "lean" in self.cur or self.cur == "listen_loop"): self.request_cut()

    def fire_reaction(self, name):
        if self.mode == "listen" and not self.lean and self.cur == "listen_loop" and name in self.meta:
            self.react = name; self.request_cut(30); return True
        return False

    def on_show(self, notice):
        """her panel appears: the Wired 'connect' (+ 'notice_you' after a long absence), from the rest pose."""
        self.closing = self.closed = False; self.cut = False; self.queue = []; self.hold = 0
        self.prefix = [n for n in (["connect"] + (["notice_you"] if notice else [])) if n in self.meta]
        self.cur = None; self.pose_now = "rest"
        if self.family and self.mode not in ("think", "talk"): self.family = None

    def disconnect(self):
        """the menu closed: 'disconnect' at once, then she's hidden (closed=True)."""
        self.closing = True; self.closed = "disconnect" not in self.meta; self.cut = False; self.prefix = []; self.queue = []
        if not self.closed: self.cur = "disconnect"; self.i = 0; self.hold = 0; self.pose_now = "rest"

    def is_safe(self, n, i):
        c = self.cuts.get(n)
        return c is None or i >= len(c) or c[i] == "1"

    def next_frame(self):
        """the file to show on this tick (None while the current frame is held)."""
        if self.hold > 1:
            self.hold -= 1; return None
        if self.cut and self.cur:
            if self.is_safe(self.cur, self.i) or (self.cut_left is not None and self.cut_left <= 0): self.cur = None; self.cut = False
            else:
                # mid head turn: skip the rest of the held turn and play only its way back (<= HURRY frames), so she
                # turns back to the front at once instead of popping (or making you wait out the whole glance)
                c = self.cuts.get(self.cur, ""); j = self.i
                while j < len(c) and c[j] == "0": j += 1
                if j - self.i > HURRY: self.i = j - HURRY
                if self.cut_left is not None: self.cut_left -= 1
        if self.cur is None or self.i >= len(self.files[self.cur]):
            if self.closing:
                self.closed = True; return None
            if self.cur and self.cur.startswith("wires_out"): self.family = None          # unplugged: next time a new layout
            self.cut = False
            nxt = self.next_clip()
            if nxt is None: return None
            self.cur = nxt; self.i = 0; self.pose_now = self.pose[nxt][1]
        f = self.files[self.cur][self.i]
        hl = self.meta[self.cur].get("holds"); self.hold = hl[self.i] if hl and self.i < len(hl) else 1
        self.at = (self.cur, self.i, f); self.i += 1
        return f

    def eye_entry(self):
        n, i, _ = self.at
        ev = self.meta.get(n, {}).get("eyes") if n else None
        return ev[i] if ev and i is not None and i < len(ev) else None

    def baked_gaze(self):
        """the baked iris gaze (eye-sprite units) of the frame going up now, None if unknown / irises not visible."""
        n, i, _ = self.at
        g = self.bgaze.get(n) if n else None
        v = g[i] if g and i is not None and i < len(g) else None
        return (v[0] / 100.0, v[1] / 100.0) if v else None

    def head_T(self):
        n, i, _ = self.at
        h = self.head.get(n)
        return h[i] if h and i is not None and i < len(h) else None


def layer_rows(rows, T, w_px, h_px, m_per_px):
    """overlay transform for a full-panel sprite moved by the frame transform T = [a,b,c,d,e,f] (canvas px, y down):
    the sprite's pixel (x, y) lands on the panel's pixel (a x + b y + c, d x + e y + f)."""
    a, b, c, d, e, f = T
    tx = a * w_px / 2 + b * h_px / 2 + c - w_px / 2; ty = h_px / 2 - d * w_px / 2 - e * h_px / 2 - f
    return mul(rows, [[a, -b, 0.0, tx * m_per_px], [-d, e, 0.0, ty * m_per_px], [0.0, 0.0, 1.0, 0.0]])


_POOL = None
_CACHE = OrderedDict()                       # decoded frames (eye sprites and loops repeat): path -> (w, h, bytes)


# She is always Wired-blue and a little see-through, as if she were in the Wired. Every frame is recoloured on decode:
# luminance -> navy shadows / blue-aqua mids / pale cyan highlights, alpha x WIRED["alpha"].
# lain.json: "wired": {"on": true, "alpha": 0.8, "black": [...], "mid": [...], "white": [...]}
WIRED = {"on": True, "alpha": 0.8, "black": [6, 12, 34], "mid": [38, 104, 168], "white": [176, 236, 255]}


def wired(im):
    a = im.getchannel("A")
    if WIRED["alpha"] < 0.999: a = a.point(lambda v: int(v * WIRED["alpha"]))
    out = ImageOps.colorize(im.convert("L"), tuple(WIRED["black"]), tuple(WIRED["white"]), mid=tuple(WIRED["mid"]))
    out.putalpha(a)
    return out


def decode(path):
    """-> (w, h, RGBA bytes, crop). PNG decode + recolour per frame lagged on the Frame, so the PC pre-bakes every image
    (art_pipeline/bake_rgbz.py: Wired colour + alpha, cropped to its visible pixels, raw RGBA zlib) into
    clips_baked/<same path>.rgbz, so this only inflates (~3 ms) a small patch; crop = (x0, y0, full_w, full_h) places
    it. Fallback for anything not baked: PNG via Pillow + the Wired recolour here (crop None). Worker threads."""
    hit_ = _CACHE.get(path)
    if hit_ is not None: return hit_
    bp = os.path.join(BAKED, os.path.relpath(path, CLIPS))[:-4] + ".rgbz" if path.startswith(CLIPS) else None
    if bp and os.path.exists(bp):
        with open(bp, "rb") as f: raw = f.read()
        x0, y0, w, h, W, H = struct.unpack("<6H", raw[4:16])
        out = (w, h, zlib.decompress(raw[16:]), (x0, y0, W, H))
    else:
        im = Image.open(path)
        if im.mode != "RGBA": im = im.convert("RGBA")
        if WIRED["on"]: im = wired(im)
        out = (im.width, im.height, im.tobytes(), None)
    _CACHE[path] = out
    while len(_CACHE) > 48: _CACHE.popitem(last=False)
    return out


class GL:
    """one surfaceless EGL + desktop OpenGL context (Mesa) in the main thread, for her textures."""
    gl = None

    @classmethod
    def init(cls):
        if cls.gl is not None: return
        egl = ctypes.CDLL("libEGL.so.1"); gl = ctypes.CDLL("libGL.so.1"); vp = ctypes.c_void_p
        egl.eglGetPlatformDisplay.restype = vp; egl.eglGetPlatformDisplay.argtypes = [ctypes.c_uint, vp, vp]
        egl.eglInitialize.argtypes = [vp, vp, vp]; egl.eglChooseConfig.argtypes = [vp, vp, vp, ctypes.c_int, vp]
        egl.eglCreateContext.restype = vp; egl.eglCreateContext.argtypes = [vp, vp, vp, vp]
        egl.eglMakeCurrent.argtypes = [vp, vp, vp, vp]
        egl.eglGetProcAddress.restype = vp; egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
        dpy = egl.eglGetPlatformDisplay(0x31DD, None, None)                   # EGL_PLATFORM_SURFACELESS_MESA
        if not dpy or not egl.eglInitialize(dpy, None, None) or not egl.eglBindAPI(0x30A2): raise RuntimeError("EGL init failed")
        attr = (ctypes.c_int * 3)(0x3040, 0x0008, 0x3038)                    # EGL_RENDERABLE_TYPE = EGL_OPENGL_BIT
        cfg = vp(); n = ctypes.c_int(); egl.eglChooseConfig(dpy, attr, ctypes.byref(cfg), 1, ctypes.byref(n))
        ctx = egl.eglCreateContext(dpy, cfg, None, None)
        if not ctx or not egl.eglMakeCurrent(dpy, None, None, ctx): raise RuntimeError("EGL context failed")
        F, D, U, I = ctypes.c_float, ctypes.c_double, ctypes.c_uint, ctypes.c_int
        for name, args in (("glOrtho", [D] * 6), ("glColor4f", [F] * 4), ("glTexCoord2f", [F] * 2), ("glVertex2f", [F] * 2),
                           ("glClearColor", [F] * 4), ("glTexEnvf", [U, U, F])):
            getattr(gl, name).argtypes = args

        def ext(name, args, res=None):                                        # GL 1.4 / 3.0 entry points
            setattr(gl, "x_" + name, ctypes.CFUNCTYPE(res, *args)(egl.eglGetProcAddress(name.encode())))
        ext("glGenFramebuffers", [I, vp]); ext("glBindFramebuffer", [U, U]); ext("glFramebufferTexture2D", [U, U, U, U, I])
        ext("glCheckFramebufferStatus", [U], U); ext("glBlendFuncSeparate", [U, U, U, U])
        cls.gl = gl


def _new_tex(gl, w, h, data):
    t = ctypes.c_uint(); gl.glGenTextures(1, ctypes.byref(t)); gl.glBindTexture(0x0DE1, t.value)
    gl.glTexParameteri(0x0DE1, 0x2801, 0x2601); gl.glTexParameteri(0x0DE1, 0x2800, 0x2601)     # linear
    gl.glTexParameteri(0x0DE1, 0x2802, 0x812F); gl.glTexParameteri(0x0DE1, 0x2803, 0x812F)     # clamp to edge
    gl.glTexImage2D(0x0DE1, 0, 0x8058, w, h, 0, 0x1908, 0x1401, data)
    return t.value


class GLLayer:
    """one image (body frame, eye sprite, mouth sprite) decoded on a worker thread into its own GL texture; GLPanel draws
    it into her one composite picture. stage(path, T): T = [a,b,c,d,e,f] canvas-px transform of the sprite (None = as
    is); stage(None) = not drawn from the next commit."""
    def __init__(self):
        global _POOL
        if _POOL is None: _POOL = ThreadPoolExecutor(max_workers=3)
        self.cur = None; self.want = None; self.fut = None; self.T = None; self.wantT = None
        self.size = None; self.tid = None; self.crop = None

    def stage(self, path, T=None):
        self.want = path; self.wantT = T
        if path is not None and path != self.cur and (self.fut is None or self.fut[0] != path):
            self.fut = (path, _POOL.submit(decode, path))

    def width(self, w): pass

    def hide(self): self.want = None

    def update(self):
        """upload the staged frame once it's decoded -> what gets drawn: (path, T), or None."""
        if self.want is None: return None
        if self.want != self.cur and self.fut is not None and self.fut[0] == self.want:
            try:
                w, h, data, self.crop = self.fut[1].result(); gl = GL.gl
                if self.tid is None or self.size != (w, h):
                    if self.tid is not None: gl.glDeleteTextures(1, ctypes.byref(ctypes.c_uint(self.tid)))
                    self.tid = _new_tex(gl, w, h, data); self.size = (w, h)
                else:
                    gl.glBindTexture(0x0DE1, self.tid); gl.glTexSubImage2D(0x0DE1, 0, 0, 0, w, h, 0x1908, 0x1401, data)
                self.cur = self.want
            except Exception as e: log("frame error:", self.want, repr(e))
            self.fut = None
        if self.cur is None: return None
        self.T = self.wantT
        return (self.cur, tuple(self.T) if self.T else None)

    def draw(self, gl):
        x0, y0 = self.crop[:2] if self.crop else (0, 0); w, h = self.size
        a, b, c, d, e, f = self.T if self.T else (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        gl.glMatrixMode(0x1700); gl.glLoadMatrixf((ctypes.c_float * 16)(a, d, 0, 0, b, e, 0, 0, 0, 0, 1, 0, c, f, 0, 1))
        gl.glBindTexture(0x0DE1, self.tid); gl.glBegin(0x0007)
        for u, v in ((0, 0), (1, 0), (1, 1), (0, 1)):
            gl.glTexCoord2f(u, v); gl.glVertex2f(x0 + u * w, y0 + v * h)
        gl.glEnd()


class GLPanel:
    """her one overlay. On SteamOS 0.4.5's SteamVR every setOverlayFromFile of a new image leaks ~3.5 MB in vrcompositor
    for good (lag, then crashes, frames missing), and re-using file paths shows stale frames, so she is a GL texture we
    own, submitted with setOverlayTexture (1 ms per frame, zero growth, no gap).
    Eyes and mouth used to be overlays of their own, each 80% see-through, so where the mouth patch sat on her face the
    two stacked into a brighter box around her mouth during lip sync. Now body +
    eyes + mouth are drawn into one full-canvas picture at full strength (FBO) and the overlay as a whole gets the Wired
    see-through (setOverlayAlpha). stage() decodes on a worker thread; commit() draws on the next tick."""
    def __init__(self, ov, o, W, H, layers=()):
        self.ov, self.o, self.W, self.H = ov, o, W, H; self.src = GLLayer(); self.layers = list(layers)
        self.rows = None; self.on = False; self.base_w = None; self.sent = None; self.drawn = None; self.fbo = None
        b = openvr.VRTextureBounds_t(); b.uMin, b.vMin, b.uMax, b.vMax = 0.0, 1.0, 1.0, 0.0   # GL rows are bottom-up
        ov.setOverlayTextureBounds(o, b)
        ov.setOverlayAlpha(o, float(WIRED["alpha"]) if WIRED["on"] else 1.0)

    def width(self, w): self.base_w = w; self._apply()

    def place(self, rows): self.rows = rows; self._apply()

    def _apply(self):
        if self.base_w is None or self.rows is None: return
        if self.sent != self.base_w: self.ov.setOverlayWidthInMeters(self.o, self.base_w); self.sent = self.base_w
        self.ov.setOverlayTransformAbsolute(self.o, openvr.TrackingUniverseStanding, mat34(self.rows))

    def stage(self, path, rows=None):
        if rows is not None: self.rows = rows
        self.src.stage(path)

    def _compose(self):
        gl = GL.gl; W, H = self.W, self.H
        if self.fbo is None:
            self.ftex = _new_tex(gl, W, H, None); f = ctypes.c_uint(); gl.x_glGenFramebuffers(1, ctypes.byref(f)); self.fbo = f.value
            gl.x_glBindFramebuffer(0x8D40, self.fbo); gl.x_glFramebufferTexture2D(0x8D40, 0x8CE0, 0x0DE1, self.ftex, 0)
            st = gl.x_glCheckFramebufferStatus(0x8D40)
            if st != 0x8CD5: raise RuntimeError("framebuffer incomplete %x" % st)
            self.tex = openvr.Texture_t(); self.tex.handle = self.ftex
            self.tex.eType = openvr.TextureType_OpenGL; self.tex.eColorSpace = openvr.ColorSpace_Auto
        gl.x_glBindFramebuffer(0x8D40, self.fbo); gl.glViewport(0, 0, W, H)
        gl.glClearColor(0.0, 0.0, 0.0, 0.0); gl.glClear(0x4000)
        gl.glMatrixMode(0x1701); gl.glLoadIdentity(); gl.glOrtho(0, W, 0, H, -1, 1)   # canvas y down -> texture row 0 = top
        # baked texels carry alpha x WIRED alpha: undone here (texture alpha x colour alpha x scale); the overlay re-applies it
        al = float(WIRED["alpha"]) if WIRED["on"] else 1.0; sc = 1.0 if al > 0.999 else (2.0 if al >= 0.5 else 4.0)
        gl.glEnable(0x0DE1); gl.glTexEnvi(0x2300, 0x2200, 0x8570)                      # GL_COMBINE
        gl.glTexEnvi(0x2300, 0x8571, 0x1E01); gl.glTexEnvi(0x2300, 0x8580, 0x1702)     # rgb = texture
        gl.glTexEnvi(0x2300, 0x8572, 0x2100); gl.glTexEnvi(0x2300, 0x8588, 0x1702); gl.glTexEnvi(0x2300, 0x8589, 0x8577)
        gl.glTexEnvf(0x2300, 0x0D1C, sc); gl.glColor4f(1.0, 1.0, 1.0, 1.0 / (al * sc))
        gl.glDisable(0x0BE2); self.src.draw(gl)                                        # body: copied as is
        gl.glEnable(0x0BE2); gl.x_glBlendFuncSeparate(0x0302, 0x0303, 1, 0x0303)        # eyes, mouth: over it
        for l in self.layers:
            if l.cur is not None and l.want is not None: l.draw(gl)
        gl.glFinish(); gl.x_glBindFramebuffer(0x8D40, 0)

    def commit(self):
        if self.src.want is None:
            if self.on: self.hide()
            return
        state = (self.src.update(),) + tuple(l.update() for l in self.layers)
        if state[0] is not None and state != self.drawn:
            try: self._compose(); self.ov.setOverlayTexture(self.o, self.tex); self.drawn = state
            except Exception as e: log("compose error:", repr(e))
        self._apply()
        if not self.on and self.drawn is not None: self.ov.showOverlay(self.o); self.on = True

    def hide(self):
        self.ov.hideOverlay(self.o); self.on = False; self.src.want = None


def load_rel():
    try:
        r = json.load(open(REL_FILE))
        return r if len(r) == 3 and all(len(x) == 4 for x in r) else None
    except (OSError, ValueError, TypeError): return None


def save_rel(r):
    try:
        with open(REL_FILE + ".tmp", "w") as f: json.dump(r, f)
        os.replace(REL_FILE + ".tmp", REL_FILE)
    except OSError: pass


def main():
    # Lain is only on the Frame while it is connected to the PC. Nothing at all (no SteamVR connection, no GL) until a PC
    # stream has been up for 10 s: she never starts at boot next to the Steam UI (after a hard power-off the UI
    # crash-looped while overlays started with it).
    up = None
    while True:
        if pc_linked():
            up = up or time.time()
            if time.time() - up >= 10: break
        else: up = None
        time.sleep(3)
    log("PC stream up: starting")
    while True:
        try: openvr.init(openvr.VRApplication_Overlay); break
        except openvr.OpenVRError as e: log("waiting for SteamVR:", e); time.sleep(3)
    ov = openvr.VROverlay(); sysvr = openvr.VRSystem()
    C = Clips(); P = placement(); FPS = C.fps

    def make(key, name, sort):
        for attempt in range(10):
            try: o = ov.createOverlay(key, name); break
            except openvr.OpenVRError as e: log("overlay not ready yet:", repr(e)); time.sleep(2)
        else: raise SystemExit(1)
        ov.setOverlayInputMethod(o, openvr.VROverlayInputMethod_None); ov.setOverlaySortOrder(o, sort)
        return o
    GL.init(); WIRED.update(P.get("wired") or {})
    pan = [make(KEY_PANEL, "Lain", P["sort"])]
    eyes = GLLayer(); mouth = GLLayer()                                            # drawn into her one picture
    body = GLPanel(ov, pan[0], C.w, C.h, (eyes, mouth))
    hit = ov.createOverlay(KEY_HIT, "Lain click target")
    hb = P["hit_box"]; hb_w = hb[2] - hb[0]; hb_h = hb[3] - hb[1]
    htw = 40; hth = max(8, round(htw * hb_h * C.h / (hb_w * C.w)))       # texture aspect = her silhouette box aspect
    ov.setOverlayFromFile(hit, hit_png(htw, hth)); ov.setOverlayInputMethod(hit, openvr.VROverlayInputMethod_Mouse)
    hms = openvr.HmdVector2_t(); hms.v[0] = float(htw); hms.v[1] = float(hth); ov.setOverlayMouseScale(hit, hms)
    ov.setOverlayFlag(hit, openvr.VROverlayFlags_MakeOverlaysInteractiveIfVisible, True)
    ov.setOverlaySortOrder(hit, max(P["hit_sort"], P["sort"] + 6))
    vs = voice.Voice(VOICE_DIR, CLICKS, log)
    lips = LipTrack()
    EJ = C.eyes or {}; EGX = EJ.get("gx") or [0.0]; EGY = EJ.get("gy") or [0.0]
    eref = (EJ.get("sets", {}).get("rest", {}).get("ref_centre") or [C.w / 2, C.h / 2])
    width_m = 1.0; rows = None; fit = None
    shown = False; front = 0; pending = False; last_vis = 0.0; place_retry = 0.0; refit_t = 0.0; errs = 0
    saved_rel = load_rel(); linked = False; link_off = time.time(); link_check = 0.0; bar = None; rel = None; lastB = None; hit_on = False
    last_click = 0.0; listen_at = 0.0; prev_vstate = "idle"; idle_since = time.time(); first_miss = None; fallback_on = False
    wake_touch = 0.0; wake_check = 0.0; hidden_at = time.time() - 3600; speak_mode = None
    gaze = [0.0, 0.0]; prev_live = False; prev_baked = None; sac = None; hp = None; pause_fired = False; last_react = 0.0; next_rand_react = 0.0
    try: os.remove(WAKE_REQ)                       # a stale wake from before a restart never fires
    except OSError: pass
    log("lain (grok) ready")

    def place(f):
        nonlocal rows, width_m
        top, x, y, z, nu, nv = f
        width_m = nu * P["width"]; h_m = width_m * C.h / C.w
        pad_m = h_m * P["bottom_pad_px"] / C.h
        c = [top[k] - y[k] * (P["drop_m"] + pad_m) + y[k] * h_m / 2 + z[k] * P["toward_you"] for k in range(3)]
        rows = [[x[0], y[0], z[0], c[0]], [x[1], y[1], z[1], c[1]], [x[2], y[2], z[2], c[2]]]
        body.width(width_m); body.place([r[:] for r in rows])
        eyes.width(width_m); mouth.width(width_m)
        ov.setOverlayWidthInMeters(hit, width_m * hb_w)
        place_hit()

    def place_hit():
        h_m = width_m * C.h / C.w
        dx = ((hb[0] + hb[2]) / 2 - 0.5) * width_m; dy = (0.5 - (hb[1] + hb[3]) / 2) * h_m
        hrows = mul(rows, [[1, 0, 0, dx], [0, 1, 0, dy], [0, 0, 1, P["hit_forward_m"]]])
        ov.setOverlayTransformAbsolute(hit, openvr.TrackingUniverseStanding, mat34(hrows))

    def head_pos():
        try:
            poses = (openvr.TrackedDevicePose_t * 1)(); sysvr.getDeviceToAbsoluteTrackingPose(openvr.TrackingUniverseStanding, 0, poses)
            if not poses[0].bPoseIsValid: return None, None
            return to_rows(poses[0].mDeviceToAbsoluteTracking), [poses[0].mDeviceToAbsoluteTracking.m[r][3] for r in range(3)]
        except Exception: return None, None

    def hide_all():
        body.hide(); eyes.hide(); mouth.hide()

    while True:
        t0 = time.time()
        if t0 > link_check:
            link_check = t0 + 2.0; now = pc_linked()
            if now != linked:
                linked = now; log("PC link", "on" if linked else "off: hidden"); link_off = None if linked else t0
                if not linked and vs.state in ("listening", "thinking"): vs.stop_listening("standalone")
            if not linked and link_off and t0 - link_off > 120 and vs.state == "idle":   # standalone for 2 min: quit fully
                log("standalone for 2 min: exiting until the next PC stream")              # (systemd restarts her into the wait above)
                hide_all(); openvr.shutdown(); return 0
        try:
            if bar is None:
                try: bar = ov.findOverlay(STEAM_BAR)
                except openvr.OpenVRError: bar = None
            vis = linked and ov.isDashboardVisible() and (bar is None or ov.isOverlayVisible(bar))
        except openvr.OpenVRError: vis = False
        if vis: last_vis = t0
        if vis and shown and C.closing:                                          # menu back before she vanished
            C.on_show(False); log("menu back: reconnect")
        if vis and (not shown or t0 > refit_t) and t0 > place_retry:
            place_retry = t0 + (0.5 if not shown else 3.0); refit_t = t0 + 3.0
            try:
                hm, _hp = head_pos()
                f = menu_top(ov, [hm[r][3] for r in range(3)], math.atan2(hm[0][2], hm[2][2])) if hm else None
                if f is not None and (fit is None or not shown or math.dist(f[0], fit[0]) > 0.08 or fallback_on):
                    fit = f; place(f); rel = None; fallback_on = False
                    if not shown:
                        notice = t0 - hidden_at > NOTICE_AFTER_S and vs.state == "idle" and not vs.speaking()
                        idle_since = t0; C.on_show(notice); hide_all(); pending = False; shown = True
                        log("shown on the menu top edge, width", round(width_m, 2), "(notice_you)" if notice else "")
                elif f is None and not shown and hm:
                    if first_miss is None: first_miss = t0
                    # She stays on top whatever menu is open: other menus (SteamVR Settings, ...) replace the home panel in
                    # the same spot and can't be found by name. The dock bar stays: put her where she sat on the home
                    # panel, relative to the bar (remembered in REL_FILE).
                    B = None
                    if saved_rel is not None and bar is not None and t0 - first_miss > 0.6:
                        try: _, bm = ov.getOverlayTransformAbsolute(bar); B = to_rows(bm)
                        except Exception: B = None
                    if B is not None:
                        new = mul(B, saved_rel); rows = [r[:] for r in new]; rel = [r[:] for r in saved_rel]; lastB = B
                        body.width(width_m); body.place([r[:] for r in rows]); place_hit(); fallback_on = False
                        idle_since = t0; C.on_show(False); hide_all(); pending = False; shown = True
                        log("shown on another menu (where the home menu's top was, riding the dock bar)")
                    elif t0 - first_miss > 8.0:                                         # menu panel not found (new SteamOS?): a spot in front of you
                        a = math.atan2(hm[0][2], hm[2][2]); c, s_ = math.cos(a), math.sin(a)
                        px, pz = hm[0][3] - s_ * 1.3, hm[2][3] - c * 1.3; py = hm[1][3] - 0.05
                        x, y, z = [c, 0.0, -s_], [0.0, 1.0, 0.0], [s_, 0.0, c]
                        place(([px, py - 0.35, pz], x, y, z, 1.0, 0.7)); rel = None; fallback_on = True
                        C.on_show(False); hide_all(); pending = False; shown = True
                        log("menu panel not found for 8 s: shown in front of you (fallback); still looking for the menu")
            except Exception as e:
                if errs < 5: errs += 1; log("place:", repr(e))
        elif not vis and shown and not C.closing and t0 - last_vis > 0.3:
            C.disconnect(); log("menu closed: disconnect")
        if shown and C.closed:
            hide_all(); shown = False; first_miss = None; pending = False; hidden_at = t0
        want_hit = shown and not C.closing
        if want_hit != hit_on: (ov.showOverlay if want_hit else ov.hideOverlay)(hit); hit_on = want_hit
        if shown and rows is not None and bar is not None and not fallback_on:    # ride along with the menu every frame
            try:
                _, bm = ov.getOverlayTransformAbsolute(bar); B = to_rows(bm)
                if rel is None: rel = mul(aff_inv(B), rows); lastB = B; saved_rel = [r[:] for r in rel]; save_rel(saved_rel)
                elif max(abs(B[r][c] - lastB[r][c]) for r in range(3) for c in range(4)) > 1e-4:
                    new = mul(B, rel); lastB = B
                    for r in range(3): rows[r][:] = new[r]
                    body.place([r[:] for r in rows])
                    place_hit()
            except Exception as e:
                if errs < 5: errs += 1; log("follow:", repr(e))
        # ---- what the voice loop wants -> her mode
        st = vs.state
        if st == "idle" and vs.speaking(): st = "speaking"
        if st != "idle": idle_since = t0
        night = is_night(P); C.night = night
        if st == "listening": mode = "listen"; speak_mode = None
        elif st == "thinking":
            speak_mode = None
            mode = "think" if (C.mode == "think" or t0 - getattr(vs, "t_state", t0) > THINK_OPEN_S) else "think_open"
        elif st == "speaking":
            if speak_mode is None:                                               # decided once per answer
                speak_mode = "talk" if (C.mode in ("think", "talk") or C.pose_now in ("wired", "talk") or not P.get("lips", True)) else "talk_open"
            mode = speak_mode
        else:
            speak_mode = None
            mode = "sleep" if t0 - idle_since > (SLEEP_NIGHT_S if night else SLEEP_DAY_S) else "idle"   # opening the menu resets idle_since: wakes her
        C.set_mode(mode)
        # ---- your head relative to her panel: leans + live eyes
        if shown and rows is not None:
            _, hp = head_pos()
        else: hp = None
        if hp is not None and C.mode in ("idle", "listen") and not C.closing:
            lat = sum((hp[k] - rows[k][3]) * rows[k][0] for k in range(3))
            side = C.lean
            if side is None and abs(lat) > LEAN_ON_M: side = "l" if lat < 0 else "r"
            elif side == "l" and lat > -LEAN_OFF_M: side = ("r" if lat > LEAN_ON_M else None)
            elif side == "r" and lat < LEAN_OFF_M: side = ("l" if lat < -LEAN_ON_M else None)
            C.set_lean(side)
        elif C.lean and C.mode not in ("idle", "listen"): C.set_lean(None)
        # ---- reactions at the pauses in your speech
        if C.mode == "listen" and C.cur == "listen_loop" and t0 - last_react > 3.0:
            lv = getattr(vs, "levels", None)
            if lv is not None:
                if len(lv) > 10:
                    floor = max(min(lv[3:]), 20.0); thr = max(floor * 2.5, 1500.0)
                    quiet = all(x < thr for x in lv[-5:]); spoke = any(x >= thr for x in lv[-15:-5])
                    if quiet and spoke and not pause_fired:
                        pause_fired = True
                        if C.fire_reaction(C.rng.choice(REACTIONS)): last_react = t0; log("pause in speech: reaction", C.react)
                    elif not quiet: pause_fired = False
            elif t0 > next_rand_react:
                next_rand_react = t0 + random.uniform(4.0, 8.0)
                if C.fire_reaction(C.rng.choice(REACTIONS)): last_react = t0
        # ---- frames (body + eyes + mouth swap together)
        if shown:
            body.commit()
            path = C.next_frame()
            if path:
                try: body.stage(path)
                except openvr.OpenVRError as e:
                    errs += 1
                    if errs < 5: log("frame error:", repr(e))
                m_px = width_m / C.w
                # live eyes: on every frame that carries an eye transform (attention clips), else hidden. Target: your head.
                e = C.eye_entry(); tgt = None
                # her irises are baked into this frame (not just hidden by a blink in a live-eye clip): a later live frame
                # saccades from here
                baked_src = C.at[0] not in C.head
                if e and rows is not None:
                    if hp is not None:
                        ex = [rows[k][3] + rows[k][0] * (eref[0] - C.w / 2) * m_px + rows[k][1] * (C.h / 2 - eref[1]) * m_px for k in range(3)]
                        dv = [hp[k] - ex[k] for k in range(3)]
                        lat = sum(dv[k] * rows[k][0] for k in range(3)); up = sum(dv[k] * rows[k][1] for k in range(3))
                        dist = max(0.1, sum(dv[k] * rows[k][2] for k in range(3)))
                        tgt = (max(-0.4, min(0.4, 0.4 * math.degrees(math.atan2(lat, dist)) / 25.0)),
                               max(-0.2, min(0.2, 0.2 * math.degrees(math.atan2(-up, dist)) / 20.0)))
                if tgt is not None:
                    for k in range(2):
                        gaze[k] = tgt[k] if abs(tgt[k] - gaze[k]) > 0.15 else gaze[k] + (tgt[k] - gaze[k]) * 0.3
                    ax, ay = gaze[0] + e[6], gaze[1] + e[7]
                    if sac is None and not prev_live and prev_baked is not None: sac = [0, prev_baked]   # baked -> live
                    if sac is not None:                                       # start at her baked gaze, 100 ms saccade
                        u = min(1.0, sac[0] / float(SACCADE_FRAMES)); s5 = u * u * u * (u * (u * 6 - 15) + 10)
                        ax = sac[1][0] + (ax - sac[1][0]) * s5; ay = sac[1][1] + (ay - sac[1][1]) * s5
                        sac[0] += 1
                        if u >= 1.0: sac = None
                    gx = min(EGX, key=lambda v: abs(v - ax)) + 0.0
                    gy = min(EGY, key=lambda v: abs(v - ay)) + 0.0
                    eyes.stage(os.path.join(CLIPS, "eyes", "rest", f"x{gx:+.2f}_y{gy:+.2f}.png"), e[:6])
                    prev_live = True; prev_baked = None
                else:
                    gaze = [g * 0.6 for g in gaze]; eyes.stage(None, None)
                    prev_live = False; sac = None; prev_baked = C.baked_gaze() if baked_src else None
                # mouth: *_lips talk loops (per-frame sprites) or the wire-less answer in the listen pose (shared sprite)
                mp = None; mrows = None
                cl = C.at[0] or ""
                if C.mode == "talk_open" or (lips.active and cl.endswith("_lips")):
                    shape = lips.shape_at(time.time() + 1.0 / FPS)
                    spr, per_frame = mouth_sprite(cl, C.at[2], shape, lips.fallback)
                    if spr and per_frame: mp = spr
                    elif spr and C.mode == "talk_open" and C.head_T() is not None:
                        mp, mrows = spr, C.head_T()
                mouth.stage(mp, mrows)
            ev = openvr.VREvent_t()
            while ov.pollNextOverlayEvent(hit, ev)[0]:
                if ev.eventType == openvr.VREvent_MouseButtonDown and t0 - last_click > 1.2 and not C.closing:
                    last_click = t0; idle_since = t0
                    if vs.state == "listening": vs.stop_listening("click"); log("click -> done talking")
                    elif vs.state == "thinking": log("click while thinking (ignored)")
                    else: listen_at = t0 + 0.2; log("click -> listening")
        # ---- "Wake up, Lain": armed only while she's on the open menu and the voice loop is idle (mic closed otherwise)
        armed = P.get("wake", True) and shown and not C.closing and linked and vs.state == "idle" and not vs.speaking() and not listen_at
        if armed and t0 - wake_touch > 1.0:
            wake_touch = t0
            try:
                with open(WAKE_ARMED, "a"): pass
                os.utime(WAKE_ARMED, None)
            except OSError: pass
        elif not armed and wake_touch:
            wake_touch = 0.0
            try: os.remove(WAKE_ARMED)
            except OSError: pass
        if t0 > wake_check:
            wake_check = t0 + 0.1
            try: req_age = t0 - os.path.getmtime(WAKE_REQ)
            except OSError: req_age = None
            if req_age is not None:
                try: os.remove(WAKE_REQ)
                except OSError: pass
                if armed and req_age < 3.0 and t0 - last_click > 1.2:      # exactly what a click does from idle
                    last_click = t0; idle_since = t0; listen_at = t0 + 0.2; log("wake phrase -> listening")
                else: log("wake phrase ignored (state %s, armed %s, age %s)" % (vs.state, armed, req_age))
        if listen_at and t0 >= listen_at: listen_at = 0.0; vs.start_listening()
        vs.update()
        # ---- lip track: starts in the same tick voice.py starts the reply audio
        if vs.state == "speaking" and prev_vstate != "speaking" and P.get("lips", True) and vs.speaking():
            t_audio = time.time(); req = vs.req or ""
            for f in glob.glob(os.path.join(VOICE_DIR, "*.vis.json")):       # voice.py's cleanup doesn't know these
                if not f.endswith(req + ".vis.json"):
                    try: os.remove(f)
                    except OSError: pass
            ok = lips.start(os.path.join(VOICE_DIR, req + ".vis.json"), t_audio, P.get("lips_offset_s", 0.08))
            if not ok: ok = lips.synth(wav_seconds(os.path.join(VOICE_DIR, req + ".reply.wav")), t_audio, P.get("lips_offset_s", 0.08))
            C.lips = ok
        elif lips.active and not vs.speaking():                  # finished, or you talked over her (player stopped)
            lips.stop(); C.lips = False
        prev_vstate = vs.state
        if vs.state == "idle" and os.path.exists(RESTART_REQ):
            try: os.remove(RESTART_REQ)
            except OSError: pass
            log("restart requested")
            for o in pan + [hit]:
                try: ov.destroyOverlay(o)
                except Exception: pass
            openvr.shutdown(); time.sleep(1.0); os.execv(sys.executable, [sys.executable] + sys.argv)
        sev = openvr.VREvent_t()
        while sysvr.pollNextEvent(sev):
            if sev.eventType == openvr.VREvent_Quit: log("SteamVR quit"); openvr.shutdown(); return 0
        # battery: menu closed and nothing going on -> she pauses: 4 checks a second instead of 30
        # (she still appears within 0.25 s of the menu opening; nothing is drawn or decoded while she's hidden).
        paused = not shown and not listen_at and vs.state == "idle" and not vs.speaking()
        time.sleep(max(0.0, (0.25 if paused else 1.0 / FPS) - (time.time() - t0)))


if __name__ == "__main__":
    try: sys.exit(main())
    except Exception as e:
        log("fatal:", repr(e)); raise
