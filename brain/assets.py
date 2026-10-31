"""Art and voice downloads for Lainframe (all on the PC; standard library + Pillow/numpy for the sky panorama).
  - art: the GitHub Release zips (lainframe-lain-clips-1..N.zip, lainframe-skies.zip) or local zips -> unpacked into
    <art>/clips_grok, <art>/skies and <art>/weather -> <art>/clips_baked baked by art_pipeline/bake_rgbz.py
  - voice: whisper.cpp (Windows x64 build) + ggml base.en model, Kokoro onnx + voices
  - SteamVR background: one sky mood's cube faces -> an equirect panorama PNG
Downloads resume (.part + HTTP Range) and check sha256 when one is known."""
import hashlib, os, re, shutil, subprocess, sys, time, urllib.error, urllib.request, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

UA = {"User-Agent": "Lainframe-setup"}
WHISPER_ZIP = "https://github.com/ggml-org/whisper.cpp/releases/latest/download/whisper-bin-x64.zip"
WHISPER_MODEL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
KOKORO = {"kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
          "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"}


def art_dir(cfg):
    return config.path(cfg["art"]["local_dir"])


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB": return ("%.0f %s" if u in ("B", "KB") else "%.1f %s") % (n, u)
        n /= 1024.0


def bar(done, total, label="", width=30):
    """one-line console progress bar (\\r redraw)."""
    if total:
        f = min(1.0, done / total); fill = int(width * f)
        s = "\r  [%s%s] %3d%%  %s" % ("#" * fill, "." * (width - fill), f * 100, label)
    else: s = "\r  %s %s" % (human(done), label)
    sys.stdout.write(s[:110].ljust(110)); sys.stdout.flush()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def download(url, dest, sha=None, progress=bar, tries=5):
    """url -> dest, resuming dest.part. Raises RuntimeError with a plain message on failure."""
    if os.path.exists(dest) and (not sha or sha256(dest).lower() == sha.lower()): return dest
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    part = dest + ".part"; last = None; ok = False
    for attempt in range(tries):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        req = urllib.request.Request(url, headers=dict(UA, **({"Range": "bytes=%d-" % have} if have else {})))
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if have and r.status == 200: have = 0                         # server ignored Range: start over
                total = r.headers.get("Content-Length"); total = int(total) + have if total else 0
                with open(part, "ab" if have else "wb") as f:
                    got = have; t0 = time.time(); g0 = got
                    while True:
                        b = r.read(1 << 20)
                        if not b: break
                        f.write(b); got += len(b)
                        if progress:
                            spd = (got - g0) / max(0.5, time.time() - t0)
                            progress(got, total, "%s of %s, %s/s" % (human(got), human(total) if total else "?", human(spd)))
            if total and os.path.getsize(part) < total: raise IOError("connection dropped")
            ok = True; break
        except urllib.error.HTTPError as e:
            if e.code == 416 and have: ok = True; break                          # already complete
            last = "HTTP %d %s" % (e.code, e.reason)
            if e.code in (401, 403, 404): break                                  # retrying won't help
        except OSError as e:
            last = str(e)
        if progress: print("\n  (connection problem: %s, retrying)" % last)
        time.sleep(min(30, 2 ** attempt))
    if progress: print()
    if not ok: raise RuntimeError("download failed: %s (%s)" % (url, last))
    if sha and sha256(part).lower() != sha.lower():
        os.remove(part); raise RuntimeError("checksum mismatch for %s: the file was damaged, run setup again" % url)
    os.replace(part, dest)
    return dest


def unzip(zpath, dest, progress=bar):
    """extract (resumable: files already there with the right size are skipped); refuses paths leaving dest."""
    dest = os.path.abspath(dest)
    with zipfile.ZipFile(zpath) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        total = sum(i.file_size for i in infos) or 1; done = 0
        for i in infos:
            out = os.path.abspath(os.path.join(dest, i.filename))
            if not out.startswith(dest + os.sep): raise RuntimeError("unsafe path in zip: " + i.filename)
            if not (os.path.exists(out) and os.path.getsize(out) == i.file_size):
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with z.open(i) as s, open(out + ".tmp", "wb") as d: shutil.copyfileobj(s, d, 1 << 20)
                os.replace(out + ".tmp", out)
            done += i.file_size
            if progress: progress(done, total, os.path.basename(i.filename))
    if progress: print()


