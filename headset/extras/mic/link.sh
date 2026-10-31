#!/bin/bash
# Point the PC stream (vrlink) at the EQ'd mic instead of the plain loopback mic. "./link.sh off" puts it back.
# Always connect the new source BEFORE removing the old one: a moment with no link closes Steam Link's mic stream
# (it only comes back when the stream reconnects).
SRC=alsa_loopback_device.alsa_input.platform-sound.HiFi__Mic__source; EQ=lainframe_mic_eq
for ch in FL FR; do
  if [ "$1" = off ]; then
    pw-link "$SRC:capture_$ch" "vrlink:input_$ch" 2>/dev/null; pw-link -d "$EQ:capture_$ch" "vrlink:input_$ch" 2>/dev/null
  else
    pw-link "$EQ:capture_$ch" "vrlink:input_$ch" 2>/dev/null; pw-link -d "$SRC:capture_$ch" "vrlink:input_$ch" 2>/dev/null
  fi
done
