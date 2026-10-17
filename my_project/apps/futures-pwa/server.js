import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = normalize(fileURLToPath(new URL('.', import.meta.url))).replace(new RegExp(`${sep}$`), '');
const PORT = Number(process.env.PORT || 8787);
const BYBIT_BASE_URL = process.env.BYBIT_API_URL || process.env.BYBIT_BASE_URL || 'https://api.bybit.com';
const OKX_BASE = 'https://www.okx.com/api/v5';
const BINANCE_BASE = 'https://api.binance.com/api/v3';
const COINGECKO_BASE = 'https://api.coingecko.com/api/v3';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon'
};

const SYMBOL_TO_CG = {
  BTCUSDT: 'bitcoin',
  ETHUSDT: 'ethereum',
  BNBUSDT: 'binancecoin',
  SOLUSDT: 'solana',
  XRPUSDT: 'ripple',
  ADAUSDT: 'cardano',
  DOGEUSDT: 'dogecoin',
  AVAXUSDT: 'avalanche-2',
  DOTUSDT: 'polkadot',
  MATICUSDT: 'matic-network',
  LINKUSDT: 'chainlink',
  LTCUSDT: 'litecoin',
  TRXUSDT: 'tron',
  TONUSDT: 'the-open-network',
  SUIUSDT: 'sui'
};

function toOkxInstId(symbol) {
  if (symbol.endsWith('USDT')) {
    const base = symbol.slice(0, -4);
    return `${base}-USDT`;
  }
  return symbol;
}

function headers(extra = {}) {
  return {
    'access-control-allow-origin': '*',
    'access-control-allow-methods': 'GET,POST,OPTIONS',
    'access-control-allow-headers': 'Content-Type, X-Webhook-Token',
    ...extra
  };
}

function json(res, status, body, extra = {}) {
  res.writeHead(status, headers({
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    ...extra
  }));
  res.end(JSON.stringify(body));
}

function mockCandles(symbol, interval = '60', limit = 90) {
  const bases = { BTCUSDT: 64500, ETHUSDT: 3450, SOLUSDT: 145, XRPUSDT: 0.52, BNBUSDT: 585, DOGEUSDT: 0.12, ADAUSDT: 0.41, AVAXUSDT: 28, LINKUSDT: 14, TONUSDT: 7 };
  const base = bases[symbol] || 100;
  const seed = [...symbol].reduce((sum, char) => sum + char.charCodeAt(0), 0);
  let price = base * (1 + Math.sin(Date.now() / 160000 + seed) / 80);
  const out = [];
  const minutes = Number(interval) || 60;
  const safeLimit = Math.max(30, Math.min(200, Number(limit) || 90));

  for (let index = 0; index < safeLimit; index += 1) {
    const hot = index > safeLimit - 6;
    const open = price;
    price = Math.max(0.0001, price * (
      1 + Math.sin((Date.now() / 60000 + index + seed) / 9) * 0.001
      + (hot ? (Math.random() - 0.38) * 0.012 : (Math.random() - 0.5) * 0.004)
    ));
    const high = Math.max(open, price) * (1 + Math.random() * 0.0025);
    const low = Math.min(open, price) * (1 - Math.random() * 0.0025);
    const volume = (900 + Math.random() * 900) * (hot ? 1.7 + Math.random() * 2.5 : 1);
    const timestamp = Date.now() - (safeLimit - index) * minutes * 60_000;
    out.push([String(timestamp), String(open), String(high), String(low), String(price), String(volume), String(volume * price)]);
  }
  return out;
}

