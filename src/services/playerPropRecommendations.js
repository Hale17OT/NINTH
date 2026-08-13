const clamp = (value, minimum, maximum) =>
  Math.min(maximum, Math.max(minimum, Number(value)));

export function historyAdjustedProbability(probability, historyGames) {
  const raw = clamp(probability, 0.01, 0.99);
  const historyMultiplier = Math.min(
    1,
    0.72 + Math.max(0, Number(historyGames) || 0) / 180,
  );
  return 0.5 + (raw - 0.5) * historyMultiplier;
}

export function conservativeRecommendationProbability(
  probability,
  historyGames,
  marketRule,
  evidence = {},
) {
  const historyAdjusted = historyAdjustedProbability(probability, historyGames);
  const multipliers = [marketRule?.confidence_multiplier ?? 0.5];
  if (evidence.exactEligible) multipliers.push(evidence.exact?.confidence_multiplier ?? 0.5);
  if (evidence.selectionEligible) multipliers.push(evidence.selection?.confidence_multiplier ?? 0.5);
  if (evidence.pricedEligible) multipliers.push(evidence.priced?.confidence_multiplier ?? 0.5);
  const calibrationMultiplier = clamp(Math.min(...multipliers), 0.5, 1);
  return 0.5 + (historyAdjusted - 0.5) * calibrationMultiplier;
}

export function exactMarketSegmentKey(side, line) {
  return `${String(side || "").toLowerCase()}:${Number(line).toString()}`;
}

export function exactMarketEvidence(marketRule, side, line, policy = {}) {
  const key = exactMarketSegmentKey(side, line);
  const exact = marketRule?.segments?.[key] || null;
  const selection = marketRule?.selection_segments?.[key] || null;
  const priced = marketRule?.priced_segments?.[key] || null;
  const qualityEligible = (evidence, minimum) => {
    if (Number(evidence?.samples || 0) < Number(minimum)) return false;
    const brier = Number(evidence?.brier);
    const lower = Number(evidence?.lower_bound);
    const accuracy = Number(evidence?.accuracy);
    const confidence = Number(evidence?.mean_confidence);
    return Number.isFinite(brier)
      && brier <= Number(policy.maximum_exact_segment_brier ?? .24)
      && Number.isFinite(lower)
      && lower >= Number(policy.minimum_exact_segment_lower_bound ?? .5)
      && Number.isFinite(accuracy)
      && Number.isFinite(confidence)
      && confidence - accuracy <= Number(policy.maximum_exact_segment_calibration_gap ?? .05);
  };
  return {
    key,
    exact,
    selection,
    priced,
    exactEligible: qualityEligible(exact, policy.minimum_exact_segment_samples || 30),
    selectionEligible: qualityEligible(selection, policy.minimum_selection_segment_samples || 10),
    pricedEligible: qualityEligible(priced, policy.minimum_priced_segment_samples || 30),
  };
}

export function robustRecommendationProbability(
  probability,
  historyGames,
  marketRule,
  side,
  line,
  policy = {},
) {
  const evidence = exactMarketEvidence(marketRule, side, line, policy);
  const recommendationProbability = conservativeRecommendationProbability(
    probability,
    historyGames,
    marketRule,
    evidence,
  );
  const lowerBounds = [];
  if (evidence.exactEligible && Number.isFinite(Number(evidence.exact?.lower_bound))) {
    lowerBounds.push(Number(evidence.exact.lower_bound));
  }
  if (evidence.selectionEligible && Number.isFinite(Number(evidence.selection?.lower_bound))) {
    lowerBounds.push(Number(evidence.selection.lower_bound));
  }
  if (evidence.pricedEligible && Number.isFinite(Number(evidence.priced?.lower_bound))) {
    lowerBounds.push(Number(evidence.priced.lower_bound));
  }
  if (!lowerBounds.length) return { recommendationProbability, robustProbability: recommendationProbability, evidence };
  const auditedLowerBound = Math.max(0.5, Math.min(...lowerBounds));
  const robustProbability = Math.min(
    recommendationProbability,
    recommendationProbability * 0.35 + auditedLowerBound * 0.65,
  );
  return { recommendationProbability, robustProbability, evidence };
}

