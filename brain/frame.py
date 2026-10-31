"""ssh / scp to the Steam Frame, and finding it on the LAN. Every call uses BatchMode (never a password prompt),
IdentitiesOnly with the Lainframe key, and `ssh -n` for one-shots (without -n Windows OpenSSH can hang forever).
Shell scripts go through `tr -d '\\r' | bash -s` (Windows line endings break bash).
    import config, frame; cfg = config.load()
    frame.run(cfg, "uname -m").stdout      frame.script(cfg, "echo hi\\n")      frame.find(cfg)"""
import ipaddress, os, re, socket, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

NW = 0x08000000 if os.name == "nt" else 0                     # CREATE_NO_WINDOW: no console flashes from background tools


def opts(cfg, timeout=8):
    return ["-o", "BatchMode=yes", "-o", "ConnectTimeout=%d" % timeout, "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3",
            "-i", config.path(cfg["headset"]["ssh_key"])]


def target(cfg, host=None):
    return "%s@%s" % (cfg["headset"]["user"] or "steamos", host or cfg["headset"]["host"])


def remote_rel(p):
    """~/x -> x (scp paths without a leading / are relative to the home folder; avoids ~ quirks of scp/sftp)."""
    return p[2:] if p.startswith("~/") else p


def run(cfg, cmd, timeout=30, host=None, input=None):
    """one remote command -> CompletedProcess (text). input=None -> ssh -n."""
    a = ["ssh"] + (["-n"] if input is None else []) + opts(cfg) + [target(cfg, host), cmd]
    try:
        return subprocess.run(a, input=None if input is None else input.replace("\r", "").encode("utf-8"),
                              capture_output=True, timeout=timeout, creationflags=NW)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(a, 124, b"", b"timed out after %d s" % timeout)


def text(r):
    return (r.stdout or b"").decode("utf-8", "replace") if isinstance(r.stdout, bytes) else (r.stdout or "")


def err(r):
    e = r.stderr.decode("utf-8", "replace") if isinstance(r.stderr, bytes) else (r.stderr or "")
    return " ".join(e.split())[-300:]


def script(cfg, sh, args=(), timeout=120, host=None):
    """a bash script piped in (CRs stripped on both sides)."""
    return run(cfg, "tr -d '\\r' | bash -s -- " + " ".join(shq(x) for x in args), timeout, host, input=sh)


def py(cfg, src, args=(), timeout=60, host=None):
    """a python3 script piped in, run on the Frame."""
    return run(cfg, "python3 - " + " ".join(shq(x) for x in args), timeout, host, input=src)


def shq(s):
    return "'" + str(s).replace("'", "'\\''") + "'"


def scp_to(cfg, files, remote_dir, timeout=300):
    a = ["scp"] + opts(cfg) + list(files) + ["%s:%s/" % (target(cfg), remote_rel(remote_dir).rstrip("/"))]
    try: return subprocess.run(a, capture_output=True, timeout=timeout, creationflags=NW).returncode == 0
    except subprocess.TimeoutExpired: return False


def scp_from(cfg, remote, local, timeout=120):
    a = ["scp"] + opts(cfg) + ["%s:%s" % (target(cfg), remote_rel(remote)), local]
    try: return subprocess.run(a, capture_output=True, timeout=timeout, creationflags=NW).returncode == 0
    except subprocess.TimeoutExpired: return False


IDENT = "printf '%s|%s|' \"$(hostname)\" \"$(uname -m)\"; . /etc/os-release 2>/dev/null; echo \"$ID\""


def identify(cfg, host=None):
    """(hostname, arch, os id) over BatchMode ssh, or None if the key doesn't get in."""
    r = run(cfg, IDENT, timeout=20, host=host)
    if r.returncode != 0: return None
    parts = text(r).strip().split("|")
    return tuple(parts) if len(parts) == 3 else None


