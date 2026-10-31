# Troubleshooting

Start with the health check. It tests every part and tells you how to fix what's red:

```
LainBrain.bat doctor
```

The sections below cover the problems people actually hit.

---

## Lain doesn't show up

Go through these in order:

1. **Are you streaming from your PC?** Lain only exists during a Steam Link PC stream. In standalone mode she's off on
   purpose. A USB-C cable by itself is just a network link. Streaming starts when you connect from the headset's
   **Remote PC** tab, or when SteamVR starts on the PC.
2. **Is the Steam menu open?** She only shows while the menu is really open, and she pauses when it's closed.
3. **Did you start Lain Brain first?** Start `LainBrain.bat` on the PC **before** putting the headset on, then connect.
   She can appear without it, but voice won't work.
4. **Is her service running?** `LainBrain.bat doctor` checks it. On the headset, the service is `lainframe-lain`
   (systemd user service, started together with SteamVR).
5. Check `~/.local/state/lainframe/lain.log` (see [Logs](#reading-the-logs)).

## She floats in front of me instead of on the menu (first run)

On a fresh install she hasn't measured the menu yet. When she can't find any menu panel for a few seconds, she waits
in a spot in front of you. **Open the home Steam menu once.** She finds its curved top edge, moves onto it, and
remembers where that is relative to the dock bar. After that she follows you into other menus too.

## She's on the menu but tilted, or one shoulder looks further away

The menu fit needs ray hits across the menu's width. Close and reopen the menu while looking at its centre. If it
keeps happening after a SteamOS update, the menu panel may have changed. Please open an issue and attach `lain.log`.

---

## The Steam UI crash-loops after a SteamOS update or a hard power-off

**Symptom:** after an update (or after holding the power button), the Frame flickers between a black screen and the
Steam UI, or lands on the Linux desktop instead of game mode.

**Known cause:** the Steam UI compositor (gamescope) crashes over and over with
`Assertion !modifiers.empty() failed`. The known trigger is a **Vulkan layer from a colour mod** (vkBasalt-based)
that SteamVR loads. When SteamOS updates, the layer and the new compositor stop getting along. Lainframe doesn't
install any Vulkan layers itself.

**Fix by hand:**
1. In Desktop Mode, open Konsole.
2. Disable the colour mod's layer by renaming its `.json` file (for example, add `.disabled` to the end). Renaming is
   reversible.
3. Run `steamosctl set-default-login-mode game` then `steamosctl switch-to-game-mode`.

**Or let the optional boot guard handle it.** If you enabled it in the wizard, for 10 minutes after each login it
watches for repeated gamescope crashes. If it sees them, it disables that layer, restarts SteamVR, switches back to
game mode, and logs everything to `~/.local/state/lainframe/guard.log`, including how to undo the rename.
<!-- TODO(verify): final guard log filename once headset/extras/guard is finished (original wrote frame_guard.log). -->

## The sky still shows during a game, or covers room view

- **PC games:** the hide signal comes from Lain Brain's game watcher on the PC. Make sure Lain Brain is running.
- **Room view:** the sky watches SteamVR's own log for room view changes. If it doesn't hide, check
  `~/.local/state/lainframe/sky.log` for "room view" lines.
- **Weather looks "reset" after a game:** it shouldn't. The weather clock pauses while the sky is hidden. Weather is
  random, though, so a clear sky after a long session can just be the weather.

---

## She doesn't hear me, or the voice loop stalls

- **The mic went silent in every PC app after fiddling with audio:** Steam Link **closes its mic stream if it's ever
  left with no source**, even for a moment, and doesn't reopen it until the stream reconnects. **Disconnect and
  reconnect Steam Link.** (The optional mic extra always links the new source before unlinking the old one, so it
  avoids this.)
- **She hears the TV, or never hears you:** speech detection uses a loudness gate. Check the mic levels logged in
  `lain.log`. The mic extra (gain + EQ) helps with a quiet, dull-sounding mic.
- **No answer at all:** run `claude --version` on the PC and make sure Claude Code is logged in (run `claude` once in a
  terminal). Then check the bridge log.
- **She ends quietly without answering:** Whisper heard only silence ("Thank you", "Thanks for watching"...), which the
  bridge treats as nothing said. Speak a little louder or closer.

## The wireless adapter drops until I replug it

Some PC-side wireless adapters for the Frame drop out and only come back after a replug, with nothing in the
Windows event log. What helped:
- Turn **USB selective suspend** off in the Windows power plan (Power Options, then Advanced, then USB settings).
- In Device Manager, open the adapter, go to Power Management, and untick "Allow the computer to turn off this
  device".
- Give it airflow or a short USB extension cable. These adapters can throttle when they get hot.

Lainframe doesn't change these settings for you.

---

## SSH problems

- **The wizard can't find the headset:** the Frame and PC must be on the same network. On the headset, check that
  Developer Mode and SSH are both on (see the wizard's step 2), then enter the headset's IP by hand. You'll find it in
  the Frame's network settings.
- **"Permission denied (publickey)":** the key install didn't take. Re-run the wizard's headset step. It opens a
  window where you type the `steamos` password once.
- **"Connection refused":** sshd isn't running on the headset. In Desktop Mode → Konsole, run
  `sudo systemctl enable --now sshd`.
- **The IP changed** (new router, travel, a different adapter): re-run the wizard's "find the headset" step. It scans
  and updates the config.
- **Rolling your own commands from Windows:** use `ssh -n` for one-shot commands (otherwise Windows OpenSSH can hang),
  and pipe shell scripts through `tr -d '\r' | bash -s` (Windows line endings break bash).

---

## Reading the logs

**On the headset** (`~/.local/state/lainframe/`):

| File | What's in it |
|---|---|
| `lain.log` | Lain's player: when she found the menu, showed or hid, every state change, mic levels |
| `sky.log` | The Wired: mood changes, game hide/show, room view, weather events |
| `mic.log` | Mic extra (if enabled): gain corrections, EQ hooked to the stream |
| `guard.log` | Boot guard (if enabled): SteamOS version per boot, crash-loop fixes |
<!-- TODO(verify): confirm guard/worn log names once the extras are final. -->

From the PC, read the end of Lain's log with:
```
ssh -n steamos@<headset-ip> tail -n 50 ~/.local/state/lainframe/lain.log
```
Services: `systemctl --user status lainframe-lain lainframe-sky`.

**On the PC:** `LainBrain.bat doctor` prints where the bridge log is. Read it, but don't keep it open with a live
`tail -F`, because Windows file locking can stop the bridge from writing.
<!-- TODO(verify): exact bridge log location (likely under %APPDATA%\Lainframe or %LOCALAPPDATA%\Lainframe). -->

---

## Still stuck?

Open an issue with:
- the output of `LainBrain.bat doctor`,
- the last ~100 lines of `lain.log` / `sky.log`,
- your SteamOS version (Settings → System).

Check the logs for anything personal before you post them.
