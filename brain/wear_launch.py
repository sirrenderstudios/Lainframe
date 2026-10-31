"""PC side of the "worn" extra: when you put the Steam Frame on, start SteamVR on the PC (= the headset's
"SteamVR without game": it begins streaming). Reads the Frame's ~/.local/state/lainframe/worn ("<1|0> <epoch>",
written by lainframe-worn.service). Starts SteamVR only on a not-worn -> worn change, only if SteamVR isn't already
running on the PC, at most once a minute. Started hidden by `lain_brain.py run` when the worn extra is on. One copy only.
    pythonw wear_launch.py [--dry]      (--dry: log what it would do, never start SteamVR)"""
import ctypes, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, frame  # noqa: E402

LOG = config.log_file("wear_launch.log")
DRY = "--dry" in sys.argv


def log(*a):
    with open(LOG, "a", encoding="utf-8") as f: f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(map(str, a)) + "\n")


def worn():
    cfg = config.load()
    if not cfg["headset"]["host"]: return None
    try:
        v, t = frame.text(frame.run(cfg, "cat ~/.local/state/lainframe/worn", timeout=15)).split()[:2]
        return (v == "1") and abs(time.time() - int(t)) < 15      # stale file = Frame asleep/off
    except Exception:
        return None


def vr_running():
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, creationflags=frame.NW).stdout.lower()
    return "vrserver.exe" in out or "vrmonitor.exe" in out


def main():
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\LainframeWearLaunch")
    if ctypes.windll.kernel32.GetLastError() == 183: return "already running"
    log("started" + (" (dry run)" if DRY else ""))
    prev = None; last_launch = 0.0
    while True:
        w = worn()
        if w is not None:
            if w and prev is False and time.time() - last_launch > 60:
                if vr_running(): log("headset on, SteamVR already running: nothing to do")
                else:
                    log("headset on: starting SteamVR" + (" (dry run, not started)" if DRY else ""))
                    if not DRY: os.startfile("steam://rungameid/250820")
                    last_launch = time.time()
            elif w != prev: log("worn =", w)
            prev = w
        time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
