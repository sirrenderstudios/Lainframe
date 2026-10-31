"""Runs render/lain_sky.py (unchanged on disk) with a better roof for the small houses (2026-10-23: "the house's
roof reads as a thin lid floating over the walls" + "a weird part coming off the roof" = the same roof seen edge-on).
2026-10-26 wire tidy-up (ANCHOR_CODE): far wires down the street thinned (whole wires), dead ends continue their own
hanging curve to an anchor, wire ends piercing a wall end where they meet it. Shipped 10-24 version: sky_rebuild.py.bak-anchor2.
v1 roof: two zero-thickness planes, eaves 0.3 m BELOW the wall top, 0.6 m overhang on all sides, open gables (you saw
the sky through the triangle between wall top and roof). v2 roof: gable walls closing the triangles, two roof slabs
20 cm thick sitting ON the walls (eave overhang 0.45 m, gable overhang 0.3 m, ~30 deg pitch), fascia at the slab
ends, a ridge cap and a gutter along each eave. The random sequence is untouched (the new code draws no random
numbers), so everything else in the street stays exactly where it was.
  blender -b --factory-startup --python sky_rebuild.py -- <face_px> <samples> <outdir>     (env VARIANT, FACES as lain_sky)"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "lain_sky.py")
code = open(SRC, encoding="utf-8").read()

OLD = '''    xm = (xi + xo) / 2; ov = 0.6
    quad("roof", [(xi - s * ov, y0 - ov, H - 0.3), (xi - s * ov, y1 + ov, H - 0.3), (xm, y1 + ov, H + 2.2), (xm, y0 - ov, H + 2.2)])
    quad("roof", [(xo + s * ov, y0 - ov, H - 0.3), (xm, y0 - ov, H + 2.2), (xm, y1 + ov, H + 2.2), (xo + s * ov, y1 + ov, H - 0.3)])
'''
NEW = '''    house_roof(mat, s, xi, xo, y0, y1, H)
'''
ROOF = '''

# wire categories for the far-wire thinning: no random numbers are drawn here
_wire_base = wire
WCAT = {}
def wire(p0, p1, sag, thick=0.012, n=18):
    _wire_base(p0, p1, sag, thick, n)
    WCAT[id(WIRES[round(thick, 3)][-1])] = CATLINE.get(sys._getframe(1).f_lineno, "?")


def hexa(mat, P):
    """8 corners (bottom 0-3, top 4-7, same winding) -> 6 quads."""
    for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        quad(mat, [P[i] for i in f])


def house_roof(mat, s, xi, xo, y0, y1, H):
    """gable roof with thickness sitting on the walls; no random numbers drawn (keeps the street identical)."""
    xm = (xi + xo) / 2; hw = abs(xo - xi) / 2; rise = 0.58 * hw; slope = rise / hw
    ove, ovg, th = 0.45, 0.30, 0.20
    ya, yb = y0 - ovg, y1 + ovg
    for yy in (y0, y1):
        quad(mat, [(xi, yy, H), (xo, yy, H), (xm, yy, H + rise)])
    for a in (xi, xo):
        sg = 1 if a > xm else -1
        e = a + sg * ove; ze = H - ove * slope                       # the roof plane passes through the wall top edge
        zr = H + rise
        b0, b1 = (e, ze), (xm, zr)
        t0, t1 = (e, ze + th), (xm, zr + th)
        hexa("roof", [(b0[0], ya, b0[1]), (b1[0], ya, b1[1]), (b1[0], yb, b1[1]), (b0[0], yb, b0[1]),
                      (t0[0], ya, t0[1]), (t1[0], ya, t1[1]), (t1[0], yb, t1[1]), (t0[0], yb, t0[1])])
        box("frame", e - sg * 0.02, ya, ze - 0.02, e + sg * 0.04, yb, ze + th + 0.02)            # fascia board
        cyl("metal", (e + sg * 0.09, ya, ze - 0.04), (e + sg * 0.09, yb, ze - 0.04), 0.065, n=8)  # gutter
    box("roof", xm - 0.16, ya, H + rise + th - 0.05, xm + 0.16, yb, H + rise + th + 0.12)        # ridge cap
'''

ANCHOR_CODE = """

