#!/usr/bin/env python3
"""Lainframe live skybox ("The Wired"): follows the time of day so you can stay in the headset and watch it change.
SteamVR backgrounds are one still image and only reload on restart, so the sky lives here instead: a cube of 6 overlay
quads (150 m out, sort order 0) per sky, two cubes (A/B) crossfaded with overlay alpha. When a fade finishes, the hidden
cube loads the next sky. Each face is one opaque, pre-flattened image (skies/<mood>/flat_<face>.png: foreground + road
baked onto the open sky; plain <face>.png if a sky has no flat set). Weather and street life: weather.py.
Rare live event: the red shadows (skies/<mood>_red/) fade in for 25-45 s every 40-90 minutes.
Schedule + fade length: ~/.config/lainframe/sky.json (shipped defaults: sky.json next to this file).
Writes ~/.local/state/lainframe/sky_now (json: weight per sky) for other tools.
Override (voice / PC): write a sky name into ~/.local/state/lainframe/sky_override (empty or missing = follow the clock).
Hidden while a game runs (GameWatch below: standalone scene apps + the PC's pc_game flag; logged on every change) and
while room view (passthrough) is on. Log: ~/.local/state/lainframe/sky.log"""
import json, math, os, random, sys, time

# ---- paths (Lainframe layout: code ~/lainframe/<part>, libs ~/lainframe/lib, config ~/.config/lainframe,
# state + logs ~/.local/state/lainframe)
HERE = os.path.dirname(os.path.abspath(__file__))                 # ~/lainframe/sky
ROOT = os.path.dirname(HERE)                                       # ~/lainframe
sys.path.insert(0, os.path.join(ROOT, "lib"))                     # vendored pyopenvr (aarch64)
import openvr  # noqa: E402

CONFIG = os.path.expanduser("~/.config/lainframe/sky.json")
SKIES = os.path.join(HERE, "skies")                # skies/<name>/flat_{front,back,left,right,up,down}.png (+ pool.png, patches/)
STATE = os.path.expanduser("~/.local/state/lainframe")
PC_GAME = os.path.join(STATE, "pc_game")           # touched by the PC (brain/pcgame_watch.py) while a PC game runs
OVERRIDE = os.path.join(STATE, "sky_override"); NOW = os.path.join(STATE, "sky_now")
LOG = os.path.join(STATE, "sky.log")
KEY_PREFIX = "lainframe.sky"                       # overlay keys: lainframe.sky.<cube>.<face>
os.makedirs(STATE, exist_ok=True)
R = 150.0                                          # cube half-size, metres
EYE = 1.7
POOL_M = 2.6                                       # blood pool texture covers 2.6 x 2.6 m (blood_pool.py SIZE)
HZ = 24                                            # rain and the black cat animate at this rate
# face: (centre direction F, texture right X, texture up Y), OpenVR axes (x right, y up, -z forward)
FACES = {"front": ((0, 0, -1), (1, 0, 0), (0, 1, 0)), "back": ((0, 0, 1), (-1, 0, 0), (0, 1, 0)),
         "right": ((1, 0, 0), (0, 0, 1), (0, 1, 0)), "left": ((-1, 0, 0), (0, 0, -1), (0, 1, 0)),
         "up": ((0, 1, 0), (1, 0, 0), (0, 0, 1)), "down": ((0, -1, 0), (1, 0, 0), (0, 0, -1))}


def log(*a):
    try:
        with open(LOG, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(map(str, a)) + "\n")
    except OSError: pass


def mat34(F, X, Y):
    Z = [-c for c in F]                                    # quad's +Z points back at you
    P = [F[0] * R, EYE + F[1] * R, F[2] * R]
    m = openvr.HmdMatrix34_t()
    for r in range(3):
        m.m[r][0], m.m[r][1], m.m[r][2], m.m[r][3] = X[r], Y[r], Z[r], P[r]
    return m


