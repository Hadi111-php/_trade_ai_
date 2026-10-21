export class RealBroker {
  constructor(settings, paper, logger) {
    this.s = settings;
    this.paper = paper;
    this.log = logger;
    this.enabled = false;
    this.lastSentAt = new Map();
    this.inFlight = new Set();
  }

  setEnabled(value) {
    this.enabled = !!value;
    this.log.info(this.enabled ? 'REAL ENABLED (explicit user action)' : 'REAL DISABLED');
  }

  kill() {
    this.enabled = false;
    this.inFlight.clear();
    this.log.info('KILL SWITCH ACTIVATED');
  }

  record(row) {
    const state = this.paper.state;
    state.realOrders.unshift(row);
    state.realOrders = state.realOrders.slice(0, 250);
    this.paper.save();
    this.log.info('REAL ORDER', row);
    return row;
  }

  async send(signal) {
    const row = {
      time: Date.now(),
      symbol: signal?.symbol || '--',
      side: signal?.side || '--',
      status: 'SKIP',
      message: ''
    };

    if (!signal) {
      row.message = 'سیگنال خالی است';
      return this.record(row);
    }
    if (!this.enabled) {
      row.message = 'Real OFF';
      return this.record(row);
    }
    if (!signal || signal.side === 'WAIT') {
      row.message = 'سیگنال WAIT است';
      return this.record(row);
    }
    if (this.s.value.dataMode !== 'live' && !signal.source.includes('LIVE')) {
      row.status = 'REJECT';
      row.message = 'ارسال واقعی فقط با دیتای زنده (LIVE) مجاز است؛ داده شبیه‌ساز قابل ترید واقعی نیست';
      return this.record(row);
    }
    if (!this.s.value.realWebhookUrl) {
      row.status = 'REJECT';
      row.message = 'Webhook امن Backend تنظیم نشده است';
      return this.record(row);
    }
    if (this.paper.dailyLossExceeded()) {
      row.status = 'REJECT';
      row.message = 'Daily loss limit';
      return this.record(row);
    }

    const now = Date.now();
    const cooldownMs = Number(this.s.value.cooldownSec) * 1000;
    const last = Number(this.lastSentAt.get(signal.symbol) || 0);
    if (this.inFlight.has(signal.signalId) || now - last < cooldownMs) {
      row.message = 'Duplicate/cooldown؛ سفارش تکراری ارسال نشد';
      return this.record(row);
    }
    this.inFlight.add(signal.signalId);
    this.lastSentAt.set(signal.symbol, now);

    const mappedSymbol = this.s.value.symbolMap[signal.symbol] || signal.symbol;
    const activeAcc = this.s.value.activeAccount || 'hadi';
    const payload = {
      accountId: activeAcc,
      accountLabel: activeAcc === 'hadi' ? 'حساب داداش هادی' : 'حساب آقا پسر',
      venue: this.s.value.realVenue || 'lbank-futures',
      exchange: this.s.value.realVenue || 'lbank-futures',
      mode: 'live-trade',
      category: this.s.value.bybitCategory || 'linear',
      action: 'open',
      symbol: mappedSymbol,
      side: signal.side,
      orderType: 'MARKET',
      margin: Number(this.s.value.orderMargin),
      leverage: Number(this.s.value.leverage),
      qty: signal.qty,
      expectedEntry: signal.entry,
      stopLoss: signal.stop,
      takeProfit: signal.take,
      signalScore: signal.score,
      signalId: signal.signalId,
      source: signal.source || 'live-feed',
      timestamp: new Date().toISOString()
    };

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (this.s.value.webhookToken) headers['X-Webhook-Token'] = this.s.value.webhookToken;
      const response = await fetch(this.s.value.realWebhookUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });
      const text = await response.text();
      row.status = response.ok ? 'SENT' : 'ERROR';
      row.message = text.slice(0, 220);
      row.signalId = signal.signalId;
    } catch (error) {
      row.status = 'ERROR';
      row.message = error.message;
      row.signalId = signal.signalId;
    } finally {
      this.inFlight.delete(signal.signalId);
    }
    return this.record(row);
  }
}
