#!/bin/bash
echo "===================================================================="
echo "   🎣 در حال راه‌اندازی موتور اتوترید تور ماهیگیری (Net Fishing)"
echo "===================================================================="
echo ""

python3 scalplab/net_fishing_engine.py --symbol BTCUSDT --data auto --capital 1000 --leverage 5 --layers 5
