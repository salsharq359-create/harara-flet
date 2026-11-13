# حرارة (Harara) — Flet

مراقب صادق لحرارة الجوال، مكتوب بـ Python + Flet (بدل Kivy). نفس الشاشات السبع:
Welcome، Home، Alert، Suggested Actions، Log، Apps، Settings.

## من وين تجي البيانات
| | أندرويد (pyjnius) | آيفون (pyobjus) |
|---|---|---|
| الحرارة | درجة البطارية بالضبط (`BatteryManager`) + حالة النظام الحرارية | مستوى فقط: Normal / Warm / Hot / Critical (آبل ما تعطي رقم) |
| البطارية والشحن | نعم | نعم |
| التطبيقات الأكثر استخدامًا | نعم (يحتاج Usage access) | لا |

على اللابتوب يشتغل بقراءات محاكاة.

## الإشعارات (flet-notifications)
- تنبيه فوري عند تجاوز الحد (شاشة Alert + إشعار نظام) **وأنت فاتح التطبيق**.
- تقرير أسبوعي: إشعار كل أحد 8 مساءً (من Settings).
- الإذن يُطلب عند "Start monitoring".

## حدود صادقة
- Flet ما فيه خدمة خلفية دائمة على أندرويد، فالمراقبة والتنبيه يشتغلون **وأنت فاتح التطبيق**.
- iOS يوقف التطبيق إذا طلعت منه، فنفس الشي.
- خفض السطوع تلقائيًا يشتغل على أندرويد فقط.

## البناء
- Push إلى GitHub → تشتغل الاختبارات وتبني **harara-apk** (Artifacts).
- آيفون: Actions → Build → Run workflow → **harara-ipa** (غير موقّع، ثبّته بـ Sideloadly).
  التطبيق ينتهي بعد 7 أيام بحساب Apple المجاني.

## تشغيل محلي
```
pip install -e ".[dev]"   # أو: pip install flet flet-notifications cryptography pytest
python -m pytest -q
flet run
```