# ------------------------------------------------------------------ "is a game running?" (2026-10-25 rewrite)
# A simpler check (`pc_game exists OR (scene pid != 0 AND no vrlink process)`) missed games: any resident vrlink process
# vetoed the local check, an API error silently meant "no game", and a pc_game flag that never arrived (PC watcher could
# not reach the Frame) missed PCVR games. So the SCENE PROCESS ITSELF is classified:
#   1. PC flag ~/.local/state/lainframe/pc_game, only while fresh (the PC re-touches it every 60 s; older than PC_FRESH_S = ignored)
#   2. OpenVR scene app: getCurrentSceneProcessId(); a game unless it is SteamVR's own (exe under /opt/steamvr, vrlink =
#      the PC stream, vrcompositor, ...) or its app key says system/tool. A pid we can't inspect counts as a game.
#   3. Fallback when the API errors or reports no scene: a Steam-launched app (reaper "SteamLaunch AppId=N") whose process
#      tree loads the VR client (vrclient / openxr), is not SteamVR / Steam Link and not in "not_games".
# Hides at once; shows again only after SHOW_AFTER_S of "no game" (loading screens can drop the scene briefly).
# Every change of the inputs and of the decision is logged ("game check: ...").
SYSTEM_EXES = {"vrlink", "vrcompositor", "vrserver", "vrdashboard", "vrmonitor", "vrstartup", "vrwebhelper", "vrstartup.sh",
               "steamwebhelper", "steam", "gamescope", "steamvr_environments", "vrpathreg"}
SYSTEM_KEY_PARTS = ("vrlink", "steamvr_environments", "openvr.tool.", "openvr.component.", "system.", "steam.overlay")
TOOL_APPIDS = {"0", "250820", "353380", "1070560", "1391110", "1628350", "1493710", "228980", "961940", "2180100"}   # SteamVR, Steam Link, runtimes, Proton
NOT_GAMES = ["ovr-advanced", "advancedsettings", "frametop", "framecolor", "perfoverlay", "perf_overlay", "mictuner",
             "vrcfacetracking", "lainframe", "lain_player", "skyclock"]
PC_FRESH_S = 180.0
SHOW_AFTER_S = 3.0
SCENE_STATE = {0: "none", 1: "starting", 2: "quitting", 3: "running", 4: "waiting"}


def _read(p, n=4096):
    try:
        with open(p, "rb") as f: return f.read(n)
    except OSError: return b""


