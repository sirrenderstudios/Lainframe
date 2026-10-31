#!/bin/bash
# Lainframe guard (opt-in extra, lainframe-guard.service): keeps the Frame booting into the Steam UI (game mode) after
# SteamOS updates. Runs once per login as a user service (it lives in ~, so updates don't wipe it) and checks every 20 s
# for 10 minutes, then exits.
#  1. gamescope (the Steam UI) crash-looping: at least CRASHES coredumps within 2 min, counted only since this guard
#     started (older crashes never count), and the latest one under 40 s old (still looping, not a past burst).
#     Known cause: FrameColor's vkBasalt Vulkan layer (SteamOS 0.3.0 -> 0.4.5: "Assertion !modifiers.empty() failed").
#     Fix, once per boot: disable that layer if present (rename, reversible), restart SteamVR, switch back to game mode.
#     This is the ONLY case where the guard restarts SteamVR.
#  2. the SteamOS version changed since the last boot and the login mode was left on desktop -> back to game mode.
#  3. logs every boot's SteamOS version and the state of the Lainframe services.
# Log: ~/.local/state/lainframe/guard.log
STATE="$HOME/.local/state/lainframe"; mkdir -p "$STATE"
LOG="$STATE/guard.log"; VERF="$STATE/guard.version"
LAYER="$HOME/.local/share/framecolor/layer/vkBasalt.json"
CRASHES=3
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
[ -f "$LOG" ] && [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt 524288 ] && mv -f "$LOG" "$LOG.1"

ver=$(. /etc/os-release; echo "$VERSION_ID $BUILD_ID"); old=$(cat "$VERF" 2>/dev/null)
log "boot: SteamOS $ver (last seen: ${old:-none})"
updated=0; [ -n "$old" ] && [ "$old" != "$ver" ] && updated=1
echo "$ver" > "$VERF"

since=$(date '+%F %T')                    # only crashes after this guard started count
fixed=0; i=0
while [ $i -lt 30 ]; do
    i=$((i + 1)); sleep 20
    win=$(date -d '-2min' '+%F %T'); [[ "$win" < "$since" ]] && win=$since
    crashes=$(coredumpctl list --no-pager --no-legend -S "$win" /usr/bin/gamescope 2>/dev/null | grep -c .)
    recent=$(coredumpctl list --no-pager --no-legend -S "$(date -d '-40sec' '+%F %T')" /usr/bin/gamescope 2>/dev/null | grep -c .)
    if [ $fixed -eq 0 ] && [ "$crashes" -ge $CRASHES ] && [ "$recent" -ge 1 ]; then
        log "gamescope crash loop: $crashes crashes in 2 min (since guard start), still crashing"
        if [ -f "$LAYER" ]; then mv "$LAYER" "$LAYER.disabled"; log "FrameColor Vulkan layer disabled (undo: mv $LAYER.disabled $LAYER)"; fi
        systemctl --user kill --signal=SIGKILL steamvr.service; sleep 10
        steamosctl set-default-login-mode game; steamosctl switch-to-game-mode; fixed=1
        log "SteamVR restarted, switched to game mode"
        continue
    fi
    if [ $updated -eq 1 ] && grep -q plasma /etc/sddm.conf.d/zz-steamos-autologin.conf 2>/dev/null; then
        log "update left the login mode on desktop: back to game mode"
        steamosctl set-default-login-mode game; steamosctl switch-to-game-mode; updated=0
    fi
    if [ $i -eq 6 ]; then
        s=""; for u in steamvr lainframe-lain lainframe-sky lainframe-worn lainframe-mic; do s="$s$u=$(systemctl --user is-active $u.service) "; done
        log "services: $s"
    fi
done
log "done (10 min after login)"
