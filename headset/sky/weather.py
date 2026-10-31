"""Weather and the life of the street for skyclock.py: random rain, mostly dark and gloomy like the show, black cats
on the wires, birds, "a living, breathing street" -- always subtle, never stealing the scene. Every layer is an overlay
below Lain and the Steam menu (sort orders 7-9, see skyclock.ROLE):
  7 window patches: lights going off and on over minutes, a TV flickering cold blue (skies/<mood>/patches/)
  9 rain (one ring of quads 9 m around you), the black cat on a wire, crows landing / sitting / leaving and birds flying
    over, a distant car light crossing the far end of the street, electricity crackling at a pole's insulators now and
    then (more often in rain), a street lamp buzzing (its glow stutters) every 5-20 minutes, a puddle on the road that
    shows the Wired (the red sky, rippling) for ten seconds every 25-60 minutes
The weather clock pauses while the sky is hidden (a game, room view): you come back to the weather you left.
Assets (weather/): rain_atlas.png (4x4 frames), cat_atlas.png, crow_atlas.png, car.png, spark_atlas.png, lampglow.png,
puddle_atlas.png, wires.json (wires + lamp heads, exported with the sky). A missing asset (or no free overlay slot)
just switches that layer off."""
import json, math, os, random, time

import openvr

HERE = os.path.dirname(os.path.abspath(__file__))                 # ~/lainframe/sky
W = os.path.join(HERE, "weather")
KEY_PREFIX = "lainframe.sky.wx."
SKIES = os.path.join(HERE, "skies")
EYE = 1.7
SKY_R = 140.0                                  # sprites on the wires are projected to here (zero parallax, like the sky)
CUBE_R = 150.0
FLASH_COL = (0.72, 0.68, 0.84); FLASH_A = 0.45      # lightning: soft lilac at most, never white
# weather states: rain = 0..1.6 (ring alpha saturates at 1; more rain = more sparks and fewer perched birds)
STATES = {"gloomy": dict(rain=0.0), "drizzle": dict(rain=0.45), "rain": dict(rain=1.0), "downpour": dict(rain=1.6),
          "clearing": dict(rain=0.0)}
WEIGHTS = {"gloomy": 40, "drizzle": 14, "rain": 20, "downpour": 7, "clearing": 19}     # mostly dark and gloomy
TAU = 70.0                                     # seconds: how fast the weather blends into a new state
CATS_PER_HOUR = 4                 # hard rule: 4 black cats and 20 birds every hour, at random times
BIRDS_PER_HOUR = 20
BIRD_SLOTS = 4                    # birds that can be on screen at once (each lands, sits 25-150 s, flies off)

def _bez2(a, c, b, u):
    return [(1 - u) ** 2 * a[k] + 2 * (1 - u) * u * c[k] + u * u * b[k] for k in range(3)]


MOOD = {   # rain tint, how often cars show up, are house lights on
    "lain_dusk":   dict(rain=(0.85, 0.8, 0.95), car=0.8, lights=True),
    "lain_night":  dict(rain=(0.6, 0.55, 0.7), car=1.0, lights=True),
    "lain_sunset": dict(rain=(0.9, 0.78, 0.8), car=0.6, lights=True),
    "lain_day":    dict(rain=(0.85, 0.85, 0.9), car=0.3, lights=False),
}


def m34(X, Y, Z, P):
    m = openvr.HmdMatrix34_t()
    for r in range(3): m.m[r][0], m.m[r][1], m.m[r][2], m.m[r][3] = X[r], Y[r], Z[r], P[r]
    return m


def norm(v): n = math.sqrt(sum(c * c for c in v)) or 1.0; return [c / n for c in v]
def cross(a, b): return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
def lerp(a, b, t): return [x + (y - x) * t for x, y in zip(a, b)]


def facing(P, roll=0.0):
    """quad at P (OpenVR standing space) facing the eye; roll = rotation in its own plane (radians)."""
    Z = norm([-P[0], EYE - P[1], -P[2]])
    X = norm(cross([0, 1, 0], Z)) if abs(Z[1]) < 0.99 else [1, 0, 0]
    Y = cross(Z, X)
    c, s = math.cos(roll), math.sin(roll)
    X2 = [c * X[i] + s * Y[i] for i in range(3)]; Y2 = [-s * X[i] + c * Y[i] for i in range(3)]
    return X2, Y2, Z


def bounds(u0, v0, u1, v1):
    b = openvr.VRTextureBounds_t(); b.uMin, b.vMin, b.uMax, b.vMax = u0, v0, u1, v1; return b


