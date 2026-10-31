#!/usr/bin/env python3
"""Lainframe worn sensor (opt-in extra, lainframe-worn.service).
Writes ~/.local/state/lainframe/worn: "<1|0> <epoch>" every second, 1 = the headset is on a head (OpenVR activity level
UserInteraction). The PC (brain/wear_launch.py) reads it to start SteamVR when the headset is put on.
Optional brightness switching, ~/.config/lainframe/worn.json:
  {"brightness": false, "worn_level": "max", "off_level": 1, "backlight": ""}
  brightness: true -> taken off = backlight to off_level, put on = worn_level ("max" or a number). Only on a change, so a
  brightness set by hand while wearing it stays. backlight: a /sys/class/backlight/<name> folder (empty = auto-detect).
  When the service stops while the headset is off, the worn level is put back.
Log: stdout (journalctl --user -u lainframe-worn)."""
import glob, json, os, signal, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))                       # ~/lainframe
sys.path.insert(0, os.path.join(ROOT, "lib"))
import openvr  # noqa: E402

CONF = os.path.expanduser("~/.config/lainframe/worn.json")
STATE = os.path.expanduser("~/.local/state/lainframe")
OUT = os.path.join(STATE, "worn")
os.makedirs(STATE, exist_ok=True)


def say(*a): print("wornwatch:", *a, flush=True)


def config():
    c = {"brightness": False, "worn_level": "max", "off_level": 1, "backlight": ""}
    try: c.update(json.load(open(CONF)))
    except (OSError, ValueError): pass
    return c


def backlight(c):
    if c.get("backlight"): return c["backlight"]
    cands = sorted(d for d in glob.glob("/sys/class/backlight/*") if os.path.exists(os.path.join(d, "max_brightness")))
    return cands[0] if cands else None


C = config(); BL = backlight(C) if C["brightness"] else None
if C["brightness"]: say("brightness switching on,", BL or "no backlight found (switching off)")


def level(v):
    hi = int(open(os.path.join(BL, "max_brightness")).read())
    if v == "max": return hi
    return max(0, min(hi, int(v)))


def bright(worn):
    if not BL: return
    try:
        v = level(C["worn_level"] if worn else C["off_level"])
        with open(os.path.join(BL, "brightness"), "w") as f: f.write(str(v))
        say("brightness ->", v)
    except Exception as e: say("brightness", repr(e))


last = None


def put(v):
    global last
    if v != last:
        if last is not None or v == 1: bright(v)            # never dim on the first reading alone (startup before SteamVR)
        last = v
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f: f.write("%d %d\n" % (v, time.time()))
    os.replace(tmp, OUT)


def on_term(*_):
    if last == 0: bright(1)                                 # stopping (uninstall / disable): don't leave the screen dimmed
    sys.exit(0)


signal.signal(signal.SIGTERM, on_term)


def vrserver_up():
    """openvr.init as a background app fails at boot before SteamVR runs (InitError_Init_NoServerForBackgroundApp)."""
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                if os.path.basename(os.readlink(f"/proc/{d}/exe")) == "vrserver": return True
            except OSError: pass
    return False


while True:
    try:
        while not vrserver_up():
            put(0); time.sleep(5)
        openvr.init(openvr.VRApplication_Background); vs = openvr.VRSystem(); say("connected to SteamVR")
        while True:
            put(1 if vs.getTrackedDeviceActivityLevel(0) == openvr.k_EDeviceActivityLevel_UserInteraction else 0)
            time.sleep(1)
    except Exception as e:
        say(repr(e))
        try: openvr.shutdown()
        except Exception: pass
        put(0); time.sleep(5)
