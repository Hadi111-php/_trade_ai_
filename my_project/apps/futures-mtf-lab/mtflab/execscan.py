"""آزمون ایدهٔ «کندل ۴ساعته باز شود، ولی هر ۱۵ دقیقه بررسی شود».

**فرضیه (پیش‌ثبت‌شده، قبل از دیدن نتیجه):**

مدیریت خروج در ۴ ساعت کور است. یک کندل ۴ساعته می‌تواند سقف و کف را هر دو
لمس کند و مدل مجبور است حد ضرر را فرض کند. با نگاه ۱۵دقیقه‌ای:
  ۱) ترتیب واقعیِ لمس‌ها معلوم می‌شود (دقت مسیر)
  ۲) تریلینگ هر ۱۵ دقیقه سفت می‌شود، نه هر ۴ ساعت
  ۳) قاعدهٔ «افت سود» ممکن است: اگر سود شناور به +۱R رسید و بعد به ۵۰٪ اوجش
     برگشت، بسته شود.

**آنچه سنجیده می‌شود:** سه تنظیم روی همان داده، نه یک جست‌وجو:

    A  پایه    : همه چیز مثل امروز (۴ ساعته، بدون قاعدهٔ افت سود)
    B  دقیق    : مدیریت خروج روی ۱۵ دقیقه (بدون افت سود)
    C  دقیق+افت: همان B + قاعدهٔ افت سود (‏+۱R و ۵۰٪)

معیار قبولی **قبل از اجرا** قفل شده است و در گزارش هم چاپ می‌شود.
"""
from __future__ import annotations

import json
import os
import statistics as st
import time
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

from .autoscan import build_layers, run_variant
from .data import tf_to_minutes

#: تنظیم‌های آزمون: (کلید، exec_tf، arm_r، frac، توضیح فارسی)
ARMS: List[Tuple[str, str, float, float, str]] = [
    ("A_base", "", 0.0, 0.0, "پایه: ۴ ساعته، بدون قاعدهٔ افت سود"),
    ("B_fine", "15m", 0.0, 0.0, "دقیق: مدیریت ۱۵ دقیقه‌ای"),
    ("C_fine_gb", "15m", 1.0, 0.5, "دقیق + افت سود: +۱R و ۵۰٪"),
]

#: معیارهای قبولی — **قبل از اجرا** نوشته شده‌اند
GATE = {
    "median_pf_min": 1.1201,      # نباید از پایهٔ امروز پایین‌تر بیاید
    "symbols_pf_above_min": 15,   # از ۱۲ به ۱۵ از ۲۰
    "top5_share_max": 0.70,       # از ۱۱۸٪ به زیر ۷۰٪
}


def load_pair(data_dir: str, tf_trigger: str, tf_exec: str
              ) -> Tuple[Dict[str, list], Dict[str, list], List[str]]:
    """بسته‌های هر دو تایم‌فریم را می‌خواند و نمادهای مشترک را برمی‌گرداند."""
    from .sweep import load_cached
    trig = load_cached(data_dir, tf_trigger)
    exe = load_cached(data_dir, tf_exec)
    both = sorted(set(trig) & set(exe))
    only_t = sorted(set(trig) - set(exe))
    only_e = sorted(set(exe) - set(trig))
    return trig, exe, both + [f"!{s}" for s in only_t] + [f"!{s}" for s in only_e]


def _clip(candles: Sequence, start_ms: int) -> list:
    """کندل‌های ریزتر را به بازهٔ دادهٔ تریگر محدود می‌کند (هم‌پوشانی زمانی)."""
    return [c for c in candles if c.open_time_ms >= start_ms]


