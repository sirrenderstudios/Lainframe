"""Push Lainframe to the Steam Frame and install it there.
  1. libs: Pillow (aarch64 wheel for the Frame's Python 3.12) + pyopenvr, staged on the PC in %LOCALAPPDATA%\\Lainframe\\frame_lib
  2. code: repo headset/ -> ~/lainframe (tar over ssh, CRLF stripped from text files)
  3. lib + art (clips_grok, clips_baked -> ~/lainframe/lain/; skies, weather -> ~/lainframe/sky/): per top-level subfolder, tar over ssh into <dest>.part/<sub>, then moved into place. Subfolders whose
     file count and byte total already match are skipped, so an interrupted push resumes where it stopped.
  4. pyopenvr's loader wants lib/openvr/libopenvr_api_64.so: linked to SteamVR's own linuxarm64 libopenvr_api.so
     (pyopenvr only bundles x86_64 builds)
  5. ~/lainframe/install.sh --extras <list>, then a service/log check
Also: the optional SteamVR background (headset setting, edited only with SteamVR killed) and the headset uninstall.
    python deploy.py [--no-art]"""
import io, json, os, shutil, subprocess, sys, tarfile, time, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets, config, frame  # noqa: E402

REMOTE = "~/lainframe"
STAGE = os.path.join(config.DATA_DIR, "frame_lib")
TEXT_EXT = (".py", ".sh", ".service", ".json", ".conf", ".env", ".txt", ".md", ".cfg", ".ini")
PIP_PLATFORMS = ["manylinux_2_28_aarch64", "manylinux_2_27_aarch64", "manylinux_2_17_aarch64", "manylinux2014_aarch64"]
SERVICES = ["lainframe-lain", "lainframe-sky"]
EXTRA_SERVICES = {"guard": "lainframe-guard", "worn": "lainframe-worn", "mic": "lainframe-mic"}
BG_KEYS = ("background", "backgroundCameraHeight", "backgroundDomeRadius", "backgroundUseDomeProjection",
           "backgroundOmitDomeProjectionFloor")


def say(*a):
    print("  " + " ".join(str(x) for x in a), flush=True)


def rq(p):
    """remote path for a double-quoted shell word: ~/x -> "$HOME/x" """
    return '"%s"' % (("$HOME/" + p[2:]) if p.startswith("~/") else p)


