"""Bake Lain's clip library for the headset player (so the headset never decodes PNGs while she plays):
every PNG -> Wired recolour + alpha (same maths as lain_player.wired()) -> cropped to its visible pixels -> raw RGBA,
zlib level 1, in a .rgbz file next to the same relative path under clips_baked/. The headset then only inflates
(~3 ms, no Pillow) and uploads a small texture; the eye/mouth layers shrink from 820x832 to small patches.
.rgbz = b"RGBZ" + <6 x uint16: x0, y0, w, h, full_w, full_h> + zlib(RGBA rows, top-down).
    python bake_rgbz.py --src <clips_grok> --out <clips_baked> [--alpha 0.8] [--jobs N]
Skips files already up to date (resumable). Prints "progress <done> <total>" lines for the setup wizard."""
import argparse, os, struct, sys, zlib
from multiprocessing import Pool, freeze_support
from PIL import Image, ImageOps

WIRED = {"alpha": 0.8, "black": (6, 12, 34), "mid": (38, 104, 168), "white": (176, 236, 255)}   # = lain_player.WIRED
PAD = 2
SRC = OUT = None


def init(src, out, alpha):
    global SRC, OUT
    SRC, OUT = src, out; WIRED["alpha"] = alpha


def bake(rel):
    src = os.path.join(SRC, rel); dst = os.path.join(OUT, rel[:-4] + ".rgbz")
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src): return 0
    im = Image.open(src).convert("RGBA"); W, H = im.size
    a = im.getchannel("A").point(lambda v: int(v * WIRED["alpha"]))
    out = ImageOps.colorize(im.convert("L"), WIRED["black"], WIRED["white"], mid=WIRED["mid"]); out.putalpha(a)
    bb = a.getbbox() or (0, 0, 1, 1)
    x0, y0 = max(0, bb[0] - PAD), max(0, bb[1] - PAD); x1, y1 = min(W, bb[2] + PAD), min(H, bb[3] + PAD)
    c = out.crop((x0, y0, x1, y1))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst + ".tmp", "wb") as f:
        f.write(b"RGBZ" + struct.pack("<6H", x0, y0, c.width, c.height, W, H) + zlib.compress(c.tobytes(), 1))
    os.replace(dst + ".tmp", dst)
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="clips_grok folder (PNG library)")
    ap.add_argument("--out", required=True, help="clips_baked folder to write")
    ap.add_argument("--alpha", type=float, default=WIRED["alpha"])
    ap.add_argument("--jobs", type=int, default=max(2, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    src, out = os.path.abspath(a.src), os.path.abspath(a.out)
    if not os.path.isdir(src): sys.exit("no such folder: " + src)
    rels = [os.path.relpath(os.path.join(d, f), src) for d, _, fs in os.walk(src) for f in fs if f.lower().endswith(".png")]
    n = done = 0; step = max(1, len(rels) // 200)
    print("progress 0 %d" % len(rels), flush=True)
    with Pool(a.jobs, initializer=init, initargs=(src, out, a.alpha)) as p:
        for r in p.imap_unordered(bake, rels, chunksize=32):
            n += r; done += 1
            if done % step == 0 or done == len(rels): print("progress %d %d" % (done, len(rels)), flush=True)
    print(f"baked {n} of {len(rels)} images -> {out}", flush=True)


if __name__ == "__main__":
    freeze_support()
    main()
