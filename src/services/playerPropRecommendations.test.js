import assert from "node:assert/strict";
import test from "node:test";

import {
  automaticMarketKey,
  automaticMarketRule,
  automaticThresholdCandidates,
  applyBuildSelectionCalibration,
  applyWithinGameReranking,
  buildSelectionProcessEvidence,
  candidateReliabilityTier,
  conservativeRecommendationProbability,
  exactMarketEvidence,
  historyAdjustedProbability,
  noVigSportsbookProbability,
  nextSameGameAlternate,
  normalizePlayerPropMarkets,
  passesSportsbookDisagreementGuard,
  playerPropExposureKey,
  playerPropPortfolioContextKey,
  playerPropCandidateKey,
  playerPropBuildSide,
  playerPropMarketKey,
  playerPropMarketSelected,
  recommendationCutoffFloor,
  rerankWithinGameCandidates,
  robustRecommendationProbability,
  saferSamePropLine,
  selectDiversifiedCandidates,
  strongestPlayerPropMarkets,
  strongestPlayerPropSide,
} from "./playerPropRecommendations.js";

test("history adjustment shrinks short histories toward fifty percent", () => {
  assert.equal(historyAdjustedProbability(0.8, 0), 0.716);
  assert.equal(historyAdjustedProbability(0.8, 180), 0.8);
});

test("automatic probability applies post-selection calibration shrinkage", () => {
  const adjusted = conservativeRecommendationProbability(
    0.864,
    180,
    { confidence_multiplier: 0.75 },
  );
  assert.equal(adjusted, 0.773);
});

test("market rules are addressed by player kind and prop", () => {
  const policy = { market_rules: {
    "batter:total_bases": { automatic_eligible: false },
  } };
  const player = { kind: "batter" };
  const prop = { prop: "total_bases" };
  assert.equal(automaticMarketKey(player, prop), "batter:total_bases");
  assert.equal(automaticMarketRule(policy, player, prop).automatic_eligible, false);
});

test("player prop filters keep batter and pitcher markets separate", () => {
  const selected = ["batter:strikeouts", "pitcher:walks"];
  assert.equal(playerPropMarketKey("pitcher", "strikeouts"), "pitcher:strikeouts");
  assert.equal(playerPropMarketSelected(selected, "batter", "strikeouts"), true);
  assert.equal(playerPropMarketSelected(selected, "pitcher", "strikeouts"), false);
  assert.equal(playerPropMarketSelected(selected, "pitcher", "walks"), true);
});

test("legacy unqualified filters expand to every matching participant market", () => {
  assert.deepEqual(
    normalizePlayerPropMarkets(
      ["strikeouts", "batter:hits"],
      ["batter:strikeouts", "pitcher:strikeouts", "batter:hits", "pitcher:walks"],
    ),
    ["batter:strikeouts", "pitcher:strikeouts", "batter:hits"],
  );
});

test("each selected player prop can use its own automatic build direction", () => {
  const preferences = {
    "batter:strikeouts": "over",
    "pitcher:strikeouts": "under",
    "batter:walks": "both",
  };
  assert.equal(playerPropBuildSide(preferences, "batter", "strikeouts", "under"), "over");
  assert.equal(playerPropBuildSide(preferences, "pitcher", "strikeouts", "over"), "under");
  assert.equal(playerPropBuildSide(preferences, "batter", "walks", "under"), "under");
  assert.equal(playerPropBuildSide(preferences, "batter", "runs", "over", "under"), "under");
});

test("strongest picks preset contains the seven audited market-side combinations", () => {
  assert.equal(strongestPlayerPropMarkets.length, 7);
  assert.equal(strongestPlayerPropSide("pitcher", "strikeouts"), "over");
  assert.equal(strongestPlayerPropSide("batter", "rbi"), "under");
  assert.equal(strongestPlayerPropSide("pitcher", "walks"), null);
});