export function selectionProcessOddsBucket(value) {
  if (value == null || value === "" || value === "all") return "all";
  const floor = Number(value);
  if (!Number.isFinite(floor)) return "all";
  if (floor < 1.2) return "under_1.20";
  if (floor < 1.3) return "1.20";
  if (floor < 1.4) return "1.30";
  if (floor < 1.5) return "1.40";
  return "1.50_plus";
}

const selectionRotationBucket = value => Number(value || 0) <= 0
  ? "0" : Number(value) === 1 ? "1" : "2_plus";
const selectionRankBucket = value => Number(value || 1) <= 1
  ? "1" : Number(value) === 2 ? "2" : "3_plus";

export function buildSelectionProcessEvidence(candidate, policy = {}, options = {}) {
  const audit = policy?.build_selection_audit || {};
  const style = options.buildStyle === "sweep" ? "sweep" : "balanced";
  const odds = selectionProcessOddsBucket(options.minimumOdds);
  const rotation = selectionRotationBucket(options.rotationDepth);
  const rank = selectionRankBucket(options.candidateRank);
  const action = options.selectionAction || "build_best";
  const market = `${candidate?.player?.kind}:${candidate?.prop?.prop}:${candidate?.side}`;
  const filterName = options.propPreset === "strongest" ? "strongest"
    : Number(options.selectedPropTypeCount || 0) > 0 && Number(options.selectedPropTypeCount) <= 7
      ? "focused" : "broad";
  const actionLookups = [
    ["market_action_style_odds_rotation", audit.by_market_action_style_odds_rotation?.[`${market}|${action}|${style}|${odds}|${rotation}`]],
    ["action_style_odds_rotation", audit.by_action_style_odds_rotation?.[`${action}|${style}|${odds}|${rotation}`]],
  ];
  const primaryLookups = [
    ["market_style_odds_rotation", audit.by_market_style_odds_rotation?.[`${market}|${style}|${odds}|${rotation}`]],
    ["style_odds_rotation_rank", audit.by_style_odds_rotation_rank?.[`${style}|${odds}|${rotation}|${rank}`]],
    ["filter_style_odds", audit.by_filter_style_odds?.[`${filterName}|${style}|${odds}`]],
    ["style_odds_rotation", audit.by_style_odds_rotation?.[`${style}|${odds}|${rotation}`]],
    ["style_odds", audit.by_style_odds?.[`${style}|${odds}`]],
    ["style", audit.by_style?.[style]],
  ];
  // An alternate must earn alternate-specific evidence. Falling back to the
  // primary-card audit would recreate the selection-bias leak this layer fixes.
  const lookups = [...actionLookups, ...(action === "build_best" ? primaryLookups : [])]
    .filter(([, evidence]) => evidence && Number(evidence.samples || 0) > 0);
  const minimum = Number(policy.minimum_build_selection_samples ?? 20);
  const qualified = lookups.find(([, evidence]) => Number(evidence.samples || 0) >= minimum);
  const fallback = lookups[0] || [null, null];
  const [level, evidence] = qualified || fallback;
  return { level, evidence, qualified: Boolean(qualified), minimumSamples: minimum };
}

