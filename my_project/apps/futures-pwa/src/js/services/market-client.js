import { mean, timeframeMs } from '../core/utils.js';

// These bases are used only when the user explicitly selects Mock Local in Settings.
const MOCK_BASES = Object.freeze({
  BTCUSDT: 65000,
  ETHUSDT: 3400,
  SOLUSDT: 145,
  XRPUSDT: 0.52,
  BNBUSDT: 585,
  DOGEUSDT: 0.12,
  ADAUSDT: 0.41,
  AVAXUSDT: 28,
  LINKUSDT: 14,
  TONUSDT: 7
});

export class MarketClient {
  constructor(settings, logger) {
    this.s = settings;
    this.log = logger;
  }

  buildUrl(base, path) {
    const cleanBase = String(base || '').replace(/\/$/, '');
    const cleanPath = String(path || '').startsWith('/') ? String(path) : `/${path}`;
    if (!cleanBase) throw new Error('Market data base URL خالی است');
    return `${cleanBase}${cleanPath}`;
  }

  interpolate(path, symbol) {
    const s = this.s.value;
    return String(path)
      .replaceAll('{symbol}', encodeURIComponent(symbol))
      .replaceAll('{timeframe}', encodeURIComponent(s.timeframe))
      .replaceAll('{category}', encodeURIComponent(s.bybitCategory || 'linear'));
  }

  async fetchJson(url) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 9000);
    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: { Accept: 'application/json' },
        cache: 'no-store'
      });
      const text = await response.text();
      let body;
      try {
        body = text ? JSON.parse(text) : {};
      } catch {
        body = { retMsg: text.slice(0, 180) };
      }
      if (!response.ok) {
        const message = body?.retMsg || body?.error || response.statusText || 'HTTP error';
        throw new Error(`${response.status}: ${message}`);
      }
      if (body && body.retCode !== undefined && Number(body.retCode) !== 0) {
        throw new Error(`Bybit ${body.retCode}: ${body.retMsg || 'API error'}`);
      }
      return body;
    } finally {
      clearTimeout(timeout);
    }
  }

  isOfficialLiveBase(base) {
    const value = String(base || '').trim();
    if (value === '/api/bybit' || value.startsWith('/api/bybit/')) return true;
    try {
      const host = new URL(value).hostname.toLowerCase();
      return [
        'api.bybit.com',
        'api.bytick.com',
        'api.bybit.eu',
        'api.bybit.kz',
        'api.bybit-tr.com',
        'api.bybit.id',
        'api.bybit.nl',
        'api.bybit.ae',
        'api.byhkbit.com',
        'api.bybitgeorgia.ge',
        'api.manepa.jp'
      ].includes(host);
    } catch {
      return false;
    }
  }

  async get(symbol) {
    const s = this.s.value;
    if (s.dataMode === 'mock-local') return this.mock(symbol);

    const mode = s.dataMode === 'mock-server' ? 'mock-server' : 'live';
    const base = mode === 'mock-server' ? s.mockBaseUrl : s.dataBaseUrl;
    if (mode === 'live' && !this.isOfficialLiveBase(base)) {
      throw new Error('Live mode فقط Base URL رسمی Bybit یا /api/bybit را قبول می‌کند');
    }
    let tickerUrl = this.buildUrl(base, this.interpolate(s.tickerPath, symbol));
    let klineUrl = this.buildUrl(base, this.interpolate(s.klinePath, symbol));

    let ticker, kline;
    try {
      [ticker, kline] = await Promise.all([
        this.fetchJson(tickerUrl),
        this.fetchJson(klineUrl)
      ]);
    } catch (err) {
      // If proxy via /api/bybit failed (e.g. PC lacks VPN), try direct https://api.bybit.com using browser's VPN!
      if (base === '/api/bybit') {
        const directBase = 'https://api.bybit.com';
        tickerUrl = this.buildUrl(directBase, this.interpolate(s.tickerPath, symbol));
        klineUrl = this.buildUrl(directBase, this.interpolate(s.klinePath, symbol));
        [ticker, kline] = await Promise.all([
          this.fetchJson(tickerUrl),
          this.fetchJson(klineUrl)
        ]);
      } else {
        throw err;
      }
    }

    const tickerRow = ticker?.result?.list?.[0];
    const price = Number(tickerRow?.lastPrice || tickerRow?.markPrice || 0);
    let candles = (kline?.result?.list || []).map(row => ({
      ts: Number(row[0]),
      open: Number(row[1]),
      high: Number(row[2]),
      low: Number(row[3]),
      close: Number(row[4]),
      volume: Number(row[5])
    })).filter(c => [c.ts, c.open, c.high, c.low, c.close, c.volume].every(Number.isFinite)).reverse();

    // Bybit returns the currently forming candle. For validation, do not score a
    // candle that can still repaint unless the developer explicitly opts out.
    const interval = timeframeMs(s.timeframe);
    const last = candles.at(-1);
    const currentCandleIsOpen = !!last && last.ts + interval > Date.now();
    if (s.useClosedCandle === 'true' && currentCandleIsOpen && candles.length > 30) candles = candles.slice(0, -1);

    if (!price || candles.length < 30) throw new Error(`داده ناقص Bybit برای ${symbol}`);
    const lastCandle = candles.at(-1);
    const source = mode === 'live' ? 'BYBIT LIVE' : 'MOCK SERVER (EXPLICIT)';

    return {
      symbol,
      price,
      candles,
      source,
      exchangeTime: Number(ticker?.time || kline?.time || 0),
      receivedAt: Date.now(),
      lastCandle,
      currentCandleIsOpen,
      requestInfo: { tickerUrl, klineUrl },
      tickerRaw: {
        symbol: tickerRow?.symbol || symbol,
        lastPrice: tickerRow?.lastPrice || null,
        markPrice: tickerRow?.markPrice || null,
        indexPrice: tickerRow?.indexPrice || null,
        volume24h: tickerRow?.volume24h || null,
        turnover24h: tickerRow?.turnover24h || null
      }
    };
  }

  mock(symbol) {
    const base = MOCK_BASES[symbol] || 100;
    const seed = [...symbol].reduce((sum, char) => sum + char.charCodeAt(0), 0);
    let price = base * (1 + Math.sin(Date.now() / 160000 + seed) / 80);
    const candles = [];

    for (let i = 0; i < 90; i += 1) {
      const hot = i > 84;
      const open = price;
      price = Math.max(
        0.0001,
        price * (1 + Math.sin((Date.now() / 60000 + i + seed) / 9) * 0.001
          + (hot ? (Math.random() - 0.38) * 0.012 : (Math.random() - 0.5) * 0.004))
      );
      const high = Math.max(open, price) * (1 + Math.random() * 0.0025);
      const low = Math.min(open, price) * (1 - Math.random() * 0.0025);
      const volume = (900 + Math.random() * 900) * (hot ? 1.7 + Math.random() * 2.5 : 1);
      candles.push({
        ts: Date.now() - (90 - i) * 60_000,
        open,
        high,
        low,
        close: price,
        volume
      });
    }

    return {
      symbol,
      price,
      candles,
      source: 'MOCK LOCAL (EXPLICIT)',
      exchangeTime: 0,
      receivedAt: Date.now(),
      lastCandle: candles.at(-1),
      currentCandleIsOpen: false,
      requestInfo: { tickerUrl: 'mock-local', klineUrl: 'mock-local' },
      tickerRaw: { symbol, lastPrice: String(price), markPrice: String(price), indexPrice: null, volume24h: null, turnover24h: null },
      avgVol: mean(candles.map(c => c.volume))
    };
  }
}