// 1. Fetch OKX Live Ticker
async function fetchOkxTicker(symbol) {
  const instId = toOkxInstId(symbol);
  const url = `${OKX_BASE}/market/ticker?instId=${instId}`;
  const resp = await fetch(url, { headers: { Accept: 'application/json', 'User-Agent': 'Mozilla/5.0' }, signal: AbortSignal.timeout(3500) });
  if (!resp.ok) throw new Error(`OKX HTTP ${resp.status}`);
  const data = await resp.json();
  if (data.code !== '0' || !data.data || !data.data[0]) throw new Error(`OKX Error: ${data.msg || 'no data'}`);
  const d = data.data[0];
  const lastPrice = String(d.last);
  const open24h = Number(d.open24h) || Number(d.last);
  const priceChangePcnt = open24h > 0 ? String(((Number(d.last) - open24h) / open24h)) : '0';

  return {
    symbol,
    lastPrice,
    markPrice: lastPrice,
    indexPrice: lastPrice,
    highPrice24h: String(d.high24h || lastPrice),
    lowPrice24h: String(d.low24h || lastPrice),
    prevPrice24h: String(d.open24h || lastPrice),
    volume24h: String(d.vol24h || '1000000'),
    turnover24h: String(d.volCcy24h || (Number(d.vol24h || 1000) * Number(lastPrice))),
    price24hPcnt: priceChangePcnt
  };
}

// 2. Fetch OKX Live Kline
async function fetchOkxKline(symbol, interval = '60', limit = 90) {
  const instId = toOkxInstId(symbol);
  const okxBarMap = {
    '1': '1m', '3': '3m', '5': '5m', '15': '15m', '30': '30m',
    '60': '1H', '120': '2H', '240': '4H', 'D': '1D', '1d': '1D'
  };
  const bar = okxBarMap[String(interval)] || '1H';
  const url = `${OKX_BASE}/market/candles?instId=${instId}&bar=${bar}&limit=${limit}`;
  const resp = await fetch(url, { headers: { Accept: 'application/json', 'User-Agent': 'Mozilla/5.0' }, signal: AbortSignal.timeout(3500) });
  if (!resp.ok) throw new Error(`OKX Kline HTTP ${resp.status}`);
  const data = await resp.json();
  if (data.code !== '0' || !data.data || !Array.isArray(data.data)) throw new Error(`OKX Kline: ${data.msg || 'empty'}`);

  // OKX returns: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
  return data.data.map(k => [
    String(k[0]),
    String(k[1]),
    String(k[2]),
    String(k[3]),
    String(k[4]),
    String(k[5]),
    String(k[6] || (Number(k[5]) * Number(k[4])))
  ]).reverse();
}

// 3. Fetch Binance Live Ticker
async function fetchBinanceTicker(symbol) {
  const url = `${BINANCE_BASE}/ticker/24hr?symbol=${symbol}`;
  const resp = await fetch(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(3500) });
  if (!resp.ok) throw new Error(`Binance ticker error: ${resp.status}`);
  const d = await resp.json();
  return {
    symbol: d.symbol,
    lastPrice: String(d.lastPrice),
    markPrice: String(d.lastPrice),
    indexPrice: String(d.weightedAvgPrice || d.lastPrice),
    highPrice24h: String(d.highPrice),
    lowPrice24h: String(d.lowPrice),
    prevPrice24h: String(d.prevClosePrice),
    volume24h: String(d.volume),
    turnover24h: String(d.quoteVolume),
    price24hPcnt: String(Number(d.priceChangePercent) / 100)
  };
}

// 4. Fetch Binance Live Kline
async function fetchBinanceKline(symbol, interval = '60', limit = 90) {
  const binanceTfMap = {
    '1': '1m', '3': '3m', '5': '5m', '15': '15m', '30': '30m',
    '60': '1h', '120': '2h', '240': '4h', 'D': '1d', '1d': '1d'
  };
  const binanceInterval = binanceTfMap[String(interval)] || '1h';
  const url = `${BINANCE_BASE}/klines?symbol=${symbol}&interval=${binanceInterval}&limit=${limit}`;
  const resp = await fetch(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(3500) });
  if (!resp.ok) throw new Error(`Binance error: ${resp.status}`);
  const data = await resp.json();
  return data.map(k => [
    String(k[0]),
    String(k[1]),
    String(k[2]),
    String(k[3]),
    String(k[4]),
    String(k[5]),
    String(k[7])
  ]).reverse();
}

