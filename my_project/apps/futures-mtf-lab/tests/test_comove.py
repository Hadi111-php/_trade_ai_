"""تست‌های تحلیل هم‌حرکتی (comove).

مهم‌ترین اصل: ابزار باید **هم بتواند سیگنال پیدا کند و هم بتواند رد کند**.
اگر فقط روی دادهٔ واقعی اجرا شود و نتیجه هرچه بود بپذیریم، ابزار تزئینی است.
پس اینجا دو کنترل می‌گذاریم:

- **کنترل مثبت:** داده‌ای می‌سازیم که در آن واقعاً دو گروه پنهان وجود دارد
  ⇒ H1 باید تأیید و H2 باید پایدار باشد.
- **کنترل منفی:** دادهٔ کاملاً تصادفی ⇒ H1 باید رد شود.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtflab import comove as C                                        # noqa: E402


# ── ریاضیات پایه ────────────────────────────────────────────────────────────
def test_rank_handles_ties():
    assert C.rank([10, 20, 30]) == [1.0, 2.0, 3.0]
    assert C.rank([5, 5, 9]) == [1.5, 1.5, 3.0]


def test_spearman_is_one_for_monotone():
    a = [1, 2, 3, 4, 5]
    assert abs(C.spearman(a, [x * 100 + 7 for x in a]) - 1.0) < 1e-9
    assert abs(C.spearman(a, [5, 4, 3, 2, 1]) + 1.0) < 1e-9


def test_spearman_handles_constant_series():
    """سری ثابت نباید خطا بدهد (تقسیم بر صفر)."""
    assert C.spearman([1, 1, 1, 1], [1, 2, 3, 4]) == 0.0


def test_adjusted_rand_identical_and_random():
    a = [0, 0, 1, 1, 2, 2]
    assert abs(C.adjusted_rand(a, a) - 1.0) < 1e-9
    b = [0, 1, 0, 1, 0, 1]
    assert C.adjusted_rand(a, b) < 0.3


# ── ماتریس و خوشه ───────────────────────────────────────────────────────────
def test_corr_matrix_is_symmetric_with_unit_diagonal():
    panel = {"A": [0.01, -0.02, 0.03, 0.04, -0.01],
             "B": [0.02, -0.01, 0.05, 0.02, -0.03],
             "C": [-0.01, 0.03, -0.02, -0.01, 0.05]}
    syms, m = C.corr_matrix(panel)
    assert syms == ["A", "B", "C"]
    for i in range(3):
        assert m[i][i] == 1.0
        for j in range(3):
            assert abs(m[i][j] - m[j][i]) < 1e-12


def test_cluster_groups_similar_together():
    panel = {"A": [1, 2, 3, 4, 5, 6],
             "B": [1.1, 2.1, 3.1, 4.1, 5.1, 6.1],
             "C": [6, 5, 4, 3, 2, 1],
             "D": [5.9, 4.9, 3.9, 2.9, 1.9, 0.9]}
    _, m = C.corr_matrix(panel)
    groups = C.cluster(m, k=2)
    flat = [sorted(g) for g in groups]
    assert [0, 1] in flat and [2, 3] in flat


def test_demean_removes_common_market_move():
    """اگر همه با هم بالا بروند، باقیمانده باید صفر شود."""
    panel = {"A": [0.10, 0.10], "B": [0.10, 0.10], "C": [0.10, 0.10]}
    res = C.demean_by_month(panel)
    for v in res.values():
        assert all(abs(x) < 1e-12 for x in v)


# ── کنترل مثبت: ساختار واقعی باید پیدا شود ─────────────────────────────────
def _two_groups(months=60, seed=5, noise=0.02, n_per_group=6):
    """دو گروه پنهان هم‌اندازه که خلاف هم حرکت می‌کنند.

    اندازهٔ گروه عمداً بزرگ است: با ۳ نماد در هر گروه، ۱۰٪ جایگشت‌ها تصادفاً همان
    افراز را بازتولید می‌کنند و کمترین p ممکن ۰.۱ می‌شود ⇒ آزمون بی‌دلیل «رد» می‌دهد.
    """
    rng = random.Random(seed)
    f1 = [rng.gauss(0, 0.05) for _ in range(months)]
    f2 = [-x for x in f1]
    panel = {}
    for g, f in ((0, f1), (1, f2)):
        for j in range(n_per_group):
            panel[f"G{g}S{j:02d}"] = [f[i] + rng.gauss(0, noise) for i in range(months)]
    return panel


def test_positive_control_finds_real_structure():
    """اگر واقعاً دو گروه وجود دارد، H1 باید تأیید شود."""
    panel = _two_groups()
    res = panel and C.demean_by_month(panel)
    _, m = C.corr_matrix(res)
    obs = C.mean_abs_corr(m)
    h1 = C.permutation_h1(res, obs, n_iter=300)
    assert h1["supported"] is True, h1
    assert h1["observed"] > h1["null_p95"]


def test_positive_control_clusters_are_correct():
    panel = C.demean_by_month(_two_groups())
    _, m = C.corr_matrix(panel)
    groups = [sorted(g) for g in C.cluster(m, k=2)]
    syms = sorted(panel)
    idx = {s: i for i, s in enumerate(syms)}
    g0 = [idx[s] for s in syms if s.startswith("G0")]
    g1 = [idx[s] for s in syms if s.startswith("G1")]
    assert g0 in groups and g1 in groups


def test_positive_control_stability_is_detected():
    """ساختار پایدار در دو نیمه باید ARI بالا بدهد."""
    panel = C.demean_by_month(_two_groups(months=80))
    h2 = C.stability_h2(panel, k=2, n_iter=300)
    assert h2["ok"] and h2["ari"] > 0.3, h2
    assert h2["mantel_r"] > 0.5, h2
    assert h2["supported"] is True, h2


# ── کنترل منفی: نویز خالص نباید سیگنال بدهد ──────────────────────────────────
def test_negative_control_pure_noise_is_rejected():
    """دادهٔ کاملاً تصادفی ⇒ H1 نباید تأیید شود (وگرنه ابزار تزئینی است)."""
    rng = random.Random(99)
    panel = {f"S{i}": [rng.gauss(0, 0.05) for _ in range(48)] for i in range(8)}
    res = C.demean_by_month(panel)
    _, m = C.corr_matrix(res)
    obs = C.mean_abs_corr(m)
    h1 = C.permutation_h1(res, obs, n_iter=300)
    assert h1["supported"] is False, h1


# ── اجرای کامل و گزارش ──────────────────────────────────────────────────────
def test_run_comove_refuses_two_symbols():
    """با ۲ نماد، باقیمانده‌ها قرینهٔ هم می‌شوند ⇒ همبستگی مصنوعی. باید رد کند."""
    try:
        C.run_comove(panel_override={"A": [0.01, 0.02], "B": [0.02, 0.01]})
    except RuntimeError as e:
        assert "۳ نماد" in str(e) or "3" in str(e)
    else:
        raise AssertionError("باید با ۲ نماد خطا می‌داد")


def test_run_comove_shape_and_verdict_keys():
    res = C.run_comove(panel_override=_two_groups(months=40), n_iter=150, k=2)
    for k in ("version", "symbols", "corr_raw", "corr_residual", "clusters",
              "hypothesis_h1", "hypothesis_h2", "verdict"):
        assert k in res
    assert set(res["verdict"]) == {"hidden_structure", "stable_groups"}
    assert len(res["clusters"]) == 2


def test_reports_render_in_both_languages():
    import re
    res = C.run_comove(panel_override=_two_groups(months=40), n_iter=120, k=2)
    C.set_lang("fa")
    fa = C.render_report(res)
    C.set_lang("en")
    en = C.render_report_en(res)
    C.set_lang("fa")
    assert "حکم" in fa and "فرضیهٔ H1" in fa
    assert "Verdict" in en and "H1" in en
    assert not re.search(r"[\u0600-\u06FF]", en), "گزارش انگلیسی نباید فارسی داشته باشد"


def test_monthly_returns_are_computed_from_closes():
    """بازده ماهانه = قیمت بستهٔ آخرین کندل هر ماه نسبت به ماه قبل."""
    from mtflab.data import Candle
    import datetime as dt
    ms = 4 * 3_600_000                     # کندل ۴ ساعته
    cs = []
    for mon, price in ((1, 100.0), (2, 110.0), (3, 99.0)):
        start = int(dt.datetime(2024, mon, 2, tzinfo=dt.timezone.utc).timestamp() * 1000)
        cs.append(Candle(start, price, price, price, price, 1.0))
    r = C.monthly_returns(cs)
    assert set(r) == {"2024-02", "2024-03"}
    assert abs(r["2024-02"] - 0.10) < 1e-9
    assert abs(r["2024-03"] + 0.10) < 1e-9


# ── هم‌ترازی تقویمی: باگی که نتیجهٔ ۲۰ نمادی را باطل کرد ────────────────────
def test_build_panel_aligns_by_calendar_not_position():
    """نمادی که داده‌اش زودتر تمام شده نباید بقیه را جابه‌جا کند.

    باگ واقعی: نسخهٔ اول ماه‌های گمشده را حذف می‌کرد و بعد `v[-cutoff:]` می‌گرفت.
    نمادی با ۸ ماه داده روی ماه‌های ۱..۸ می‌ماند و نمادی با ۱۲ ماه روی ۵..۱۲ →
    مقایسهٔ دو تقویم مختلف. با TONUSDT در اجرای واقعی دقیقاً همین رخ داد.
    """
    rets = {s: {f"2024-{m:02d}": 0.01 * (i + 1) for m in range(1, 13)}
            for i, s in enumerate(["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT"])}
    rets["TONUSDT"] = {f"2024-{m:02d}": 0.01 for m in range(1, 9)}  # ۸ ماه

    months, panel, dropped = C.build_panel(rets, min_months=8)
    assert len({len(v) for v in panel.values()}) == 1, "طول‌ها باید برابر باشند"
    assert months == [f"2024-{m:02d}" for m in range(1, 9)], months
    # TON پنجره را محدود کرد ولی خودش حذف نشد (چون ۸ ماه ≥ حد)
    assert "TONUSDT" in panel
    assert dropped == {}


def test_build_panel_drops_symbol_that_shrinks_window_too_much():
    """اگر نمادی پنجره را زیر حداقل بیاورد، باید حذف و **ثبت** شود."""
    rets = {s: {f"2024-{m:02d}": 0.01 for m in range(1, 13)}
            for s in ["A", "B", "C", "D"]}
    rets["E"] = {f"2024-{m:02d}": 0.01 for m in range(1, 5)}   # فقط ۴ ماه
    months, panel, dropped = C.build_panel(rets, min_months=10)
    assert "E" not in panel
    assert "E" in dropped, "نماد حذف‌شده باید با دلیل ثبت شود"
    assert len(months) == 12


def test_build_panel_refuses_when_alignment_leaves_too_few():
    rets = {"A": {"2024-01": 0.1, "2024-02": 0.1},
            "B": {"2024-02": 0.1, "2024-03": 0.1},
            "C": {"2024-03": 0.1, "2024-04": 0.1}}
    try:
        C.build_panel(rets, min_months=3)
    except RuntimeError as e:
        assert "۳" in str(e) or "3" in str(e)
    else:
        raise AssertionError("باید خطا می‌داد")


def test_run_comove_panel_is_always_rectangular():
    """خروجی اجرای کامل باید ماه‌های برچسب‌دار و طول‌های برابر داشته باشد."""
    res = C.run_comove(panel_override=_two_groups(months=48), n_iter=120, k=2)
    st_ = res["settings"]
    assert len(st_["months_label"]) == st_["months"]
    assert st_["first_month"] and st_["last_month"]


# ── استحکام برش تصادفی ──────────────────────────────────────────────────────
def test_split_robustness_high_for_real_structure():
    panel = C.demean_by_month(_two_groups(months=80))
    rob = C.split_robustness(panel, n_splits=60, min_half=20)
    assert rob["ok"] and rob["median"] > 0.6, rob
    assert rob["share_above_threshold"] > 0.9


def test_split_robustness_low_for_noise():
    rng = random.Random(5)
    panel = C.demean_by_month({f"S{i}": [rng.gauss(0, 0.05) for _ in range(60)]
                               for i in range(8)})
    rob = C.split_robustness(panel, n_splits=60, min_half=15)
    assert rob["ok"] and rob["median"] < 0.30, rob


def test_marginal_flag_marks_borderline_pass():
    """قبول لب‌مرز باید «حاشیه‌ای» علامت بخورد تا با قبول محکم اشتباه نشود."""
    panel = C.demean_by_month(_two_groups(months=80))
    h2 = C.stability_h2(panel, k=2, n_iter=200)
    assert h2["supported"] is True
    assert h2["margin"] == round(h2["mantel_r"] - 0.30, 4)
    assert isinstance(h2["marginal"], bool)
