"""Skybox v6 "Wired Street" (2026-10-23): standing in the middle of a long road in a rainy, hazy, purple-brown
late-90s anime suburb: apartment blocks, metal fences, street lights overhead and LOTS of wires. Original scene
in the spirit of the show's look, nothing copied.

Blender (Cycles + Freestyle ink lines). Freestyle can't do panoramic cameras, so it renders the 6 cube faces with
90-degree cameras at eye height 1.7 m, plus a distance pass per face (material override: emission = view distance),
and saves them as .npy. lain_post.py then stitches the equirect, adds haze, rain and the colour grade.
  blender -b --python lain_sky.py -- <face_px> <samples> <outdir>
"""
import bpy, bmesh, math, os, random, sys
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
FACE = int(argv[0]) if len(argv) > 0 else 512
SAMPLES = int(argv[1]) if len(argv) > 1 else 24
OUT = os.path.abspath(argv[2]) if len(argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "lain_sky", "preview")
FACES_ONLY = os.environ.get("FACES", "")                      # e.g. "py" = only the forward face (quick look)
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gpu_setup import use_gpu

R = random.Random(1998)
EYE = 1.7
L = 420.0                                                     # road runs y = -L .. L
VARIANT = os.environ.get("VARIANT", "dusk")
P = {  # three moods. sky: (horizon, mid, zenith) colours; win/lamp: emission strengths; wires: density multiplier
    "dusk":   dict(sky=((0.92, 0.82, 0.95), (0.7, 0.6, 0.8), (0.42, 0.34, 0.55)), sky_str=1.7, win=0.7, lamp=5.0, spot=250, wires=1.6, sun=None, signs=0.3),
    "night":  dict(sky=((0.2, 0.13, 0.24), (0.08, 0.05, 0.12), (0.02, 0.015, 0.035)), sky_str=1.0, win=1.6, lamp=20.0, spot=1600, wires=1.6, sun=None, signs=1.0),
    "sunset": dict(sky=((1.0, 0.58, 0.42), (0.62, 0.4, 0.55), (0.22, 0.16, 0.33)), sky_str=1.8, win=0.9, lamp=8.0, spot=500, wires=2.6, sun=(1.0, 0.6, 0.38), signs=0.6),
    # the show's daytime, toned down for VR (no glaring white): pale grey-lilac overcast, soft high sun, black wire silhouettes, deep shadows (red dots added in post)
    "day":    dict(sky=((0.8, 0.78, 0.82), (0.7, 0.69, 0.75), (0.56, 0.56, 0.66)), sky_str=1.5, win=0.12, lamp=0.4, spot=0, wires=1.6, sun=(1.0, 0.95, 0.9),
                   sun_e=3.0, sun_rot=(38, 0, 125), signs=0.12),
}[VARIANT]

# ------------------------------------------------------------------ scene reset
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
col_main = bpy.data.collections.new("Main"); sc.collection.children.link(col_main)
col_wire = bpy.data.collections.new("Wires"); sc.collection.children.link(col_wire)
col_noline = bpy.data.collections.new("NoLines"); sc.collection.children.link(col_noline)