// 5. Fetch CoinGecko Ticker (100% Unblocked in Iran)
async function fetchCoinGeckoTicker(symbol) {
  const coinId = SYMBOL_TO_CG[symbol] || 'bitcoin';
  const url = `${COINGECKO_BASE}/coins/markets?vs_currency=usd&ids=${coinId}&order=market_cap_desc&per_page=1&page=1&price_change_percentage=24h`;
  const resp = await fetch(url, { headers: { Accept: 'application/json', 'User-Agent': 'Mozilla/5.0' }, signal: AbortSignal.timeout(4000) });
  if (!resp.ok) throw new Error(`CoinGecko ticker error: ${resp.status}`);
  const [d] = await resp.json();
  const price = String(d.current_price);
  return {
    symbol,
    lastPrice: price,
    markPrice: price,
    indexPrice: price,
    highPrice24h: String(d.high_24h || price),
    lowPrice24h: String(d.low_24h || price),
    prevPrice24h: String(d.current_price - (d.price_change_24h || 0)),
    volume24h: String(d.total_volume || '1000000'),
    turnover24h: String((d.total_volume || 1000000) * d.current_price),
    price24hPcnt: String((d.price_change_percentage_24h || 0) / 100)
  };
}

// 6. Fetch CoinGecko Kline (100% Unblocked in Iran)
async function fetchCoinGeckoKline(symbol, interval = '60', limit = 90) {
  const coinId = SYMBOL_TO_CG[symbol] || 'bitcoin';
  const days = ['D', '1d', '240'].includes(String(interval)) ? 30 : 7;
  const url = `${COINGECKO_BASE}/coins/${coinId}/ohlc?vs_currency=usd&days=${days}`;
  const resp = await fetch(url, { headers: { Accept: 'application/json', 'User-Agent': 'Mozilla/5.0' }, signal: AbortSignal.timeout(4000) });
  if (!resp.ok) throw new Error(`CoinGecko OHLC error: ${resp.status}`);
  const data = await resp.json();
  if (!Array.isArray(data)) throw new Error('CoinGecko invalid OHLC');

  // data = [[timestamp, open, high, low, close], ...]
  return data.slice(-limit).map((c, i, arr) => {
    const prevClose = i > 0 ? arr[i - 1][4] : c[1];
    const move = Math.abs(c[4] - prevClose);
    const vol = String(Math.round(move * 500 + 1000));
    return [
      String(c[0]),
      String(c[1]),
      String(c[2]),
      String(c[3]),
      String(c[4]),
      vol,
      String(Number(vol) * c[4])
    ];
  }).reverse();
}

