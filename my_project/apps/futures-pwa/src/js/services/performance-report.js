export class PerformanceReport {
  summarize(state, initialEquity, profile = null, scoringMode = null) {
    const allTrades = Array.isArray(state?.paperTrades) ? state.paperTrades : [];
    let trades = profile ? allTrades.filter(trade => trade.riskProfile === profile) : allTrades;
    if (scoringMode) {
      trades = trades.filter(trade => (trade.scoringMode || 'base') === scoringMode);
    }
    const chronological = [...trades].reverse();
    const profileStart = profile ? state?.profileStarts?.[profile] : null;
    const startingEquity = Number(profileStart ?? initialEquity) || 0;
    let netPnl = 0;
    let fees = 0;
    let grossPnl = 0;
    let grossProfit = 0;
    let grossLoss = 0;
    let holdSeconds = 0;
    let peak = startingEquity;
    let curve = startingEquity;
    let maxDrawdown = 0;

    for (const trade of chronological) {
      const net = Number(trade.pnl || 0);
      const gross = Number(trade.grossPnl || 0);
      const tradeFees = Number(trade.fees || Number(trade.feeOpen || 0) + Number(trade.feeClose || 0));
      netPnl += net;
      grossPnl += gross;
      fees += tradeFees;
      holdSeconds += Number(trade.durationSec || 0);
      if (net > 0) grossProfit += net;
      if (net < 0) grossLoss += Math.abs(net);
      curve += net;
      peak = Math.max(peak, curve);
      maxDrawdown = Math.max(maxDrawdown, peak - curve);
    }

    const wins = trades.filter(trade => Number(trade.pnl || 0) > 0).length;
    const losses = trades.filter(trade => Number(trade.pnl || 0) < 0).length;
    const count = trades.length;
    const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;

    return {
      profile: profile || 'all',
      scope: profile ? `closed paper trades / ${profile} / net after fees` : 'closed paper trades / net after fees',
      count,
      wins,
      losses,
      winRate: count ? wins / count * 100 : null,
      netPnl,
      grossPnl,
      fees,
      grossProfit,
      grossLoss,
      profitFactor,
      expectancy: count ? netPnl / count : null,
      averageWin: wins ? grossProfit / wins : null,
      averageLoss: losses ? grossLoss / losses : null,
      averageHoldSec: count ? holdSeconds / count : null,
      maxDrawdown,
      maxDrawdownPct: startingEquity > 0 ? maxDrawdown / startingEquity * 100 : null
    };
  }

  compareScoringModes(state, initialEquity, profile = null) {
    const baseline = this.summarize(state, initialEquity, profile, 'base');
    const hunter = this.summarize(state, initialEquity, profile, 'adaptive_hunter');
    return {
      baseline,
      adaptiveHunter: hunter,
      hunterWeightUpdates: Array.isArray(state?.hunterUpdates) ? state.hunterUpdates.length : 0,
      note: 'Closed paper trades only; net PnL includes entry and exit fees. Historical comparison, not a live-performance claim.'
    };
  }
}
