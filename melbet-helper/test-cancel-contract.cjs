const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { randomUUID } = require("node:crypto");

const runtimeListeners = [];
const stored = {};
const sentToTabs = [];
const detached = [];
const clearedAlarms = [];
const updatedTabs = [];
const createdTabs = [];
let queriedTabs = [];
const event = () => ({ addListener(listener) { this.listeners ||= []; this.listeners.push(listener); } });
const chrome = {
  runtime: { onInstalled: event(), onMessage: { addListener: (listener) => runtimeListeners.push(listener) } },
  storage: { session: {
    async set(values) { Object.assign(stored, values); },
    async get(key) { return key == null ? { ...stored } : { [key]: stored[key] }; },
    async remove(key) { delete stored[key]; },
  } },
  tabs: {
    onUpdated: event(),
    async query() { return queriedTabs; },
    async reload() {},
    async create(options) { createdTabs.push(options); return { id: 44, ...options }; },
    async update(tabId, options) { updatedTabs.push({ tabId, options }); return { id: tabId, ...options }; },
    async sendMessage(tabId, message) { sentToTabs.push({ tabId, message }); },
  },
  alarms: {
    onAlarm: event(),
    async create() {},
    async clear(name) { clearedAlarms.push(name); return true; },
    async getAll() { return [{ name: "ninth-fallback:session-test:44" }]; },
  },
  debugger: {
    async attach() {}, async sendCommand() {},
    async detach(target) { detached.push(target); },
  },
};

const scriptContext = vm.createContext({
  chrome, crypto: { randomUUID: () => "session-test" }, URL, URLSearchParams,
  setTimeout, clearTimeout, Promise, Date, Number, String, Boolean, Set, console,
});
vm.runInContext(fs.readFileSync(require.resolve("./service-worker.js"), "utf8"), scriptContext);

const supportedProps = vm.runInContext(`[
  "outs", "strikeouts", "hits_allowed", "walks", "home_runs", "runs",
  "hits", "total_bases", "singles", "doubles", "triples", "rbi",
  "hits_runs_rbi", "stolen_bases", "win",
].map((prop) => canonicalProp(prop))`, scriptContext);
assert.equal(JSON.stringify(supportedProps), JSON.stringify([
  "outs", "strikeouts", "hits_allowed", "walks", "home_runs", "runs",
  "hits", "total_bases", "singles", "doubles", "triples", "rbi",
  "hits_runs_rbi", "stolen_bases", "win",
]));
const allPlayerEntriesValid = vm.runInContext(`[
  "outs", "strikeouts", "hits_allowed", "walks", "home_runs", "runs",
  "hits", "total_bases", "singles", "doubles", "triples", "rbi",
  "hits_runs_rbi", "stolen_bases", "win",
].every((prop) => isValidEntry({
  url: "https://mel-bet.et/event", automation: {
    kind: "player_prop", eventId: "123", player: "Test Player",
    prop, marketLabel: prop, side: "over", line: 0.5,
  },
}))`, scriptContext);
assert.equal(allPlayerEntriesValid, true);
assert.equal(vm.runInContext("shouldReconnectTab('http://192.168.1.9:5173/props-builder')", scriptContext), true);

function dispatch(message, sender = { tab: { id: 7 }, url: "http://localhost:5173/props-builder" }) {
  return new Promise((resolve, reject) => {
    let handled = false;
    for (const listener of runtimeListeners) {
      const result = listener(message, sender, (response) => resolve(response));
      handled ||= result === true;
    }
    if (!handled) reject(new Error(`No listener handled ${message.type}`));
  });
}

