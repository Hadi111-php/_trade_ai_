#!/usr/bin/env bash
# ============================================================================
# scalp-lab — Auto-Regime + Forensic Report
# برای Termux — یک‌مرحله‌ای: klon + backtest + analysis
# ============================================================================
#
# چه کار می‌کند:
#   ۱. بررسی محیط (python3, git)
#   ۲. klon یا pull repo
#   ۳. selftest
#   ۴. backtest auto-regime برای BTC و ETH (1 سال داده واقعی Bybit)
#   ۵. تحلیلِ forensic: exit reasons، profit-eating detection، market state
#   ۶.汇总 report
#
#用法:
#   bash run_autoregime.sh
# ============================================================================

set -e

#สี‌ها
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "========================================================="
echo "  scalp-lab — Auto-Regime + Forensic Report"
echo "  برای Termux — یک‌مرحله‌ای"
echo "========================================================="
echo -e "${NC}"

# ۱. بررسی python3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ python3 یافت نشد:${NC}"
    echo "   pkg install python"
    exit 1
fi
echo -e "${GREEN}✅ python3: $(python3 --version)${NC}"

# ۲. بررسی git
if ! command -v git &> /dev/null; then
    echo -e "${RED}❌ git یافت نشد:${NC}"
    echo "   pkg install git"
    exit 1
fi
echo -e "${GREEN}✅ git: $(git --version)${NC}"
echo ""

# ۳. مسیرها — absolute paths
REPO_URL="https://github.com/Hadi111-php/_trade_ai_.git"
SCALPLAB_DIR="$HOME/scalplab"
SCALPLAB_APP="$SCALPLAB_DIR/my_project/apps/futures-scalp-lab"

echo -e "${BLUE}📁 SCALPLAB_DIR: $SCALPLAB_DIR${NC}"
echo -e "${BLUE}📁 SCALPLAB_APP: $SCALPLAB_APP${NC}"
echo ""

# ۴. klon یا pull
if [ -d "$SCALPLAB_DIR/.git" ]; then
    echo -e "${YELLOW}📦 repo وجود دارد — pullِ latest...${NC}"
    cd "$SCALPLAB_DIR" || { echo -e "${RED}❌ cd به $SCALPLAB_DIR ناموفق${NC}"; exit 1; }
    git pull origin main 2>&1 | tail -3
else
    echo -e "${YELLOW}📦 klon repo از گیت هاب...${NC}"
    git clone "$REPO_URL" "$SCALPLAB_DIR" 2>&1 | tail -5
    if [ ! -d "$SCALPLAB_DIR/.git" ]; then
        echo -e "${RED}❌ clone ناموفق${NC}"
        exit 1
    fi
    cd "$SCALPLAB_DIR" || { echo -e "${RED}❌ cd به $SCALPLAB_DIR ناموفق${NC}"; exit 1; }
fi
echo ""
echo -e "${GREEN}✅ repo root: $(pwd)${NC}"

# ۵. navigate به scalp-lab
if [ ! -d "$SCALPLAB_APP" ]; then
    echo -e "${RED}❌ مسیر scalp-lab یافت نشد: $SCALPLAB_APP${NC}"
    exit 1
fi
cd "$SCALPLAB_APP" || { echo -e "${RED}❌ cd به $SCALPLAB_APP ناموفق${NC}"; exit 1; }
echo -e "${GREEN}✅ scalp-lab: $(pwd)${NC}"
echo ""

# ۶. selftest
echo -e "${CYAN}=========================================================${NC}"
echo -e "${CYAN}  ۱. selftest${NC}"
echo -e "${CYAN}=========================================================${NC}"
python3 -m scalplab selftest 2>&1
echo ""

