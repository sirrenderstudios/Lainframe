"""Tells the Frame whether a VR game is running on the PC, so the headset's live sky hides during games.
Reads SteamVR's own log (Steam\\logs\\vrserver.txt) for "(VRApplication_Scene)" connects, keeps the game PIDs, checks
they're still alive, and keeps ~/.local/state/lainframe/pc_game on the Frame touched while one is (re-touched every
60 s; the headset ignores a stale flag), removed otherwise. Read-only on the PC: it never talks to SteamVR's API
(writing settings through it can crash SteamVR). Started hidden by `lain_brain.py run`. One copy only (named mutex)."""
import ctypes, os, re, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, frame  # noqa: E402

FLAG = "~/.local/state/lainframe/pc_game"
SCENE = re.compile(r"New Connect message from (.+?) \(VRApplication_Scene\) \(Args:.*?\) (\d+)")


def steam_dir():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return os.path.normpath(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Steam")


def alive(pids):
    if not pids: return set()
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, creationflags=frame.NW).stdout
    running = {int(m) for m in re.findall(r'^"[^"]*","(\d+)"', out, re.M)}
    return {p for p in pids if p in running}


def main():
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\LainframePcGameWatch")
    if ctypes.windll.kernel32.GetLastError() == 183: return "already running"
    log = os.path.join(steam_dir(), "logs", "vrserver.txt")
    pids, pos, published, last_push = set(), 0, None, 0.0
    while True:
        try:
            size = os.path.getsize(log)
            if size < pos: pos = 0; pids.clear()               # SteamVR restarted: new log
            if size > pos:
                with open(log, "rb") as f:
                    f.seek(pos); data = f.read().decode("utf-8", "replace"); pos = f.tell()
                for exe, pid in SCENE.findall(data): pids.add(int(pid))
        except OSError:
            pass
        pids = alive(pids); game = bool(pids)
        if game != published or time.time() - last_push > 60:  # on change, and refresh every minute
            cfg = config.load()
            if cfg["headset"]["host"]:
                cmd = ("mkdir -p ~/.local/state/lainframe && touch " if game else "rm -f ") + FLAG
                try:
                    if frame.run(cfg, cmd, timeout=20).returncode == 0: published = game; last_push = time.time()
                except Exception: pass
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