export function applyBuildSelectionCalibration(candidate, policy = {}, options = {}) {
  const base = clamp(candidate?.preProcessProbability ?? candidate?.robustProbability ?? candidate?.recommendationProbability ?? .5, .01, .99);
  const process = buildSelectionProcessEvidence(candidate, policy, options);
  const samples = Number(process.evidence?.samples || 0);
  let probability;
  if (process.qualified) {
    const multiplier = clamp(process.evidence?.confidence_multiplier ?? .5, .5, 1);
    probability = .5 + (base - .5) * multiplier;
    const lower = Number(process.evidence?.lower_bound);
    if (Number.isFinite(lower)) probability = Math.min(probability, probability * .35 + Math.max(.5, lower) * .65);
  } else if (Number.isFinite(Number(candidate?.sportsbookProbability))) {
    const sparseWeight = clamp(policy.sparse_selection_sportsbook_weight ?? .75, 0, 1);
    const sportsbookWeight = sparseWeight * (1 - Math.min(1, samples / Math.max(1, process.minimumSamples)));
    probability = base * (1 - sportsbookWeight) + Number(candidate.sportsbookProbability) * sportsbookWeight;
  } else {
    const edgeMultiplier = clamp(policy.sparse_selection_edge_multiplier ?? .5, 0, 1);
    probability = .5 + (base - .5) * edgeMultiplier;
  }
  return {
    ...candidate,
    candidateRank: Number(options.candidateRank || 1),
    preProcessProbability: base,
    processProbability: clamp(probability, .01, .99),
    robustProbability: clamp(probability, .01, .99),
    postSelectionEvidence: process,
  };
}

export function expectedPlayerPropValue(prop) {
  const thresholds = (prop?.thresholds || []).map(row => ({
    line: Number(row?.line), probability: Number(row?.over_probability),
  })).filter(row => Number.isFinite(row.line) && Number.isFinite(row.probability))
    .sort((a, b) => a.line - b.line);
  if (!thresholds.length) return Number.isFinite(Number(prop?.recent_10_average))
    ? Number(prop.recent_10_average) : null;
  let implied = null;
  for (let index = 1; index < thresholds.length; index += 1) {
    const lower = thresholds[index - 1];
    const upper = thresholds[index];
    if ((lower.probability - .5) * (upper.probability - .5) <= 0
      && lower.probability !== upper.probability) {
      const share = (.5 - lower.probability) / (upper.probability - lower.probability);
      implied = lower.line + share * (upper.line - lower.line);
      break;
    }
  }
  if (implied == null) {
    const closest = thresholds.reduce((best, row) => (
      Math.abs(row.probability - .5) < Math.abs(best.probability - .5) ? row : best
    ));
    implied = closest.line + (closest.probability - .5) * 2;
  }
  const recent = Number(prop?.recent_10_average);
  return Number.isFinite(recent) ? implied * .7 + recent * .3 : implied;
}

export function playerPropLineClearance(candidate) {
  const expectedValue = expectedPlayerPropValue(candidate?.prop);
  const line = Number(candidate?.line?.line ?? candidate?.line);
  if (!Number.isFinite(expectedValue) || !Number.isFinite(line)) {
    return { expectedValue: null, rawClearance: 0, normalizedClearance: 0 };
  }
  const rawClearance = candidate?.side === "under" ? line - expectedValue : expectedValue - line;
  return {
    expectedValue,
    rawClearance,
    normalizedClearance: rawClearance / Math.max(1, Math.sqrt(Math.abs(expectedValue) + .5)),
  };
}

