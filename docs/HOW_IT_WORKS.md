# How it works

Lainframe is small, but getting an animated character to sit still and look right on a standalone VR headset took a
few detours. This page covers the parts that are interesting (or were painful) and why they're built the way they
are. File names refer to this repository.

```
  PC  ("Lain Brain")                                     Steam Frame (SteamOS, user services)
  ─────────────────────────────────                      ─────────────────────────────────────────────
  bridge.ps1  ◄── ssh tail of the clicks file ────────── lain/voice.py   (mic → wav, speech detection)
     │ scp wav                                           lain/lain_player.py  (Lain overlay, GL texture)
     ▼                                                    ▲   ▲
  whisper.cpp  → text                                     │   │ <id>.wav + <id>.vis.json + .done
  claude (Claude Code CLI, own session) → reply           │   │
  tts/lain_say.py (Kokoro) → wav                          │   │
  tts/lipsync.py (word timings + phonemes) → mouth track ─┘───┘ scp
  pcgame_watch.py → "a PC game is running" flag ───────► sky/skyclock.py + weather.py  (The Wired)
```

---

## 1. The overlay leak, and why Lain is an OpenGL texture

Lain is a 2D animation: a library of 30 fps clips (idle, listen, think, wires, talk, doze...) chained by pose, so a
clip never starts from the wrong pose. The obvious way to animate a SteamVR overlay is to hand it a new image file
every frame with `setOverlayFromFile`. On SteamOS 0.4.5 that's a trap:

- **Every `setOverlayFromFile` with a new image leaks about 3.5 MB inside `vrcompositor`.** The memory isn't freed when
  you destroy the overlay or quit your app. Only a SteamVR restart frees it. At animation rates that's on the order of
  100 MB per second: lag first, then crashes.
- **Reusing the same file path** (writing frame N into `frame.png` each time) doesn't leak, but the compositor caches
  by path, so it shows **stale frames**.
- **`setOverlayRaw`** (pushing raw pixels) avoids both problems but is far too slow (about 34 ms per call), and it
  started failing after a few hundred frames.

The fix is to own the texture. `lain_player.py` creates a **surfaceless EGL context** (`EGL_PLATFORM_SURFACELESS_MESA`,
desktop OpenGL through Mesa, no window), uploads each frame into a GL texture it keeps, and hands that texture to
SteamVR with **`setOverlayTexture`**. Result: about **1 ms per frame and zero memory growth**, however long she runs.

### One picture, not stacked layers

Lain is drawn in a see-through "Wired blue" at 80% opacity. At first her body, live eyes and lip-sync mouth were three
separate overlays, each 80% see-through. Where two of them overlapped, such as the mouth patch on her face, the
alphas stacked and showed a visibly brighter **box**.

Now body, eyes and mouth are drawn at full strength into **one framebuffer (FBO)**, and the overlay as a whole gets the
80% with `setOverlayAlpha`. Opacity is applied exactly once, so there are no seams or boxes. (The baked texels already
carry the alpha, so the composite divides it back out before the overlay re-applies it.)

### Pre-baked frames (`.rgbz`)

Decoding PNGs with Pillow on the headset for every frame costs real CPU. During setup the PC runs
`art_pipeline/bake_rgbz.py` over the whole clip library. Each frame gets the Wired colour grade and alpha applied, is
**cropped to its visible pixels**, and is stored as raw RGBA, zlib-compressed, with a tiny header
(`x0, y0, w, h, full_w, full_h`). On the headset, a frame is then just a zlib inflate of a small patch (a few ms on a
worker thread) placed at its crop offset. No Pillow per frame. With the menu open, the player idles at a fraction of a
percent of CPU.

---

## 2. Finding the curved Steam menu

Lain sits on the **top edge of the big Steam menu**, centred. The menu is a SteamVR overlay owned by the system
(`valve.steam.gamepadui.main`), but **its transform can't be read**. So it gets measured:

1. From your head, cast a fan of rays (yaw −100°…+100°, pitch −60°…+40°, every 5°) and ask SteamVR where each one hits
   that overlay (`computeOverlayIntersection`). Each hit returns a world point and the panel's **UV** coordinates.
2. Fit the panel as `world = O + u·U + v·V` by least squares over all hits: origin, "right" axis and "up" axis.

The catch is that **the home menu is curved**. A flat fit leans its right axis toward whichever side happened to get
more ray hits. The result was visibly tilted, with one of Lain's shoulders further away than the other. The fix is
one extra term:

```
world = O + u·U + v·V + (u − 0.5)²·B
```

The `(u − 0.5)²` term absorbs the bend, so `U` becomes the exact tangent at the menu's centre, and `O + 0.5·U + V` is
the top centre where she sits. (The bend term is only used when the hits span enough of the width to pin it down.
Otherwise the player falls back to the 3-term flat fit.) The fit is re-checked every few seconds and whenever the
menu moves.

### Other menus: ride the dock bar

SteamVR settings and other menus replace the home panel in the same place, but they **can't be found by name**. The
dock bar at the bottom stays, though, and **its** transform can be read cheaply. So whenever Lain is placed on the
home menu, the player remembers where she sits *relative to the dock bar*. When the home panel disappears but the bar
is still there, she rides the bar to the same spot. If no menu can be found at all for several seconds (on a fresh
install, for example), she waits in a spot in front of you until she sees the home menu once.

### Showing only when the menu is really open

