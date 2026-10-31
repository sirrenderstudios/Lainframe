# Changelog

All notable changes to Lainframe. Format loosely follows [Keep a Changelog](https://keepachangelog.com/);
versions follow [SemVer](https://semver.org/).

## [0.1.0] - unreleased

First public release.

### Lain (headset, only while streaming from a PC)
- Animated 2D Lain sits on the top edge of the Steam menu, centred. She follows the curved menu and rides the dock
  bar when you open other menus.
- Quiet idle life: breathing, looking around, dozing, sleepier at night. She notices you when you come back after a
  while. She leans toward you if you move to her side.
- Attention by laser click or the optional "Wake up, Lain" phrase. Her eyes follow your head while she's listening.
- Thinking: eyes open for the first 15 seconds. After that, wires come up from behind the menu and clamp to her face
  while she works in the Wired.
- Voice answers with lip sync. Kokoro TTS, whisper word timings and phonemes drive the mouth shapes.
- Wired-blue colour with 80% opacity, drawn as one composited picture.
- GPU-texture overlay (surfaceless EGL + OpenGL). About 1 ms per frame with no memory growth, which avoids the
  SteamVR 0.4.5 overlay image leak.
- Completely off in standalone mode.

### The Wired (headset skybox)
- Live late-90s suburb street. Four moods follow the real clock (dawn/dusk, day, sunset, night) with slow crossfades.
- Random weather and life: drizzle, rain, downpours, lightning, black cats running along the wires, birds, a puddle
  that shows the Wired, and a rare red-shadow event.
- Hides during games and in room view (passthrough). The weather clock pauses while the sky is hidden.
- Flattened cube layers keep compositor cost around 5.4 ms.

### Lain Brain (PC)
- `LainBrain.bat`, a one-click entry point with a resumable setup wizard. It covers headset prerequisites, finding
  the headset, SSH key, art download and bake, opt-in extras, deploy, optional voice, autostart, and a health check.
- Voice bridge: Whisper speech to text, then Claude Code, then Kokoro voice plus a lip-sync track, sent back to the
  headset.
- `doctor` health check and `uninstall`.

### Opt-in extras (off by default)
- Boot guard: recovers from the Steam UI crash-loop after updates. It can restart SteamVR.
- Worn sensor: optional minimum brightness when the headset is off your head and maximum when you put it on.
- Mic: holds mic gain and adds an EQ to the stream that goes to the PC.
