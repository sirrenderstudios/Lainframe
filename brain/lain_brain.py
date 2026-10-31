"""Lain Brain: the PC half of Lainframe. Double-click LainBrain.bat (it makes the .venv and runs this).
    lain_brain.py                  not set up yet -> setup; set up -> run
    lain_brain.py setup            the step-by-step setup (resumable: re-run it any time, it continues where it stopped)
    lain_brain.py setup --step 7   run just that step again (e.g. 7 = SteamVR background, 8 = voice)
    lain_brain.py setup --dry-run  walk every step and print what it would do: no network, no ssh, nothing saved
    lain_brain.py run              start the background parts (voice bridge, game watcher, ...) and show status
    lain_brain.py stop             stop them
    lain_brain.py status           what's configured and what's running
    lain_brain.py deploy [--no-art]  push code (+ art) to the headset again and reinstall
    lain_brain.py doctor           health check: every part green/red, with the fix
    lain_brain.py uninstall        remove Lainframe from the headset and (if you want) from this PC
Settings: %APPDATA%\\Lainframe\\config.json. Big files and logs: %LOCALAPPDATA%\\Lainframe."""
import argparse, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import assets, config, deploy, frame  # noqa: E402

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
if os.name == "nt": os.system("")                                   # turns on ANSI colours in the Windows console

DRY = False
G, Y, R, B, D, X = "\033[92m", "\033[93m", "\033[91m", "\033[96m", "\033[2m", "\033[0m"
STEP_TITLES = {"welcome": "Welcome and PC check", "prereqs": "Get the headset ready", "headset": "Connect to the headset",
               "art": "Lain's art", "extras": "Optional extras", "deploy": "Install on the headset",
               "background": "Sky as the SteamVR background (optional)", "voice": "Talking to Lain (optional)",
               "autostart": "Start with Windows (optional)", "doctor": "Final check"}
STARTUP_LNK = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup", "Lainframe Brain.lnk")
NEW_CONSOLE = 0x00000010
BG_FLAGS = 0x08000000 | 0x00000200                                  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP


# ---------------- console helpers
def info(*a): print("  " + " ".join(str(x) for x in a))
def ok(*a): print("  %s[ok]%s %s" % (G, X, " ".join(str(x) for x in a)))
def warn(*a): print("  %s[!]%s  %s" % (Y, X, " ".join(str(x) for x in a)))
def bad(*a): print("  %s[x]%s  %s" % (R, X, " ".join(str(x) for x in a)))
def dry(*a): print("  %s(dry run) %s%s" % (D, " ".join(str(x) for x in a), X))


def ask(prompt, default=""):
    if DRY: print("  %s? %s%s -> %s" % (B, prompt, X, default or "(Enter)")); return default
    try: a = input("  %s?%s %s%s: " % (B, X, prompt, (" [%s]" % default) if default else "")).strip()
    except EOFError: a = ""
    return a or default


def yes(prompt, default=False):
    if DRY: print("  %s? %s%s -> y (dry run walks every branch)" % (B, prompt, X)); return True
    while True:
        a = ask(prompt + (" (Y/n)" if default else " (y/N)"), "y" if default else "n").lower()
        if a in ("y", "yes"): return True
        if a in ("n", "no"): return False
        info("Please type y or n.")


def wait_enter(prompt="Press Enter when you're ready"):
    ask(prompt)


def header(n, key):
    print("\n%s== Step %d of %d: %s ==%s" % (B, n, len(config.STEPS), STEP_TITLES[key], X))


def save(cfg):
    if DRY: return
    config.save(cfg)


def mark(cfg, step):
    if DRY: return
    config.mark(cfg, step)


# ---------------- steps
def step_welcome(cfg):
    info("Lain Brain will set up Lainframe: Lain Iwakura living above your Steam Frame's menu, and the live")
    info("\"Wired\" sky around you. It walks you through everything, one numbered step at a time:")
    for i, k in enumerate(config.STEPS, 1): info("  %2d. %s" % (i, STEP_TITLES[k]))
    info("Time: about 30-90 minutes, mostly waiting for downloads (~6 GB) and the copy to the headset.")
    info("You can close this window at any point: run LainBrain.bat again and it continues where it stopped.")
    print()
    good = True
    if os.name != "nt": bad("This part of Lainframe runs on Windows."); good = False
    else: ok("Windows")
    if sys.version_info >= (3, 12): ok("Python %d.%d" % sys.version_info[:2])
    else: bad("Python 3.12 or newer is needed (this is %d.%d)" % sys.version_info[:2]); good = False
    for exe in ("ssh", "scp", "ssh-keygen"):
        if shutil.which(exe): ok(exe, "found")
        else:
            bad(exe, "is missing. Install Windows' \"OpenSSH Client\": Settings > System > Optional features >")
            info("     View features > search \"OpenSSH Client\" > Install. Then run LainBrain.bat again."); good = False
    art = assets.art_dir(cfg); free = assets.free_gb(art)
    if free >= 10: ok("%.0f GB free on the drive for %s" % (free, art))
    else: warn("only %.1f GB free where the art goes (%s); about 10 GB are needed." % (free, art))
    if not good: return False
    return yes("Ready to start?", True)