test("automatic candidates use a higher ladder when the primary line misses the odds floor", () => {
  const thresholds = [
    { line: 2.5, over_probability: 0.82, over_odds: 1.08 },
    { line: 3.5, over_probability: 0.71, over_odds: 1.32 },
    { line: 4.5, over_probability: 0.59, over_odds: 1.75 },
  ];
  const candidates = automaticThresholdCandidates(
    thresholds,
    "over",
    180,
    { confidence_multiplier: 1 },
    line => line.over_odds >= 1.2,
  );

  assert.deepEqual(candidates.map(candidate => candidate.line.line), [3.5, 4.5]);
  assert.equal(candidates[0].recommendationProbability, 0.71);
});

test("exact and top-selection evidence conservatively lower an overconfident line", () => {
  const rule = {
    confidence_multiplier: 1,
    segments: { "under:1.5": { samples: 100, lower_bound: 0.67, confidence_multiplier: 1, brier: .18, accuracy: .72, mean_confidence: .74 } },
    selection_segments: { "under:1.5": { samples: 14, lower_bound: 0.53, confidence_multiplier: 0.5, brier: .23, accuracy: .60, mean_confidence: .61 } },
  };
  const result = robustRecommendationProbability(0.84, 180, rule, "under", 1.5, {
    minimum_exact_segment_samples: 30,
    minimum_selection_segment_samples: 10,
  });
  assert.equal(exactMarketEvidence(rule, "under", 1.5).key, "under:1.5");
  assert.ok(result.robustProbability < 0.65);
});

test("sportsbook guard uses paired no-vig prices and rejects material disagreement", () => {
  const threshold = { melbet_selections: {
    over: [{ decimal_odds: 2.1 }],
    under: [{ decimal_odds: 1.75 }],
  } };
  const market = noVigSportsbookProbability(threshold, "under");
  assert.ok(market > 0.5 && market < 0.6);
  assert.equal(passesSportsbookDisagreementGuard(0.8, market, 0.15), false);
  assert.equal(passesSportsbookDisagreementGuard(0.7, null, 0.10, true), false);
});

test("an adequately sampled but poorly calibrated exact line remains manual only", () => {
  const evidence = exactMarketEvidence({
    segments: {
      "over:4.5": {
        samples: 120, lower_bound: .48, confidence_multiplier: .5,
        brier: .27, accuracy: .53, mean_confidence: .66,
      },
    },
  }, "over", 4.5);
  assert.equal(evidence.exactEligible, false);
});

test("sparse exact build selections shrink toward the sportsbook", () => {
  const candidate = {
    player: { kind: "batter" }, prop: { prop: "walks" }, side: "under",
    robustProbability: .8, sportsbookProbability: .6,
  };
  const adjusted = applyBuildSelectionCalibration(candidate, {
    minimum_build_selection_samples: 20,
    sparse_selection_sportsbook_weight: .75,
    build_selection_audit: {
      by_style_odds: { "sweep|1.30": { samples: 5, confidence_multiplier: .5 } },
    },
  }, { buildStyle: "sweep", minimumOdds: "1.30", rotationDepth: 0, candidateRank: 1 });
  assert.equal(buildSelectionProcessEvidence(candidate, {
    build_selection_audit: { by_style_odds: { "sweep|1.30": { samples: 5 } } },
  }, { buildStyle: "sweep", minimumOdds: "1.30" }).qualified, false);
  assert.ok(adjusted.robustProbability < .8);
  assert.ok(adjusted.robustProbability > .6);
});

test("alternates never borrow primary-card post-selection evidence", () => {
  const candidate = {
    player: { kind: "batter" }, prop: { prop: "rbi" }, side: "under",
  };
  const evidence = buildSelectionProcessEvidence(candidate, {
    minimum_build_selection_samples: 20,
    build_selection_audit: {
      by_action_style_odds_rotation: {
        "build_best|sweep|1.30|0": { samples: 200 },
      },
      by_style_odds: { "sweep|1.30": { samples: 300 } },
    },
  }, {
    buildStyle: "sweep", minimumOdds: "1.30", selectionAction: "alternate",
  });
  assert.equal(evidence.qualified, false);
  assert.equal(evidence.evidence, null);
});

