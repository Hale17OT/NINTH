const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const couponBets = [];
const requested = [];
const documentScrolls = [];
let documentScrollOffset = 0;
class MockInput {
  constructor() {
    this._value = "";
  }
  get value() { return this._value; }
  set value(value) { this._value = value; }
  dispatchEvent() {}
  focus() {}
}
const context = {
  chrome: {
    runtime: {
      getManifest: () => ({ version: "test" }),
      sendMessage: () => Promise.resolve({}),
      onMessage: { addListener: () => {} },
      lastError: null,
    },
  },
  document: {
    querySelector: () => null,
    querySelectorAll: (selector) => selector.includes("coupon") ? couponBets : [],
    getElementById: () => null,
    documentElement: { appendChild: () => {} },
    createElement: () => ({ style: {}, querySelector: () => ({}) }),
  },
  location: { search: "", hash: "", pathname: "/en/line/baseball/test" },
  innerHeight: 800,
  window: {
    scrollBy: (_x, y) => {
      documentScrolls.push(y);
      documentScrollOffset += y;
    },
    scrollTo: () => {},
  },
  sessionStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  fetch: async (url) => {
    requested.push(url);
    const count = Number(new URL(url, "https://example.test").searchParams.get("countevents"));
    return { ok: true, json: async () => ({ Value: { EC: 2100, count } }) };
  },
  URL,
  URLSearchParams,
  HTMLInputElement: MockInput,
  InputEvent: class InputEvent {},
  Event: class Event {},
  setTimeout,
  clearTimeout,
  console,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(require.resolve("./melbet-autofill.js"), "utf8"), context);
vm.runInContext(
  "globalThis.__test = { canonicalProp, exactTarget, couponContains, fetchFeed, playerNamesMatch, isolatedGridGeometry, filterToExactMarket, marketViewportBounds, stopBeforeClick, shouldRecoverPage };",
  context,
);
const helper = context.__test;
const helperSource = fs.readFileSync(require.resolve("./melbet-autofill.js"), "utf8");

assert.match(helperSource, /closest\("article,\.dashboard-game"\)/);
assert.match(helperSource, /getAttribute\("aria-label"\)/);

const entry = (automation) => ({ automation: {
  kind: "player_prop", player: "Aaron Judge", marketLabel: "Player prop",
  ...automation,
} });
const feed = (groupId, rows) => ({ Value: { GE: [{ G: groupId, E: rows }] } });

assert.equal(helper.canonicalProp("Hits + Runs + RBIs"), "hits_runs_rbi");
assert.equal(helper.canonicalProp("Pitcher To Win"), "win");
assert.equal(helper.playerNamesMatch("Michael Taylor", "Michael A. Taylor Jr."), true);
assert.equal(helper.playerNamesMatch("J. T. Realmuto", "JT Realmuto"), true);
assert.equal(helper.playerNamesMatch("José Ramírez", "Jose Ramirez"), true);
assert.equal(helper.playerNamesMatch("Micheal Harris", "Michael Harris II"), true);
assert.equal(helper.playerNamesMatch("Michael Harris", "Michael Taylor"), false);

// MelBet may retain a viewport-sized canvas after an exact search. Long
// isolated markets use scrollHeight for rows below that viewport.
assert.equal(helper.isolatedGridGeometry(850, { row: 0, rowCount: 2 }), false);
assert.equal(helper.isolatedGridGeometry(850, { row: 20, rowCount: 21 }), true);
assert.equal(helper.isolatedGridGeometry(674, { row: 9, rowCount: 18 }, 1406), true);
assert.equal(helper.isolatedGridGeometry(1830, { row: 51, rowCount: 52 }, 1830), true);
assert.equal(helper.isolatedGridGeometry(810, { row: 32, rowCount: 65 }, 1406), true);
assert.equal(helper.isolatedGridGeometry(810, { row: 32, rowCount: 65 }, 810), false);
assert.equal(helper.isolatedGridGeometry(1000, { row: 0, rowCount: 18 }, 2400), false);
assert.equal(helper.isolatedGridGeometry(100, { row: 5, rowCount: 6 }), false);
assert.equal(helper.isolatedGridGeometry(2400, { row: 0, rowCount: 2 }), false);
assert.equal(helper.isolatedGridGeometry(0, { row: 0, rowCount: 2 }), false);

