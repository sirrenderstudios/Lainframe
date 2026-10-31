#!/usr/bin/env python3
"""The "Wake up, Lain" phrase, headset side. Lives in ~/lainframe/lain/. Not a service: the PC starts it over its own
ssh link (brain/wake/lain_wake.py runs `python3 -u ~/lainframe/lain/wake_link.py`) and it dies with that link.

- The mic is open ONLY while ~/.local/state/lainframe/wake_armed is fresh (< 2.5 s old). lain_player.py touches it every
  second while she is on the open Steam menu, the Frame streams from the PC, and the voice loop is idle. So: nothing
  is recorded in games, with the menu closed, while she listens / thinks / speaks, or when the PC isn't connected.
- Cheap energy gate (same thresholds as voice.py: RMS > max(2.5x room, 1500) or peak > 9000; a TV across the room sits
  ~870): a speech burst of >= 0.3 s, with 0.3 s of audio before it, ended by 0.7 s of quiet, cut at 3.5 s -> one line on
  stdout: "seg <n> <base64 of s16le 16 kHz mono>". Only the head of a long burst is sent, then it waits for quiet.
  The PC transcribes it locally (whisper.cpp) and looks for the phrase.
- stdin from the PC: "wake <n>" -> touches ~/.local/state/lainframe/wake.req (lain_player starts listening exactly like
  a click, and only if she's still idle); "ping" -> "pong". stdin EOF / broken stdout (ssh gone) -> exit.
Log: ~/.local/state/lainframe/wake.log"""
import array, base64, math, os, subprocess, sys, threading, time, warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
try:
    import audioop                                   # C speed on 3.12 (removed in 3.13: pure Python fallback below)
except ImportError:
    audioop = None

RATE = 16000
CHUNK = RATE // 10                                   # 100 ms
ST = os.path.expanduser("~/.local/state/lainframe")       # shared with lain_player.py (same names there)
ARMED = os.path.join(ST, "wake_armed")
REQ = os.path.join(ST, "wake.req")
LOG = os.path.join(ST, "wake.log")
ARMED_FRESH_S = 2.5
PRE_CHUNKS = 3                                       # 0.3 s before the burst
MIN_LOUD = 3                                         # >= 0.3 s of loud chunks
END_QUIET_S = 0.7                                    # "Wake up, Lain" has a comma pause: do not split it
MAX_SEG_S = 3.5
MIN_GAP_S = 0.3                                      # never more than ~3 segments a second
out_lock = threading.Lock()


def log(*a):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 512 * 1024: os.replace(LOG, LOG + ".1")
        with open(LOG, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
    except OSError: pass


def send(line):
    try:
        with out_lock:
            sys.stdout.write(line + "\n"); sys.stdout.flush()
    except (BrokenPipeError, OSError):
        log("pc link gone (stdout)"); os._exit(0)


def levels(buf):
    if audioop:
        return audioop.rms(buf, 2), audioop.max(buf, 2)
    a = array.array("h"); a.frombytes(buf[: len(buf) // 2 * 2])
    if not a: return 0.0, 0
    return math.sqrt(sum(x * x for x in a) / len(a)), max(abs(x) for x in a)


def armed():
    try: return time.time() - os.path.getmtime(ARMED) < ARMED_FRESH_S
    except OSError: return False


def stdin_reader():
    for line in sys.stdin:
        w = line.split()
        if not w: continue
        if w[0] == "wake":
            try:
                with open(REQ, "a"): pass
                os.utime(REQ, None)
                log("wake from the PC", w[1:] and w[1] or "")
            except OSError as e: log("wake req failed", e)
        elif w[0] == "ping":
            send("pong")
    log("pc link gone (stdin)"); os._exit(0)


class Segmenter:
    """energy gate: feed 100 ms chunks, get back finished speech bursts (bytes) or None."""
    def __init__(self):
        self.pre = []; self.seg = None; self.loud = 0; self.last_loud = -9.0; self.skip = False; self.floor = None
        self.t = 0.0; self.t_start = 0.0; self.last_sent = -9.0; self.cut = False

    def feed(self, buf):
        self.t += len(buf) / 2 / RATE; t = self.t
        lv, pk = levels(buf)
        f = self.floor
        f = lv if f is None else (lv if lv < f else f + (lv - f) * 0.002)       # room noise: quietest, rises slowly
        self.floor = f = max(f, 20.0)
        is_loud = lv > max(f * 2.5, 1500.0) or pk > 9000
        if is_loud: self.last_loud = t
        if self.skip:                                                     # rest of a long burst: wait for quiet
            if t - self.last_loud > END_QUIET_S: self.skip = False
            return None
        if self.seg is None:
            self.pre.append(buf); self.pre = self.pre[-PRE_CHUNKS:]
            if is_loud:
                self.seg = bytearray(b"".join(self.pre)); self.loud = 1; self.t_start = t
            return None
        self.seg += buf; self.loud += is_loud
        ended = t - self.last_loud > END_QUIET_S
        cut = t - self.t_start > MAX_SEG_S
        if not (ended or cut): return None
        seg, loud = bytes(self.seg), self.loud
        self.seg = None; self.pre = []; self.skip = cut; self.cut = cut
        if loud >= MIN_LOUD and t - self.last_sent > MIN_GAP_S:
            self.last_sent = t; return seg
        return None


def listen_while_armed(seq):
    """record while armed; returns the next segment number when disarmed."""
    try:
        p = subprocess.Popen(["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as e:
        log("mic failed", e); time.sleep(5); return seq
    log("armed: mic open")
    sg = Segmenter(); t_check = 0.0
    try:
        while True:
            buf = p.stdout.read(CHUNK * 2)
            if not buf: break
            now = time.time()
            if now > t_check:
                t_check = now + 0.25
                if not armed(): break
            seg = sg.feed(buf)
            if seg:
                seq += 1
                send("seg %d %s" % (seq, base64.b64encode(seg).decode("ascii")))
                log("seg %d: %.1f s%s" % (seq, len(seg) / 2 / RATE, " (cut)" if sg.cut else ""))
    finally:
        try: p.terminate(); p.wait(2)
        except Exception: pass
        log("disarmed: mic closed")
    return seq


def main():
    os.makedirs(ST, exist_ok=True)
    log("started (pid %d)" % os.getpid())
    threading.Thread(target=stdin_reader, daemon=True).start()
    send("hello wake_link 1")
    seq = 0
    while True:
        if armed(): seq = listen_while_armed(seq)
        else: time.sleep(0.25)


if __name__ == "__main__":
    main()