def looks_like_frame(ident):
    """SteamOS on ARM = a Steam Frame (a Steam Deck is SteamOS on x86_64)."""
    return bool(ident) and ident[2].lower() == "steamos" and ident[1] in ("aarch64", "arm64")


def reachable(cfg, host=None):
    """(ok, message) for the configured headset."""
    if not (host or cfg["headset"]["host"]): return False, "no headset address configured"
    if not os.path.exists(config.path(cfg["headset"]["ssh_key"])): return False, "ssh key missing"
    if not port_open(host or cfg["headset"]["host"]): return False, "headset not on the network (off, asleep or other Wi-Fi)"
    ident = identify(cfg, host)
    if not ident: return False, "headset answers but refuses the Lainframe key (redo setup step 3)"
    return True, "%s (%s, %s)" % ident


# ---------------- discovery
def port_open(ip, port=22, timeout=1.2):
    try:
        with socket.create_connection((ip, port), timeout=timeout): return True
    except OSError: return False


def local_ipv4():
    """this PC's private IPv4 addresses (from ipconfig; getaddrinfo misses some adapters)."""
    ips = set()
    try:
        out = subprocess.run(["ipconfig"], capture_output=True, text=True, creationflags=NW).stdout
        ips.update(re.findall(r"IPv4[^:]*:\s*(\d+\.\d+\.\d+\.\d+)", out))
    except OSError: pass
    try: ips.update(i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError: pass
    return sorted(ip for ip in ips if ipaddress.ip_address(ip).is_private and not ip.startswith("127.")
                  and not ip.startswith("169.254."))


def arp_neighbours():
    try: out = subprocess.run(["arp", "-a"], capture_output=True, text=True, creationflags=NW).stdout
    except OSError: return []
    return [ip for ip in re.findall(r"^\s+(\d+\.\d+\.\d+\.\d+)\s+[0-9a-f-]{17}\s+dynamic", out, re.M)]


def resolve(name):
    try: return socket.gethostbyname(name)
    except OSError: return None


def rname(ip):
    try: return socket.gethostbyaddr(ip)[0]
    except OSError: return ""


def scan(extra=(), progress=None):
    """every host with ssh (port 22) open on this PC's /24 networks, the ARP table, frame.local and `extra`.
    -> [(ip, reverse-dns name)], likely Frames first."""
    cands = []
    def add(ip):
        if ip and ip not in cands: cands.append(ip)
    for ip in extra: add(ip)
    for n in ("frame.local", "steamframe.local", "frame", "steamframe"): add(resolve(n))
    for ip in arp_neighbours(): add(ip)
    mine = local_ipv4()
    for ip in mine:
        for h in ipaddress.ip_network(ip + "/24", strict=False).hosts(): add(str(h))
    cands = [c for c in cands if c not in mine]
    done = [0]
    def probe(ip):
        ok = port_open(ip, timeout=0.8); done[0] += 1
        if progress: progress(done[0], len(cands))
        return ip if ok else None
    with ThreadPoolExecutor(96) as ex: hits = [ip for ip in ex.map(probe, cands) if ip]
    out = [(ip, rname(ip)) for ip in hits]
    out.sort(key=lambda t: 0 if re.search(r"frame|steam", t[1], re.I) else 1)
    return out


def find(cfg, save=True):
    """the Frame's address using the installed key (saved address first, then a scan); saves it to config. None if not
    found. Only hosts that let the key in AND run SteamOS on ARM count."""
    saved = cfg["headset"]["host"]
    if saved and port_open(saved) and looks_like_frame(identify(cfg, saved)): return saved
    for ip, _ in scan(extra=[saved] if saved else []):
        if ip == saved: continue
        if looks_like_frame(identify(cfg, ip)):
            if save:
                c = config.load(); c["headset"]["host"] = ip; config.save(c); cfg["headset"]["host"] = ip
            return ip
    return None


if __name__ == "__main__":
    c = config.load()
    print(reachable(c)[1])
