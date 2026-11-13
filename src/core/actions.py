"""أشياء يقدر التطبيق يسويها فعلًا لتقليل الحرارة، حسب المنصة.

حدود صادقة:
- يقدر يخفّض سطوع الشاشة وهو مفتوح (أندرويد فقط هنا). على الآيفون نفتح الإعدادات بدل ما نغيّر السطوع.
- ما يقدر يشغّل توفير الطاقة بنفسه: يفتح شاشة النظام.
- ما يقدر يقفل تطبيقات ثانية: يفتح إعدادات التطبيقات.
"""
from .platform_info import android_activity, current_platform

PLATFORM = current_platform()


def set_brightness(fraction: float) -> bool:
    """يخفّض سطوع نافذة التطبيق على أندرويد. يرجع True إذا نجح."""
    fraction = max(0.05, min(1.0, fraction))
    if PLATFORM != "android":
        return False
    try:
        from jnius import autoclass, PythonJavaClass, java_method

        class _Run(PythonJavaClass):
            __javainterfaces__ = ["java/lang/Runnable"]

            @java_method("()V")
            def run(self):
                window = android_activity().getWindow()
                params = window.getAttributes()
                params.screenBrightness = fraction
                window.setAttributes(params)

        # لازم تنفّذ على خيط الواجهة
        activity = android_activity()
        activity.runOnUiThread(_Run())
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[harara] brightness change failed: {exc}")
    return False


def _start_android_settings(action_name: str) -> bool:
    from jnius import autoclass
    Intent = autoclass("android.content.Intent")
    Settings = autoclass("android.provider.Settings")
    android_activity().startActivity(Intent(getattr(Settings, action_name)))
    return True


def open_power_saver_settings() -> bool:
    try:
        if PLATFORM == "android":
            return _start_android_settings("ACTION_BATTERY_SAVER_SETTINGS")
        if PLATFORM == "ios":
            return _open_ios_settings()
    except Exception as exc:  # noqa: BLE001
        print(f"[harara] could not open power saver settings: {exc}")
    return False


def open_app_management() -> bool:
    try:
        if PLATFORM == "android":
            return _start_android_settings("ACTION_APPLICATION_SETTINGS")
        if PLATFORM == "ios":
            return _open_ios_settings()
    except Exception as exc:  # noqa: BLE001
        print(f"[harara] could not open app settings: {exc}")
    return False


def open_usage_access_settings() -> bool:
    """أندرويد فقط: المستخدم لازم يسمح بـ Usage access عشان قائمة التطبيقات."""
    try:
        if PLATFORM == "android":
            return _start_android_settings("ACTION_USAGE_ACCESS_SETTINGS")
    except Exception as exc:  # noqa: BLE001
        print(f"[harara] could not open usage access settings: {exc}")
    return False


def _open_ios_settings() -> bool:
    """يفتح صفحة حرارة في تطبيق إعدادات الآيفون."""
    from pyobjus import autoclass, objc_str
    app = autoclass("UIApplication").sharedApplication()
    url = autoclass("NSURL").URLWithString_(objc_str("app-settings:"))
    try:
        options = autoclass("NSDictionary").dictionary()
        app.openURL_options_completionHandler_(url, options, None)
    except Exception as exc:  # noqa: BLE001
        print(f"[harara] openURL:options: failed ({exc}); trying openURL:")
        app.openURL_(url)
    return True
