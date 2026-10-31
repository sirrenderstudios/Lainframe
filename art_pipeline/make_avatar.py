"""Make your own Lainframe avatar from still pictures: writes a character pack in the same format as Lain's clip library
(clips_grok/: one folder per clip + clips.json), which the player, the baker and the installer use unchanged.

    python art_pipeline/make_avatar.py --idle me.png [--listen ear.png] [--think focus.png] [--talk talk.png]
                                       [--sleep zzz.png] [--blink blink.png] --out my_avatar/clips_grok

Pictures: transparent PNGs, all the same size (Lain's are 820 x 832), the character standing on the bottom edge (the
bottom of the picture sits on the top edge of the Steam menu; anything below is hidden behind it). Only --idle is
required; any state you don't give uses the idle picture. --blink (eyes closed) is shown for a moment now and then.

Then: put the folder where Lain's art lives (Lain Brain settings: art.local_dir -> <art>/clips_grok, keep a copy of Lain's)
and run `LainBrain.bat deploy`. It bakes the pack and installs it. See docs/MAKE_YOUR_OWN_AVATAR.md for animated clips,
lip sync and live eyes, and for giving your avatar its own personality."""
import argparse, json, os, shutil
from PIL import Image

# every clip the player can ask for: (state, loop, family) -- same names as Lain's library
CLIPS = {
    "rest_a": ("idle", False), "rest_b": ("idle", False), "rest_c": ("idle", False), "still_a": ("idle", False),
    "look_around_l": ("idle", False), "look_around_r": ("idle", False), "peek_l": ("idle", False), "peek_r": ("idle", False),
    "sigh": ("idle", False), "doze_short": ("idle", False), "enter_listen": ("idle", False), "listen_loop": ("listen", True),
    "exit_listen": ("idle", False), "think_open": ("think", True), "enter_think_A": ("idle", False),
    "listen_to_think_A": ("listen", False), "think_loop_A": ("think", True), "answer_A": ("think", False),
    "talk_0_A": ("talk", True), "talk_1_A": ("talk", True), "wires_out_A": ("idle", False), "enter_sleep": ("idle", False),
    "sleep_loop": ("sleep", True), "wake": ("sleep", False), "connect": ("idle", False), "disconnect": ("idle", False),
    "notice_you": ("idle", False), "rest_night_a": ("idle", False), "rest_night_b": ("idle", False),
    "listen_nod": ("listen", False), "listen_blink": ("listen", False), "listen_tilt": ("listen", False),
    "shy_glance": ("idle", False), "lean_l_in": ("idle", False), "lean_l_loop": ("idle", True), "lean_l_out": ("idle", False),
    "listen_lean_l_in": ("listen", False), "listen_lean_l_loop": ("listen", True), "listen_lean_l_out": ("listen", False),
    "lean_r_in": ("idle", False), "lean_r_loop": ("idle", True), "lean_r_out": ("idle", False),
    "listen_lean_r_in": ("listen", False), "listen_lean_r_loop": ("listen", True), "listen_lean_r_out": ("listen", False),
}
# which picture each clip shows (the "wired" clips are the thinking look; sleep clips the sleeping one)
PICK = {"think_open": "think", "enter_think_A": "think", "listen_to_think_A": "think", "think_loop_A": "think",
        "answer_A": "talk", "talk_0_A": "talk", "talk_1_A": "talk", "wires_out_A": "think", "enter_sleep": "sleep",
        "sleep_loop": "sleep", "wake": "sleep", "doze_short": "sleep"}
BLINKS = {"rest_a", "rest_b", "rest_c", "still_a", "listen_loop", "listen_blink", "sigh"}   # these get a short blink in the middle


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--idle", required=True)
    for k in ("listen", "think", "talk", "sleep", "blink"): ap.add_argument("--" + k)
    ap.add_argument("--seconds", type=float, default=4.0, help="how long each clip lasts (default 4)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pics = {k: getattr(a, k) for k in ("idle", "listen", "think", "talk", "sleep", "blink") if getattr(a, k)}
    size = None
    for k, p in pics.items():
        im = Image.open(p)
        if im.mode != "RGBA": raise SystemExit("%s: needs a transparent PNG (RGBA), got %s" % (p, im.mode))
        if size and im.size != size: raise SystemExit("%s is %dx%d; all pictures must be the same size (%dx%d)" % ((p,) + im.size + size))
        size = im.size
    if os.path.exists(os.path.join(a.out, "clips.json")): shutil.move(a.out, a.out.rstrip("/\\") + ".old")
    os.makedirs(a.out, exist_ok=True)
    fps = 30; ticks = max(1, int(a.seconds * fps)); meta = {}
    for name, (state, loop) in CLIPS.items():
        d = os.path.join(a.out, name); os.makedirs(d, exist_ok=True)
        src = pics.get(PICK.get(name, state if state in ("listen", "talk", "sleep") else "idle")) or pics["idle"]
        if name in BLINKS and "blink" in pics:                   # open ... blink (0.15 s) ... open
            frames = [(src, ticks // 2), (pics["blink"], 5), (src, max(1, ticks - ticks // 2 - 5))]
        else: frames = [(src, ticks)]
        for i, (p, _) in enumerate(frames): shutil.copyfile(p, os.path.join(d, "%03d.png" % i))
        meta[name] = dict(state=state, frames=len(frames), loop=loop, fps=fps, w=size[0], h=size[1],
                          holds=[h for _, h in frames], family="A" if name.endswith("_A") else None)
    json.dump(meta, open(os.path.join(a.out, "clips.json"), "w"), indent=1)
    print("avatar pack: %d clips, %dx%d, pictures: %s -> %s" % (len(meta), size[0], size[1], ", ".join(sorted(pics)), a.out))


if __name__ == "__main__":
    main()