class GameWatch:
    """game_running(apps) for the sky. Proc access is in procs()/vr_client() so the offline test can fake it."""
    def __init__(self, extra_not_games=()):
        self.not_games = [s.lower() for s in list(NOT_GAMES) + list(extra_not_games or ())]
        self.state = None; self.no_game_since = None; self.last_inputs = None; self.last_reason = None
        self._cache_t = 0.0; self._cache = None

    # ---- process info (Linux /proc; empty on other systems)
    def procs(self):
        """pid -> (ppid, exe path, cmdline str)"""
        out = {}
        try: ds = [d for d in os.listdir("/proc") if d.isdigit()]
        except OSError: return out
        for d in ds:
            st = _read(f"/proc/{d}/stat").decode("utf-8", "replace")
            try: ppid = int(st[st.rindex(")") + 2:].split()[1])
            except (ValueError, IndexError): continue
            try: exe = os.readlink(f"/proc/{d}/exe")
            except OSError: exe = ""
            cmd = _read(f"/proc/{d}/cmdline").replace(b"\0", b" ").decode("utf-8", "replace").strip()
            out[int(d)] = (ppid, exe, cmd)
        return out

    def vr_client(self, pid):
        """True if the process has the VR client / OpenXR runtime loaded."""
        m = _read(f"/proc/{pid}/maps", 4 << 20)
        return b"vrclient" in m or b"openxr" in m.lower()

    # ---- classification
    def system_proc(self, exe, cmd, key=""):
        e = (exe or "").lower(); b = os.path.basename(e).replace(" (deleted)", "")
        if b in SYSTEM_EXES or e.startswith("/opt/steamvr") or "/steamvr/" in e or "vrlink" in e: return True
        k = (key or "").lower()
        if any(p in k for p in SYSTEM_KEY_PARTS): return True
        if k.startswith("steam.app.") and k[10:] in TOOL_APPIDS: return True
        c = (cmd or "").lower()
        return any(n in c or n in e for n in self.not_games)

    def scene(self, apps, P):
        """-> (pid, exe, key, state, error)"""
        pid, key, state, err = 0, "", None, ""
        try: pid = int(apps.getCurrentSceneProcessId() or 0)
        except Exception as e: err = "pid: " + repr(e)[:80]
        try: state = int(apps.getSceneApplicationState())
        except Exception: state = None
        if pid:
            try:
                import ctypes
                buf = ctypes.create_string_buffer(256)
                if apps.function_table.getApplicationKeyByProcessId(pid, buf, 256) == 0: key = buf.value.decode("utf-8", "replace")
            except Exception:
                try: key = apps.getApplicationKeyByProcessId(pid) or ""
                except Exception: key = ""
        exe = P.get(pid, (0, "", ""))[1] if pid else ""
        return pid, exe, key, state, err

    def steam_launched(self, P):
        """VR apps started by Steam (reaper SteamLaunch AppId=N) that aren't SteamVR / the stream / a tool."""
        kids = {}
        for pid, (pp, _, _) in P.items(): kids.setdefault(pp, []).append(pid)
        found = []
        for pid, (pp, exe, cmd) in P.items():
            if "SteamLaunch" not in cmd or "AppId=" not in cmd or os.path.basename(exe) != "reaper": continue
            appid = cmd.split("AppId=", 1)[1].split()[0]
            if appid in TOOL_APPIDS: continue
            tree, stack = [], list(kids.get(pid, []))
            while stack and len(tree) < 400:
                q = stack.pop(); tree.append(q); stack.extend(kids.get(q, []))
            if any(self.system_proc(P[q][1], P[q][2]) for q in tree if q in P):
                continue
            if any(n in cmd.lower() for n in self.not_games): continue
            if any(self.vr_client(q) for q in tree): found.append(appid)
        return sorted(set(found))

    def check(self, apps, now=None):
        now = time.time() if now is None else now
        if self._cache is not None and now - self._cache_t < 1.0: return self._cache
        self._cache_t = now
        # 1. PC flag
        try: age = now - os.path.getmtime(PC_GAME)
        except OSError: age = None
        pc = age is not None and age < PC_FRESH_S
        # 2. scene app
        P = self.procs()
        pid, exe, key, state, err = self.scene(apps, P) if apps is not None else (0, "", "", None, "no api")
        cmd = P.get(pid, (0, "", ""))[2] if pid else ""
        local = bool(pid) and not self.system_proc(exe, cmd, key)
        # 3. Steam-launched VR app, only when the API gave no usable answer
        steam = self.steam_launched(P) if (err or not pid) else []
        game = pc or local or bool(steam)
        inputs = (pid, exe, key, state, err, None if age is None else ("fresh" if pc else "stale"), tuple(steam))
        if inputs != self.last_inputs:
            self.last_inputs = inputs
            log("game check inputs: scene pid=%s exe=%s key=%s state=%s%s | pc_game=%s | steam-launched VR=%s" % (
                pid, exe or "?", key or "?", SCENE_STATE.get(state, state), (" err=" + err) if err else "",
                "none" if age is None else "%.0fs old (%s)" % (age, "fresh" if pc else "stale, ignored"), ",".join(steam) or "none"))
        reason = "PC game (fresh pc_game flag from the PC)" if pc else ("standalone scene app pid %s %s %s" % (pid, exe or "?", key)) if local \
            else ("Steam-launched VR app AppId=%s" % ",".join(steam)) if steam else "no game"
        if game:
            self.no_game_since = None; want = True
        else:
            if self.no_game_since is None: self.no_game_since = now
            want = self.state is True and now - self.no_game_since < SHOW_AFTER_S        # brief grace before showing again
        if want != self.state or (want and game and reason != self.last_reason):
            log("game check: %s -> sky %s" % (reason if game else "no game", "HIDDEN" if want else "shown"))
            self.state = want; self.last_reason = reason
        self._cache = want
        return want


_gw = None
def game_running(apps, cfg=None, now=None):
    global _gw
    if _gw is None: _gw = GameWatch((cfg or {}).get("not_games", ()))
    try: return _gw.check(apps, now)
    except Exception as e:                                   # never crash the sky over this; keep the last decision
        log("game check error:", repr(e)); return bool(_gw.state)


class RoomView:
    """Room view (camera passthrough) looked like it could not be toggled: the toggle works (vrserver logs the camera
    view's currentRoomViewRenderingMode 0 <-> 7), but the sky cubes sit over the background, so the camera view was hidden
    behind them. Follows that log line (new bytes only) and hides the sky + weather while room view is on."""
    LOG = os.path.expanduser("~/.local/share/Steam/logs/vrserver.txt")
    KEY = b'"currentRoomViewRenderingMode":'

    def __init__(self): self.pos = None; self.on = False; self.t = 0.0

    def check(self, now):
        if now - self.t < 0.3: return self.on
        self.t = now
        try:
            size = os.path.getsize(self.LOG)
            if self.pos is None or size < self.pos: self.pos = max(0, size - 262144); self.on = False   # start / SteamVR restart
            if size > self.pos:
                with open(self.LOG, "rb") as f: f.seek(self.pos); data = f.read(size - self.pos)
                self.pos = size
                i = data.rfind(self.KEY)
                if i >= 0:
                    on = data[i + len(self.KEY):i + len(self.KEY) + 8].strip()[:1] not in (b"0", b"")
                    if on != self.on: log("room view", "ON -> sky hidden" if on else "off -> sky shown"); self.on = on
        except OSError: pass
        return self.on


