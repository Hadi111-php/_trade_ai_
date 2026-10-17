import { MomentumScalpStrategy } from '../src/js/services/strategy.js';
import { PaperBroker } from '../src/js/services/paper-broker.js';

function createMockCandles(count = 50, trend = 'neutral', volatility = 1.0) {
  const candles = [];
  let price = 50000;
  const now = Date.now();
  for (let i = 0; i < count; i++) {
    const ts = now - (count - i) * 60000;
    let change = (Math.random() - 0.5) * 50 * volatility;
    if (trend === 'up') change += 20 * volatility;
    if (trend === 'down') change -= 20 * volatility;
    const open = price;
    price = open + change;
    const high = Math.max(open, price) + Math.random() * 15 * volatility;
    const low = Math.min(open, price) - Math.random() * 15 * volatility;
    const volume = 100 + Math.random() * 50;
    candles.push({ ts, open, high, low, close: price, volume });
  }
  return candles;
}

function runTests() {
  console.log('=== RUNNING STRATEGY & PAPER BROKER INTEGRATION TESTS ===');
  let passed = 0;
  let failed = 0;

  function assert(condition, message) {
    if (condition) {
      console.log(`[PASS] ${message}`);
      passed++;
    } else {
      console.error(`[FAIL] ${message}`);
      failed++;
    }
  }

  const mockSettings = {
    value: {
      algoMode: 'consensus',
      minScore: 70,
      minMovePct: 0.1,
      volumeSpikeX: 1.5,
      atrStopMult: 1.5,
      takeProfitR: 2.0,
      paperInitialEquity: 1000,
      orderMargin: 50,
      leverage: 5,
      feeOpenPct: 0.055,
      feeClosePct: 0.055,
      slippagePct: 0.02,
      maxOpenPositions: 3,
      dailyLossLimitPct: 5,
      cooldownSec: 0,
      riskProfile: 'medium'
    }
  };

  const mockLogger = { info: () => {}, warn: () => {}, error: () => {} };

  // Test 1: Strategy Indicator Calculations
  const strategy = new MomentumScalpStrategy(mockSettings);
  const candles = createMockCandles(50, 'up');
  const atr = strategy.atr(candles);
  const rsi = strategy.rsi(candles);
  const ema = strategy.ema(candles, 20);
  const bb = strategy.bollingerBands(candles);

  assert(atr > 0, `ATR calculated correctly: ${atr.toFixed(2)}`);
  assert(rsi >= 0 && rsi <= 100, `RSI calculated correctly: ${rsi.toFixed(2)}`);
  assert(ema > 0, `EMA calculated correctly: ${ema.toFixed(2)}`);
  assert(bb.upper >= bb.middle && bb.middle >= bb.lower, 'Bollinger Bands structure valid');

  // Test 2: Pump & Dump Algorithm Detection
  const pumpCandles = createMockCandles(50, 'neutral');
  // Inject massive volume spike and price surge into last candle
  const lastC = pumpCandles.at(-1);
  lastC.close = lastC.open * 1.05;
  lastC.high = lastC.close;
  lastC.volume = 2000;

  const market = { symbol: 'BTCUSDT', price: lastC.close, candles: pumpCandles, source: 'TEST' };
  mockSettings.value.algoMode = 'pump_dump';
  const pdResult = strategy.analyze(market);

  assert(pdResult.side !== 'WAIT' || pdResult.why.includes('پامپ'), `Pump detection triggered: side=${pdResult.side}, score=${pdResult.score}`);

  // Test 3: Consensus Mode Evaluation
  mockSettings.value.algoMode = 'consensus';
  const consensusResult = strategy.analyze(market);
  assert(consensusResult.score > 0, `Consensus score calculated: ${consensusResult.score}`);

  // Test 4: Paper Broker Order Execution and Risk Management
  const paperBroker = new PaperBroker(mockSettings, mockLogger);
  const initialEquity = paperBroker.state.paperEquity;

  const signal = {
    symbol: 'ETHUSDT',
    side: 'LONG',
    score: 85,
    entry: 3000,
    stop: 2950,
    take: 3100,
    notional: 250,
    qty: 0.0833,
    candleTs: Date.now(),
    source: 'TEST'
  };

  const openSuccess = paperBroker.open(signal, 'test_auto', true);
  assert(openSuccess === true, 'Paper position opened successfully');
  assert(paperBroker.state.paperPositions.length === 1, 'Position stored in state');

  const position = paperBroker.state.paperPositions[0];
  const closeSuccess = paperBroker.close(position, 3050, 'test_take_profit');
  assert(closeSuccess === true, 'Paper position closed successfully');
  assert(paperBroker.state.paperPositions.length === 0, 'Position removed after close');
  assert(paperBroker.state.paperTrades.length === 1, 'Trade recorded in trade log');

  console.log(`=== TEST SUMMARY: ${passed} PASSED, ${failed} FAILED ===`);
  if (failed > 0) process.exit(1);
}

runTests();
