import assert from "node:assert/strict";
import test from "node:test";
import {
  moneylineBuilderProbability,
  selectMixedCandidates,
  selectTotalsCandidates,
} from "./slipBuilderRecommendations.js";

const candidate = (game, market, probability) => ({ game: { game_id: game }, option: { market, probability } });

test("mixed selection includes an eligible total when raw ranking is all moneyline", () => {
  const selected = selectMixedCandidates([
    candidate(1, "moneyline", .72), candidate(1, "totals", .58),
    candidate(2, "moneyline", .70), candidate(2, "totals", .57),
    candidate(3, "moneyline", .69), candidate(3, "totals", .56),
    candidate(4, "moneyline", .68), candidate(4, "totals", .55),
    candidate(5, "moneyline", .67), candidate(5, "totals", .54),
  ], 5);
  assert.equal(selected.length, 5);
  assert.equal(new Set(selected.map(row => row.game.game_id)).size, 5);
  assert.ok(selected.some(row => row.option.market === "totals"));
  assert.ok(selected.some(row => row.option.market === "moneyline"));
});

test("totals selection caps repeated exact line and side without forcing the opposite side", () => {
  const rows = [1, 2, 3, 4].map((game, index) => ({
    game: { game_id: game }, option: { market: "totals", side: "over", line: 8.5, probability: .70 - index / 100 },
  }));
  rows.push({ game: { game_id: 5 }, option: { market: "totals", side: "over", line: 9.5, probability: .60 } });
  const selected = selectTotalsCandidates(rows, 5);
  assert.equal(selected.length, 3);
  assert.equal(selected.filter(row => row.option.line === 8.5).length, 2);
  assert.ok(selected.every(row => row.option.side === "over"));
});

test("mixed selection applies the same totals line-side exposure cap", () => {
  const candidates = Array.from({ length: 10 }, (_, index) => ({
    game: { game_id: String(index + 1) },
    option: index < 7
      ? { market: "totals", side: "over", line: 8.5, probability: .9 - index * .01 }
      : { market: "moneyline", side: "home", probability: .7 - index * .01 },
  }));
  const selected = selectMixedCandidates(candidates, 8);
  assert.ok(selected.filter(row => row.option.market === "totals"
    && row.option.side === "over" && row.option.line === 8.5).length <= 3);
});

test("moneyline builder uses the conservative ranking probability when supplied", () => {
  assert.equal(moneylineBuilderProbability({ recommended_probability: .64 }), .64);
  assert.equal(moneylineBuilderProbability({
    recommended_probability: .64,
    moneyline_builder_probability: .605,
  }), .605);
});
