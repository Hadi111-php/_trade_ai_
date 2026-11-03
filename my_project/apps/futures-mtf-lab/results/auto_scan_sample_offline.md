> **SAMPLE OUTPUT — not a result.** Generated with 2 symbols from bundled data to
> prove the pipeline works on a phone. A real run covers 20 symbols and writes
> `auto_scan_<date>.md` (Persian by default, `--lang en` for English).

# Multi-symbol autoscan report

*generated: 2026-10-31 07:52 UTC · scanner 1.0 · runtime 6.7s*

- symbols: **2** · trigger tf `4h` / filter `1d` · window 1460 days
- costs: 5.5 bps + 0.02% slippage per side · risk 1.0% · max 1 concurrent

## 1) Verdict

**FAIL: no variant passed the acceptance gate.**

Best by median expectancy: **`trend`** at +7.97$ (median PF 1.9456) across 2 symbols and 211 trades.

Pre-registered gate: >= 8 symbols · PF>1 in >=60.0% of symbols · positive years >=60.0% · median PF >= 1.05 · sign-test p <= 0.1 vs base.

## 2) Variants (same timeframe, same symbols)

| variant | symbols | trades | median PF | median exp | PF>1 | pos. years | p vs base | gate |
|---|---:|---:|---:|---:|---:|---:|---:|:--:|
| `base` | 2 | 464 | 1.0812 | +0.57$ | 2/100.0% | 6/11 (54.55%) | — | FAIL |
| `trend` | 2 | 211 | 1.9456 | +7.97$ | 2/100.0% | 8/11 (72.73%) | 0.5 (2/2) | FAIL |
| `trend_tp` | 2 | 269 | 1.6247 | +5.38$ | 2/100.0% | 10/11 (90.91%) | 0.5 (2/2) | FAIL |
| `pullback` | 2 | 288 | 1.0041 | +0.02$ | 1/50.0% | 5/11 (45.45%) | 0.5 (0/2) | FAIL |
| `climax` | 2 | 260 | 1.1627 | +0.95$ | 2/100.0% | 6/11 (54.55%) | 1.0 (1/2) | FAIL |

## 3) Per symbol — `trend`

| symbol | coverage | trades | PF | expectancy | return% | max DD% | pos. years |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 5.7y | 108 | 1.9456 | +7.97$ | +86.04% | -10.23% | 6/6 |
| ETHUSDT | 4.73y | 103 | 1.212 | +1.54$ | +15.85% | -16.19% | 2/5 |

## 4) Year by year — `trend` (PnL in $)

| symbol | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | +165.39 | +39.28 | +144.39 | +92.05 | +298.58 | +120.68 |
| ETHUSDT | — | -27.70 | +168.57 | -11.15 | -68.18 | +96.92 |

## 5) Data coverage

| symbol | candles | years | from | to | source |
|---|---:|---:|---|---|---|
| BTCUSDT | 12488 | 5.7 | 2020-03-25 | 2025-12-05 | CSV محلی |
| ETHUSDT | 10361 | 4.73 | 2021-03-15 | 2025-12-05 | CSV محلی |

## 6) Limitations

- **Survivorship bias**: the symbol list contains coins alive *today*; delisted (losing) coins are missing.
- Symbols have different histories; younger ones carry less weight but still count in 'positive years'.
- The symbol list is fixed in code and was not tuned after seeing results.
- PAPER only: no orders are sent and none of these are realized profits.

---
_Backtest on historical data, not trading advice._