const viewportError = helper.stopBeforeClick("MelBet's filtered market is outside the browser viewport. Nothing was clicked.");
assert.equal(helper.shouldRecoverPage(viewportError), false);
assert.equal(viewportError.skipPageRecovery, true);
assert.equal(helper.shouldRecoverPage(new Error("MelBet did not finish rendering the market grid.")), true);

assert.equal(helper.exactTarget(feed(10469, [[
  { T: 13838, P: 1.5, PL: { N: "Aaron Judge" } },
]]), entry({
  prop: "singles", side: "over", line: 1.5, melbetDisplayLine: 1.5,
  melbetFormat: "over_under", melbetGroupId: 10469, melbetTypeId: 13838,
})).groupId, 10469);

assert.equal(helper.exactTarget(feed(11325, [[
  { T: 16064, P: 1.5, PL: { N: "Bryce Harper" } },
], [
  { T: 16065, P: 1.5, PL: { N: "Aaron Judge" } },
]]), entry({
  prop: "strikeouts", side: "under", line: 1.5, melbetDisplayLine: 1.5,
  melbetFormat: "over_under", melbetGroupId: 11325, melbetTypeId: 16065,
})).sideIndex, 1);

const atLeastRows = Array.from({ length: 66 }, (_, index) => ({
  T: 16129,
  P: index === 55 ? 1 : (index % 4) + 1,
  PL: { N: index === 55 ? "Andy Pages" : `Player ${index}` },
}));
const atLeastTarget = helper.exactTarget(feed(11355, [atLeastRows]), entry({
  player: "Andy Pages", melbetPlayerName: "Andy Pages",
  prop: "hits_runs_rbi", side: "over", line: 0.5, melbetDisplayLine: 1,
  melbetFormat: "at_least", melbetGroupId: 11355, melbetTypeId: 16129,
}));
assert.equal(atLeastTarget.groupId, 11355);
assert.equal(atLeastTarget.row, 11);
assert.equal(atLeastTarget.rowCount, 22);
assert.equal(atLeastTarget.sideIndex, 2);
assert.equal(atLeastTarget.columnCount, 3);
assert.equal(helper.isolatedGridGeometry(810, atLeastTarget, 1406), true);

const strikeoutLadderTarget = helper.exactTarget(feed(11357, [atLeastRows.map((market) => ({
  ...market,
  T: 16131,
}))]), entry({
  player: "Andy Pages", melbetPlayerName: "Andy Pages",
  prop: "strikeouts", side: "over", line: 0.5, melbetDisplayLine: 1,
  melbetFormat: "at_least", melbetGroupId: 11357, melbetTypeId: 16131,
}));
assert.equal(strikeoutLadderTarget.row, 11);
assert.equal(strikeoutLadderTarget.rowCount, 22);
assert.equal(strikeoutLadderTarget.sideIndex, 2);
assert.equal(helper.isolatedGridGeometry(810, strikeoutLadderTarget, 1406), true);

const pitcherListRows = Array.from({ length: 22 }, (_, index) => ({
  T: 16132,
  P: index === 17 ? 8 : (index % 12) + 1,
  PL: { N: index === 17 ? "Cam Schlittler" : `Pitcher ${index}` },
}));
const pitcherListTarget = helper.exactTarget(feed(11358, [pitcherListRows]), entry({
  player: "Cam Schlittler", melbetPlayerName: "Cam Schlittler",
  prop: "strikeouts", side: "over", line: 7.5, melbetDisplayLine: 8,
  melbetFormat: "at_least", melbetGroupId: 11358, melbetTypeId: 16132,
  melbetMarketLabel: "Pitchers. Extra Total Strikeouts",
}));
assert.equal(pitcherListTarget.row, 17);
assert.equal(pitcherListTarget.rowCount, 22);
assert.equal(pitcherListTarget.sideIndex, 0);
assert.equal(pitcherListTarget.columnCount, 1);
assert.equal(helper.isolatedGridGeometry(810, pitcherListTarget, 1406), true);

assert.equal(helper.exactTarget(feed(10711, [[
  { T: 14502, PL: { N: "Aaron Nola" } },
], [
  { T: 14503, PL: { N: "Aaron Nola" } },
]]), entry({
  player: "Aaron Nola", prop: "win", side: "under", line: 0.5,
  melbetDisplayLine: 1, melbetFormat: "yes_no",
  melbetGroupId: 10711, melbetTypeId: 14503,
})).sideIndex, 1);

