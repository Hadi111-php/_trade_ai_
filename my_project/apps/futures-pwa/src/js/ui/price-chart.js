import { fmt } from '../core/utils.js';

export class PriceChart {
  constructor(canvas) {
    this.canvas = canvas;
    this.market = null;
    this.signal = null;
    this.resizeObserver = typeof ResizeObserver === 'function'
      ? new ResizeObserver(() => this.draw())
      : null;
    if (this.resizeObserver) this.resizeObserver.observe(canvas);
    window.addEventListener('resize', () => this.draw());
  }

  setData(market, signal) {
    this.market = market || null;
    this.signal = signal || null;
    this.draw();
  }

  clear(message = 'No market data') {
    this.market = null;
    this.signal = null;
    this.draw(message);
  }

  dimensions() {
    const rect = this.canvas.getBoundingClientRect();
    const width = Math.max(320, Math.floor(rect.width || this.canvas.clientWidth || 820));
    const height = Math.max(260, Math.floor(rect.height || 360));
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.floor(width * ratio);
    this.canvas.height = Math.floor(height * ratio);
    this.canvas.style.height = `${height}px`;
    const context = this.canvas.getContext('2d');
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { context, width, height };
  }

  draw(emptyMessage = 'منتظر دیتای معتبر Bybit...') {
    const { context: ctx, width, height } = this.dimensions();
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#08182a';
    ctx.fillRect(0, 0, width, height);

    if (!this.market?.candles?.length) {
      ctx.fillStyle = '#8ca3bd';
      ctx.font = '14px Tahoma, Arial';
      ctx.textAlign = 'center';
      ctx.fillText(emptyMessage, width / 2, height / 2);
      return;
    }

    const candles = this.market.candles.slice(-90);
    const signal = this.signal;
    const padding = { left: 58, right: 18, top: 24, bottom: 48 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    const volumeHeight = Math.max(34, chartHeight * 0.16);
    const priceHeight = chartHeight - volumeHeight - 10;
    const plottedPrices = [
      ...candles.flatMap(candle => [candle.low, candle.high]),
      Number(this.market.price),
      ...(signal?.side !== 'WAIT' ? [signal.entry, signal.stop, signal.take] : [])
    ].filter(Number.isFinite);
    const minPrice = Math.min(...plottedPrices);
    const maxPrice = Math.max(...plottedPrices);
    const span = Math.max(maxPrice - minPrice, maxPrice * 0.0001);
    const lower = minPrice - span * 0.08;
    const upper = maxPrice + span * 0.08;
    const maxVolume = Math.max(...candles.map(candle => candle.volume), 1);
    const step = chartWidth / candles.length;
    const bodyWidth = Math.max(2, step * 0.62);

    const priceY = price => padding.top + (upper - price) / (upper - lower) * priceHeight;
    const volumeY = volume => padding.top + priceHeight + 10 + (1 - volume / maxVolume) * volumeHeight;

    // Grid and price labels.
    ctx.strokeStyle = 'rgba(140,163,189,.16)';
    ctx.lineWidth = 1;
    ctx.font = '10px Tahoma, Arial';
    ctx.textAlign = 'left';
    ctx.fillStyle = '#8ca3bd';
    for (let i = 0; i <= 4; i += 1) {
      const y = padding.top + priceHeight * i / 4;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      const value = upper - (upper - lower) * i / 4;
      ctx.fillText(fmt(value, value > 10 ? 2 : 6), 5, y + 4);
    }

    // Volume bars and candlesticks.
    candles.forEach((candle, index) => {
      const x = padding.left + index * step + step / 2;
      const rising = candle.close >= candle.open;
      const color = rising ? '#35e0a1' : '#ff5c7a';
      ctx.fillStyle = rising ? 'rgba(53,224,161,.28)' : 'rgba(255,92,122,.28)';
      const volumeTop = volumeY(candle.volume);
      ctx.fillRect(x - bodyWidth / 2, volumeTop, bodyWidth, padding.top + priceHeight + 10 + volumeHeight - volumeTop);

      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, priceY(candle.high));
      ctx.lineTo(x, priceY(candle.low));
      ctx.stroke();

      ctx.fillStyle = color;
      const openY = priceY(candle.open);
      const closeY = priceY(candle.close);
      ctx.fillRect(x - bodyWidth / 2, Math.min(openY, closeY), bodyWidth, Math.max(1, Math.abs(closeY - openY)));
    });

    const lastPrice = Number(this.market.price);
    this.drawLine(ctx, padding.left, width - padding.right, priceY(lastPrice), '#53a7ff', 'Last', lastPrice, width, padding);
    if (signal?.side !== 'WAIT') {
      this.drawLine(ctx, padding.left, width - padding.right, priceY(signal.entry), '#ffd166', 'Entry', signal.entry, width, padding);
      this.drawLine(ctx, padding.left, width - padding.right, priceY(signal.stop), '#ff5c7a', 'SL', signal.stop, width, padding);
      this.drawLine(ctx, padding.left, width - padding.right, priceY(signal.take), '#35e0a1', 'TP', signal.take, width, padding);
    }

    ctx.fillStyle = '#e9f1ff';
    ctx.font = 'bold 12px Tahoma, Arial';
    ctx.textAlign = 'right';
    ctx.fillText(`${this.market.symbol} • ${this.market.source}`, width - padding.right, 15);
    ctx.fillStyle = '#8ca3bd';
    ctx.font = '10px Tahoma, Arial';
    ctx.fillText(`Candles: ${candles.length} • ${signal?.side || 'WAIT'}`, width - padding.right, height - 12);
  }

  drawLine(ctx, left, right, y, color, label, value, width, padding) {
    const visibleHeight = this.canvas.clientHeight || 360;
    if (!Number.isFinite(y) || y < padding.top - 5 || y > visibleHeight - padding.bottom + 5) return;
    ctx.save();
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
    ctx.restore();
    ctx.fillStyle = color;
    ctx.font = '10px Tahoma, Arial';
    ctx.textAlign = 'left';
    ctx.fillText(`${label} ${fmt(value, value > 10 ? 2 : 6)}`, 5, Math.max(padding.top + 10, y - 4));
  }
}
