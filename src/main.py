"""حرارة (Harara): مراقب صادق لحرارة الجوال، مكتوب بـ Flet.

نفس الشاشات السبع بتاعة نسخة Kivy الأصلية: Welcome, Home, Alert, Suggested Actions,
Log, Apps, Settings. المنطق في monitor.py و core/ (مختبر بدون جوال).
"""
import asyncio
import os
import time
import traceback
from datetime import datetime, timedelta

import flet as ft
import flet_notifications as ftn

from core import actions, usage
from core.platform_info import current_platform
from core.rules import LEVEL_LABEL, LEVEL_ORDER, format_temp, suggestions_for
from core.sensors import make_sensor
from core.storage import Store
from monitor import Monitor

PLATFORM = current_platform()

NAVY = "#132839"
GREY = "#4A5A6D"
ORANGE = "#EA580C"
ORANGE_DARK = "#C2410B"
ORANGE_TEXT = "#9A3412"
TEAL = "#0F766E"
CREAM = "#FBFAF7"
CARD = "#F2F4F7"
WARM_CARD = "#FDF0E6"
MINT = "#E3F2EF"
WHITE = "#FFFFFF"
BAR = "#4D5C6E"
TRACK = "#F6E4D8"
LEVEL_COLOR = {"normal": TEAL, "warm": "#B45309", "hot": ORANGE, "critical": "#7F1D1D"}
LEVEL_BG = {"normal": "#D9F0EC", "warm": "#FBEBC8", "hot": "#FDE0CC", "critical": "#FDD9D9"}
W500, W600, W700 = ft.FontWeight.W_500, ft.FontWeight.W_600, ft.FontWeight.W_700

ALERT_ID, WEEKLY_ID = 10, 11
TICK_SECONDS = 3 if PLATFORM == "desktop" else 30


def clock_label(ts: float, minutes: bool = False) -> str:
    """'7pm' / '7:03pm' (بدون %-I عشان ويندوز)."""
    d = datetime.fromtimestamp(ts)
    hour = d.hour % 12 or 12
    ampm = "am" if d.hour < 12 else "pm"
    return f"{hour}:{d.minute:02d}{ampm}" if minutes else f"{hour}{ampm}"


def txt(value, size=16, weight=None, color=NAVY, **kw):
    return ft.Text(value, size=size, weight=weight, color=color, **kw)


def card(content, bgcolor=CARD, padding=16, radius=14, **kw):
    return ft.Container(content=content, bgcolor=bgcolor, border_radius=radius, padding=padding, **kw)


def pill(text, on_click, bg=NAVY, fg=WHITE, outline=False, expand=True, height=52):
    style = ft.ButtonStyle(
        bgcolor=None if outline else bg,
        color=fg if not outline else NAVY,
        shape=ft.RoundedRectangleBorder(radius=26),
        side=ft.BorderSide(1.5, NAVY) if outline else None,
        text_style=ft.TextStyle(size=16, weight=W600),
    )
    btn = ft.FilledButton(text, on_click=on_click, style=style, height=height, expand=expand)
    return btn


