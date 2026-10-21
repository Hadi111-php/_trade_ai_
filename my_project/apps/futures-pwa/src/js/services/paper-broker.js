import { STORAGE_KEYS } from '../core/config.js';
import { readJson, uid, writeJson } from '../core/utils.js';

export class PaperBroker {
  constructor(settings, logger) {
    this.s = settings;
    this.log = logger;
    const saved = readJson(STORAGE_KEYS.state, null);
    this.state = this.normalise(saved || this.initial());
    this.migrateDay();
  }

  initial() {
    const equity = Number(this.s.value.paperInitialEquity);
    return {
      paperEquity: equity,
      paperPositions: [],
      paperTrades: [],
      realOrders: [],
      lastCooldown: {},
      profileStarts: {},
      feesPaid: 0,
      day: new Date().toDateString(),
      dayStartEquity: equity
    };
  }

  normalise(saved) {
    const base = this.initial();
    const positions = Array.isArray(saved.paperPositions)
      ? saved.paperPositions.map(position => ({ ...position, riskProfile: position.riskProfile || 'medium' }))
      : [];
    const trades = Array.isArray(saved.paperTrades)
      ? saved.paperTrades.map(trade => ({ ...trade, riskProfile: trade.riskProfile || 'medium' }))
      : [];
    const profileStarts = saved.profileStarts && typeof saved.profileStarts === 'object'
      ? { ...saved.profileStarts }
      : {};
    // Existing v3 history predates profile tags; treat it as the default medium run.
    if (trades.length && profileStarts.medium === undefined) profileStarts.medium = Number(this.s.value.paperInitialEquity);
    return {
      ...base,
      ...saved,
      paperPositions: positions,
      paperTrades: trades,
      realOrders: Array.isArray(saved.realOrders) ? saved.realOrders : [],
      lastCooldown: saved.lastCooldown && typeof saved.lastCooldown === 'object' ? saved.lastCooldown : {},
      profileStarts,
      feesPaid: Number.isFinite(Number(saved.feesPaid)) ? Number(saved.feesPaid) : 0
    };
  }

  save() {
    writeJson(STORAGE_KEYS.state, this.state);
  }

  reset() {
    this.state = this.initial();
    this.save();
  }

  migrateDay() {
    const today = new Date().toDateString();
    if (this.state.day !== today) {
      this.state.day = today;
      this.state.dayStartEquity = this.state.paperEquity;
      this.save();
    }
  }

  oneWayFee(notional, percentage) {
    return Math.abs(Number(notional)) * (Number(percentage) / 100);
  }

  grossPnl(position, mark) {
    const direction = position.side === 'LONG' ? 1 : -1;
    return (Number(mark) - Number(position.entry)) * direction * Number(position.qty);
  }

  closeFee(position, mark) {
    return this.oneWayFee(Number(mark) * Number(position.qty), this.s.value.feeClosePct);
  }

  // This is the cash/equity delta at a mark. Opening fee is already removed
  // from paperEquity when the position is opened, so it is not removed twice.
  markToMarketDelta(position, mark) {
    return this.grossPnl(position, mark) - this.closeFee(position, mark);
  }

  // Net PnL shown for validation: gross movement minus both entry and exit fees.
  netPnl(position, mark) {
    return this.grossPnl(position, mark)
      - Number(position.openFee || 0)
      - this.closeFee(position, mark);
  }

  dailyLossExceeded() {
    const start = Number(this.state.dayStartEquity);
    if (!(start > 0)) return true;
    return ((start - Number(this.state.paperEquity)) / start * 100) >= Number(this.s.value.dailyLossLimitPct);
  }

  canOpen(signal) {
    const s = this.s.value;
    if (!signal || signal.side === 'WAIT' || this.dailyLossExceeded()) return false;
    if (this.state.paperPositions.length >= Number(s.maxOpenPositions)) return false;
    if (this.state.paperPositions.some(position => position.symbol === signal.symbol)) return false;
    const cooldown = Number(s.cooldownSec) * 1000;
    return Date.now() - Number(this.state.lastCooldown[signal.symbol] || 0) > cooldown;
  }

  open(signal, reason = 'auto', force = false) {
    if (!signal || signal.side === 'WAIT') return false;
    // Manual entry may bypass cooldown, never the account-level safety checks.
    if (this.dailyLossExceeded()) return false;
    if (this.state.paperPositions.length >= Number(this.s.value.maxOpenPositions)) return false;
    if (this.state.paperPositions.some(position => position.symbol === signal.symbol)) return false;
    if (!force && !this.canOpen(signal)) return false;

    const openFee = this.oneWayFee(signal.notional, this.s.value.feeOpenPct);
    const riskProfile = this.s.value.riskProfile || 'medium';
    if (!Object.prototype.hasOwnProperty.call(this.state.profileStarts, riskProfile)) {
      this.state.profileStarts[riskProfile] = this.state.paperEquity;
    }
    this.state.paperEquity -= openFee;
    this.state.feesPaid += openFee;
    this.state.paperPositions.push({
      id: uid(),
      symbol: signal.symbol,
      side: signal.side,
      entry: signal.entry,
      qty: signal.qty,
      notional: signal.notional,
      stop: signal.stop,
      take: signal.take,
      openFee,
      openedAt: Date.now(),
      reason,
      score: signal.score,
      riskProfile,
      signalId: signal.signalId,
      source: signal.source,
      candleTs: signal.candleTs
    });
    this.state.lastCooldown[signal.symbol] = Date.now();
    this.save();
    this.log.info('PAPER OPEN', {
      symbol: signal.symbol,
      side: signal.side,
      entry: signal.entry,
      qty: signal.qty,
      score: signal.score,
      feeOpen: openFee,
      source: signal.source
    });
    return true;
  }

