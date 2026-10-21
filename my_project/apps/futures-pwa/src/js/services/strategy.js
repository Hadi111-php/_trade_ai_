import { clamp, mean } from '../core/utils.js';

export class MomentumScalpStrategy {
  constructor(settings) {
    this.s = settings;
  }

  // --- Technical Indicator Calculations ---

  atr(candles, length = 14) {
    if (candles.length < 2) return 0;
    const ranges = [];
    for (let i = 1; i < candles.length; i += 1) {
      const current = candles[i];
      const previous = candles[i - 1];
      ranges.push(Math.max(
        current.high - current.low,
        Math.abs(current.high - previous.close),
        Math.abs(current.low - previous.close)
      ));
    }
    return mean(ranges.slice(-length)) || 0;
  }

  rsi(candles, period = 14) {
    if (candles.length <= period) return 50;
    let gains = 0, losses = 0;
    for (let i = 1; i <= period; i++) {
      const diff = candles[i].close - candles[i - 1].close;
      if (diff >= 0) gains += diff;
      else losses -= diff;
    }
    let avgGain = gains / period;
    let avgLoss = losses / period;
    for (let i = period + 1; i < candles.length; i++) {
      const diff = candles[i].close - candles[i - 1].close;
      if (diff >= 0) {
        avgGain = (avgGain * (period - 1) + diff) / period;
        avgLoss = (avgLoss * (period - 1)) / period;
      } else {
        avgGain = (avgGain * (period - 1)) / period;
        avgLoss = (avgLoss * (period - 1) - diff) / period;
      }
    }
    if (avgLoss === 0) return 100;
    const rs = avgGain / avgLoss;
    return 100 - (100 / (1 + rs));
  }

  ema(candles, period = 20) {
    if (!candles || candles.length === 0) return 0;
    if (candles.length < period) return candles.at(-1)?.close || 0;
    const k = 2 / (period + 1);
    let emaVal = candles.slice(0, period).reduce((sum, c) => sum + c.close, 0) / period;
    for (let i = period; i < candles.length; i++) {
      emaVal = candles[i].close * k + emaVal * (1 - k);
    }
    return emaVal;
  }

  bollingerBands(candles, period = 20, multiplier = 2.0) {
    if (candles.length < period) {
      const lastClose = candles.at(-1)?.close || 0;
      return { middle: lastClose, upper: lastClose, lower: lastClose, bandwidth: 0, percentB: 0.5 };
    }
    const slice = candles.slice(-period);
    const middle = mean(slice.map(c => c.close));
    const variance = mean(slice.map(c => Math.pow(c.close - middle, 2)));
    const stdDev = Math.sqrt(variance);
    const upper = middle + (multiplier * stdDev);
    const lower = middle - (multiplier * stdDev);
    const bandwidth = middle > 0 ? (upper - lower) / middle : 0;
    const lastClose = candles.at(-1).close;
    const percentB = (upper - lower) > 0 ? (lastClose - lower) / (upper - lower) : 0.5;
    return { middle, upper, lower, bandwidth, percentB, stdDev };
  }

  macd(candles, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) {
    if (candles.length < slowPeriod) {
      return { macdLine: 0, signalLine: 0, histogram: 0 };
    }
    const kFast = 2 / (fastPeriod + 1);
    const kSlow = 2 / (slowPeriod + 1);
    const kSignal = 2 / (signalPeriod + 1);

    let emaFastVal = candles.slice(0, fastPeriod).reduce((s, c) => s + c.close, 0) / fastPeriod;
    let emaSlowVal = candles.slice(0, slowPeriod).reduce((s, c) => s + c.close, 0) / slowPeriod;

    const macdSeries = [];
    for (let i = slowPeriod; i < candles.length; i++) {
      emaFastVal = candles[i].close * kFast + emaFastVal * (1 - kFast);
      emaSlowVal = candles[i].close * kSlow + emaSlowVal * (1 - kSlow);
      macdSeries.push(emaFastVal - emaSlowVal);
    }

    if (macdSeries.length < signalPeriod) {
      const lastMacd = macdSeries.at(-1) || 0;
      return { macdLine: lastMacd, signalLine: lastMacd, histogram: 0 };
    }

    let signalVal = macdSeries.slice(0, signalPeriod).reduce((s, v) => s + v, 0) / signalPeriod;
    for (let i = signalPeriod; i < macdSeries.length; i++) {
      signalVal = macdSeries[i] * kSignal + signalVal * (1 - kSignal);
    }

    const currentMacd = macdSeries.at(-1);
    const histogram = currentMacd - signalVal;
    const prevMacd = macdSeries.at(-2) || currentMacd;
    const prevSignal = macdSeries.length >= 2 ? macdSeries.slice(0, -1).reduce((s, v) => s + v, 0) / (macdSeries.length - 1) : signalVal;
    const prevHistogram = prevMacd - prevSignal;

    return { macdLine: currentMacd, signalLine: signalVal, histogram, prevHistogram };
  }

