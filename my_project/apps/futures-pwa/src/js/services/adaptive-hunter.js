const MIN_WEIGHT = 0.25;
const MAX_WEIGHT = 4;
const LEARNING_RATE = 0.12;

export function scoreAdaptiveHunter(votes, weights = {}, minScore = 55) {
  const active = (votes || []).filter(vote => vote && [-1, 1].includes(vote.direction));
  if (active.length < 2) return { direction: 0, score: 0, activeExperts: active.length };
  const denominator = active.reduce((sum, vote) => sum + (Number(weights[vote.id]) || 1) * vote.confidence, 0);
  if (!(denominator > 0)) return { direction: 0, score: 0, activeExperts: active.length };
  const signed = active.reduce((sum, vote) => sum + (Number(weights[vote.id]) || 1) * vote.confidence * vote.direction, 0);
  const score = Math.abs(signed / denominator) * 100;
  return {
    direction: score >= minScore ? Math.sign(signed) : 0,
    score: Math.round(score),
    activeExperts: active.length
  };
}

// Called exclusively from PaperBroker.close after gross PnL and both fees are known.
export function learnAdaptiveHunter(weights = {}, votes = [], side, netPnl, notional, outcomeTs = Date.now()) {
  const next = { ...weights };
  const direction = side === 'LONG' ? 1 : side === 'SHORT' ? -1 : 0;
  const scale = Math.max(0, Math.min(1, Math.abs(Number(netPnl) / (Number(notional) || 1)) * 20));
  const result = [];
  for (const vote of votes || []) {
    if (!vote?.id || ![-1, 1].includes(vote.direction)) continue;
    const before = Number(next[vote.id]) || 1;
    const reward = Math.sign(Number(netPnl)) * (vote.direction === direction ? 1 : -1) * scale;
    const after = Math.max(MIN_WEIGHT, Math.min(MAX_WEIGHT, before * Math.exp(LEARNING_RATE * reward)));
    next[vote.id] = after;
    result.push({ expert: vote.id, weightBefore: before, weightAfter: after, netPnl: Number(netPnl), outcomeTs });
  }
  return { weights: next, updates: result };
}