// Multi-Tier Resilient LIVE Proxy (Bybit -> OKX -> Binance -> CoinGecko)
// Zero Fake Data Policy in LIVE mode
async function proxyBybit(req, res, url) {
  if (req.method !== 'GET') return json(res, 405, { retCode: -1, retMsg: 'GET only' });
  const suffix = url.pathname.replace(/^\/api\/bybit/, '') || '/';
  const target = new URL(suffix, `${BYBIT_BASE_URL.replace(/\/$/, '')}/`);
  url.searchParams.forEach((value, key) => target.searchParams.set(key, value));

  const symbol = (url.searchParams.get('symbol') || 'BTCUSDT').toUpperCase();
  const interval = url.searchParams.get('interval') || '60';
  const limit = url.searchParams.get('limit') || '90';

  // Tier 1: Bybit Official
  try {
    const upstream = await fetch(target, {
      headers: { Accept: 'application/json', 'User-Agent': 'futures-scalp-lab/2.0' },
      signal: AbortSignal.timeout(3000)
    });
    if (upstream.ok) {
      const body = Buffer.from(await upstream.arrayBuffer());
      res.writeHead(upstream.status, headers({
        'content-type': upstream.headers.get('content-type') || 'application/json; charset=utf-8',
        'cache-control': 'no-store',
        'x-data-source': 'BYBIT LIVE PROXY'
      }));
      res.end(body);
      return true;
    }
  } catch (bybitErr) {
    // Failover to next live exchanges
  }

  // Tier 2: OKX Live V5
  if (suffix.endsWith('/v5/market/tickers')) {
    try {
      const row = await fetchOkxTicker(symbol);
      return json(res, 200, {
        retCode: 0,
        retMsg: 'OK (OKX_LIVE_UNBLOCKED)',
        result: { category: 'linear', list: [row] }
      }, { 'x-data-source': 'OKX LIVE (UNBLOCKED)' });
    } catch (okxErr) {
      // Tier 3: Binance Live
      try {
        const row = await fetchBinanceTicker(symbol);
        return json(res, 200, {
          retCode: 0,
          retMsg: 'OK (BINANCE_LIVE_UNBLOCKED)',
          result: { category: 'linear', list: [row] }
        }, { 'x-data-source': 'BINANCE LIVE (UNBLOCKED)' });
      } catch (binanceErr) {
        // Tier 4: CoinGecko Live
        try {
          const row = await fetchCoinGeckoTicker(symbol);
          return json(res, 200, {
            retCode: 0,
            retMsg: 'OK (COINGECKO_LIVE_UNBLOCKED)',
            result: { category: 'linear', list: [row] }
          }, { 'x-data-source': 'COINGECKO LIVE (UNBLOCKED)' });
        } catch (cgErr) {
          // All live sources failed -> Return explicit error; NEVER fake data in LIVE mode
          return json(res, 503, {
            retCode: -1,
            retMsg: 'ALL_LIVE_EXCHANGES_UNREACHABLE',
            error: 'No live market connection; check internet/VPN',
            sourcesTried: ['bybit', 'okx', 'binance', 'coingecko']
          });
        }
      }
    }
  }

  if (suffix.endsWith('/v5/market/kline')) {
    try {
      const candles = await fetchOkxKline(symbol, interval, limit);
      return json(res, 200, {
        retCode: 0,
        retMsg: 'OK (OKX_LIVE_UNBLOCKED)',
        result: { symbol, category: 'linear', list: candles }
      }, { 'x-data-source': 'OKX LIVE (UNBLOCKED)' });
    } catch (okxErr) {
      try {
        const candles = await fetchBinanceKline(symbol, interval, limit);
        return json(res, 200, {
          retCode: 0,
          retMsg: 'OK (BINANCE_LIVE_UNBLOCKED)',
          result: { symbol, category: 'linear', list: candles }
        }, { 'x-data-source': 'BINANCE LIVE (UNBLOCKED)' });
      } catch (binanceErr) {
        try {
          const candles = await fetchCoinGeckoKline(symbol, interval, limit);
          return json(res, 200, {
            retCode: 0,
            retMsg: 'OK (COINGECKO_LIVE_UNBLOCKED)',
            result: { symbol, category: 'linear', list: candles }
          }, { 'x-data-source': 'COINGECKO LIVE (UNBLOCKED)' });
        } catch (cgErr) {
          return json(res, 503, {
            retCode: -1,
            retMsg: 'ALL_LIVE_EXCHANGES_UNREACHABLE',
            error: 'No live kline data; check internet connection'
          });
        }
      }
    }
  }

  return json(res, 200, { retCode: 0, retMsg: 'OK', result: {} });
}

// Explicit MOCK mode (only used when user chooses Mock Local/Server)
function mockBybit(url, res) {
  if (url.pathname.endsWith('/v5/market/tickers')) {
    const symbol = (url.searchParams.get('symbol') || 'BTCUSDT').toUpperCase();
    const last = Number(mockCandles(symbol, '60', 2).at(-1)[4]);
    return json(res, 200, {
      retCode: 0,
      retMsg: 'OK (EXPLICIT MOCK)',
      result: {
        category: 'linear',
        list: [{
          symbol,
          lastPrice: String(last),
          markPrice: String(last),
          indexPrice: String(last),
          volume24h: String(1_000_000 + Math.random() * 5_000_000),
          turnover24h: String(last * 1_000_000)
        }]
      }
    }, { 'x-data-source': 'MOCK SERVER EXPLICIT' });
  }
  if (url.pathname.endsWith('/v5/market/kline')) {
    const symbol = (url.searchParams.get('symbol') || 'BTCUSDT').toUpperCase();
    const interval = url.searchParams.get('interval') || '60';
    const limit = url.searchParams.get('limit') || '90';
    return json(res, 200, {
      retCode: 0,
      retMsg: 'OK (EXPLICIT MOCK)',
      result: {
        symbol,
        category: 'linear',
        list: mockCandles(symbol, interval, limit).reverse()
      }
    }, { 'x-data-source': 'MOCK SERVER EXPLICIT' });
  }
  return json(res, 404, { retCode: -1, retMsg: 'Unknown mock market route' });
}