# ------------------------------------------------------------------ wire tidy-up (2026-10-26)
# 1. thin the FAR wires down the street (whole wires only, own random generator: the scene's R sequence is untouched)
# 2. dead ends are extended by CONTINUING the wire's own hanging curve (same parabola, continuous tangent, a gentle
#    plan-view arc at most) until it meets a wall / pole / roof edge (bracket + insulator) or a window (ends in it)
# 3. a wire end that pierces a building (grazing into a wall next to a window) is ended where it first meets it
def thin_far_wires():
    rr = random.Random(2610)
    rem = dict(cross=0, extra=0)
    for th, lst in WIRES.items():
        keep = []
        for pts in lst:
            cat = WCAT.get(id(pts), "?")
            dmin = min(math.hypot(p[0], p[1]) for p in pts)
            u = rr.random()
            if cat == "cross": p = THIN_CROSS * min(1.0, max(0.0, (dmin - 50.0) / 50.0))
            elif cat in ("extra", "drop"): p = THIN_EXTRA * min(1.0, max(0.0, (dmin - 60.0) / 60.0))
            else: p = 0.0
            if u < p: rem["cross" if cat == "cross" else "extra"] += 1
            else: keep.append(pts)
        lst[:] = keep
    return rem


THIN_CROSS = float(os.environ.get("THIN_CROSS", "0.88"))
THIN_EXTRA = float(os.environ.get("THIN_EXTRA", "0.65"))