def stat(label, value):
    return card(
        ft.Column([txt(value, 22, W700), txt(label, 13, color=GREY)],
                  spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=12, expand=True,
    )


class HararaApp:
    def __init__(self, page: ft.Page, monitor: Monitor, notifications):
        self.page = page
        self.m = monitor
        self.store = monitor.store
        self.notifications = notifications
        self.screen = "home" if self.store.get_bool("onboarded") else "welcome"
        self.log_week = False
        self.session_message = ""
        self.app_name_field = ft.TextField(hint_text="App name, e.g. Game or Video", border_radius=12,
                                           bgcolor=WHITE, color=NAVY)
        self.pass_field = ft.TextField(hint_text="Passphrase (8+ characters)", password=True,
                                       can_reveal_password=True, border_radius=12, bgcolor=WHITE, color=NAVY)
        self.body = ft.Column(spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)
        self.nav = ft.NavigationBar(
            on_change=self._nav_changed, bgcolor=WHITE, indicator_color=MINT,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.THERMOSTAT_OUTLINED, selected_icon=ft.Icons.THERMOSTAT, label="Home"),
                ft.NavigationBarDestination(icon=ft.Icons.INSIGHTS_OUTLINED, selected_icon=ft.Icons.INSIGHTS, label="Log"),
                ft.NavigationBarDestination(icon=ft.Icons.APPS_OUTLINED, selected_icon=ft.Icons.APPS, label="Apps"),
                ft.NavigationBarDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label="Settings"),
            ],
        )

    # ---------- الإقلاع ----------
    def start(self):
        p = self.page
        p.title = "Harara"
        p.bgcolor = CREAM
        p.padding = 0
        p.theme = ft.Theme(color_scheme_seed=NAVY)
        p.theme_mode = ft.ThemeMode.LIGHT
        p.add(ft.SafeArea(expand=True, content=ft.Container(
            content=self.body, expand=True, padding=ft.Padding.symmetric(horizontal=20, vertical=16))))
        self.render()

    def toast(self, message: str):
        self.page.show_dialog(ft.SnackBar(content=ft.Text(message)))

    def go(self, name: str):
        self.screen = name
        self.render()

    def _nav_changed(self, e):
        self.go(["home", "log", "apps", "settings"][int(e.control.selected_index)])

    def render(self):
        builders = {"welcome": self.welcome_view, "home": self.home_view, "alert": self.alert_view,
                    "actions": self.actions_view, "log": self.log_view, "apps": self.apps_view,
                    "settings": self.settings_view}
        tabs = {"home": 0, "log": 1, "apps": 2, "settings": 3}
        if self.screen in tabs:
            self.nav.selected_index = tabs[self.screen]
            self.page.navigation_bar = self.nav
        else:
            self.page.navigation_bar = None
        self.body.controls = builders[self.screen]()
        self.page.update()

    # ---------- حلقة المراقبة ----------
    async def monitor_loop(self):
        while True:
            try:
                await self.do_tick()
            except Exception:  # noqa: BLE001
                print("tick error:", traceback.format_exc())
            await asyncio.sleep(TICK_SECONDS)

    async def do_tick(self):
        alert_reading = self.m.tick()
        if alert_reading is not None:
            await self.send_alert(alert_reading)
        elif self.screen in ("home", "alert", "actions"):
            self.render()

    async def send_alert(self, r):
        title, body = self.m.make_alert(r)
        try:
            await self.notifications.show(ALERT_ID, title=title, body=body)
        except Exception as ex:  # noqa: BLE001
            print(f"notification error: {ex}")
        if self.store.get_bool("auto_brightness") and PLATFORM == "android":
            self.toggle_brightness(True)
        if self.screen in ("home", "log", "apps"):
            self.screen = "alert"
        self.render()

    async def schedule_weekly(self):
        """تقرير أسبوعي: إشعار كل أحد 8 مساءً يذكّرك تفتح السجل."""
        try:
            if not self.store.get_bool("weekly_report"):
                await self.notifications.cancel(WEEKLY_ID)
                return
            now = datetime.now()
            when = now.replace(hour=20, minute=0, second=0, microsecond=0)
            when += timedelta(days=(6 - now.weekday()) % 7)
            if when <= now:
                when += timedelta(days=7)
            await self.notifications.schedule(
                WEEKLY_ID, when=when, title="Your weekly heat report",
                body="Open Harara to see how hot your phone got this week.",
                match_components=ftn.DateTimeComponents.DAY_OF_WEEK_AND_TIME)
        except Exception as ex:  # noqa: BLE001
            print(f"weekly report error: {ex}")

    # ---------- إجراءات ----------
    async def finish_onboarding(self, e=None):
        self.store.set("onboarded", True)
        try:
            await self.notifications.request_permissions()
        except Exception as ex:  # noqa: BLE001
            print(f"permission error: {ex}")
        await self.schedule_weekly()
        self.go("home")

    def toggle_brightness(self, on):
        self.m.brightness_lowered = bool(on)
        actions.set_brightness(0.4 if on else 1.0)

    def run_action(self, key):
        if key == "power_saver":
            actions.open_power_saver_settings()
        elif key == "heavy_apps":
            self.go("apps")

    def manage_apps(self, e=None):
        if usage.top_apps() == []:
            actions.open_usage_access_settings()
        else:
            actions.open_app_management()

    def open_actions(self, e=None):
        if self.m.actions_start is None and self.m.last and self.m.last.temp_c is not None:
            self.m.actions_start = self.m.last.temp_c
        self.go("actions")

    def dismiss_alert(self, e=None):
        self.go("home")

    # ---------- الأجزاء المشتركة ----------
    def header(self, title, back_to="home"):
        return ft.Row([
            ft.IconButton(icon=ft.Icons.ARROW_BACK, icon_color=NAVY, on_click=lambda e: self.go(back_to)),
            txt(title, 22, W700),
        ])

    def logo(self, size=84):
        return ft.Container(
            width=size, height=size, border_radius=size * 0.22, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=ft.Image(src="icon.png", width=size, height=size, fit=ft.BoxFit.COVER))

    # ---------- 1. الترحيب ----------
    def welcome_view(self):
        ios = PLATFORM == "ios"
        bullets = [
            "•  Live heat-level monitoring" if ios else "•  Live temperature monitoring",
            "•  Alert on screen when it gets Hot" if ios else "•  Alert when it passes your safe limit",
            "•  One-tap practical fixes",
            "•  Honest: it measures heat, it does not fake “cooling”",
        ]
        return [
            ft.Container(height=24),
            ft.Row([self.logo(110)], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([txt("Harara", 36, W700)], alignment=ft.MainAxisAlignment.CENTER),
            txt("Watch your phone… before it overheats", 17, color=GREY, text_align=ft.TextAlign.CENTER),
            ft.Container(height=8),
            card(ft.Column([txt(b, 15, color=NAVY) for b in bullets], spacing=10), padding=18),
            ft.Container(height=8),
            ft.Row([pill("Start monitoring", self.finish_onboarding, bg=ORANGE)]),
            txt("Allow notifications when asked, so Harara can warn you.", 13, color=GREY,
                text_align=ft.TextAlign.CENTER),
        ]

    # ---------- 2. الرئيسية ----------
    def gauge(self, size=230):
        m = self.m
        color = LEVEL_COLOR[m.level]
        return ft.Stack(width=size, height=size, controls=[
            ft.ProgressRing(value=1, width=size, height=size, stroke_width=16, color=TRACK, bgcolor=TRACK),
            ft.ProgressRing(value=m.gauge_frac, width=size, height=size, stroke_width=16, color=color,
                            bgcolor=TRACK, stroke_cap=ft.StrokeCap.ROUND),
            ft.Container(width=size, height=size, alignment=ft.Alignment.CENTER, content=ft.Column(
                [txt(m.temp_text, 48 if PLATFORM != "ios" else 40, W700),
                 txt("Battery temp" if PLATFORM != "ios" else "Heat level", 14, color=GREY),
                 ft.Container(content=txt(m.level_text, 14, W600, WHITE), bgcolor=color,
                              border_radius=14, padding=ft.Padding.symmetric(horizontal=12, vertical=3))],
                alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4)),
        ])

    def home_view(self):
        m = self.m
        return [
            ft.Row([self.logo(36), txt("Home", 22, W700)], spacing=10),
            ft.Row([self.gauge()], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([stat("Battery", m.battery_text), stat("Charger", m.charger_text),
                    stat(m.change_label, m.change_text)], spacing=10),
            card(txt(m.tip_text, 15, color=ORANGE_TEXT), bgcolor=WARM_CARD, padding=16),
            ft.Row([pill("See suggested actions", self.open_actions, bg=NAVY)]),
        ]

    # ---------- 3. التنبيه ----------
    def alert_view(self):
        m = self.m
        ios = PLATFORM == "ios"
        color = LEVEL_COLOR[m.level]
        return [
            ft.Container(height=16),
            ft.Container(bgcolor=LEVEL_BG[m.level], border_radius=24, padding=22, content=ft.Column([
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=color, size=40),
                txt(m.alert_big, 64, W700, color),
                txt("Alerts at: Hot or Critical" if ios else "Safe limit: " + m.limit_text, 15, color=GREY),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4), alignment=ft.Alignment.CENTER),
            card(ft.Column([
                ft.Row([txt("Harara · now", 12, color=GREY)]),
                txt(m.alert_title or "Your phone is hot", 17, W700),
                txt(m.alert_body, 14, color=GREY),
                ft.Row([pill("See fixes", self.open_actions, bg=ORANGE, height=44),
                        pill("Dismiss", self.dismiss_alert, outline=True, height=44)], spacing=10),
            ], spacing=8), bgcolor=WHITE, padding=16, border=ft.Border.all(1, "#E2E6EC")),
            txt("Tip: keep the phone out of direct sunlight", 14, color=GREY, text_align=ft.TextAlign.CENTER),
        ]

    # ---------- 4. الإجراءات المقترحة ----------
    def actions_view(self):
        m = self.m
        rows = []
        n_apps = len(usage.top_apps() or [])
        for s in suggestions_for(m.last, m.brightness_lowered, heavy_apps=n_apps) if m.last else []:
            kind = s.kind
            if kind == "toggle" and PLATFORM != "android":
                kind = "tip"            # تغيير السطوع من التطبيق متاح على أندرويد فقط
                s.title, s.detail = "Lower your brightness", "Swipe down for Control Center and dim the screen."
            if kind == "toggle":
                trailing = ft.Switch(value=m.brightness_lowered, active_color=ORANGE,
                                     on_change=lambda e: self.toggle_brightness(e.control.value))
            elif kind == "button":
                trailing = ft.FilledButton("Open" if s.key == "power_saver" else "View",
                                           on_click=lambda e, k=s.key: self.run_action(k),
                                           style=ft.ButtonStyle(bgcolor=NAVY, color=WHITE))
            else:
                trailing = txt("Tip", 13, color=GREY)
            rows.append(card(ft.Row([
                ft.Column([txt(s.title, 16, W600), txt(s.detail, 13, color=GREY)], spacing=2, expand=True),
                trailing], vertical_alignment=ft.CrossAxisAlignment.CENTER)))
        return [
            self.header("Suggested Actions"),
            *rows,
            card(ft.Column([
                txt("Now", 13, color=GREY),
                txt(m.temp_text, 34, W700, LEVEL_COLOR[m.level]),
                txt(m.after_text(), 14, color=GREY)], spacing=2), bgcolor=MINT, padding=18),
        ]

    # ---------- 5. السجل ----------
    def log_data(self):
        m, store = self.m, self.store
        ios = PLATFORM == "ios"
        now = time.time()
        if self.log_week:
            since, step, n = now - 7 * 86400, 86400, 7
            labels = [datetime.fromtimestamp(since + i * step + step).strftime("%a") for i in (0, 3, 6)]
        else:
            since, step, n = now - 86400, 7200, 12
            labels = [clock_label(since + i * step) for i in (0, 4, 8, 11)]
        if ios:
            lo, hi, limit = 0, 4, 3
            values = [None if lv is None else LEVEL_ORDER.index(lv) + 1
                      for lv in store.level_buckets(since, step, n)]
            st = store.level_stats(since)
            stats = [("Hottest level", LEVEL_LABEL[st["peak"]] if st["peak"] else "--"),
                     ("Time hot", "--" if st["hot_share"] is None else f"{st['hot_share'] * 100:.0f}%"),
                     ("Alerts", str(st["alerts"]))]
            if st["hottest"]:
                ts, level, charging = st["hottest"]
                hot_when = f"{clock_label(ts, True)} · {'while charging' if charging else 'on battery'}"
                hot_val = LEVEL_LABEL[level]
            else:
                hot_when, hot_val = "No data yet", ""
        else:
            lo, hi, limit = 25, 50, m.policy.limit_c
            values = store.buckets(since, step, n)
            st = store.stats(since)
            stats = [("Peak", format_temp(st["peak"], m.unit, False) if st["peak"] else "--"),
                     ("Average", format_temp(st["avg"], m.unit, False) if st["avg"] else "--"),
                     ("Alerts", str(st["alerts"]))]
            if st["hottest"]:
                ts, temp, charging = st["hottest"]
                hot_when = f"{clock_label(ts, True)} · {'while charging' if charging else 'on battery'}"
                hot_val = format_temp(temp, m.unit, False)
            else:
                hot_when, hot_val = "No data yet", ""
        return values, lo, hi, limit, labels, stats, hot_when, hot_val

    def bar_chart(self, values, lo, hi, limit, height=150):
        span = hi - lo
        bars = []
        for v in values:
            if v is None:
                h = 0
                color = BAR
            else:
                h = max(4, height * (min(v, hi) - lo) / span)
                color = ORANGE if v >= limit else BAR
            bars.append(ft.Container(expand=True, height=h, bgcolor=color if h else None,
                                     border_radius=ft.BorderRadius.only(top_left=4, top_right=4)))
        limit_y = height * (limit - lo) / span
        return ft.Stack(height=height, controls=[
            ft.Row(bars, spacing=5, vertical_alignment=ft.CrossAxisAlignment.END, left=0, right=0, bottom=0),
            ft.Container(height=1.5, bgcolor=ORANGE_DARK, left=0, right=0, bottom=max(0, limit_y - 0.75)),
        ])

    def set_log_range(self, week: bool):
        self.log_week = week
        self.render()

    def log_view(self):
        values, lo, hi, limit, labels, stats, hot_when, hot_val = self.log_data()
        ios = PLATFORM == "ios"

        def tab(label, week):
            on = self.log_week == week
            return ft.Container(
                content=txt(label, 15, W600, WHITE if on else NAVY, text_align=ft.TextAlign.CENTER),
                bgcolor=NAVY if on else CARD, border_radius=20, padding=ft.Padding.symmetric(vertical=8),
                expand=True, on_click=lambda e: self.set_log_range(week))

        return [
            txt("Heat Log" if ios else "Temperature Log", 22, W700),
            ft.Row([tab("Today", False), tab("Week", True)], spacing=8),
            card(ft.Column([
                self.bar_chart(values, lo, hi, limit),
                ft.Row([txt(l, 12, color=GREY) for l in labels], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ], spacing=6), bgcolor=WHITE, padding=16, border=ft.Border.all(1, "#E2E6EC")),
            ft.Row([stat(label, value) for label, value in stats], spacing=10),
            card(ft.Row([
                ft.Column([txt("Hottest moment", 13, color=GREY), txt(hot_when, 15, W600)], spacing=2, expand=True),
                txt(hot_val, 26, W700, ORANGE_TEXT)], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=WARM_CARD),
        ]

    # ---------- 6. التطبيقات ----------
    def toggle_session(self, e=None):
        self.session_message = self.m.toggle_session(self.app_name_field.value)
        if self.m.store.active_session() is None:
            self.app_name_field.value = ""
        self.render()

    def apps_view(self):
        m = self.m
        ios = PLATFORM == "ios"
        apps = usage.top_apps()
        rows = []
        if apps is None:
            note = ("iPhone does not let apps see how other apps use power. "
                    "Open Settings › Battery to see the list.")
        elif not apps:
            note = "Allow “Usage access” for Harara to see which apps you used most."
        else:
            note = "Screen time in the last hour"
            colors = [ORANGE, "#B45309", "#6B7F95", "#6B7F95"]
            for i, a in enumerate(apps):
                rows.append(card(ft.Column([
                    ft.Row([txt(a.name, 15, W600, expand=True), txt(f"{a.minutes:.0f} min", 14, color=GREY)]),
                    ft.ProgressBar(value=a.share, color=colors[min(i, 3)], bgcolor=TRACK, bar_height=8,
                                   border_radius=4)], spacing=6), padding=12))
        active = self.store.active_session()
        if self.session_message:
            status = self.session_message
        elif active:
            status = f"Running: {active[1]} since {clock_label(active[2], True)}"
        else:
            status = "Not running."
        sessions = [card(ft.Column([txt(t, 15, W600), txt(d, 13, color=GREY)], spacing=2), padding=12)
                    for t, d in m.session_lines(6)]
        return [
            txt("Power-Hungry Apps", 22, W700),
            txt(note, 14, color=GREY),
            *rows,
            txt("Track an app", 17, W700),
            txt("Start, use the app, then stop. Harara records heat and battery during it. "
                "iPhone Shortcuts: open harara://start?app=Name or harara://stop.", 13, color=GREY),
            self.app_name_field,
            ft.Row([pill("Stop session" if active else "Start session", self.toggle_session, bg=NAVY, height=46)]),
            txt(status, 13, color=GREY),
            *sessions,
            ft.Row([pill("Open iPhone Settings" if ios else "Manage apps in Settings", self.manage_apps,
                         outline=True, height=46)]),
        ]

    # ---------- 7. الإعدادات ----------
    def settings_view(self):
        m, s = self.m, self.store
        ios = PLATFORM == "ios"

        def switch_row(title, key, on_change=None):
            def changed(e):
                m.set_setting(key, e.control.value)
                if on_change:
                    self.page.run_task(on_change)
            return ft.Row([txt(title, 16, expand=True),
                           ft.Switch(value=s.get_bool(key), active_color=ORANGE, on_change=changed)])

        limit_label = txt(m.limit_text, 20, W700, ORANGE_TEXT)

        def slide(e):
            value = round(e.control.value)
            m.set_limit(value)
            limit_label.value = m.limit_text
            limit_label.update()

        items = []
        if not ios:
            items.append(card(ft.Column([
                ft.Row([txt("Alert limit", 16, W600, expand=True), limit_label]),
                ft.Slider(min=35, max=48, divisions=13, value=s.get_float("limit_c"),
                          active_color=ORANGE, on_change=slide)], spacing=0)))
        items.append(card(ft.Column([
            *([switch_row("Auto-lower brightness when hot", "auto_brightness")] if PLATFORM == "android" else []),
            switch_row("Alert while charging", "alert_while_charging"),
            switch_row("Weekly report", "weekly_report", self.schedule_weekly),
        ], spacing=6)))
        if not ios:
            def unit_changed(e):
                m.set_unit("F" if "F" in e.control.selected else "C")
                self.render()
            items.append(card(ft.Row([
                txt("Unit", 16, expand=True),
                ft.SegmentedButton(selected=[m.unit], allow_empty_selection=False, on_change=unit_changed,
                                   segments=[ft.Segment(value="C", label=ft.Text("°C")),
                                             ft.Segment(value="F", label=ft.Text("°F"))])])))

        status = txt(m.backup_status, 13, color=GREY)

        def export(e):
            status.value = m.export_backup(self.pass_field.value or "")
            status.update()

        items.append(card(ft.Column([
            txt("Encrypted backup (AES-256)", 16, W600),
            self.pass_field,
            ft.Row([pill("Export", export, bg=NAVY, height=44)]),
            status], spacing=8)))
        note = ("On iPhone, Apple only shares a heat level (Normal, Warm, Hot, Critical), not a temperature, "
                "so there is no °C limit to set: Harara alerts at Hot or Critical. iPhone also pauses Harara "
                "when you leave it, so checks and alerts happen while the app is open."
                if ios else
                "Harara checks and alerts while the app is open. When you leave the app, the phone may pause it, "
                "so keep Harara open while you game or charge. On iPhone, Apple only shares a heat level "
                "(Normal, Warm, Hot, Critical), so alerts use that level instead of a number.")
        return [txt("Settings", 22, W700), *items, txt(note, 12, color=GREY)]


def data_dir() -> str:
    path = os.environ.get("FLET_APP_STORAGE_DATA") or os.path.join(os.path.expanduser("~"), ".harara")
    os.makedirs(path, exist_ok=True)
    return path


def error_view(page: ft.Page, err: str):
    page.add(ft.SafeArea(content=ft.Column(
        [ft.Text("Harara could not start:", size=18, weight=W700),
         ft.Text(err, size=11, selectable=True)], scroll=ft.ScrollMode.AUTO, expand=True)))
    page.update()


async def main(page: ft.Page):
    try:
        folder = data_dir()
        store = Store(os.path.join(folder, "harara.db"))
        store.prune(30)
        monitor = Monitor(store, make_sensor(), PLATFORM, folder)
        notifications = ftn.Notifications()
        app = HararaApp(page, monitor, notifications)
        app.start()
        page.run_task(app.monitor_loop)
    except Exception:  # noqa: BLE001
        error_view(page, traceback.format_exc())


if __name__ == "__main__":
    ft.run(main)