def step_prereqs(cfg):
    info("Do these on the headset once (they can't be done from the PC). Take your time:")
    print("""
   1. Update SteamOS: Steam menu > Settings > System > check for updates. Install any update and restart.
   2. Turn on Developer Mode: Settings > System > "Enable Developer Mode" (then a Developer section appears in Settings).
   3. Switch to Desktop Mode: Steam menu > Power > "Switch to Desktop".
   4. Open Konsole (the terminal): app launcher (bottom-left) > System > Konsole.
   5. Give the "steamos" user a password. Type this and press Enter:
          passwd
      Choose a password and type it twice. Nothing shows while you type, that's normal.
      Remember it: you'll type it ONCE more, in a window on this PC, in step 3. Lain Brain never sees or saves it.
   6. Turn on SSH (lets this PC copy files to the headset). Type this, press Enter, and give the same password:
          sudo systemctl enable --now sshd
   7. Optional, but handy for step 3: see the headset's network address by typing
          ip -4 addr | grep inet
      (the line that is NOT 127.0.0.1, e.g. 10.0.0.42).
   8. Go back to the normal headset view: double-click "Return to Gaming Mode" on the desktop.
   9. Keep the headset on the SAME Wi-Fi/network as this PC, and awake.
""")
    return yes("Have you done all of these?", False)


def make_key(cfg):
    key = config.path(cfg["headset"]["ssh_key"])
    if os.path.exists(key) and os.path.exists(key + ".pub"): return key
    if DRY: dry("would create the ssh key", key); return key
    os.makedirs(os.path.dirname(key), exist_ok=True)
    r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "lainframe", "-f", key], capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError("ssh-keygen failed: " + r.stderr)
    ok("made a key for Lainframe:", key)
    return key


def pick_host(cfg):
    """scan, list, let the user choose or type an address. -> ip or None"""
    if DRY: dry("would scan this PC's networks for devices with SSH open"); return "192.0.2.10"
    while True:
        info("Looking for your headset on this PC's networks (about 10 seconds) ...")
        found = frame.scan(extra=[cfg["headset"]["host"]] if cfg["headset"]["host"] else [],
                           progress=lambda d, t: assets.bar(d, t, "addresses checked"))
        print()
        if found:
            info("Devices that accept SSH:")
            for i, (ip, name) in enumerate(found, 1):
                hint = "  <- probably your Frame" if ("frame" in name.lower() or "steam" in name.lower()) else ""
                info("  %d. %s  %s%s" % (i, ip, name, hint))
        else:
            warn("No device with SSH turned on was found. Is the headset awake, on the same network, and did")
            info("     step 2 (passwd + sudo systemctl enable --now sshd) work?")
        a = ask("Type a number from the list, an address (like 10.0.0.42), or press Enter to search again", "")
        if not a: continue
        if a.isdigit() and 1 <= int(a) <= len(found): return found[int(a) - 1][0]
        if a.count(".") == 3 and all(p.isdigit() for p in a.split(".")):
            if frame.port_open(a): return a
            warn("%s doesn't answer on the SSH port. Check the address and that SSH is on." % a)
        else: warn("That's neither a list number nor an address.")


def install_key(cfg, host):
    """opens a NEW console where the user types the headset password (this program never sees it)."""
    pub = open(config.path(cfg["headset"]["ssh_key"]) + ".pub").read().strip()
    user = cfg["headset"]["user"] or "steamos"
    remote = ("mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
              " && (grep -qxF '{k}' ~/.ssh/authorized_keys || echo '{k}' >> ~/.ssh/authorized_keys) && echo Lainframe key installed.").format(k=pub)
    bat = os.path.join(config.DATA_DIR, "install_key.bat"); os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(bat, "w", encoding="ascii", newline="\r\n") as f:
        f.write("""@echo off
title Lainframe - type your headset password here
echo.
echo   This window connects to your Steam Frame at {host} ONE time, to install Lainframe's key.
echo   When it asks for a password, type the one you set with passwd on the headset and press Enter.
echo   Nothing shows while you type. That's normal.
echo   If it asks "Are you sure you want to continue connecting", type yes and press Enter.
echo.
ssh -o StrictHostKeyChecking=accept-new -o PubkeyAuthentication=no -o PreferredAuthentications=keyboard-interactive,password {user}@{host} "{remote}"
if errorlevel 1 goto failed
echo.
echo   Done. This window closes in a few seconds.
timeout /t 4 >nul
exit /b 0
:failed
echo.
echo   That didn't work. Most likely a mistyped password. Close this window and try again from the setup window.
pause
exit /b 1
""".format(host=host, user=user, remote=remote))
    info("A new window opens now. Type your headset password THERE (not here).")
    return subprocess.Popen(["cmd", "/c", bat], creationflags=NEW_CONSOLE).wait() == 0


def step_headset(cfg):
    make_key(cfg)
    if DRY:
        pick_host(cfg); dry("would open a new console window running ssh so YOU type the headset password once")
        dry("would then check that the key works (ssh BatchMode) and that it's SteamOS on ARM"); return True
    cur = cfg["headset"]["host"]
    if cur and frame.reachable(cfg)[0]:
        ok("already connected to", cur, "-", frame.reachable(cfg)[1])
        if not yes("Use a different headset or address?", False): return True
    for attempt in range(4):
        host = pick_host(cfg)
        ident = frame.identify(cfg, host)
        if not ident:
            if not install_key(cfg, host):
                warn("The key wasn't installed.")
                if yes("Did it complain about a CHANGED HOST KEY / possible spoofing? (an old device used this address)", False):
                    subprocess.run(["ssh-keygen", "-R", host], capture_output=True); info("Forgot the old key for", host)
                if yes("Try again?", True): continue
                return False
            ident = frame.identify(cfg, host)
        if not ident:
            bad("The key still doesn't work on", host); continue
        if not frame.looks_like_frame(ident):
            warn("%s is %s (%s, %s), which doesn't look like a Steam Frame (SteamOS on ARM)." % ((host,) + ident))
            if not yes("Use it anyway?", False): continue
        cfg["headset"]["host"] = host; save(cfg)
        ok("connected: %s is %s (%s, %s). No password needed from now on." % ((host,) + ident))
        return True
    return False


