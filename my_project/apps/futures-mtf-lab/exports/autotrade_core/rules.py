"""قاعده‌های بست و دلیل‌های «چرا وارد نشد» — دادهٔ خالص، بدون وابستگی.

این ماژول عمداً از موتور/ژورنال/داشبورد جدا است تا هر داشبورد دیگری هم بتواند
همان انتساب را نشان دهد: هر معامله باید بگوید با کدام قاعده بسته شد و آن قاعده
آیا برای **کم‌کردن ضرر** بود یا نه.
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict, Tuple

#: انتساب هر قاعدهٔ خروج: (نوع، توضیح فارسی، توضیح انگلیسی، آیا برای کم‌کردن ضرر است؟)
RULE_META: Dict[str, Tuple[str, str, str, bool]] = {
    "stop_loss": ("risk", "حد ضرر اولیه (ATR×ضریب)", "initial stop loss", True),
    "stop_trail": ("risk", "تریلینگ استاپ (ATR×ضریب)", "trailing stop", True),
    "breakeven": ("risk", "انتقال استاپ به نقطهٔ ورود", "stop moved to breakeven", True),
    "giveback": ("risk", "قاعدهٔ افت سود (سود برگشتی)", "profit-giveback rule", True),
    "regime_flip": ("risk", "چرخش تأییدشدهٔ رژیم فیلتر", "confirmed regime flip", True),
    "time_stop": ("time", "سقف زمان نگه‌داری", "max holding bars", False),
    "take_profit": ("profit", "حد سود", "take profit", False),
    "partial_take": ("profit", "برداشت جزئی", "partial take", False),
    "manual": ("manual", "بسته‌شده به‌دست کاربر", "closed manually", False),
    "end_of_data": ("data", "پایان داده", "end of data", False),
}


#: نام فارسی «چرا وارد نشد» — همان شمارنده‌های موتور
VETO_FA = {
    "circuit_breaker": "فیوز ضررهای پیاپی",
    "cooldown": "استراحت بعد از ضرر",
    "daily_loss": "سقف ضرر روزانه",
    "slots": "همهٔ جایگاه‌ها پر بود",
    "hour_filter": "ساعت ممنوع",
    "climax": "شرط climax",
}


def normalize_reason(reason: str) -> str:
    """دلیل خروج موتور → کلید استاندارد. (`stop/trail` و `regime_flip_confirmed_3`)"""
    r = str(reason or "").strip()
    if r in ("stop/trail", "stop_trail"):
        return "stop_trail"
    if r.startswith("regime_flip"):
        return "regime_flip"
    if r.startswith("partial_take"):
        return "partial_take"
    return r or "unknown"


def rule_meta(reason: str) -> dict:
    key = normalize_reason(reason)
    kind, fa, en, risk = RULE_META.get(key, ("other", key, key, False))
    return {"rule": key, "kind": kind, "fa": fa, "en": en, "is_risk_control": risk}


def cfg_digest(overrides: dict) -> str:
    """اثر انگشت پیکربندی — تا سیگنال‌های دو نسخهٔ متفاوت قاطی نشوند."""
    blob = json.dumps(overrides, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]


# ---------------------------------------------------------------------------
# سریال‌کردن پوزیشن (تا بین اجراها زنده بماند)
# ---------------------------------------------------------------------------
