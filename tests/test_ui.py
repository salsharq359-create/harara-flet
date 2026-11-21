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
    m.set_setting("tracking_allowed", True)
    assert "Started" in m.toggle_session("Game")
    m.tick()
    assert m.toggle_session("") == "Session saved."
    assert m.session_lines()
    assert "at least 8" in m.export_backup("short")
    assert "Saved" in m.export_backup("long enough pass")


def test_tracking_permission_window(tmp_path):
    app, m, _ = make(tmp_path, "ios")
    page = app.page
    page.popped = 0
    page.pop_dialog = lambda: setattr(page, "popped", page.popped + 1)
    app.screen = "apps"
    app.render()                                      # first visit: Harara asks once
    assert len(page.dialogs) == 1
    dlg = page.dialogs[0]
    assert "track app sessions" in dlg.title.value
    app.render()                                      # no second window while it is open
    assert len(page.dialogs) == 1

    # starting before allowing is refused by the logic layer
    assert m.toggle_session("Game") == "Allow tracking first."

    # "Allow" (second action) saves the choice; a typed name then starts
    app.app_name_field.value = "Game"
    dlg.actions[1].on_click(None)
    assert m.store.get_bool("tracking_allowed") and m.store.get_bool("tracking_asked")
    assert page.popped == 1
    app.toggle_session()
    assert m.store.active_session() is not None

    # turning it off in Settings ends the running session
    m.set_setting("tracking_allowed", False)
    assert m.store.active_session() is None


def test_start_without_permission_opens_window_then_starts(tmp_path):
    app, m, _ = make(tmp_path, "android")
    page = app.page
    page.pop_dialog = lambda: None
    m.store.set("tracking_asked", True)               # asked before, said "Not now"
    app.app_name_field.value = "Video"
    app.toggle_session()
    assert page.dialogs and m.store.active_session() is None
    page.dialogs[-1].actions[1].on_click(None)        # Allow -> the waiting session starts
    assert m.store.active_session()[1] == "Video"


def test_stat_values_stay_on_one_line():
    card = app_main.stat("Charger", "Battery")
    value = card.content.controls[0]
    assert value.max_lines == 1 and value.size < 22


def test_iphone_settings_explain_shortcuts(tmp_path):
    def all_text(controls):
        out = []
        for c in controls:
            if isinstance(c, ft.Text):
                out.append(c.value)
            for attr in ("content", "controls"):
                v = getattr(c, attr, None)
                if v is None:
                    continue
                out += all_text(v if isinstance(v, list) else [v])
        return out

    app, _, _ = make(tmp_path, "ios")
    app.screen = "settings"
    app.render()
    assert "Open Harara automatically" in all_text(app.body.controls)
    app2, _, _ = make(tmp_path, "android")
    app2.screen = "settings"
    app2.render()
    assert "Open Harara automatically" not in all_text(app2.body.controls)