export function playerPropFragility(candidate, policy = {}) {
  const player = candidate?.player || {};
  const prop = candidate?.prop || {};
  const line = Number(candidate?.line?.line ?? candidate?.line);
  const recent = Number(prop?.recent_10_average);
  const clearance = playerPropLineClearance(candidate);
  const reasons = [];
  let penalty = 0;
  const status = String(player?.lineup_status || "").toLowerCase();
  if (status !== "confirmed") {
    const value = player?.kind === "pitcher" && status === "probable" ? .01 : .025;
    penalty += value; reasons.push("participant_not_confirmed");
  }
  if (player?.kind === "batter" && !player?.opponent_starter_id) {
    penalty += .015; reasons.push("opposing_starter_unconfirmed");
  }
  if (player?.kind === "pitcher" && String(player?.opponent_lineup_status || "").toLowerCase() !== "confirmed") {
    penalty += .015; reasons.push("opponent_lineup_projected");
  }
  const lineupSlot = Number(player?.lineup_slot || 0);
  if (player?.kind === "batter" && prop?.prop === "rbi" && candidate?.side === "under"
    && line <= .5 && lineupSlot >= 3 && lineupSlot <= 5) {
    penalty += .04; reasons.push("middle_order_rbi_under");
  }
  if (player?.kind === "batter" && prop?.prop === "walks" && candidate?.side === "under" && line <= .5) {
    if (Number.isFinite(recent) && recent >= .45) {
      penalty += .04; reasons.push("high_walk_rate_under");
    } else if (Number.isFinite(recent) && recent >= .3) {
      penalty += .02; reasons.push("moderate_walk_rate_under");
    }
  }
  if (player?.kind === "pitcher" && prop?.prop === "strikeouts" && candidate?.side === "over") {
    if (clearance.rawClearance <= 0) {
      penalty += .06; reasons.push("pitcher_k_projection_below_line");
    } else if (clearance.rawClearance < .5) {
      penalty += .04; reasons.push("pitcher_k_thin_clearance");
    } else if (clearance.rawClearance < 1) {
      penalty += .02; reasons.push("pitcher_k_limited_clearance");
    }
  }
  if (!Number.isFinite(Number(candidate?.sportsbookProbability))) {
    penalty += Number(policy.unpaired_price_fragility_penalty ?? .015);
    reasons.push("unpaired_sportsbook_price");
  }
  return { penalty, reasons, ...clearance };
}

export function applyWithinGameReranking(candidate, policy = {}) {
  const probability = Number(candidate?.processProbability
    ?? candidate?.robustProbability ?? candidate?.recommendationProbability ?? .5);
  const fragility = playerPropFragility(candidate, policy);
  const book = Number(candidate?.sportsbookProbability);
  const disagreement = Number.isFinite(book) ? Math.abs(probability - book) : 0;
  const clearanceWeight = Number(policy.line_clearance_ranking_weight ?? .035);
  const disagreementWeight = Number(policy.sportsbook_disagreement_ranking_weight ?? .35);
  const shadowRerankScore = probability
    + clearanceWeight * Math.max(-1.5, Math.min(1.5, fragility.normalizedClearance))
    - fragility.penalty
    - disagreementWeight * disagreement;
  const rerankerPromoted = policy.reranker_promoted === true;
  const rerankScore = rerankerPromoted ? shadowRerankScore : probability;
  return {
    ...candidate,
    rerankScore,
    shadowRerankScore,
    rerankerPromoted,
    expectedValue: fragility.expectedValue,
    rawLineClearance: fragility.rawClearance,
    normalizedLineClearance: fragility.normalizedClearance,
    fragilityPenalty: fragility.penalty,
    fragilityReasons: fragility.reasons,
    sportsbookDisagreement: disagreement,
    rerankerVersion: policy.reranker_version || "within_game_v1",
  };
}

export function rerankWithinGameCandidates(candidates, policy = {}) {
  return (candidates || []).map(candidate => applyWithinGameReranking(candidate, policy))
    .sort((a, b) => Number(b.rerankScore) - Number(a.rerankScore)
      || Number(b.processProbability ?? b.robustProbability) - Number(a.processProbability ?? a.robustProbability))
    .map((candidate, index) => ({ ...candidate, withinGameRank: index + 1 }));
}

export function noVigSportsbookProbability(threshold, side) {
  const prices = {};
  for (const value of ["over", "under"]) {
    const selections = threshold?.melbet_selections?.[value] || [];
    const best = Math.max(...selections.map(row => Number(row.decimal_odds)).filter(odds => odds > 1));
    if (Number.isFinite(best)) prices[value] = best;
  }
  if (!prices.over || !prices.under || !prices[side]) return null;
  const over = 1 / prices.over;
  const under = 1 / prices.under;
  return (1 / prices[side]) / (over + under);
}

export function passesSportsbookDisagreementGuard(
  probability,
  sportsbookProbability,
  tolerance = 0.15,
  requireSportsbookProbability = false,
) {
  if (sportsbookProbability == null || !Number.isFinite(Number(sportsbookProbability))) {
    return !requireSportsbookProbability;
  }
  return Number(probability) - Number(sportsbookProbability) <= Number(tolerance);
}