def have(*names): return all(os.path.exists(os.path.join(W, n)) for n in names)


def scene_to_vr(p):
    """lain_sky scene coords (x right, y forward, z up, metres) -> OpenVR standing (x right, y up, -z forward)."""
    return [p[0], p[2], -p[1]]


def project(p_vr):
    """a point in the street -> its spot on the SKY_R sphere + the scale factor for its real size."""
    d = [p_vr[0], p_vr[1] - EYE, p_vr[2]]; dist = math.sqrt(sum(c * c for c in d)) or 1.0
    return [d[0] / dist * SKY_R, EYE + d[1] / dist * SKY_R, d[2] / dist * SKY_R], SKY_R / dist


class Weather:
    def __init__(self, ov, log, rng=None):
        self.ov, self.log, self.r = ov, log, rng or random.Random()
        self._st = {}; self.tick = 0
        self.cur = dict(STATES["gloomy"]); self.target = dict(self.cur); self.name = "gloomy"; self.until = 0.0
        self.night = False; self.mood = None; self.t0 = time.time(); self.last = time.time()
        self.rain = self._safe(self._rain) if have("rain_atlas.png") else []
        self.bolt = self._safe(self._lightning) if have("lightning_up.png") else []
        self.next_flash = time.time() + 1e9; self.flash_t = -1e9; self.flash2 = False
        wj = json.load(open(os.path.join(W, "wires.json"))) if have("wires.json") else {}
        self.wires = wj.get("wires", []); self.lamps = [l for l in wj.get("lamps", []) if 8 < math.hypot(l[0], l[1]) < 60]
        self.cat = self._sprite("cat", "cat_atlas.png") if have("cat_atlas.png") and self.wires else None
        self.crows = [self._sprite(f"crow{i}", "crow_atlas.png") for i in range(BIRD_SLOTS)] if have("crow_atlas.png") and self.wires else []
        self.crows = [c for c in self.crows if c is not None]
        self.car = self._sprite("car", "car.png") if have("car.png") else None
        self.spark = self._sprite("spark", "spark_atlas.png") if have("spark_atlas.png") and self.wires else None
        self.lampg = self._sprite("lampglow", "lampglow.png") if have("lampglow.png") and self.lamps else None
        self.puddle = self._sprite("puddle", "puddle_atlas.png") if have("puddle_atlas.png") else None
        self.spark_pts = self._insulators() if self.spark else []
        self.patch_h = [self._sprite(f"patch{i}", None) for i in range(4)]; self.patch_h = [h for h in self.patch_h if h is not None]
        self.patches = []
        now = time.time()
        self.quota = {}; self.ev_cat = None
        self.crow_ev = [None] * len(self.crows)
        self.next_car = now + self.r.uniform(30, 150); self.ev_car = None
        self.next_spark = now + self.r.uniform(900, 2100); self.ev_spark = None
        self.next_lamp = now + self.r.uniform(300, 1200); self.ev_lamp = None
        self.next_puddle = now + self.r.uniform(1500, 3600); self.ev_puddle = None
        log("weather ready: rain", len(self.rain), "lightning", len(self.bolt), "cat", bool(self.cat), "crows", len(self.crows), "car", bool(self.car),
            "sparks", len(self.spark_pts), "lamps", len(self.lamps), "patch slots", len(self.patch_h))

    # ---------------------------------------------------------------- layers
    def _safe(self, fn, default=None):
        try: return fn()
        except Exception as e:
            self.log("weather layer off:", fn.__name__, repr(e)); return default if default is not None else []

    def _mk(self, key, tex, width, sort):
        h = self.ov.createOverlay(KEY_PREFIX + key, "Sky weather " + key)
        if tex: self.ov.setOverlayFromFile(h, os.path.join(W, tex))
        self.ov.setOverlayWidthInMeters(h, width); self.ov.setOverlaySortOrder(h, sort)
        self.ov.setOverlayAlpha(h, 0.0); self.ov.hideOverlay(h); return h

    def _lightning(self):
        """the lightning layer: one quad per sky face (not the floor) carrying lightning_<face>.png = the open sky cut out of
        the skyline (buildings and wires stay dark in a flash). Exact face size: faces meet but never overlap (an
        overlapping see-through veil drew bright seams)."""
        from skyclock import FACES
        hs = []
        for f, (F, X, Y) in FACES.items():
            if f == "down" or not have("lightning_%s.png" % f): continue
            h = self._mk("bolt." + f, "lightning_%s.png" % f, 2 * (CUBE_R - 2), 2)
            P = [F[0] * (CUBE_R - 2), EYE + F[1] * (CUBE_R - 2), F[2] * (CUBE_R - 2)]
            self.ov.setOverlayTransformAbsolute(h, openvr.TrackingUniverseStanding, m34(X, Y, [-c for c in F], P)); hs.append(h)
        return hs

    def _rain(self):
        """one ring of 8 tall quads standing on the ground 9 m around you (a near ring cost 0.8 ms GPU at 144 Hz);
        neighbours overlap by the texture's feathered 15% edges so the density stays even."""
        hs = []; rad, n = 9.0, 8
        chord = 2 * rad * math.sin(math.pi / n); w = chord / 0.85; hgt = 2 * w
        for i in range(n):
            a = 2 * math.pi * i / n
            P = [rad * math.cos(math.pi / n) * math.sin(a), hgt / 2, -rad * math.cos(math.pi / n) * math.cos(a)]
            h = self._mk("rain0_%02d" % i, "rain_atlas.png", w, 9)
            X, Y, Z = facing([P[0], EYE, P[2]])
            self.ov.setOverlayTransformAbsolute(h, openvr.TrackingUniverseStanding, m34(X, Y, Z, P))
            hs.append((h, self.r.randrange(16)))
        return hs

    def _sprite(self, key, tex):
        try: return self._mk(key, tex, 1.0, 7 if key.startswith("patch") else 9)
        except Exception as e:
            self.log("weather sprite off:", key, repr(e)); return None

    def _vis(self, h, on, a):
        a = round(max(0.0, min(1.0, a)), 3); on = bool(on and a > 0.004)
        st = self._st.setdefault(h, [None, None, None])
        if st[0] != a: self.ov.setOverlayAlpha(h, a); st[0] = a
        if st[1] != on: (self.ov.showOverlay if on else self.ov.hideOverlay)(h); st[1] = on

    def _col(self, h, c):
        c = (round(c[0], 3), round(c[1], 3), round(c[2], 3))
        st = self._st.setdefault(h, [None, None, None])
        if st[2] != c: self.ov.setOverlayColor(h, *c); st[2] = c

    # ---------------------------------------------------------------- weather state
    def pick(self, now):
        names = [n for n in WEIGHTS if not (n == "clearing" and self.night)]
        n = self.r.choices(names, [WEIGHTS[k] for k in names])[0]
        self.name, self.target = n, dict(STATES[n]); self.until = now + self.r.uniform(20, 65) * 60
        self.log("weather ->", n)

    def update(self, now, show, night, mood=None, red=False, blend=None):
        self.night = night; self.tick += 1
        if mood and mood != self.mood: self.mood = mood; self._load_patches(mood)
        M = dict(MOOD.get(self.mood or "lain_dusk", MOOD["lain_dusk"]))
        if blend and blend[0] in MOOD and blend[1] in MOOD and 0 < blend[2] < 1:      # rain tint glides with the sky crossfade
            bt = blend[2]; bt = bt * bt * (3 - 2 * bt)
            M["rain"] = tuple(lerp(MOOD[blend[0]]["rain"], MOOD[blend[1]]["rain"], bt))
        # the weather clock pauses while the sky is hidden (a game, room view): coming back to the menu shows the weather
        # that was there when you left, not a different one that "happened" meanwhile
        if not show: self.until += max(0.0, now - self.last)
        elif now > self.until: self.pick(now)
        k = min(1.0, max(0.0, now - self.last) / TAU); self.last = now
        for key in self.cur: self.cur[key] += (self.target[key] - self.cur[key]) * k
        rn = self.cur["rain"]
        t = now - self.t0
        a = min(1.0, rn) * 0.8
        for (h, ph) in self.rain:
            self._vis(h, show and a > 0.02, a)
            if show and a > 0.02:
                fr = (int(t * 24) + ph) % 16; u, v = fr % 4, fr // 4
                self.ov.setOverlayTextureBounds(h, bounds(u / 4, v / 4, (u + 1) / 4, (v + 1) / 4)); self._col(h, M["rain"])
        self._lightning_tick(now, show, rn, red)
        self._cat(now, show, rn)
        self._crows(now, show, rn, M)
        self._car(now, show, M)
        self._spark(now, show, rn)
        self._lamp(now, show, M)
        self._puddle(now, show)
        self._patches(now, show, M, red)

    def _lightning_tick(self, now, show, rn, red):
        """random lightning: every 1-4 min in rain or a downpour, every 7-15 min in drizzle, never when dry. Kept gentle for
        photosensitive players: a soft rise and fade to soft lilac (never white), at most two pulses ~0.4 s apart."""
        if not self.bolt: return
        gap = (lambda: self.r.uniform(60, 240)) if rn > 0.9 else (lambda: self.r.uniform(420, 900)) if rn > 0.3 else None
        if gap is None or not show: self.next_flash = now + 1e9
        elif self.next_flash > now + 1e8: self.next_flash = now + gap()
        if now >= self.next_flash:
            self.flash_t = now; self.flash2 = self.r.random() < 0.55; self.next_flash = now + gap(); self.log("event: lightning")
        fs = now - self.flash_t
        f = min(1.0, fs / 0.07) if fs < 0.07 else math.exp(-(fs - 0.07) / 0.16) if fs < 1.6 else 0.0
        if self.flash2 and 0.38 < fs < 2.2:
            u = fs - 0.38; f = max(f, 0.7 * (min(1.0, u / 0.06) if u < 0.06 else math.exp(-(u - 0.06) / 0.45)))
        for h in self.bolt:
            self._col(h, FLASH_COL); self._vis(h, show and not red and f > 0.01, FLASH_A * f)

    # ---------------------------------------------------------------- hard hourly counts
    def _due(self, key, per_hour, now):
        """hard rule: per_hour events in every clock hour, at random minutes. True when one is due; the caller
        calls _done(key) once it really started (a blocked one stays due and retries on the next tick)."""
        hour = int(now // 3600); q = self.quota.get(key)
        if q is None:                                                            # starting mid-hour: the rest of this hour's share
            left = (hour + 1) * 3600.0 - now; n = int(round(per_hour * left / 3600.0))
            q = self.quota[key] = dict(hour=hour, times=sorted(now + self.r.uniform(0, left) for _ in range(n)))
        elif q["hour"] != hour:
            q["hour"] = hour; q["times"] += sorted(hour * 3600.0 + self.r.uniform(0, 3600) for _ in range(per_hour))
        return bool(q["times"]) and now >= q["times"][0]

    def _done(self, key):
        q = self.quota.get(key)
        if q and q["times"]: q["times"].pop(0)

    # ---------------------------------------------------------------- the black cat
    def _cat(self, now, show, rn):
        if not self.cat: return
        if self.ev_cat is None:
            if not show or not self._due("cat", CATS_PER_HOUR, now): return
            w = None
            ok = [c for c in self.wires if len(c) >= 2 and self._side_on(c)]      # wires seen side-on (the cat is a side view)
            recent = getattr(self, "_cat_recent", [])
            pool = [c for c in ok if id(c) not in recent] or ok
            if pool:                                                             # a random wire each time, no repeats; it runs the whole wire
                w = self.r.choice(pool); self._cat_recent = (recent + [id(w)])[-2:]
            if w is None: return
            if self.r.random() < 0.5: w = w[::-1]
            seg = [math.dist(a, b) for a, b in zip(w, w[1:])]; L = sum(seg)
            self.ev_cat = dict(w=w, seg=seg, L=L, t0=now, speed=self.r.uniform(2.0, 3.2)); self._done("cat"); self.log("event: black cat on a wire")
        e = self.ev_cat; s = (now - e["t0"]) * e["speed"]
        if s >= e["L"] or not show:
            self._vis(self.cat, False, 0); self.ev_cat = None; return
        i = 0
        while i < len(e["seg"]) - 1 and s > e["seg"][i]: s -= e["seg"][i]; i += 1
        a, b = e["w"][i], e["w"][i + 1]; f = s / max(e["seg"][i], 1e-6)
        p = scene_to_vr([a[k] + (b[k] - a[k]) * f for k in range(3)])
        P, sc = project(p)
        X, Y, Z = facing(P)
        mv = [b[0] - a[0], b[2] - a[2], -(b[1] - a[1])]
        dx = sum(mv[k] * X[k] for k in range(3)); dy = sum(mv[k] * Y[k] for k in range(3))
        flip = dx < 0; roll = max(-0.61, min(0.61, math.atan2(dy, abs(dx)))) * (-1 if flip else 1)     # never climbing a cliff
        X, Y, Z = facing(P, roll)
        P = [P[k] + Y[k] * 0.12 * sc for k in range(3)]                             # paws on the wire (feet sit 12 cm below the middle)
        self.ov.setOverlayWidthInMeters(self.cat, 0.55 * sc)                        # a ~55 cm cat at the wire's real distance
        self.ov.setOverlayTransformAbsolute(self.cat, openvr.TrackingUniverseStanding, m34(X, Y, Z, P))
        fr = int((now - e["t0"]) * e["speed"] / 0.9 * 8) % 8                      # gait locked to the distance run: one stride = 0.9 m, no sliding paws
        u0, u1 = fr / 8, (fr + 1) / 8
        self.ov.setOverlayTextureBounds(self.cat, bounds(u1, 0, u0, 1) if flip else bounds(u0, 0, u1, 1))
        run = (now - e["t0"]) * e["speed"]
        self._vis(self.cat, True, min(1.0, run / 0.8, (e["L"] - run) / 0.8))       # slips out from / behind the pole, no pop

    def _side_on(self, w):
        """the cat is a side view: 3/4 of the wire's length must cross your line of sight at > 45 deg with an on-screen
        slope under 35 deg (10 of the 119 wires qualify; the result is cached per wire)."""
        key = id(w); c = getattr(self, "_side_c", None)
        if c is None: c = self._side_c = {}
        if key in c: return c[key]
        good = tot = 0.0
        for a, b in zip(w, w[1:]):
            L = math.dist(a, b); tot += L
            m = [(a[k] + b[k]) / 2 for k in range(3)]; dv = [b[0] - a[0], b[1] - a[1]]
            los = math.hypot(m[0], m[1]) or 1.0; dl = math.hypot(*dv) or 1.0
            if abs(m[0] * dv[0] + m[1] * dv[1]) / (los * dl) > math.cos(math.radians(45)): continue
            P, _ = project(scene_to_vr(m)); X, Y, Z = facing(P)
            mv = [b[0] - a[0], b[2] - a[2], -(b[1] - a[1])]
            dx = sum(mv[k] * X[k] for k in range(3)); dy = sum(mv[k] * Y[k] for k in range(3))
            if abs(math.degrees(math.atan2(dy, abs(dx) + 1e-9))) <= 35: good += L
        c[key] = tot > 0 and good >= 0.75 * tot
        return c[key]

    # ---------------------------------------------------------------- crows: land on a near wire, sit a while, fly off
    def _perch(self):
        for _ in range(30):
            w = self.r.choice(self.wires)
            if len(w) < 3: continue
            i = self.r.randrange(1, len(w) - 1); p = w[i]
            dist = math.dist(p, (0, 0, EYE)); el = math.degrees(math.atan2(p[2] - EYE, math.hypot(p[0], p[1])))
            slope = abs(w[i + 1][2] - w[i - 1][2]) / max(math.dist(w[i + 1], w[i - 1]), 1e-6)
            if 9 < dist < 38 and el > 12 and slope < 0.25: return p
        return None

    def _crows(self, now, show, rn, M):
        for i, h in enumerate(self.crows):
            e = self.crow_ev[i]
            if e is None:
                if show and self._due("bird", BIRDS_PER_HOUR, now):
                    if self.r.random() < 0.45:                                       # a bird crossing the whole sky on a random curve
                        self.crow_ev[i] = self._flyby(now); self._done("bird"); self.log("event: bird flies over"); continue
                    p = self._perch()
                    if p:                                                            # or: lands on a wire, sits a while, flies away
                        ang = self.r.uniform(0, 2 * math.pi); r_ = self.r.uniform(10, 24)
                        start = [p[0] + r_ * math.cos(ang), p[1] + r_ * math.sin(ang), p[2] + self.r.uniform(3, 12)]
                        ang2 = self.r.uniform(0, 2 * math.pi); r2 = self.r.uniform(25, 45)
                        e2 = dict(p=p, a=start, ca=self._ctrl(start, p), t0=now, stay=self.r.uniform(25, 150) * (0.6 if rn > 0.4 else 1.0),
                                  b=[p[0] + r2 * math.cos(ang2), p[1] + r2 * math.sin(ang2), p[2] + self.r.uniform(8, 18)],
                                  fly=self.r.uniform(1.8, 3.2), face=self.r.choice((1, -1)), idle=now + self.r.uniform(3, 9), frame=0)
                        e2["cb"] = self._ctrl(p, e2["b"]); self.crow_ev[i] = e2; self._done("bird"); self.log("event: crow lands")
                continue
            if not show: self._vis(h, False, 0); continue
            ts = now - e["t0"]
            if e.get("over"):                                                        # fly-over: the whole curve, flapping, then gone
                u = ts / e["dur"]
                if u >= 1: self._vis(h, False, 0); self.crow_ev[i] = None; continue
                q = _bez2(e["a"], e["c"], e["b"], u); q2 = _bez2(e["a"], e["c"], e["b"], min(1.0, u + 0.02))
                self._draw_bird(h, q, 3 + int(ts * e["flap"]) % 2, self._dir_x(q, q2), min(1.0, ts / 0.4, (e["dur"] - ts) / 0.4)); continue
            fly = e.get("fly", 2.4)
            if ts < fly:                                                             # landing: glide in on a random curve, flapping
                u = ts / fly; u2 = 1 - (1 - u) ** 2
                q = _bez2(e["a"], e["ca"], e["p"], u2); q2 = _bez2(e["a"], e["ca"], e["p"], min(1.0, u2 + 0.02))
                frame = 3 + int(ts * 9) % 2 if u < 0.85 else 0; facing_x = self._dir_x(q, q2)
            elif ts < fly + e["stay"]:                                               # perched: mostly still, a head turn, a ruffle
                q = e["p"]; facing_x = e["face"]
                if now >= e["idle"]:
                    e["frame"] = self.r.choices((0, 1, 2), (55, 35, 10))[0]; e["idle"] = now + (self.r.uniform(0.3, 0.6) if e["frame"] == 2 else self.r.uniform(1.5, 7))
                frame = e["frame"]
            elif ts < fly * 3 + e["stay"]:                                           # leaving: up and away, out of sight
                u = (ts - fly - e["stay"]) / (2 * fly)
                q = _bez2(e["p"], e["cb"], e["b"], u * u); q2 = _bez2(e["p"], e["cb"], e["b"], min(1.0, u * u + 0.02))
                frame = 3 + int(ts * 9) % 2; facing_x = self._dir_x(q, q2)
            else:
                self._vis(h, False, 0); self.crow_ev[i] = None; continue
            self._draw_bird(h, q, frame, facing_x, min(1.0, ts / 0.6, (fly * 3 + e["stay"] - ts) / 0.6))

    def _draw_bird(self, h, q, frame, facing_x, fade):
        P, sc = project(scene_to_vr(q))
        X, Y, Z = facing(P)
        P = [P[k] + Y[k] * (0.21 if frame < 3 else 0.0) * sc for k in range(3)]      # feet on the wire
        self.ov.setOverlayWidthInMeters(h, 0.65 * sc)
        self.ov.setOverlayTransformAbsolute(h, openvr.TrackingUniverseStanding, m34(X, Y, Z, P))
        u0, u1 = frame / 5, (frame + 1) / 5
        self.ov.setOverlayTextureBounds(h, bounds(u0, 0, u1, 1) if facing_x > 0 else bounds(u1, 0, u0, 1))
        self._vis(h, True, fade)

    def _ctrl(self, a, b):
        """a random bend for a flight curve between a and b (no two flights take the same line)."""
        m = [(a[k] + b[k]) / 2 for k in range(3)]; d = math.dist(a, b)
        return [m[0] + self.r.uniform(-0.5, 0.5) * d, m[1] + self.r.uniform(-0.5, 0.5) * d, m[2] + self.r.uniform(0, 0.4) * d]

    def _flyby(self, now):
        """a bird crossing the WHOLE sky: from one side of you to the far other side (random azimuths ~140-220 deg apart,
        10-50 deg up, 25-60 m out), on a random curve, 6-12 s, appearing and leaving at the edges."""
        def pt(az):
            el = math.radians(self.r.uniform(10, 50)); d = self.r.uniform(25, 60)
            return [d * math.cos(el) * math.cos(az), d * math.cos(el) * math.sin(az), EYE + d * math.sin(el)]
        az = self.r.uniform(0, 2 * math.pi)
        a = pt(az); b = pt(az + math.pi + math.radians(self.r.uniform(-40, 40)))
        return dict(over=True, a=a, b=b, c=self._ctrl(a, b), t0=now, dur=self.r.uniform(6, 12), flap=self.r.uniform(7, 11))

    def _dir_x(self, q, q2):
        """which way the sprite faces: its on-screen direction of travel."""
        P, _ = project(scene_to_vr(q)); P2, _ = project(scene_to_vr(q2)); X, Y, Z = facing(P)
        return 1 if sum((P2[k] - P[k]) * X[k] for k in range(3)) >= 0 else -1

    # ---------------------------------------------------------------- electricity crackling at a pole
    def _insulators(self):
        """pole tops / transformers = where several wire ends meet (from wires.json), 6-45 m away."""
        groups = {}
        for w in self.wires:
            for p in (w[0], w[-1]): groups.setdefault((round(p[0]), round(p[1]), round(p[2])), []).append(p)
        pts = [[sum(c) / len(v) for c in zip(*v)] for v in groups.values() if len(v) >= 2]
        return [p for p in pts if 6 < math.dist(p, (0, 0, EYE)) < 45 and p[2] > 4]

    def _spark(self, now, show, rn):
        if not self.spark or not self.spark_pts: return
        if self.ev_spark is None:
            if now < self.next_spark or not show: return
            seq, t = [], 0.0
            for _ in range(self.r.randint(2, 5)):                                    # a few quick crackles in a row
                d = self.r.uniform(0.04, 0.11); seq.append((t, t + d, self.r.randrange(8))); t += d + self.r.uniform(0.05, 0.3)
            p = self.r.choice(self.spark_pts)
            self.ev_spark = dict(t0=now, seq=seq, end=t, p=[p[0] + self.r.uniform(-0.3, 0.3), p[1], p[2] + self.r.uniform(-0.2, 0.2)])
            self.log("event: sparks at a pole")
        e = self.ev_spark; ts = now - e["t0"]
        if ts > e["end"] or not show:
            self._vis(self.spark, False, 0); self.ev_spark = None
            self.next_spark = now + self.r.uniform(900, 2100) / (2.2 if rn > 0.4 else 1.0); return     # ~2/h, ~4/h in rain
        on = next((f for a, b, f in e["seq"] if a <= ts < b), None)
        if on is None: self._vis(self.spark, False, 0); return
        P, sc = project(scene_to_vr(e["p"]))
        X, Y, Z = facing(P, self.r.uniform(-0.5, 0.5))
        self.ov.setOverlayWidthInMeters(self.spark, 0.6 * sc)                         # ~60 cm crackle at the pole's real distance
        self.ov.setOverlayTransformAbsolute(self.spark, openvr.TrackingUniverseStanding, m34(X, Y, Z, P))
        self.ov.setOverlayTextureBounds(self.spark, bounds(on / 8, 0, (on + 1) / 8, 1))
        self._vis(self.spark, True, 0.9)

    # ---------------------------------------------------------------- a street lamp buzzing (its glow stutters for a few seconds)
    def _lamp(self, now, show, M):
        if not self.lampg: return
        if self.ev_lamp is None:
            if now < self.next_lamp or not show or not M["lights"]: return
            seq, t = [], 0.0
            for _ in range(self.r.randint(5, 14)):                                   # irregular on/off steps, like a failing ballast
                d = self.r.uniform(0.03, 0.14); seq.append((t, t + d, self.r.uniform(0.3, 0.8))); t += d + self.r.uniform(0.04, 0.35)
            self.ev_lamp = dict(t0=now, seq=seq, end=t, p=self.r.choice(self.lamps)); self.log("event: lamp buzz")
        e = self.ev_lamp; ts = now - e["t0"]
        if ts > e["end"] or not show:
            self._vis(self.lampg, False, 0); self.ev_lamp = None; self.next_lamp = now + self.r.uniform(300, 1200); return
        a = next((v for s0, s1, v in e["seq"] if s0 <= ts < s1), 0.0)
        if a <= 0: self._vis(self.lampg, False, 0); return
        P, sc = project(scene_to_vr(e["p"][:3]))
        X, Y, Z = facing(P)
        self.ov.setOverlayWidthInMeters(self.lampg, 1.6 * sc)                       # a ~1.6 m halo around the lamp head
        self.ov.setOverlayTransformAbsolute(self.lampg, openvr.TrackingUniverseStanding, m34(X, Y, Z, P))
        self._col(self.lampg, (1.0, 0.72, 0.42) if e["p"][3] == "sodium" else (0.9, 0.93, 1.0))
        self._vis(self.lampg, True, a * (0.55 if self.mood == "lain_night" else 0.35))

    # ---------------------------------------------------------------- a puddle shows the Wired for a moment (the red sky, rippling)
    def _puddle(self, now, show):
        if not self.puddle: return
        if self.ev_puddle is None:
            if now < self.next_puddle or not show: return
            side = self.r.choice((-1, 1)); x = self.r.uniform(0.8, 3.0) * self.r.choice((-1, 1)); y = side * self.r.uniform(4.0, 9.0)
            self.ev_puddle = dict(t0=now, P=[x, 0.012, -y], dur=self.r.uniform(7, 12), w=self.r.uniform(1.3, 2.2)); self.log("event: puddle reflection")
        e = self.ev_puddle; ts = now - e["t0"]
        if ts > e["dur"] or not show:
            self._vis(self.puddle, False, 0); self.ev_puddle = None; self.next_puddle = now + self.r.uniform(1500, 3600); return
        a = min(1.0, ts / 3.0, (e["dur"] - ts) / 3.0); a = a * a * (3 - 2 * a) * 0.7          # the reflection seeps in and out
        self.ov.setOverlayWidthInMeters(self.puddle, e["w"])
        dn = math.hypot(e["P"][0], e["P"][2]) or 1.0; dx, dz = e["P"][0] / dn, e["P"][2] / dn     # texture up = away from you
        self.ov.setOverlayTransformAbsolute(self.puddle, openvr.TrackingUniverseStanding, m34([-dz, 0, dx], [dx, 0, dz], [0, 1, 0], e["P"]))   # lying flat
        fr = int(ts * 8) % 8; u, v = fr % 4, fr // 4
        self.ov.setOverlayTextureBounds(self.puddle, bounds(u / 4, v / 2, (u + 1) / 4, (v + 1) / 2))
        self._vis(self.puddle, True, a)

    # ---------------------------------------------------------------- a car light crossing the far end of the street
    def _car(self, now, show, M):
        if not self.car: return
        if self.ev_car is None:
            if now < self.next_car or not show: return
            d = self.r.uniform(170, 260) * self.r.choice((1, -1)); x0 = self.r.choice((-1, 1)) * 7.5
            self.ev_car = dict(t0=now, y=d, x0=x0, v=-math.copysign(self.r.uniform(7, 12), x0)); self.log("event: car light")
        e = self.ev_car; x = e["x0"] + e["v"] * (now - e["t0"])
        if abs(x) > 7.6 or not show:
            self._vis(self.car, False, 0); self.ev_car = None
            self.next_car = now + self.r.uniform(90, 400) / max(M["car"], 0.05); return
        P, sc = project(scene_to_vr([x, e["y"], 0.75]))
        X, Y, Z = facing(P)
        P = [P[k] - Y[k] * 0.1 * 3.0 * sc for k in range(3)]                       # the sprite's lamp sits 10% above its middle
        self.ov.setOverlayWidthInMeters(self.car, 3.0 * sc)
        self.ov.setOverlayTransformAbsolute(self.car, openvr.TrackingUniverseStanding, m34(X, Y, Z, P))
        edge = min(1.0, (7.6 - abs(x)) / 1.5)                                         # appears / disappears at the cross street
        self._vis(self.car, True, edge * (0.9 if M["lights"] else 0.35))

    # ---------------------------------------------------------------- windows: lights off and on, a TV flickering
    def _load_patches(self, mood):
        self.patches = []
        try: items = json.load(open(os.path.join(SKIES, mood, "patches", "patches.json")))
        except (OSError, ValueError): items = []
        from skyclock import FACES
        for h, it in zip(self.patch_h, items):
            F, X, Y = FACES[it["face"]]; S = it["size"]; Rr = CUBE_R - 1.0
            cx = (it["x"] + it["w"] / 2) / S * 2 - 1; cy = 1 - (it["y"] + it["h"] / 2) / S * 2
            P = [Rr * (F[k] + cx * X[k] + cy * Y[k]) for k in range(3)]; P[1] += EYE
            self.ov.setOverlayFromFile(h, os.path.join(SKIES, mood, "patches", it["file"]))
            self.ov.setOverlayWidthInMeters(h, it["w"] / S * 2 * Rr)
            self.ov.setOverlayTransformAbsolute(h, openvr.TrackingUniverseStanding, m34(X, Y, [-c for c in F], P))
            self.patches.append(dict(h=h, kind=it["kind"], a=0.0, tgt=0.0, next=time.time() + self.r.uniform(20, 400)))
        for h in self.patch_h[len(self.patches):]: self._vis(h, False, 0)

    def _patches(self, now, show, M, red=False):
        for p in self.patches:
            if now >= p["next"]:
                if p["kind"] == "window":                                            # someone switches the light off / on
                    p["tgt"] = 1.0 - round(p["tgt"]); p["next"] = now + self.r.uniform(120, 900)
                else:                                                                # TV: restless cold flicker, off now and then
                    if p["tgt"] > 0 and self.r.random() < 0.01: p["tgt"] = 0.0; p["next"] = now + self.r.uniform(300, 1200)
                    else: p["tgt"] = self.r.uniform(0.35, 0.85); p["next"] = now + self.r.uniform(0.12, 0.7)
            rate = 0.5 if p["kind"] == "window" else 0.35
            p["a"] += (p["tgt"] - p["a"]) * rate
            self._vis(p["h"], show and M["lights"] and not red, p["a"])