test("within-game reranker demotes fragile RBI unders and rewards line clearance", () => {
  const candidate = (prop, side, line, probability, recent, extra = {}) => ({
    game: { game_id: 1 },
    player: {
      kind: prop === "strikeouts" ? "pitcher" : "batter",
      player_id: prop, lineup_status: "confirmed", lineup_slot: 4,
      opponent_starter_id: 9, opponent_lineup_status: "confirmed",
    },
    prop: {
      prop, recent_10_average: recent,
      thresholds: [{ line, over_probability: side === "over" ? probability : 1 - probability }],
    },
    side, line: { line }, processProbability: probability,
    robustProbability: probability, sportsbookProbability: probability - .02,
    ...extra,
  });
  const fragile = candidate("rbi", "under", .5, .76, .65);
  const cleared = candidate("strikeouts", "over", 4.5, .74, 6.2);
  const ranked = rerankWithinGameCandidates([fragile, cleared], { reranker_promoted: true });
  assert.equal(ranked[0].prop.prop, "strikeouts");
  assert.ok(applyWithinGameReranking(fragile, { reranker_promoted: true }).fragilityReasons.includes("middle_order_rbi_under"));
  assert.ok(ranked[0].rawLineClearance > 0);
});

test("within-game reranker penalizes thin pitcher strikeout overs", () => {
  const candidate = {
    player: { kind: "pitcher", lineup_status: "confirmed", opponent_lineup_status: "confirmed" },
    prop: {
      prop: "strikeouts", recent_10_average: 4.6,
      thresholds: [{ line: 4.5, over_probability: .53 }],
    },
    line: { line: 4.5 }, side: "over", processProbability: .68,
    sportsbookProbability: .62,
  };
  const ranked = applyWithinGameReranking(candidate, { reranker_promoted: true });
  assert.ok(ranked.fragilityPenalty >= .04);
  assert.ok(ranked.rerankScore < candidate.processProbability);
});

test("unpromoted reranker records a shadow score without changing live order", () => {
  const candidate = {
    player: { kind: "batter", lineup_status: "confirmed", opponent_lineup_status: "confirmed" },
    prop: {
      prop: "rbi", recent_10_average: .7,
      thresholds: [{ line: .5, over_probability: .28 }],
    },
    line: { line: .5 }, side: "under", processProbability: .72,
    sportsbookProbability: .68,
  };
  const ranked = applyWithinGameReranking(candidate, { reranker_promoted: false });
  assert.equal(ranked.rerankScore, .72);
  assert.notEqual(ranked.shadowRerankScore, ranked.rerankScore);
  assert.equal(ranked.rerankerPromoted, false);
});

test("sweep candidates require exact-line evidence and paired prices", () => {
  const threshold = {
    line: 1.5, under_probability: .72,
    melbet_selections: {
      over: [{ decimal_odds: 3.0 }],
      under: [{ decimal_odds: 1.55 }],
    },
  };
  const policy = {
    lower_confidence_lines_manual_only: true,
    minimum_exact_segment_samples: 30,
    minimum_selection_segment_samples: 10,
    sweep_sportsbook_disagreement_tolerance: .10,
    sweep_requires_paired_prices: true,
  };
  assert.equal(automaticThresholdCandidates(
    [threshold], "under", 180, { confidence_multiplier: 1 },
    () => true, policy, { sweep: true },
  ).length, 0);
  const evidenced = automaticThresholdCandidates(
    [threshold], "under", 180, {
      confidence_multiplier: 1,
      segments: { "under:1.5": { samples: 35, lower_bound: .66, confidence_multiplier: 1, brier: .18, accuracy: .72, mean_confidence: .72 } },
    }, () => true, policy, { sweep: true },
  );
  assert.equal(evidenced.length, 1);
  assert.equal(evidenced[0].exactEvidenceEligible, true);
});