export function automaticMarketKey(player, prop) {
  return `${player?.kind || "player"}:${prop?.prop || "unknown"}`;
}

export function playerPropMarketKey(kind, prop) {
  return `${kind || "player"}:${prop || "unknown"}`;
}

export function playerPropMarketSelected(selectedMarkets, kind, prop) {
  const selected = selectedMarkets instanceof Set ? selectedMarkets : new Set(selectedMarkets || []);
  return selected.has(playerPropMarketKey(kind, prop)) || selected.has(prop);
}

export function normalizePlayerPropBuildSide(value, fallback = "both") {
  const normalizedFallback = ["over", "under"].includes(fallback) ? fallback : "both";
  return ["both", "over", "under"].includes(value) ? value : normalizedFallback;
}

export function playerPropBuildSide(preferences, kind, prop, recommendedSide, fallback = "both") {
  const marketKey = playerPropMarketKey(kind, prop);
  const preference = normalizePlayerPropBuildSide(
    preferences?.[marketKey] ?? preferences?.[prop],
    fallback,
  );
  if (preference !== "both") return preference;
  return ["over", "under"].includes(recommendedSide) ? recommendedSide : "over";
}

export function normalizePlayerPropMarkets(selectedMarkets, availableMarkets) {
  const available = [...new Set(availableMarkets || [])];
  const availableSet = new Set(available);
  const normalized = new Set();
  for (const value of selectedMarkets || []) {
    if (availableSet.has(value)) {
      normalized.add(value);
      continue;
    }
    if (!String(value).includes(":")) {
      for (const market of available) if (market.endsWith(`:${value}`)) normalized.add(market);
    }
  }
  return [...normalized];
}

export const strongestPlayerPropMarkets = Object.freeze([
  { kind: "pitcher", prop: "strikeouts", side: "over", label: "Pitcher strikeouts · Over" },
  { kind: "batter", prop: "rbi", side: "under", label: "Batter RBIs · Under" },
  { kind: "batter", prop: "walks", side: "under", label: "Batter walks · Under" },
  { kind: "batter", prop: "total_bases", side: "under", label: "Batter total bases · Under" },
  { kind: "batter", prop: "hits_runs_rbi", side: "over", label: "Hits + runs + RBIs · Over" },
  { kind: "batter", prop: "runs", side: "under", label: "Batter runs · Under" },
  { kind: "batter", prop: "strikeouts", side: "over", label: "Batter strikeouts · Over" },
]);

export function strongestPlayerPropSide(kind, prop) {
  return strongestPlayerPropMarkets.find(market => market.kind === kind && market.prop === prop)?.side || null;
}

export function automaticMarketRule(policy, player, prop) {
  return policy?.market_rules?.[automaticMarketKey(player, prop)] || null;
}

export function automaticThresholdCandidates(
  thresholds,
  side,
  historyGames,
  marketRule,
  isSideAvailable = () => true,
  policy = {},
  options = {},
) {
  if ((marketRule?.blocked_sides || []).includes(side)) return [];
  return (thresholds || []).filter(line => isSideAvailable(line, side)).map(line => {
    const probability = Number(line?.[`${side}_probability`]);
    const adjusted = robustRecommendationProbability(
      probability,
      historyGames,
      marketRule,
      side,
      line?.line,
      policy,
    );
    const sportsbookProbability = noVigSportsbookProbability(line, side);
    const sweep = options.sweep === true;
    const exactEvidenceEligible = adjusted.evidence.exactEligible
      || adjusted.evidence.selectionEligible
      || adjusted.evidence.pricedEligible;
    const exactEvidenceRequired = sweep
      && policy.lower_confidence_lines_manual_only !== false;
    const sportsbookTolerance = sweep
      ? policy.sweep_sportsbook_disagreement_tolerance
        ?? policy.sportsbook_disagreement_tolerance
        ?? 0.10
      : policy.sportsbook_disagreement_tolerance ?? 0.15;
    return {
      line,
      side,
      probability,
      ...adjusted,
      sportsbookProbability,
      exactEvidenceEligible,
      automaticEligible: !exactEvidenceRequired || exactEvidenceEligible,
      sportsbookEligible: passesSportsbookDisagreementGuard(
        adjusted.robustProbability,
        sportsbookProbability,
        sportsbookTolerance,
        sweep && policy.sweep_requires_paired_prices !== false,
      ),
    };
  }).filter(candidate => candidate.automaticEligible && candidate.sportsbookEligible);
}