def run(data_dir: str, tf_trigger: str, tf_exec: str, tf_filter: str, tf_bias: str,
        variant_id: str, progress: bool = True) -> dict:
    from .config import load_config

    t0 = time.time()
    trig, exe, report = load_pair(data_dir, tf_trigger, tf_exec)
    both = [s for s in report if not s.startswith("!")]
    missing = [s.lstrip("!") for s in report if s.startswith("!")]
    if not both:
        return {"error": "no common symbols", "report": report}

    cfg = load_config(["--data", "synthetic", "--quiet"])
    from .autoscan import variants_for
    by_id = {v[0]: v for v in variants_for(tf_trigger, tf_filter, tf_bias)}
    variant = by_id.get(variant_id)
    if variant is None:
        return {"error": f"unknown variant {variant_id}", "allowed": sorted(by_id)}

    out: Dict[str, Dict[str, dict]] = {a[0]: {} for a in ARMS}
    for n, sym in enumerate(both, 1):
        if progress:
            print(f"[{n}/{len(both)}] {sym}", flush=True)
        sub = _clip(exe[sym], trig[sym][0].open_time_ms)
        for key, ex_tf, arm, frac, _label in ARMS:
            layers = build_layers(trig[sym], tf_trigger, tf_filter, tf_bias,
                                  bias_enabled=True,
                                  exec_candles=sub if ex_tf else None)
            c = replace(cfg, verbose=False, forensics=False, run_id="",
                        exec_tf=ex_tf, giveback_arm_r=arm, giveback_frac=frac)
            try:
                out[key][sym] = run_variant(c, layers, variant[2])
            except Exception as e:                              # noqa: BLE001
                out[key][sym] = {"error": str(e)[:70]}

    summary = {}
    for key, _tf, _a, _f, label in ARMS:
        rows = [m for m in out[key].values() if "error" not in m]
        if not rows:
            summary[key] = {"ok": False, "label": label}
            continue
        pfs = sorted(r["profit_factor"] for r in rows if r["profit_factor"] is not None)
        pnls = sorted(((s, m["pnl"]) for s, m in out[key].items() if "error" not in m),
                      key=lambda x: -x[1])
        tot = sum(v for _s, v in pnls)
        top5 = sum(v for _s, v in pnls[:5])
        summary[key] = {
            "ok": True, "label": label,
            "trades": sum(r["n"] for r in rows),
            "median_pf": round(st.median(pfs), 4) if pfs else None,
            "median_expectancy": round(st.median([r["expectancy"] for r in rows]), 4),
            "symbols_pf_above_1": sum(1 for x in pfs if x > 1.0),
            "n_symbols": len(rows),
            "total_pnl": round(tot, 2),
            "top5_share": round(top5 / tot, 4) if tot else None,
            "median_dd": round(st.median([r["max_drawdown_pct"] for r in rows]), 2),
            "exit_reasons": _merged_exits(rows),
        }

    base = summary.get("A_base") or {}
    for key in summary:
        s_ = summary[key]
        if not s_.get("ok") or not base.get("ok"):
            continue
        if s_.get("median_pf") is None or base.get("median_pf") is None:
            continue
        s_["delta_median_pf"] = round(s_["median_pf"] - base["median_pf"], 4)
        s_["delta_symbols"] = s_["symbols_pf_above_1"] - base["symbols_pf_above_1"]
        s_["gate"] = {
            "median_pf": s_["median_pf"] >= GATE["median_pf_min"],
            "symbols": s_["symbols_pf_above_1"] >= GATE["symbols_pf_above_min"],
            "concentration": (s_["top5_share"] is not None
                              and s_["top5_share"] <= GATE["top5_share_max"]),
        }
        s_["gate_pass"] = all(s_["gate"].values())

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "elapsed_s": round(time.time() - t0, 1),
        "settings": {
            "tf_trigger": tf_trigger, "tf_exec": tf_exec,
            "tf_filter": tf_filter, "tf_bias": tf_bias,
            "variant": variant_id, "symbols": both,
            "n_symbols": len(both), "only_one_tf": missing, "gate": GATE,
            "arms": [{"key": k, "exec_tf": t, "arm_r": a, "frac": f, "label": lb}
                     for k, t, a, f, lb in ARMS],
        },
        "summary": summary,
        "detail": out,
    }


def _merged_exits(rows: Sequence[dict]) -> Dict[str, int]:
    tot: Dict[str, int] = {}
    for r in rows:
        for k, v in (r.get("exit_reasons") or {}).items():
            tot[k] = tot.get(k, 0) + int(v)
    return dict(sorted(tot.items(), key=lambda kv: -kv[1]))


