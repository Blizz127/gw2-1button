#!/usr/bin/env python3
"""
gw2-1button — one-button rotation for Guild Wars 2 on Linux (Wayland).

Supports Guild Wars 2, Guild Wars: Reforged (original GW1 client) and
EverQuest (Legends): the script detects which game is running and uses the
matching rotation. GW1 has 8 skill slots (keys 1-8), no weapon swap. EQ uses
the gem bar — Alt+1..0 — with slow, cast-safe taps (in EQ, pressing another
key mid-cast interrupts the spell).

Injection : ydotool (virtual keyboard via uinput — works with Proton/Wine)
Modes:
  auto  — one press of the key STARTS the rotation, another press stops it.
          Only injects while GW2 / GW Reforged is actually running.
              python3 gw2-1button.py auto            (key: - )
              python3 gw2-1button.py auto --key MB4   (mouse side button)
              python3 gw2-1button.py auto --key PAD_X (Xbox controller X)
              python3 gw2-1button.py auto --char monk (GW1 Reforged profile)
  run   — hold the key to rotate, release to stop.
  toggle/stop — start/stop once (for a KDE global shortcut).

Input-device read access comes from /etc/udev/rules.d/90-gw2-input-read.rules
on this machine (the `input` group can't be used here — sysusers-only).

GW2 has no global cooldown: skills still on recharge are simply ignored, so
the loop cycles everything in priority order. Edit ROTATIONS to tune.
` (backtick) is GW2's default weapon-swap key.
"""

import argparse
import fcntl
import os
import select
import signal
import struct
import subprocess
import sys
import time

EV_KEY = 1

KEY = {
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6,
    "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "-": 12,
    "`": 41,
    "F1": 59, "F2": 60, "F3": 61, "F4": 62, "F5": 63,
    "F6": 64, "F7": 65, "F8": 66, "F9": 67, "F10": 68,
    "MB4": 276, "MB5": 277,
    # Xbox controller face buttons (BTN_SOUTH/EAST/NORTH/WEST)
    "PAD_A": 304, "PAD_B": 305, "PAD_X": 307, "PAD_Y": 308,
}

# Skill 1 is the auto-attack chain; pad it so the loop lands on it often.
FILL = ["1"] * 6