export function playerPropCandidateKey(candidate) {
  return `${candidate?.game?.game_id}:${candidate?.player?.player_id}:${candidate?.prop?.prop}`;
}

const marketSideKey = candidate => `${candidate?.player?.kind}:${candidate?.prop?.prop}:${candidate?.side}`;

export function playerPropExposureKey(candidate) {
  return [
    candidate?.game?.game_id ?? candidate?.game_id,
    candidate?.player?.player_id ?? candidate?.player_id,
    candidate?.prop?.prop ?? candidate?.propKey ?? candidate?.prop,
    candidate?.side,
    Number(candidate?.line?.line ?? candidate?.line),
  ].join(":");
}

export function playerPropPortfolioContextKey(candidate) {
  return [
    candidate?.game?.game_id ?? candidate?.game_id,
    candidate?.player?.team_id ?? candidate?.team_id ?? "team",
    candidate?.side,
  ].join(":");
}

export function candidateReliabilityTier(candidate, policy = {}) {
  const exactLower = candidate?.evidence?.exactEligible
    ? Number(candidate?.evidence?.exact?.lower_bound)
    : NaN;
  const selectionLower = candidate?.evidence?.selectionEligible
    ? Number(candidate?.evidence?.selection?.lower_bound)
    : NaN;
  const eligibleBounds = [exactLower, selectionLower].filter(Number.isFinite);
  const auditedLower = eligibleBounds.length ? Math.min(...eligibleBounds) : null;
  const marketAccuracy = Number(candidate?.marketRule?.accuracy);
  const marketBrier = Number(candidate?.marketRule?.brier);
  const tierALower = Number(policy.tier_a_lower_bound ?? 0.65);
  const tierAMarketAccuracy = Number(policy.tier_a_market_accuracy ?? 0.75);
  const tierAMarketBrier = Number(policy.tier_a_market_brier ?? 0.20);
  if ((auditedLower != null && auditedLower >= tierALower)
    || (Number.isFinite(marketAccuracy) && marketAccuracy >= tierAMarketAccuracy
      && Number.isFinite(marketBrier) && marketBrier <= tierAMarketBrier)) return "A";
  if (candidate?.exactEvidenceEligible
    || candidate?.evidence?.exactEligible
    || candidate?.evidence?.selectionEligible
    || (Number.isFinite(marketAccuracy) && marketAccuracy >= Number(policy.tier_b_market_accuracy ?? 0.65))) return "B";
  return "probation";
}