_rv = RoomView()


def smooth(t): t = min(1.0, max(0.0, t)); return t * t * (3 - 2 * t)


def mix_now(cfg, now=None):
    """-> (sky_from, sky_to, t): schedule entries are [ "HH:MM", sky ]; each sky fades into the next over fade_min
    minutes, centred on the next entry's time."""
    sched = sorted(cfg["schedule"], key=lambda e: e[0]); fade = cfg.get("fade_min", 40) * 60
    lt = time.localtime(now); s = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
    mins = [int(h) * 3600 + int(m) * 60 for h, m in (e[0].split(":") for e in sched)]
    for i in range(len(sched)):
        b = mins[(i + 1) % len(sched)]
        d = (s - b + 43200) % 86400 - 43200                 # seconds relative to the next boundary, -12h..12h
        if abs(d) < fade / 2: return sched[i][1], sched[(i + 1) % len(sched)][1], smooth(d / fade + 0.5)
    cur = min(range(len(sched)), key=lambda i: (s - mins[i]) % 86400)    # last boundary passed
    return sched[cur][1], sched[cur][1], 0.0


# draw order (sort order; everything stays below the Steam menu and Lain): sky 0/1 (A, fading-in B), window patches 7,
# red event 8, rain / cat / crows / car / sparks / lamp / puddle 9, blood pool 9/10 (never in the same view as the sprites)
ROLE = {0: dict(sky=0, pool=9), 1: dict(sky=1, pool=10), "red": dict(sky=8, pool=10)}


class Cube:
    """one sky: six opaque faces and the pool lying on the floor (pool=False: the red-shadow event)."""
    def __init__(self, ov, tag, pool=True):
        self.ov, self.sky, self.h = ov, None, {}; self.st = {}
        for f, (F, X, Y) in FACES.items():
            h = ov.createOverlay(f"{KEY_PREFIX}.{tag}.{f}", f"Sky {tag} {f}")
            ov.setOverlayWidthInMeters(h, 2 * R * 1.004)                    # a hair of overlap hides the seams
            ov.setOverlaySortOrder(h, 0)
            ov.setOverlayTransformAbsolute(h, openvr.TrackingUniverseStanding, mat34(F, X, Y))
            self.h[f] = h
        self.pool = None; self.has_pool = False
        if pool:                                   # the pool of blood you stand in: rendered per sky, lying flat on the floor
            try:
                self.pool = ov.createOverlay(f"{KEY_PREFIX}.{tag}.pool", f"Sky {tag} pool")
                ov.setOverlayWidthInMeters(self.pool, POOL_M)
                m = openvr.HmdMatrix34_t()
                for r, row in enumerate(((1, 0, 0, 0), (0, 0, 1, 0.003), (0, -1, 0, 0))):      # texture up = forward, lying flat
                    for c in range(4): m.m[r][c] = row[c]
                ov.setOverlayTransformAbsolute(self.pool, openvr.TrackingUniverseStanding, m)
            except Exception as e: log("no pool overlay for", tag, repr(e)); self.pool = None

    def load(self, sky):
        if sky == self.sky: return
        d = os.path.join(SKIES, sky)
        for f, h in self.h.items():
            fl = os.path.join(d, "flat_" + f + ".png")
            self.ov.setOverlayFromFile(h, fl if os.path.exists(fl) else os.path.join(d, f + ".png"))
        if self.pool is not None:
            pp = os.path.join(d, "pool.png"); self.has_pool = os.path.exists(pp)
            if self.has_pool: self.ov.setOverlayFromFile(self.pool, pp)
        self.sky = sky; self.st = {}; log("loaded", sky)                      # new textures: resend state next tick

    def _set(self, h, a, sort, on):
        """alpha / sort / visibility, sent only when they change (keeps the IPC to vrserver small on the Frame)."""
        a = round(a, 3); st = self.st.setdefault(h, [None, None, None])
        if st[0] != a: self.ov.setOverlayAlpha(h, a); st[0] = a
        if st[1] != sort: self.ov.setOverlaySortOrder(h, sort); st[1] = sort
        if st[2] != on: (self.ov.showOverlay if on else self.ov.hideOverlay)(h); st[2] = on

    def alpha(self, a, show, role):
        so = ROLE[role]; vis = bool(show and a > 0.001)
        for h in self.h.values(): self._set(h, a, so["sky"], vis)
        if self.pool is not None: self._set(self.pool, a, so["pool"], vis and self.has_pool)

    def destroy(self):
        for h in list(self.h.values()) + ([self.pool] if self.pool is not None else []):
            try: self.ov.destroyOverlay(h)
            except Exception: pass


