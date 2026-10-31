"""Frame-side check of lain_player's one-picture composite: draws a talk frame
+ eye sprite + mouth sprite through GLPanel into its FBO, reads it back and saves <lain dir>/composite_test.png (RGBA, before
the overlay's see-through), plus the old stacked look (each layer at 80%) as composite_old.png for comparison.
    python3 test_lain_composite.py [<lain_player.py dir, default ~/lainframe/lain>]"""
import os, sys, ctypes, time
D = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/lainframe/lain")
sys.path.insert(0, os.path.join(os.path.dirname(D), "lib")); sys.path.insert(0, D)
import lain_player as LP
from PIL import Image


class FakeOv:
    def __getattr__(self, n): return lambda *a, **k: None


LP.GL.init(); gl = LP.GL.gl
C = LP.Clips()
body_p = os.path.join(LP.CLIPS, "talk_0_A_lips", "000.png")
spr, per_frame = LP.mouth_sprite("talk_0_A_lips", body_p, "A", {})
eye_dir = os.path.join(LP.CLIPS, "eyes", "rest"); eye_p = os.path.join(eye_dir, sorted(os.listdir(eye_dir))[len(os.listdir(eye_dir)) // 2])
print("body", body_p, "\nmouth", spr, per_frame, "\neye", eye_p)
eyes = LP.GLLayer(); mouth = LP.GLLayer(); P = LP.GLPanel(FakeOv(), 1, C.w, C.h, (eyes, mouth))
P.stage(body_p); eyes.stage(eye_p, None); mouth.stage(spr, None)
time.sleep(0.5)
t = time.time(); P.commit(); dt = (time.time() - t) * 1000
t = time.time(); P.drawn = None; P.commit(); dt2 = (time.time() - t) * 1000
print("first commit %.1f ms, recompose %.1f ms, drawn %s" % (dt, dt2, P.drawn is not None))
buf = (ctypes.c_ubyte * (C.w * C.h * 4))()
gl.x_glBindFramebuffer(0x8D40, P.fbo); gl.glReadPixels(0, 0, C.w, C.h, 0x1908, 0x1401, buf); gl.x_glBindFramebuffer(0x8D40, 0)
im = Image.frombytes("RGBA", (C.w, C.h), bytes(buf))           # FBO row 0 = canvas top (shown with flipped bounds)
im.save(os.path.join(D, "composite_test.png"))
# old look: each layer (already at 80%) stacked
def lay(p):
    w, h, data, crop = LP.decode(p); x0, y0 = crop[:2] if crop else (0, 0)
    c = Image.new("RGBA", (C.w, C.h)); c.paste(Image.frombytes("RGBA", (w, h), data), (x0, y0)); return c
old = lay(body_p); old.alpha_composite(lay(eye_p)); old.alpha_composite(lay(spr)); old.save(os.path.join(D, "composite_old.png"))
print("saved")
