# Make your own avatar

Lain is the first character, not the only one. Everything that makes her work (sitting on the Steam menu, following it,
the see-through Wired look, voice, lip sync, waking up when you open the menu) is a general system. The character is just
a folder of pictures plus a description of who they are. Swap those and you have your own companion in the Frame.

This is early. The tooling below works, but it's young; if something is confusing or breaks, please open an issue or a
discussion. That feedback is exactly what shapes the next version.

## Level 1: one picture (10 minutes)

You need one **transparent PNG** of your character, waist or chest up, standing on the bottom edge of the picture (the
bottom edge sits on top of the Steam menu; anything lower is hidden behind it). Lain's pictures are 820 x 832; any size
works as long as all your pictures match.

```
python art_pipeline/make_avatar.py --idle my_character.png --out my_avatar/clips_grok
```

Optional extra pictures make it feel alive, each one the same size as the first:

| Option | Shown when |
|---|---|
| `--listen` | you're talking to them |
| `--think` | they're working on your request (Lain's wires look) |
| `--talk` | they answer |
| `--sleep` | nobody has talked to them for a while |
| `--blink` | eyes closed: a short blink now and then |

The tool writes a character pack in exactly the format of Lain's library, so nothing else needs to change.

## Install it

1. Find your art folder: `LainBrain.bat status` prints it (default `%LOCALAPPDATA%\Lainframe\art`).
2. Rename Lain's `clips_grok` folder there (e.g. `clips_grok_lain`) so you can go back, and put your `clips_grok` in its place.
3. Run `LainBrain.bat deploy`. It bakes your pictures for the headset and installs them.

## Give them their own personality and voice

- **Who they are:** create `%APPDATA%\Lainframe\persona.md` and describe the character in plain sentences
  ("You are Kit, a cheerful robot fox who lives in my headset. You love bad puns..."). It replaces Lain's built-in
  character. Lines starting with `#` are ignored.
- **How they talk:** optional style bullets in `%APPDATA%\Lainframe\lain_personality.md` (one `- ` bullet per line);
  see `brain/voice/lain_personality.md` for Lain's.
- **Their voice:** `voice.voice_mix`, `voice.semitones` and `voice.speed` in `%APPDATA%\Lainframe\config.json` choose the
  Kokoro voice (e.g. `[["am_adam", 1.0]]` for a male voice, or a blend of two).

## Level 2: animation

Each clip is a folder of numbered frames (`000.png`, `001.png`, ...) plus its entry in `clips.json`:

```json
"rest_a": {"state": "idle", "frames": 120, "loop": false, "fps": 30, "w": 820, "h": 832, "holds": [1, 1, ...], "family": null}
```

`holds` = how many ticks (1/30 s) each frame stays up. Start from the pack `make_avatar.py` made and replace any clip
folder with real animation; keep the clip names (the player picks clips by name and state). Clips must start and end on
the same resting pose so any clip can follow any other.

## Level 3: lip sync and live eyes (advanced)

Lain's library shows how: talk loops have closed-mouth twins (`talk_0_A_lips`) with per-frame mouth sprites in
`<clip>/mouth/<shape>/NNN.png` for the shapes `closed small open A E I O U`, and `eyes.json` + `eyes/` hold iris sprites
so her eyes can follow you. Look at the Lain pack and `headset/lain/lain_player.py` (`mouth_sprite`, `eye_entry`). Without
these, everything still works; the mouth and eyes just stay as drawn.

## Share yours

Made one? Post it in Discussions with a picture. If enough people make characters, a proper character picker in Lain
Brain is next.

Please only share characters you have the right to share.
