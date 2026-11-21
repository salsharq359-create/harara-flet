"""Read the phone's temperature, battery and charging state.

- Android: exact battery temperature from the ACTION_BATTERY_CHANGED intent
  (BatteryManager.EXTRA_TEMPERATURE, tenths of °C) via Pyjnius, plus the
  system thermal status (PowerManager, Android 10+).
- iPhone: Apple gives no number, only NSProcessInfo.thermalState
  (nominal / fair / serious / critical) via Pyobjus, plus UIDevice battery info.
- Windows laptop: battery % and charger from GetSystemPowerStatus (kernel32), and the
  laptop's ACPI thermal zone from WMI when Windows shares it (often it needs admin
  rights or is missing; then Harara says so instead of guessing).
- Desktop (Linux/Mac, tests): a simulator for development.
"""
import math
import random
import subprocess
import time

from .platform_info import android_activity, current_platform
from .rules import (Reading, acpi_to_c, level_from_android_thermal_status,
                    level_from_ios_thermal_state, level_from_laptop_temp,
                    level_from_temp, worst_level)


class AndroidSensor:
    source = "android"

    def __init__(self):
        from jnius import autoclass
        self._autoclass = autoclass
        self.Intent = autoclass("android.content.Intent")
        self.IntentFilter = autoclass("android.content.IntentFilter")
        self.BatteryManager = autoclass("android.os.BatteryManager")
        self.Context = autoclass("android.content.Context")
        self.VERSION = autoclass("android.os.Build$VERSION")
        self._filter = self.IntentFilter(self.Intent.ACTION_BATTERY_CHANGED)

    def _context(self):
        return android_activity()

    def read(self) -> Reading:
        ctx = self._context()
        intent = ctx.registerReceiver(None, self._filter)   # sticky broadcast, no receiver needed
        bm = self.BatteryManager
        temp_c = intent.getIntExtra(bm.EXTRA_TEMPERATURE, -1000) / 10.0
        level = intent.getIntExtra(bm.EXTRA_LEVEL, -1)
        scale = intent.getIntExtra(bm.EXTRA_SCALE, 100) or 100
        plugged = intent.getIntExtra(bm.EXTRA_PLUGGED, 0) > 0

        heat = level_from_temp(temp_c) if temp_c > -100 else None
        if self.VERSION.SDK_INT >= 29:                       # Android 10+
            pm = ctx.getSystemService(self.Context.POWER_SERVICE)
            heat = worst_level(heat, level_from_android_thermal_status(pm.getCurrentThermalStatus()))

        return Reading(timestamp=time.time(),
                       temp_c=temp_c if temp_c > -100 else None,
                       level=heat or "normal",
                       battery_pct=int(level * 100 / scale) if level >= 0 else None,
                       charging=plugged, source=self.source)


class IOSSensor:
    source = "ios"

    def __init__(self):
        from pyobjus import autoclass
        from pyobjus.dylib_manager import INCLUDE, load_framework
        try:
            load_framework(INCLUDE.Foundation)
        except Exception:          # UIKit محمّل أصلًا، و INCLUDE ما فيه UIKit
            pass
        self.process_info = autoclass("NSProcessInfo").processInfo()
        self.device = autoclass("UIDevice").currentDevice()
        self.device.setBatteryMonitoringEnabled_(True)

    @staticmethod
    def _get(obj, name, default):
        """pyobjus exposes Objective-C properties as plain values, not methods."""
        try:
            value = getattr(obj, name)
            return value() if callable(value) else value
        except Exception as exc:
            print(f"[harara] could not read {name}: {exc}")
            return default

    def read(self) -> Reading:
        state = int(self._get(self.process_info, "thermalState", 0))
        battery = float(self._get(self.device, "batteryLevel", -1.0))      # -1.0 when unknown
        battery_state = int(self._get(self.device, "batteryState", 0))     # 2 = charging, 3 = full
        return Reading(timestamp=time.time(), temp_c=None,
                       level=level_from_ios_thermal_state(state),
                       battery_pct=int(battery * 100) if battery >= 0 else None,
                       charging=battery_state in (2, 3), source=self.source)


class WindowsSensor:
    source = "windows"
    THERMAL_QUERY = ("(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
                     "-ErrorAction Stop | Measure-Object -Property CurrentTemperature -Maximum).Maximum")

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class SystemPowerStatus(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                        ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]

        self._ctypes = ctypes
        self._status_type = SystemPowerStatus
        self._kernel32 = ctypes.windll.kernel32
        self.temp_supported = True          # becomes False after the first failed WMI read

    def _power(self):
        status = self._status_type()
        if not self._kernel32.GetSystemPowerStatus(self._ctypes.byref(status)):
            return None, False
        no_battery = status.BatteryFlag == 128 or status.BatteryLifePercent == 255
        return (None if no_battery else int(status.BatteryLifePercent)), status.ACLineStatus == 1

    def _temperature(self):
        if not self.temp_supported:
            return None
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", self.THERMAL_QUERY],
                capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            temp = acpi_to_c(float(out.stdout.strip()))
            if temp is None:
                raise ValueError(out.stdout.strip())
            return temp
        except Exception as exc:  # noqa: BLE001  (no admin rights, no sensor, no PowerShell)
            print(f"[harara] laptop temperature not available: {exc}")
            self.temp_supported = False
            return None

    def read(self) -> Reading:
        battery, plugged = self._power()
        temp = self._temperature()
        return Reading(timestamp=time.time(), temp_c=temp,
                       level=level_from_laptop_temp(temp) if temp is not None else "normal",
                       battery_pct=battery, charging=plugged, source=self.source)


class SimulatedSensor:
    """Smooth, realistic-looking values for demos on a laptop."""
    source = "desktop"

    def __init__(self, start_c: float = 36.0, seed: int | None = None):
        self._rng = random.Random(seed)
        self.temp_c = start_c
        self.battery = 68
        self.charging = True
        self._t0 = time.time()

    def read(self) -> Reading:
        t = time.time() - self._t0
        target = 39.5 + 3.5 * math.sin(t / 40.0) + (1.5 if self.charging else 0.0)
        self.temp_c += (target - self.temp_c) * 0.25 + self._rng.uniform(-0.3, 0.3)
        if self.charging:
            self.battery = min(100, self.battery + 1)
        else:
            self.battery = max(5, self.battery - 1)
        return Reading(timestamp=time.time(), temp_c=round(self.temp_c, 1),
                       level=level_from_temp(self.temp_c), battery_pct=self.battery,
                       charging=self.charging, source=self.source)


def make_sensor():
    """Pick the right sensor for the platform; fall back to the simulator."""
    plat = current_platform()
    try:
        if plat == "android":
            return AndroidSensor()
        if plat == "ios":
            return IOSSensor()
        if plat == "windows":
            return WindowsSensor()
    except Exception as exc:          # keep the app usable if a native call fails
        print(f"[harara] native sensor unavailable ({exc}); using simulator")
    return SimulatedSensor()
