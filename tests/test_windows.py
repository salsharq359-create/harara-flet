"""Laptop (Windows) version: rules and screens, tested without Windows."""
import time

import pytest

import main as app_main
from core import sensors
from core.rules import (Reading, acpi_to_c, is_over_limit, level_from_laptop_temp)
from core.storage import Store
from monitor import Monitor
from test_ui import FakeNotes, FakePage


class FakeLaptop:
    """Behaves like WindowsSensor: source 'windows', temperature may be missing."""
    source = "windows"

    def __init__(self, temp_c):
        self.temp_c = temp_c

    def read(self):
        t = self.temp_c
        level = level_from_laptop_temp(t) if t is not None else "normal"
        return Reading(time.time(), t, level, 55, False, "windows")


def make(tmp_path, temp_c):
    m = Monitor(Store(":memory:"), FakeLaptop(temp_c), "windows", str(tmp_path))
    app_main.PLATFORM = "windows"
    return app_main.HararaApp(FakePage(), m, FakeNotes()), m


def test_acpi_conversion():
    assert acpi_to_c(3232) == 50.1           # 323.2 K
    assert acpi_to_c(0) is None              # nonsense values are rejected
    assert acpi_to_c(2731.5 + 2000) is None  # 200 °C is not believable


def test_laptop_bands_and_limit():
    assert level_from_laptop_temp(60) == "normal"
    assert level_from_laptop_temp(72) == "warm"
    assert level_from_laptop_temp(88) == "hot"
    warm_laptop = Reading(0, 60.0, "normal", 50, False, "windows")
    assert not is_over_limit(warm_laptop, 40)          # the phone's 40 °C limit does not apply
    assert is_over_limit(Reading(0, 88.0, "hot", 50, False, "windows"), 40)


@pytest.mark.parametrize("temp", [None, 62.0, 90.0])
def test_every_laptop_screen_builds(tmp_path, temp):
    app, m = make(tmp_path, temp)
    for _ in range(3):
        m.tick()
    for screen in ["welcome", "home", "alert", "actions", "log", "apps", "settings"]:
        app.screen = screen
        app.render()
        assert app.body.controls, screen


def test_laptop_without_sensor_is_honest(tmp_path):
    app, m = make(tmp_path, None)
    m.tick()
    assert m.temp_text == "--" and m.level_text == "Unknown"
    assert "does not share" in m.tip_text
    assert app.gauge_caption() == "Not shared"


def test_hot_laptop_alerts(tmp_path):
    app, m = make(tmp_path, 90.0)
    r = m.tick()
    assert r is not None
    title, _ = m.make_alert(r)
    assert title.startswith("Your laptop is hot")


def test_windows_sensor_turns_off_after_failed_read(monkeypatch):
    s = sensors.WindowsSensor.__new__(sensors.WindowsSensor)
    s.temp_supported = True

    def boom(*a, **k):
        raise PermissionError("Access denied")
    monkeypatch.setattr(sensors.subprocess, "run", boom)
    assert s._temperature() is None and s.temp_supported is False
    assert s._temperature() is None                     # no second PowerShell call