def step_art(cfg):
    art = assets.art_dir(cfg)
    info("Lain's animation library and the skies (with their weather: rain, lightning, the cat, crows, cars) are big,")
    info("so they aren't in the code download. They come as three zip files (Lain in two parts, plus the sky).")
    info("They go to:", art, "(change \"art.local_dir\" in %s to move them)" % config.CONFIG)
    st = assets.art_state(cfg) if not DRY else {"clips_grok": (0, 0), "clips_baked": (0, 0), "skies": (0, 0), "weather": (0, 0)}
    have_clips = st["clips_grok"][0] > 0 and os.path.exists(os.path.join(art, "clips_grok", "clips.json"))
    have_skies = (bool(assets.moods(cfg)) and st["weather"][0] > 0) if not DRY else False
    redo = True
    if have_clips and have_skies:
        ok("art is already here: %d clip images, %d sky images, %d weather sprites" % (st["clips_grok"][0], st["skies"][0], st["weather"][0]))
        redo = yes("Get the art again (e.g. a newer release)?", False)
    if redo:
        packs = config.art_packs(cfg); rel = cfg["art"].get("release") or config.RELEASE
        urls_ok = config.url_set(rel)
        info("Where should the art come from?")
        info("  1. Download it from the Lainframe release page" + ("" if urls_ok else " (no release address set yet)"))
        info("  2. I already downloaded the zip files: " + ", ".join(n for _, n in packs))
        c = ask("1 or 2", "1" if urls_ok else "2")
        zips = {"clips": [], "skies": []}
        if c == "1":
            if not urls_ok:
                rel = ask("Address of the release download folder (ends with /download/)", ""); cfg["art"]["release"] = rel; save(cfg)
                if not rel: bad("no address given"); return False
            for kind, name in packs:
                url = rel.rstrip("/") + "/" + name
                if DRY: dry("would download", url, "(resumable)"); continue
                info("Downloading %s ..." % name)
                try: zips[kind].append(assets.download(url, os.path.join(config.DATA_DIR, "downloads", name),
                                                       (cfg["art"].get("sha256") or {}).get(name) or None))
                except RuntimeError as e: bad(e); info("Run setup again to resume the download."); return False
        else:
            folder = ask("Folder with the zip files", os.path.join(os.path.expanduser("~"), "Downloads")).strip('"')
            for kind, name in packs:
                p = os.path.join(folder, name)
                while not (DRY or os.path.isfile(p)):
                    warn("not found:", p)
                    p = ask("Full path of %s" % name, p).strip('"')
                zips[kind].append(p)
        for kind, zl in zips.items():
            if not zl: continue
            if DRY: dry("would unpack", ", ".join(zl), "into", art); continue
            info("Unpacking %s ..." % ", ".join(os.path.basename(z) for z in zl))
            try: ok("->", assets.install_zip(cfg, zl, kind))
            except (RuntimeError, OSError, Exception) as e: bad(e); return False
        if c == "1" and zips and not DRY and yes("Delete the downloaded zip files to free space?", True):
            for z in [z for zl in zips.values() for z in zl]:
                try: os.remove(z)
                except OSError: pass
    info("Preparing Lain's images for the headset (\"baking\": so the headset doesn't decode PNGs while she moves).")
    info("This uses all CPU cores for a few minutes; it skips images already done.")
    if DRY: dry("would run art_pipeline/bake_rgbz.py --src", os.path.join(art, "clips_grok"), "--out", os.path.join(art, "clips_baked")); return True
    try: ok(assets.bake(cfg))
    except RuntimeError as e: bad(e); return False
    st = assets.art_state(cfg)
    ok("clips %d files, baked %d, skies %d, weather %d (%s total)" % (st["clips_grok"][0], st["clips_baked"][0], st["skies"][0], st["weather"][0],
                                                        assets.human(sum(v[1] for v in st.values()))))
    return True


EXTRAS = [
    ("guard", "Boot guard",
     "Watches the first 10 minutes after each headset start. If a SteamOS update leaves the headset stuck in Desktop "
     "Mode, it switches back to the normal view; if the Steam view keeps crashing because of a known broken colour "
     "add-on (FrameColor's vkBasalt layer) it turns that add-on off and RESTARTS SteamVR (only in that case). Skip it "
     "if you don't use FrameColor and rarely update."),
    ("worn", "Headset-on detector",
     "A small headset service notices when you put the headset on, and Lain Brain then starts SteamVR on the PC by "
     "itself (so streaming begins without clicking anything). Costs a tiny bit of battery; the PC asks the headset "
     "every few seconds while Lain Brain runs."),
    ("mic", "Microphone fix",
     "Holds the headset microphone gain at a cleaner level (the headset resets it to a loud, hissy setting) and adds a "
     "voice EQ to the mic that goes to your PC stream. Changes the mic for EVERY app on the PC stream, not just Lain. "
     "Only useful if your mic sounds harsh or clips."),
]


