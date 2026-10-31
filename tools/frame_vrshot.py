# From saphid/frame-control (MIT License) - ui/frame_vrshot.py
"""Runs ON the Steam Frame (piped over SSH as `python3 -`); captures the headset view.

Asks SteamVR for a stereo screenshot through OpenVR's IVRScreenshots API (ctypes,
so nothing to build or install). The result is a side-by-side PNG of both eyes
with everything composited: the room, floating panels, dashboard and
controllers. Verified 2026-09-25 (SteamOS 0.3.0, SteamVR 2.17.10): 1920x1080,
960x1080 per eye.

Prints one JSON line: {"path": ...} or {"error": ...}. The caller copies the PNG
back and deletes it.
"""
import ctypes as C
import json
import os
import sys
import time

LIB = "/opt/steamvr/bin/linuxarm64/libopenvr_api.so"
OUT_DIR = "/tmp/frame-vrcap"
APP_OVERLAY = 2  # doesn't take focus from whatever is running
SCREENSHOT_STEREO = 2
ERRORS = {1: "request failed", 100: "incompatible version", 101: "not found",
          102: "buffer too small", 108: "screenshot already in progress"}
Err, Handle = C.c_int, C.c_uint32


class ScreenshotsFnTable(C.Structure):
    # openvr_capi.h, VR_IVRScreenshots_FnTable (IVRScreenshots_001).
    _fields_ = [
        ("RequestScreenshot", C.CFUNCTYPE(Err, C.POINTER(Handle), C.c_int, C.c_char_p, C.c_char_p)),
        ("HookScreenshot", C.CFUNCTYPE(Err, C.POINTER(C.c_int), C.c_int)),
        ("GetScreenshotPropertyType", C.CFUNCTYPE(C.c_int, Handle, C.POINTER(Err))),
        ("GetScreenshotPropertyFilename", C.CFUNCTYPE(C.c_uint32, Handle, C.c_int, C.c_char_p,
                                                      C.c_uint32, C.POINTER(Err))),
        ("UpdateScreenshotProgress", C.CFUNCTYPE(Err, Handle, C.c_float)),
        ("TakeStereoScreenshot", C.CFUNCTYPE(Err, C.POINTER(Handle), C.c_char_p, C.c_char_p)),
        ("SubmitScreenshot", C.CFUNCTYPE(Err, Handle, C.c_int, C.c_char_p, C.c_char_p)),
    ]


def done(**result):
    print(json.dumps(result))
    sys.exit(0 if "path" in result else 1)


def settled(path, wait=0.1):
    """True once the file exists and its size has stopped changing."""
    try:
        size = os.path.getsize(path)
        time.sleep(wait)
        return size > 0 and size == os.path.getsize(path)
    except OSError:
        return False


def capture(vr):
    err = Err(0)
    ptr = vr.VR_GetGenericInterface(b"FnTable:IVRScreenshots_001", C.byref(err))
    if err.value or not ptr:
        done(error=f"SteamVR screenshots unavailable ({err.value})")
    shots = C.cast(ptr, C.POINTER(ScreenshotsFnTable)).contents

    os.makedirs(OUT_DIR, mode=0o700, exist_ok=True)
    for name in os.listdir(OUT_DIR):  # leftovers from interrupted captures
        p = os.path.join(OUT_DIR, name)
        try:
            # Older than the server's 15 s `timeout`, so no capture still owns it.
            if time.time() - os.path.getmtime(p) > 20:
                os.remove(p)
        except OSError:
            pass
    base = os.path.join(OUT_DIR, f"shot-{os.getpid()}")
    handle = Handle(0)
    rc = shots.RequestScreenshot(C.byref(handle), SCREENSHOT_STEREO,
                                 (base + "-preview").encode(), (base + "-vr").encode())
    if rc:
        done(error=f"SteamVR screenshot: {ERRORS.get(rc, rc)}")
    # The compositor appends .png. The preview (left eye only) is written last.
    stereo, preview = base + "-vr.png", base + "-preview.png"
    deadline = time.time() + 8
    while time.time() < deadline:
        if os.path.exists(preview) and settled(stereo):
            os.remove(preview)
            return stereo
        time.sleep(0.05)
    for p in (stereo, preview):
        if os.path.exists(p):
            os.remove(p)
    done(error="SteamVR didn't write the screenshot in time")


def main():
    vr = C.CDLL(LIB)
    vr.VR_InitInternal2.restype = C.c_uint32
    vr.VR_InitInternal2.argtypes = [C.POINTER(Err), C.c_int, C.c_char_p]
    vr.VR_GetGenericInterface.restype = C.c_void_p
    vr.VR_GetGenericInterface.argtypes = [C.c_char_p, C.POINTER(Err)]
    err = Err(0)
    vr.VR_InitInternal2(C.byref(err), APP_OVERLAY, None)
    if err.value:
        done(error=f"Can't reach SteamVR (init error {err.value}). Is SteamVR running?")
    try:
        done(path=capture(vr))
    finally:
        vr.VR_ShutdownInternal()


main()