`isDashboardVisible()` alone isn't trustworthy: some system UI reports "visible" while closed. Lain shows only when the
dashboard is visible **and** the menu panel is actually found. A nearly invisible click target shaped to her
silhouette takes the laser (black at alpha 1, which SteamVR's premultiplied blending makes invisible), so the laser
stops on her instead of passing through.

---

## 3. PC-stream-only lifecycle

Lain's services start with SteamVR, but she only **exists** while the Frame streams from a PC. The player looks for
the Steam Link VR process: a process whose executable (`/proc/<pid>/exe`) is `vrlink`. It matches the **exe, not the
process name**, because the thread name is something else. In standalone mode she creates nothing, renders nothing,
and uses no GPU. While the menu is closed she's paused at about 0% CPU.

---

## 4. Voice and lip sync

1. **Listening.** A laser click (or the optional "Wake up, Lain" phrase) starts the mic on the headset (`pw-record`,
   16 kHz mono). Simple speech detection ends the utterance after about 1.2 s of silence. The wav goes into a state
   folder, and a line goes into a "clicks" file.
2. **PC side.** The bridge holds an SSH `tail` on that file, fetches the wav, and transcribes it with **whisper.cpp**
   (`base.en`). Whisper invents "Thank you" / "Thanks for watching" on near-silence, so those count as nothing heard.
3. **Brain.** The text goes to **Claude Code** (`claude -p`) in its **own** saved session. It never uses `--continue`,
   which would grab whatever session is newest. Small talk can use a faster model, and real work a stronger one
   (`voice.chat_model` / `voice.model` in the config).
4. **Voice.** **Kokoro** (82M, ONNX on the CPU, roughly 8× real time) speaks the reply in a soft voice, pitched up
   slightly.
5. **Lip sync.** `tts/lipsync.py` takes the reply audio plus its text. whisper.cpp gives **word timings**, espeak-ng gives
   **phonemes**, and together they become a 30 fps track of mouth shapes (A, I, U, E, O, closed), gated by the audio's
   loudness. Without espeak it falls back to loudness only. Without any track, the player makes a synthetic one from the
   reply's length.
6. **Back to the headset.** The wav and the small mouth track go over scp, then a `.done` marker. The player swaps
   pre-drawn mouth sprites onto her talk frames in time with the audio, all inside the same one-picture composite.

**The wires.** While she thinks, her eyes stay open for the first 15 seconds. If the answer takes longer, wires rise
from behind the menu and clamp to her cheeks and temples. She closes her eyes and answers from the Wired, and the
wires let go when she's done.

---

## 5. The Wired (skybox)

SteamVR's own background is one still image that reloads only on restart. A sky that changes through the day has to
be **overlays**.

**Built in Blender, offline.** The street is procedural Blender code with a fixed random seed, so a re-render is
identical and a fix touches only what it's meant to. It's rendered with Cycles and Freestyle ink lines. Freestyle
can't do panoramas, so each mood is rendered as **six 90° cube faces** at eye height (1.7 m). Post-processing adds
distance haze and a per-mood colour grade, and cuts the extra layers: open-sky mask, foreground, wet road, red-event
layer.

**On the headset** (`sky/skyclock.py`). Each sky is a cube of six overlay quads about 150 m out, at the lowest sort
order so it's under the menu and Lain. Two cubes (A and B) crossfade by overlay alpha over about 40 minutes around
each schedule time. When a fade finishes, the hidden cube loads the next mood. Overlay state (alpha, sort order,
visibility) is only sent when it changes, which keeps the traffic to vrserver small.

**Flattened faces for performance.** Originally each face was a sky layer plus a transparent foreground layer
(buildings, wires, road), which meant two full-screen blended cubes. `art_pipeline/sky_flatten.py` bakes the
foreground and wet road onto the sky (`flat_<face>.png`), giving **one opaque cube**. Compositor GPU time dropped from
about 7.7–8.4 ms to about **5.4 ms** per frame.

**Weather and life** (`sky/weather.py`) sit in front of the cube in a fixed sort order: rain, lightning (its own layer: the open sky cut out of the skyline, faces that meet without overlapping, a soft rise-and-fade with at most two pulses),
black cats running the full length of a random wire (a fixed number per hour, at random minutes), birds on
random curved paths (some cross the whole sky, some land on a wire for a while and leave), a lamp that buzzes, a puddle
that briefly shows the Wired, and a rare red-shadow event. Nothing in it is a full-sky tinted veil. One early version
had one, and in the headset it drew harsh white bands, so every layer is checked in a real headset capture.

**Getting out of the way.**
- **Games:** the sky hides while a VR app runs. On the headset it watches for scene apps that Steam started. For PC
  games, the PC's `pcgame_watch.py` reads SteamVR's log and sets a flag on the headset.
- **Room view:** the sky cubes sit over the passthrough camera view, so `RoomView` follows SteamVR's
  `vrserver.txt` log for `currentRoomViewRenderingMode` changes (new bytes only) and hides the sky and weather while
  the camera view is on.
- **The weather clock pauses while hidden.** Without that, you'd leave a drizzle, play for an hour, and come back to a
  dry sky. Now you come back to the weather you left.

---

## Lessons that apply to any Frame overlay project

- Don't animate with `setOverlayFromFile` on SteamOS 0.4.5: use a GL texture and `setOverlayTexture`.
- Apply overlay alpha once. Stacked see-through overlays show their overlaps.
- System panels often have no readable transform. Ray-cast them with `computeOverlayIntersection` and fit, and model
  the curve.
- One re-textured overlay flickers, and so does a naive show-new/hide-old swap. Either own the texture or keep the old
  frame up for one more tick.
- From Windows, use `ssh -n` for one-shot commands (otherwise it can hang forever), and pipe shell scripts through
  `tr -d '\r' | bash -s`.
- Keep everything in `~`: SteamOS updates reset `/etc`, not your home folder.
