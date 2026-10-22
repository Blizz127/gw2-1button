#!/usr/bin/env python3
"""Window for the gw2-1button rotation, styled like the AION 2 / EQ Solo Assist windows.

The window runs the same `auto` loop as `python3 gw2-1button.py auto`: one
press of the trigger key (or the Rotation ON button) starts the rotation,
another press (or STOP) ends it. Keys are only injected while Guild Wars 2,
Guild Wars: Reforged or EverQuest Legends is running.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("gw2_1button", HERE / "gw2-1button.py")
gw2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gw2)

GAMES = {"gw2": "Guild Wars 2", "gw1": "Guild Wars: Reforged", "eq": "EverQuest Legends"}
PROFILES = {
    "any": "GW2 · any profession",
    "guardian": "GW2 · Guardian (virtues first)",
    "revenant": "GW2 · Revenant",
    "gw1": "GW: Reforged · generic",
    "monk": "GW: Reforged · Monk",
    "mesmer": "GW: Reforged · Mesmer",
    "eq": "EQ Legends · spell gems",
}
BADGES = {
    "on": ("●  ROTATION ON", "#7addac"),
    "waiting": ("●  ON · WAITING FOR GAME", "#f5ca72"),
    "off": ("●  STOPPED", "#a9b5c5"),
    "blocked": ("●  CONSOLE HELPER RUNNING", "#f5ca72"),
}


def step_meaning(name: str, char: str) -> str:
    """Describe one rotation entry for the table."""
    if name == "_":
        return "skip (keeps timing)"
    if name == "`":
        return "weapon swap"
    if char in gw2.EQ_CHARS:
        return f"spell gem {name} (Alt+{name}, {gw2.EQ_DELAY:g} s cast-safe)"
    if char in gw2.GW1_CHARS:
        return f"skill slot {name}"
    if name.startswith("F"):
        return "profession skill"
    if name == "1":
        return "auto-attack chain"
    if name in "2345":
        return f"weapon skill {name}"
    return f"utility / elite {name}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--char", choices=sorted(gw2.ROTATIONS), default="any")
    parser.add_argument("--key", choices=sorted(gw2.KEY), default="-")
    parser.add_argument("--delay", type=float, default=0.09,
                        help="seconds between key taps (default 0.09)")
    parser.add_argument("--gui-smoke-test", type=Path,
                        help="render the window to a PNG without opening input devices")
    args = parser.parse_args()
    run_gui(args.char, args.key, args.delay, args.gui_smoke_test)


def run_gui(char: str, key: str, delay: float, smoke_path: Path | None = None) -> None:
    from PySide6.QtCore import QThread, QTimer, Signal
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (
        QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
        QLabel, QMainWindow, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
        QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
    )

    class Worker(QThread):
        state = Signal(object)
        line = Signal(str)

        def __init__(self) -> None:
            super().__init__()
            self.loop = gw2.AutoLoop(char, key, delay, log=self.log, report=self.state.emit)

        def log(self, line: str) -> None:
            print(line, flush=True)
            self.line.emit(line)

        def run(self) -> None:
            try:
                self.loop.run()
            except Exception as exc:  # noqa: BLE001 - surface in the window
                self.log(f"error: {exc}")

    class Window(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.worker: Worker | None = None
            self.owns_pidfile = False
            self.setWindowTitle("Guild Wars 2 · 1-Button Rotation")
            self.resize(920, 760)
            body = QWidget()
            self.setCentralWidget(body)
            layout = QVBoxLayout(body)
            layout.setContentsMargins(24, 20, 24, 20)
            layout.setSpacing(14)

            eyebrow = QLabel("GUILD WARS 2  /  ONE BUTTON")
            eyebrow.setObjectName("eyebrow")
            layout.addWidget(eyebrow)
            title = QLabel("1-Button Rotation")
            title.setObjectName("title")
            layout.addWidget(title)
            subtitle = QLabel(
                "One trigger key. Cycles the skill bar in priority order while the "
                "game is running. Also drives Guild Wars: Reforged and EQ Legends."
            )
            subtitle.setObjectName("muted")
            layout.addWidget(subtitle)

            banner = QFrame()
            banner.setObjectName("banner")
            banner_layout = QHBoxLayout(banner)
            banner_layout.setContentsMargins(16, 14, 16, 14)
            self.badge = QLabel()
            self.badge.setObjectName("state")
            banner_layout.addWidget(self.badge)
            banner_layout.addStretch()
            self.hint = QLabel()
            banner_layout.addWidget(self.hint)
            layout.addWidget(banner)

            controls = QGridLayout()
            self.profile = QComboBox()
            for name in gw2.ROTATIONS:
                self.profile.addItem(PROFILES.get(name, name), name)
            self.profile.setCurrentIndex(list(gw2.ROTATIONS).index(char))
            self.profile.currentIndexChanged.connect(self.profile_changed)
            self.trigger = QComboBox()
            for name in sorted(gw2.KEY):
                self.trigger.addItem(name, name)
            self.trigger.setCurrentIndex(sorted(gw2.KEY).index(key))
            self.trigger.currentIndexChanged.connect(self.trigger_changed)
            self.delay = QSpinBox()
            self.delay.setRange(30, 2000)
            self.delay.setSingleStep(10)
            self.delay.setSuffix(" ms")
            self.delay.setValue(round(delay * 1000))
            self.delay.setToolTip("Gap between key taps for GW2 / GW: Reforged. "
                                  "EQ always uses the cast-safe 500 ms.")
            self.delay.valueChanged.connect(self.delay_changed)
            self.game = QLabel("none detected")
            self.game.setObjectName("field")
            for column, (label, widget) in enumerate([
                ("Profile", self.profile),
                ("Trigger key", self.trigger),
                ("Tap delay", self.delay),
                ("Detected game", self.game),
            ]):
                controls.addWidget(QLabel(label), 0, column)
                controls.addWidget(widget, 1, column)
            layout.addLayout(controls)

            self.tabs = QTabWidget()
            combat = QWidget()
            tab_layout = QVBoxLayout(combat)
            tab_layout.setContentsMargins(12, 16, 12, 12)
            self.status = QLabel()
            self.status.setWordWrap(True)
            self.status.setMinimumHeight(42)
            tab_layout.addWidget(self.status)
            self.detail = QLabel("Last key: none yet")
            self.detail.setObjectName("muted")
            tab_layout.addWidget(self.detail)
            self.table = QTableWidget(0, 3)
            self.table.setHorizontalHeaderLabels(["Step", "Key", "Meaning"])
            self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
            tab_layout.addWidget(self.table, 1)

            buttons = QHBoxLayout()
            self.start = QPushButton()
            self.start.setObjectName("primary")
            self.start.clicked.connect(lambda: self.post("on"))
            self.stop = QPushButton("STOP")
            self.stop.setObjectName("stop")
            self.stop.clicked.connect(lambda: self.post("off"))
            self.takeover = QPushButton("Stop console helper and use this window")
            self.takeover.clicked.connect(self.take_over)
            self.takeover.hide()
            buttons.addWidget(self.start)
            buttons.addWidget(self.stop)
            buttons.addWidget(self.takeover)
            tab_layout.addLayout(buttons)
            self.tabs.addTab(combat, "Rotation")

            self.activity = QPlainTextEdit()
            self.activity.setReadOnly(True)
            self.activity.setMaximumBlockCount(1000)
            self.tabs.addTab(self.activity, "Activity")
            guide = QPlainTextEdit()
            guide.setReadOnly(True)
            guide.setPlainText(GUIDE)
            self.tabs.addTab(guide, "Setup")
            layout.addWidget(self.tabs, 1)

            footer = QLabel(
                "Trigger key or Rotation ON starts  ·  press again or STOP ends  ·  "
                "keys go out only while a supported game is running  ·  targeting stays manual"
            )
            footer.setWordWrap(True)
            footer.setObjectName("muted")
            layout.addWidget(footer)

            self.render_table(char, gw2.pick_rotation(char, None))
            self.set_trigger_text(key)
            self.update_state({
                "mode": "off", "status": "Starting.", "game": None, "char": char,
                "key": key, "delay": delay, "rotation": gw2.pick_rotation(char, None),
                "devices": 0, "last_key": "",
            })
            if smoke_path is None:
                existing = gw2.read_pid()
                if existing:
                    self.blocked(existing)
                else:
                    self.start_worker()

        # -- worker management -------------------------------------------
        def start_worker(self) -> None:
            with open(gw2.pidfile(), "w") as f:
                f.write(str(os.getpid()))
            self.owns_pidfile = True
            self.takeover.hide()
            self.worker = Worker()
            self.worker.state.connect(self.update_state)
            self.worker.line.connect(self.append_line)
            self.worker.start()

        def blocked(self, pid: int) -> None:
            text, color = BADGES["blocked"]
            self.badge.setText(text)
            self.badge.setStyleSheet(f"color: {color};")
            self.status.setText(
                f"The console helper (python3 gw2-1button.py auto, pid {pid}) is already "
                "running, probably from login autostart. Two copies would double every key, "
                "so this window stays idle until you stop it."
            )
            self.takeover.show()

        def take_over(self) -> None:
            pid = gw2.read_pid()
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                self.append_line(f"stopped console helper (pid {pid})")
            try:
                os.remove(gw2.pidfile())
            except FileNotFoundError:
                pass
            self.start_worker()

        def post(self, command: str, value: object = None) -> None:
            if self.worker is not None:
                self.worker.loop.post(command, value)

        # -- controls ------------------------------------------------------
        def profile_changed(self, index: int) -> None:
            name = self.profile.itemData(index)
            self.render_table(name, gw2.pick_rotation(name, self.current_game))
            self.post("char", name)

        def trigger_changed(self, index: int) -> None:
            name = self.trigger.itemData(index)
            self.set_trigger_text(name)
            self.post("key", name)

        def delay_changed(self, value: int) -> None:
            self.post("delay", value / 1000)

        def set_trigger_text(self, name: str) -> None:
            self.start.setText(f"Rotation ON  ·  {name}")
            self.hint.setText(f"{name}  START / STOP")

        current_game: str | None = None

        def render_table(self, name: str, rotation: list[str]) -> None:
            self.table.setRowCount(len(rotation))
            for row, entry in enumerate(rotation):
                cells = [str(row + 1), entry, step_meaning(entry, name)]
                for column, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    if column == 1:
                        item.setForeground(QColor("#f5ca72"))
                    self.table.setItem(row, column, item)
            self.table.resizeColumnsToContents()

        def update_state(self, state: dict[str, object]) -> None:
            text, color = BADGES.get(str(state["mode"]), BADGES["off"])
            self.badge.setText(text)
            self.badge.setStyleSheet(f"color: {color};")
            status = str(state["status"])
            if not state["devices"] and state["mode"] != "off":
                status += "  No readable input device: the trigger key is inactive, buttons still work."
            self.status.setText(status)
            game = state["game"]
            self.current_game = game if isinstance(game, str) else None
            self.game.setText(GAMES.get(str(game), "none detected"))
            if state["last_key"]:
                self.detail.setText(f"Last key: {state['last_key']}")
            char_now = str(state["char"])
            rotation = list(state["rotation"])
            if (char_now, rotation) != getattr(self, "_rendered", None):
                self._rendered = (char_now, rotation)
                self.render_table(char_now, rotation)

        def append_line(self, line: str) -> None:
            text = line.strip()
            if text:
                self.activity.appendPlainText(text)

        def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
            if self.worker is not None:
                self.worker.loop.post("quit")
                self.worker.loop.stopping = True
                if not self.worker.wait(5000):
                    event.ignore()
                    self.status.setText("Stopping… close again in a moment.")
                    return
            if self.owns_pidfile:
                try:
                    os.remove(gw2.pidfile())
                except FileNotFoundError:
                    pass
            event.accept()

    app = QApplication(sys.argv[:1])
    app.setApplicationName("GW2 1-Button Rotation")
    app.setStyleSheet(STYLE)
    window = Window()
    signal.signal(signal.SIGTERM, lambda *_: window.close())
    signal.signal(signal.SIGINT, lambda *_: window.close())
    wakeup = QTimer()
    wakeup.timeout.connect(lambda: None)
    wakeup.start(250)
    window.show()
    if smoke_path is not None:

        def render() -> None:
            smoke_path.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(smoke_path))
            app.quit()

        QTimer.singleShot(400, render)
    app.exec()


GUIDE = """QUICK START
1. Start Guild Wars 2 (or GW: Reforged / EQ Legends). The window can open first; it waits for the game.
2. Pick the profile and the trigger key. "-" is the default; MB4/MB5 are mouse side buttons, PAD_* are Xbox face buttons.
3. Press the trigger key once, or click Rotation ON. The rotation cycles the table from the top while the game is running.
4. Press the trigger key again, or STOP, to end it. Closing the window also ends it.