def step_extras(cfg):
    info("These are all OFF unless you say yes. You can change them any time (setup --step 5, then --step 6).")
    for key, name, text in EXTRAS:
        print("\n  %s%s%s" % (B, name, X))
        words = text.split(); line = "    "
        for w in words:
            if len(line) + len(w) > 112: print(line); line = "    "
            line += w + " "
        print(line)
        cfg["extras"][key] = yes("Turn on %s?" % name, bool(cfg["extras"].get(key)))
        if key == "worn" and cfg["extras"]["worn"]:
            info("    Also: dim the headset screen when you take it off, and back to full when you put it on?")
            cfg["extras"]["brightness"] = yes("Turn on screen dimming?", bool(cfg["extras"].get("brightness")))
        elif key == "worn": cfg["extras"]["brightness"] = False
    save(cfg)
    on = [n for k, n, _ in EXTRAS if cfg["extras"][k]]
    ok("extras:", ", ".join(on) if on else "none")
    return True


def step_deploy(cfg):
    info("Now everything goes to the headset: Lain's code, two Python libraries, the art (~5 GB), then the")
    info("install script sets up the services. Over Wi-Fi the art takes 10-40 minutes; it resumes if interrupted.")
    info("Keep the headset awake (on, or on its charger with the screen on) until this finishes.")
    if DRY:
        dry("would download Pillow (Linux ARM64, Python 3.12) and pyopenvr with pip download into", deploy.STAGE)
        dry("would push headset/ -> ~/lainframe, libs -> ~/lainframe/lib, art -> ~/lainframe/lain/clips_grok, clips_baked, ~/lainframe/sky/skies, ~/lainframe/sky/weather")
        dry("would link SteamVR's ARM64 libopenvr_api.so into ~/lainframe/lib/openvr/libopenvr_api_64.so")
        dry("would run: bash ~/lainframe/install.sh --extras %s" % (",".join(deploy.extras_list(cfg)) or "none"))
        return True
    wait_enter("Headset on and awake? Press Enter to start")
    try:
        facts, raw = deploy.deploy(cfg)
    except RuntimeError as e:
        bad(e); return False
    print()
    good = True
    for s in deploy.SERVICES + [deploy.EXTRA_SERVICES[k] for k in deploy.extras_list(cfg)]:
        f = facts.get(s, {})
        if f.get("enabled") == "enabled": ok(s, "installed")
        else: bad(s, "not enabled (%s)" % f.get("enabled", "?")); good = False
    if facts.get("openvr"): ok("OpenVR library linked")
    else: bad("OpenVR library missing"); good = False
    info("Lain and the sky start together with SteamVR on the headset. Lain only appears while the headset is")
    info("streaming from this PC (Steam Link), and only when you open the Steam menu. Her log says \"lain (grok) ready\"")
    info("only once such a stream runs, so don't worry if it isn't there yet.")
    return good


def step_background(cfg):
    info("Optional: use one of the Wired skies as the headset's SteamVR background (what you see around the menu")
    info("when the live sky isn't showing). Your current SteamVR settings are backed up on the headset first and")
    info("\"uninstall\" puts them back. This RESTARTS SteamVR on the headset once (a running stream or game stops).")
    want = yes("Use the Wired sky as the SteamVR background?", bool(cfg.get("skybox_as_steamvr_background")))
    if not want:
        if cfg.get("skybox_as_steamvr_background") and not DRY:
            if yes("It's on now. Put your old background back (restarts SteamVR on the headset)?", True):
                info(deploy.restore_background(cfg)); cfg["skybox_as_steamvr_background"] = False; save(cfg)
        return True
    ms = assets.moods(cfg) if not DRY else ["lain_night"]
    ms = [m for m in ms if not m.endswith("_red")] or ms
    if not ms: bad("no skies on this PC (step 4)"); return False
    info("Skies:", ", ".join(ms))
    mood = ask("Which one", cfg.get("background_mood") if cfg.get("background_mood") in ms else ms[0])
    if mood not in ms: bad("unknown sky", mood); return False
    if DRY: dry("would build an equirect panorama from skies/%s, copy it to ~/lainframe/sky/, edit steamvr.vrsettings (backup .bak-lainframe) and SIGKILL steamvr.service so it restarts with it" % mood); return True
    if not yes("Take the headset off or stop any game now. Restart SteamVR on the headset?", True): return True
    try: deploy.set_background(cfg, mood)
    except RuntimeError as e: bad(e); return False
    cfg["skybox_as_steamvr_background"] = True; cfg["background_mood"] = mood; save(cfg)
    ok("background set; SteamVR on the headset is restarting (about 20 seconds)")
    return True


