"""يبني كل الشاشات بصفحة وهمية: يمسك أخطاء أسماء/معاملات Flet قبل ما نبني التطبيق."""
import asyncio

import flet as ft
import pytest

import main as app_main
from core.sensors import SimulatedSensor
from core.storage import Store
from monitor import Monitor


class FakePage:
    def __init__(self):
        self.navigation_bar = None
        self.dialogs = []

    def update(self):
        pass

    def add(self, *c):
        pass

    def show_dialog(self, d):
        self.dialogs.append(d)

    def run_task(self, fn, *a):
        pass


class FakeNotes:
    def __init__(self):
        self.shown = []

    async def show(self, id, **kw):
        self.shown.append(kw)

    async def schedule(self, *a, **kw):
        pass

    async def cancel(self, *a, **kw):
        pass

    async def request_permissions(self):
        return True


def make(tmp_path, platform):
    store = Store(":memory:")
    m = Monitor(store, SimulatedSensor(start_c=44, seed=1), platform, str(tmp_path))
    app_main.PLATFORM = platform
    notes = FakeNotes()
    return app_main.HararaApp(FakePage(), m, notes), m, notes


@pytest.mark.parametrize("platform", ["android", "ios", "desktop"])
def test_every_screen_builds(tmp_path, platform):
    app, m, notes = make(tmp_path, platform)
    for _ in range(3):
        m.tick()
    for screen in ["welcome", "home", "alert", "actions", "log", "apps", "settings"]:
        app.screen = screen
        app.render()
        assert app.body.controls, screen


def test_alert_goes_to_notification_and_alert_screen(tmp_path):
    app, m, notes = make(tmp_path, "android")
    m.sensor.temp_c = 46
    app.screen = "home"
    asyncio.run(app.do_tick())
    assert notes.shown and "hot" in notes.shown[0]["title"].lower()
    assert app.screen == "alert"
    assert m.store.stats(0)["alerts"] == 1


def test_session_and_backup(tmp_path):
    app, m, _ = make(tmp_path, "android")
    m.tick()
    assert "Type the app name" in m.toggle_session("")
    assert "Started" in m.toggle_session("Game")
    m.tick()
    assert m.toggle_session("") == "Session saved."
    assert m.session_lines()
    assert "at least 8" in m.export_backup("short")
    assert "Saved" in m.export_backup("long enough pass")