(async () => {
  queriedTabs = [{
    id: 44,
    url: "https://mel-bet.et/en/line/baseball/166775-usa-mlb/123-test#ninth-bootstrap=request-test",
  }];
  const created = await dispatch({
    type: "NINTH_CREATE_MELBET_SESSION", requestId: "request-test",
    payload: { entries: [{
      key: "one", game: "Away at Home", selection: "Aaron Judge Over 0.5 Hits",
      url: "https://mel-bet.et/en/line/baseball/166775-usa-mlb/123-test",
      automation: {
        kind: "player_prop", eventId: "123", player: "Aaron Judge",
        melbetPlayerName: "Aaron James Judge", prop: "hits", marketLabel: "Hits",
        side: "over", line: 0.5,
      },
    }] },
  });
  assert.equal(created.ok, true);
  assert.equal(createdTabs.length, 0);
  assert.equal(updatedTabs[0].tabId, 44);
  assert.match(updatedTabs[0].options.url, /#ninth-session=session-test&step=0$/);
  assert.equal(stored["ninth:session-test"].melbetTabId, 44);
  assert.equal(stored["ninth:session-test"].entries[0].automation.melbetPlayerName, "Aaron James Judge");

  // Once the content script boots on the primary page, all later failures are
  // local workflow failures and the proxy readiness timer must be gone.
  clearedAlarms.length = 0;
  const bootstrapped = await dispatch(
    { type: "NINTH_MELBET_PAGE_BOOTSTRAPPED", id: "session-test" },
    { tab: { id: 44 }, url: updatedTabs[0].options.url },
  );
  assert.equal(bootstrapped.ok, true);
  assert.equal(clearedAlarms.includes("ninth-fallback:session-test:44"), true);
  assert.equal(stored["ninth:session-test"].primaryHostBootstrapped, true);

  // Even if a later navigation recreates an alarm, a session that has already
  // booted successfully on the primary host must never be sent to the proxy.
  const updatesBeforeAlarm = updatedTabs.length;
  const fallbackListener = chrome.alarms.onAlarm.listeners[0];
  await fallbackListener({ name: "ninth-fallback:session-test:44" });
  assert.equal(updatedTabs.length, updatesBeforeAlarm);

  // When the builder does not pre-open a bootstrap page, the extension owns
  // tab creation and creates exactly one session tab.
  queriedTabs = [];
  const payload = { entries: [{
    key: "two", game: "Away at Home", selection: "Aaron Judge Over 0.5 Hits",
    url: "https://mel-bet.et/en/line/baseball/166775-usa-mlb/123-test",
    automation: {
      kind: "player_prop", eventId: "123", player: "Aaron Judge",
      prop: "hits", marketLabel: "Hits", side: "over", line: 0.5,
    },
  }] };
  const extensionOwned = await dispatch({
    type: "NINTH_CREATE_MELBET_SESSION", requestId: "request-extension-owned", payload,
  });
  assert.equal(extensionOwned.ok, true);
  assert.equal(createdTabs.length, 1);
  assert.match(createdTabs[0].url, /#ninth-session=session-test&step=0$/);

  // Duplicate delivery of the same builder request must share one creation
  // promise instead of opening a second MelBet tab.
  const beforeDuplicate = createdTabs.length;
  const [duplicateOne, duplicateTwo] = await Promise.all([
    dispatch({ type: "NINTH_CREATE_MELBET_SESSION", requestId: "request-duplicate", payload }),
    dispatch({ type: "NINTH_CREATE_MELBET_SESSION", requestId: "request-duplicate", payload }),
  ]);
  assert.equal(duplicateOne.ok, true);
  assert.equal(duplicateTwo.ok, true);
  assert.equal(duplicateOne.sessionId, duplicateTwo.sessionId);
  assert.equal(createdTabs.length, beforeDuplicate + 1);

  const cancelled = await dispatch({ type: "NINTH_CANCEL_MELBET_SESSION", id: "session-test" });
  assert.equal(cancelled.ok, true);
  assert.equal(stored["ninth:session-test"].cancelled, true);
  assert.equal(JSON.stringify(sentToTabs.at(-1)), JSON.stringify({
    tabId: 44, message: { type: "NINTH_CANCEL_MELBET_AUTOFILL", id: "session-test" },
  }));
  assert.equal(detached.at(-1).tabId, 44);
  assert.equal(clearedAlarms.includes("ninth-fallback:session-test:44"), true);
  console.log("MelBet helper cancellation contract: OK");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