assert.equal(helper.exactTarget(feed(8527, [[
  { T: 8091, P: 0.5, PL: { N: "Michael A. Taylor Jr." } },
]]), entry({
  player: "Michael Taylor", melbetPlayerName: "Michael A. Taylor Jr.",
  prop: "hits", side: "over", line: 0.5,
  melbetDisplayLine: 0.5, melbetFormat: "over_under",
  melbetGroupId: 8527, melbetTypeId: 8091,
})).row, 0);

assert.throws(() => helper.exactTarget(feed(8527, [[
  { T: 8091, P: 0.5, PL: { N: "Jake Garcia" } },
  { T: 8091, P: 0.5, PL: { N: "Jose Garcia" } },
]]), entry({
  player: "Jase Garcia", prop: "hits", side: "over", line: 0.5,
  melbetDisplayLine: 0.5, melbetFormat: "over_under",
  melbetGroupId: 8527, melbetTypeId: 8091,
})), /no longer an exact MelBet line/);

couponBets.push({ textContent: "Pitchers. To Win — Aaron Nola - No @ 1.50" });
assert.equal(helper.couponContains(entry({
  player: "Aaron Nola", prop: "win", side: "under", line: 0.5,
  melbetDisplayLine: 1, melbetFormat: "yes_no",
  melbetMarketLabel: "Pitchers. To Win", melbetSelectionName: "Aaron Nola - No",
})), true);

// Confirmation must not depend on the pre-click price. MelBet can reprice and
// replace the game-card DOM while it adds the exact event and side to the slip.
couponBets.length = 0;
couponBets.push({ textContent: "167480. USA. MLB Philadelphia Phillies - Washington Nationals 1.27 1X2: W1" });
assert.equal(helper.couponContains(entry({
  kind: "moneyline", eventId: "742007154", homeTeam: "Philadelphia Phillies",
  awayTeam: "Washington Nationals", side: "home", expectedOdds: 1.308,
})), true);

(async () => {
  const offscreenRect = () => ({
    top: 1200 - documentScrollOffset,
    bottom: 1800 - documentScrollOffset,
    left: 0,
    right: 900,
    width: 900,
    height: 600,
  });
  const offscreenCanvas = {
    getBoundingClientRect: offscreenRect,
    parentElement: { getBoundingClientRect: offscreenRect },
  };
  const viewportBounds = await helper.marketViewportBounds(offscreenCanvas);
  assert.equal(documentScrolls.length, 1);
  assert.ok(viewportBounds.top >= 100 && viewportBounds.top < context.innerHeight);
  assert.ok(viewportBounds.bottom > viewportBounds.top);

  // Regression: the canvas may become visible only after the fourth and final
  // correction. The helper must return a fresh post-scroll rectangle rather
  // than the stale bounds measured at the start of that last attempt.
  let laggedOffset = 0;
  context.window.scrollBy = () => { laggedOffset += 300; };
  const laggedRect = () => ({
    top: 1400 - laggedOffset,
    bottom: 2000 - laggedOffset,
    left: 0,
    right: 900,
    width: 900,
    height: 600,
  });
  const laggedCanvas = {
    scrollIntoView: () => {},
    getBoundingClientRect: laggedRect,
    parentElement: { getBoundingClientRect: laggedRect },
  };
  const laggedBounds = await helper.marketViewportBounds(laggedCanvas);
  assert.equal(laggedOffset, 900);
  assert.equal(laggedBounds.top, 500);
  assert.ok(laggedBounds.top < context.innerHeight - 36);

  const result = await helper.fetchFeed("123");
  assert.equal(result.Value.count, 2200);
  assert.equal(requested.length, 2);
  assert.match(requested[0], /countevents=2000/);
  assert.match(requested[1], /countevents=2200/);

  const input = new MockInput();
  const canvas = { getBoundingClientRect: () => ({ width: 900 }) };
  const container = {
    getBoundingClientRect: () => ({ height: 130 }),
    scrollHeight: 130,
    querySelector: () => canvas,
  };
  const toolbar = { querySelector: () => input };
  context.document.querySelector = (selector) => {
    if (selector === ".game-toolbar__search") return toolbar;
    if (selector === ".market-grid-canvas__container") return container;
    if (selector === "canvas.market-grid-canvas__canvas") return canvas;
    return null;
  };
  context.chrome.runtime.sendMessage = (_message, callback) => callback({ ok: true });
  assert.equal(await helper.filterToExactMarket(entry({
    prop: "hits", marketLabel: "Hits", melbetMarketLabel: "Batters. Total Hits",
  }), { row: 0, rowCount: 2 }), true);
  console.log("MelBet helper market contract: OK");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
