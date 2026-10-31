#!/bin/bash
# Lainframe headset installer. Runs ON the Steam Frame (user steamos), normally started by the PC app
# (brain/deploy.py) after it has copied headset/ to ~/lainframe. Safe to run again: it only changes what differs.
#
# usage: bash ~/lainframe/install.sh [--extras guard,worn,mic | --extras none] [--brightness on|off] [--no-restart]
#   --extras      which opt-in extras to have enabled; every extra NOT listed is disabled and its unit removed.
#                 Leave it out to keep the extras exactly as they are now. Env alternative: LAINFRAME_EXTRAS=guard,worn
#   --brightness  worn extra: dim the screen when the headset is taken off (writes ~/.config/lainframe/worn.json)
#   --no-restart  install/enable only; don't (re)start anything now
# Core services lainframe-lain + lainframe-sky start with SteamVR (steamvr.service.wants); extras with the login session.
set -u
ROOT="$HOME/lainframe"; CONF="$HOME/.config/lainframe"; STATE="$HOME/.local/state/lainframe"
UNITS="$HOME/.config/systemd/user"; VRWANTS="$UNITS/steamvr.service.wants"; DEFWANTS="$UNITS/default.target.wants"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALL_EXTRAS="guard worn mic"

EXTRAS="${LAINFRAME_EXTRAS-__keep__}"; BRIGHT=""; RESTART=1
while [ $# -gt 0 ]; do
    case "$1" in
        --extras) EXTRAS="${2-}"; shift; [ $# -gt 0 ] && shift ;;
        --extras=*) EXTRAS="${1#*=}"; shift ;;
        --brightness) BRIGHT="${2-}"; shift; [ $# -gt 0 ] && shift ;;
        --brightness=*) BRIGHT="${1#*=}"; shift ;;
        --no-restart) RESTART=0; shift ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "install.sh: unknown argument $1" >&2; exit 2 ;;
    esac
done
EXTRAS="$(echo "$EXTRAS" | tr ',' ' ')"; [ "$EXTRAS" = "none" ] && EXTRAS=""
for e in $EXTRAS; do
    [ "$e" = "__keep__" ] && continue
    case " $ALL_EXTRAS " in *" $e "*) ;; *) echo "install.sh: unknown extra '$e' (known: $ALL_EXTRAS)" >&2; exit 2 ;; esac
done
case "$BRIGHT" in ""|on|off) ;; *) echo "install.sh: --brightness takes on|off" >&2; exit 2 ;; esac

say() { echo "lainframe: $*"; }
CHANGED=""                       # units whose file changed this run

# ---- 1. files in place
mkdir -p "$ROOT/lib" "$CONF" "$STATE/voice" "$UNITS" "$VRWANTS" "$DEFWANTS"
if [ "$SRC" != "$ROOT" ]; then say "copying $SRC -> $ROOT"; cp -a "$SRC/." "$ROOT/"; fi
# the PC strips \r before sending; strip again in case files arrived another way (CRLF breaks bash and shebangs)
find "$ROOT" -maxdepth 3 \( -name '*.sh' -o -name '*.py' -o -name '*.service' -o -name '*.conf' -o -name '*.env' -o -name '*.json' \) \
     -not -path "$ROOT/lib/*" -not -path "$ROOT/lain/clips_*" -not -path "$ROOT/sky/skies/*" -not -path "$ROOT/sky/weather/*" -type f -exec sed -i 's/\r$//' {} + 2>/dev/null