def find_claude():
    for n in ("claude", "claude.exe", "claude.cmd"):
        p = shutil.which(n)
        if p: return p
    for p in (os.path.expandvars(r"%USERPROFILE%\.local\bin\claude.exe"), os.path.expandvars(r"%APPDATA%\npm\claude.cmd"),
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\claude\claude.exe")):
        if os.path.exists(p): return p
    return None


def claude_works(cfg):
    exe = find_claude()
    if not exe: return False, "not installed"
    try:
        r = subprocess.run([exe, "-p", "--model", cfg["voice"]["chat_model"], "Reply with exactly one word: ready"],
                           capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace",
                           cwd=config.CONFIG_DIR if os.path.isdir(config.CONFIG_DIR) else None)
    except (subprocess.TimeoutExpired, OSError) as e: return False, str(e)
    out = (r.stdout or "").strip()
    return ("ready" in out.lower()), (out or r.stderr.strip())[-200:]


def venv_has(mods):
    r = subprocess.run([config.venv_python(), "-c", "import " + ", ".join(mods)], capture_output=True, text=True)
    return r.returncode == 0, (r.stderr.strip().splitlines() or [""])[-1][-300:]


def step_voice(cfg):
    info("Optional: talk to Lain. Click her (or say \"Wake up, Lain\" if you turn that on), speak, and she answers")
    info("in her own voice with her lips moving. Speech-to-text (whisper) and her voice (Kokoro) run on THIS PC;")
    info("her answers come from Claude Code (Anthropic's assistant CLI), which needs a Claude account.")
    if not yes("Set up voice?", True):
        cfg["voice"]["enabled"] = False; save(cfg); return True
    v = cfg["voice"]
    # a. Claude Code
    print("\n  %sa. Claude Code%s" % (B, X))
    if DRY: dry("would check `claude --version`, offer to install it and to log in, then ask it one test question")
    else:
        if not find_claude():
            info("Claude Code isn't installed. The official installer is a one-line command in PowerShell:")
            info("    irm https://claude.ai/install.ps1 | iex")
            if yes("Open a PowerShell window that runs it now?", True):
                subprocess.Popen(["powershell", "-NoExit", "-NoProfile", "-Command", "irm https://claude.ai/install.ps1 | iex"],
                                 creationflags=NEW_CONSOLE)
                wait_enter("When that window says it's installed, press Enter here")
        if not find_claude():
            bad("Claude Code still isn't found. Install it (see https://claude.com/claude-code), then run setup --step 8."); return False
        ok("Claude Code:", find_claude())
        good, msg = claude_works(cfg)
        if not good:
            info("Claude Code needs you to log in once. A window opens running `claude`: follow its login steps in")
            info("your browser, then type /exit in that window. (Lain Brain never sees your account or tokens.)")
            wait_enter("Press Enter to open it")
            subprocess.Popen(["cmd", "/k", find_claude()], creationflags=NEW_CONSOLE, cwd=os.path.expanduser("~"))
            wait_enter("Logged in and typed /exit? Press Enter")
            good, msg = claude_works(cfg)
        if good: ok("Claude answers")
        else: bad("Claude didn't answer the test question:", msg); info("Fix the login, then run setup --step 8."); return False
    # b. whisper + c. Kokoro
    print("\n  %sb. Speech-to-text (whisper.cpp, ~150 MB) and c. Lain's voice (Kokoro, ~340 MB)%s" % (B, X))
    if DRY: dry("would download", assets.WHISPER_ZIP, assets.WHISPER_MODEL, "and", ", ".join(assets.KOKORO.values()))
    else:
        try:
            assets.whisper(cfg); ok("whisper:", v["whisper_exe"])
            assets.kokoro(cfg); ok("Kokoro:", v["kokoro_dir"])
        except RuntimeError as e: bad(e); info("Run setup --step 8 again to resume."); return False
        save(cfg)
        good, e = venv_has(["kokoro_onnx", "soundfile", "phonemizer", "espeakng_loader", "numpy"])
        if good: ok("voice Python packages")
        else: bad("voice Python packages missing:", e); info("Close this window and double-click LainBrain.bat again (it reinstalls them)."); return False
    # d. name, wake phrase
    print("\n  %sd. About you%s" % (B, X))
    cfg["user_name"] = ask("What should Lain call you? (a first name or nickname; Enter = no name)", cfg.get("user_name", ""))
    info("Optional: \"Wake up, Lain\" starts a conversation without clicking. While she's on the open menu and idle,")
    info("the headset sends short bursts of sound to THIS PC for whisper to check (nothing leaves your network).")
    v["wake_phrase"] = yes("Turn on the wake phrase?", bool(v.get("wake_phrase")))
    info("Lain can also DO things you ask for, live, while you watch in the headset: move or resize herself, change the")
    info("sky or the weather, fix a setting. For that she runs commands on this PC and on the headset through Claude Code.")
    info("Destructive commands (deleting folders, resets, shutdowns, reading your SSH keys) stay blocked, and she asks out")
    info("loud before anything she can't undo. Say no and she only talks.")
    v["hands"] = yes("Let Lain change things on your PC and headset? (recommended)", v.get("hands", True) is not False)
    v["enabled"] = True; save(cfg)
    # e. test
    print("\n  %se. Test%s" % (B, X))
    name = cfg["user_name"]; line = "Hello%s. I'm here. I'm always here." % ((", " + name) if name else "")
    if DRY: dry("would speak:", line); return True
    wav = os.path.join(config.DATA_DIR, "voice_test.wav")
    info("Lain says a test line through your PC speakers (the first time takes ~20 s to load her voice) ...")
    stop_matching(["tts\\lain_say.py"], quiet=True)                   # a running helper keeps old voice settings
    r = subprocess.run([config.venv_python(), os.path.join(HERE, "tts", "lain_say.py"), "--local", "--no-lips", line, wav],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(wav): bad("her voice failed:", (r.stderr or r.stdout)[-400:]); return False
    try:
        import winsound; winsound.PlaySound(wav, winsound.SND_FILENAME)
    except Exception as e: warn("couldn't play it here (%s); the file is %s" % (e, wav))
    if not yes("Did you hear her?", True):
        warn("Check the PC's sound output. The voice file is", wav, "- the voice still works on the headset.")
    ok("voice is set up. Lain remembers things you tell her in", config.MEMORY)
    return True


def shortcut(create):
    if DRY: dry(("would create " if create else "would remove ") + STARTUP_LNK); return
    if not create:
        if os.path.exists(STARTUP_LNK): os.remove(STARTUP_LNK)
        return
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); $s.TargetPath='{t}'; $s.Arguments='\"{a}\" run --quiet';"
          " $s.WorkingDirectory='{w}'; $s.WindowStyle=7; $s.Description='Lainframe Brain'; $s.Save()").format(
        lnk=STARTUP_LNK.replace("'", "''"), t=config.venv_python(True).replace("'", "''"),
        a=os.path.join(HERE, "lain_brain.py").replace("'", "''"), w=config.ROOT.replace("'", "''"))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError("couldn't create the shortcut: " + r.stderr[-300:])


