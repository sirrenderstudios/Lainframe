"""The Steam Frame's battery, read-only (the voice bridge answers "how's my battery" with it, no Claude round trip).
    python tools\\frame_battery.py            -> "72%, charging"   (or "unreachable" / "no battery found"; exit 1)
    python tools\\frame_battery.py --speak    -> one short line in Lain's voice, e.g. "Seventy-two percent. It's charging."
    python tools\\frame_battery.py --test     -> parser self-test on sample sysfs text (no ssh)
One ssh -n (BatchMode, the Lainframe key, 8 s timeout) that only cats /sys/class/power_supply/*/{type,scope,capacity,status}.
Picks the supply with type Battery that isn't a peripheral (scope Device = controllers etc.), preferring BAT*/battery names."""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brain"))
import config, frame  # noqa: E402
REMOTE = ("for d in /sys/class/power_supply/*; do [ -e \"$d\" ] || continue; echo \"== ${d##*/}\"; "
          "for f in type scope capacity status present; do [ -r \"$d/$f\" ] && echo \"$f=$(cat \"$d/$f\" 2>/dev/null)\"; done; done")


def parse(text):
    """sysfs dump -> (percent, status) of the headset's own battery, or None."""
    sup = {}; cur = None
    for ln in text.splitlines():
        ln = ln.strip()
        if ln.startswith("== "): cur = ln[3:].strip(); sup[cur] = {}
        elif cur and "=" in ln: k, v = ln.split("=", 1); sup[cur][k.strip()] = v.strip()
    best = None
    for name, d in sup.items():
        if d.get("type", "").lower() != "battery" or d.get("scope", "").lower() == "device" or d.get("present", "1") == "0": continue
        try: cap = int(float(d.get("capacity", "")))
        except ValueError: continue
        score = 2 if name.upper().startswith("BAT") or "battery" in name.lower() else 1
        if best is None or score > best[0]: best = (score, cap, d.get("status", "Unknown"))
    return (max(0, min(100, best[1])), best[2]) if best else None


def describe(cap, status):
    s = status.lower()
    word = "charging" if s == "charging" else ("full" if s == "full" or (cap >= 100 and s != "discharging") else
                                                ("not charging" if s in ("discharging", "not charging") else s or "unknown"))
    return "%d%%, %s" % (cap, word), word


ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def words(n):
    if n == 100: return "a hundred"
    if n < 20: return ONES[n]
    return TENS[n // 10] + ("" if n % 10 == 0 else "-" + ONES[n % 10])


def lain_line(cap, word):
    p = words(cap).capitalize() + " percent"
    if word == "full": return "Your Frame is full. %s." % p
    if word == "charging": return "%s. It's charging." % p
    if word == "not charging": return "%s... it isn't charging." % p
    return "%s." % p


def read_frame():
    cfg = config.load()
    if not cfg["headset"]["host"]: return None, "no headset address (run setup)"
    r = frame.run(cfg, REMOTE, timeout=20)
    if r.returncode != 0: return None, frame.err(r) or "ssh failed"
    return frame.text(r), None


SAMPLE = """== ACAD
type=Mains
scope=System
== BAT1
type=Battery
scope=System
capacity=72
status=Charging
present=1
== hid-0003:28DE:1302.0005-battery
type=Battery
scope=Device
capacity=40
status=Discharging
"""


def selftest():
    cases = [(SAMPLE, (72, "Charging"), "72%, charging"),
             (SAMPLE.replace("Charging", "Discharging"), (72, "Discharging"), "72%, not charging"),
             ("== battery\ntype=Battery\ncapacity=100\nstatus=Full\n", (100, "Full"), "100%, full"),
             ("== BAT0\ntype=Battery\ncapacity=9\nstatus=Not charging\n", (9, "Not charging"), "9%, not charging"),
             ("== hid-x-battery\ntype=Battery\nscope=Device\ncapacity=50\nstatus=Discharging\n== ACAD\ntype=Mains\n", None, None)]
    ok = True
    for text, want, say in cases:
        got = parse(text); line = describe(*got)[0] if got else None
        good = got == want and line == say; ok &= good
        print("PASS" if good else "FAIL", got, line, "|", lain_line(*got[:1], describe(*got)[1]) if got else "-")
    print("ALL PASS" if ok else "SOME FAILED"); return 0 if ok else 1


def main():
    if "--test" in sys.argv: return selftest()
    speak = "--speak" in sys.argv
    text, err = read_frame()
    if text is None:
        print("I can't reach your Frame right now." if speak else "unreachable (%s)" % err); return 1
    got = parse(text)
    if not got:
        print("I can't find your Frame's battery." if speak else "no battery found"); return 1
    line, word = describe(*got)
    print(lain_line(got[0], word) if speak else line); return 0


if __name__ == "__main__":
    sys.exit(main())
