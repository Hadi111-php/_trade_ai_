export const DEFAULT_SETTINGS = Object.freeze({
  // LIVE is intentional: the app never silently falls back to synthetic candles.
  dataMode: 'live',
  dataBaseUrl: '/api/bybit',
  mockBaseUrl: '/api/mock/bybit',
  bybitCategory: 'linear',
  tickerPath: '/v5/market/tickers?category={category}&symbol={symbol}',
  klinePath: '/v5/market/kline?category={category}&symbol={symbol}&interval={timeframe}&limit=200',
  useClosedCandle: 'true',
  realWebhookUrl: '/api/lbank/order',
  realVenue: 'lbank-futures',
  symbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT'],
  symbolMap: {},
  timeframe: '60', // پیش‌فرض ۱ ساعته طلایی (۱h) برای حذف نویزها
  riskProfile: 'medium',

  // Medium profile defaults (تایم‌فریم ۱ ساعته با فیلتر دقیق شکست و RSI)
  minScore: 85,
  minMovePct: 0.45,
  volumeSpikeX: 1.8,
  atrStopMult: 2.2,
  takeProfitR: 2.0,
  cooldownSec: 300,
  maxHoldMinutes: 120,

  // Paper account. Fee values are editable taker-fee percentages.
  paperInitialEquity: 1000,
  orderMargin: 40,
  leverage: 5,
  feeOpenPct: 0.055,
  feeClosePct: 0.055,
  slippagePct: 0.02,
  dailyLossLimitPct: 3,
  maxOpenPositions: 3,

  scanIntervalSec: 5,
  paperAutoDefault: 'true',
  webhookToken: '',
  cloudServerUrl: '',
  activeAccount: 'hadi',
  customFormula: "if (rsi < 36 && movePct > 0.3 && volX > 1.4) { return { side: 'LONG', score: 92, why: 'کف RSI + تایید حجم صعودی' }; } if (rsi > 66 && movePct < -0.3) { return { side: 'SHORT', score: 92, why: 'سقف اشباع خرید RSI' }; }"
});

export const RISK_PROFILES = Object.freeze({
  low: Object.freeze({
    minScore: 82,
    minMovePct: 0.25,
    volumeSpikeX: 2.0,
    atrStopMult: 1.5,
    takeProfitR: 1.5,
    cooldownSec: 240,
    maxHoldMinutes: 15,
    orderMargin: 20,
    leverage: 3,
    dailyLossLimitPct: 1.5,
    maxOpenPositions: 2
  }),
  medium: Object.freeze({
    minScore: 72,
    minMovePct: 0.18,
    volumeSpikeX: 1.65,
    atrStopMult: 1.25,
    takeProfitR: 1.35,
    cooldownSec: 150,
    maxHoldMinutes: 20,
    orderMargin: 40,
    leverage: 5,
    dailyLossLimitPct: 3,
    maxOpenPositions: 3
  }),
  high: Object.freeze({
    minScore: 65,
    minMovePct: 0.12,
    volumeSpikeX: 1.35,
    atrStopMult: 1.0,
    takeProfitR: 1.1,
    cooldownSec: 60,
    maxHoldMinutes: 30,
    orderMargin: 80,
    leverage: 10,
    dailyLossLimitPct: 5,
    maxOpenPositions: 5
  })
});

export const RISK_PROFILE_LABELS = Object.freeze({
  low: 'کم‌ریسک — فیلتر قوی، حجم/اهرم کمتر',
  medium: 'متوسط — تعادل سیگنال و ریسک',
  high: 'پرریسک — سیگنال بیشتر، اهرم/اکسپوژر بالاتر'
});

export const STORAGE_KEYS = Object.freeze({
  settings: 'scalp.lab.settings.v3',
  state: 'scalp.lab.state.v3',
  logs: 'scalp.lab.logs.v3'
});

export const DATA_MODES = Object.freeze({
  LIVE: 'live',
  MOCK_SERVER: 'mock-server',
  MOCK_LOCAL: 'mock-local'
});
