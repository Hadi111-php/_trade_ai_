import { DEFAULT_SETTINGS, RISK_PROFILES, STORAGE_KEYS } from '../core/config.js';
import { clone, readJson, writeJson } from '../core/utils.js';

export class SettingsStore {
  constructor() {
    this.value = { ...clone(DEFAULT_SETTINGS), ...readJson(STORAGE_KEYS.settings, {}) };
  }

  save(next = this.value) {
    this.value = { ...clone(DEFAULT_SETTINGS), ...next };
    writeJson(STORAGE_KEYS.settings, this.value);
  }

  applyRiskProfile(profile = 'medium') {
    const selected = RISK_PROFILES[profile] ? profile : 'medium';
    this.save({ ...this.value, ...clone(RISK_PROFILES[selected]), riskProfile: selected });
  }

  reset() {
    this.save(clone(DEFAULT_SETTINGS));
  }
}