ROTATIONS = {
    # GW2: weapon skills 2-5 and utilities 6-0, then auto-attack, swap, repeat
    # on the second weapon set.
    "any": ["2", "3", "4", "5", "6", "7", "8", "9", "0"] + FILL
           + ["`", "2", "3", "4", "5"] + FILL + ["`"],
    # Guardian: fire the F1-F3 virtues before the skill bar.
    "guardian": ["F1", "F2", "F3", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
                + FILL
                + ["`", "2", "3", "4", "5"] + FILL + ["`"],
    "revenant": ["2", "3", "4", "5", "6", "7", "8", "9", "0"] + FILL
                + ["`", "2", "3", "4", "5"] + FILL + ["`"],
    # Guild Wars: Reforged (GW1) — 8 skill slots, no weapon swap.
    # "gw1" is the generic profile; monk/mesmer are the same keys today and
    # exist so per-character orders can be tuned later.
    "gw1": ["1", "2", "3", "4", "5", "6", "7", "8"],
    "monk": ["1", "2", "3", "4", "5", "6", "7", "8"],
    "mesmer": ["1", "2", "3", "4", "5", "6", "7", "8"],
    # EverQuest (Legends): spell gems 1-0, sent as Alt+<n> (see EQ_MOD).
    # Each tap waits EQ_DELAY so a cast is never interrupted by the next
    # key; gems that are still refreshing are simply ignored by the game.
    # "_" in a rotation means "skip this slot" (keeps the timing).
    "eq": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
}

GW1_CHARS = ("gw1", "monk", "mesmer")
GW2_CHARS = ("any", "guardian", "revenant")
EQ_CHARS = ("eq",)

# EQ casts are interrupted by any other key press, so taps are slow and
# every gem key is sent as Alt+<n> (the gem bar's default binding).
EQ_DELAY = 0.5
EQ_MOD = 56  # KEY_LEFTALT

NO_INPUT_ERR = (
    "error: cannot read any /dev/input/event* device.\n"
    "Fix (needs sudo):\n"
    "    echo 'SUBSYSTEM==\"input\", KERNEL==\"event[0-9]*\", MODE=\"0666\"' |\n"
    "        sudo tee /etc/udev/rules.d/90-gw2-input-read.rules &&\n"
    "    sudo udevadm control --reload-rules &&\n"
    "    sudo udevadm trigger --subsystem-match=input"
)


def send_key(code: int, mod: int = None) -> None:
    if mod is None:
        seq = [f"{code}:1", f"{code}:0"]
        subprocess.run(["ydotool", "key", *seq],
                       check=False, capture_output=True)
        return
    seq = [f"{mod}:1", f"{code}:1", f"{code}:0", f"{mod}:0"]
    # -d 50: hold the modifier a moment so the game registers Alt+key.
    subprocess.run(["ydotool", "key", "-d", "50", *seq],
                   check=False, capture_output=True)


def game_running():
    """Which game is running: 'gw2', 'gw1', 'eq', or None."""
    found = None
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", "replace").lower()
        except OSError:
            continue
        if "gw2-64.exe" in cmd or "gw2.exe" in cmd:
            return "gw2"
        if "eqgame.exe" in cmd:
            found = found or "eq"
        if "gw.exe" in cmd:
            found = found or "gw1"
    return found


def pick_rotation(char, game):
    """Rotation list for the requested profile and the running game.

    Profiles fall back to the running game's default, so one instance works
    for every supported game without reconfiguring.
    """
    if game == "eq":
        return ROTATIONS[char] if char in EQ_CHARS else ROTATIONS["eq"]
    if game == "gw1":
        return ROTATIONS[char] if char in GW1_CHARS else ROTATIONS["gw1"]
    return ROTATIONS[char] if char in GW2_CHARS else ROTATIONS["any"]


# struct input_event: time (sec, usec), type, code, value
EVENT = struct.Struct("llHHi")
# EVIOCGNAME(256): _IOC(_IOC_READ, 'E', 0x06, 256) — read a device's name so
# the ydotoold virtual keyboard (our own output) can be skipped.
_EVIOCGNAME = (2 << 30) | (256 << 16) | (ord("E") << 8) | 6


class EventDevices:
    """All readable /dev/input/event* fds, kept current across hotplug.

Re-scans on every poll so controllers plugged in — or renumbered —
after startup get picked up, and drops fds whose node vanished (a
dead evdev fd stays "ready" in select forever and busy-loops).
The ydotoold virtual device is skipped: that's our own output.
"""

    def __init__(self):
        self.fds = {}
        self.scan()

    @staticmethod
    def _name(fd):
        try:
            raw = fcntl.ioctl(fd, _EVIOCGNAME, b"\0" * 256)
        except OSError:
            return ""
        return raw.rstrip(b"\0").decode(errors="replace")

    def scan(self):
        try:
            names = os.listdir("/dev/input")
        except FileNotFoundError:
            return
        for name in sorted(names):
            if not name.startswith("event"):
                continue
            path = f"/dev/input/{name}"
            if path in self.fds.values():
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            if "ydotoold" in self._name(fd):
                os.close(fd)
                continue
            self.fds[fd] = path

    def _drop(self, fd):
        try:
            os.close(fd)
        except OSError:
            pass
        self.fds.pop(fd, None)

    def poll(self, timeout):
        """Yield (type, code, value) events; rescans for hotplug."""
        self.scan()
        try:
            ready, _, _ = select.select(list(self.fds), [], [], timeout)
        except (OSError, ValueError):
            for fd in list(self.fds):
                self._drop(fd)
            return
        for fd in ready:
            try:
                data = os.read(fd, 4096)
            except OSError:
                data = b""
            if not data:
                self._drop(fd)
                continue
            for off in range(0, len(data) - len(data) % EVENT.size,
                             EVENT.size):
                _, _, typ, code, value = EVENT.unpack_from(data, off)
                yield (typ, code, value)


def rotate_forever(rotation, delay):
    stop = {"flag": False}

    def term(sig, frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, term)
    signal.signal(signal.SIGINT, term)
    while not stop["flag"]:
        for name in rotation:
            if stop["flag"]:
                break
            send_key(KEY[name])
            time.sleep(delay)


def cmd_auto(args):
    hot = KEY[args.key]
    devs = EventDevices()
    if not devs.fds:
        sys.exit(NO_INPUT_ERR)
    existing = read_pid()
    if existing:
        sys.exit(f"already running (pid {existing}) — use 'python3 gw2-1button.py stop' first")

    with open(pidfile(), "w") as f:
        f.write(str(os.getpid()))
    print(f"GW 1-button | char={args.char} | press {args.key} ONCE to start, press again to stop | Ctrl+C quits",
          flush=True)
    print("Rotation runs while GW2 / GW: Reforged / EverQuest is running.",
          flush=True)
    armed = False
    idx = 0
    next_t = 0.0
    game = game_running()
    rotation = pick_rotation(args.char, game)
    last_check = time.monotonic()
    signal.signal(signal.SIGTERM,
                  lambda sig, frame: (_ for _ in ()).throw(KeyboardInterrupt))
    try:
        while True:
            now = time.monotonic()
            if now - last_check >= 1.0:
                new_game = game_running()
                last_check = now
                if new_game != game:
                    game = new_game
                    new_rot = pick_rotation(args.char, game)
                    if new_rot is not rotation:
                        rotation = new_rot
                        idx = 0
            if not armed:
                timeout = None
            elif game:
                timeout = max(0.0, next_t - now)
            else:  # armed but the game is not up yet: idle-poll
                timeout = 0.2
            events = list(devs.poll(timeout))
            now = time.monotonic()
            if armed and game and now >= next_t:
                name = rotation[idx % len(rotation)]
                if name != "_":
                    send_key(KEY[name], EQ_MOD if game == "eq" else None)
                idx += 1
                next_t = now + (EQ_DELAY if game == "eq" else args.delay)
            for typ, code, value in events:
                if typ != EV_KEY or code != hot or value != 1:
                    continue
                armed = not armed
                idx = 0
                next_t = 0.0
                if armed:
                    game = game_running()
                    rotation = pick_rotation(args.char, game)
                    last_check = now
                    print("ON" if game else
                          "ON (waiting for the game to start)", flush=True)
                else:
                    print("OFF", flush=True)
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        try:
            os.remove(pidfile())
        except FileNotFoundError:
            pass


def cmd_run(args):
    rotation = ROTATIONS[args.char]
    hot = KEY[args.key]
    devs = EventDevices()
    if not devs.fds:
        sys.exit(NO_INPUT_ERR)
    print(f"GW2 1-button | char={args.char} | HOLD {args.key} to rotate, release to stop | Ctrl+C quits",
          flush=True)
    print("Focus the GW2 window, then hold the key.", flush=True)
    running = False
    idx = 0
    next_t = 0.0
    try:
        while True:
            timeout = max(0.0, next_t - time.monotonic()) if running else None
            events = list(devs.poll(timeout))
            now = time.monotonic()
            if running and now >= next_t:
                send_key(KEY[rotation[idx % len(rotation)]])
                idx += 1
                next_t = now + args.delay
            for typ, code, value in events:
                if typ != EV_KEY or code != hot or value == 2:
                    continue
                if value == 1:
                    running = True
                    idx = 0
                    next_t = 0.0
                elif value == 0:
                    running = False
    except KeyboardInterrupt:
        print("\nbye")


def pidfile():
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                        "gw2-1button.pid")


