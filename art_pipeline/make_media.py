"""README media from the art (no headset needed): banner, Lain-with-wires still, sky stills, and an animated GIF of Lain
connecting to the Wired, all in her in-headset look (Wired-blue, 80% see-through over the sky).
    python art_pipeline/make_media.py --clips <clips_grok> --skies <skies> --out docs/media"""
import argparse, os
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

WIRED = {"alpha": 0.8, "black": (6, 12, 34), "mid": (38, 104, 168), "white": (176, 236, 255)}   # = lain_player / bake_rgbz


def wired(im):
    im = im.convert("RGBA"); a = im.getchannel("A").point(lambda v: int(v * WIRED["alpha"]))
    out = ImageOps.colorize(im.convert("L"), WIRED["black"], WIRED["white"], mid=WIRED["mid"]); out.putalpha(a); return out


def sky(skies, mood, face="front", size=None):
    p = os.path.join(skies, mood, "flat_%s.png" % face)
    im = Image.open(p if os.path.exists(p) else os.path.join(skies, mood, face + ".png")).convert("RGB")
    return im.resize(size, Image.LANCZOS) if size else im


def lain_over(bg, frame, scale, cx, bottom):
    l = wired(frame); l = l.resize((int(l.width * scale), int(l.height * scale)), Image.LANCZOS)
    out = bg.convert("RGBA"); out.alpha_composite(l, (int(cx - l.width / 2), int(bottom - l.height))); return out


def font(size, bold=True):
    for f in (("bahnschrift.ttf",) if bold else ()) + ("consolab.ttf", "consola.ttf", "DejaVuSans-Bold.ttf"):
        try: return ImageFont.truetype(f, size)
        except OSError: pass
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--clips", required=True); ap.add_argument("--skies", required=True)
    ap.add_argument("--out", required=True); a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    C = lambda clip, i: Image.open(os.path.join(a.clips, clip, "%03d.png" % i))
    # sky stills (crop the upper-middle of the front face: the street, the wires, the sky)
    for mood, name in (("lain_night", "wired_night"), ("lain_dusk", "wired_dusk"), ("lain_sunset", "wired_sunset")):
        s = sky(a.skies, mood); w, h = s.size
        s.crop((0, int(h * 0.12), w, int(h * 0.12) + int(w * 9 / 16))).resize((1280, 720), Image.LANCZOS).save(os.path.join(a.out, name + ".png"))
    # Lain still, wires clamped, over the night street
    bg = sky(a.skies, "lain_night", size=(1600, 1600)).crop((160, 260, 1440, 980))          # 1280 x 720
    st = lain_over(bg, C("think_loop_A", 200), 0.86, 640, 735)
    st.convert("RGB").save(os.path.join(a.out, "lain_wires.png"))
    # banner: dusk street, Lain on the right, title on the left
    bg = sky(a.skies, "lain_dusk", size=(2000, 2000)).crop((0, 520, 2000, 1170)).resize((1600, 520), Image.LANCZOS)
    bg = Image.blend(bg, Image.new("RGB", bg.size, (12, 6, 22)), 0.35)
    ban = lain_over(bg, C("rest_a", 0), 0.62, 1330, 545)
    d = ImageDraw.Draw(ban); t = "LAINFRAME"; f = font(132)
    for dx, dy, col in ((4, 4, (0, 0, 0, 160)), (0, 0, (176, 236, 255, 255))):
        d.text((90 + dx, 150 + dy), t, font=f, fill=col)
    d.text((96, 310), "Lain Iwakura in your Steam Frame.  The Wired, live around you.", font=font(30, False), fill=(214, 222, 240, 255))
    d.text((96, 356), "present day.  present time.", font=font(26, False), fill=(150, 170, 210, 255))
    ban.convert("RGB").save(os.path.join(a.out, "banner.png"))
    # GIF: wires come out and clamp, she closes her eyes and works (enter_think_A then think_loop_A), 12 fps
    bg = sky(a.skies, "lain_night", size=(1000, 1000)).crop((100, 170, 900, 620)).convert("RGBA")   # 800 x 450
    frames = []
    for clip, rng in (("enter_think_A", range(0, 120, 3)), ("think_loop_A", range(0, 96, 3))):
        for i in rng:
            f = lain_over(bg, C(clip, i), 0.54, 400, 455).convert("RGB")
            frames.append(f.resize((640, 360), Image.LANCZOS).quantize(colors=160, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    frames[0].save(os.path.join(a.out, "lain_wired.gif"), save_all=True, append_images=frames[1:], duration=83, loop=0, optimize=True)
    for f in sorted(os.listdir(a.out)): print("%-20s %6.0f KB" % (f, os.path.getsize(os.path.join(a.out, f)) / 1024))


if __name__ == "__main__":
    main()