def render(res: dict, lang: str = "fa") -> str:
    if res.get("error"):
        return f"❌ {res['error']}\n"
    s = res["settings"]
    L: List[str] = []
    w = L.append
    fa = lang != "en"

    if fa:
        w("# اجرا در تایم‌فریم ریزتر — آیا نگاه ۱۵دقیقه‌ای چیزی را عوض می‌کند؟\n")
        w(f"*{res['generated_at']} · زمان {res['elapsed_s']} ثانیه · "
          f"{s['n_symbols']} نماد · تریگر `{s['tf_trigger']}` · اجرا `{s['tf_exec']}` · "
          f"نسخهٔ `{s['variant']}`*\n")
        w("سه تنظیم، **همان داده، همان سیگنال**؛ فقط مدیریت خروج عوض می‌شود. "
          "هیچ جست‌وجویی انجام نشده — اعداد قبل از اجرا قفل شده بودند.\n")
    else:
        w("# Finer execution timeframe — does a 15-minute view change anything?\n")
        w(f"*{res['generated_at']} · {res['elapsed_s']}s · {s['n_symbols']} symbols · "
          f"trigger `{s['tf_trigger']}` · exec `{s['tf_exec']}` · variant "
          f"`{s['variant']}`*\n")
        w("Three arms, **same data, same signal**; only exit management changes. "
          "No search was performed — the thresholds were fixed before the run.\n")

    hdr = ("| تنظیم | معاملات | میانهٔ PF | ΔPF | PF>1 | جمع PnL | سهم ۵ سکه | MaxDD | قبولی |"
           if fa else
           "| arm | trades | median PF | ΔPF | PF>1 | total PnL | top-5 share | MaxDD | gate |")
    w(hdr)
    w("|---|---:|---:|---:|---:|---:|---:|---:|:--:|")
    for arm in s["arms"]:
        k = arm["key"]
        m = res["summary"].get(k) or {}
        if not m.get("ok"):
            continue
        share = m.get("top5_share")
        gate = ("✅" if m.get("gate_pass") else "❌") if k != "A_base" else "—"
        w(f"| `{k}` {arm['label'] if fa else ''} | {m['trades']} | "
          f"{m['median_pf']} | {m.get('delta_median_pf', 0):+} | "
          f"{m['symbols_pf_above_1']}/{m['n_symbols']} | {m['total_pnl']:+}$ | "
          f"{(f'{share * 100:.0f}%' if share is not None else '—')} | "
          f"{m['median_dd']}% | {gate} |")
    w("")

    g = s["gate"]
    if fa:
        w("## معیار قبولی (قبل از اجرا قفل شده)\n")
        w(f"- میانهٔ PF ≥ **{g['median_pf_min']}** (پایهٔ امروز)")
        w(f"- نمادهای PF>1 ≥ **{g['symbols_pf_above_min']}** از {s['n_symbols']}")
        w(f"- سهم ۵ سکهٔ اول از سود < **{g['top5_share_max'] * 100:.0f}٪**\n")
        w("> هر سه باید هم‌زمان پاس شوند. PF بهتر با تمرکز بیشتر روی چند سکه، "
          "**قبولی نیست** — همان دام overfitting است.\n")
    else:
        w("## Pre-registered gate\n")
        w(f"- median PF ≥ **{g['median_pf_min']}** (today's baseline)")
        w(f"- symbols PF>1 ≥ **{g['symbols_pf_above_min']}** of {s['n_symbols']}")
        w(f"- top-5 share < **{g['top5_share_max'] * 100:.0f}%**\n")

    if fa:
        w("## دلیل خروج‌ها\n")
        for arm in s["arms"]:
            m = res["summary"].get(arm["key"]) or {}
            if not m.get("ok"):
                continue
            ex = m.get("exit_reasons") or {}
            tot = sum(ex.values()) or 1
            parts = " · ".join(f"`{k}` {v * 100 // tot}٪" for k, v in ex.items())
            w(f"- `{arm['key']}`: {parts}")
    if s.get("only_one_tf"):
        w("")
        w(("**نمادهای حذف‌شده** (فقط یک تایم‌فریم در کش داشتند): "
           if fa else "**Excluded** (only one timeframe cached): ")
          + ", ".join(s["only_one_tf"]))
    return "\n".join(L) + "\n"


def exec_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from .autoscan import set_lang, _t
    from .sweep import deliver

    p = argparse.ArgumentParser(
        prog="mtflab exec-scan",
        description="مدیریت خروج در تایم‌فریم ریزتر + قاعدهٔ افت سود")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--tf", default="4h", help="تایم‌فریم تریگر (تصمیم ورود)")
    p.add_argument("--exec-tf", default="15m", help="تایم‌فریم مدیریت خروج")
    p.add_argument("--tf-filter", default="1d")
    p.add_argument("--tf-bias", default="1d")
    p.add_argument("--variant", default="trend")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--tag", default="")
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    a = p.parse_args(argv)
    set_lang(a.lang)

    print("=" * 70)
    print(_t(f"آزمون اجرا در {a.exec_tf} — تریگر {a.tf} · نسخهٔ {a.variant}",
             f"exec-tf {a.exec_tf} test — trigger {a.tf} · variant {a.variant}"))
    print("=" * 70)

    res = run(a.data_dir, a.tf, a.exec_tf, a.tf_filter, a.tf_bias, a.variant)
    if res.get("error"):
        print(_t(f"❌ {res['error']}", f"❌ {res['error']}"))
        if res.get("report"):
            print(_t("   نمادهای موجود: ", "   cached symbols: ") + ", ".join(res["report"]))
        return 2

    os.makedirs(a.out_dir, exist_ok=True)
    tag = f"_{a.tag}" if a.tag else ""
    md = os.path.join(a.out_dir, f"exec_tf{tag}.md")
    js = os.path.join(a.out_dir, f"exec_tf{tag}.json")
    with open(md, "w", encoding="utf-8") as f:
        f.write(render(res, lang=a.lang))
    with open(js, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)

    print("\n" + "=" * 70)
    for arm in res["settings"]["arms"]:
        m = res["summary"].get(arm["key"]) or {}
        if not m.get("ok"):
            continue
        mark = "✅" if m.get("gate_pass") else ("—" if arm["key"] == "A_base" else "❌")
        print(f"  {arm['key']:11s} trades={m['trades']:5d} medPF={m['median_pf']} "
              f"PF>1={m['symbols_pf_above_1']:2d}/{m['n_symbols']} "
              f"pnl={m['total_pnl']:+8.2f}$ top5={m['top5_share']} {mark}")
    print(f"\n📄 {os.path.abspath(md)}\n🗂 {os.path.abspath(js)}")
    deliver([md, js], a.out_dir, lang=a.lang)
    return 0
