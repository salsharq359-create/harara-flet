"""على أي منصة يشتغل التطبيق؟ Flet يحدد FLET_PLATFORM داخل تطبيقات الجوال."""
import os
import sys


def current_platform() -> str:
    """يرجع 'android' أو 'ios' أو 'windows' (لابتوب، قراءات حقيقية) أو 'desktop' (محاكي)."""
    plat = os.environ.get("FLET_PLATFORM", "").lower()
    if plat in ("android", "ios"):
        return plat
    if sys.platform == "win32" and os.environ.get("HARARA_SIMULATE") != "1":
        return "windows"
    return "desktop"


def android_activity():
    """نشاط أندرويد الحالي (نفس الطريقة اللي اختبرناها على الجوال)."""
    from jnius import autoclass
    return autoclass(os.environ["MAIN_ACTIVITY_HOST_CLASS_NAME"]).mActivity