chmod +x "$ROOT"/*.sh "$ROOT"/lain/*.py "$ROOT"/sky/*.py "$ROOT"/extras/*/*.sh "$ROOT"/extras/*/*.py 2>/dev/null

# ---- 2. default configs (never overwrite the user's)
cfg_default() { if [ ! -f "$2" ] && [ -f "$1" ]; then cp "$1" "$2"; say "config created: $2"; fi; }
cfg_default "$ROOT/lain/lain.json" "$CONF/lain.json"
cfg_default "$ROOT/sky/sky.json" "$CONF/sky.json"

# ---- helpers for units
install_unit() {   # $1 = source unit file
    local n; n="$(basename "$1")"
    if ! cmp -s "$1" "$UNITS/$n"; then cp "$1" "$UNITS/$n"; CHANGED="$CHANGED $n"; say "unit installed: $n"; fi
}
remove_unit() {    # $1 = unit name
    local n="$1"
    if [ -f "$UNITS/$n" ] || [ -L "$DEFWANTS/$n" ] || [ -e "$DEFWANTS/$n" ] || [ -L "$VRWANTS/$n" ] || [ -e "$VRWANTS/$n" ]; then
        systemctl --user stop "$n" 2>/dev/null; systemctl --user disable "$n" 2>/dev/null
        rm -f "$UNITS/$n" "$DEFWANTS/$n" "$VRWANTS/$n"; say "removed: $n"; CHANGED="$CHANGED -$n"
    fi
}

# ---- 3. core: lain + sky, started by SteamVR
for u in "$ROOT/lain/lainframe-lain.service" "$ROOT/sky/lainframe-sky.service"; do
    install_unit "$u"; n="$(basename "$u")"
    ln -sfn "$UNITS/$n" "$VRWANTS/$n"
done

# ---- 4. extras
if [ "$EXTRAS" = "__keep__" ]; then
    WANT=""; for e in $ALL_EXTRAS; do [ -f "$UNITS/lainframe-$e.service" ] && WANT="$WANT $e"; done
    say "extras unchanged:${WANT:- none}"
else
    WANT="$EXTRAS"
fi
for e in $ALL_EXTRAS; do
    case " $WANT " in
        *" $e "*)
            case "$e" in
                worn) cfg_default "$ROOT/extras/worn/worn.json" "$CONF/worn.json" ;;
                mic)  cfg_default "$ROOT/extras/mic/mic.env" "$CONF/mic.env" ;;
            esac
            install_unit "$ROOT/extras/$e/lainframe-$e.service"
            ln -sfn "$UNITS/lainframe-$e.service" "$DEFWANTS/lainframe-$e.service" ;;
        *) remove_unit "lainframe-$e.service" ;;
    esac
done
if [ -n "$BRIGHT" ]; then
    [ -f "$CONF/worn.json" ] || cp "$ROOT/extras/worn/worn.json" "$CONF/worn.json"
    python3 - "$CONF/worn.json" "$BRIGHT" <<'PY'
import json, sys
p, on = sys.argv[1], sys.argv[2] == "on"
try: c = json.load(open(p))
except (OSError, ValueError): c = {}
if c.get("brightness") != on:
    c["brightness"] = on; json.dump(c, open(p, "w"), indent=2); print("lainframe: worn.json brightness ->", on)
PY
    case " $WANT " in *" worn "*) CHANGED="$CHANGED lainframe-worn.service" ;; esac   # re-read on restart
fi
systemctl --user daemon-reload

# ---- 5. (re)start
active() { [ "$(systemctl --user is-active "$1" 2>/dev/null)" = active ]; }
if [ $RESTART -eq 1 ]; then
    if active steamvr.service; then
        # sky: a restart is quick and harmless. lain: if she runs and only her code changed, ask her to restart herself
        # once idle (a systemctl restart could cut off a reply mid-sentence).
        systemctl --user restart lainframe-sky.service && say "lainframe-sky restarted"
        if active lainframe-lain.service && [[ "$CHANGED" != *lainframe-lain.service* ]]; then
            touch "$STATE/restart.req"; say "lainframe-lain will restart itself when idle"
        else
            systemctl --user restart lainframe-lain.service && say "lainframe-lain (re)started"
        fi
    else
        say "SteamVR is not running: lain + sky start with it"
    fi
    for e in $WANT; do
        u="lainframe-$e.service"
        if [[ "$CHANGED" == *"$u"* ]] || ! active "$u"; then systemctl --user restart "$u" && say "$u (re)started"; fi
    done
fi

# ---- 6. status
echo
echo "=== Lainframe status ==="
for u in lainframe-lain lainframe-sky lainframe-guard lainframe-worn lainframe-mic; do
    if [ -f "$UNITS/$u.service" ]; then
        if [ -e "$VRWANTS/$u.service" ]; then en="with SteamVR"; elif [ -e "$DEFWANTS/$u.service" ]; then en="at login"; else en="not enabled"; fi
        printf '  %-16s installed, starts %-12s now: %s\n' "$u" "$en," "$(systemctl --user is-active $u.service 2>/dev/null)"
    else
        printf '  %-16s not installed\n' "$u"
    fi
done
if python3 -c "import sys; sys.path.insert(0, '$ROOT/lib'); import openvr, PIL" 2>/dev/null; then echo "  python libs      ok (pyopenvr + Pillow in $ROOT/lib)"
else echo "  python libs      MISSING: pyopenvr and/or Pillow not importable from $ROOT/lib (the PC app pushes them)"; fi
nclips=$(find "$ROOT/lain/clips_grok" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
nbaked=$(find "$ROOT/lain/clips_baked" -name '*.rgbz' 2>/dev/null | head -1000 | wc -l)
nskies=$(find "$ROOT/sky/skies" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
[ -f "$ROOT/lain/clips_grok/clips.json" ] && echo "  lain art         ok ($nclips folders, baked: $([ "$nbaked" -gt 0 ] && echo yes || echo 'no, PNG fallback (slower)'))" \
                                          || echo "  lain art         MISSING: $ROOT/lain/clips_grok/clips.json"
[ "$nskies" -gt 0 ] && echo "  sky art          ok ($nskies skies)" || echo "  sky art          MISSING: $ROOT/sky/skies/"
echo "  config           $CONF"
echo "  logs             $STATE (lain.log, sky.log; extras: guard.log, mic.log, journalctl --user -u lainframe-worn)"
echo "  note: Lain appears only while the Frame streams from the PC with the Steam menu open (log line \"lain (grok) ready\")."