export function selectDiversifiedCandidates(candidates, target, policy = {}, sweep = false, options = {}) {
  const wanted = Math.max(1, Number(target) || 1);
  const selected = [];
  const games = new Set();
  const markets = new Map();
  const remaining = [...(candidates || [])];
  const priorExposure = options.priorExposureKeys instanceof Set
    ? options.priorExposureKeys
    : new Set(options.priorExposureKeys || []);
  const diversityPenalty = Number(policy.market_side_repeat_penalty ?? 0.025);
  const reusePenalty = options.avoidPriorExposure === false
    ? 0
    : Number(policy.cross_card_reuse_penalty ?? 0.25);
  const priorContextExposure = options.priorContextExposureKeys instanceof Set
    ? options.priorContextExposureKeys
    : new Set(options.priorContextExposureKeys || []);
  const contextReusePenalty = options.avoidPriorExposure === false
    ? 0
    : Number(policy.portfolio_context_reuse_penalty ?? 0.08);
  const hardMarketLimit = sweep
    ? Number(policy.sweep_market_side_maximum ?? 2)
    : Number(policy.balanced_market_side_maximum ?? 3);
  const tierLimit = tier => {
    if (tier === "A") return hardMarketLimit;
    if (tier === "B") return sweep
      ? Math.min(hardMarketLimit, Number(policy.sweep_tier_b_maximum ?? 2))
      : Math.min(hardMarketLimit, Number(policy.balanced_tier_b_maximum ?? 3));
    return sweep
      ? Math.min(hardMarketLimit, Number(policy.sweep_probation_maximum ?? 1))
      : Math.min(hardMarketLimit, Number(policy.balanced_probation_maximum ?? 2));
  };
  while (selected.length < wanted) {
    const eligible = remaining.filter(candidate => {
      const gameId = String(candidate?.game?.game_id ?? "");
      const market = marketSideKey(candidate);
      return !games.has(gameId)
        && Number(markets.get(market) || 0) < tierLimit(candidateReliabilityTier(candidate, policy));
    });
    if (!eligible.length) break;
    eligible.sort((a, b) => {
      const score = candidate => Number(candidate.rerankScore ?? candidate.robustProbability ?? candidate.recommendationProbability)
        - Number(markets.get(marketSideKey(candidate)) || 0) * diversityPenalty
        - (priorExposure.has(playerPropExposureKey(candidate)) ? reusePenalty : 0)
        - (priorContextExposure.has(playerPropPortfolioContextKey(candidate)) ? contextReusePenalty : 0);
      return score(b) - score(a)
        || Number(b.recommendationProbability) - Number(a.recommendationProbability);
    });
    const candidate = eligible[0];
    selected.push(candidate);
    games.add(String(candidate?.game?.game_id ?? ""));
    const market = marketSideKey(candidate);
    markets.set(market, Number(markets.get(market) || 0) + 1);
    remaining.splice(remaining.indexOf(candidate), 1);
  }
  return selected;
}

export function nextSameGameAlternate(candidates, leg, selectedKeys = new Set(), usedKeys = new Set(), selected = []) {
  const gameId = String(leg?.game_id ?? leg?.game?.game_id ?? "");
  const exposure = new Map();
  for (const candidate of selected || []) {
    const key = marketSideKey(candidate);
    exposure.set(key, Number(exposure.get(key) || 0) + 1);
  }
  return (candidates || []).filter(candidate => {
    const key = playerPropCandidateKey(candidate);
    return String(candidate?.game?.game_id ?? "") === gameId
      && !selectedKeys.has(key)
      && !usedKeys.has(key);
  }).sort((a, b) => {
    const score = candidate => Number(candidate.rerankScore ?? candidate.robustProbability ?? candidate.recommendationProbability)
      - Number(exposure.get(marketSideKey(candidate)) || 0) * 0.025;
    return score(b) - score(a);
  })[0] || null;
}

export function saferSamePropLine(candidates, leg) {
  const gameId = String(leg?.game_id ?? "");
  const playerId = String(leg?.player_id ?? "");
  const currentLine = Number(leg?.line);
  const side = String(leg?.side || "");
  return (candidates || []).filter(candidate =>
    String(candidate?.game?.game_id ?? "") === gameId
    && String(candidate?.player?.player_id ?? "") === playerId
    && candidate?.prop?.prop === (leg?.propKey ?? leg?.prop)
    && candidate?.side === side
    && (side === "under" ? Number(candidate?.line?.line) > currentLine : Number(candidate?.line?.line) < currentLine))
    .sort((a, b) => side === "under"
      ? Number(b.line.line) - Number(a.line.line)
      : Number(a.line.line) - Number(b.line.line))[0] || null;
}

export function recommendationCutoffFloor(value, fallback = 0.65) {
  if (value === "ignore") return 0;
  const cutoff = Number(value);
  return Number.isFinite(cutoff) && cutoff >= 0 && cutoff <= 1 ? cutoff : fallback;
}
