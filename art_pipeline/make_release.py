"""Pack Lainframe's art into GitHub Release zips (each release file must stay under 2 GiB).
    python art_pipeline/make_release.py --clips <clips_grok dir> --skies <skies dir> --weather <weather dir> --out <dir>
-> lainframe-lain-clips-1.zip .. -N.zip  (clips_grok/<clip>/... split at clip-folder boundaries; part 1 also carries the
   library's top-level files: clips.json, eyes.json, ...)
-> lainframe-skies.zip                   (skies/<mood>/... + weather/...)
-> SHA256SUMS.txt + release.json         ({"lain_clips_parts": N, "sha256": {name: hash}}) for brain/config.py
PNGs are already compressed: the zips STORE them (fast, same size). Backup/scratch files (*.bak*, *.off, *.tmp) are left out."""
import argparse, hashlib, json, os, zipfile

LIMIT = int(1.8 * 1024 ** 3)                     # stay well under GitHub's 2 GiB per release file


def files_under(top, arc_root):
    out = []
    for d, subs, fs in os.walk(top):
        subs[:] = sorted(s for s in subs if not s.startswith(("_", ".")) and ".bak" not in s and not s.endswith(".off"))
        for f in sorted(fs):
            if ".bak" in f or f.endswith((".off", ".tmp", ".pyc")) or f.startswith("."): continue
            p = os.path.join(d, f); out.append((p, os.path.join(arc_root, os.path.relpath(p, top)).replace("\\", "/")))
    return out


def write_zip(path, items):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for i, (p, arc) in enumerate(items):
            z.write(p, arc)
            if i % 500 == 0: print("  %s: %d/%d" % (os.path.basename(path), i, len(items)), flush=True)
    return path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clips", required=True); ap.add_argument("--skies", required=True); ap.add_argument("--weather", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    # clips: top-level files go in part 1; clip folders are packed greedily, never split
    top = [(os.path.join(a.clips, f), "clips_grok/" + f) for f in sorted(os.listdir(a.clips))
           if os.path.isfile(os.path.join(a.clips, f)) and ".bak" not in f]
    folders = [d for d in sorted(os.listdir(a.clips)) if os.path.isdir(os.path.join(a.clips, d)) and not d.startswith(("_", "."))
               and ".bak" not in d]
    parts = [list(top)]; size = sum(os.path.getsize(p) for p, _ in top)
    for d in folders:
        items = files_under(os.path.join(a.clips, d), "clips_grok/" + d); s = sum(os.path.getsize(p) for p, _ in items)
        if size + s > LIMIT and parts[-1]: parts.append([]); size = 0
        parts[-1] += items; size += s
    names = []
    for i, items in enumerate(parts, 1):
        n = "lainframe-lain-clips-%d.zip" % i; print("writing", n, len(items), "files"); write_zip(os.path.join(a.out, n), items); names.append(n)
    sk = files_under(a.skies, "skies") + files_under(a.weather, "weather")
    print("writing lainframe-skies.zip", len(sk), "files"); write_zip(os.path.join(a.out, "lainframe-skies.zip"), sk); names.append("lainframe-skies.zip")
    sums = {n: sha256(os.path.join(a.out, n)) for n in names}
    for n in names:
        sz = os.path.getsize(os.path.join(a.out, n))
        assert sz < 2 * 1024 ** 3, n + " is over 2 GiB"
        print("%-30s %6.0f MB  %s" % (n, sz / 1e6, sums[n]))
    open(os.path.join(a.out, "SHA256SUMS.txt"), "w").write("".join("%s  %s\n" % (sums[n], n) for n in names))
    json.dump({"lain_clips_parts": len(parts), "sha256": sums}, open(os.path.join(a.out, "release.json"), "w"), indent=1)
    print("done ->", a.out)


if __name__ == "__main__":
    main()
