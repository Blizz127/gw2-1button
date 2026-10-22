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
only comments and formatting are new.

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
