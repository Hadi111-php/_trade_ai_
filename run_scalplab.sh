#!/usr/bin/env bash
# ============================================================================
# scalp-lab — یک‌مرحله‌ای: klon + test + backtest
# برای Termux / PC
# ============================================================================

echo "========================================="
echo "  scalp-lab — یک‌مرحله‌ای"
echo "========================================="

# ۱. بررسیِ python3
if ! command -v python3 &> /dev/null; then
    echo "❌ python3 یافت نشد:"
    echo "   pkg install python"
    exit 1
fi
echo "✅ python3: $(python3 --version)"

# ۲. بررسیِ git
if ! command -v git &> /dev/null; then
    echo "❌ git یافت نشد:"
    echo "   pkg install git"
    exit 1
fi
echo "✅ git: $(git --version)"
echo ""

# ۳. مسیرها — absolute paths
REPO_URL="https://github.com/Hadi111-php/_trade_ai_.git"
SCALPLAB_DIR="$HOME/scalplab"
SCALPLAB_APP="$SCALPLAB_DIR/my_project/apps/futures-scalp-lab"

echo "📁 SCALPLAB_DIR: $SCALPLAB_DIR"
echo "📁 SCALPLAB_APP: $SCALPLAB_APP"
echo ""

# ۴. klon یا pull
if [ -d "$SCALPLAB_DIR/.git" ]; then
    echo "📦 repo وجود دارد — pullِ latest..."
    cd "$SCALPLAB_DIR" || { echo "❌ cd به $SCALPLAB_DIR ناموفق"; exit 1; }
    git pull origin main 2>&1 | tail -3
else
    echo "📦 klon repo از گیت هاب..."
    git clone "$REPO_URL" "$SCALPLAB_DIR" 2>&1 | tail -5
    if [ ! -d "$SCALPLAB_DIR/.git" ]; then
        echo "❌ clone ناموفق"
        exit 1
    fi
    cd "$SCALPLAB_DIR" || { echo "❌ cd به $SCALPLAB_DIR ناموفق"; exit 1; }
fi

echo ""
echo "✅ repo root: $(pwd)"

# ۵. navigate به scalp-lab — با absolute path
if [ ! -d "$SCALPLAB_APP" ]; then
    echo "❌ مسیر scalp-lab یافت نشد: $SCALPLAB_APP"
    echo "   ساختار repo:"
    ls -la "$SCALPLAB_DIR/"
    echo "   my_project contents:"
    ls -la "$SCALPLAB_DIR/my_project/" 2>/dev/null || echo "   my_project found نشد"
    exit 1
fi
cd "$SCALPLAB_APP" || { echo "❌ cd به $SCALPLAB_APP ناموفق"; exit 1; }
echo "✅ scalp-lab: $(pwd)"
echo ""

# ۶. selftest
echo "========================================="
echo "  ۱. selftest"
echo "========================================="
python3 -m scalplab selftest 2>&1
echo ""

