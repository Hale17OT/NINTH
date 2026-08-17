import test from "node:test";
import assert from "node:assert/strict";
import {
  buildGuaranteeCandidates,
  DEFAULT_GUARANTEE_ROBUST_FLOOR,
  guaranteeOddsFloor,
  guaranteeRobustProbability,
  isExactGuaranteePick,
  selectGuaranteeCandidates,
} from "./playerPropGuaranteeRecommendations.js";

const record = { player_id: 7, kind: "batter", prop: "hits", side: "over", line: 0.5, samples: 10, correct: 8, accuracy: .8, wilson_lower: .68, recent_10_correct: 8, recent_10_samples: 10 };
const game = (id, odds = 1.25, line = .5) => ({ game_id: id, players: [{ player_id: 7 + id, kind: "batter", name: `Player ${id}`, team_id: id, props: [{ prop: "hits", label: "Hits", thresholds: [{ line, over_probability: .72, under_probability: .28, melbet_selections: { over: [{ decimal_odds: odds, format: "over_under" }] } }] }] }] });

test("Guarantee always applies a 1.20 minimum and respects a higher selected floor", () => {
  assert.equal(guaranteeOddsFloor("all"), 1.2);
  assert.equal(guaranteeOddsFloor("1.10"), 1.2);
  assert.equal(guaranteeOddsFloor("1.50"), 1.5);
});

test("candidate requires the exact player, role, prop, side and line plus eligible live odds", () => {
  const candidateGame = game(1);
  const matching = { ...record, player_id: 8 };
  assert.equal(buildGuaranteeCandidates([candidateGame], [matching], { minimumOdds: "all" }).length, 1);
  assert.equal(buildGuaranteeCandidates([game(1, 1.19)], [matching], { minimumOdds: "all" }).length, 0);
  assert.equal(buildGuaranteeCandidates([candidateGame], [{ ...matching, line: 1.5 }], { minimumOdds: "all" }).length, 0);
  assert.equal(isExactGuaranteePick(matching, candidateGame.players[0], candidateGame.players[0].props[0], "under", { line: .5 }), false);
});

test("Guarantee excludes low-probability longshots even when their historical identity qualifies", () => {
  const candidateGame = game(1, 5.5);
  candidateGame.players[0].props[0].thresholds[0].over_probability = .21;
  const matching = {
    ...record,
    player_id: 8,
    samples: 20,
    correct: 18,
    accuracy: .9,
    wilson_lower: .82,
    recent_10_correct: 9,
  };

  assert.equal(DEFAULT_GUARANTEE_ROBUST_FLOOR, .6);
  assert.equal(buildGuaranteeCandidates([candidateGame], [matching], {
    minimumOdds: "all",
    minimumRobustProbability: null,
  }).length, 0);
  assert.equal(guaranteeRobustProbability(matching, .21), .21);
  assert.equal(buildGuaranteeCandidates([candidateGame], [matching], { minimumOdds: "all" }).length, 0);
  assert.equal(buildGuaranteeCandidates([candidateGame], [matching], {
    minimumOdds: "all",
    minimumRobustProbability: .2,
  }).length, 1);
});

test("Guarantee requires historical strength as well as today's model probability", () => {
  const candidateGame = game(1, 1.3);
  const weakHistory = {
    ...record,
    player_id: 8,
    samples: 10,
    correct: 5,
    accuracy: .5,
    wilson_lower: .32,
    recent_10_correct: 5,
  };

  assert.equal(buildGuaranteeCandidates([candidateGame], [weakHistory], { minimumOdds: "all" }).length, 0);
});

test("selection keeps one leg per game and enforces build-style market-side caps", () => {
  const games = [1, 2, 3, 4].map(id => game(id));
  const records = games.map(row => ({ ...record, player_id: row.players[0].player_id }));
  const candidates = buildGuaranteeCandidates(games, records, { minimumOdds: "all" });
  assert.equal(selectGuaranteeCandidates(candidates, 4, { sweep: true }).length, 2);
  assert.equal(selectGuaranteeCandidates(candidates, 4, { sweep: false }).length, 3);
});