def anchor_wires():
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    import json as _json
    removed = thin_far_wires()
    dg = bpy.context.evaluated_depsgraph_get()
    SKIP = {"asphalt", "line", "curb", "walk", "chainlink", "rail"}             # never anchor a wire on the ground / a fence
    NOANCH = SKIP | {"lamp", "sodium", "neon_pink", "neon_cyan", "neon_white", "vend"}
    WINDOWS = {"glass", "lit_warm", "lit_cool", "lit_pink"}
    trees = []
    def build_all():
        trees[:] = []; V = []; F = []; FM = []
        for ob in list(col_main.objects) + list(col_noline.objects):
            if ob.type != "MESH": continue
            base = ob.name.split(".")[0]
            trees.append((base, BVHTree.FromObject(ob, dg)))
            me = ob.data; o = len(V)
            V.extend([tuple(v.co) for v in me.vertices])
            for p in me.polygons:
                F.append(tuple(o + i for i in p.vertices)); FM.append(base)
        return BVHTree.FromPolygons(V, F), FM
    ALL, FMAT = build_all()
    def nearest(p):
        best = (1e9, None)
        for nm, t in trees:
            r = t.find_nearest(p)
            if r[0] is not None and r[3] < best[0]: best = (r[3], nm)
        return best
    def nearest_n(p):
        best = (1e9, None, None, None)
        for nm, t in trees:
            r = t.find_nearest(p)
            if r[0] is not None and r[3] < best[0]: best = (r[3], nm, r[0], r[1])
        return best
    WALLS = {"conc_a", "conc_b", "conc_c", "tile", "roof", "glass", "lit_warm", "lit_cool", "lit_pink", "red", "yellow"}
    BUILD = WALLS | {"frame"}
    def cast(o, d, dist):
        best = None
        for nm, t in trees:
            loc, nrm, idx, dd = t.ray_cast(o, d, dist)
            if loc is not None and (best is None or dd < best[3]): best = (loc, nrm, nm, dd)
        return best
    def seg_hit(p, q):
        d = q - p; L = d.length
        if L < 1e-9: return None
        loc, nrm, idx, dd = ALL.ray_cast(p, d / L, L)
        return None if loc is None else (loc, nrm, FMAT[idx], dd, d / L)
    def anchored(pts, end):
        P = [Vector(q) for q in (pts if end else pts[::-1])]
        d, nm = nearest(P[-1])
        if d < 0.10: return True, "touches " + str(nm)                     # on it (insulator top, clamp, wall), not just near a gutter
        inside = 0                                                              # the END itself is inside a solid (wall, pole, roof slab)
        for dv in (Vector((0, 0, 1)), Vector((0, 0, -1)), Vector((1, 0, 0)), Vector((-1, 0, 0))):
            h = cast(P[-1], dv, 200.0)
            if h is not None and h[1].dot(dv) > 0: inside += 1                      # first surface met from behind
        if inside >= 3: return True, "ends inside " + str(nm)
        return False, "open (nearest %.2f m)" % d
    def bracket(loc, nrm):
        b0 = loc + nrm * 0.02; b1 = loc + nrm * 0.12
        cyl("metal", tuple(loc - nrm * 0.02), tuple(b1), 0.025, n=6)
        box("metal", b0.x - 0.06, b0.y - 0.06, b0.z - 0.06, b0.x + 0.06, b0.y + 0.06, b0.z + 0.06)
        cyl("insul", tuple(b1), tuple(loc + nrm * 0.17), 0.035, n=6)
    def continue_curve(P, SL=1.3, SMAX=140.0):
        # P: wire points with the dead end last (an original 19-point parabola). The wire keeps hanging the same way:
        # z = e + m s + c s^2 in horizontal distance s with the end's own slope m (continuous tangent) and a sag c >= 0 close
        # to its own (c0 = the original parabola), plan heading straight or bending gently (constant curvature k).
        e = P[-1]; v = (3 * P[-1] - 4 * P[-2] + P[-3]) / 2; acc = P[-1] - 2 * P[-2] + P[-3]
        hs = Vector((v.x, v.y, 0)).length
        if hs < 1e-6: return None
        m = v.z / hs; c0 = max(0.0, 0.5 * acc.z / hs ** 2); th0 = math.atan2(v.y, v.x)
        zmin = 0.8 if e.z < 5.0 else 2.5                                      # a low service drop may meet the wall low down
        DS = 0.35
        combos = []
        for cf in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3, 0.2, 0.1, 0.05, 0.0, 1.3, 1.7, 2.2):
            for k in (0.0, 1 / 160, -1 / 160, 1 / 90, -1 / 90, 1 / 55, -1 / 55, 1 / 35, -1 / 35, 1 / 25, -1 / 25, 1 / 18, -1 / 18):
                combos.append((abs(cf - 1.0) * 1.2 + abs(k) * 60, cf, k))
        combos.sort()
        best = None
        for pen, cf, k in combos:
            if best is not None and pen >= best[0]: break
            c = c0 * cf; pts = [e]; x, y = e.x, e.y; s = 0.0; ok = False
            while s < SMAX:
                s2 = s + DS; tm = th0 + k * (s + DS / 2)
                x += math.cos(tm) * DS; y += math.sin(tm) * DS
                q = Vector((x, y, e.z + m * s2 + c * s2 * s2))
                if m + 2 * c * s2 > SL or q.z < zmin or abs(k) * s2 > 0.35: break   # too steep / into the street / turning: not this one
                hit = seg_hit(pts[-1], q)
                if hit is not None:
                    loc, nrm, nm, dd, dv = hit
                    if nm in NOANCH or nrm.dot(dv) > -0.08: break       # a fence / lamp / the back of something: no
                    ok = True; break
                pts.append(q); s = s2
            if ok:
                sc = pen + s / 80.0                                         # shape first, then the shorter one
                if best is None or sc < best[0]: best = (sc, (pts, loc, nrm, nm, cf, k))
        return best[1] if best else None
    def old_extend(pts, end):
        # the 10-24 straight extension, kept ONLY for line ends sitting inside a pole (0.3 m to a bracket on the pole:
        # nothing visible changes there)
        P = [Vector(q) for q in (pts if end else pts[::-1])]
        e = P[-1]; tg = P[-1] - P[-2]; h = Vector((tg.x, tg.y, 0))
        if h.length < 1e-6: h = Vector((1 if e.x > 0 else -1, 0, 0))
        h.normalize(); out = Vector((1 if e.x > 0 else -1, 0, 0))
        best = None
        for base in (h, out):
            for yaw in (0, 10, -10, 20, -20, 35, -35, 50, -50, 65, -65):
                for pitch in (0, -8, -16, -26, -38, -52):
                    c, s_ = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
                    d = Vector((base.x * c - base.y * s_, base.x * s_ + base.y * c, 0))
                    d = (d * math.cos(math.radians(pitch)) + Vector((0, 0, math.sin(math.radians(pitch))))).normalized()
                    if d.dot(Vector((h.x, h.y, 0))) < 0.3: continue
                    hit = cast(e + d * 0.05, d, 45.0)
                    if hit is None or hit[2] in SKIP: continue
                    score = hit[3] * (1 + (abs(yaw) + abs(pitch)) / 90.0)
                    if best is None or score < best[0]: best = (score, hit, d)
        if best is None: return None
        loc, nrm, nm, dd = best[1]
        window = nm in ("glass", "lit_warm", "lit_cool", "lit_pink")
        tip = loc - nrm * 0.25 if window else loc + nrm * 0.16
        seg = tip - e; n = max(3, int(seg.length / 1.5)); sag = 0.015 * seg.length
        add = [tuple(e + seg * (k / n) - Vector((0, 0, 4 * sag * (k / n) * (1 - k / n)))) for k in range(1, n + 1)]
        if end: pts.extend(add)
        else: pts[:0] = add[::-1]
        if not window: bracket(loc, nrm)
        return round(seg.length, 2), nm
    def pierce(P):
        # P with the end last; the end is inside something. First entry into a building along the last half of the wire.
        for j in range(len(P) // 2, len(P) - 1):
            hit = seg_hit(P[j], P[j + 1])
            if hit is None: continue
            loc, nrm, nm, dd, dv = hit
            if nm not in BUILD or nrm.dot(dv) > 0: return None
            rest = dd + sum((P[i + 1] - P[i]).length for i in range(j + 1, len(P) - 1))
            if rest < 0.04: return None
            return j, loc, nrm, nm, rest
        return None
    def in_pole(q):
        return any(abs(q.x - pp["x"]) < 0.2 and abs(q.y - pp["y"]) < 0.2 and q.z < pp["H"] for pp in POLES[-1] + POLES[1])
    unanch = []                                     # a wire whose dead end can't continue its own curve to anything: removed whole
    for th, lst in WIRES.items():
        keep = []
        for pts in lst:
            bad = False
            for end in (True, False):
                ok, why = anchored(pts, end)
                if ok: continue
                P = [Vector(q) for q in (pts if end else pts[::-1])]
                if in_pole(P[-1]): continue
                if continue_curve(P) is None and continue_curve(P, 2.0, 260.0) is None: bad = True; break
            if bad: unanch.append(dict(th=th, a=[round(c, 2) for c in pts[0]], b=[round(c, 2) for c in pts[-1]]))
            else: keep.append(pts)
        lst[:] = keep
    G.clear(); G.update({k: Geo() for k in M})                                 # new geometry = only the anchors
    total = ends = dead0 = 0; ext = []; rep = []; fixed_n = [0]; trims = []
    for th, lst in WIRES.items():
        for wi, pts in enumerate(lst):
            total += 1
            for end in (True, False):
                ends += 1
                ok, why = anchored(pts, end)
                if ok:
                    if why.startswith("touches"):                             # meets a wall / window: give it a visible fixing
                        d_, nm_, loc_, nrm_ = nearest_n(Vector(pts[-1] if end else pts[0]))
                        if nm_ in WALLS and nrm_ is not None:
                            box("metal", loc_.x - 0.05, loc_.y - 0.05, loc_.z - 0.05, loc_.x + 0.05, loc_.y + 0.05, loc_.z + 0.05)
                            cyl("insul", tuple(loc_), tuple(loc_ + nrm_ * 0.12), 0.03, n=6)
                            fixed_n[0] += 1
                    elif why.startswith("ends inside"):                       # sticks into a wall: end it where it meets the building
                        P = [Vector(q) for q in (pts if end else pts[::-1])]
                        pr = pierce(P)
                        if pr is not None:
                            j, loc, nrm, nm, rest = pr
                            win = nm in WINDOWS
                            tip = loc - nrm * 0.015 if win else loc + nrm * 0.16
                            if not win: bracket(loc, nrm)
                            newp = [tuple(q) for q in P[:j + 1]] + [tuple(tip)]
                            if end: pts[:] = newp
                            else: pts[:] = newp[::-1]
                            trims.append(dict(th=th, i=wi, end="end" if end else "start", onto=nm, window=win, cut=round(rest, 2),
                                              at=[round(c, 2) for c in loc]))
                    continue
                dead0 += 1
                P = [Vector(q) for q in (pts if end else pts[::-1])]
                if in_pole(P[-1]):
                    # a line ending inside its pole: extended exactly as on 10-24 (short, to a bracket; nothing visible changes)
                    r0 = old_extend(pts, end)
                    if r0 is not None:
                        ext.append(dict(th=th, i=wi, end="end" if end else "start", onto=r0[1], len=r0[0], old_style=True)); continue
                r = continue_curve(P) if len(P) >= 3 else None
                if r is None and len(P) >= 3: r = continue_curve(P, 2.0, 260.0)
                if r is None:
                    rep.append(dict(th=th, i=wi, end=end, p=list(P[-1]), why="NO SMOOTH ANCHOR FOUND")); continue
                cpts, loc, nrm, nm, cf, k = r
                window = nm in WINDOWS
                tip = loc - nrm * 0.015 if window else loc + nrm * 0.16
                add = [tuple(q) for q in cpts[1:]] + [tuple(tip)]
                if end: pts.extend(add)
                else: pts[:0] = add[::-1]
                if not window: bracket(loc, nrm)
                L = sum((cpts[i + 1] - cpts[i]).length for i in range(len(cpts) - 1)) + (tip - cpts[-1]).length
                ext.append(dict(th=th, i=wi, end="end" if end else "start", onto=nm, window=window, len=round(L, 2), n=len(add),
                                c_factor=cf, bend=round(k, 4), at=[round(c, 2) for c in loc]))
    flush_meshes()                                                             # the anchors become geometry too
    # re-check every endpoint against the scene incl. the new anchors
    bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get(); build_all()
    dead1 = []
    for th, lst in WIRES.items():
        for wi, pts in enumerate(lst):
            for end in (True, False):
                ok, why = anchored(pts, end)
                if not ok: dead1.append(dict(th=th, i=wi, end="end" if end else "start", p=[round(c, 2) for c in (pts[-1] if end else pts[0])], why=why))
    res = dict(variant=VARIANT, removed_far=removed, removed_unanchorable=unanch, wall_fixings=fixed_n[0], wires=total, endpoints=ends, dead_before=dead0, extended=len(ext),
               trimmed=len(trims), dead_after=len(dead1), failed=rep, still_dead=dead1, extensions=ext, trims=trims)
    _json.dump(res, open(os.path.join(OUT, "wire_check.json"), "w"), indent=1)
    print("WIRECHECK unanchorable_removed=%d wires=%d removed=%s endpoints=%d dead_before=%d extended=%d failed=%d trimmed=%d wall_fixings=%d dead_after=%d" % (
        len(unanch), total, removed, ends, dead0, len(ext), len(rep), len(trims), fixed_n[0], len(dead1)), flush=True)

"""
assert OLD in code, "lain_sky.py house() changed: update sky_rebuild.py"
assert "flush_meshes(); flush_wires()" in code
code = code.replace("flush_meshes(); flush_wires()", ANCHOR_CODE + "flush_meshes(); anchor_wires(); flush_wires()", 1)
code = code.replace(OLD, NEW)
code = code.replace("\ndef house(s, y0, y1, xf):", ROOF + "\n\ndef house(s, y0, y1, xf):", 1)
CATS = [("wire(pa, pb, span * R.uniform(0.012, 0.022)", "power"), ("wire(ta, tb, span", "telecom"),
        ("if R.random() < 0.5: wire((ta[0]", "extra"), ('wire((a["x"], a["y"], za)', "extra"),
        ("wire(src, (s * R.uniform(7.0, 8.0)", "drop"), ("wire(pa, pb, d * R.uniform(0.02, 0.06)", "cross"),
        ("wire((-R.uniform(8, 12), y0", "cross")]
CATLINE = {}
for _n, _ln in enumerate(code.split("\n")):
    for _s, _c in CATS:
        if _s in _ln: CATLINE[_n + 1] = _c
assert len(CATLINE) == 7, CATLINE
# 2026-10-26: "all moods should have the same amount of wires". Sunset had wires=2.6 (dusk/night/day 1.6): that
# multiplier sets how many across-road and rooftop cables are drawn, so sunset got a different, denser wire set. All
# moods now use 1.6 -> one shared wire set (wire passes are the last random draws, nothing else in the street moves).
assert 'spot=500, wires=2.6' in code
code = code.replace('spot=500, wires=2.6', 'spot=500, wires=1.6', 1)
g = {"__name__": "__main__", "__file__": SRC, "CATLINE": CATLINE}

exec(compile(code, SRC, "exec"), g)