# ۷. بررسیِ داده‌ها
echo "========================================="
echo "  ۲. بررسیِ داده‌ها"
echo "========================================="
echo ""
echo "📊 داده‌های CSV:"
ls -lh data/*.csv 2>/dev/null | awk '{print "  "$NF, "("$5")"}'
echo ""
echo "📋 نتایج:"
echo "  reports: $(ls results/trader_report_*.json 2>/dev/null | wc -l) JSON"
echo "  signals: $(ls results/trader_signals_*.jsonl 2>/dev/null | wc -l) JSONL"
echo ""

# ۸. backtestِ optimal — فقط breakout
echo "========================================="
echo "  ۳. backtestِ optimal — فقط breakout"
echo "========================================="
echo ""
echo "🔍 BTC (1 سالِ dernier) — vol_min=4.0:"
python3 -m scalplab trader \
    --data csv \
    --csv data/btcusdt_1h_lastyear.csv \
    --tf 60 \
    --symbol BTCUSDT \
    --run-id brk-btc-optimal \
    --risk 1.0 \
    --fixed-risk 10 \
    --rr 2.0 \
    --entry-mode both \
    --equity 1000 \
    --daily-loss 10 \
    --range-breakout \
    --rb-vol-min 4.0 \
    --no-trend 2>&1 | tail -15
echo ""

echo "🔍 ETH (1 سالِ dernier) — vol_min=4.0:"
python3 -m scalplab trader \
    --data csv \
    --csv data/ethusdt_1h_lastyear.csv \
    --tf 60 \
    --symbol ETHUSDT \
    --run-id brk-eth-optimal \
    --risk 1.0 \
    --fixed-risk 10 \
    --rr 2.0 \
    --entry-mode both \
    --equity 1000 \
    --daily-loss 10 \
    --range-breakout \
    --rb-vol-min 4.0 \
    --no-trend 2>&1 | tail -15
echo ""

# ۹. backtestِ ترکیب
echo "========================================="
echo "  ۴. backtestِ ترکیب — breakout + trend"
echo "========================================="
echo ""
echo "🔍 BTC (1 سالِ dernier) — breakout vol=4.0 + trend:"
python3 -m scalplab trader \
    --data csv \
    --csv data/btcusdt_1h_lastyear.csv \
    --tf 60 \
    --symbol BTCUSDT \
    --run-id combo-btc-optimal \
    --risk 1.0 \
    --fixed-risk 10 \
    --rr 2.0 \
    --entry-mode both \
    --equity 1000 \
    --daily-loss 10 \
    --range-breakout \
    --rb-vol-min 4.0 2>&1 | tail -15
echo ""

# ۱۰. backtestِ auto-regime — config خودکار طبق داده recent
echo "========================================="
echo "  ۵. backtestِ Auto-Regime — config خودکار"
echo "========================================="
echo ""
echo "🔍 BTC — auto-regime (3 ماه اخیر):"
python3 -m scalplab trader \
    --data csv \
    --csv data/btcusdt_1h_lastyear.csv \
    --tf 60 \
    --symbol BTCUSDT \
    --run-id auto-btc \
    --risk 1.0 \
    --fixed-risk 10 \
    --rr 2.0 \
    --entry-mode both \
    --equity 1000 \
    --daily-loss 10 \
    --range-breakout \
    --no-trend \
    --auto-regime \
    --regime-months 3 2>&1 | tail -20
echo ""

echo "🔍 ETH — auto-regime (3 ماه اخیر):"
python3 -m scalplab trader \
    --data csv \
    --csv data/ethusdt_1h_lastyear.csv \
    --tf 60 \
    --symbol ETHUSDT \
    --run-id auto-eth \
    --risk 1.0 \
    --fixed-risk 10 \
    --rr 2.0 \
    --entry-mode both \
    --equity 1000 \
    --daily-loss 10 \
    --range-breakout \
    --no-trend \
    --auto-regime \
    --regime-months 3 2>&1 | tail -20
echo ""

# ۱۲. خلاصه
echo "========================================="
echo "  ۶. خلاصهِ نتایج"
echo "========================================="
echo ""
for f in results/trader_report_brk-btc-optimal.json results/trader_report_brk-eth-optimal.json results/trader_report_combo-btc-optimal.json results/trader_report_auto-btc.json results/trader_report_auto-eth.json; do
    if [ -f "$f" ]; then
        name=$(basename "$f" .json | sed 's/trader_report_//')
        python3 -c "
import json
try:
    with open('$f') as fh:
        d = json.load(fh)
    s = d.get('summary',{})
    n = s.get('trades',0)
    wins = s.get('wins',0)
    pnl = s.get('total_pnl',0)
    pf = s.get('profit_factor',0)
    wr = (wins/n*100) if n > 0 else 0
    print(f'  $name: n={n} W={wins} WR={wr:.0f}% PnL={pnl:.2f} PF={pf:.3f}')
except Exception as e:
    print(f'  $name: error: {e}')
"
    fi
done
echo ""
echo "✅ تمام. نتایج در: $(pwd)/results/"
echo "========================================="
