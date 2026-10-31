r"""Finds the Steam Frame on any network this PC shares with it (home Wi-Fi, the Steam Link adapter's own network,
USB) and saves its address in %APPDATA%\Lainframe\config.json. Prints the address, or nothing (exit 1) if not found.
Order: the saved address, frame.local, the ARP table, then every host on this PC's /24 networks with ssh open. Only
hosts that accept the Lainframe key AND run SteamOS on ARM count (a Steam Deck is SteamOS on x86_64).
    python tools\find_frame.py [--quiet]"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brain"))
import config, frame  # noqa: E402


def main():
    cfg = config.load()
    if not os.path.exists(config.path(cfg["headset"]["ssh_key"])):
        if "--quiet" not in sys.argv: print("no Lainframe ssh key yet: run LainBrain.bat setup", file=sys.stderr)
        return 1
    ip = frame.find(cfg, save=True)
    if ip: print(ip); return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