# ۷. بررسی داده‌ها
echo -e "${CYAN}=========================================================${NC}"
echo -e "${CYAN}  ۲. بررسیِ داده‌ها${NC}"
echo -e "${CYAN}=========================================================${NC}"
echo ""
echo -e "${BLUE}📊 داده‌های CSV:${NC}"
ls -lh data/*.csv 2>/dev/null | awk '{print "  "$NF, "("$5")"}'
echo ""
echo -e "${BLUE}📊 داده windows:${NC}"
ls -lh data/windows/*.csv 2>/dev/null | awk '{print "  "$NF, "("$5")"}'
echo ""

# ۸. backtestِ auto-regime
echo -e "${CYAN}=========================================================${NC}"
echo -e "${CYAN}  ۳. backtestِ Auto-Regime (config خودکار)${NC}"
echo -e "${CYAN}=========================================================${NC}"
echo ""

# backtest directory
mkdir -p results/autoregime_run

# BTC
echo -e "${BLUE}🔍 BTC — auto-regime (3 ماه اخیر) + trailing fix:${NC}"
python3 -m scalplab trader \
    --data csv \
    --csv data/btcusdt_1h_lastyear.csv \
    --tf 1h \
    --symbol BTCUSDT \
    --preset optimal \
    --run-id autoregime-btc \
    --risk 1.0 \
    --fixed-risk 10 \
    --rr 2.0 \
    --entry-mode both \
    --equity 1000 \
    --daily-loss 10 \
    --auto-regime \
    --regime-months 3 2>&1 | tail -25
echo ""

# ETH
echo -e "${BLUE}🔍 ETH — auto-regime (3 ماه اخیر) + trailing fix:${NC}"
python3 -m scalplab trader \
    --data csv \
    --csv data/ethusdt_1h_lastyear.csv \
    --tf 1h \
    --symbol ETHUSDT \
    --preset optimal \
    --run-id autoregime-eth \
    --risk 1.0 \
    --fixed-risk 10 \
    --rr 2.0 \
    --entry-mode both \
    --equity 1000 \
    --daily-loss 10 \
    --auto-regime \
    --regime-months 3 2>&1 | tail -25
echo ""

# ۹. Forensic analysis
echo -e "${CYAN}=========================================================${NC}"
echo -e "${CYAN}  ۴. تحلیلِ Forensic — exit reasons + profit-eating${NC}"
echo -e "${CYAN}=========================================================${NC}"
echo ""

python3 << 'PYEOF'
import json, os, sys
from collections import defaultdict
from datetime import datetime

def analyze_symbol(sym_label, run_id):
    """Analyze forensic data for one symbol."""
    print(f"\n{'='*60}")
    print(f"  {sym_label} — Forensic Analysis ({run_id})")
    print(f"{'='*60}")

    # Load trades
    trades_path = f"results/autoregime_run/trader_trades_{run_id}.jsonl"
    if not os.path.exists(trades_path):
        print(f"  ❌ trades file not found: {trades_path}")
        return

    trades = []
    with open(trades_path) as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))

    if not trades:
        print(f"  ❌ no trades found")
        return

    # Summary
    wins = [t for t in trades if t.get("is_win", False)]
    losses = [t for t in trades if not t.get("is_win", False)]
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    gross_win = sum(t.get("pnl", 0) for t in wins)
    gross_loss = abs(sum(t.get("pnl", 0) for t in losses))
    pf = round(gross_win / gross_loss, 3) if gross_loss > 0 else 0.0

    print(f"\n  📊 Summary:")
    print(f"     Trades: {len(trades)} | Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"     Win Rate: {len(wins)/len(trades)*100:.0f}%")
    print(f"     Profit Factor: {pf}")
    print(f"     Total PnL: {total_pnl:+.2f}")
    print(f"     Return: {(total_pnl/1000)*100:+.2f}%")

    # Exit reason analysis
    by_reason = defaultdict(list)
    for t in trades:
        by_reason[t.get("reason", "?")].append(t)

    print(f"\n  📋 Exit Reason Analysis:")
    print(f"     {'Reason':<30} {'n':>3} {'AvgPnL':>8} {'AvgMFE':>7} {'AvgMAE':>7} {'Win%':>5}")
    print(f"     {'-'*65}")
    for reason, ts in sorted(by_reason.items()):
        pnls = [t.get("pnl", 0) for t in ts]
        mfes = [t.get("mfe_pct", 0) for t in ts]
        maes = [t.get("mae_pct", 0) for t in ts]
        wins_r = sum(1 for t in ts if t.get("is_win", False))
        avg_pnl = sum(pnls)/len(pnls) if pnls else 0
        avg_mfe = sum(mfes)/len(mfes) if mfes else 0
        avg_mae = sum(maes)/len(maes) if maes else 0
        wr = wins_r/len(ts)*100 if ts else 0
        # color coding
        pnl_color = "\033[0;32m" if avg_pnl > 0 else "\033[0;31m"
        print(f"     {reason:<30} {len(ts):>3} {pnl_color}{avg_pnl:>+8.2f}\033[0m {avg_mfe:>+6.2f}% {avg_mae:>+6.2f}% {wr:>4.0f}%")

    # Profit-eating detection
    eaten = []
    for t in trades:
        pnl = t.get("pnl", 0)
        mfe = t.get("mfe_pct", 0)
        # Profit eaten: trade went positive but exited with small/no profit
        if pnl > 0 and mfe > 1.0 and pnl < 5:
            eaten.append(t)

    # Trades that had positive MFE but lost (could have been winners)
    could_win = []
    for t in trades:
        pnl = t.get("pnl", 0)
        mfe = t.get("mfe_pct", 0)
        if pnl <= 0 and mfe > 1.0:
            could_win.append(t)

    print(f"\n  🔍 Profit-Eating Detection:")
    if eaten:
        print(f"     ⚠️  {len(eaten)} trades with small profit despite high MFE:")
        for t in eaten:
            side = "LONG" if t.get("side", 1) == 1 else "SHORT"
            print(f"       {side}: PnL={t.get('pnl',0):+.2f}, MFE={t.get('mfe_pct',0):+.2f}%, "
                  f"exit={t.get('reason','?')}, bars={t.get('bars_held',0)}")
    else:
        print(f"     ✅ No profit-eating detected (all profitable trades captured their MFE)")

    print(f"\n  ⚠️  Trades with positive MFE but lost (could have been winners):")
    if could_win:
        for t in could_win:
            side = "LONG" if t.get("side", 1) == 1 else "SHORT"
            print(f"       {side}: PnL={t.get('pnl',0):+.2f}, MFE={t.get('mfe_pct',0):+.2f}%, "
                  f"MAE={t.get('mae_pct',0):+.2f}%, exit={t.get('reason','?')}")
    else:
        print(f"     ✅ None — all losing trades never went positive")

    # Individual trade detail
    print(f"\n  📋 All Trades:")
    print(f"     {'#':>3} {'Side':>5} {'Entry':>10} {'Exit':>10} {'PnL':>7} {'MFE%':>6} "
          f"{'MAE%':>6} {'Bars':>4} {'Regime':>10} {'Exit Reason':<25}")
    print(f"     {'-'*85}")
    for i, t in enumerate(sorted(trades, key=lambda x: x.get("pnl", 0)), 1):
        side = "LONG" if t.get("side", 1) == 1 else "SHORT"
        entry = t.get("entry", 0)
        exit_p = t.get("exit", 0)
        pnl = t.get("pnl", 0)
        mfe = t.get("mfe_pct", 0)
        mae = t.get("mae_pct", 0)
        bars = t.get("bars_held", 0)
        regime = t.get("regime_entry", "?")
        reason = t.get("reason", "?")
        pnl_color = "\033[0;32m" if pnl > 0 else "\033[0;31m"
        print(f"     {i:>3} {side:>5} {entry:>10.2f} {exit_p:>10.2f} "
              f"{pnl_color}{pnl:>+7.2f}\033[0m {mfe:>+6.2f}% {mae:>+6.2f}% {bars:>4} {regime:>10} {reason:<25}")

    # Market state at entry
    print(f"\n  📊 Market State at Entry (for each trade):")
    print(f"     {'#':>3} {'Regime':>10} {'ADX':>5} {'BB%':>5} {'VolZ':>6} {'RSI':>5} {'Conf':>5} {'Reason':<30}")
    print(f"     {'-'*80}")
    for i, t in enumerate(sorted(trades, key=lambda x: x.get("pnl", 0)), 1):
        ind = t.get("indicators_entry", {})
        regime = t.get("regime_entry", "?")
        adx = ind.get("adx", 0) if "indicators_regime_entry" in t else t.get("indicators_regime_entry", {}).get("adx", 0)
        reg_ind = t.get("indicators_regime_entry", {})
        adx = reg_ind.get("adx", 0)
        bb_pos = ind.get("bb_pos", 0)
        vol_z = ind.get("vol_z", 0)
        rsi = ind.get("rsi", 0)
        conf = t.get("confidence_entry", 0)
        reason = t.get("reason_entry", "?")
        print(f"     {i:>3} {regime:>10} {adx:>5.1f} {bb_pos:>5.2f} {vol_z:>6.2f} {rsi:>5.1f} {conf:>5.2f} {reason:<30}")

    # Trailing status
    trail_trades = [t for t in trades if t.get("trail_active", False)]
    print(f"\n  🐢 Trailing Status:")
    print(f"     Trades with trailing active: {len(trail_trades)}")
    for t in trail_trades:
        side = "LONG" if t.get("side", 1) == 1 else "SHORT"
        print(f"       {side}: PnL={t.get('pnl',0):+.2f}, MFE={t.get('mfe_pct',0):+.2f}%, "
              f"exit={t.get('reason','?')}, bars={t.get('bars_held',0)}")

    print()

# Analyze both symbols
analyze_symbol("BTC", "autoregime-btc")
analyze_symbol("ETH", "autoregime-eth")

# Overall summary
print(f"\n{'='*60}")
print(f"  OVERALL SUMMARY")
print(f"{'='*60}")
for sym, run_id in [("BTC", "autoregime-btc"), ("ETH", "autoregime-eth")]:
    trades_path = f"results/autoregime_run/trader_trades_{run_id}.jsonl"
    if os.path.exists(trades_path):
        trades = []
        with open(trades_path) as f:
            for line in f:
                line = line.strip()
                if line: trades.append(json.loads(line))
        wins = [t for t in trades if t.get("is_win", False)]
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        gross_win = sum(t.get("pnl", 0) for t in wins)
        gross_loss = abs(sum(t.get("pnl", 0) for t in [t for t in trades if not t.get("is_win", False)]))
        pf = round(gross_win / gross_loss, 3) if gross_loss > 0 else 0.0
        wr = len(wins)/len(trades)*100 if trades else 0
        print(f"  {sym}: {len(trades)} trades, {wr:.0f}% WR, PF={pf}, PnL={total_pnl:+.2f}")

print(f"\n✅ تمام. Forensic data در: results/autoregime_run/")
print(f"   - trader_trades_*.jsonl: معاملات کامل با semua indicators")
print(f"   - trader_signals_*.jsonl: سیگنال‌های ورود")
print(f"   - trader_report_*.json: خلاصهٔ backtest")
PYEOF

echo ""
echo -e "${CYAN}=========================================================${NC}"
echo -e "${CYAN}  ۵. کامل شد${NC}"
echo -e "${CYAN}=========================================================${NC}"
echo ""
echo -e "${GREEN}✅ تمام.${NC}"
echo ""
echo -e "${YELLOW}📁 نتایج:${NC}"
echo -e "    $(pwd)/results/autoregime_run/"
echo ""
echo -e "${YELLOW}📊 Forensic data:${NC}"
echo -e "    - trader_trades_*.jsonl: معاملات کامل با all indicators"
echo -e "    - trader_signals_*.jsonl: سیگنال‌های ورود"
echo -e "    - trader_report_*.json: خلاصهٔ backtest"
echo ""
echo -e "${YELLOW}🔍 profit-eating check:${NC}"
echo -e "    در بخشِ ۴ — تشخیصِ trades با small profit despite high MFE"
echo ""
