"""حسابرسی خروج — «چقدر سود را با بستنِ زودهنگام ریختیم؟»

## سؤالی که جواب می‌دهد

کاربر: «بعضی اوقات سیگنال درست گرفته می‌شود، ولی **زود بسته می‌شود** و سود از
بین می‌رود». این فایل همان را عددی می‌کند:

هر معامله در ژورنال سه چیز دارد: `mfe_pct` (بیشترین سود شناور)، `mae_pct`
(بیشترین ضرر شناور)، و `r_multiple` (نتیجهٔ نهایی). اگر MFE را به واحد ریسک
برگردانیم:

```
mfe_r = mfe_pct ÷ risk_pct        (risk_pct = risk_amount ÷ notional × 100)
give_back_r = mfe_r − r           ← «سودی که در دست بود و رفت»
```

## سه دستهٔ معامله

| دسته | شرط | معنی |
|---|---|---|
| **برندهٔ پس‌داده‌شده** | `mfe_r ≥ ۰.۸` ولی `r ≤ ۰.۲` | در سود بود، سربه‌سر/ضرر بسته شد — بدترین حالت |
| **کوتاه‌شده** | `r > ۰` و `give_back_r ≥ ۱.۰` | سود گرفتیم ولی دست‌کم ۱R روی میز ماند |
| **حد ضرر سالم** | `r < ۰` و `mfe_r < ۰.۳` | هرگز سود نشد؛ استاپ کارش را کرد (ایراد نیست) |

## محدودیت صادقانه

MFE فقط **داخل عمر معامله** اندازه‌گیری می‌شود. اگر بعد از بستن، قیمت ۳R دیگر
برود، این فایل آن را **نمی‌بیند** — چون آن دیگر سودِ این معامله نبود، سودِ
معاملهٔ بعدی بود (اگر سیگنال تازه‌ای می‌داد). برای همین «حد ضرر سالم» را خطا
حساب نمی‌کنیم.

## خروجی

- آمار کلی و به تفکیک قاعدهٔ بست / الگو / نماد
- سه «نامزد تنظیم» برای آزمایشگاه (`trail_start_r`، `breakeven_at_r`،
  `max_holding_bars`) — **فقط نامزد، نه تغییر خودکار**
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Sequence

from .hunter import read_journal

VERSION = "1.0"

#: آستانه‌ها — از پیش ثابت، تا بعداً با دیدن نتیجه عوضشان نکنیم.
MIN_MFE_TO_CARE_R = 0.8      # زیر این، «در سود بود» حساب نمی‌شود
BREAKEVEN_R = 0.2            # بالای این، «سود نگه داشت»
BIG_GIVE_BACK_R = 1.0        # این‌قدر R روی میز = «کوتاه شد»


def _risk_pct(open_rec: dict) -> Optional[float]:
    o = (open_rec or {}).get("order") or {}
    try:
        notional = float(o.get("notional") or 0)
        risk = float(o.get("risk_amount") or 0)
        if notional <= 0 or risk <= 0:
            return None
        return risk / notional * 100.0
    except (TypeError, ValueError):
        return None


def collect(journal_path: str) -> List[dict]:
    """معاملات بسته‌شده + MFE/MAE به واحد R + دسته‌بندی خروج."""
    if not journal_path or not os.path.exists(journal_path):
        return []
    opens: Dict[str, dict] = {}
    trades: List[dict] = []
    with open(journal_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "open" and rec.get("id"):
                opens[rec["id"]] = rec
            elif rec.get("type") in ("close", "exit"):
                o = opens.get(rec.get("open_id") or "")
                res = rec.get("result") or {}
                r = res.get("r_multiple")
                if r is None:
                    continue
                rp = _risk_pct(o or {})
                mfe_pct = res.get("mfe_pct")
                mae_pct = res.get("mae_pct")
                mfe_r = (float(mfe_pct) / rp) if (mfe_pct is not None
                                                  and rp) else None
                mae_r = (float(mae_pct) / rp) if (mae_pct is not None
                                                  and rp) else None
                row = {
                    "symbol": rec.get("symbol") or (o or {}).get("symbol"),
                    "ts": (o or {}).get("ts") or rec.get("ts"),
                    "r": float(r),
                    "mfe_r": None if mfe_r is None else round(mfe_r, 3),
                    "mae_r": None if mae_r is None else round(mae_r, 3),
                    "risk_pct": None if rp is None else round(rp, 4),
                    "bars": res.get("bars_held"),
                    "pnl": res.get("pnl"),
                    "rule": ((rec.get("closed_by") or {}).get("fa")
                             or (rec.get("closed_by") or {}).get("id") or "?"),
                    "rule_id": (rec.get("closed_by") or {}).get("id"),
                    "is_risk_control": bool((rec.get("closed_by") or {})
                                            .get("is_risk_control")),
                    "pattern": (((o or {}).get("entry_pattern") or {}).get("mode")),
                    "algorithm": ((rec.get("algorithm") or {}).get("id")),
                }
                row["give_back_r"] = (None if row["mfe_r"] is None
                                      else round(row["mfe_r"] - row["r"], 3))
                row["category"] = _categorize(row)
                trades.append(row)
    trades.sort(key=lambda t: t.get("ts") or 0)
    return trades


def _categorize(t: dict) -> str:
    mfe, r = t.get("mfe_r"), t.get("r")
    if mfe is None or r is None:
        return "نامعلوم"
    if mfe >= MIN_MFE_TO_CARE_R and r <= BREAKEVEN_R:
        return "برندهٔ پس‌داده‌شده"
    if r > BREAKEVEN_R:
        return "کوتاه‌شده" if (mfe - r) >= BIG_GIVE_BACK_R else "خوب"
    if mfe < 0.3:
        return "حد ضرر سالم"
    return "ضرر پس از سود"


def _median(xs: Sequence[float]) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _agg(rows: List[dict]) -> dict:
    rs = [t["r"] for t in rows]
    gb = [t["give_back_r"] for t in rows if t.get("give_back_r") is not None
          and t["give_back_r"] > 0]
    return {
        "n": len(rows),
        "expectancy_r": (sum(rs) / len(rs)) if rs else None,
        "r_sum": sum(rs) if rs else 0.0,
        "median_mfe_r": _median([t["mfe_r"] for t in rows
                                 if t.get("mfe_r") is not None]),
        "median_give_back_r": _median(gb),
        "give_back_total_r": round(sum(gb), 3) if gb else 0.0,
    }


def analyze(trades: Sequence[dict] = None, journal_path: str = "") -> dict:
    rows = list(trades if trades is not None else collect(journal_path))
    cats: Dict[str, int] = {}
    for t in rows:
        cats[t["category"]] = cats.get(t["category"], 0) + 1

    def _by(key: str) -> Dict[str, dict]:
        buckets: Dict[str, List[dict]] = {}
        for t in rows:
            buckets.setdefault(str(t.get(key) or "?"), []).append(t)
        return {k: _agg(v) for k, v in sorted(buckets.items(),
                                              key=lambda kv: -len(kv[1]))}

    gave_back = [t for t in rows if t["category"] in ("برندهٔ پس‌داده‌شده",
                                                      "کوتاه‌شده",
                                                      "ضرر پس از سود")]
    leak_r = sum(max(0.0, t.get("give_back_r") or 0.0) for t in gave_back)
    total_r = sum(t["r"] for t in rows) or 0.0

    knobs: List[dict] = []
    if gave_back:
        knobs.append({
            "knob": "trail_start_r",
            "why": f"{len(gave_back)} معامله دست‌کم {MIN_MFE_TO_CARE_R}R سود دید و "
                   f"{leak_r:.1f}R از دست رفت",
            "try": "آزمون با ۰.۵ و ۰.۸ (شروع تریل زودتر)",
        })
        if any(t["category"] == "برندهٔ پس‌داده‌شده" for t in rows):
            knobs.append({
                "knob": "breakeven_at_r",
                "why": "بعضی معاملات در سود بودند و سربه‌سر/ضرر بستند",
                "try": "آزمون با ۰.۵ (بردن استاپ به نقطهٔ ورود)",
            })
        if any(t["category"] == "کوتاه‌شده" for t in rows):
            knobs.append({
                "knob": "makeable_hold" if False else "max_holding_bars",
                "why": "بخشی از سودها با قاعدهٔ زمانی بسته شدند",
                "try": "آزمون با برداشتن سقف زمان (۰ = بی‌نهایت) برای مقایسه",
            })

    warnings: List[str] = []
    n = len(rows)
    if n < 30:
        warnings.append(f"n={n} — با این تعداد، هیچ تنظیمی را بر اساس این گزارش "
                        "عوض نکن. این گزارش برای «دیدن ساختار» است.")
    if rows and all(t.get("mfe_r") is None for t in rows):
        warnings.append("mfe_pct در ژورنال نیست — یا ژورنال قدیمی است یا موتور "
                        "MFE را ثبت نکرده. گزارش ناقص است.")

    return {
        "version": VERSION,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n": n,
        "overall": _agg(rows),
        "categories": cats,
        "leak_total_r": round(leak_r, 3),
        "share_of_total": (round(leak_r / abs(total_r), 3) if total_r else None),
        "by_rule": _by("rule"),
        "by_pattern": _by("pattern"),
        "by_symbol": _by("symbol"),
        "candidates": knobs,
        "warnings": warnings,
        "trades": rows[-400:],
    }


def render(rep: dict) -> str:
    o = rep["overall"]
    L = ["# حسابرسی خروج — چقدر سود روی میز ماند؟\n"]
    L.append(f"*{rep['created_utc']}* · نسخهٔ {rep['version']} · {rep['n']} معامله\n")
    L.append("> این گزارش فقط **نگاه** می‌کند. هیچ پارامتری را خودش عوض نمی‌کند.\n")
    L.append("## خلاصه\n")
    L.append("| سنجه | مقدار |")
    L.append("|---|---:|")
    L.append(f"| معامله | {o['n']} |")
    L.append(f"| expectancy | {_p(o['expectancy_r'])}R |")
    L.append(f"| جمع R | {o['r_sum']:.2f}R |")
    L.append(f"| میانهٔ بیشترین سود شناور | {_p(o['median_mfe_r'])}R |")
    L.append(f"| میانهٔ سودِ پس‌داده‌شده | {_p(o['median_give_back_r'])}R |")
    L.append(f"| **کل سودِ ریخته‌شده** | **{rep['leak_total_r']:.2f}R** |")
    if rep.get("share_of_total") is not None:
        L.append(f"| نسبت به کل نتیجه | {rep['share_of_total'] * 100:.0f}٪ |")
    L.append("")
    L.append("## دسته‌بندی معاملات\n")
    L.append("| دسته | تعداد | معنی |")
    L.append("|---|---:|---|")
    meaning = {
        "برندهٔ پس‌داده‌شده": "در سود بود، سربه‌سر/ضرر بست — بدترین حالت",
        "کوتاه‌شده": "سود گرفت ولی ≥ ۱R روی میز ماند",
        "خوب": "سود گرفت و نزدیک سقفش بست",
        "ضرر پس از سود": "کمی سود دید و بعد ضرر شد",
        "حد ضرر سالم": "هرگز سود نشد؛ استاپ کارش را کرد",
        "نامعلوم": "MFE ثبت نشده",
    }
    for k, v in sorted(rep["categories"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {k} | {v} | {meaning.get(k, '')} |")
    L.append("")
    L.append("## به تفکیک قاعدهٔ بست\n")
    L.append("| قاعده | n | expectancy | میانهٔ MFE | سودِ ریخته |")
    L.append("|---|---:|---:|---:|---:|")
    for k, d in rep["by_rule"].items():
        L.append(f"| {k} | {d['n']} | {_p(d['expectancy_r'])}R | "
                 f"{_p(d['median_mfe_r'])}R | {d['give_back_total_r']:.2f}R |")
    L.append("")
    if rep.get("by_pattern"):
        L.append("## به تفکیک الگوی ورود\n")
        L.append("| الگو | n | expectancy | سودِ ریخته |")
        L.append("|---|---:|---:|---:|")
        for k, d in rep["by_pattern"].items():
            L.append(f"| {k} | {d['n']} | {_p(d['expectancy_r'])}R | "
                     f"{d['give_back_total_r']:.2f}R |")
        L.append("")
    if rep["candidates"]:
        L.append("## نامزدهای آزمایشگاه (نه تغییر خودکار)\n")
        L.append("| پارامتر | چرا | چه چیزی را امتحان کن |")
        L.append("|---|---|---|")
        for c in rep["candidates"]:
            L.append(f"| `{c['knob']}` | {c['why']} | {c['try']} |")
        L.append("")
        L.append("برای هر نامزد **یک** آزمون با دروازهٔ ازپیش‌نوشته. اگر پاس نشد، "
                 "رد است — نه اینکه دروازه را عوض کنیم.\n")
    else:
        L.append("**هیچ نامزدی نیست:** یا سودی روی میز نمانده (خوب)، یا ژورنال "
                 "MFE ندارد (داده ناقص).\n")
    if rep["warnings"]:
        L.append("## هشدارها\n")
        for w in rep["warnings"]:
            L.append(f"- ⚠️ {w}")
        L.append("")
    return "\n".join(L)


def _p(x, nd: int = 2) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def exits_command(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="mtflab exits",
        description="حسابرسی خروج: چقدر سود با بستن زودهنگام از دست رفت")
    p.add_argument("--journal", default="results/live/journal.jsonl")
    p.add_argument("--out", default="results/exits_fa.md")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    rows = collect(a.journal)
    rep = analyze(rows)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
        return 0
    md = render(rep)
    print(md)
    if rows:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"\n📄 {os.path.abspath(a.out)}")
    return 0 if rows else 2