# ------------------------------------------------------------------ materials
def node_mat(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    return m, nt, out


def mat_basic(name, color, rough=0.8, metal=0.0, stain=0.0, scale=0.6, stain_col=None, emit=None, emit_str=0.0):
    m, nt, out = node_mat(name)
    bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bs.inputs["Roughness"].default_value = rough
    bs.inputs["Metallic"].default_value = metal
    if stain > 0:                                             # grime: noise-mixed darker colour, streaks down walls
        tc = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (scale, scale, scale * 0.25)
        nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 3.0; nz.inputs["Detail"].default_value = 8.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = 0.35; ramp.color_ramp.elements[1].position = 0.75
        ramp.color_ramp.elements[0].color = (*(stain_col or [c * 0.45 for c in color]), 1)
        ramp.color_ramp.elements[1].color = (*color, 1)
        nt.links.new(tc.outputs["Object"], mp.inputs["Vector"]); nt.links.new(mp.outputs["Vector"], nz.inputs["Vector"])
        nt.links.new(nz.outputs["Fac"], ramp.inputs["Fac"]); nt.links.new(ramp.outputs["Color"], bs.inputs["Base Color"])
    else:
        bs.inputs["Base Color"].default_value = (*color, 1)
    if emit:
        bs.inputs["Emission Color"].default_value = (*emit, 1); bs.inputs["Emission Strength"].default_value = emit_str
    nt.links.new(bs.outputs["BSDF"], out.inputs["Surface"])
    return m


def mat_emit(name, color, strength):
    m, nt, out = node_mat(name)
    em = nt.nodes.new("ShaderNodeEmission"); em.inputs["Color"].default_value = (*color, 1); em.inputs["Strength"].default_value = strength
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def mat_asphalt():
    m, nt, out = node_mat("asphalt")
    bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (0.35, 0.12, 0.35)
    nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 2.0; nz.inputs["Detail"].default_value = 6.0
    pud = nt.nodes.new("ShaderNodeValToRGB")                  # puddles = mirror-smooth, darker
    pud.color_ramp.elements[0].position = 0.48; pud.color_ramp.elements[1].position = 0.56
    pud.color_ramp.elements[0].color = (0.03, 0.025, 0.035, 1); pud.color_ramp.elements[1].color = (0.075, 0.065, 0.07, 1)
    rr = nt.nodes.new("ShaderNodeMapRange"); rr.inputs["From Min"].default_value = 0.48; rr.inputs["From Max"].default_value = 0.56
    rr.inputs["To Min"].default_value = 0.02; rr.inputs["To Max"].default_value = 0.28
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"]); nt.links.new(mp.outputs["Vector"], nz.inputs["Vector"])
    nt.links.new(nz.outputs["Fac"], pud.inputs["Fac"]); nt.links.new(nz.outputs["Fac"], rr.inputs["Value"])
    nt.links.new(pud.outputs["Color"], bs.inputs["Base Color"]); nt.links.new(rr.outputs["Result"], bs.inputs["Roughness"])
    nt.links.new(bs.outputs["BSDF"], out.inputs["Surface"])
    return m


def mat_chainlink():
    """procedural diamond chain-link on the fence plane (object Y/Z or X/Z), transparent between the wires."""
    m, nt, out = node_mat("chainlink")
    tc = nt.nodes.new("ShaderNodeTexCoord"); sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs["Vector"])
    def mk(op, a=None, b=None, v=None):
        n = nt.nodes.new("ShaderNodeMath"); n.operation = op
        if v is not None: n.inputs[1].default_value = v
        if a is not None: nt.links.new(a, n.inputs[0])
        if b is not None: nt.links.new(b, n.inputs[1])
        return n
    h = mk("ADD", sep.outputs["X"], sep.outputs["Y"])        # fences run along Y (or X); one of them is constant
    d1 = mk("ADD", h.outputs[0], sep.outputs["Z"]); d2 = mk("SUBTRACT", h.outputs[0], sep.outputs["Z"])
    f1 = mk("PINGPONG", d1.outputs[0], v=0.035); f2 = mk("PINGPONG", d2.outputs[0], v=0.035)
    mn = mk("MINIMUM", f1.outputs[0], f2.outputs[0])
    a = mk("LESS_THAN", mn.outputs[0], v=0.006)
    bs = nt.nodes.new("ShaderNodeBsdfPrincipled"); bs.inputs["Base Color"].default_value = (0.18, 0.18, 0.17, 1)
    bs.inputs["Metallic"].default_value = 0.6; bs.inputs["Roughness"].default_value = 0.45
    tr = nt.nodes.new("ShaderNodeBsdfTransparent"); mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(a.outputs[0], mix.inputs["Fac"]); nt.links.new(tr.outputs[0], mix.inputs[1]); nt.links.new(bs.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return m


M = {
    "asphalt": mat_asphalt(),
    "line": mat_basic("line", (0.55, 0.53, 0.5), 0.5),
    "curb": mat_basic("curb", (0.42, 0.4, 0.38), 0.7, stain=1, scale=1.5),
    "walk": mat_basic("walk", (0.3, 0.28, 0.27), 0.45, stain=1, scale=1.0),
    "conc_a": mat_basic("conc_a", (0.55, 0.52, 0.5), 0.85, stain=1, scale=0.3, stain_col=(0.22, 0.2, 0.2)),
    "conc_b": mat_basic("conc_b", (0.62, 0.58, 0.52), 0.85, stain=1, scale=0.25, stain_col=(0.3, 0.26, 0.22)),
    "conc_c": mat_basic("conc_c", (0.45, 0.43, 0.46), 0.85, stain=1, scale=0.35, stain_col=(0.18, 0.17, 0.2)),
    "tile": mat_basic("tile", (0.5, 0.36, 0.3), 0.6, stain=1, scale=0.4, stain_col=(0.25, 0.17, 0.15)),
    "roof": mat_basic("roof", (0.2, 0.2, 0.24), 0.6, stain=1, scale=0.5),
    "glass": mat_basic("glass", (0.05, 0.05, 0.07), 0.08, metal=0.3),
    "lit_warm": mat_emit("lit_warm", (1.0, 0.72, 0.45), 1.4 * P["win"]),
    "lit_cool": mat_emit("lit_cool", (0.75, 0.85, 1.0), 1.2 * P["win"]),
    "lit_pink": mat_emit("lit_pink", (1.0, 0.55, 0.75), 1.2 * P["win"]),
    "neon_pink": mat_emit("neon_pink", (1.0, 0.25, 0.6), 6.0 * P["signs"]),
    "neon_cyan": mat_emit("neon_cyan", (0.3, 0.9, 1.0), 5.0 * P["signs"]),
    "neon_white": mat_emit("neon_white", (1.0, 0.95, 0.9), 4.0 * P["signs"]),
    "frame": mat_basic("frame", (0.3, 0.3, 0.32), 0.5, metal=0.5),
    "metal": mat_basic("metal", (0.12, 0.12, 0.13), 0.5, metal=0.7),
    "rail": mat_basic("rail", (0.6, 0.6, 0.58), 0.4, metal=0.5),
    "pole": mat_basic("pole", (0.5, 0.48, 0.45), 0.8, stain=1, scale=2.0, stain_col=(0.25, 0.24, 0.23)),
    "insul": mat_basic("insul", (0.75, 0.73, 0.7), 0.3),
    "trans": mat_basic("trans", (0.38, 0.4, 0.4), 0.5, metal=0.3, stain=1, scale=3.0),
    "lamp": mat_emit("lamp", (0.92, 0.95, 1.0), P["lamp"]),
    "sodium": mat_emit("sodium", (1.0, 0.62, 0.3), P["lamp"] * 0.8),
    "yellow": mat_basic("yellow", (0.75, 0.6, 0.08), 0.6, stain=1, scale=2.0),
    "vend": mat_emit("vend", (0.85, 0.9, 1.0), 3.0),
    "red": mat_basic("red", (0.45, 0.06, 0.05), 0.5),
    "tank": mat_basic("tank", (0.55, 0.55, 0.6), 0.5, stain=1, scale=1.5),
    "chainlink": mat_chainlink(),
    "wire": mat_basic("wire", (0.02, 0.02, 0.025), 0.4),
}


# ------------------------------------------------------------------ mesh builder (one mesh per material)
class Geo:
    def __init__(self): self.v, self.f = [], []
G = {k: Geo() for k in M}


def box(mat, x0, y0, z0, x1, y1, z1):
    g = G[mat]; b = len(g.v)
    xs, ys, zs = sorted((x0, x1)), sorted((y0, y1)), sorted((z0, z1))
    for z in zs:
        for y in ys:
            for x in xs: g.v.append((x, y, z))
    q = lambda a, b_, c, d: g.f.append((b + a, b + b_, b + c, b + d))
    q(0, 2, 3, 1); q(4, 5, 7, 6); q(0, 1, 5, 4); q(2, 6, 7, 3); q(0, 4, 6, 2); q(1, 3, 7, 5)


def quad(mat, pts):
    g = G[mat]; b = len(g.v); g.v.extend(pts); g.f.append(tuple(range(b, b + len(pts))))


def cyl(mat, p0, p1, r0, r1=None, n=8):
    r1 = r0 if r1 is None else r1
    g = G[mat]; b = len(g.v)
    ax = np.subtract(p1, p0); ln = np.linalg.norm(ax); ax = ax / ln
    t = np.cross(ax, (0, 0, 1) if abs(ax[2]) < 0.9 else (1, 0, 0)); t /= np.linalg.norm(t); u = np.cross(ax, t)
    for p, r in ((p0, r0), (p1, r1)):
        for i in range(n):
            a = 2 * math.pi * i / n
            g.v.append(tuple(np.add(p, r * (math.cos(a) * t + math.sin(a) * u))))
    for i in range(n):
        j = (i + 1) % n; g.f.append((b + i, b + j, b + n + j, b + n + i))
    g.f.append(tuple(b + i for i in range(n))[::-1]); g.f.append(tuple(b + n + i for i in range(n)))


def flush_meshes():
    for k, g in G.items():
        if not g.f: continue
        me = bpy.data.meshes.new(k); me.from_pydata(g.v, [], g.f); me.validate()
        ob = bpy.data.objects.new(k, me); me.materials.append(M[k])
        (col_noline if k in ("chainlink", "line") else col_main).objects.link(ob)
        for p in me.polygons: p.use_smooth = False


# ------------------------------------------------------------------ wires (curves, grouped by thickness)
WIRES = {}
LAMPS = []                                                    # street lamp heads (x, y, z, kind) for the live sky's lamp buzz


def wire(p0, p1, sag, thick=0.012, n=18):
    lst = WIRES.setdefault(round(thick, 3), [])
    pts = []
    for i in range(n + 1):
        t = i / n
        x = p0[0] + (p1[0] - p0[0]) * t; y = p0[1] + (p1[1] - p0[1]) * t
        z = p0[2] + (p1[2] - p0[2]) * t - 4 * sag * t * (1 - t)
        pts.append((x, y, z))
    lst.append(pts)


def flush_wires():
    for th, splines in WIRES.items():
        cu = bpy.data.curves.new("wires_%s" % th, "CURVE"); cu.dimensions = "3D"
        cu.bevel_depth = th; cu.bevel_resolution = 1; cu.resolution_u = 2
        for pts in splines:
            sp = cu.splines.new("POLY"); sp.points.add(len(pts) - 1)
            for p, q in zip(sp.points, pts): p.co = (*q, 1)
        ob = bpy.data.objects.new("wires_%s" % th, cu); cu.materials.append(M["wire"]); col_wire.objects.link(ob)


# ------------------------------------------------------------------ road
box("asphalt", -4.0, -L, -0.05, 4.0, L, 0.0)
for y in np.arange(-L, L, 9.0):                               # worn dashed centre line
    if R.random() < 0.85: box("line", -0.07, y, 0.0, 0.07, y + 5.0, 0.004)
for s in (-1, 1):
    box("line", s * 3.75, -L, 0.0, s * 3.62, L, 0.004)        # edge lines
    box("curb", s * 4.0, -L, 0.0, s * 4.2, L, 0.15)
    box("walk", s * 4.2, -L, 0.0, s * 6.2, L, 0.13)
    # Japanese-style pipe guard rail on the curb, broken into runs
    y = -L
    while y < L:
        run = R.uniform(15, 60)
        if R.random() < 0.6:
            for yy in np.arange(y, y + run, 2.0):
                cyl("rail", (s * 4.1, yy, 0.13), (s * 4.1, yy, 0.85), 0.03, n=6)
            for z in (0.5, 0.8): cyl("rail", (s * 4.1, y, z), (s * 4.1, y + run, z), 0.025, n=6)
        y += run + R.uniform(4, 20)
box("asphalt", -L, -L, -0.06, L, L, -0.05)                    # ground everywhere else (under buildings)


# ------------------------------------------------------------------ buildings
def windows_grid(s, x_face, y0, y1, z0, floors, fh, wpat, lit_p):
    """windows on a facade facing the road (x = x_face, facing -s)."""
    cols = max(1, int((y1 - y0) / wpat))
    for fl in range(floors):
        zb = z0 + fl * fh + 0.95; zt = zb + fh * 0.42
        for c in range(cols):
            yc = y0 + (c + 0.5) * (y1 - y0) / cols; hw = min(0.6, (y1 - y0) / cols * 0.26)
            r = R.random()
            mat = "glass" if r > lit_p else R.choice(["lit_warm", "lit_warm", "lit_cool", "lit_pink"])
            box("frame", x_face - s * 0.01, yc - hw - 0.06, zb - 0.06, x_face - s * 0.04, yc + hw + 0.06, zt + 0.06)
            box(mat, x_face - s * 0.04, yc - hw, zb, x_face - s * 0.07, yc + hw, zt)
            if mat != "glass" and R.random() < 0.5:                 # half-drawn curtain
                box("conc_c", x_face - s * 0.075, yc - hw, zb, x_face - s * 0.08, yc - hw + R.uniform(0.2, 1.0) * hw, zt)
            if R.random() < 0.12:                             # AC unit under the window
                box("conc_c", x_face - s * 0.05, yc + hw + 0.1, zb - 0.6, x_face - s * 0.45, yc + hw + 0.9, zb - 0.05)


def apartment(s, y0, y1, xf, floors):
    fh = 2.9; depth = R.uniform(9, 14); H = floors * fh
    mat = R.choice(["conc_a", "conc_b", "conc_c", "tile"])
    xi, xo = s * xf, s * (xf + depth)
    box(mat, xi, y0, 0, xo, y1, H)
    box("roof", xi - s * 0.0, y0, H, xo, y1, H + 0.4)                       # parapet slab
    for yy in (y0, y1): box(mat, xi, yy - 0.15, H, xi + s * 0.2, yy + 0.15, H + 1.0)
    box(mat, xi, y0, H + 0.4, xi + s * 0.2, y1, H + 1.1)                    # parapet front
    balcony = R.random() < 0.65
    if balcony:
        for fl in range(1, floors):
            z = fl * fh
            box(mat, xi, y0 + 0.3, z - 0.15, xi - s * 1.1, y1 - 0.3, z)    # slab
            box("rail" if R.random() < 0.5 else mat, xi - s * 1.05, y0 + 0.3, z, xi - s * 1.1, y1 - 0.3, z + 1.05)
            for k in np.arange(y0 + 2.5, y1 - 1, 3.2):                      # dividers
                box(mat, xi, k - 0.05, z, xi - s * 1.1, k + 0.05, z + 2.4)
            if R.random() < 0.25:                                           # laundry pole
                cyl("metal", (xi - s * 0.9, y0 + 1, z + 1.9), (xi - s * 0.9, y0 + R.uniform(3, (y1 - y0) - 1), z + 1.9), 0.015, n=5)
    windows_grid(s, xi, y0 if not R.random() < 0.0 else y0, y1, 0, floors, fh, R.uniform(2.6, 3.6), 0.28)
    if R.random() < 0.35:                                                   # ground floor shop: lit front + shutter
        box(R.choice(["lit_warm", "lit_cool", "neon_white"]), xi - s * 0.08, y0 + 1, 0.2, xi - s * 0.1, y1 - 1, 2.3)
        box("metal", xi - s * 0.1, y0 + 1, 2.3, xi - s * 0.4, y1 - 1, 2.9)
    if R.random() < 0.3:                                                    # vertical sign sticking out
        yc = R.uniform(y0 + 1, y1 - 1); z0s = R.uniform(3, 6)
        box(R.choice(["neon_pink", "neon_cyan", "neon_white", "neon_pink"]), xi - s * 0.3, yc - 0.05, z0s, xi - s * 1.0, yc + 0.05, z0s + R.uniform(2.5, 5))
        box("frame", xi - s * 0.25, yc - 0.08, z0s - 0.05, xi - s * 1.05, yc + 0.08, z0s)
    if R.random() < 0.5:                                                    # outside stair tower at one end
        ye = y0 if R.random() < 0.5 else y1 - 3.0
        box(mat, xi - s * 0.0, ye, 0, xi - s * 0.0 + s * 3.0, ye + 3.0, H + 2.2)
        for fl in range(floors):
            box("rail", xi - s * 0.05, ye, fl * fh + 1.0, xi - s * 0.1, ye + 3.0, fl * fh + 2.0)
    roof_stuff(s, xi, xo, y0, y1, H + 0.4)


def roof_stuff(s, xi, xo, y0, y1, z):
    if R.random() < 0.6:
        cx = (xi + xo) / 2 + R.uniform(-2, 2); cy = R.uniform(y0 + 2, y1 - 2)
        for dx, dy in ((-0.8, -0.8), (0.8, -0.8), (-0.8, 0.8), (0.8, 0.8)):
            cyl("metal", (cx + dx, cy + dy, z), (cx + dx, cy + dy, z + 1.8), 0.05, n=5)
        cyl("tank", (cx, cy, z + 1.8), (cx, cy, z + 3.6), 1.2, n=16)
    for _ in range(R.randint(0, 3)):                                        # antennas
        ax, ay = R.uniform(min(xi, xo), max(xi, xo)), R.uniform(y0 + 1, y1 - 1); h = R.uniform(2, 6)
        cyl("metal", (ax, ay, z), (ax, ay, z + h), 0.03, n=5)
        for k in range(R.randint(2, 5)):
            zz = z + h * (0.5 + 0.1 * k); w = R.uniform(0.4, 1.2)
            cyl("metal", (ax, ay - w, zz), (ax, ay + w, zz), 0.012, n=4)
    if R.random() < 0.15:                                                   # billboard frame
        bx = xi + s * 1.0
        for yy in (y0 + 1, y1 - 1): cyl("metal", (bx, yy, z), (bx, yy, z + 5), 0.08, n=6)
        box(R.choice(["conc_c", "yellow", "red"]), bx, y0 + 0.8, z + 2.5, bx + s * 0.2, y1 - 0.8, z + 5.5)


def house(s, y0, y1, xf):
    mat = R.choice(["conc_b", "tile", "conc_a"]); H = R.choice([5.6, 6.0, 6.4]); xi, xo = s * xf, s * (xf + R.uniform(7, 10))
    box(mat, xi, y0, 0, xo, y1, H)
    # pitched roof (ridge along y)
    xm = (xi + xo) / 2; ov = 0.6
    quad("roof", [(xi - s * ov, y0 - ov, H - 0.3), (xi - s * ov, y1 + ov, H - 0.3), (xm, y1 + ov, H + 2.2), (xm, y0 - ov, H + 2.2)])
    quad("roof", [(xo + s * ov, y0 - ov, H - 0.3), (xm, y0 - ov, H + 2.2), (xm, y1 + ov, H + 2.2), (xo + s * ov, y1 + ov, H - 0.3)])
    windows_grid(s, xi, y0, y1, 0, 2, 2.8, R.uniform(2.5, 3.5), 0.35)
    box(R.choice(["conc_c", "conc_a"]), s * (xf - 0.6), y0, 0, s * (xf - 0.8), y1, R.uniform(1.4, 2.0))   # block wall


def lot(s, y0, y1, xf):
    """empty lot / parking behind a chain-link fence, taller building further back."""
    fx = s * (xf - 0.6); h = R.uniform(1.8, 3.0)
    quad("chainlink", [(fx, y0, 0), (fx, y1, 0), (fx, y1, h), (fx, y0, h)])
    for yy in np.arange(y0, y1 + 0.01, 2.5): cyl("metal", (fx, yy, 0), (fx, yy, h + 0.1), 0.035, n=6)
    cyl("metal", (fx, y0, h), (fx, y1, h), 0.025, n=5)
    if R.random() < 0.5:                                                    # caution sign on the fence
        yc = R.uniform(y0 + 1, y1 - 1)
        box("yellow", fx - s * 0.03, yc - 0.4, 1.0, fx - s * 0.05, yc + 0.4, 1.6)
    if R.random() < 0.7: apartment(s, y0 + R.uniform(0, 3), y1 - R.uniform(0, 3), xf + R.uniform(14, 26), R.randint(6, 12))


def vending(s, y, xf):
    x = s * (xf - 1.6)
    box("red" if R.random() < 0.5 else "conc_c", x, y, 0.13, x + s * 0.8, y + 1.0, 1.95)
    box("vend", x - s * 0.01, y + 0.1, 0.9, x - s * 0.02, y + 0.9, 1.8)


for s in (-1, 1):
    y = -L + R.uniform(0, 10)
    while y < L:
        w = R.uniform(8, 24); xf = R.uniform(7.0, 9.0); r = R.random()
        if r < 0.5: apartment(s, y, y + w, xf, R.randint(3, 7))
        elif r < 0.72: house(s, y, y + w * 0.7, xf)
        elif r < 0.9: lot(s, y, y + w, xf)
        else: apartment(s, y, y + w, xf + R.uniform(4, 10), R.randint(8, 14))
        if R.random() < 0.08: vending(s, y + w + 0.5, xf)
        y += w + R.uniform(0.4, 3.5)
    # second row behind (skyline depth)
    y = -L
    while y < L:
        w = R.uniform(14, 40); apartment(s, y, y + w, R.uniform(30, 60), R.randint(5, 16)); y += w + R.uniform(2, 15)


# ------------------------------------------------------------------ utility poles, street lights and wires
POLES = {-1: [], 1: []}
for s in (-1, 1):
    y = -L + (12 if s > 0 else 0)
    while y < L:
        x = s * 4.6; H = R.uniform(10.5, 12.5)
        cyl("pole", (x, y, 0), (x, y, H), 0.17, 0.12, n=10)
        arms = []
        for k, za in enumerate((H - 0.35, H - 1.3, H - 2.4)[:R.randint(2, 3)]):
            w = R.uniform(0.9, 1.3)
            box("metal", x - w, y - 0.05, za - 0.05, x + w, y + 0.05, za + 0.05)
            pts = []
            for dx in np.linspace(-w + 0.1, w - 0.1, R.randint(3, 4)):
                cyl("insul", (x + dx, y, za + 0.05), (x + dx, y, za + 0.2), 0.04, n=6); pts.append((x + dx, y, za + 0.2))
            arms.append(pts)
        if R.random() < 0.45:                                               # transformer drums
            for dy in ((-0.45,) if R.random() < 0.5 else (-0.45, 0.45)):
                cyl("trans", (x - s * 0.45, y + dy, H - 4.2), (x - s * 0.45, y + dy, H - 3.0), 0.3, n=12)
            box("metal", x - 0.6, y - 0.6, H - 4.3, x + 0.6, y + 0.6, H - 4.2)
        tele = [(x + s * 0.2, y, H - R.uniform(4.5, 6.0)) for _ in range(R.randint(1, 3))]   # telecom cable clamps
        # step bolts
        for z in np.arange(2.5, H - 1, 0.45):
            a = (z * 2.1) % (2 * math.pi); cyl("metal", (x, y, z), (x + 0.3 * math.cos(a), y + 0.3 * math.sin(a), z), 0.012, n=4)
        lamp = R.random() < 0.55
        if lamp:                                                            # street light arm over the road
            zl = R.uniform(7.0, 8.0); reach = R.uniform(1.6, 2.4)
            cyl("metal", (x, y, zl - 0.6), (x - s * reach, y, zl), 0.04, n=6)
            box("metal", x - s * reach - 0.25, y - 0.15, zl - 0.12, x - s * reach + 0.25, y + 0.15, zl + 0.04)
            kind = "lamp" if R.random() < 0.8 else "sodium"
            box(kind, x - s * reach - 0.22, y - 0.12, zl - 0.14, x - s * reach + 0.22, y + 0.12, zl - 0.11)
            LAMPS.append((round(x - s * reach, 2), round(y, 2), round(zl - 0.12, 2), kind))
            if abs(y) < 160:
                ld = bpy.data.lights.new("lamp", "SPOT"); ld.energy = P["spot"]; ld.spot_size = math.radians(120); ld.spot_blend = 0.6
                ld.color = (0.85, 0.88, 1.0); ld.shadow_soft_size = 0.3
                lo = bpy.data.objects.new("lamp", ld); lo.location = (x - s * reach, y, zl - 0.2); col_main.objects.link(lo)
        if R.random() < 0.15:                                               # yellow-black guard sleeve at the bottom
            cyl("yellow", (x, y, 0.1), (x, y, 2.0), 0.19, n=10)
        POLES[s].append(dict(x=x, y=y, H=H, arms=arms, tele=tele))
        y += R.uniform(24, 34)

for s in (-1, 1):
    PL = POLES[s]
    for a, b in zip(PL, PL[1:]):
        span = abs(b["y"] - a["y"])
        for ai, (aa, bb) in enumerate(zip(a["arms"], b["arms"])):          # power lines arm to arm
            for pa, pb in zip(aa, bb):
                wire(pa, pb, span * R.uniform(0.012, 0.022), 0.011 if ai == 0 else 0.014)
        for ta, tb in zip(a["tele"], b["tele"]):                            # fat telecom cables, saggy
            wire(ta, tb, span * R.uniform(0.02, 0.04), R.choice([0.025, 0.035, 0.045]))
            if R.random() < 0.5: wire((ta[0], ta[1], ta[2] - 0.15), (tb[0], tb[1], tb[2] - 0.2), span * R.uniform(0.025, 0.045), 0.02)
        for _ in range(R.randint(1, 4)):                                    # extra random lines between the same poles
            za, zb = R.uniform(5.5, a["H"] - 0.5), R.uniform(5.5, b["H"] - 0.5)
            wire((a["x"], a["y"], za), (b["x"], b["y"], zb), span * R.uniform(0.01, 0.05), R.choice([0.01, 0.015, 0.02]))
        for _ in range(R.randint(1, 4)):                                    # service drops into the buildings
            yb = R.uniform(a["y"], b["y"]); zb = R.uniform(3.0, 8.0)
            src = R.choice(a["arms"][-1] + a["tele"])
            wire(src, (s * R.uniform(7.0, 8.0), yb, zb), R.uniform(0.2, 0.8), R.choice([0.01, 0.014, 0.02]))

# across the road: lots of wires overhead, straight and diagonal
L1, L2 = POLES[-1], POLES[1]
for a in L1:
    near = sorted(L2, key=lambda b: abs(b["y"] - a["y"]))[:3]
    for b in near:
        if R.random() < 0.75:
            for _ in range(int(R.randint(2, 6) * P["wires"])):
                pa = R.choice(sum(a["arms"], []) + a["tele"]); pb = R.choice(sum(b["arms"], []) + b["tele"])
                d = math.dist(pa, pb)
                wire(pa, pb, d * R.uniform(0.02, 0.06), R.choice([0.01, 0.012, 0.016, 0.022, 0.03]))
# a few high cables from rooftop to rooftop across the street, very saggy
for _ in range(int(120 * P["wires"])):
    y0 = R.uniform(-L, L); y1 = y0 + R.uniform(-25, 25)
    wire((-R.uniform(8, 12), y0, R.uniform(9, 17)), (R.uniform(8, 12), y1, R.uniform(9, 17)), R.uniform(0.6, 2.5), R.choice([0.012, 0.02, 0.03]))

flush_meshes(); flush_wires()
if os.environ.get("EXPORT_WIRES"):                            # wire paths for skyclock events (black cats run along them), then quit
    import json
    near = [[[round(c, 2) for c in p] for p in pts] for th, sp in WIRES.items() for pts in sp
            if th >= 0.012 and min(math.hypot(p[0], p[1]) for p in pts) < 45]
    lamps = [l for l in LAMPS if math.hypot(l[0], l[1]) < 80]
    json.dump({"eye": EYE, "axes": "x right, y forward, z up (metres)", "wires": near, "lamps": lamps}, open(os.environ["EXPORT_WIRES"], "w"))
    print("exported", len(near), "wires", len(lamps), "lamps"); bpy.ops.wm.quit_blender()

# ------------------------------------------------------------------ world: overcast lavender dusk sky
w = bpy.data.worlds.new("sky"); sc.world = w; w.use_nodes = True; nt = w.node_tree; nt.nodes.clear()
tc = nt.nodes.new("ShaderNodeTexCoord"); sep = nt.nodes.new("ShaderNodeSeparateXYZ")
ramp = nt.nodes.new("ShaderNodeValToRGB"); bg = nt.nodes.new("ShaderNodeBackground"); out = nt.nodes.new("ShaderNodeOutputWorld")
el = ramp.color_ramp.elements
el[0].position = 0.0; el[0].color = (*P["sky"][0], 1)                     # world Generated = view direction: Z 0 = horizon
el[1].position = 0.75; el[1].color = (*P["sky"][2], 1)
e = el.new(0.2); e.color = (*P["sky"][1], 1)
nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 2.5; nz.inputs["Detail"].default_value = 6
mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 0.35
nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"]); nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
nt.links.new(tc.outputs["Generated"], nz.inputs["Vector"])
nt.links.new(ramp.outputs["Color"], mx.inputs["A"]); nt.links.new(nz.outputs["Color"], mx.inputs["B"])
nt.links.new(mx.outputs["Result"], bg.inputs["Color"]); bg.inputs["Strength"].default_value = P["sky_str"]
nt.links.new(bg.outputs[0], out.inputs["Surface"])

if P["sun"]:                                                                # low sun straight down the road
    sd = bpy.data.lights.new("sun", "SUN"); sd.energy = P.get("sun_e", 2.5); sd.color = P["sun"]; sd.angle = math.radians(3)
    so = bpy.data.objects.new("sun", sd); so.rotation_euler = [math.radians(a) for a in P.get("sun_rot", (84, 0, 180))]; sc.collection.objects.link(so)

# ------------------------------------------------------------------ render setup
sc.render.engine = "CYCLES"; use_gpu()
sc.cycles.samples = SAMPLES; sc.cycles.use_denoising = True
sc.cycles.max_bounces = 4; sc.cycles.transparent_max_bounces = 16
sc.render.resolution_x = sc.render.resolution_y = FACE; sc.render.resolution_percentage = 100
sc.view_settings.view_transform = "AgX"; sc.view_settings.look = "None"
sc.render.image_settings.file_format = "OPEN_EXR"; sc.render.image_settings.color_depth = "32"
sc.render.use_freestyle = True; sc.render.line_thickness_mode = "ABSOLUTE"; sc.render.line_thickness = max(1.0, FACE / 1400)
vl = sc.view_layers[0]; vl.use_freestyle = True
fs = vl.freestyle_settings; fs.crease_angle = math.radians(140)
ls = fs.linesets[0] if fs.linesets else fs.linesets.new("ink")
ls.select_by_collection = True; ls.collection = col_main; ls.collection_negation = "INCLUSIVE"
ls.select_silhouette = ls.select_border = ls.select_crease = True
if ls.linestyle is None: ls.linestyle = bpy.data.linestyles.new("ink")
ls.linestyle.color = (0.09, 0.05, 0.09); ls.linestyle.thickness = max(1.0, FACE / 1400)

cam_d = bpy.data.cameras.new("cam"); cam_d.angle = math.radians(90); cam_d.sensor_fit = "HORIZONTAL"; cam_d.clip_end = 2000
cam = bpy.data.objects.new("cam", cam_d); sc.collection.objects.link(cam); sc.camera = cam

FACES = {  # name: (forward, up) in world; Blender camera looks down local -Z with +Y up
    "px": ((1, 0, 0), (0, 0, 1)), "nx": ((-1, 0, 0), (0, 0, 1)),
    "py": ((0, 1, 0), (0, 0, 1)), "ny": ((0, -1, 0), (0, 0, 1)),
    "pz": ((0, 0, 1), (0, -1, 0)), "nz": ((0, 0, -1), (0, 1, 0)),
}

dist_mat, nt2, out2 = node_mat("distance")
cd = nt2.nodes.new("ShaderNodeCameraData"); em = nt2.nodes.new("ShaderNodeEmission")
nt2.links.new(cd.outputs["View Distance"], em.inputs["Strength"]); em.inputs["Color"].default_value = (1, 1, 1, 1)
nt2.links.new(em.outputs[0], out2.inputs["Surface"])


def load_exr(path):
    im = bpy.data.images.load(path); a = np.empty(im.size[0] * im.size[1] * 4, np.float32); im.pixels.foreach_get(a)
    a = a.reshape(im.size[1], im.size[0], 4)[::-1]; bpy.data.images.remove(im); return a   # top row first


from mathutils import Matrix, Vector
for name, (f, u) in FACES.items():
    if FACES_ONLY and name not in FACES_ONLY.split(","): continue
    fv, uv = Vector(f), Vector(u); rv = fv.cross(uv)
    m = Matrix((rv, uv, -fv)).transposed().to_4x4(); m.translation = (0, 0, EYE); cam.matrix_world = m
    # beauty
    vl.material_override = None; sc.render.use_freestyle = True; sc.cycles.samples = SAMPLES; sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX"
    p = os.path.join(OUT, f"{name}_rgb.exr"); sc.render.filepath = p; bpy.ops.render.render(write_still=True)
    np.save(os.path.join(OUT, f"{name}_rgb.npy"), load_exr(p)[..., :3].astype(np.float16))
    # distance (metres); sky = large
    vl.material_override = dist_mat; sc.render.use_freestyle = False; sc.cycles.samples = 1; sc.cycles.use_denoising = False
    sc.view_settings.view_transform = "Standard"
    wsave = w.node_tree.nodes["Background"].inputs["Strength"].default_value
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    sc.cycles.filter_width = 0.01
    p = os.path.join(OUT, f"{name}_dist.exr"); sc.render.filepath = p; bpy.ops.render.render(write_still=True)
    d = load_exr(p)[..., 0]; d[d <= 0] = 1e4
    np.save(os.path.join(OUT, f"{name}_dist.npy"), d.astype(np.float32))
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = wsave; sc.cycles.filter_width = 1.5
    print("face done:", name, flush=True)

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "wired_street.blend"))
print("ALL DONE", flush=True)