def step_autostart(cfg):
    info("Optional: start Lain Brain (in the background, no window) every time you log in to Windows, so you")
    info("never have to remember to double-click LainBrain.bat before putting the headset on.")
    want = yes("Start Lain Brain with Windows?", bool(cfg.get("autostart")))
    try: shortcut(want)
    except RuntimeError as e: bad(e); return False
    cfg["autostart"] = want; save(cfg)
    ok("autostart", "on (%s)" % STARTUP_LNK if want else "off")
    return True


def step_doctor(cfg):
    if DRY: dry("would run every health check (lain_brain.py doctor)")
    else: doctor(cfg)
    closing()
    return True


def closing():
    print("""
  %sHow to use it from now on:%s
    1. Start Lain Brain BEFORE you put the headset on: double-click LainBrain.bat. It starts in the background
       (the window closes by itself).%s
    2. Then put the headset on and connect to your PC with Steam Link (Remote PC / stream from your PC).
    3. Open the Steam menu: Lain is there, above it.%s
  Problems? In the Lainframe folder, right-click an empty spot > "Open in Terminal" and type:  cmd /c LainBrain.bat doctor
""" % (G, X, "" if not config.load().get("autostart") else "\n       (You turned on autostart, so this already happens when you log in.)",
       "" if not config.load()["voice"]["enabled"] else " Click her (point and pull the trigger) and talk."))


STEP_FUNCS = {"welcome": step_welcome, "prereqs": step_prereqs, "headset": step_headset, "art": step_art,
              "extras": step_extras, "deploy": step_deploy, "background": step_background, "voice": step_voice,
              "autostart": step_autostart, "doctor": step_doctor}


def setup(only=None):
    cfg = config.load()
    print("\n%sLain Brain setup%s   %s" % (B, X, "(dry run: nothing is downloaded, sent or saved)" if DRY else ""))
    done = cfg["setup"]["done"]
    steps = config.STEPS
    if only:
        idx = [only - 1]
    else:
        first = next((i for i, k in enumerate(steps) if k not in done), None)
        if done:
            for i, k in enumerate(steps, 1): info("%s %2d. %s" % ("[x]" if k in done else "[ ]", i, STEP_TITLES[k]))
        if first is None:
            info("Setup is complete.")
            a = ask("Type a step number to redo it, or press Enter to just run the final check", "")
            idx = [int(a) - 1] if a.isdigit() and 1 <= int(a) <= len(steps) else [len(steps) - 1]
        else:
            if done:
                a = ask("Press Enter to continue with step %d, or type a step number to start there" % (first + 1), "")
                if a.isdigit() and 1 <= int(a) <= len(steps): first = int(a) - 1
            idx = list(range(first, len(steps)))
    for i in idx:
        key = steps[i]
        if key in done and not only and i != idx[0] and key not in ("doctor",):
            info("\n  Step %d (%s) is already done." % (i + 1, STEP_TITLES[key]))
            if not yes("Do it again?", False): continue
        header(i + 1, key)
        try: good = STEP_FUNCS[key](cfg)
        except KeyboardInterrupt: print(); warn("stopped. Run LainBrain.bat again to continue."); return 1
        except Exception as e:
            bad("unexpected problem in this step: %r" % (e,)); good = False
        if good:
            mark(cfg, key); cfg = config.load() if not DRY else cfg
            if key == "doctor" and not DRY and config.is_set_up(cfg) and yes("Start Lain Brain now (in the background)?", True):
                return run()
        else:
            print(); warn("Step %d isn't finished. Fix what it says above, then run LainBrain.bat again:" % (i + 1))
            info("it continues right here.")
            return 1
    return 0