# ---------------- 1. python libs for the Frame
def stage_libs(force=False):
    """pip download the aarch64 Pillow wheel + pyopenvr and unpack them into STAGE/lib. -> lib folder."""
    lib = os.path.join(STAGE, "lib"); ok = os.path.join(STAGE, "staged.json")
    if os.path.exists(ok) and os.path.isdir(lib) and not force: return lib
    shutil.rmtree(STAGE, ignore_errors=True); wh = os.path.join(STAGE, "wheels"); os.makedirs(wh)
    py = config.venv_python()
    plat = sum((["--platform", p] for p in PIP_PLATFORMS), [])
    base = [py, "-m", "pip", "download", "--disable-pip-version-check", "--no-deps", "--only-binary=:all:", "-d", wh]
    say("downloading Pillow for the headset (Linux ARM64, Python 3.12) ...")
    r = subprocess.run(base + plat + ["--python-version", "312", "--implementation", "cp", "--abi", "cp312", "pillow"],
                       capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError("pip could not get Pillow for the headset:\n" + r.stderr[-800:])
    say("downloading pyopenvr ...")
    r = subprocess.run(base + plat + ["--python-version", "312", "openvr"], capture_output=True, text=True)
    if r.returncode != 0:                                    # pure-python wheel: platform tags may not apply
        r = subprocess.run(base + ["openvr"], capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError("pip could not get pyopenvr:\n" + r.stderr[-800:])
    names = []
    for f in sorted(os.listdir(wh)):
        if f.endswith(".whl"):
            with zipfile.ZipFile(os.path.join(wh, f)) as z: z.extractall(lib)
            names.append(f)
    od = os.path.join(lib, "openvr")
    if not os.path.isdir(od): raise RuntimeError("the pyopenvr wheel has no openvr package")
    for f in os.listdir(od):                                  # bundled x86 / Windows / mac libraries are useless there
        if f.lower().endswith((".dll", ".so", ".dylib", ".pdb", ".lib")): os.remove(os.path.join(od, f))
    if not any(n.lower().startswith("pillow") for n in names): raise RuntimeError("no Pillow wheel was downloaded")
    with open(ok, "w") as f: json.dump({"wheels": names, "when": time.strftime("%Y-%m-%d %H:%M")}, f)
    shutil.rmtree(wh, ignore_errors=True)
    return lib


# ---------------- tar over ssh
def _ssh_tar(cfg, dest, members, label):
    """stream a tar of [(abs path, arcname, normalize_crlf)] into remote dir `dest` (created). -> True on success."""
    total = sum(os.path.getsize(p) for p, _, _ in members) or 1
    cmd = "mkdir -p %s && tar -x -C %s" % (rq(dest), rq(dest))
    p = subprocess.Popen(["ssh"] + frame.opts(cfg, 15) + [frame.target(cfg), cmd], stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=frame.NW)
    done = 0
    try:
        with tarfile.open(fileobj=p.stdin, mode="w|", format=tarfile.GNU_FORMAT) as t:
            for path, arc, crlf in members:
                ti = tarfile.TarInfo(arc.replace("\\", "/")); ti.mtime = int(os.path.getmtime(path))
                ti.mode = 0o755 if arc.endswith((".sh",)) else 0o644
                if crlf:
                    data = open(path, "rb").read().replace(b"\r\n", b"\n"); ti.size = len(data); t.addfile(ti, io.BytesIO(data))
                else:
                    ti.size = os.path.getsize(path)
                    with open(path, "rb") as f: t.addfile(ti, f)
                done += os.path.getsize(path)
                assets.bar(done, total, label)
        p.stdin.close()
    except (BrokenPipeError, OSError) as e:
        try: p.kill()
        except OSError: pass
        print(); say("transfer broke:", e); return False
    rc = p.wait(); print()
    if rc != 0: say("remote tar failed:", (p.stderr.read() or b"").decode("utf-8", "replace")[-300:])
    return rc == 0


MANIFEST = r"""
import json, os, sys
def man(r):
    out = {}
    if not os.path.isdir(r): return out
    for e in os.scandir(r):
        if e.is_dir(follow_symlinks=False):
            n = b = 0
            for d, _, fs in os.walk(e.path):
                for f in fs:
                    try: b += os.path.getsize(os.path.join(d, f)); n += 1
                    except OSError: pass
            out[e.name] = [n, b]
        elif e.is_file(): out[e.name] = [1, e.stat().st_size]
    return out
print(json.dumps(man(os.path.expanduser(sys.argv[1]))))
"""


def local_manifest(root):
    out = {}
    for e in os.scandir(root):
        if e.is_dir(): out[e.name] = list(assets.count(e.path))
        elif e.is_file() and not e.name.endswith((".tmp", ".part")): out[e.name] = [1, e.stat().st_size]
    return out


def push_tree(cfg, local, remote, label):
    """mirror folder `local` to `remote`, one top-level entry at a time (see module doc). -> True if all went over."""
    r = frame.py(cfg, MANIFEST, [remote])
    if r.returncode != 0: raise RuntimeError("could not read %s on the headset: %s" % (remote, frame.err(r)))
    have = json.loads(frame.text(r).strip() or "{}"); want = local_manifest(local)
    todo = [k for k, v in want.items() if have.get(k) != v]
    stale = [k for k in have if k not in want]
    if not todo and not stale: say("%s: already up to date (%d items)" % (label, len(want))); return True
    say("%s: %d of %d items to send%s" % (label, len(todo), len(want), (", %d old ones to remove" % len(stale)) if stale else ""))
    part = remote.rstrip("/") + ".part"
    dirs = [k for k in todo if os.path.isdir(os.path.join(local, k))]; files = [k for k in todo if k not in dirs]
    for i, k in enumerate(sorted(dirs)):
        src = os.path.join(local, k)
        mem = [(os.path.join(d, f), os.path.relpath(os.path.join(d, f), local), False)
               for d, _, fs in os.walk(src) for f in fs if not f.endswith((".tmp", ".part"))]
        frame.run(cfg, "rm -rf %s/%s" % (rq(part), frame.shq(k)), 60)
        if not _ssh_tar(cfg, part, mem, "%s %d/%d %s" % (label, i + 1, len(dirs), k)): return False
        r = frame.run(cfg, "mkdir -p {r} && rm -rf {r}/{k} && mv {p}/{k} {r}/{k}".format(r=rq(remote), p=rq(part), k=frame.shq(k)), 120)
        if r.returncode != 0: say("move failed:", frame.err(r)); return False
    if files:
        mem = [(os.path.join(local, k), "_files/" + k, False) for k in files]
        if not _ssh_tar(cfg, part, mem, "%s files" % label): return False
        r = frame.run(cfg, "mkdir -p {r} && mv -f {p}/_files/* {r}/ && rm -rf {p}/_files".format(r=rq(remote), p=rq(part)), 60)
        if r.returncode != 0: say("move failed:", frame.err(r)); return False
    for k in stale: frame.run(cfg, "rm -rf %s/%s" % (rq(remote), frame.shq(k)), 120)
    frame.run(cfg, "rmdir %s 2>/dev/null; true" % rq(part))
    return True


def push_code(cfg):
    src = os.path.join(config.ROOT, "headset")
    mem = [(os.path.join(d, f), os.path.relpath(os.path.join(d, f), src), f.lower().endswith(TEXT_EXT) or "." not in f)
           for d, subs, fs in os.walk(src) if "__pycache__" not in d for f in fs if not f.endswith((".pyc", ".bak"))]
    if not mem: raise RuntimeError("the repo's headset/ folder is empty")
    return _ssh_tar(cfg, REMOTE, mem, "code")


# ---------------- 4. libopenvr_api for ARM64
LINK_OPENVR = r"""
import json, os, struct, sys
lib = os.path.expanduser(sys.argv[1])
def arm64(p):
    try:
        with open(p, "rb") as f: h = f.read(20)
        return h[:4] == b"\x7fELF" and h[4] == 2 and struct.unpack("<H", h[18:20])[0] == 183
    except OSError: return False
found = None
for c in ("/opt/steamvr/bin/linuxarm64/libopenvr_api.so",
          os.path.expanduser("~/.local/share/Steam/steamapps/common/SteamVR/bin/linuxarm64/libopenvr_api.so")):
    if arm64(c): found = c; break
if not found:
    for r in ("/opt/steamvr", os.path.expanduser("~/.local/share/Steam/steamapps/common/SteamVR"), os.path.expanduser("~/.steam/root")):
        for d, subs, fs in os.walk(r):
            p = os.path.join(d, "libopenvr_api.so")
            if "libopenvr_api.so" in fs and arm64(p):
                if found is None or "linuxarm64" in p: found = p
        if found: break
if not found: print(json.dumps({"error": "SteamVR's ARM64 libopenvr_api.so was not found under /opt/steamvr or the Steam library. Start SteamVR on the headset once (or update SteamOS), then run setup again."})); sys.exit(3)
dst = os.path.join(lib, "openvr", "libopenvr_api_64.so")
os.makedirs(os.path.dirname(dst), exist_ok=True)
if os.path.lexists(dst): os.remove(dst)
os.symlink(found, dst)
sys.path.insert(0, lib)
try:
    import openvr, PIL.Image
    print(json.dumps({"lib": found, "openvr": getattr(openvr, "__version__", "?"), "pillow": PIL.__version__}))
except Exception as e:
    print(json.dumps({"lib": found, "error": "python libs do not load on the headset: %r" % (e,)})); sys.exit(4)
"""


def link_openvr(cfg):
    r = frame.py(cfg, LINK_OPENVR, [REMOTE + "/lib"], timeout=120)
    try: res = json.loads(frame.text(r).strip().splitlines()[-1])
    except (ValueError, IndexError): res = {"error": "no answer: " + frame.err(r)}
    if "error" in res: raise RuntimeError(res["error"])
    return res


# ---------------- 5. install.sh + checks
def extras_list(cfg):
    return [k for k in ("guard", "worn", "mic") if cfg["extras"].get(k)]


def run_install(cfg):
    # --extras is always the full list ("none" = disable all), so turning an extra off in setup removes it there too
    ex = extras_list(cfg)
    cmd = "bash ~/lainframe/install.sh --extras " + (",".join(ex) or "none")
    if cfg["extras"].get("worn"): cmd += " --brightness " + ("on" if cfg["extras"].get("brightness") else "off")
    say("running on the headset:", cmd)
    r = frame.run(cfg, cmd, timeout=300)
    out = (frame.text(r) + frame.err(r)).strip()
    for ln in out.splitlines()[-25:]: say("  | " + ln)
    if r.returncode != 0: raise RuntimeError("install.sh failed (exit %d)" % r.returncode)
    return out


VERIFY = r"""
for s in %s; do printf '%%s enabled=%%s active=%%s\n' "$s" "$(systemctl --user is-enabled $s 2>/dev/null)" "$(systemctl --user is-active $s 2>/dev/null)"; done
printf 'wants='; ls ~/.config/systemd/user/steamvr.service.wants/ 2>/dev/null | tr '\n' ' '; echo
echo "steamvr=$(systemctl --user is-active steamvr.service 2>/dev/null)"
s=0; for p in /proc/[0-9]*/exe; do case "$(readlink "$p" 2>/dev/null)" in */vrlink/*) s=1;; esac; done; echo "streaming=$s"
echo "clips=$(find ~/lainframe/lain/clips_grok -type f 2>/dev/null | wc -l) baked=$(find ~/lainframe/lain/clips_baked -type f 2>/dev/null | wc -l) skies=$(find ~/lainframe/sky/skies -type f 2>/dev/null | wc -l) weather=$(find ~/lainframe/sky/weather -type f 2>/dev/null | wc -l)"
echo "openvr=$(readlink ~/lainframe/lib/openvr/libopenvr_api_64.so 2>/dev/null)"
for l in lain sky; do echo "--- $l.log"; tail -n 4 ~/.local/state/lainframe/$l.log 2>/dev/null; done
"""


def verify(cfg):
    """-> (dict of facts, raw text)"""
    svcs = SERVICES + [EXTRA_SERVICES[k] for k in extras_list(cfg)]
    r = frame.script(cfg, VERIFY % " ".join(svcs), timeout=60)
    raw = frame.text(r); facts = {}
    for ln in raw.splitlines():
        if ln.startswith("---"): break
        if " enabled=" in ln:
            n, e, a = ln.split(" ", 2); facts[n] = {"enabled": e.split("=", 1)[1], "active": a.split("=", 1)[1]}
        elif "=" in ln:
            for part in ln.split(" "):
                if "=" in part: k, v = part.split("=", 1); facts[k] = v
    return facts, raw


def deploy(cfg, art=True):
    ok, msg = frame.reachable(cfg)
    if not ok: raise RuntimeError("can't reach the headset: " + msg)
    say("headset:", msg)
    lib = stage_libs()
    frame.run(cfg, "systemctl --user stop %s 2>/dev/null; mkdir -p ~/lainframe" % " ".join(SERVICES), 60)
    if not push_code(cfg): raise RuntimeError("sending the code failed (network?). Run it again: it resumes.")
    if not push_tree(cfg, lib, REMOTE + "/lib", "python libs"): raise RuntimeError("sending the python libs failed; run again")
    if art:
        a = assets.art_dir(cfg)
        for sub, rem, lab in (("clips_grok", "/lain/clips_grok", "Lain clips"), ("clips_baked", "/lain/clips_baked", "baked clips"),
                              ("skies", "/sky/skies", "skies"), ("weather", "/sky/weather", "sky weather sprites")):
            d = os.path.join(a, sub)
            if not os.path.isdir(d): raise RuntimeError("%s is missing on the PC (%s): do the art step first" % (lab, d))
            if not push_tree(cfg, d, REMOTE + rem, lab): raise RuntimeError("sending %s broke off; run again, it resumes" % lab)
    res = link_openvr(cfg); say("openvr ->", res.get("lib"), "| pyopenvr", res.get("openvr"), "| Pillow", res.get("pillow"))
    run_install(cfg)
    facts, raw = verify(cfg)
    return facts, raw


# ---------------- SteamVR background (headset setting)
VRSETTINGS = "~/.config/openvr/config/steamvr.vrsettings"
BG_EDIT = r"""
import json, os, shutil, sys
p = os.path.expanduser("~/.config/openvr/config/steamvr.vrsettings"); bak = p + ".bak-lainframe"
mode, img = sys.argv[1], os.path.expanduser(sys.argv[2])
KEYS = %r
d = json.load(open(p)) if os.path.exists(p) else {}
s = d.setdefault("steamvr", {})
if mode == "set":
    if not os.path.exists(bak) and os.path.exists(p): shutil.copy2(p, bak)      # the user's own settings, kept once
    s.update({"background": img, "backgroundCameraHeight": 1.7, "backgroundDomeRadius": 0.0,
              "backgroundUseDomeProjection": True, "backgroundOmitDomeProjectionFloor": False})
else:
    if not os.path.exists(bak): print("no backup: nothing to restore"); sys.exit(0)
    old = json.load(open(bak)).get("steamvr", {})
    for k in KEYS:
        if k in old: s[k] = old[k]
        else: s.pop(k, None)
tmp = p + ".tmp"; json.dump(d, open(tmp, "w"), indent=3); os.replace(tmp, p)
print("ok", mode)
""" % (BG_KEYS,)


def set_background(cfg, mood, progress=assets.bar):
    """mood's cube faces -> equirect on the PC -> headset -> steamvr.vrsettings (backup kept) -> SteamVR killed so it
    restarts with it (SIGKILL: a clean stop would let SteamVR write its old settings back over ours)."""
    faces = os.path.join(assets.art_dir(cfg), "skies", mood)
    png = os.path.join(config.DATA_DIR, "steamvr_background_%s.png" % mood)
    if not os.path.exists(png):
        say("building the panorama from the %s sky (about a minute) ..." % mood); assets.equirect(faces, png)
    remote_dir = REMOTE + "/sky"
    frame.run(cfg, "mkdir -p " + rq(remote_dir))
    if not frame.scp_to(cfg, [png], remote_dir): raise RuntimeError("could not copy the background to the headset")
    r = frame.py(cfg, BG_EDIT, ["set", remote_dir + "/" + os.path.basename(png)])
    if "ok set" not in frame.text(r): raise RuntimeError("editing SteamVR settings failed: " + frame.err(r))
    frame.run(cfg, "systemctl --user kill --signal=SIGKILL steamvr.service 2>/dev/null; true")
    return True


def restore_background(cfg):
    r = frame.py(cfg, BG_EDIT, ["restore", "-"])
    out = frame.text(r).strip()
    if "ok restore" in out: frame.run(cfg, "systemctl --user kill --signal=SIGKILL steamvr.service 2>/dev/null; true")
    return out or frame.err(r)


# ---------------- uninstall
def uninstall_headset(cfg, remove_key=True):
    out = []
    if cfg.get("skybox_as_steamvr_background"): out.append("background: " + restore_background(cfg))
    sh = r"""
if [ -f ~/lainframe/uninstall.sh ]; then bash ~/lainframe/uninstall.sh; else
  for s in lainframe-lain lainframe-sky lainframe-guard lainframe-worn lainframe-mic; do
    systemctl --user disable --now $s.service 2>/dev/null; rm -f ~/.config/systemd/user/$s.service ~/.config/systemd/user/*.wants/$s.service
  done
  systemctl --user daemon-reload; rm -rf ~/lainframe ~/lainframe.part
fi
echo "headset files removed"
"""
    r = frame.script(cfg, sh, timeout=180); out.append(frame.text(r).strip() or frame.err(r))
    if remove_key:
        pub = config.path(cfg["headset"]["ssh_key"]) + ".pub"
        if os.path.exists(pub):
            k = open(pub).read().split()[1]
            frame.run(cfg, "f=~/.ssh/authorized_keys; [ -f $f ] && { grep -vF %s $f > $f.tmp; mv -f $f.tmp $f; chmod 600 $f; }; true" % frame.shq(k))
            out.append("Lainframe key removed from the headset")
    return "\n".join(out)


if __name__ == "__main__":
    c = config.load()
    f, raw = deploy(c, art="--no-art" not in sys.argv)
    print(raw)