def find_root(top, want):
    """the folder under `top` that IS the library: for "clips" the one holding clips.json, for "skies" the one whose
    subfolders hold front.png."""
    for d, subs, files in os.walk(top):
        if want == "clips" and "clips.json" in files: return d
        if want == "skies" and any(os.path.exists(os.path.join(d, s, "front.png")) for s in subs): return d
        if want == "weather" and ("wires.json" in files or "rain_atlas.png" in files): return d
    return None


def install_zip(cfg, zpaths, kind, progress=bar):
    """unpack a release zip and put its libraries in place: the clips pack -> <art>/clips_grok; the skies pack ->
    <art>/skies (skies/<mood>/ cube faces) AND <art>/weather (the sky's rain/lightning/cat/crow/car sprites, wires.json).
    -> the folders, joined by ", " """
    art = art_dir(cfg); tmp = os.path.join(art, "_unpack_" + kind)
    zpaths = [zpaths] if isinstance(zpaths, str) else list(zpaths)      # the clips come as several parts: one library
    for zp in zpaths: unzip(zp, tmp, progress)
    zpath = zpaths[0]
    parts = [("clips", "clips_grok")] if kind == "clips" else [("weather", "weather"), ("skies", "skies")]
    # weather first: if the zip's top folder IS the skies folder, weather/ sits inside it and must move out first
    found = [(find_root(tmp, w), name) for w, name in parts]
    for (root, name), (w, _) in zip(found, parts):
        if not root: raise RuntimeError("%s does not look like the Lainframe %s pack (no %s inside)" % (os.path.basename(zpath), kind, w))
    out = []
    for root, name in found:
        final = os.path.join(art, name)
        if os.path.exists(final): shutil.rmtree(final)
        os.replace(root, final); out.append(final)
    shutil.rmtree(tmp, ignore_errors=True)
    return ", ".join(out)


def count(folder, exts=None):
    n = b = 0
    for d, _, fs in os.walk(folder):
        for f in fs:
            if exts and not f.lower().endswith(exts): continue
            n += 1; b += os.path.getsize(os.path.join(d, f))
    return n, b


def art_state(cfg):
    a = art_dir(cfg)
    return {k: count(os.path.join(a, k)) for k in ("clips_grok", "clips_baked", "skies", "weather")}