  donchianChannels(candles, period = 20) {
    if (candles.length < period) {
      const lastClose = candles.at(-1)?.close || 0;
      return { high: lastClose, low: lastClose, middle: lastClose };
    }
    const slice = candles.slice(-period, -1);
    const highs = slice.map(c => c.high);
    const lows = slice.map(c => c.low);
    const high = Math.max(...highs);
    const low = Math.min(...lows);
    const middle = (high + low) / 2;
    return { high, low, middle };
  }

  fee(notional, percentage) {
    return Math.abs(notional) * (Number(percentage) / 100);
  }

  // --- Pump & Dump Detection Engine ---

  detectPumpAndDump(ctx) {
    const { price, movePct, oneCandlePct, volX, rsi, atrPct, candles, last, previous } = ctx;
    const s = this.s.value;

    const pumpVolThresh = Number(s.pumpVolumeMultiplier || 2.5);
    const pumpSurgeThresh = Number(s.pumpSurgePct || 0.8);

    let side = 'WAIT';
    let score = 0;
    const reasons = [];

    if (volX >= pumpVolThresh && (oneCandlePct >= pumpSurgeThresh || movePct >= pumpSurgeThresh * 1.5)) {
      if (rsi > 75) {
        side = 'SHORT';
        score = clamp(80 + Math.round((volX - pumpVolThresh) * 5) + Math.round(rsi - 75), 0, 100);
        reasons.push(`پامپ شدید و اشباع خرید RSI (${rsi.toFixed(0)}) - احتمال ریزش/دامپ (Short)`);
      } else {
        side = 'LONG';
        score = clamp(75 + Math.round(oneCandlePct * 10) + Math.round((volX - pumpVolThresh) * 5), 0, 100);
        reasons.push(`پامپ صعودی با حجم اسپایک ${volX.toFixed(2)}x و رشد ${oneCandlePct.toFixed(2)}% (Long)`);
      }
    } else if (volX >= pumpVolThresh && (oneCandlePct <= -pumpSurgeThresh || movePct <= -pumpSurgeThresh * 1.5)) {
      if (rsi < 25) {
        side = 'LONG';
        score = clamp(80 + Math.round((volX - pumpVolThresh) * 5) + Math.round(25 - rsi), 0, 100);
        reasons.push(`دامپ شدید و کف اساسی RSI (${rsi.toFixed(0)}) - احتمال بازگشت (Long)`);
      } else {
        side = 'SHORT';
        score = clamp(75 + Math.round(Math.abs(oneCandlePct) * 10) + Math.round((volX - pumpVolThresh) * 5), 0, 100);
        reasons.push(`دامپ نزولی با حجم اسپایک ${volX.toFixed(2)}x و ریزش ${Math.abs(oneCandlePct).toFixed(2)}% (Short)`);
      }
    }

    return { side, score, why: reasons.join(' ، ') || 'پامپ و دامپی شناسایی نشد' };
  }

  // --- Main Analysis Engine ---

