#!/bin/bash
# Lainframe headset uninstaller. Runs ON the Steam Frame; asks nothing. Stops and removes every lainframe service and
# its symlinks, then deletes ~/lainframe, ~/.config/lainframe and ~/.local/state/lainframe. SteamVR settings are not
# touched (the PC app restores its own background change).
# usage: bash ~/lainframe/uninstall.sh
set -u
UNITS="$HOME/.config/systemd/user"
say() { echo "lainframe: $*"; }

for u in lainframe-lain lainframe-sky lainframe-guard lainframe-worn lainframe-mic; do
    n="$u.service"
    if [ -e "$UNITS/$n" ] || [ -L "$UNITS/steamvr.service.wants/$n" ] || [ -L "$UNITS/default.target.wants/$n" ]; then
        systemctl --user stop "$n" 2>/dev/null          # mic: its ExecStop puts the PC stream back on the plain mic
        systemctl --user disable "$n" 2>/dev/null
        rm -f "$UNITS/$n" "$UNITS/steamvr.service.wants/$n" "$UNITS/default.target.wants/$n"
        say "service removed: $n"
    fi
done
systemctl --user daemon-reload 2>/dev/null; systemctl --user reset-failed 2>/dev/null
# the "Wake up, Lain" listener runs over the PC's ssh link, not as a service
pkill -f "lainframe/lain/wake_link\.py" 2>/dev/null && say "wake listener stopped"
for d in "$HOME/lainframe" "$HOME/.config/lainframe" "$HOME/.local/state/lainframe"; do
    if [ -e "$d" ]; then rm -rf "$d"; say "deleted $d"; fi
done
L="$HOME/.local/share/framecolor/layer/vkBasalt.json"
[ -f "$L.disabled" ] && say "note: the guard had disabled FrameColor's Vulkan layer (it crash-looped the Steam UI); left as is. Undo: mv $L.disabled $L"
say "uninstalled"
