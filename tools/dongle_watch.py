r"""Steam Link wireless adapter watchdog (optional, not part of setup). The adapter sometimes fails to start
("Dongle VR Mode Initialize Failure" in Steam's logs\remote_connections.txt) and Steam then times out connecting the
Frame through it until it is replugged. This follows that log and, when the adapter fails, restarts the USB device
(pnputil /restart-device = a software replug). pnputil needs admin: run it from an elevated prompt or as an elevated
logon task in Task Scheduler.
Triggers: an Initialize Failure line, or 3 "Connect timeout event" lines within 4 min with no "Connect event" since.
At most one restart per 3 min and 6 per hour. Log: %LOCALAPPDATA%\Lainframe\logs\dongle_watch.log
    python tools\dongle_watch.py [--device "USB\VID_28DE&PID_2432\<serial>"]   (default: the first connected adapter found)"""
import os, re, subprocess, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brain"))
import config  # noqa: E402
from pcgame_watch import steam_dir  # noqa: E402

LOG_IN = os.path.join(steam_dir(), "logs", "remote_connections.txt")
OUT = config.log_file("dongle_watch.log")
ADAPTER = re.compile(r"USB\\VID_28DE&PID_2432\\\S+", re.I)          # Valve's Steam Link wireless adapter
NW = 0x08000000


def find_device():
    if "--device" in sys.argv: return sys.argv[sys.argv.index("--device") + 1]
    out = subprocess.run(["pnputil", "/enum-devices", "/connected"], capture_output=True, text=True, creationflags=NW).stdout
    m = ADAPTER.search(out)
    return m.group(0) if m else None


def log(*a):
    with open(OUT, "a", encoding="utf-8") as f: f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(map(str, a)) + "\n")


def restart(why):
    dev = find_device()
    if not dev: log("adapter not working (%s) but no adapter is connected" % why); return
    log("adapter not working (%s): restarting %s" % (why, dev))
    r = subprocess.run(["pnputil", "/restart-device", dev], capture_output=True, text=True, creationflags=NW)
    log("pnputil:", " ".join((r.stdout + r.stderr).split())[-200:])


def main():
    log("watching", LOG_IN)
    pos = os.path.getsize(LOG_IN) if os.path.exists(LOG_IN) else 0
    timeouts = []; last_fix = 0.0; fixes = []
    while True:
        time.sleep(5)
        try:
            size = os.path.getsize(LOG_IN)
            if size < pos: pos = 0                                       # Steam rotated the log
            if size == pos: continue
            with open(LOG_IN, "rb") as f: f.seek(pos); data = f.read(size - pos).decode("utf-8", "replace")
            pos = size
        except OSError: continue
        now = time.time(); why = None
        for ln in data.splitlines():
            if "Dongle VR Mode Initialize Failure" in ln: why = "init failure"
            elif re.search(r"\] Connect timeout event", ln): timeouts.append(now)
            elif re.search(r"\] Connect event", ln) or "Dongle VR Mode Initialize Ok" in ln: timeouts = []
        timeouts = [t for t in timeouts if now - t < 240]
        if why is None and len(timeouts) >= 3: why = "%d connect timeouts" % len(timeouts)
        fixes = [t for t in fixes if now - t < 3600]
        if why and now - last_fix > 180 and len(fixes) < 6:
            restart(why); last_fix = now; fixes.append(now); timeouts = []


if __name__ == "__main__":
    try: main()
    except Exception as e: log("crashed:", repr(e)); raise
