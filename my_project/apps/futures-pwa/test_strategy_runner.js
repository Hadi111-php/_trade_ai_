import { MomentumScalpStrategy } from './src/js/services/strategy.js';
import { PaperBroker } from './src/js/services/paper-broker.js';
import { PerformanceReport } from './src/js/services/performance-report.js';
import { scoreAdaptiveHunter } from './src/js/services/adaptive-hunter.js';

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
  assert(consensusResult.side === consensusResult.baseSide && consensusResult.score === consensusResult.baseScore,
    'Disabled Adaptive Hunter preserves baseline signal and score');

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

  // Adaptive Hunter votes require multiple experts; weights only change after close.
  const agreement = scoreAdaptiveHunter([
    { id: 'ema', direction: 1, confidence: 1 },
    { id: 'momentum', direction: 1, confidence: 0.8 }
  ], {}, 55);
  assert(agreement.direction === 1 && agreement.score >= 55, 'Adaptive Hunter scores aligned expert votes');
  const noConsensus = scoreAdaptiveHunter([
    { id: 'ema', direction: 1, confidence: 1 },
    { id: 'momentum', direction: -1, confidence: 1 }
  ], {}, 55);
  assert(noConsensus.direction === 0, 'Adaptive Hunter rejects tied votes');

  const hunterSettings = { value: { ...mockSettings.value, paperInitialEquity: 1000, riskProfile: 'medium' } };
  const hunterBroker = new PaperBroker(hunterSettings, mockLogger);
  const hunterSignal = {
    ...signal,
    symbol: 'BTCUSDT', side: 'LONG', entry: 3000, score: 82,
    stop: 2950, take: 3100, candleTs: Date.now(),
    scoringMode: 'adaptive_hunter', baseSide: 'LONG', baseScore: 80, hunterScore: 84,
    hunterVotes: [{ id: 'ema', direction: 1, confidence: 1 }, { id: 'momentum', direction: 1, confidence: 0.8 }]
  };
  hunterBroker.open(hunterSignal, 'hunter-test', true);
  assert(Object.keys(hunterBroker.state.hunterWeights).length === 0,
    'Adaptive Hunter weights stay unchanged while outcome is unresolved');
  const hunterPosition = hunterBroker.state.paperPositions[0];
  hunterBroker.close(hunterPosition, 3100, 'test_close');
  assert(hunterBroker.state.hunterWeights.ema > 1 && hunterBroker.state.hunterUpdates.length === 2,
    'Adaptive Hunter weights update only after net paper outcome is known');
  const learnedWeight = hunterBroker.state.hunterWeights.ema;
  hunterBroker.close(hunterPosition, 3200, 'duplicate_close');
  assert(hunterBroker.state.hunterWeights.ema === learnedWeight && hunterBroker.state.hunterUpdates.length === 2,
    'A closed signal cannot produce a duplicate learning update');
  const baseSignal = { ...hunterSignal, symbol: 'ETHUSDT', scoringMode: 'base', hunterVotes: [] };
  hunterBroker.open(baseSignal, 'base-test', true);
  hunterBroker.close(hunterBroker.state.paperPositions[0], 3050, 'test_close');
  const comparison = new PerformanceReport().compareScoringModes(hunterBroker.state, 1000, 'medium');
  assert(comparison.adaptiveHunter.count === 1 && comparison.baseline.count === 1,
    'PWA report separates baseline and Hunter closed trades');

  console.log(`=== TEST SUMMARY: ${passed} PASSED, ${failed} FAILED ===`);
  if (failed > 0) process.exit(1);
}

runTests();
