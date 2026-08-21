function totalsExposureKey(candidate) {
  const option = candidate?.option || {};
  return option.market === "totals" ? `${option.side}:${Number(option.line)}` : null;
}

export function moneylineBuilderProbability(game) {
  const adjusted = Number(game?.moneyline_builder_probability);
  return Number.isFinite(adjusted)
    ? adjusted
    : Number(game?.recommended_probability || 0);
}

function permitsTotalsExposure(selected, candidate, maximum, excludedIndex = -1) {
  const key = totalsExposureKey(candidate);
  if (!key) return true;
  const count = selected.reduce((total, row, index) => (
    index !== excludedIndex && totalsExposureKey(row) === key ? total + 1 : total
  ), 0);
  return count < maximum;
}

export function selectMixedCandidates(candidates, target, minimumShare = 0.2) {
  const wanted = Math.max(1, Number(target) || 1);
  const exactLineSideMaximum = wanted <= 5 ? 2 : 3;
  const ranked = [...(candidates || [])].sort((a, b) => Number(b.option?.probability || 0) - Number(a.option?.probability || 0));
  const selected = [];
  const games = new Set();
  for (const candidate of ranked) {
    const gameId = String(candidate.game?.game_id ?? "");
    if (!gameId || games.has(gameId) || !permitsTotalsExposure(selected, candidate, exactLineSideMaximum)) continue;
    selected.push(candidate);
    games.add(gameId);
    if (selected.length === wanted) break;
  }
  if (selected.length < 2) return selected;
  const minimum = Math.max(1, Math.ceil(selected.length * Number(minimumShare || 0)));
  for (const market of ["totals", "moneyline"]) {
    while (selected.filter(row => row.option?.market === market).length < minimum) {
      const replacement = ranked.find(candidate => {
        if (candidate.option?.market !== market) return false;
        const sameGameIndex = selected.findIndex(row => String(row.game?.game_id) === String(candidate.game?.game_id));
        const sameGame = sameGameIndex >= 0 ? selected[sameGameIndex] : null;
        return (!sameGame || sameGame.option?.market !== market)
          && permitsTotalsExposure(selected, candidate, exactLineSideMaximum, sameGameIndex);
      });
      if (!replacement) break;
      const sameGameIndex = selected.findIndex(row => String(row.game?.game_id) === String(replacement.game?.game_id));
      if (sameGameIndex >= 0) {
        const displacedMarket = selected[sameGameIndex].option?.market;
        if (selected.filter(row => row.option?.market === displacedMarket).length <= minimum) break;
        selected.splice(sameGameIndex, 1, replacement);
        continue;
      }
      const replaceable = selected
        .map((row, index) => ({ row, index }))
        .filter(({ row }) => row.option?.market !== market
          && selected.filter(item => item.option?.market === row.option?.market).length > minimum)
        .sort((a, b) => Number(a.row.option?.probability || 0) - Number(b.row.option?.probability || 0))[0];
      if (!replaceable) break;
      selected.splice(replaceable.index, 1, replacement);
    }
  }
  return selected.sort((a, b) => Number(b.option?.probability || 0) - Number(a.option?.probability || 0));
}

export function selectTotalsCandidates(candidates, target) {
  const wanted = Math.max(1, Number(target) || 1);
  const exactLineSideMaximum = wanted <= 5 ? 2 : 3;
  const selected = [];
  const games = new Set();
  const exposure = new Map();
  for (const candidate of candidates || []) {
    const gameId = String(candidate.game?.game_id ?? "");
    const option = candidate.option || {};
    const key = `${option.side}:${Number(option.line)}`;
    if (!gameId || games.has(gameId) || (exposure.get(key) || 0) >= exactLineSideMaximum) continue;
    selected.push(candidate);
    games.add(gameId);
    exposure.set(key, (exposure.get(key) || 0) + 1);
    if (selected.length === wanted) break;
  }
  return selected;
}
