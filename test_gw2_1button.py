"""Behavioral tests for the gw2-1button auto loop and its window."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("gw2_1button", HERE / "gw2-1button.py")
gw2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gw2)


class FakeDevices:
    """Stands in for EventDevices: scripted key events, no /dev/input."""

    def __init__(self, fds=(1,)):
        self.fds = dict.fromkeys(fds, "/dev/input/fake")
        self.pending = []
        self.polls = 0

    def press(self, name):
        self.pending.append((gw2.EV_KEY, gw2.KEY[name], 1))
        self.pending.append((gw2.EV_KEY, gw2.KEY[name], 0))

    def poll(self, timeout):
        self.polls += 1
        events, self.pending = self.pending, []
        yield from events


class Scene:
    def __init__(self, monkeypatch, *, game="gw2", char="any", key="-", delay=0.09):
        self.clock = 100.0
        self.game = game
        self.sent = []
        self.lines = []
        self.states = []
        monkeypatch.setattr(gw2.time, "monotonic", lambda: self.clock)
        monkeypatch.setattr(gw2, "game_running", lambda: self.game)
        monkeypatch.setattr(gw2, "send_key", lambda code, mod=None: self.sent.append((code, mod)))
        self.devs = FakeDevices()
        self.loop = gw2.AutoLoop(char, key, delay, log=self.lines.append, report=self.states.append)

    def run(self, polls, *, step=0.1, on_poll=None):
        """Run the loop for a number of polls; each poll advances the clock."""
        original = self.devs.poll

        def poll(timeout):
            if self.devs.polls >= polls:
                self.loop.stopping = True
                return iter(())
            if on_poll is not None:
                on_poll(self.devs.polls)
            self.clock += step
            return original(timeout)

        self.devs.poll = poll
        self.loop.run(self.devs)


def key_names(sent):
    back = {code: name for name, code in gw2.KEY.items()}
    return [back[code] for code, _ in sent]


def test_rotation_profiles_fall_back_to_the_running_game():
    assert gw2.pick_rotation("monk", "gw1") is gw2.ROTATIONS["monk"]
    assert gw2.pick_rotation("guardian", "gw1") is gw2.ROTATIONS["gw1"]
    assert gw2.pick_rotation("monk", "gw2") is gw2.ROTATIONS["any"]
    assert gw2.pick_rotation("guardian", "eq") is gw2.ROTATIONS["eq"]
    assert gw2.pick_rotation("eq", None) is gw2.ROTATIONS["any"]


def test_trigger_key_press_starts_the_rotation_in_table_order(monkeypatch):
    scene = Scene(monkeypatch)
    scene.devs.press("-")
    scene.run(12)

    assert scene.loop.armed
    assert key_names(scene.sent)[:5] == gw2.ROTATIONS["any"][:5]
    assert scene.lines[0] == "ON"
    assert scene.states[-1]["mode"] == "on"


def test_second_trigger_press_stops_and_no_more_keys_follow(monkeypatch):
    scene = Scene(monkeypatch)
    scene.devs.press("-")

    def second_press(poll_index):
        if poll_index == 4:
            scene.devs.press("-")

    scene.run(12, on_poll=second_press)

    assert not scene.loop.armed
    assert "OFF" in scene.lines
    sent_after_off = len(scene.sent)
    assert sent_after_off < 12
    assert scene.states[-1]["mode"] == "off"


def test_window_on_and_off_commands_mirror_the_trigger_key(monkeypatch):
    scene = Scene(monkeypatch)
    scene.loop.post("on")

    def stop_from_window(poll_index):
        if poll_index == 3:
            scene.loop.post("off")

    scene.run(8, on_poll=stop_from_window)

    assert scene.lines[0] == "ON (window)"
    assert "OFF (window)" in scene.lines
    assert 1 <= len(scene.sent) <= 4


def test_no_keys_are_sent_while_no_supported_game_is_running(monkeypatch):
    scene = Scene(monkeypatch, game=None)
    scene.devs.press("-")
    scene.run(6)

    assert scene.loop.armed
    assert scene.sent == []
    assert scene.lines[0] == "ON (waiting for the game to start)"
    assert scene.states[-1]["mode"] == "waiting"


def test_eq_uses_alt_modifier_and_cast_safe_delay(monkeypatch):
    scene = Scene(monkeypatch, game="eq", char="eq")
    scene.devs.press("-")
    scene.run(4, step=0.6)

    assert scene.sent[0] == (gw2.KEY["1"], gw2.EQ_MOD)
    assert key_names(scene.sent)[:3] == ["1", "2", "3"]


def test_profile_change_from_the_window_restarts_the_table(monkeypatch):
    scene = Scene(monkeypatch, game="gw1")
    scene.loop.post("on")

    def switch(poll_index):
        if poll_index == 2:
            scene.loop.post("char", "monk")

    scene.run(6, on_poll=switch)

    assert scene.loop.char == "monk"
    assert scene.loop.rotation is gw2.ROTATIONS["monk"]
    assert scene.states[-1]["char"] == "monk"


def test_quit_command_ends_the_loop(monkeypatch):
    scene = Scene(monkeypatch)
    scene.loop.post("quit")
    scene.loop.run(scene.devs)

    assert scene.loop.stopping
    assert scene.devs.polls == 0


def test_loop_runs_without_input_devices_and_says_so(monkeypatch):
    scene = Scene(monkeypatch)
    scene.devs = FakeDevices(fds=())
    scene.loop.post("on")
    scene.run(3)

    assert any("no readable /dev/input" in line for line in scene.lines)
    assert scene.states[-1]["devices"] == 0
    assert scene.sent  # window buttons still drive the rotation


def test_console_help_still_lists_all_modes():
    proc = subprocess.run([sys.executable, str(HERE / "gw2-1button.py"), "--help"],
                          capture_output=True, text=True, timeout=20)
    assert proc.returncode == 0
    for mode in ("auto", "run", "toggle", "stop"):
        assert mode in proc.stdout


def test_window_renders_without_opening_input_devices(tmp_path):
    pytest.importorskip("PySide6")
    image = tmp_path / "window.png"
    proc = subprocess.run(
        [sys.executable, str(HERE / "gw2_1button_gui.py"), "--gui-smoke-test", str(image)],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert proc.returncode == 0, proc.stderr
    assert image.stat().st_size > 10_000


def test_reforged_window_preset_renders_with_the_monk_profile(tmp_path):
    pytest.importorskip("PySide6")
    image = tmp_path / "gw1-window.png"
    proc = subprocess.run(
        [sys.executable, str(HERE / "gw2_1button_gui.py"), "--game", "gw1",
         "--gui-smoke-test", str(image)],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert proc.returncode == 0, proc.stderr
    assert image.stat().st_size > 10_000
