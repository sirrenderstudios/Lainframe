"""Lain's voice loop (headset side): the recorder + state machine that lain_player.py drives.
a click (or the wake phrase) -> listening (mic via pw-record, 16 kHz mono) -> stops on 1.2 s of silence after speech, a
click, or no speech at all -> writes <id>.wav + "voice <id>" to the clicks file (the PC bridge picks it up) -> thinking
-> the PC answers with <id>.reply.wav (her voice; optional <id>.vis.json lip track, read by the player) + <id>.done
-> speaking (pw-play) -> after the answer she keeps listening for a reply (conversation mode), else back to idle.
States: idle | listening | thinking | speaking | error. Exchange folder: ~/.local/state/lainframe/voice (set by the player)."""
import array, math, os, subprocess, threading, time, wave

RATE = 16000
CHUNK = RATE // 10                 # 100 ms
MAX_S = 60.0                       # long instructions are fine
END_SILENCE_S = 1.2
NO_SPEECH_S = 7.0
CONVO_TIMEOUT_S = 10.0          # after she answers she keeps listening; 10 s of silence -> back to idle
REPLY_TIMEOUT_S = 660.0          # bridge allows Claude 600 s for real work (renders, deploys)
LINGER_S = 6.0

def rms(buf):
    a = array.array("h"); a.frombytes(buf[: len(buf) // 2 * 2])
    if not a: return 0.0
    return math.sqrt(sum(x * x for x in a) / len(a))

class Voice:
    def __init__(self, vdir, clicks, log, rec_cmd=None, play_cmd=None):
        self.vdir, self.clicks, self.log = vdir, clicks, log
        os.makedirs(vdir, exist_ok=True)
        self.rec_cmd = rec_cmd or ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"]
        self.play_cmd = play_cmd or ["pw-play"]
        self.state = "idle"            # idle | listening | thinking | speaking | error
        self.t_state = time.time()
        self.req = None; self.player = None
        self._rec = None; self._stop = threading.Event(); self._why = None; self._pcm = bytearray(); self._heard = False
        self.levels = []; self._end = None; self.convo = False; self.no_speech = NO_SPEECH_S

    def _set(self, st):
        self.state = st; self.t_state = time.time()
        self.log("voice:", st, self.req or "")

    # ---------- listening
    def start_listening(self, convo=False):
        if self.state in ("listening", "thinking"): return
        if self.req: self._cleanup()
        self.convo = convo; self.no_speech = CONVO_TIMEOUT_S if convo else NO_SPEECH_S
        self._stop.clear(); self._why = None; self._pcm = bytearray(); self._heard = False; self.levels = []
        self.req = time.strftime("%H%M%S") + "%03d" % (int(time.time() * 1000) % 1000)
        if self.player and self.player.poll() is None:
            self.player.terminate()                     # talking over her stops her reply
        try:
            self._rec = subprocess.Popen(self.rec_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as e:
            self.log("voice: mic failed", e); self._set("error"); return
        self._set("listening")
        threading.Thread(target=self._reader, daemon=True).start()

    def stop_listening(self, why="click"):
        if self.state == "listening":
            self._why = why; self._stop.set()

    def _reader(self):
        t0 = time.time(); floor = None; last_voice = None; noise = []
        p = self._rec
        while not self._stop.is_set():
            buf = p.stdout.read(CHUNK * 2)
            if not buf: break
            self._pcm += buf
            lv = rms(buf); self.levels.append(lv)
            el = time.time() - t0
            if len(noise) < 3: noise.append(lv); continue          # first 0.3 s = room noise
            floor = floor if floor is not None else max(min(noise), 20.0)
            floor = max(min(floor, lv), 20.0)                      # quietest level so far = room noise
            thr = max(floor * 2.5, 1500.0)                        # speech close to the mic peaks ~5000-6200, a TV across the room ~870
            a_ = array.array("h"); a_.frombytes(buf[: len(buf) // 2 * 2])
            pk = max(abs(x) for x in a_) if a_ else 0
            if lv > thr or pk > 9000:
                self._heard = True; last_voice = el
            if self._heard and last_voice is not None and el - last_voice > END_SILENCE_S:
                self._why = "silence"; break
            if not self._heard and el > self.no_speech:
                self._why = "nothing heard"; break
            if el > MAX_S:
                self._why = "max length"; break
        try: p.terminate()
        except Exception: pass
        self._finish()

    def _finish(self):
        why = self._why or "stopped"
        self.log("voice: levels min %.0f max %.0f heard=%s" % (min(self.levels or [0]), max(self.levels or [0]), self._heard))
        if not self._heard and why != "click":
            self.log("voice: no speech (%s), loudest chunk %.0f" % (why, max(self.levels or [0])))
            self._set("idle"); return
        path = os.path.join(self.vdir, self.req + ".wav")
        pcm = bytes(self._pcm)
        peak = max(abs(x) for x in array.array("h", pcm[: len(pcm) // 2 * 2])) if pcm else 0
        if 0 < peak < 8000:                                   # quiet mic: normalise so speech-to-text hears it
            g = min(8.0, 12000.0 / peak)
            a = array.array("h"); a.frombytes(pcm[: len(pcm) // 2 * 2])
            pcm = array.array("h", (max(-32768, min(32767, int(x * g))) for x in a)).tobytes()
        with wave.open(path + ".tmp", "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm)
        os.replace(path + ".tmp", path)
        with open(self.clicks, "a") as f:
            f.write("voice %s\n" % self.req)
        self.log("voice: sent %s (%.1fs, %s)" % (self.req, len(pcm) / 2 / RATE, why))
        self._set("thinking")

    # ---------- reply
    def update(self):
        now = time.time()
        if self.state == "thinking":
            done = os.path.join(self.vdir, self.req + ".done")
            if os.path.exists(done):
                if self.player and self.player.poll() is None: self.player.terminate()
                wav = os.path.join(self.vdir, self.req + ".reply.wav")
                self._had_reply = os.path.exists(wav)
                if os.path.exists(wav):
                    try: self.player = subprocess.Popen(self.play_cmd + [wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except OSError as e: self.log("voice: play failed", e)
                self._set("speaking")
            elif now - self.t_state > REPLY_TIMEOUT_S:
                self.log("voice: no reply from the PC"); self._set("error")
        elif self.state == "speaking":
            playing = self.player is not None and self.player.poll() is None
            if not playing and now - self.t_state > 1.0:
                if not hasattr(self, "_end") or self._end is None: self._end = now
                if now - self._end > 0.6:                     # she finished talking: keep listening (conversation mode)
                    self._end = None; self._set("idle")
                    if getattr(self, "_had_reply", True): self.start_listening(convo=True)   # nothing said back: just sleep
        elif self.state == "error" and now - self.t_state > 4.0:
            self._set("idle")

    def speaking(self):
        return self.state == "speaking" and self.player is not None and self.player.poll() is None

    def _cleanup(self):
        for ext in (".wav", ".reply.wav", ".done"):
            try: os.remove(os.path.join(self.vdir, self.req + ext))
            except OSError: pass