HOW IT ROTATES
GW2 has no global cooldown, so skills still on recharge are simply ignored and the loop keeps cycling in priority order. "1" is padded so the auto-attack chain lands often. "`" is the default weapon-swap key.
GW: Reforged profiles tap slots 1-8 in order. EQ Legends taps spell gems as Alt+1..0 with a 500 ms gap so a cast is never interrupted.
Edit ROTATIONS in gw2-1button.py to tune an order.

REQUIREMENTS
Keys are injected through ydotool (ydotoold must be running). The trigger key is read from /dev/input, which needs your user in the input group or the udev rule the script prints when no device is readable.
The login autostart entry runs the console version (gw2-1button.py auto). If it is running, this window shows CONSOLE HELPER RUNNING and offers to stop it; two copies would double every key.

LIMITS
Targeting, movement and dodging stay manual. The helper never reads game memory. Timed key injection may count as automation under each game's rules; use at your own discretion.
"""

STYLE = """
QWidget { background: #141a12; color: #e8ecdf; font-family: 'Noto Sans'; font-size: 13px; }
QLabel#eyebrow { color: #a3b58a; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
QLabel#title { color: #e9c46a; font-size: 32px; font-weight: 700; }
QLabel#muted { color: #9aa68c; font-size: 12px; }
QLabel#field { background: #1f2a1b; border: 1px solid #44523a; border-radius: 5px; padding: 7px; min-height: 22px; }
QFrame#banner { background: #1d281a; border: 1px solid #3a4a33; border-radius: 9px; }
QFrame#banner QLabel { background: transparent; }
QLabel#state { font-size: 14px; font-weight: 700; }
QComboBox, QSpinBox { background: #1f2a1b; border: 1px solid #44523a; border-radius: 5px; padding: 7px; min-height: 22px; }
QPushButton { background: #273424; border: 1px solid #4a5c42; border-radius: 5px; padding: 10px 12px; }
QPushButton:hover { background: #34462f; }
QPushButton#primary { background: #e2bc70; color: #1b2117; border-color: #e2bc70; font-weight: 700; }
QPushButton#stop { background: #48302a; color: #ffc3b9; border-color: #7f4a3b; }
QTabWidget::pane { border: 1px solid #364631; border-radius: 6px; }
QTabBar::tab { background: #1b2518; color: #a9b79a; padding: 10px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #e9c46a; border-bottom-color: #e9c46a; }
QTableWidget { background: #171f14; border: 1px solid #2f3d2a; gridline-color: #2a3726; }
QTableWidget::item { padding: 8px; }
QHeaderView::section { background: #243120; border: 0; border-bottom: 1px solid #3a4a33; padding: 8px; color: #b7c6a6; font-size: 12px; }
QPlainTextEdit { background: #171f14; border: none; padding: 12px; font-size: 13px; }
"""


if __name__ == "__main__":
    main()
