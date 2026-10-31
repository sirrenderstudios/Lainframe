# Credits

Lainframe is a small layer on top of a lot of other people's work. Thank you.

## Software Lainframe uses

| Project | What for | License |
|---|---|---|
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | Lain's voice (text to speech, local, on the PC's CPU) | Apache-2.0 (code and weights) |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) + the `ggml-base.en` model | Speech to text, the optional wake phrase, and word timings for lip sync | MIT |
| [eSpeak NG](https://github.com/espeak-ng/espeak-ng) (if installed) | Phonemes for the lip-sync mouth shapes | GPL-3.0 (used as a separate program, not bundled) |
| [Pillow](https://python-pillow.org/) | Image decoding on the headset and art baking on the PC | MIT-CMU (HPND) |
| [pyopenvr](https://github.com/cmbruns/pyopenvr) | Python bindings for the OpenVR overlay API on the headset | BSD-3-Clause |
| [OpenVR](https://github.com/ValveSoftware/openvr) (`libopenvr_api`) | The overlay API itself | BSD-3-Clause |
| [PipeWire](https://pipewire.org/) filter-chain module | The optional mic EQ extra (it uses the module that ships with SteamOS) | MIT |
| [Mesa](https://mesa3d.org/) EGL/OpenGL | Surfaceless GL context that uploads Lain's textures (part of SteamOS) | MIT |
| [Claude Code](https://claude.com/claude-code) by Anthropic | Lain's brain: the optional voice conversations run through your own Claude Code login | Anthropic terms (not bundled) |
| [Blender](https://www.blender.org/) | Rendering "The Wired" skybox cube faces (Cycles + Freestyle), offline | GPL (used as a tool, not bundled) |
| [onnxruntime](https://onnxruntime.ai/) | Runs Kokoro on the CPU | MIT |

## Coexists with / inspired by

The Steam Frame homebrew community made the headset fun to tinker with. Lainframe runs alongside community tools
like **Frame Perf Overlay**, **OVR Advanced Settings**, colour mods, mic tuners and face-tracking modules. Thanks to
everyone who documented SteamOS on the Frame: the overlay API notes, systemd user services and Steam Link
streaming quirks.

## The character

Lain Iwakura is from *Serial Experiments Lain*. See [ART_NOTICE.md](ART_NOTICE.md). This is a fan project made out
of love for the show.

- `tools/frame_vrshot.py` comes from [saphid/frame-control](https://github.com/saphid/frame-control) (MIT); its licence header is kept in the file.
