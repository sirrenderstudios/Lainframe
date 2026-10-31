"""Flatten each Lain sky into ONE opaque cube for the headset (2026-10-27: lag/blur at 144 Hz; the compositor spent
2.8 ms on sky + foreground as two full layers and 0.8 ms on the wet-road layer). flat_<face>.png = fg over open sky, with
the wet road baked in at a moderate level. The clouds that used to pass between the layers are gone, so nothing changes.
    python sky_flatten.py        -> src/skies/lain_<mood>/flat_{front,back,left,right,up,down}.png"""
import os
from PIL import Image
SK = os.path.join(os.path.dirname(__file__), "..", "src", "skies"); WX = os.path.join(SK, "..", "weather")
WET_A = 0.25                                     # weather.py: 0.08 dry-gloomy ... 0.5 downpour
for mood in ("lain_day", "lain_dusk", "lain_sunset", "lain_night"):
    d = os.path.join(SK, mood)
    for f in ("front", "back", "left", "right", "up", "down"):
        base = Image.open(os.path.join(d, f + ".png")).convert("RGBA")
        fg = os.path.join(d, "fg_" + f + ".png")
        if os.path.exists(fg): base.alpha_composite(Image.open(fg).convert("RGBA"))
        wet = os.path.join(WX, "wet_" + f + ".png")
        if not os.path.exists(wet): wet += ".off"
        if f != "up" and os.path.exists(wet):
            w = Image.open(wet).convert("RGBA").resize(base.size, Image.LANCZOS)
            w.putalpha(w.getchannel("A").point(lambda v: int(v * WET_A))); base.alpha_composite(w)
        base.convert("RGB").save(os.path.join(d, "flat_" + f + ".png"), optimize=True)
    print(mood, "flattened", flush=True)
