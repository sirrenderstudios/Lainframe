"""Runs ON the Frame: which dashboard panels are visible right now, and how big each is (ray hits from the head).
Used to find the overlay keys of the different Steam menus Lain rides on. Copy it to the Frame, then there:
    python3 probe_panels.py [extra overlay keys...]"""
import os, sys, math
sys.path.insert(0, os.path.expanduser("~/lainframe/lib"))
import openvr
KEYS = ["valve.steam.gamepadui.main", "valve.steam.gamepadui.bar", "valve.steam.gamepadui.floatingfooter", "system.systemui",
        "system.vrwebhelper.settings", "system.vrwebhelper.controllerbinding", "system.vrdashboard", "valve.steam.bigpicture",
        "valve.steam.desktop", "valve.steam.gamepadui.fallback", "valve.steam.gamepadui.keyboard", "valve.steam.gamepadui.notifications",
        "valve.steam.browserview_MainBrowser_2", "valve.steam.gamepadui.appoverlay.438100.438100", "system.keyboard",
        "valve.steam.gamepadui.frame.menu.73360005", "valve.steam.gamepadui.frame.menu.99290005", "valve.steam.gamepadui.frame.menu.73360006",
        "valve.steam.gamepadui.frame.menu.2240005", "valve.steam.gamepadui.volumelevel", "system.toast", "steam.overlay.250820"]
KEYS += sys.argv[1:]
openvr.init(openvr.VRApplication_Overlay); ov = openvr.VROverlay(); sv = openvr.VRSystem()
poses = (openvr.TrackedDevicePose_t * 1)(); sv.getDeviceToAbsoluteTrackingPose(openvr.TrackingUniverseStanding, 0, poses)
m = poses[0].mDeviceToAbsoluteTracking.m; hp = [m[r][3] for r in range(3)]; yaw0 = math.atan2(m[0][2], m[2][2])
for k in KEYS:
    try: h = ov.findOverlay(k)
    except openvr.OpenVRError: continue
    vis = ov.isOverlayVisible(h); n = 0; ys = []
    for yw in range(-100, 101, 5):
        for pt in range(-60, 41, 5):
            a, b = math.radians(yw) + yaw0, math.radians(pt); d = (-math.sin(a) * math.cos(b), math.sin(b), -math.cos(a) * math.cos(b))
            q = openvr.VROverlayIntersectionParams_t()
            for i in range(3): q.vSource.v[i] = hp[i]; q.vDirection.v[i] = d[i]
            q.eOrigin = openvr.TrackingUniverseStanding
            ok, r = ov.computeOverlayIntersection(h, q)
            if ok: n += 1; ys.append(r.vPoint.v[1])
    try: w = ov.getOverlayWidthInMeters(h)
    except Exception: w = None
    print("%-50s visible=%d hits=%3d width=%s top_y=%s" % (k, vis, n, w, round(max(ys), 2) if ys else None))
openvr.shutdown()