def bake(cfg, progress=bar):
    """art_pipeline/bake_rgbz.py over <art>/clips_grok -> <art>/clips_baked (skips up-to-date files)."""
    a = art_dir(cfg)
    p = subprocess.Popen([config.venv_python(), os.path.join(config.ROOT, "art_pipeline", "bake_rgbz.py"),
                          "--src", os.path.join(a, "clips_grok"), "--out", os.path.join(a, "clips_baked")],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    last = ""
    for line in p.stdout:
        m = re.match(r"progress (\d+) (\d+)", line)
        if m and progress: progress(int(m.group(1)), int(m.group(2)), "images")
        elif line.strip(): last = line.strip()
    if progress: print()
    if p.wait() != 0: raise RuntimeError("baking failed: " + last)
    return last


def free_gb(folder):
    d = folder
    while not os.path.exists(d) and os.path.dirname(d) != d: d = os.path.dirname(d)
    return shutil.disk_usage(d).free / 1e9


# ---------------- voice
def whisper(cfg, progress=bar):
    """whisper.cpp for Windows + the base.en model under %LOCALAPPDATA%\\Lainframe\\whisper. Sets the config paths."""
    wd = os.path.join(config.DATA_DIR, "whisper")
    exe = next((os.path.join(d, "whisper-cli.exe") for d, _, fs in os.walk(wd) if "whisper-cli.exe" in fs), None) \
        if os.path.isdir(wd) else None
    if not exe:
        z = download(WHISPER_ZIP, os.path.join(config.DATA_DIR, "downloads", "whisper-bin-x64.zip"), progress=progress)
        unzip(z, wd, progress)
        exe = next((os.path.join(d, "whisper-cli.exe") for d, _, fs in os.walk(wd) if "whisper-cli.exe" in fs), None)
        if not exe: raise RuntimeError("the whisper.cpp download has no whisper-cli.exe")
    model = download(WHISPER_MODEL, os.path.join(wd, "ggml-base.en.bin"), progress=progress)
    cfg["voice"]["whisper_exe"], cfg["voice"]["whisper_model"] = exe, model
    return exe, model


def kokoro(cfg, progress=bar):
    kd = os.path.join(config.DATA_DIR, "kokoro")
    for f, u in KOKORO.items(): download(u, os.path.join(kd, f), progress=progress)
    cfg["voice"]["kokoro_dir"] = kd
    return kd


# ---------------- SteamVR background: cube faces -> equirect
FACES = {"front": ((0, 0, -1), (1, 0, 0), (0, 1, 0)), "back": ((0, 0, 1), (-1, 0, 0), (0, 1, 0)),
         "right": ((1, 0, 0), (0, 0, 1), (0, 1, 0)), "left": ((-1, 0, 0), (0, 0, -1), (0, 1, 0)),
         "up": ((0, 1, 0), (1, 0, 0), (0, 0, 1)), "down": ((0, -1, 0), (1, 0, 0), (0, 0, -1))}
# = the cutter that made the faces (OpenVR axes x right, y up, -z forward; face pixel (u right, v up) = F + u X + v Y;
# panorama centre column = forward, as SteamVR backgrounds expect)


def moods(cfg):
    s = os.path.join(art_dir(cfg), "skies")
    return sorted(d for d in os.listdir(s) if os.path.exists(os.path.join(s, d, "front.png"))) if os.path.isdir(s) else []


def equirect(face_dir, out_png, width=4096):
    """6 faces (flat_<face>.png preferred: those include the foreground and road) -> width x width/2 panorama."""
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    H = width // 2
    lon = ((np.arange(width) + 0.5) / width - 0.5) * 2 * np.pi
    lat = (0.5 - (np.arange(H) + 0.5) / H) * np.pi
    LON, LAT = np.meshgrid(lon, lat)
    px, py, pz = np.sin(LON) * np.cos(LAT), np.cos(LON) * np.cos(LAT), np.sin(LAT)   # panorama: x right, y fwd, z up
    d = np.stack([px, pz, -py], -1).astype(np.float32)                                  # -> OpenVR axes
    out = np.zeros((H, width, 3), np.float32)
    best = np.full((H, width), -1.0, np.float32); which = np.full((H, width), -1, np.int8)
    names = list(FACES)
    for k, n in enumerate(names):
        dp = d @ np.array(FACES[n][0], np.float32)
        m = dp > best; best[m] = dp[m]; which[m] = k
    for k, n in enumerate(names):
        m = which == k
        if not m.any(): continue
        F, X, Y = (np.array(v, np.float32) for v in FACES[n])
        f = next((os.path.join(face_dir, p + n + ".png") for p in ("flat_", "") if os.path.exists(os.path.join(face_dir, p + n + ".png"))), None)
        if not f: raise RuntimeError("sky face %s missing in %s" % (n, face_dir))
        img = np.asarray(Image.open(f).convert("RGB"), np.float32); S = img.shape[0]
        dd = d[m] / (d[m] @ F)[:, None]
        u, v = dd @ X, dd @ Y
        x = np.clip((u + 1) / 2 * S - 0.5, 0, S - 1.001); y = np.clip((1 - v) / 2 * S - 0.5, 0, S - 1.001)
        x0, y0 = x.astype(int), y.astype(int); fx, fy = (x - x0)[:, None], (y - y0)[:, None]
        out[m] = (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy)
                  + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)
    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(out_png)
    return out_png