# ---------------- background processes
def our_processes():
    """[(pid, commandline)] of python/powershell processes running files from this repo's brain folder."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe' or Name='powershell.exe'\" | "
          "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30,
                           creationflags=frame.NW)
        data = json.loads(r.stdout or "[]")
    except (subprocess.TimeoutExpired, ValueError, OSError): return []
    if isinstance(data, dict): data = [data]
    me = os.getpid(); h = HERE.lower()
    return [(d["ProcessId"], d["CommandLine"]) for d in data
            if d.get("CommandLine") and h in d["CommandLine"].lower() and d["ProcessId"] != me and "lain_brain.py" not in d["CommandLine"]]


PARTS = [("voice bridge", "bridge.ps1"), ("PC game watcher", "pcgame_watch.py"), ("headset-on launcher", "wear_launch.py"),
         ("wake phrase", "lain_wake.py"), ("voice helper", "lain_say.py")]


def running():
    procs = our_processes(); out = {}
    for name, f in PARTS: out[name] = [p for p, c in procs if f in c]
    return out


def wanted(cfg):
    w = {"PC game watcher": [config.venv_python(True), os.path.join(HERE, "pcgame_watch.py")]}
    if cfg["extras"]["worn"]: w["headset-on launcher"] = [config.venv_python(True), os.path.join(HERE, "wear_launch.py")]
    if cfg["voice"]["enabled"]:
        w["voice bridge"] = ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
                             "-File", os.path.join(HERE, "bridge.ps1")]
        if cfg["voice"].get("wake_phrase"): w["wake phrase"] = [config.venv_python(True), os.path.join(HERE, "wake", "lain_wake.py")]
    return w


def run(quiet=False):
    cfg = config.load()
    if not config.is_set_up(cfg):
        if not quiet: warn("Lainframe isn't set up yet. Starting setup ..."); return setup()
        return 1
    have = running()
    for name, cmd in wanted(cfg).items():
        if have.get(name): continue
        subprocess.Popen(cmd, creationflags=BG_FLAGS, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=config.ROOT)
    if quiet: return 0
    time.sleep(2)
    status(cfg, check_headset=False)
    print("\n  %sLain Brain is running in the background.%s Now put the headset on and connect to this PC with Steam Link." % (G, X))
    return 0


def stop_matching(files, quiet=False):
    n = 0
    for pid, cmd in our_processes():
        if any(f in cmd for f in files):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True); n += 1
    if not quiet: ok("stopped %d background process%s" % (n, "" if n == 1 else "es"))


def stop():
    stop_matching([f for _, f in PARTS]); return 0


def status(cfg=None, check_headset=True):
    cfg = cfg or config.load()
    print("\n%sLain Brain status%s" % (B, X))
    info("config:   ", config.CONFIG, "" if config.exists() else "(not created yet)")
    info("headset:  ", cfg["headset"]["host"] or "(not set)", "user", cfg["headset"]["user"])
    ex = [k for k in ("guard", "worn", "mic") if cfg["extras"][k]] + (["brightness"] if cfg["extras"]["brightness"] else [])
    info("extras:   ", ", ".join(ex) or "none")
    info("voice:    ", ("on, models %s / %s" % (cfg["voice"]["chat_model"], cfg["voice"]["model"])) if cfg["voice"]["enabled"] else "off")
    info("setup:    ", "%d of %d steps done" % (len([s for s in cfg["setup"]["done"] if s in config.STEPS]), len(config.STEPS)))
    have = running(); want = wanted(cfg)
    for name, _ in PARTS:
        if name == "voice helper":
            if have[name]: info("  %-20s running" % name)
            continue
        if have[name]: ok("%-20s running" % name)
        elif name in want: warn("%-20s not running" % name)
        else: info("  %-20s off" % name)
    if check_headset:
        good, msg = frame.reachable(cfg)
        (ok if good else warn)("headset:", msg)
    return 0


# ---------------- doctor
def doctor(cfg=None):
    cfg = cfg or config.load()
    print("\n%sLain Brain doctor%s" % (B, X))
    reds = 0
    def check(good, what, fix=""):
        nonlocal reds
        if good is True: ok(what)
        elif good is None: warn(what + (("  -> " + fix) if fix else ""))
        else: bad(what + (("  -> " + fix) if fix else "")); reds += 1
    check(sys.version_info >= (3, 12), "Python %d.%d" % sys.version_info[:2], "install Python 3.12+ from python.org")
    g, e = venv_has(["PIL", "numpy"]); check(g, "Python packages", "double-click LainBrain.bat (reinstalls them): " + e)
    check(all(shutil.which(x) for x in ("ssh", "scp")), "OpenSSH client", "Settings > System > Optional features > OpenSSH Client")
    check(config.exists(), "config file " + config.CONFIG, "run setup")
    key = config.path(cfg["headset"]["ssh_key"]); check(os.path.exists(key), "ssh key " + key, "setup --step 3")
    st = assets.art_state(cfg)
    check(st["clips_grok"][0] > 0 or None, "art on this PC: %d clip files, %d baked, %d sky files, %d weather files" % tuple(st[k][0] for k in ("clips_grok", "clips_baked", "skies", "weather")),
          "setup --step 4 (only needed to install/update the headset)")
    reach, msg = frame.reachable(cfg)
    if not reach:
        check(None, "headset: " + msg, "turn it on, keep it awake and on the same network; the address is found again automatically")
    else:
        check(True, "headset: " + msg)
        facts, raw = deploy.verify(cfg)
        for s in deploy.SERVICES:
            f = facts.get(s, {}); check(f.get("enabled") == "enabled", "%s %s" % (s, f.get("enabled", "missing")), "LainBrain.bat deploy")
        for k, s in deploy.EXTRA_SERVICES.items():
            on = facts.get(s, {}).get("enabled") == "enabled"
            if cfg["extras"][k] or on: check(on == bool(cfg["extras"][k]), "extra %s: %s on the headset, %s in config" % (k, "on" if on else "off", "on" if cfg["extras"][k] else "off"), "LainBrain.bat deploy --no-art")
        check(bool(facts.get("openvr")), "OpenVR library link on the headset", "LainBrain.bat deploy --no-art")
        rc = {k: int(facts.get(k, "0") or 0) for k in ("clips", "baked", "skies", "weather")}
        lc = {"clips": st["clips_grok"][0], "baked": st["clips_baked"][0], "skies": st["skies"][0], "weather": st["weather"][0]}
        for k in rc:
            check(rc[k] > 0 and (lc[k] == 0 or rc[k] == lc[k]) or (None if rc[k] > 0 else False),
                  "art on the headset (%s): %d files%s" % (k, rc[k], "" if lc[k] in (0, rc[k]) else ", PC has %d" % lc[k]), "LainBrain.bat deploy")
        info("  SteamVR on the headset: %s, streaming from this PC: %s" % (facts.get("steamvr", "?"), "yes" if facts.get("streaming") == "1" else "no"))
        if facts.get("streaming") != "1": info("  (Lain only shows during a stream from this PC; that's expected when you're not in VR.)")
    v = cfg["voice"]
    if v["enabled"]:
        check(bool(find_claude()), "Claude Code", "install it, then setup --step 8")
        for k in ("whisper_exe", "whisper_model"): check(os.path.exists(config.path(v[k])), "whisper " + k.split("_")[1], "setup --step 8")
        check(all(os.path.exists(os.path.join(config.path(v["kokoro_dir"]), f)) for f in assets.KOKORO), "Kokoro voice files", "setup --step 8")
        g, e = venv_has(["kokoro_onnx", "soundfile", "phonemizer", "espeakng_loader"]); check(g, "voice Python packages", "double-click LainBrain.bat: " + e)
    else: info("  voice: off (setup --step 8 turns it on)")
    have = running()
    for name in wanted(cfg):
        check(bool(have.get(name)) or None, "%s %s" % (name, "running" if have.get(name) else "not running"), "double-click LainBrain.bat (or: LainBrain.bat run)")
    check(os.path.exists(STARTUP_LNK) == bool(cfg.get("autostart")) or None,
          "start with Windows: %s" % ("on" if os.path.exists(STARTUP_LNK) else "off"), "setup --step 9")
    print("\n  %s" % ("%sAll good.%s" % (G, X) if not reds else "%s%d problem%s above.%s" % (R, reds, "" if reds == 1 else "s", X)))
    return 1 if reds else 0


# ---------------- uninstall
def uninstall():
    cfg = config.load()
    print("\n%sUninstall Lainframe%s" % (B, X))
    if not yes("Remove Lainframe from the headset (services, files, the SteamVR background change, Lainframe's key)?", False):
        info("nothing changed"); return 0
    stop()
    reach, msg = frame.reachable(cfg)
    if reach:
        info(deploy.uninstall_headset(cfg, remove_key=True)); ok("headset cleaned up")
    else:
        warn("can't reach the headset (%s). Turn it on and run uninstall again to clean it up." % msg)
        if not yes("Continue with the PC side anyway?", False): return 1
    try: shortcut(False); ok("autostart removed")
    except Exception as e: warn(e)
    if yes("Delete the downloaded art, voice models and logs on this PC (%s)?" % config.DATA_DIR, True):
        shutil.rmtree(config.DATA_DIR, ignore_errors=True); ok("removed", config.DATA_DIR)
    if yes("Delete your settings AND Lain's memories of you (%s)?" % config.CONFIG_DIR, False):
        shutil.rmtree(config.CONFIG_DIR, ignore_errors=True); ok("removed", config.CONFIG_DIR)
    else:
        c = config.load(); c["setup"]["done"] = [s for s in c["setup"]["done"] if s in ("welcome", "prereqs")]
        c["skybox_as_steamvr_background"] = False; c["autostart"] = False
        if config.exists(): config.save(c)
    key = config.path(cfg["headset"]["ssh_key"])
    if os.path.exists(key) and yes("Delete Lainframe's ssh key on this PC (%s)?" % key, True):
        for f in (key, key + ".pub"):
            try: os.remove(f)
            except OSError: pass
    info("Last bit: delete the Lainframe folder itself (%s) whenever you like." % config.ROOT)
    return 0


def main():
    ap = argparse.ArgumentParser(prog="LainBrain", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("setup", help="step-by-step setup (resumable)")
    s.add_argument("--step", type=int, choices=range(1, len(config.STEPS) + 1), help="run only this step")
    s.add_argument("--dry-run", action="store_true", help="walk the steps without network/ssh/saving")
    r = sub.add_parser("run", help="start the background parts"); r.add_argument("--quiet", action="store_true")
    sub.add_parser("stop", help="stop the background parts")
    sub.add_parser("status", help="show configuration and what's running")
    d = sub.add_parser("deploy", help="push to the headset and reinstall"); d.add_argument("--no-art", action="store_true")
    sub.add_parser("doctor", help="health check")
    sub.add_parser("uninstall", help="remove Lainframe from the headset (and optionally the PC)")
    a = ap.parse_args()
    cmd = a.cmd or ("run" if config.is_set_up() else "setup")
    rc = dispatch(a, cmd)
    # double-clicked (LainBrain.bat): keep the window readable unless Lain Brain just went to the background
    if os.environ.get("LAINBRAIN_BAT") and sys.stdin and sys.stdin.isatty() and not (cmd == "run" and rc == 0 and config.is_set_up()):
        try: input("\n  Press Enter to close this window ")
        except EOFError: pass
    return rc


def dispatch(a, cmd):
    global DRY
    try:
        if cmd == "setup":
            DRY = a.dry_run if a.cmd else False
            return setup(getattr(a, "step", None))
        if cmd == "run": return run(getattr(a, "quiet", False))
        if cmd == "stop": return stop()
        if cmd == "status": return status()
        if cmd == "doctor": return doctor()
        if cmd == "uninstall": return uninstall()
        if cmd == "deploy":
            cfg = config.load()
            facts, raw = deploy.deploy(cfg, art=not a.no_art); print(raw)
            return 0
    except KeyboardInterrupt:
        print(); warn("stopped"); return 1
    except RuntimeError as e:
        bad(e); return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