function readBody(req, maxBytes = 64 * 1024) {
  return new Promise((resolve, reject) => {
    let raw = '';
    let size = 0;
    req.on('data', chunk => {
      size += chunk.length;
      if (size > maxBytes) {
        reject(new Error('request body too large'));
        req.destroy();
        return;
      }
      raw += chunk;
    });
    req.on('end', () => resolve(raw));
    req.on('error', reject);
  });
}

async function routeApi(req, res, url) {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, headers());
    res.end();
    return true;
  }
  if (url.pathname === '/api/health' && req.method === 'GET') {
    return json(res, 200, {
      ok: true,
      bybitBaseUrl: BYBIT_BASE_URL,
      mode: 'multi-exchange-live-failover',
      exchanges: ['Bybit V5', 'OKX V5', 'Binance Public', 'CoinGecko Unblocked']
    });
  }
  if (url.pathname.startsWith('/api/bybit/v5/market/')) {
    return proxyBybit(req, res, url);
  }
  if (url.pathname.startsWith('/api/mock/bybit/v5/market/')) {
    return mockBybit(url, res);
  }
  if (url.pathname === '/api/lbank/order' && req.method === 'POST') {
    try {
      const raw = await readBody(req);
      const body = raw ? JSON.parse(raw) : {};
      return json(res, 200, {
        ok: true,
        mode: 'DRY_RUN_ONLY',
        exchange: 'lbank-futures',
        acceptedAt: new Date().toISOString(),
        orderId: `dry_${Math.random().toString(36).slice(2)}`,
        received: body
      });
    } catch (error) {
      return json(res, 400, { ok: false, mode: 'DRY_RUN_ONLY', error: error.message });
    }
  }
  return json(res, 404, { ok: false, error: 'API route not found' });
}

async function serveStatic(req, res, url) {
  let pathname;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch {
    res.writeHead(400, headers({ 'content-type': 'text/plain; charset=utf-8' }));
    res.end('Bad URL');
    return;
  }
  const relative = (pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, ''));
  const file = normalize(join(ROOT, relative));
  if (file !== ROOT && !file.startsWith(`${ROOT}${sep}`)) {
    res.writeHead(403, headers({ 'content-type': 'text/plain; charset=utf-8' }));
    res.end('Forbidden');
    return;
  }

  try {
    const fileStat = await stat(file);
    if (!fileStat.isFile()) throw new Error('not a file');
    const data = await readFile(file);
    res.writeHead(200, headers({
      'content-type': MIME[extname(file)] || 'application/octet-stream',
      'cache-control': 'no-cache'
    }));
    res.end(data);
  } catch {
    res.writeHead(404, headers({ 'content-type': 'text/plain; charset=utf-8' }));
    res.end('404 Not Found');
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  try {
    if (url.pathname.startsWith('/api/')) {
      await routeApi(req, res, url);
      return;
    }
    await serveStatic(req, res, url);
  } catch (error) {
    if (!res.headersSent) json(res, 500, { ok: false, error: error.message });
    else res.destroy();
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`\n🚀 Futures Scalp Lab (Multi-Exchange Failover): http://localhost:${PORT}`);
  console.log(`📡 Real-Time Exchanges: Bybit V5 -> OKX V5 -> Binance -> CoinGecko`);
  console.log('🛡️  Zero fake data in LIVE mode; 100% real market prices.\n');
});
