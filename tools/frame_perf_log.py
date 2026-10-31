"""Runs ON the Frame (refresh-rate check + battery drain test). Every 30 s, one CSV row in
~/.local/state/lainframe/perf_log.csv: time, worn, streaming, refresh Hz, compositor GPU/CPU ms (average over the last 30 s of
frames), dropped + reprojected frames, battery %, battery watts, status, battery temp. Stops after --minutes (default 90).
    nohup python3 ~/frame_perf_log.py [--minutes 90] &        summary on the PC: python tools\\frame_perf_log.py --report"""
import ctypes, glob, os, sys, time
OUT = os.path.expanduser("~/.local/state/lainframe/perf_log.csv")
BAT = (glob.glob("/sys/class/power_supply/max1720x_bat*") or glob.glob("/sys/class/power_supply/*bat*") or [""])[0]


def rd(p, d=""):
    try: return open(p).read().strip()
    except OSError: return d


def battery():
    cap = rd(BAT + "/capacity"); st = rd(BAT + "/status")
    try: w = int(rd(BAT + "/current_now")) * int(rd(BAT + "/voltage_now")) / 1e12
    except ValueError: w = 0.0
    try: t = int(rd(BAT + "/temp")) / 10
    except ValueError: t = 0.0
    return cap, round(w, 2), st, t


def streaming():
    for p in glob.glob("/proc/[0-9]*/exe"):
        try:
            if "/vrlink/" in os.readlink(p): return 1
        except OSError: pass
    return 0


def report():
    """PC side: fetch the CSV and summarise."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brain"))
    import config, frame
    txt = frame.text(frame.run(config.load(), "cat ~/.local/state/lainframe/perf_log.csv", timeout=30))
    rows = [r.split(",") for r in txt.strip().splitlines()[1:]]
    if not rows: print("no data"); return
    print("time      worn str  Hz   gpu_ms cpu_ms drop repr  bat%  watts  temp")
    for r in rows: print("%-9s %-4s %-4s %-4s %-6s %-6s %-4s %-5s %-5s %-6s %s" % (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[11]))
    worn = [r for r in rows if r[1] == "1" and r[10] == "Discharging"]
    if len(worn) >= 2:
        t0, t1 = worn[0], worn[-1]; mins = (float(t1[12]) - float(t0[12])) / 60
        drop = int(t0[8]) - int(t1[8]); avgw = sum(float(r[9]) for r in worn) / len(worn)
        print(f"\nworn + on battery: {mins:.0f} min, {drop}% used -> {drop / mins * 60 if mins else 0:.0f}%/hour, "
              f"avg {-avgw:.1f} W, full battery ~{100 / (drop / mins) / 60 if drop else 0:.1f} h")


def main(minutes):
    sys.path.insert(0, os.path.expanduser("~/lainframe/lib"))
    import openvr
    while True:
        try: openvr.init(openvr.VRApplication_Background); break
        except openvr.OpenVRError: time.sleep(5)
    comp = openvr.VRCompositor(); sysvr = openvr.VRSystem()
    os.makedirs(os.path.dirname(OUT), exist_ok=True); new = not os.path.exists(OUT)
    f = open(OUT, "a")
    if new: f.write("time,worn,streaming,hz,gpu_ms,cpu_ms,dropped,reprojected,bat,watts,status,temp_c,epoch\n")
    end = time.time() + minutes * 60
    while time.time() < end:
        t0 = time.time(); gpu = []; cpu = []; drop = 0; rep = 0
        while time.time() - t0 < 30:
            ft = openvr.Compositor_FrameTiming(); ft.m_nSize = ctypes.sizeof(openvr.Compositor_FrameTiming)
            try:
                if comp.function_table.getFrameTiming(ctypes.byref(ft), 0):              # pyopenvr's wrapper never sets m_nSize
                    gpu.append(ft.m_flTotalRenderGpuMs); cpu.append(ft.m_flCompositorRenderCpuMs)
                    drop += ft.m_nNumDroppedFrames > 0; rep += bool(ft.m_nReprojectionFlags & 0x14)
            except Exception: pass
            time.sleep(0.5)
        try: hz = round(sysvr.getFloatTrackedDeviceProperty(0, openvr.Prop_DisplayFrequency_Float))
        except Exception: hz = 0
        worn = rd(os.path.expanduser("~/.local/state/lainframe/worn"), "?").split(" ")[0]
        cap, w, st, temp = battery()
        avg = lambda a: round(sum(a) / len(a), 2) if a else 0
        f.write(f"{time.strftime('%H:%M:%S')},{worn},{streaming()},{hz},{avg(gpu)},{avg(cpu)},{drop},{rep},{cap},{w},{st},{temp},{int(time.time())}\n"); f.flush()
    openvr.shutdown()


if __name__ == "__main__":
    if "--report" in sys.argv: report()
    else: main(float(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 90)