class SkyClock:
    """the whole live sky; tick(now) once per frame. Kept separate from main() so a preview tool can drive it with a
    fake openvr and show exactly what the headset will draw."""
    def __init__(self, ov, apps, cfg):
        self.ov, self.apps, self.cfg = ov, apps, cfg
        # skies ship flat_<face>.png (art_pipeline/sky_flatten.py: foreground baked onto the open sky): ONE opaque cube,
        # no separate foreground layer (that cost ~1.6 ms compositor GPU time per frame and lagged at 144 Hz)
        self.A, self.B = Cube(ov, "a"), Cube(ov, "b")
        self.Rd = None                                     # rare live event (red shadows), created only while it plays
        try:
            import weather; self.wx = weather.Weather(ov, log)
        except Exception as e:                             # weather is optional: the sky still runs without it
            self.wx = None; log("weather off:", repr(e))
        self.next_red = time.time() + random.uniform(2400, 5400); self.red_ev = None; self.last = None

    def mix(self, now):
        try: ovr = open(OVERRIDE).read().strip()
        except OSError: ovr = ""
        if ovr and os.path.isdir(os.path.join(SKIES, ovr)): return ovr, ovr, 0.0
        return mix_now(self.cfg, now)

    def tick(self, now, show=None):
        fr, to, t = self.mix(now)
        A, B = self.A, self.B
        # A always holds "from"; B holds "to". When a fade ends, the cubes swap roles so nothing pops.
        if B.sky == fr and A.sky != fr: self.A, self.B = A, B = B, A
        A.load(fr)
        if t > 0: B.load(to)
        if show is None: show = not game_running(self.apps, self.cfg, now) and not _rv.check(now)
        A.alpha(1.0, show, 0); B.alpha(t if t > 0 else 0.0, show, 1)     # the incoming sky fades in on top
        if self.red_ev is None and now > self.next_red and show and t == 0 and os.path.isdir(os.path.join(SKIES, fr + "_red")):
            try:
                self.Rd = Cube(self.ov, "red", pool=False); self.Rd.load(fr + "_red")
                self.red_ev = (now, random.uniform(25, 45)); log("event: red shadows")
            except Exception as e:
                log("red event skipped:", repr(e)); self.next_red = now + 600
        if self.red_ev:
            rt = now - self.red_ev[0]; ra = 0.85 * min(1.0, rt / 6, (self.red_ev[1] - rt) / 6)
            if ra <= 0 and rt > 1:
                self.red_ev = None; self.next_red = now + random.uniform(2400, 5400); self.Rd.destroy(); self.Rd = None
            else: self.Rd.alpha(max(0.0, ra), show, "red")
        if self.wx: self.wx.update(now, show, night=(fr == "lain_night"), mood=fr if t < 0.5 else to, red=self.red_ev is not None,
                                   blend=(fr, to, t))
        state = {fr: round(1 - t, 3)}; state[to] = round(state.get(to, 0) + t, 3)
        if state != self.last:
            try:
                with open(NOW + ".tmp", "w") as f: json.dump(state, f)
                os.replace(NOW + ".tmp", NOW)
            except OSError: pass
            self.last = state
        return fr, to, t


def load_cfg():
    """shipped defaults (sky.json next to this file), then the user's ~/.config/lainframe/sky.json on top."""
    cfg = {}
    for f in (os.path.join(HERE, "sky.json"), CONFIG):
        try: cfg.update(json.load(open(f)))
        except (OSError, ValueError): pass
    return cfg


def main():
    cfg = load_cfg()
    while True:
        try: openvr.init(openvr.VRApplication_Overlay); break
        except openvr.OpenVRError as e: log("waiting for SteamVR:", e); time.sleep(3)
    ov = openvr.VROverlay(); apps = openvr.VRApplications(); sysvr = openvr.VRSystem()
    sky = SkyClock(ov, apps, cfg)
    log("skyclock ready")
    while True:
        sky.tick(time.time())
        ev = openvr.VREvent_t()
        while sysvr.pollNextEvent(ev):
            if ev.eventType == openvr.VREvent_Quit: log("SteamVR quit"); openvr.shutdown(); return 0
        time.sleep(1.0 / HZ)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":                    # print the plan for every half hour (no VR)
        cfg = load_cfg()
        base = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
        for k in range(48):
            fr, to, t = mix_now(cfg, base + k * 1800); print(time.strftime("%H:%M", time.localtime(base + k * 1800)), fr, "->", to, round(t, 2))
        sys.exit(0)
    try: sys.exit(main())
    except Exception as e:
        log("fatal:", repr(e)); raise