  close(position, mark, reason = 'manual') {
    const exit = Number(mark);
    if (!Number.isFinite(exit) || exit <= 0) return false;
    const gross = this.grossPnl(position, exit);
    const feeClose = this.closeFee(position, exit);
    const feeOpen = Number(position.openFee || 0);
    const net = gross - feeOpen - feeClose;

    // openFee has already been charged; here we settle gross PnL and exit fee.
    this.state.paperEquity += gross - feeClose;
    this.state.feesPaid += feeClose;
    this.state.paperPositions = this.state.paperPositions.filter(item => item.id !== position.id);
    this.state.paperTrades.unshift({
      time: Date.now(),
      symbol: position.symbol,
      side: position.side,
      entry: Number(position.entry),
      exit,
      grossPnl: gross,
      feeOpen,
      feeClose,
      fees: feeOpen + feeClose,
      pnl: net,
      reason,
      score: position.score,
      riskProfile: position.riskProfile || this.s.value.riskProfile || 'legacy',
      source: position.source,
      durationSec: Math.max(0, Math.round((Date.now() - Number(position.openedAt)) / 1000))
    });
    this.state.paperTrades = this.state.paperTrades.slice(0, 350);
    this.save();
    this.log.info('PAPER CLOSE', {
      symbol: position.symbol,
      side: position.side,
      exit,
      gross,
      fees: feeOpen + feeClose,
      net,
      reason
    });
    return true;
  }

  updateStops(marketMap, signalsMap) {
    for (const position of [...this.state.paperPositions]) {
      const market = marketMap.get(position.symbol);
      const signal = signalsMap ? signalsMap.get(position.symbol) : null;
      if (!market) continue;

      const mark = Number(market.price);
      const candle = market.lastCandle || {};
      const high = Number.isFinite(Number(candle.high)) ? Number(candle.high) : mark;
      const low = Number.isFinite(Number(candle.low)) ? Number(candle.low) : mark;
      const isLong = position.side === 'LONG';
      const entry = Number(position.entry);
      let exit = null;
      let reason = '';

      // رهگیری بالاترین و پایین‌ترین قیمت ثبت‌شده برای محاسبه سود شناور
      if (!position.highWater) position.highWater = entry;
      if (!position.lowWater) position.lowWater = entry;

      if (isLong) {
        position.highWater = Math.max(position.highWater, mark, high);
      } else {
        position.lowWater = Math.min(position.lowWater, mark, low);
      }

      // ۱. سمت ضرر: فعال‌سازی سریع و قاطع استاپ‌لاس برای محافظت از اصل سرمایه
      if (isLong && (mark <= Number(position.stop) || low <= Number(position.stop))) {
        exit = Number(position.stop);
        reason = 'SL_HARD_STOP';
      } else if (!isLong && (mark >= Number(position.stop) || high >= Number(position.stop))) {
        exit = Number(position.stop);
        reason = 'SL_HARD_STOP';
      }

      // ۲. سمت سود: سیستم خروج هیبریدی نامتقارن (اجازه رشد نامحدود سود شناور تا زمان تایید برگشت روند)
      const gross = this.grossPnl(position, mark);
      const isInProfit = gross > (Number(position.openFee || 0) * 1.5);

      if (!exit && isInProfit) {
        // الف) انتقال خودکار استاپ به نقطه ورود + کارمزد (Breakeven) برای صفر کردن ریسک
        const breakevenStop = isLong ? (entry * 1.002) : (entry * 0.998);
        if (isLong && Number(position.stop) < breakevenStop) {
          position.stop = breakevenStop;
        } else if (!isLong && Number(position.stop) > breakevenStop) {
          position.stop = breakevenStop;
        }

        // ب) ترلینگ استاپ پویا بر پایه ATR پشت سر بالاترین سقف قیمت
        const atr = (signal && signal.atr) ? signal.atr : (mark * 0.005);
        const trailDistance = atr * 1.25;
        if (isLong) {
          const dynamicTrailStop = position.highWater - trailDistance;
          if (dynamicTrailStop > Number(position.stop)) {
            position.stop = dynamicTrailStop;
          }
          if (mark <= position.stop) {
            exit = mark;
            reason = 'PROFIT_TRAIL_REVERSED';
          }
        } else {
          const dynamicTrailStop = position.lowWater + trailDistance;
          if (dynamicTrailStop < Number(position.stop)) {
            position.stop = dynamicTrailStop;
          }
          if (mark >= position.stop) {
            exit = mark;
            reason = 'PROFIT_TRAIL_REVERSED';
          }
        }

        // ج) خروج با تایید چرخش و بازگشت روند (RSI Reversal + EMA Cross Reversal)
        if (!exit && signal) {
          if (isLong) {
            const rsiReversal = signal.rsi && signal.rsi > 68 && signal.movePct < -0.15;
            const emaBearCross = signal.emaFast && signal.emaSlow && (signal.emaFast < signal.emaSlow) && (signal.volX > 1.3);
            if (rsiReversal || emaBearCross) {
              exit = mark;
              reason = rsiReversal ? 'REVERSAL_RSI_OVERBOUGHT' : 'REVERSAL_EMA_CROSS';
            }
          } else {
            const rsiReversal = signal.rsi && signal.rsi < 32 && signal.movePct > 0.15;
            const emaBullCross = signal.emaFast && signal.emaSlow && (signal.emaFast > signal.emaSlow) && (signal.volX > 1.3);
            if (rsiReversal || emaBullCross) {
              exit = mark;
              reason = rsiReversal ? 'REVERSAL_RSI_OVERSOLD' : 'REVERSAL_EMA_CROSS';
            }
          }
        }
      }

      if (exit) this.close(position, exit, reason);
    }
  }
}
