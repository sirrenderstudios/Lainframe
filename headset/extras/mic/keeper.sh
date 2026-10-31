#!/bin/bash
# Lainframe mic extra (opt-in): holds the mic gain at GAIN and keeps the EQ on every new PC stream.
#  - the Frame resets VA_DEC0/1 to 104 (+20 dB: clips and hisses) whenever the mic powers up; 96 (+12 dB) sounds clean
#  - the EQ (mic_eq.conf) runs as its own PipeWire client; each new Steam Link stream (vrlink) gets hooked to it
# Config: ~/.config/lainframe/mic.env (GAIN=96, EQ=1). Log: ~/.local/state/lainframe/mic.log
DIR="$(cd "$(dirname "$0")" && pwd)"; GAIN=96; EQ_ON=1
[ -f ~/.config/lainframe/mic.env ] && . ~/.config/lainframe/mic.env && EQ_ON=${EQ:-1}
mkdir -p ~/.local/state/lainframe; LOG=~/.local/state/lainframe/mic.log
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
eq_pid() { for p in $(pgrep -x pipewire); do tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | grep -q 'lainframe.*mic_eq.conf' && echo $p; done; }
log "keeper started (gain $GAIN, eq $EQ_ON)"
while true; do
  for c in "VA_DEC0 Volume" "VA_DEC1 Volume"; do
    v=$(amixer -c 0 cget name="$c" 2>/dev/null | sed -n 's/.*: values=//p')
    if [ -n "$v" ] && [ "$v" != "0" ] && [ "$v" != "$GAIN" ]; then amixer -c 0 cset name="$c" $GAIN >/dev/null 2>&1 && log "$c $v -> $GAIN"; fi
  done
  if [ "$EQ_ON" = 1 ]; then
    if [ -z "$(eq_pid)" ] && pw-cli info 0 >/dev/null 2>&1; then
      nohup pipewire -c "$DIR/mic_eq.conf" >> ~/.local/state/lainframe/mic_eq.log 2>&1 & log "EQ started"; sleep 2
    fi
    links=$(pw-link -l -I 2>/dev/null)
    if echo "$links" | grep -q "vrlink:input_FL" && ! echo "$links" | grep -A1 "vrlink:input_FL" | grep -q "lainframe_mic_eq:capture_FL" \
       && echo "$links" | grep -q "lainframe_mic_eq:capture_FL"; then "$DIR/link.sh" >/dev/null; log "PC stream hooked to the EQ"; fi
  fi
  sleep 3
done
