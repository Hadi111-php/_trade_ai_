"""انتساب سیگنال به الگو — «این سیگنال بابت کدام الگوها بود؟»

هدف کاربر: وقتی سیگنالی صادر می‌شود، سیستم بگوید **کدام الگوها** آن را داده‌اند تا
بتوان الگوی بی‌فایده را از سیستم حذف کرد و الگوی مفید را نگه داشت.

سه چیز این‌جا ساخته می‌شود:

1. `pattern_votes(candles, bar_ts, ...)` — برای یک کندل مشخص، همهٔ الگوهای موجود را
   جداگانه اجرا می‌کند و می‌گوید کدام‌ها **همان کندل** وارد می‌شدند. خروجی‌اش در
   ژورنال سیگنال می‌نشیند (`pattern_votes`)، پس بعداً قابل حسابرسی است.
2. `scorecard(journal)` — از ژورنال واقعی، برای هر الگو: تعداد، نرخ برد،
   expectancy R، ضریب سود، و **سهم یگانه/هم‌گرا** (سیگنالی که فقط آن الگو داده بود
   در برابر سیگنالی که چند الگو هم‌زمان داده بودند).
3. `prune_plan(scorecard)` — پیشنهاد «نگه‌دار / نامزد حذف / داده کافی نیست».

قاعدهٔ حذف **از قبل** نوشته شده و بعد از دیدن نتیجه عوض نمی‌شود:

* `n < MIN_N` → «داده کافی نیست». با ۱۰ معامله هیچ الگویی حذف نمی‌شود.
* `expectancy_r > 0` → «نگه‌دار».
* `expectancy_r ≤ 0` با `n ≥ MIN_N` → «نامزد حذف».

هیچ‌کدام خودکار نیست: این ماژول فقط عدد و پیشنهاد می‌دهد؛ حذف الگو تصمیم کاربر است
(همان قاعدهٔ «حکم فقط با نمونهٔ کافی و بیرون‌نمونه»).
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Sequence

VERSION = "1.0"

MIN_N = 30                 # زیر این تعداد هیچ حکمی صادر نمی‌شود
# پنجرهٔ رأی‌گیری: پیش‌فرض **بدون برش**. بریدنِ سادهٔ ابتدای سری، مرز روزها را
# می‌شکند و رژیمِ لایهٔ بالاتر را عوض می‌کند؛ در آزمایش واقعی همین باعث شد سیگنالِ
# خودِ الگو هم در رأی غایب شود. اگر کسی برش خواست، باید آگاهانه بدهد.
VOTE_WINDOW = None
MIN_BARS_TO_VOTE = 80      # زیر این تعداد کندل، رأی‌گیری بی‌معناست

VERDICT_KEEP = "نگه‌دار"
VERDICT_DROP = "نامزد حذف"
VERDICT_NEED = "داده کافی نیست"


# ══════════════════════════════════════════════════════════════════════════
#  ۱) رأی‌گیری روی یک کندل
# ══════════════════════════════════════════════════════════════════════════
def pattern_votes(candles: Sequence, bar_ts: int, cfg=None,
                  tf_trigger: str = "4h", tf_filter: str = "1d",
                  tf_bias: str = "1d", window: Optional[int] = VOTE_WINDOW,
                  variant_ids: Optional[Sequence[str]] = None) -> dict:
    """کدام الگوها روی **همین کندل** شرط‌های ورودشان برقرار بود؟

    :param candles: کندل‌های تریگر (همان تایم‌فریمی که سیگنال رویش صادر شد)
    :param bar_ts: زمان باز شدن کندلِ سیگنال (millisecond)
    :param cfg: کانفیگ پایه (اگر نباشد از پیش‌فرض‌های پروژه ساخته می‌شود)

    روش: دروازه‌های موتور (`build_decision`) برای هر الگو روی همان کندل اجرا
    می‌شود — نه یک شبیه‌سازی کامل. دو دلیل:

    1. شبیه‌سازی کامل به وضعیت قبلی (اسلات آزاد، کول‌داون) وابسته است؛ پس رأیِ
       همان الگوی سازنده هم می‌توانست «نه» بیاید (این باگ واقعاً دیده شد).
    2. سؤال کاربر «این سیگنال بابت کدام الگو بود» است، نه «کدام الگو امروز پوزیشن
       باز می‌کرد». اشغال اسلات ربطی به خوب/بد بودن الگو ندارد.

    در نتیجه رأی = «شرط‌های ورودِ آن الگو روی این کندل برقرار بود».
    """
    try:
        bar_ts = int(bar_ts)
    except (TypeError, ValueError):
        return {"available": False, "patterns": [], "ids": [], "n": 0,
                "note": "زمان کندل نامعتبر"}

    cut = [c for c in candles if int(getattr(c, "open_time_ms", 0)) <= bar_ts]
    if len(cut) < MIN_BARS_TO_VOTE:
        return {"available": False, "bar_ts": bar_ts, "patterns": [], "ids": [],
                "n": 0, "note": f"کندل کافی نیست ({len(cut)})"}
    if window and len(cut) > int(window):
        cut = cut[-int(window):]

    from dataclasses import replace

    from .alignment import align_multi_timeframe
    try:
        from .autoscan import build_layers
    except Exception:                                              # noqa: BLE001
        # در بستهٔ سبک اتوترید `autoscan` وجود ندارد. صادقانه می‌گوییم در دسترس
        # نیست تا کسی عدد ساختگی نبیند.
        return {"available": False, "bar_ts": bar_ts, "patterns": [], "ids": [],
                "n": 0, "note": "رأی‌گیری در این بستهٔ سبک در دسترس نیست "
                                "(build_layers موجود نیست)"}
    from .config import load_config
    from .data import tf_to_minutes
    from .engine import MTFEngine
    from .patterns import variants_for
    from .signals import TFContext

    if cfg is None:
        cfg = load_config(["--data", "synthetic", "--quiet"])
    cfg = replace(cfg, tf_trigger=tf_trigger, tf_filter=tf_filter, tf_bias=tf_bias,
                  verbose=False, forensics=False, run_id="", symbol="")

    try:
        layers = build_layers(cut, cfg.tf_trigger, cfg.tf_filter, cfg.tf_bias,
                              bias_enabled=cfg.bias_enabled)
        bars = align_multi_timeframe(
            layers["trigger"], tf_to_minutes(cfg.tf_trigger),
            layers["filter"], tf_to_minutes(cfg.tf_filter),
            layers["bias"] if cfg.bias_enabled else None,
            tf_to_minutes(cfg.tf_bias) if cfg.bias_enabled else None)
    except Exception as e:                                         # noqa: BLE001
        return {"available": False, "bar_ts": bar_ts, "patterns": [], "ids": [],
                "n": 0, "note": f"لایه‌سازی خطا: {type(e).__name__}"}

    idx = next((k for k, b in enumerate(bars)
                if int(b.low_tf_candle.open_time_ms) == bar_ts), None)
    if idx is None:
        return {"available": False, "bar_ts": bar_ts, "patterns": [], "ids": [],
                "n": 0, "note": "این کندل در پنجرهٔ داده نیست"}

    hits: List[dict] = []
    errors: List[str] = []
    checked = 0
    for vid, label, ov in variants_for(cfg.tf_trigger, cfg.tf_filter, cfg.tf_bias):
        if variant_ids and vid not in variant_ids:
            continue
        checked += 1
        try:
            vcfg = replace(cfg, **{k: v for k, v in (ov or {}).items()
                                   if k in {f.name for f in cfg.__dataclass_fields__.values()}})
            ctxs = {
                "trigger": TFContext(layers["trigger"], vcfg, "trigger"),
                "filter": TFContext(layers["filter"], vcfg, "filter"),
                "bias": (TFContext(layers["bias"], vcfg, "bias") if vcfg.bias_enabled
                         else TFContext(layers["filter"], vcfg, "filter")),
            }
            info = MTFEngine(vcfg, None, None).build_decision(bars[idx], ctxs)
            if info["decision"].action == "ENTER":
                hits.append({"id": vid, "label": label,
                             "mode": info["trig"].mode,
                             "side": ("LONG" if info["decision"].direction > 0 else "SHORT"),
                             "confidence": round(float(info["decision"].confidence), 4)})
        except Exception as e:                                     # noqa: BLE001
            errors.append(f"{vid}: {type(e).__name__}")

    out = {"available": True, "bar_ts": bar_ts, "patterns": hits,
           "ids": [h["id"] for h in hits], "n": len(hits),
           "confluence": len(hits) >= 2, "checked": checked,
           "method": "gates",   # دروازه‌های ورود، بدون اثر اسلات/کول‌داون
           "note": "" if hits else "هیچ الگویی روی این کندل شرط ورود نداشت",
           "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if errors:
        out["errors"] = errors
    return out


# ══════════════════════════════════════════════════════════════════════════
#  ۲) کارنامهٔ الگوها از ژورنال واقعی
# ══════════════════════════════════════════════════════════════════════════
def _stats(rs: Sequence[float]) -> dict:
    n = len(rs)
    if not n:
        return {"n": 0, "wins": 0, "win_rate": None, "expectancy_r": None,
                "profit_factor": None, "r_sum": 0.0}
    wins = [r for r in rs if r > 0]
    gw = sum(wins)
    gl = abs(sum(r for r in rs if r <= 0))
    return {
        "n": n,
        "wins": len(wins),
        "win_rate": round(len(wins) / n * 100.0, 1),
        "expectancy_r": round(sum(rs) / n, 3),
        "profit_factor": (round(gw / gl, 2) if gl > 0 else None),
        "r_sum": round(sum(rs), 3),
    }


def scorecard(journal: Sequence[dict]) -> dict:
    """کارنامهٔ هر الگو + سهم سیگنال‌های هم‌گرا از ژورنال.

    هر رکورد `open` یک سیگنال است؛ اگر `pattern_votes` داشته باشد (که live از
    این نسخه به بعد می‌نویسد) معلوم می‌شود چه الگوهای دیگری هم همان کندل را
    تأیید کرده‌اند. رکوردهای قدیمی بدون رأی، فقط به حساب الگوی سازندهٔ سیگنال
    می‌روند و در ستون «هم‌گرا» شمرده نمی‌شوند — نه اینکه صفر فرض شوند.
    """
    opens = {r.get("id"): r for r in journal if r.get("type") == "open"}
    closes = [r for r in journal if r.get("type") == "close"]

    # R هر سیگنال بسته‌شده
    r_by_open: Dict[str, float] = {}
    for c in closes:
        oid = c.get("open_id") or ""
        res = c.get("result") or {}
        r = res.get("r_multiple")
        if r is None:
            continue
        r_by_open[oid] = float(r)

    per_algo: Dict[str, dict] = {}
    per_vote: Dict[str, dict] = {}
    solo_rs: List[float] = []
    conf_rs: List[float] = []
    voted = 0
    unvoted = 0

    for oid, o in opens.items():
        algo = (o.get("algorithm") or {}).get("id") or "?"
        label = (o.get("algorithm") or {}).get("label") or ""
        d = per_algo.setdefault(algo, {
            "id": algo, "label": label, "signals": 0, "closed": 0,
            "rs": [], "modes": {}, "confluence_signals": 0, "solo_signals": 0,
            "no_vote": 0})
        d["signals"] += 1
        m = (o.get("entry_pattern") or {}).get("mode")
        if m:
            d["modes"][m] = d["modes"].get(m, 0) + 1

        r = r_by_open.get(oid)
        if r is not None:
            d["closed"] += 1
            d["rs"].append(r)

        votes = o.get("pattern_votes") or {}
        ids = list(votes.get("ids") or [])
        if not votes or not votes.get("available"):
            d["no_vote"] += 1
            unvoted += 1
            ids = [algo]                      # رأی نداریم؛ فقط سازندهٔ سیگنال
        else:
            voted += 1
            if len(ids) >= 2:
                d["confluence_signals"] += 1
                if r is not None:
                    conf_rs.append(r)
            else:
                d["solo_signals"] += 1
                if r is not None:
                    solo_rs.append(r)

        for pid in ids:
            v = per_vote.setdefault(pid, {"id": pid, "label": "", "signals": 0,
                                          "closed": 0, "rs": [], "unique": 0,
                                          "solo_rs": [], "conf_rs": []})
            v["signals"] += 1
            if r is not None:
                v["closed"] += 1
                v["rs"].append(r)
                if len(ids) >= 2:
                    v["conf_rs"].append(r)
                else:
                    v["unique"] += 1
                    v["solo_rs"].append(r)
            if len(ids) == 1:
                v["label"] = (o.get("algorithm") or {}).get("label") or v["label"]

    for algo, d in per_algo.items():
        st = _stats(d.pop("rs"))
        d.update(st)
        d["verdict"] = _verdict(st)

    for pid, v in per_vote.items():
        st = _stats(v.pop("rs"))
        v.update(st)
        v["verdict"] = _verdict(st)
        v["solo"] = _stats(v.pop("solo_rs"))
        v["concurrent"] = _stats(v.pop("conf_rs"))
        if not v["label"]:
            v["label"] = (per_algo.get(pid) or {}).get("label") or pid

    return {
        "version": VERSION,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "min_n": MIN_N,
        "signals_total": len(opens),
        "closed_total": len(r_by_open),
        "voted_signals": voted,
        "unvoted_signals": unvoted,
        "confluence": {
            "n": len(conf_rs) + len(solo_rs),
            "multi": _stats(conf_rs),
            "solo": _stats(solo_rs),
            "note": ("اختلاف «هم‌گرا» و «یگانه» می‌گوید تأیید چند الگو ارزش داشت یا نه؛ "
                     "اگر هم‌گرا بهتر نیست، داشتن چند الگو فقط شلوغی است."),
        },
        "by_algorithm": per_algo,
        "by_pattern_vote": per_vote,
    }


def _verdict(st: dict) -> str:
    if (st.get("n") or 0) < MIN_N:
        return VERDICT_NEED
    e = st.get("expectancy_r")
    if e is None:
        return VERDICT_NEED
    return VERDICT_KEEP if e > 0 else VERDICT_DROP


def prune_plan(card: dict) -> dict:
    """پیشنهاد حذف/نگه‌داشتن — بر اساس قاعدهٔ ثابت، نه سلیقه."""
    rows = card.get("by_pattern_vote") or {}
    keep, drop, need = [], [], []
    for pid, v in rows.items():
        item = {"id": pid, "label": v.get("label"), "n": v.get("n"),
                "expectancy_r": v.get("expectancy_r"), "win_rate": v.get("win_rate")}
        if v.get("verdict") == VERDICT_KEEP:
            keep.append(item)
        elif v.get("verdict") == VERDICT_DROP:
            drop.append(item)
        else:
            need.append(item)
    keep.sort(key=lambda x: -(x.get("expectancy_r") or -9))
    drop.sort(key=lambda x: (x.get("expectancy_r") or 0))
    return {"keep": keep, "drop": drop, "need_more": need,
            "rule": (f"n ≥ {MIN_N} و expectancy > 0 ⇒ نگه‌دار · "
                     f"n ≥ {MIN_N} و expectancy ≤ 0 ⇒ نامزد حذف · "
                     f"n < {MIN_N} ⇒ حکم نمی‌دهیم"),
            "note": "این فقط پیشنهاد است. حذف الگو باید آگاهانه و بعد از نمونهٔ کافی باشد."}


# ══════════════════════════════════════════════════════════════════════════
#  ۳) گزارش
# ══════════════════════════════════════════════════════════════════════════
def _p(x, nd=2, suf="") -> str:
    return "—" if x is None else f"{x:.{nd}f}{suf}"


def render(card: dict, lang: str = "fa") -> str:
    plan = prune_plan(card)
    L = ["# کارنامهٔ الگوها — این سیگنال بابت کدام الگو بود؟\n"]
    L.append(f"*{card.get('created_utc')}* · سیگنال: {card.get('signals_total')} · "
             f"بسته‌شده: {card.get('closed_total')} · "
             f"با رأی الگوها: {card.get('voted_signals')} · "
             f"بدون رأی (ژورنال قدیمی): {card.get('unvoted_signals')}\n")

    L.append("## الگویی که سیگنال را ساخت\n")
    L.append("| الگو | سیگنال | بسته | نرخ برد | expectancy R | ضریب سود | حکم |")
    L.append("|---|---:|---:|---:|---:|---:|---|")
    for aid, d in sorted(card["by_algorithm"].items(),
                         key=lambda kv: (kv[1].get("expectancy_r") is None,
                                         -(kv[1].get("expectancy_r") or -9))):
        L.append(f"| `{aid}` | {d['signals']} | {d['closed']} | "
                 f"{_p(d.get('win_rate'), 1, '٪')} | {_p(d.get('expectancy_r'), 3, 'R')} | "
                 f"{_p(d.get('profit_factor'), 2)} | {d.get('verdict', '')} |")
    L.append("")

    L.append("## رأی الگوها روی همان کندل (هم‌گرایی)\n")
    L.append("| الگو | حضور | بسته | expectancy R | فقط خودش تنها | با تأیید دیگران | حکم |")
    L.append("|---|---:|---:|---:|---:|---:|---|")
    for pid, v in sorted(card["by_pattern_vote"].items(),
                         key=lambda kv: -(kv[1].get("expectancy_r") or -9)):
        solo = v.get("solo") or {}
        conf = v.get("concurrent") or {}
        L.append(f"| `{pid}` | {v.get('signals')} | {v.get('closed')} | "
                 f"{_p(v.get('expectancy_r'), 3, 'R')} | "
                 f"{_p(solo.get('expectancy_r'), 3, 'R')} ({solo.get('n', 0)}) | "
                 f"{_p(conf.get('expectancy_r'), 3, 'R')} ({conf.get('n', 0)}) | "
                 f"{v.get('verdict', '')} |")
    L.append("")

    c = card.get("confluence") or {}
    multi, solo = c.get("multi") or {}, c.get("solo") or {}
    L.append("## آیا تأیید چند الگو ارزش داشت؟\n")
    L.append("| حالت | n | expectancy R | نرخ برد |")
    L.append("|---|---:|---:|---:|")
    L.append(f"| چند الگو هم‌زمان | {multi.get('n', 0)} | "
             f"{_p(multi.get('expectancy_r'), 3, 'R')} | {_p(multi.get('win_rate'), 1, '٪')} |")
    L.append(f"| فقط یک الگو | {solo.get('n', 0)} | "
             f"{_p(solo.get('expectancy_r'), 3, 'R')} | {_p(solo.get('win_rate'), 1, '٪')} |")
    L.append("")
    L.append(c.get("note", ""))
    L.append("")

    L.append("## پیشنهاد حذف/نگه‌داشتن\n")
    L.append(f"قاعدهٔ ثابت: {plan['rule']}\n")
    if plan["keep"]:
        L.append("**نگه‌دار:** " + "، ".join(
            f"`{x['id']}` ({_p(x['expectancy_r'], 2, 'R')}، n={x['n']})"
            for x in plan["keep"]))
    if plan["drop"]:
        L.append("**نامزد حذف:** " + "، ".join(
            f"`{x['id']}` ({_p(x['expectancy_r'], 2, 'R')}، n={x['n']})"
            for x in plan["drop"]))
    if plan["need_more"]:
        L.append("**داده کافی نیست:** " + "، ".join(
            f"`{x['id']}` (n={x['n']})" for x in plan["need_more"]))
    L.append("")
    L.append(plan["note"])
    return "\n".join(L)


# ══════════════════════════════════════════════════════════════════════════
#  ۴) CLI
# ══════════════════════════════════════════════════════════════════════════
def patterns_command(argv=None) -> int:
    import argparse

    from .live import read_journal

    p = argparse.ArgumentParser(
        prog="mtflab patterns",
        description="کارنامهٔ الگوها: هر سیگنال بابت کدام الگو بود و کدام بی‌فایده است")
    p.add_argument("--journal", default="results/live/journal.jsonl")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--lang", choices=["fa", "en"], default="fa")
    p.add_argument("--json", action="store_true", help="فقط JSON، بدون چاپ گزارش")
    a = p.parse_args(argv)

    if not os.path.exists(a.journal):
        print(f"❌ ژورنالی نیست: {a.journal}\n"
              "   اول live را اجرا کن (bash run-auto.sh --live) تا سیگنال‌ها ثبت شوند.")
        return 2

    journal = read_journal(a.journal)
    card = scorecard(journal)
    if not card["signals_total"]:
        print("⚠️  ژورنال خالی است — هیچ سیگنالی برای حسابرسی نیست.")
        return 1

    if not a.json:
        print(render(card, a.lang))
    os.makedirs(a.out_dir, exist_ok=True)
    md_path = os.path.join(a.out_dir, "pattern_scorecard.md")
    js_path = os.path.join(a.out_dir, "pattern_scorecard.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render(card, a.lang))
    with open(js_path, "w", encoding="utf-8") as f:
        json.dump({"card": card, "plan": prune_plan(card)}, f,
                  ensure_ascii=False, indent=1, default=str)
    if not a.json:
        print(f"\n📄 {os.path.abspath(md_path)}")
    return 0
