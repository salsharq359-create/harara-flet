"""منطق حرارة بدون أي واجهة: يقرأ الحساس، يخزّن، ويقرر النصوص والتنبيهات.

مأخوذ من HararaApp الأصلية (Kivy)، وصار مستقل عن الواجهة عشان نختبره بدون جوال.
"""
import os
import time

from core import packet
from core.algorithms import RollingWindow
from core.rules import (LAPTOP_HOT_FROM, LEVEL_LABEL, LEVEL_ORDER, AlertPolicy,
                        format_temp, is_over_limit, suggestions_for)
from core.sessions import summarize

FAST_RISE_C = 5.0          # ارتفاع 5° خلال 10 دقايق = تحذير مبكر


class Monitor:
    def __init__(self, store, sensor, platform: str, data_dir: str):
        self.store = store
        self.sensor = sensor
        self.platform = platform
        self.data_dir = data_dir
        self.policy = AlertPolicy(limit_c=store.get_float("limit_c"),
                                  alert_while_charging=store.get_bool("alert_while_charging"))
        self.unit = store.get("unit")
        self.window = RollingWindow(span_s=600)
        self.last = None
        self.actions_start = None
        self.brightness_lowered = False
        self.backup_status = "Readings are compressed, checked with CRC-32 and encrypted with your passphrase."
        # نصوص الواجهة
        self.temp_text = "--"
        self.level = "normal"
        self.level_text = "Normal"
        self.battery_text = "--"
        self.charger_text = "--"
        self.change_label = "Last hour"
        self.change_text = "--"
        self.tip_text = ""
        self.gauge_frac = 0.0
        self.alert_big = "--"
        self.alert_title = ""
        self.alert_body = ""

    @property
    def is_ios(self) -> bool:
        return self.platform == "ios"

    @property
    def is_windows(self) -> bool:
        return self.platform == "windows"

    @property
    def limit_text(self) -> str:
        return format_temp(self.policy.limit_c, self.unit)

    # ---------- حلقة المراقبة ----------
    def tick(self):
        """قراءة وحدة. يرجع Reading إذا لازم نرسل تنبيه، وإلا None."""
        r = self.sensor.read()
        self.last = r
        self.store.add_reading(r)
        self.level = r.level
        self.level_text = LEVEL_LABEL[r.level]
        no_laptop_temp = self.is_windows and r.temp_c is None
        if no_laptop_temp:
            self.level_text = "Unknown"         # never pretend: Windows did not share a temperature
        self.temp_text = (format_temp(r.temp_c, self.unit, False) if r.temp_c is not None
                          else "--" if no_laptop_temp else self.level_text)
        low, span = (30, 65.0) if self.is_windows else (25, 25.0)
        self.gauge_frac = (min(max((r.temp_c - low) / span, 0.04), 1) if r.temp_c is not None
                           else 0.0 if no_laptop_temp
                           else [0.25, 0.5, 0.75, 1.0][LEVEL_ORDER.index(r.level)])
        self.battery_text = f"{r.battery_pct}%" if r.battery_pct is not None else "--"
        self.charger_text = "Plugged" if r.charging else "Battery"
        if self.is_ios:
            peak = self.store.level_stats(time.time() - 3600)["peak"]
            self.change_label = "Hottest (1h)"
            self.change_text = LEVEL_LABEL[peak] if peak else "--"
        else:
            self.change_label = "Last hour"
            change = self.store.temp_change(3600)
            self.change_text = "--" if change is None else f"{change:+.0f}°"
        self.window.push(r.timestamp, r.temp_c)
        rise = self.window.rise()
        tips = suggestions_for(r, self.brightness_lowered)
        if no_laptop_temp:
            self.tip_text = ("This laptop does not share its temperature with apps, so Harara shows "
                             "battery and charger only. Running Harara as administrator may help.")
        elif is_over_limit(r, self.policy.limit_c):
            self.tip_text = f"{tips[0].title}. {tips[0].detail}"
        elif rise is not None and rise >= FAST_RISE_C:
            self.tip_text = (f"Heating fast: +{rise:.0f}° in 10 min. "
                             f"{tips[0].title} before it reaches {self.limit_text}.")
        else:
            self.tip_text = ("All good. Harara checks every 30 seconds while it is open."
                             if self.is_ios else
                             "All good. Harara checks every 30 seconds while it is open.")
        return r if self.policy.should_alert(r) else None

    def after_text(self) -> str:
        r = self.last
        if self.actions_start is not None and r is not None and r.temp_c is not None:
            return (f"Started at {format_temp(self.actions_start, self.unit)}, "
                    f"now {format_temp(r.temp_c, self.unit)}")
        if self.is_ios:
            return "Apply the actions and watch the heat level here."
        return "Apply the actions and watch the temperature drop here."

    def make_alert(self, r):
        """يجهّز نص التنبيه ويسجله. يرجع (العنوان، النص)."""
        self.policy.mark_sent(r.timestamp)
        self.store.add_alert(r)
        self.alert_big = (format_temp(r.temp_c, self.unit, False) if r.temp_c is not None
                          else LEVEL_LABEL[r.level])
        if r.temp_c is not None and self.is_windows:
            self.alert_title = f"Your laptop is hot: {format_temp(r.temp_c, self.unit)}"
            self.alert_body = (f"Heat level {LEVEL_LABEL[r.level]} (hot from {LAPTOP_HOT_FROM:.0f}°C). "
                               "Close heavy programs and keep the vents clear.")
        elif r.temp_c is not None:
            self.alert_title = f"Your phone is hot: {format_temp(r.temp_c, self.unit)}"
            self.alert_body = (f"Above the safe limit ({self.limit_text}). "
                               "Open Harara for suggested actions.")
        else:
            self.alert_title = f"Heat level: {LEVEL_LABEL[r.level]}"
            self.alert_body = "Your iPhone is running hot. Open Harara for suggested actions."
        return self.alert_title, self.alert_body

    # ---------- إجراءات المستخدم ----------
    def set_limit(self, value) -> None:
        value = round(value)
        self.store.set("limit_c", value)
        self.policy.limit_c = value

    def set_setting(self, key: str, value) -> None:
        self.store.set(key, bool(value))
        if key == "alert_while_charging":
            self.policy.alert_while_charging = bool(value)
        if key == "tracking_allowed":
            self.store.set("tracking_asked", True)
            active = self.store.active_session()
            if not value and active:            # turning tracking off ends a running session
                r = self.sensor.read()
                self.store.add_reading(r)
                self.store.end_session(active[0], r)

    def set_unit(self, unit: str) -> None:
        self.unit = unit
        self.store.set("unit", unit)

    def toggle_session(self, name: str) -> str:
        """يبدأ جلسة للتطبيق المكتوب أو يوقف الشغالة. يرجع رسالة الحالة."""
        active = self.store.active_session()
        if active:
            r = self.sensor.read()
            self.store.add_reading(r)
            self.store.end_session(active[0], r)
            return "Session saved."
        name = (name or "").strip()
        if not name:
            return "Type the app name first, then start."
        if not self.store.get_bool("tracking_allowed"):
            return "Allow tracking first."
        r = self.sensor.read()
        self.store.add_reading(r)
        self.store.start_session(name, r)
        return f"Started: {name}. Keep Harara open while you use it."

    def session_lines(self, limit: int = 6) -> list:
        out = []
        for s in self.store.recent_sessions(limit):
            m = summarize(s["name"], s["start"], s["end"], s["start_temp"], s["end_temp"],
                          s["peak"], s["start_batt"], s["end_batt"], s["charged"])
            parts = [f"{m.minutes:.0f} min"]
            if m.temp_rise is not None:
                parts.append(f"heat {m.temp_rise:+.1f}°")
            if m.peak_temp is not None:
                parts.append(f"peak {m.peak_temp:.0f}°")
            elif s["start_temp"] is None:
                parts.append("iPhone: heat as level only")
            if m.drain_per_hour is not None:
                parts.append(f"battery -{m.drain_per_hour:.0f}%/h")
            elif m.battery_drop is None:
                parts.append("charged during session")
            out.append((m.name, " · ".join(parts)))
        return out

    def export_backup(self, passphrase: str) -> str:
        if len(passphrase) < 8:
            self.backup_status = "Use a passphrase of at least 8 characters."
            return self.backup_status
        rows = self.store.db.execute(
            "SELECT CAST(ts AS INTEGER), temp_c, battery, charging FROM readings ORDER BY ts").fetchall()
        seen, readings = set(), []
        for ts, temp, batt, chg in rows:
            if ts not in seen:
                seen.add(ts)
                readings.append((ts, temp, batt, bool(chg)))
        path = os.path.join(self.data_dir, time.strftime("harara-backup-%Y%m%d.harara"))
        try:
            size = packet.export_backup(readings, passphrase, path)
        except ImportError:
            self.backup_status = "Encrypted backup is not available in this build."
            return self.backup_status
        self.backup_status = (f"Saved {len(readings):,} readings in {size / 1024:.1f} KB: "
                              f"{os.path.basename(path)}")
        return self.backup_status
