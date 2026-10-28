# Futures MTF Lab — multi-timeframe trading scenario (PAPER)

Version `2026-10-28.1` · **standard library only** (no numpy / pandas / requests /
pyyaml / pytest) · runs on any PC, phone (Termux) or VPS without `pip install`.

> Independent from `apps/futures-scalp-lab` (the previous single-timeframe
> scenario). No file of that app is modified; the only bridge is
> `mtflab/compare.py`, which imports it read-only to build the comparison
> dashboard.

> **Golden rule:** no number here is "real profit" unless it comes from real
> out-of-sample data, after full costs, with a statistically meaningful edge over
> a baseline. LIVE trading is deliberately not implemented.

---

## What it does

| Capability | Detail |
|---|---|
| Three-layer MTF alignment | bias 4h + regime filter 1h + entry trigger 15m, leak-tested |
| Alignment variants | **A** strict AND · **B** weighted score · **C** regime filter only |
| Cost/edge filter | rejects signals whose expected move < 1.5× round-trip cost |
| Risk | 1% equity risk, SL 1.5×ATR, TP 3×ATR, trailing after +1R, cooldown, circuit breaker, daily loss limit |
| Forensics | every signal / veto / trade in JSONL with full layer snapshots, MFE/MAE and diagnosis |
| Validation | 60/20/20 split · 6-window walk-forward with per-window reselection · 1000 Monte-Carlo · sensitivity · baselines · overfit checklist |
| Comparison dashboard | self-contained HTML, 5 tabs, old vs new scenario on identical data/costs |
| Bybit downloader | public klines, no API key, pagination, CSV cache, retry |

## Quick start

```bash
cd apps/futures-mtf-lab

python3 -m mtflab selftest                       # tests + causality + leakage + cost filter
python3 -m mtflab compare \
  --csv ../futures-scalp-lab/data/btcusdt_1h_lastyear.csv \
  --out results/dash_scenarios.html              # old vs new + dashboard
python3 -m mtflab serve --dir results --port 8080
```

## Real 15m data (the scenario's intended timeframe)

15m candles are not in the repo (and cannot be derived from 1h — `resample_up`
refuses). On a machine with internet:

```bash
python3 -m mtflab download --symbol BTCUSDT --days 730
python3 -m mtflab validate --data bybit --symbol BTCUSDT \
  --tf-trigger 15m --tf-filter 1h --tf-bias 4h --align A
```

## CLI

`run` (default) · `validate` · `compare` · `download` · `dashboard` · `serve` · `selftest`
Full flags: `python3 -m mtflab --help`

## Dashboard tabs

1. **Compare** — KPI side-by-side, overlaid equity curves, both cost models, verdict + bootstrap significance
2. **Old scenario** — TraderBrain detail (regime, exit reason, hour, best/worst trades)
3. **New scenario** — A/B/C comparison, per-layer veto stats, alignment health
4. **Validation** — split, walk-forward, Monte-Carlo, baselines, sensitivity, overfit checklist
5. **Health & pitfalls** — anti-lookahead test results, data gaps, pitfall coverage, run provenance

## Current results (BTCUSDT 1h, 1 year, identical costs)

| | Trades | PF | Expectancy | Return | MaxDD |
|---|---|---|---|---|---|
| New (A) | 107 | 0.871 | −0.79$ | −8.46% | −13.78% |
| Old (TraderBrain) | 163 | 0.943 | −0.33$ | −5.39% | — |
| Single-TF (no MTF layers) | 385 | 0.744 | −1.29$ | −49.61% | −52.37% |
| Random control | 140 | 0.679 | −2.22$ | −31.12% | −35.53% |
| Buy & Hold | — | — | — | −7.64% | −34.77% |

MTF layers are **better** than single-TF and random control (−0.79$ vs −1.29$ / −2.22$),
but neither scenario reaches PF > 1, and the old/new difference is **not
statistically significant** (bootstrap CI95 of expectancy diff `[−3.51, +2.71]$`).
See `docs/SUMMARY.md` for the honest breakdown.

## Docs

`docs/strategy_design.md` · `docs/validation_plan.md` · `docs/pitfalls.md` ·
`docs/pseudocode.md` · `docs/SUMMARY.md` · `docs/ORIGINAL_SCAFFOLD_NOTES_FA.md`
· Persian guide: `README_FA.md`

## Rules

1. **PAPER only.** LIVE is not implemented.
2. Every logic change needs a new test in `tests/` and a green `selftest`.
3. No API key or secret in code or config (all data is public).
4. The previous scenario stays untouched; improvements to it need their own PR.
