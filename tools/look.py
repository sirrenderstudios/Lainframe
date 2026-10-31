r"""See what the headset wearer sees: grab the headset view and save it.
    python tools\look.py          -> prints the path of a left-eye PNG under %LOCALAPPDATA%\Lainframe\captures
Uses OpenVR's screenshot API on the Frame (frame_vrshot.py, piped over ssh), so menus, Lain and the game are all in it.
Needs SteamVR running on the headset."""
import json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brain"))
import config, frame  # noqa: E402
from PIL import Image  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    cfg = config.load()
    src = open(os.path.join(HERE, "frame_vrshot.py"), encoding="utf-8").read()
    r = frame.run(cfg, "timeout 20 python3 -", timeout=45, input=src)
    try:
        remote = json.loads(frame.text(r).strip().splitlines()[-1])["path"]
    except Exception:
        sys.exit("could not capture the headset view: " + (frame.text(r) + frame.err(r))[-400:])
    out = os.path.join(config.DATA_DIR, "captures"); os.makedirs(out, exist_ok=True)
    full = os.path.join(out, time.strftime("look_%Y%m%d_%H%M%S.png"))
    frame.scp_from(cfg, remote, full, timeout=60)
    frame.run(cfg, "rm -f " + frame.shq(remote), timeout=20)
    im = Image.open(full)
    left = full.replace(".png", "_eye.png")
    im.crop((0, 0, im.width // 2, im.height)).save(left)       # one eye = what they see
    print(left)


if __name__ == "__main__":
    main()