def read_pid():
    try:
        pid = int(open(pidfile()).read().strip())
        os.kill(pid, 0)
        return pid
    except (FileNotFoundError, ValueError, ProcessLookupError,
            PermissionError):
        return None


def cmd_toggle(args):
    pid = read_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        try:
            os.remove(pidfile())
        except FileNotFoundError:
            pass
        print(f"stopped (pid {pid})")
        return
    log = open(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                            "gw2-1button.log"), "ab")
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "_loop",
         "--char", args.char, "--delay", str(args.delay)],
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    with open(pidfile(), "w") as f:
        f.write(str(proc.pid))
    print(f"started {args.char} rotation (pid {proc.pid}) - press the key again to stop")


def cmd_stop(args):
    pid = read_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        try:
            os.remove(pidfile())
        except FileNotFoundError:
            pass
        print(f"stopped (pid {pid})")
    else:
        print("not running")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "_loop":
        lp = argparse.ArgumentParser()
        lp.add_argument("--char", choices=sorted(ROTATIONS), default="any")
        lp.add_argument("--delay", type=float, default=0.09)
        a = lp.parse_args(sys.argv[2:])
        rotate_forever(ROTATIONS[a.char], a.delay)
        return

    ap = argparse.ArgumentParser(
        description="GW2 one-button rotation (ydotool)")
    sub = ap.add_subparsers(dest="cmd")
    for name, fn, help_ in (
        ("auto", cmd_auto,
         "one press starts/stops; only runs while GW2 is open"),
        ("run", cmd_run, "hold-to-rotate in the foreground"),
        ("toggle", cmd_toggle, "start/stop once (KDE global shortcut)"),
        ("stop", cmd_stop, "stop a running auto/toggle rotation"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--char", choices=sorted(ROTATIONS), default="any")
        p.add_argument("--delay", type=float, default=0.09,
                       help="seconds between key taps (default 0.09)")
        if name in ("auto", "run"):
            p.add_argument("--key",
                           default="-" if name == "auto" else "F9",
                           choices=sorted(KEY),
                           help="trigger key (default: - for auto, F9 for run; MB4/MB5 = mouse side buttons; PAD_A/PAD_B/PAD_X/PAD_Y = Xbox controller face buttons)")
        p.set_defaults(fn=fn)
    args = ap.parse_args()
    if not getattr(args, "fn", None):
        ap.print_help()
        sys.exit(1)
    args.fn(args)


if __name__ == "__main__":
    main()
