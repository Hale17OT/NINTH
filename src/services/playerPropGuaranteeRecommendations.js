const numberOrNull = value => Number.isFinite(Number(value)) ? Number(value) : null;

export const DEFAULT_GUARANTEE_ROBUST_FLOOR = 0.6;

const exactKey = (playerId, kind, prop, side, line) => [
  String(playerId),
  String(kind || "").toLowerCase(),
  String(prop || "").toLowerCase(),
  String(side || "").toLowerCase(),
  Number(line),
].join(":");

export const guaranteeOddsFloor = selectedFloor => Math.max(
  1.2,
  selectedFloor === "all" ? 1.2 : Number(selectedFloor || 1.2),
);

const preferredSelection = (threshold, side, floor) => (threshold?.melbet_selections?.[side] || [])
  .filter(selection => Number(selection.decimal_odds) >= floor)
  .sort((a, b) => {
    const formatPriority = value => value === "over_under" ? 0 : 1;
    return formatPriority(a.format) - formatPriority(b.format)
      || Number(b.decimal_odds) - Number(a.decimal_odds);
  })[0] || null;

const recordScore = (record, probability) => {
  const samples = Number(record.samples || 0);
  const recentSamples = Number(record.recent_10_samples || 0);
  const recentRate = recentSamples ? Number(record.recent_10_correct || 0) / recentSamples : Number(record.accuracy || 0);
  const sampleMaturity = Math.min(1, samples / 20);
  return 0.55 * Number(record.wilson_lower || 0)
    + 0.2 * recentRate
    + 0.15 * Number(probability || 0)
    + 0.1 * sampleMaturity;
};

export const guaranteeHistoryProbability = record => {
  const recentSamples = Number(record?.recent_10_samples || 0);
  const recentAccuracy = recentSamples
    ? Number(record?.recent_10_correct || 0) / recentSamples
    : Number(record?.accuracy || 0);
  return Math.max(0, Math.min(1,
    0.7 * Number(record?.wilson_lower || 0) + 0.3 * recentAccuracy,
  ));
};

export const guaranteeRobustFloor = value => {
  if (value == null || value === "") return DEFAULT_GUARANTEE_ROBUST_FLOOR;
  const floor = numberOrNull(value);
  return floor == null
    ? DEFAULT_GUARANTEE_ROBUST_FLOOR
    : Math.max(0, Math.min(1, floor));
};

export const guaranteeRobustProbability = (record, probability) => Math.min(
  Number(probability || 0),
  guaranteeHistoryProbability(record),
);

export function buildGuaranteeCandidates(games, records, options = {}) {
  const minimumSamples = Math.max(1, Number(options.minimumSamples || 3));
  const oddsFloor = guaranteeOddsFloor(options.minimumOdds);
  const robustFloor = guaranteeRobustFloor(options.minimumRobustProbability);
  const recordMap = new Map();
  for (const record of records || []) {
    if (Number(record.samples || 0) < minimumSamples) continue;
    recordMap.set(exactKey(record.player_id, record.kind, record.prop, record.side, record.line), record);
  }

  const candidates = [];
  for (const game of games || []) for (const player of game.players || []) for (const prop of player.props || []) {
    for (const line of prop.thresholds || []) for (const side of ["over", "under"]) {
      const record = recordMap.get(exactKey(player.player_id, player.kind, prop.prop, side, line.line));
      if (!record) continue;
      const melbetSelection = preferredSelection(line, side, oddsFloor);
      const probability = numberOrNull(line[`${side}_probability`]);
      if (!melbetSelection || probability == null) continue;
      const historyProbability = guaranteeHistoryProbability(record);
      const robustProbability = guaranteeRobustProbability(record, probability);
      if (robustProbability < robustFloor) continue;
      candidates.push({
        game,
        player,
        prop,
        line,
        side,
        probability,
        recommendationProbability: historyProbability,
        robustProbability,
        processProbability: robustProbability,
        sportsbookProbability: 1 / Number(melbetSelection.decimal_odds),
        melbetSelection,
        guaranteeRecord: record,
        guaranteeScore: recordScore(record, probability),
        guaranteeRobustFloor: robustFloor,
        marketRule: null,
      });
    }
  }
  return candidates.sort((a, b) => b.guaranteeScore - a.guaranteeScore
    || b.robustProbability - a.robustProbability
    || Number(b.guaranteeRecord.samples) - Number(a.guaranteeRecord.samples)
    || Number(a.melbetSelection.decimal_odds) - Number(b.melbetSelection.decimal_odds));
}

export function selectGuaranteeCandidates(candidates, target, options = {}) {
  const limit = Math.max(0, Number(target || 0));
  const marketSideCap = options.sweep ? 2 : 3;
  const selected = [];
  const games = new Set();
  const marketSides = new Map();
  for (const candidate of candidates || []) {
    const gameKey = String(candidate.game?.game_id);
    const marketSideKey = `${candidate.player?.kind}:${candidate.prop?.prop}:${candidate.side}`;
    if (games.has(gameKey) || Number(marketSides.get(marketSideKey) || 0) >= marketSideCap) continue;
    selected.push({ ...candidate, candidateRank: selected.length + 1, withinGameRank: 1 });
    games.add(gameKey);
    marketSides.set(marketSideKey, Number(marketSides.get(marketSideKey) || 0) + 1);
    if (selected.length >= limit) break;
  }
  return selected;
}

export const isExactGuaranteePick = (record, player, prop, side, line) => (
  exactKey(record?.player_id, record?.kind, record?.prop, record?.side, record?.line)
  === exactKey(player?.player_id, player?.kind, prop?.prop, side, line?.line)
);
