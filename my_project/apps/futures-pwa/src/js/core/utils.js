export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export const clone = value => JSON.parse(JSON.stringify(value));

export const fmt = (value, decimals = 4) => Number.isFinite(+value)
  ? (+value).toLocaleString('en-US', { maximumFractionDigits: decimals })
  : '--';

export const pct = value => Number.isFinite(+value) ? `${(+value).toFixed(2)}%` : '--';
export const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
export const uid = () => globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2);
export const mean = values => {
  const finite = values.map(Number).filter(Number.isFinite);
  return finite.reduce((sum, value) => sum + value, 0) / (finite.length || 1);
};

export const timeframeMs = timeframe => {
  const value = String(timeframe).toUpperCase();
  if (value === 'D') return 24 * 60 * 60 * 1000;
  if (value === 'W') return 7 * 24 * 60 * 60 * 1000;
  if (value === 'M') return 30 * 24 * 60 * 60 * 1000;
  return Math.max(1, Number(value) || 1) * 60 * 1000;
};

export const readJson = (key, fallback) => {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
};

export const writeJson = (key, value) => {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage can be disabled in private/sandboxed browser contexts.
  }
};

export const escapeHtml = value => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

export const toBool = value => value === true || value === 'true' || value === 1 || value === '1';
