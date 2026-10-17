import { $ } from './core/utils.js';
import { SettingsStore } from './services/settings-store.js';
import { Logger } from './services/logger.js';
import { MarketClient } from './services/market-client.js';
import { MomentumScalpStrategy } from './services/strategy.js';
import { PaperBroker } from './services/paper-broker.js';
import { RealBroker } from './services/real-broker.js';
import { PerformanceReport } from './services/performance-report.js';
import { DashboardView } from './ui/view.js';

export class ScalpLabApp {
  constructor() {
    this.settings = new SettingsStore();
    this.logger = new Logger();
    this.signals = new Map();
    this.prices = new Map();
    this.marketData = new Map();
    this.dataErrors = new Map();
    this.lastErrorLog = new Map();
    this.timer = null;
    this.scanInFlight = false;
    this.performance = new PerformanceReport();
    this.rebuildServices();
    this.view = new DashboardView(this);
  }

  rebuildServices() {
    this.market = new MarketClient(this.settings, this.logger);
    this.strategy = new MomentumScalpStrategy(this.settings);
    this.paper = this.paper || new PaperBroker(this.settings, this.logger);
    // Rebuilding services deliberately resets the real gate. A settings change
    // must never silently preserve permission to send an order.
    if (this.real?.enabled) this.real.kill();
    this.real = new RealBroker(this.settings, this.paper, this.logger);
    if (typeof document !== 'undefined' && $('#realAutoToggle')) $('#realAutoToggle').checked = false;
  }

  modeLabel() {
    const mode = this.settings.value.dataMode;
    if (mode === 'mock-local') return 'MOCK LOCAL';
    if (mode === 'mock-server') return 'MOCK SERVER';
    return 'BYBIT LIVE';
  }

  async scan() {
    if (this.scanInFlight) return;
    this.scanInFlight = true;
    this.paper.migrateDay();
    const symbols = [...new Set(this.settings.value.symbols)].filter(Boolean);
    $('#statusText').textContent = `${this.modeLabel()}؛ در حال دریافت دیتا...`;

    // Clear old values first. If Bybit is unavailable, stale prices/signals are
    // not presented as if they were current and no synthetic fallback is used.
    this.signals.clear();
    this.prices.clear();
    this.marketData.clear();
    this.dataErrors.clear();

    try {
      const results = await Promise.allSettled(symbols.map(symbol => this.market.get(symbol)));
      let ok = 0;

      results.forEach((result, index) => {
        const symbol = symbols[index];
        if (result.status !== 'fulfilled') {
          const message = result.reason?.message || 'خطای ناشناخته دیتا';
          this.dataErrors.set(symbol, message);
          if (this.lastErrorLog.get(symbol) !== message) {
            this.logger.info('DATA ERROR', { symbol, error: message });
            this.lastErrorLog.set(symbol, message);
          }
          return;
        }
        ok += 1;
        this.lastErrorLog.delete(symbol);
        const market = result.value;
        const signal = this.strategy.analyze(market);
        this.marketData.set(symbol, market);
        this.signals.set(symbol, signal);
        this.prices.set(symbol, market.price);
      });

      // Process exits before new entries. Closed-candle OHLC is used only as an
      // evidence that a stop/target was touched; with both touched, SL wins.
      this.paper.updateStops(this.marketData, this.signals);

      const paperToggle = $('#paperAutoToggle');
      const paperEnabled = !!paperToggle?.checked || this.real.enabled;
      for (const signal of this.signals.values()) {
        if (paperEnabled && signal.side !== 'WAIT') this.paper.open(signal, 'auto');
        // Real is a second, explicit gate. It is never enabled by default and
        // requires BYBIT LIVE data plus a user-configured secure backend.
        if (this.real.enabled && signal.side !== 'WAIT' && signal.score >= Number(this.settings.value.minScore)) {
          await this.real.send(signal);
        }
      }

      const update = new Date().toLocaleTimeString();
      $('#lastUpdate').textContent = `آخرین اسکن: ${update} • ${ok}/${symbols.length}`;
      if (ok > 0) {
        $('#statusText').textContent = `${this.modeLabel()} • ${ok}/${symbols.length} بازار • ${this.settings.value.timeframe}m`;
      } else {
        $('#statusText').textContent = 'دیتای بازار در دسترس نیست؛ هیچ fallback ساختگی استفاده نشد';
      }
      this.view.renderAll();
    } finally {
      this.scanInFlight = false;
    }
  }

  applyRiskProfile(profile) {
    this.settings.applyRiskProfile(profile);
    this.rebuildServices();
    this.view.renderSettings();
    this.schedule();
    this.logger.info('RISK PROFILE APPLIED', { profile: this.settings.value.riskProfile });
    this.view.renderAll();
    void this.scan();
  }

  schedule() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if ($('#autoScanToggle')?.checked) {
      const seconds = Math.max(3, Number(this.settings.value.scanIntervalSec) || 5);
      this.timer = setInterval(() => this.scan(), seconds * 1000);
    }
  }

  closeAllPaper() {
    for (const position of [...this.paper.state.paperPositions]) {
      this.paper.close(position, this.prices.get(position.symbol) || position.entry, 'close-all');
    }
    this.view.renderAll();
  }

  resetPaper() {
    this.paper.reset();
    this.view.renderAll();
  }

  async start() {
    this.view.bind();
    this.view.renderSettings();
    this.view.renderAll();
    this.schedule();
    this.logger.info('APP START', { mode: this.modeLabel(), paperDefault: this.settings.value.paperAutoDefault });
    await this.scan().catch(error => this.logger.info('INITIAL SCAN ERROR', { error: error.message }));
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js').catch(() => {});
  }
}
