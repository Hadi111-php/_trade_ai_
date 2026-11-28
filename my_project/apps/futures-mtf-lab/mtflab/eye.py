"""CLI «چشم مغز» — ساخت مدل دیدگاه و دیدنِ نظر آن روی هر نماد.

جدا از `brainview.py` نگه داشته شد تا خودِ مدل، هیچ وابستگی‌ای به CLI و
پوشه‌های داده نداشته باشد (همان اصل استقلال).

    python3 -m mtflab view --train      # ساخت/به‌روزرسانی مدل + گزارش
    python3 -m mtflab view              # فقط دیدن نظر مغز روی نمادها
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from typing import List, Optional

from .brainview import (FEATURES, VERSION, cost_frac, load_model, render_table,
                        save_model, train, view_now)
from .config import MTFConfig, load_config

DEFAULT_MODEL = os.path.join("results", "brain_model.json")


def _cfg(tf: str, tf_filter: str, tf_bias: str) -> MTFConfig:
    cfg = load_config(["--data", "synthetic", "--quiet"])
    return replace(cfg, tf_trigger=tf, tf_filter=tf_filter, tf_bias=tf_bias,
                   verbose=False, forensics=False, run_id="", symbol="")


def _md(model: dict, report: dict, views: dict, cfg: MTFConfig) -> str:
    L: List[str] = []
    w = L.append
    w("# چشم مغز — دیدگاه مستقلِ هر نماد\n")
    w(f"*{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}*\n")
    w("> این گزارش **مشاوره** است، نه دستور. الگوریتم‌یاب حاکم است و تصمیم را "
      "خودش می‌گیرد؛ دیدگاه مغز فقط کنار سیگنال ثبت می‌شود.\n")
    if report:
        oof = report.get("oof") or {}
        w("## آموزش\n")
        w(f"- ردیف آموزش: **{report['rows']}** · نماد: **{report['symbols']}** · "
          f"افق: **{report['horizon_bars']} کندل** · هزینهٔ درنظرگرفته‌شده: "
          f"**{report['cost_frac'] * 100:.3f}%**")
        w(f"- نرخ پایه (حرکت بیشتر از هزینه): **{report['base_rate'] * 100:.1f}%**")
        w(f"- ارزیابی راه‌رونده: AUC **{oof.get('auc')}** · دقت **{oof.get('acc')}** "
          f"روی **{oof.get('n')}** پیش‌بینی بیرون‌نمونه")
        if oof.get("majority_acc") is not None and oof.get("acc") is not None:
            lift = round(oof["acc"] - oof["majority_acc"], 4)
            w(f"- دقت در برابر **حدسِ همیشه-اکثریت** ({oof['majority_acc'] * 100:.1f}%): "
              f"اختلاف **{lift * 100:+.1f} درصد**")
            if abs(lift) < 0.02:
                w("  ⚠️ یعنی مدل تقریباً هیچ چیزی بیشتر از «همیشه پایین» نمی‌داند.")
        w("")
        w("| فولد | آموزش | آزمون | AUC | دقت | نرخ پایه |")
        w("|---|---:|---:|---:|---:|---:|")
        for f in report.get("folds") or []:
            w(f"| {f['fold']} | {f['n_train']} | {f['n_test']} | {f.get('auc')} | "
              f"{f['acc'] * 100:.1f}% | {f['base_rate'] * 100:.1f}% |")
        w("")
        w("**چطور بخوانیم:** AUC نزدیک ۰.۵ یعنی «چیزی نمی‌فهمد». دقت باید با "
          "نرخ پایه مقایسه شود، نه با ۵۰٪.\n")
    w("## دیدگاه فعلی\n")
    w(render_table(views))
    w("")
    w(f"مدل: `brainview/{VERSION}` · آموزش‌دیده تا "
      f"{time.strftime('%Y-%m-%d', time.gmtime((model.get('trained_through_ts') or 0) / 1000))} · "
      f"{len(FEATURES)} ویژگی · هزینهٔ رفت‌وبرگشت {cost_frac(cfg) * 100:.3f}%\n")
    w("| ویژگی | توضیح | ضریب (استانداردشده) |")
    w("|---|---|---:|")
    for (name, fa), coef in zip(FEATURES, model.get("w") or []):
        w(f"| `{name}` | {fa} | {coef:+.3f} |")
    w("")
    w("> علامت مثبت یعنی «احتمال صعود بیشتر». این ضرایب **هم‌بستگی**‌اند، نه علت؛ "
      "و روی داده‌ای آموزش دیده‌اند که ما قبلاً دیده‌ایم.\n")
    return "\n".join(L) + "\n"


def view_command(argv: Optional[List[str]] = None) -> int:
    import argparse
    from .autoscan import set_lang, _t
    from .desk import load_universe
    from .sweep import deliver

    p = argparse.ArgumentParser(
        prog="mtflab view",
        description="چشم مغز: دیدگاه مستقلِ هر نماد (فقط مشاهده، بدون تصمیم)")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--symbols", nargs="+", default=None)
    p.add_argument("--tf", default="4h")
    p.add_argument("--tf-filter", default="1d")
    p.add_argument("--tf-bias", default="1d")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--train", action="store_true", help="آموزش/بازآموزی مدل")
    p.add_argument("--horizon", type=int, default=6, help="افق پیش‌بینی (کندل)")
    p.add_argument("--folds", type=int, default=4)
    p.add_argument("--max-rows", type=int, default=20000)
    p.add_argument("--out-dir", default="results")
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    a = p.parse_args(argv)
    set_lang(a.lang)

    cfg = _cfg(a.tf, a.tf_filter, a.tf_bias)
    universe = load_universe(a.data_dir, a.tf, a.symbols)
    if not universe:
        print(_t("❌ هیچ داده‌ای در کش نیست. اول `bash run-auto.sh --live`.",
                 "❌ no cached data."))
        return 2

    model = None if a.train else load_model(a.model)
    report = {}
    if model is None:
        print(_t(f"⏳ آموزش روی {len(universe)} نماد …", "⏳ training …"))
        try:
            model, report = train(universe, cfg, horizon=a.horizon,
                                  folds=a.folds, max_rows=a.max_rows)
        except ValueError as e:
            print(_t(f"❌ {e}", f"❌ {e}"))
            return 2
        save_model(model, a.model)
        oof = report.get("oof") or {}
        print(_t(f"   ✅ مدل ذخیره شد: {a.model} · AUC بیرون‌نمونه {oof.get('auc')} "
                 f"· دقت {oof.get('acc')}",
                 f"   ✅ model saved: {a.model} · OOS AUC {oof.get('auc')}"))

    views = {sym: view_now(model, cs, cfg) for sym, cs in universe.items()}
    md = _md(model, report, views, cfg)
    os.makedirs(a.out_dir, exist_ok=True)
    md_path = os.path.join(a.out_dir, "brain_view.md")
    js_path = os.path.join(a.out_dir, "brain_view.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(js_path, "w", encoding="utf-8") as f:
        json.dump({"model": {k: model.get(k) for k in
                             ("version", "trained_through_ts", "trained_utc",
                              "horizon_bars", "cost_frac", "oof", "w", "features")},
                   "views": views, "training": report}, f,
                  ensure_ascii=False, indent=1, default=str)
    print("\n" + md)
    print(f"📄 {os.path.abspath(md_path)}\n🗂 {os.path.abspath(js_path)}")
    deliver([md_path, js_path], a.out_dir, lang=a.lang)
    return 0
