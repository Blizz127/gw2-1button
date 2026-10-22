# gw2-1button

One-button rotation helper for Guild Wars 2, Guild Wars: Reforged and
EverQuest (Legends) on Linux/Wayland. It injects keys with `ydotool`, reads
the trigger key straight from `/dev/input/event*`, and only runs while the
matching game process is up. The module docstring in `gw2-1button.py`
documents the modes (`auto`, `run`, `toggle`, `stop`) and the trigger keys.

## Provenance

The original source file was lost from `~/gw2-1button.py` some time after
2026-09-27. This copy was reconstructed on 2026-10-22 from the surviving
`__pycache__/gw2-1button.cpython-314.pyc` (compiled 2026-08-27). Compiling
this file with the same CPython 3.14 produces bytecode identical to that
cache for every function, so behavior is the same as the lost original;
only comments and formatting are new. That byte-identical state is commit
`5ab8e61`; later commits extend the script (shared `AutoLoop`, window).

## Install

The machine's launcher and login autostart expect the script at
`/var/home/blizz/gw2-1button.py`, which is a symlink to this file:

```
ln -sfn ~/Projects/gw2-1button/gw2-1button.py ~/gw2-1button.py
```

`gw2-1button.desktop` is the launcher used on the desktop and in
`~/.config/autostart/`. Reading input devices needs
`/etc/udev/rules.d/90-gw2-input-read.rules` (the script prints the rule if it
cannot open any device).

## Window

`gw2_1button_gui.py` is a PySide6 window in the same style as the AION 2 and
EQ Legends Solo Assist windows. It runs the same `auto` loop as the console
command: pick a profile, trigger key and tap delay; press the trigger key or
**Rotation ON** to start, press again or **STOP** to end. The table shows the
exact key order being cycled, the Activity tab logs ON/OFF and game changes,
and the Setup tab explains the requirements.

```
./launch-gw2-gui.sh                      # window
python3 gw2_1button_gui.py --char guardian --key MB4
QT_QPA_PLATFORM=offscreen python3 gw2_1button_gui.py --gui-smoke-test /tmp/gw2-window.png
python3 -m pytest -q
```

`gw2-1button-gui.desktop` is installed to `~/.local/share/applications/` and
the desktop. The login autostart still runs the console `auto` mode; if that
is running when the window opens, the window shows CONSOLE HELPER RUNNING and
offers a button to stop it and take over, because two copies would double
every key.
