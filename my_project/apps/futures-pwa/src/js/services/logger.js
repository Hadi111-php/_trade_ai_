import { readJson, writeJson } from '../core/utils.js';
import { STORAGE_KEYS } from '../core/config.js';
export class Logger {
  constructor(){ this.lines = readJson(STORAGE_KEYS.logs, []); this.listeners = new Set(); }
  onChange(fn){ this.listeners.add(fn); fn(this.lines); }
  emit(){ writeJson(STORAGE_KEYS.logs, this.lines); this.listeners.forEach(fn=>fn(this.lines)); }
  info(msg, obj){ this.lines.unshift(`[${new Date().toLocaleString()}] ${msg}${obj ? ' '+JSON.stringify(obj) : ''}`); this.lines = this.lines.slice(0,700); this.emit(); }
  clear(){ this.lines = []; this.emit(); }
}