  analyze(market) {
    const s = this.s.value;
    const candles = market.candles || [];
    if (!candles || candles.length < 20) {
      return { symbol: market.symbol, side: 'WAIT', score: 0, why: 'داده‌های کندل کافی نیست' };
    }

    const last = candles.at(-1);
    const previous = candles.at(-2);
    const fourBack = candles.at(-4) || previous;
    const price = Number(market.price || last.close);

    const movePct = ((last.close - fourBack.close) / fourBack.close) * 100;
    const oneCandlePct = ((last.close - previous.close) / previous.close) * 100;
    const averageVolume = mean(candles.slice(-28, -1).map(candle => candle.volume));
    const volumeX = last.volume / (averageVolume || last.volume || 1);
    const atr = this.atr(candles);
    const atrPct = (atr / price) * 100;
    const rsiVal = this.rsi(candles, 14);
    const emaFast = this.ema(candles, 9);
    const emaSlow = this.ema(candles, 21);
    const bb = this.bollingerBands(candles, 20, 2.0);
    const macdRes = this.macd(candles, 12, 26, 9);
    const donchian = this.donchianChannels(candles, 20);

    const breakoutUp = last.close > donchian.high;
    const breakoutDown = last.close < donchian.low;
    const bodyPct = Math.abs(last.close - last.open) / last.open * 100;

    const recent = candles.slice(-8);
    const trendUp = recent.filter((candle, index, array) => index > 0 && candle.close > array[index - 1].close).length >= 5;
    const trendDown = recent.filter((candle, index, array) => index > 0 && candle.close < array[index - 1].close).length >= 5;

    const ctx = {
      price,
      movePct,
      oneCandlePct,
      volX: volumeX,
      atr,
      atrPct,
      rsi: rsiVal,
      emaFast,
      emaSlow,
      bb,
      macd: macdRes,
      donchian,
      breakoutUp,
      breakoutDown,
      trendUp,
      trendDown,
      candles,
      last,
      previous,
      symbol: market.symbol
    };

    let side = 'WAIT';
    let score = 0;
    let why = '';

    const algoMode = s.algoMode || 'consensus';

    if (algoMode === 'pump_dump') {
      const pd = this.detectPumpAndDump(ctx);
      side = pd.side;
      score = pd.score;
      why = `[پامپ و دامپ]: ${pd.why}`;
    } else if (algoMode === 'ema_cross') {
      if (emaFast > emaSlow && previous.close <= emaSlow) {
        side = 'LONG'; score = 85; why = '[EMA Cross]: تقاطع صعودی EMA9 از روی EMA21';
      } else if (emaFast < emaSlow && previous.close >= emaSlow) {
        side = 'SHORT'; score = 85; why = '[EMA Cross]: تقاطع نزولی EMA9 به زیر EMA21';
      }
    } else if (algoMode === 'rsi_reversion') {
      if (rsiVal < 30) {
        side = 'LONG'; score = 82; why = `[RSI Reversion]: اشباع فروش RSI (${rsiVal.toFixed(0)})`;
      } else if (rsiVal > 70) {
        side = 'SHORT'; score = 82; why = `[RSI Reversion]: اشباع خرید RSI (${rsiVal.toFixed(0)})`;
      }
    } else if (algoMode === 'donchian_breakout') {
      if (breakoutUp && volumeX > 1.2) {
        side = 'LONG'; score = 88; why = `[Donchian Breakout]: شکست سقف ۲۰ کندله با حجم ${volumeX.toFixed(2)}x`;
      } else if (breakoutDown && volumeX > 1.2) {
        side = 'SHORT'; score = 88; why = `[Donchian Breakout]: شکست کف ۲۰ کندله با حجم ${volumeX.toFixed(2)}x`;
      }
    } else if (algoMode === 'bb_squeeze') {
      if (bb.percentB > 0.95 && bb.bandwidth > 0.02) {
        side = 'LONG'; score = 80; why = '[Bollinger Squeeze]: خروج صعودی از باند بولینگر';
      } else if (bb.percentB < 0.05 && bb.bandwidth > 0.02) {
        side = 'SHORT'; score = 80; why = '[Bollinger Squeeze]: خروج نزولی از باند بولینگر';
      }
    } else if (algoMode === 'macd_flip') {
      if (macdRes.histogram > 0 && macdRes.prevHistogram <= 0) {
        side = 'LONG'; score = 84; why = '[MACD Flip]: تغییر هیستوگرام MACD به مثبت';
      } else if (macdRes.histogram < 0 && macdRes.prevHistogram >= 0) {
        side = 'SHORT'; score = 84; why = '[MACD Flip]: تغییر هیستوگرام MACD به منفی';
      }
    }

    if (side === 'WAIT' && algoMode === 'consensus') {
      let longScore = 0;
      let shortScore = 0;
      const reasons = [];
      const minimumMove = Number(s.minMovePct);

      const pd = this.detectPumpAndDump(ctx);
      if (pd.side === 'LONG') { longScore += 30; reasons.push(pd.why); }
      if (pd.side === 'SHORT') { shortScore += 30; reasons.push(pd.why); }

      if (movePct >= minimumMove) { longScore += 20; reasons.push(`حرکت +${movePct.toFixed(2)}%`); }
      if (movePct <= -minimumMove) { shortScore += 20; reasons.push(`ریزش ${movePct.toFixed(2)}%`); }
      if (oneCandlePct >= minimumMove / 1.5) longScore += 10;
      if (oneCandlePct <= -minimumMove / 1.5) shortScore += 10;

      if (volumeX >= Number(s.volumeSpikeX)) {
        longScore += 20;
        shortScore += 20;
        reasons.push(`حجم ${volumeX.toFixed(2)}x`);
      }

      if (breakoutUp) { longScore += 20; reasons.push('Breakout سقف'); }
      if (breakoutDown) { shortScore += 20; reasons.push('Breakout کف'); }

      if (trendUp) longScore += 10;
      if (trendDown) shortScore += 10;

      if (rsiVal < 35) { longScore += 15; reasons.push(`RSI کف (${rsiVal.toFixed(0)})`); }
      else if (rsiVal > 65) { shortScore += 15; reasons.push(`RSI سقف (${rsiVal.toFixed(0)})`); }

      if (emaFast > emaSlow) longScore += 8;
      else if (emaFast < emaSlow) shortScore += 8;
      if (macdRes.histogram > 0) longScore += 10;
      else if (macdRes.histogram < 0) shortScore += 10;

      if (bodyPct > atrPct * 0.35) {
        if (last.close > last.open) longScore += 8;
        if (last.close < last.open) shortScore += 8;
      }

      if (atrPct < 0.03) {
        longScore -= 20;
        shortScore -= 20;
        reasons.push('ATR کم');
      }

      const rawScore = Math.max(longScore, shortScore);
      score = clamp(Math.round(rawScore), 0, 100);
      side = score >= Number(s.minScore)
        ? (longScore >= shortScore ? 'LONG' : 'SHORT')
        : 'WAIT';
      why = reasons.join(' ، ') || 'تأیید کافی برای ورود ندارد';
    }

    const direction = side === 'LONG' ? 1 : side === 'SHORT' ? -1 : 0;
    const stopDistance = Math.max(atr * Number(s.atrStopMult), price * 0.0015);
    const entry = price * (1 + direction * (Number(s.slippagePct) / 100));
    const stop = direction ? entry - direction * stopDistance : null;
    const take = direction ? entry + direction * stopDistance * Number(s.takeProfitR) : null;
    const notional = Number(s.orderMargin) * Number(s.leverage);
    const qty = notional / (entry || price);
    const feeOpen = this.fee(notional, s.feeOpenPct);
    const feeClose = this.fee(notional, s.feeClosePct);
    const roundTripFee = feeOpen + feeClose;
    const risk = stopDistance * qty + roundTripFee;
    const reward = stopDistance * Number(s.takeProfitR) * qty - roundTripFee;
    const candleTs = Number(last.ts || Date.now());

    return {
      symbol: market.symbol,
      source: market.source,
      price,
      side,
      score,
      movePct,
      oneCandlePct,
      volX: volumeX,
      atr,
      atrPct,
      rsi: rsiVal,
      emaFast,
      emaSlow,
      why,
      entry,
      stop,
      take,
      qty,
      notional,
      feeOpen,
      feeClose,
      fee: roundTripFee,
      risk,
      reward,
      candleTs,
      signalId: `${market.symbol}:${candleTs}:${side}`,
      ts: Date.now()
    };
  }
}