test("diversified selection caps repeated prop sides and keeps one leg per game", () => {
  const candidate = (gameId, prop, score) => ({
    game: { game_id: gameId }, player: { kind: "batter", player_id: gameId },
    prop: { prop }, side: "under", robustProbability: score,
  });
  const selected = selectDiversifiedCandidates([
    candidate(1, "runs", .9), candidate(2, "runs", .89), candidate(3, "runs", .88),
    candidate(4, "walks", .87), candidate(5, "rbi", .86),
  ], 5, { maximum_per_market_side: 3, maximum_market_side_share: .3 });
  assert.equal(selected.filter(row => row.prop.prop === "runs").length, 2);
  assert.equal(selected.length, 4);
});

test("hard sweep diversity caps every reliability tier at two", () => {
  const candidate = (gameId, prop, score, lowerBound = null) => ({
    game: { game_id: gameId }, player: { kind: "batter", player_id: gameId },
    prop: { prop }, side: "under", line: { line: .5 }, robustProbability: score,
    recommendationProbability: score,
    marketRule: { accuracy: .6, brier: .24 },
    evidence: lowerBound == null ? {} : {
      exactEligible: true, exact: { lower_bound: lowerBound },
    },
  });
  const proven = [candidate(1, "doubles", .90, .7), candidate(2, "doubles", .89, .7), candidate(3, "doubles", .88, .7)];
  assert.equal(candidateReliabilityTier(proven[0]), "A");
  const selected = selectDiversifiedCandidates([
    ...proven,
    candidate(4, "total_bases", .87), candidate(5, "total_bases", .86),
  ], 5, {}, true);
  assert.equal(selected.filter(row => row.prop.prop === "doubles").length, 2);
  assert.equal(selected.filter(row => row.prop.prop === "total_bases").length, 1);
});

test("portfolio context includes game, team and statistical direction", () => {
  assert.equal(playerPropPortfolioContextKey({
    game: { game_id: 7 }, player: { team_id: 8 }, side: "under",
  }), "7:8:under");
});

test("independent-card selection penalizes exact legs used on earlier cards", () => {
  const candidate = (playerId, score) => ({
    game: { game_id: 1 }, player: { kind: "batter", player_id: playerId },
    prop: { prop: "walks" }, side: "under", line: { line: .5 },
    robustProbability: score, recommendationProbability: score,
    marketRule: { accuracy: .8, brier: .15 }, evidence: {},
  });
  const first = candidate(10, .8);
  const alternate = candidate(11, .75);
  assert.equal(playerPropExposureKey(first), "1:10:walks:under:0.5");
  const selected = selectDiversifiedCandidates([first, alternate], 1, {}, false, {
    priorExposureKeys: new Set([playerPropExposureKey(first)]),
    avoidPriorExposure: true,
  });
  assert.equal(selected[0], alternate);
});

test("safer line stays on the same player, prop and side", () => {
  const candidate = line => ({ game: { game_id: 1 }, player: { player_id: 2 }, prop: { prop: "walks" }, side: "under", line: { line } });
  assert.equal(saferSamePropLine([candidate(.5), candidate(1.5), candidate(2.5)], {
    game_id: 1, player_id: 2, prop: "walks", side: "under", line: .5,
  }).line.line, 2.5);
});

test("alternate selection stays in the leg's game and takes the highest-ranked unused prop", () => {
  const candidate = (gameId, playerId, prop) => ({
    game: { game_id: gameId }, player: { player_id: playerId }, prop: { prop },
  });
  const candidates = [
    candidate(2, 201, "hits"),
    candidate(1, 101, "hits"),
    candidate(1, 102, "runs"),
  ];
  const selected = new Set([playerPropCandidateKey(candidates[1])]);

  assert.equal(
    nextSameGameAlternate(candidates, { game_id: 1 }, selected),
    candidates[2],
  );
  assert.equal(
    nextSameGameAlternate(candidates, { game_id: 1 }, selected, new Set([playerPropCandidateKey(candidates[2])])),
    null,
  );
});

test("player prop cutoff can be ignored or selected explicitly", () => {
  assert.equal(recommendationCutoffFloor("ignore"), 0);
  assert.equal(recommendationCutoffFloor("0.55"), 0.55);
  assert.equal(recommendationCutoffFloor("invalid"), 0.65);
});
