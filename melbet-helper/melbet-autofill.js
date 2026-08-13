const PROP_GROUPS = {
  outs: 10710,
  strikeouts: 2891,
  hits_allowed: 10713,
  walks: 10712,
  home_runs: 10466,
  runs: 11328,
  hits: 8527,
  total_bases: 10465,
  singles: 10469,
  doubles: 10956,
  triples: 10957,
  rbi: 10714,
  hits_runs_rbi: 11326,
  stolen_bases: 10955,
  win: 10711,
};
const PROP_SIDE_TYPES = {
  outs: { over: [14500], under: [14501] },
  strikeouts: { over: [3868, 16064], under: [3869, 16065] },
  hits_allowed: { over: [14506], under: [14507] },
  walks: { over: [14504, 16066], under: [14505, 16067] },
  home_runs: { over: [13829], under: [13830] },
  runs: { over: [16068], under: [16069] },
  hits: { over: [8091], under: [8092] },
  total_bases: { over: [13827], under: [13828] },
  singles: { over: [13838], under: [13839] },
  doubles: { over: [15214], under: [15215] },
  triples: { over: [15216], under: [15217] },
  rbi: { over: [14508], under: [14509] },
  hits_runs_rbi: { over: [16062], under: [16063] },
  stolen_bases: { over: [15212], under: [15213] },
  win: { over: [14502], under: [14503] },
};
const PROP_COUPON_LABELS = {
  outs: ["total outs"],
  strikeouts: ["strikeouts"],
  hits_allowed: ["hits allowed"],
  walks: ["walks"],
  home_runs: ["home runs"],
  runs: ["runs"],
  hits: ["hits"],
  total_bases: ["total bases"],
  singles: ["total singles", "singles"],
  doubles: ["doubles"],
  triples: ["triples"],
  rbi: ["rbi", "runs batted in"],
  hits_runs_rbi: ["hits runs and rbis", "hits runs rbi"],
  stolen_bases: ["stolen bases"],
  win: ["pitchers to win", "to win"],
};
const GROUP_GAP = 13;
const GROUP_HEADER_HEIGHT = 33;
const MARKET_ROW_HEIGHT = 34;
const FILTER_BOTTOM_GAP = 16;
const BATTER_ONE_SIDED_VISUAL_COLUMNS = 3;
const TOTAL_GROUP_ID = 17;
const TOTAL_SIDE_TYPES = { over: [9], under: [10] };
const FALLBACK_HOST = "melbet-322491.top";
const HELPER_VERSION = chrome.runtime.getManifest().version;
const PROP_ALIASES = {
  outs: "outs", total_outs: "outs", pitcher_outs: "outs",
  strikeout: "strikeouts", strikeouts: "strikeouts",
  total_strikeouts: "strikeouts", pitcher_strikeouts: "strikeouts",
  hits_allowed: "hits_allowed", pitcher_hits_allowed: "hits_allowed",
  walks: "walks", total_walks: "walks",
  home_run: "home_runs", home_runs: "home_runs",
  runs: "runs", hits: "hits", total_bases: "total_bases",
  single: "singles", singles: "singles", total_singles: "singles",
  doubles: "doubles", triple: "triples", triples: "triples", total_triples: "triples",
  rbi: "rbi", hits_runs_rbi: "hits_runs_rbi", hits_runs_rbis: "hits_runs_rbi",
  hits_runs_and_rbi: "hits_runs_rbi", hits_runs_and_rbis: "hits_runs_rbi",
  stolen_base: "stolen_bases", stolen_bases: "stolen_bases",
  win: "win", pitcher_to_win: "win", pitchers_to_win: "win",
};
const PROP_MARKET_SEARCH = {
  outs: "Pitchers. Total Outs. Players' stats",
  strikeouts: "Pitchers. Total Strikeouts. Players' stats",
  hits_allowed: "Pitchers. Total Hits Allowed. Players' stats",
  walks: "Pitchers. Total Walks Allowed. Players' stats",
  home_runs: "Batters. Total Home Runs. Players' stats",
  runs: "Batters. Total Runs. Players' stats",
  hits: "Batters. Total Hits. Players' stats",
  total_bases: "Batters. Total Bases Taken. Players' stats",
  singles: "Batters. Total Singles. Players' stats",
  doubles: "Batters. Total Doubles. Players' stats",
  triples: "Batters. Total Triples. Players' stats",
  rbi: "Batters. Total RBIs. Players' stats",
  hits_runs_rbi: "Batters. Total Hits, Runs, and RBIs. Players' stats",
  stolen_bases: "Batters. Total Stolen Bases. Players' stats",
  win: "Pitchers. To Win. Players' stats",
};

let activeSessionId = "";
const cancelledSessions = new Set();

function cancellationError() {
  const error = new Error("Autofill stopped. No more MelBet selections will be clicked.");
  error.cancelled = true;
  error.skipPageRecovery = true;
  return error;
}

function assertActive() {
  if (activeSessionId && cancelledSessions.has(activeSessionId)) throw cancellationError();
}

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "NINTH_MELBET_BOOTSTRAP_ERROR") {
    show(message.message || "NINTH could not validate this card. Return to the builder and refresh it.", "error");
    return;
  }
  if (message?.type !== "NINTH_CANCEL_MELBET_AUTOFILL") return;
  const id = String(message.id || "");
  if (id) cancelledSessions.add(id);
  show("Autofill stopped. This MelBet tab will remain open.", "done");
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const normalized = (value) => String(value || "")
  .normalize("NFKD")
  .replace(/\p{M}+/gu, "")
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, " ")
  .trim();
const playerNameParts = (value) => normalized(value).split(" ")
  .filter((part) => part && !["jr", "sr", "ii", "iii", "iv"].includes(part));
const playerIdentity = (value) => {
  const parts = playerNameParts(value);
  if (parts.length < 2) return null;
  const initialsOnly = parts.length > 2 && parts.slice(0, -1).every((part) => part.length === 1);
  return { first: initialsOnly ? parts.slice(0, -1).join("") : parts[0], last: parts.at(-1) };
};
const editDistance = (left, right) => {
  let previous = [...Array(right.length + 1).keys()];
  for (let i = 1; i <= left.length; i += 1) {
    const current = [i];
    for (let j = 1; j <= right.length; j += 1) {
      current[j] = Math.min(current[j - 1] + 1, previous[j] + 1, previous[j - 1] + (left[i - 1] === right[j - 1] ? 0 : 1));
    }
    previous = current;
  }
  return previous[right.length];
};
function playerNamesMatch(left, right) {
  if (normalized(left).replaceAll(" ", "") === normalized(right).replaceAll(" ", "")) return true;
  const wanted = playerIdentity(left);
  const offered = playerIdentity(right);
  if (!wanted || !offered || wanted.last !== offered.last || wanted.first[0] !== offered.first[0]) return false;
  if (wanted.first === offered.first) return true;
  if ((wanted.first.length === 1 || offered.first.length === 1)
      && (wanted.first.startsWith(offered.first) || offered.first.startsWith(wanted.first))) return true;
  const minimumLength = Math.min(wanted.first.length, offered.first.length);
  const allowedDistance = minimumLength >= 6 ? 2 : 1;
  return minimumLength >= 3 && editDistance(wanted.first, offered.first) <= allowedDistance;
}
const closeEnough = (left, right) => Math.abs(Number(left) - Number(right)) < 0.001;
const canonicalProp = (...values) => {
  for (const value of values) {
    const key = normalized(value).replaceAll(" ", "_");
    if (PROP_ALIASES[key]) return PROP_ALIASES[key];
  }
  return "";
};

function overlay() {
  let node = document.getElementById("ninth-melbet-helper");
  if (node) return node;
  node = document.createElement("aside");
  node.id = "ninth-melbet-helper";
  node.style.cssText = "position:fixed;z-index:2147483647;right:18px;bottom:18px;width:min(360px,calc(100vw - 36px));padding:16px 18px;background:#10130f;color:#f5f4e9;border:1px solid #a9ff5b;box-shadow:0 18px 55px #000b;font:700 12px/1.5 Arial,sans-serif;letter-spacing:.02em";
  node.innerHTML = `<b style="display:block;color:#a9ff5b;font-size:10px;letter-spacing:.14em;margin-bottom:5px">NINTH / MELBET HELPER · v${HELPER_VERSION}</b><span>Preparing selection...</span><button type="button" style="display:block;margin-top:10px;padding:7px 10px;border:1px solid #ff766f;background:transparent;color:#ff9b95;font:800 10px Arial,sans-serif;cursor:pointer">STOP AUTOFILL</button>`;
  node.querySelector("button").addEventListener("click", async () => {
    if (!activeSessionId || cancelledSessions.has(activeSessionId)) return;
    cancelledSessions.add(activeSessionId);
    show("Stopping before the next browser action...", "working");
    await extensionMessage({ type: "NINTH_CANCEL_MELBET_SESSION", id: activeSessionId }).catch(() => {});
    show("Autofill stopped. This MelBet tab will remain open.", "done");
  });
  document.documentElement.appendChild(node);
  return node;
}

function show(message, tone = "working") {
  const node = overlay();
  node.style.borderColor = tone === "error" ? "#ff766f" : tone === "done" ? "#a9ff5b" : "#f5c84c";
  node.querySelector("span").textContent = message;
}

function progress(session, state, message) {
  show(message, state === "error" ? "error" : state === "done" ? "done" : "working");
  chrome.runtime.sendMessage({
    type: "NINTH_AUTOFILL_PROGRESS",
    sourceTabId: session.sourceTabId,
    detail: { state, message },
  }).catch(() => {});
}

function parseSession() {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  const id = params.get("ninth-session");
  const step = Number(params.get("step") || 0);
  return id ? { id, step } : null;
}

function recoveryKey(request) {
  return `ninth:melbet-refresh:${request.id}:${request.step}`;
}

function stopBeforeClick(message) {
  const error = new Error(message);
  // Deterministic market/viewport validation failures are not page-readiness
  // failures. Reloading for them can arm the primary-host readiness timer and
  // incorrectly send an otherwise healthy event page to the proxy.
  error.skipPageRecovery = true;
  return error;
}

function shouldRecoverPage(error) {
  return !error?.skipPageRecovery;
}

function recoverPageOnce(session, request, message) {
  const key = recoveryKey(request);
  if (sessionStorage.getItem(key)) return false;
  sessionStorage.setItem(key, String(Date.now()));
  progress(
    session,
    "working",
    message || `MelBet did not restore the active session or market grid correctly. Refreshing this event once before retrying ${request.step + 1}/${session.entries.length}...`,
  );
  setTimeout(() => location.reload(), 500);
  return true;
}

function visible(element) {
  if (!element) return false;
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity || 1) > 0
    && rect.width > 0 && rect.height > 0;
}

function authenticationState() {
  const header = document.querySelector("header,[role='banner']");
  if (!header) return "loading";
  const controls = [...header.querySelectorAll("a,button")].filter(visible);
  const signedOut = controls.some((control) => {
    const text = normalized(control.textContent);
    const href = String(control.getAttribute("href") || "").toLowerCase();
    return /\/(registration|login)(?:$|[/?#])/.test(href)
      || ["registration", "log in", "login", "sign in"].includes(text);
  });
  if (signedOut) return "signed_out";
  if (visible(header.querySelector(".auth_dropdown_loading,[class*='auth_dropdown_loading']"))) return "loading";
  return "signed_in";
}

async function waitForAuthentication(afterRecovery = false) {
  let positiveChecks = 0;
  let signedOutChecks = 0;
  const attempts = afterRecovery ? 32 : 20;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const state = authenticationState();
    if (state === "signed_in") {
      positiveChecks += 1;
      signedOutChecks = 0;
      if (positiveChecks >= 3) return true;
    } else {
      positiveChecks = 0;
      signedOutChecks = state === "signed_out" ? signedOutChecks + 1 : 0;
      // On the first load, three stable signed-out checks are enough to invoke
      // MelBet's known refresh recovery. After that refresh, allow the account
      // header the full window to restore before stopping.
      if (!afterRecovery && signedOutChecks >= 3) return false;
    }
    await sleep(250);
  }
  return false;
}

function extensionMessage(message, timeoutMs = 12000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error("The NINTH helper background stopped responding."));
    }, timeoutMs);
    chrome.runtime.sendMessage(message, (response) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(response || {});
    });
  });
}

async function getSession(id) {
  const response = await extensionMessage({ type: "NINTH_GET_MELBET_SESSION", id });
  return response.session || null;
}

function groupRows(feed) {
  const rawGroups = Array.isArray(feed?.Value?.GE) ? feed.Value.GE : [];
  const grouped = [];
  for (const raw of rawGroups) {
    const events = Array.isArray(raw?.E) ? raw.E : [];
    if (!events.length) continue;
    // Current MelBet payloads put the market group identifier on the GE
    // container. Older payloads also repeated it on the first event row.
    const nested = events.some(Array.isArray);
    const columns = (nested ? events.filter(Array.isArray) : [events])
      .map((column) => column.flat(Infinity).filter((row) => row && typeof row === "object" && row.T != null))
      .filter((column) => column.length);
    const firstEvent = columns[0]?.[0];
    const id = Number(raw?.G ?? firstEvent?.G);
    if (!Number.isFinite(id) || !columns.length) continue;
    const previous = grouped[grouped.length - 1];
    if (previous?.id === id) previous.columns.push(...columns);
    else grouped.push({ id, columns });
  }
  return grouped;
}

function exactTarget(feed, entry) {
  const prop = canonicalProp(entry.automation.prop, entry.automation.marketLabel);
  const groupId = Number(entry.automation.melbetGroupId) || PROP_GROUPS[prop];
  if (!groupId) throw new Error(`Unsupported prop: ${entry.automation.marketLabel}.`);
  const groups = groupRows(feed);
  for (const group of groups) {
    if (group.id !== groupId) continue;
    const player = normalized(entry.automation.melbetPlayerName || entry.automation.player);
    const exactType = Number(entry.automation.melbetTypeId);
    const sideTypes = Number.isFinite(exactType) && exactType > 0
      ? [exactType]
      : (PROP_SIDE_TYPES[prop]?.[entry.automation.side] || []);
    let sideIndex = group.columns.findIndex((column) =>
      column.some((market) => sideTypes.includes(Number(market?.T))),
    );
    // Older feeds do not always expose a stable selection type ID. Their
    // visual columns remain Over then Under, so retain that as a fallback.
    if (sideIndex < 0) sideIndex = entry.automation.side === "under" ? 1 : 0;
    const column = group.columns[sideIndex];
    if (!column) throw new Error(`${entry.automation.side.toUpperCase()} is no longer listed for ${entry.automation.marketLabel}.`);
    const format = String(entry.automation.melbetFormat || "");
    const displayedLine = entry.automation.melbetDisplayLine == null
      ? Number(entry.automation.line)
      : Number(entry.automation.melbetDisplayLine);
    const eligible = column.map((market, index) => ({ market, index })).filter(({ market }) =>
      sideTypes.includes(Number(market?.T))
      && (["yes", "yes_no"].includes(format) || closeEnough(market?.P, displayedLine)));
    const exactMatches = eligible.filter(({ market }) => normalized(market?.PL?.N) === player);
    let row = exactMatches.length === 1 ? exactMatches[0].index : -1;
    if (row < 0 && !entry.automation.melbetPlayerName) {
      const matches = eligible.filter(({ market }) => playerNamesMatch(entry.automation.player, market?.PL?.N));
      if (matches.length === 1) row = matches[0].index;
    }
    if (row < 0) throw new Error(`${entry.automation.player} ${entry.automation.side.toUpperCase()} ${entry.automation.line} is no longer an exact MelBet line.`);
    const hasExactMetadata = Number.isFinite(exactType) && exactType > 0;
    const oppositeSide = entry.automation.side === "under" ? "over" : "under";
    const oppositeTypes = PROP_SIDE_TYPES[prop]?.[oppositeSide] || [];
    let oppositeIndex = group.columns.findIndex((candidate) =>
      candidate.some((market) => oppositeTypes.includes(Number(market?.T))),
    );
    if (oppositeIndex < 0) oppositeIndex = sideIndex === 0 ? 1 : 0;
    const opposite = group.columns[oppositeIndex]?.find((market) => normalized(market?.PL?.N) === player && closeEnough(market?.P, entry.automation.line));
    if (!hasExactMetadata && !opposite) throw new Error(`The paired line for ${entry.automation.player} ${entry.automation.line} changed. Nothing was clicked.`);
    let visualRow = row;
    let visualRowCount = Math.max(...group.columns.map((candidate) => candidate.length));
    let visualSideIndex = sideIndex;
    let visualColumnCount = group.columns.length;
    // MelBet's feed stores one-sided selections as one flat column. Its desktop
    // canvas balances batter lists across three columns, but pitcher strikeout
    // ladders stay in one full-width vertical list. Convert the feed index
    // before validating geometry or clicking.
    if (group.columns.length === 1 && ["at_least", "yes"].includes(format)) {
      const isPitcherList = normalized(entry.automation.melbetMarketLabel).startsWith("pitchers ");
      visualColumnCount = isPitcherList
        ? 1
        : Math.min(BATTER_ONE_SIDED_VISUAL_COLUMNS, column.length);
      visualRowCount = Math.ceil(column.length / visualColumnCount);
      visualSideIndex = Math.floor(row / visualRowCount);
      visualRow = row % visualRowCount;
    }
    return {
      contentY: GROUP_GAP + GROUP_HEADER_HEIGHT + visualRow * MARKET_ROW_HEIGHT + MARKET_ROW_HEIGHT / 2,
      groupId,
      row: visualRow,
      rowCount: visualRowCount,
      sideIndex: visualSideIndex,
      columnCount: visualColumnCount,
    };
  }
  throw new Error(`${entry.automation.marketLabel} is no longer listed for this event.`);
}

function couponContains(entry) {
  const kind = entry.automation.kind;
  const bets = [...document.querySelectorAll(".coupon-bets__bet, .coupon-bet")];
  if (kind === "moneyline") {
    const home = normalized(entry.automation.homeTeam);
    const away = normalized(entry.automation.awayTeam);
    const code = entry.automation.side === "home" ? "w1" : "w2";
    return bets.some((bet) => {
      const text = normalized(bet.textContent);
      return text.includes(home) && text.includes(away)
        && text.includes("1x2") && text.includes(code);
    });
  }
  if (kind === "totals") {
    const home = normalized(entry.automation.homeTeam);
    const away = normalized(entry.automation.awayTeam);
    const side = normalized(entry.automation.side);
    const line = Number(entry.automation.line);
    return bets.some((bet) => {
      const text = normalized(bet.textContent);
      const numbers = String(bet.textContent || "").match(/-?\d+(?:\.\d+)?/g) || [];
      return text.includes(home) && text.includes(away)
        && text.includes("total") && text.includes(side)
        && numbers.some((value) => closeEnough(value, line));
    });
  }
  const player = normalized(entry.automation.melbetPlayerName || entry.automation.player);
  const side = normalized(entry.automation.side);
  const line = entry.automation.melbetDisplayLine == null ? Number(entry.automation.line) : Number(entry.automation.melbetDisplayLine);
  const prop = canonicalProp(entry.automation.prop, entry.automation.marketLabel);
  const format = String(entry.automation.melbetFormat || "");
  const exactSelection = normalized(entry.automation.melbetSelectionName);
  const exactMarket = normalized(entry.automation.melbetMarketLabel);
  const labels = exactMarket ? [exactMarket, ...(PROP_COUPON_LABELS[prop] || [])] : (PROP_COUPON_LABELS[prop] || [normalized(entry.automation.marketLabel)]);
  return [...document.querySelectorAll(".coupon-bets__bet, .coupon-bet")].some((bet) => {
    const text = normalized(bet.textContent);
    const numbers = String(bet.textContent || "").match(/-?\d+(?:\.\d+)?/g) || [];
    if (!text.includes(player) || !labels.some((label) => text.includes(label))) return false;
    if (exactSelection && text.includes(exactSelection)) return true;
    if (format === "yes") return true;
    if (format === "yes_no") return text.includes(side === "over" ? "yes" : "no");
    if (format === "at_least") {
      return (text.includes("or more") || text.includes("at least"))
        && numbers.some((value) => closeEnough(value, line));
    }
    return text.includes(side) && numbers.some((value) => closeEnough(value, line));
  });
}

function couponBetCount() {
  return document.querySelectorAll(".coupon-bets__bet, .coupon-bet").length;
}

function moneylineControlSelected(entry, originalButton = null) {
  const expectedCode = entry.automation.side === "home" ? "w1" : "w2";
  const eventId = String(entry.automation.eventId);
  const home = normalized(entry.automation.homeTeam);
  const away = normalized(entry.automation.awayTeam);
  // MelBet replaces a game card after accepting its selection. Re-resolve the
  // current control instead of relying only on the clicked button node; that
  // original node is often detached when the price changes during the click.
  const exactContainer = [...document.querySelectorAll(`a[href*="/${eventId}-"]`)]
    .map((link) => link.closest("article,.dashboard-game"))
    .find((container) => {
      const text = normalized(container?.textContent);
      return container && text.includes(home) && text.includes(away);
    });
  const currentButton = exactContainer && [...exactContainer.querySelectorAll("button.ui-market__toggle")]
    .find((candidate) => normalized(candidate.getAttribute("aria-label")) === expectedCode
      || normalized(candidate.closest(".ui-market")?.textContent).startsWith(expectedCode));
  return [currentButton, originalButton].some((button) => {
    if (!button) return false;
    const market = button.closest(".ui-market");
    return market?.classList.contains("ui-market--toggled")
      || button.getAttribute("aria-pressed") === "true";
  });
}

async function waitForCoupon(entry, previousCount, checks = 40) {
  for (let attempt = 0; attempt < checks; attempt += 1) {
    if (couponContains(entry)) return "exact";
    if (couponBetCount() > previousCount) return "count";
    await sleep(150);
  }
  return "";
}

async function waitForMoneylineConfirmation(entry, button, previousCount, checks = 40) {
  for (let attempt = 0; attempt < checks; attempt += 1) {
    if (couponContains(entry)) return "exact";
    if (moneylineControlSelected(entry, button)) return "selected";
    if (couponBetCount() > previousCount) return "count";
    await sleep(150);
  }
  return "";
}

async function trustedWheel(x, y, deltaY) {
  assertActive();
  const response = await extensionMessage({
    type: "NINTH_MELBET_TRUSTED_WHEEL",
    sessionId: activeSessionId,
    x: Math.round(x),
    y: Math.round(y),
    deltaY: Math.round(deltaY),
  });
  if (!response.ok) throw new Error(response.error || "MelBet's market grid could not be scrolled.");
}

async function trustedClick(x, y) {
  assertActive();
  const response = await extensionMessage({
    type: "NINTH_MELBET_TRUSTED_CLICK",
    sessionId: activeSessionId,
    x: Math.round(x),
    y: Math.round(y),
  });
  if (!response.ok) {
    throw new Error(response.error || "The browser-level MelBet click could not be completed.");
  }
}

async function trustedEnter() {
  assertActive();
  const response = await extensionMessage({ type: "NINTH_MELBET_TRUSTED_ENTER", sessionId: activeSessionId });
  if (!response.ok) throw new Error(response.error || "MelBet's market search could not be submitted.");
}

function isolatedGridGeometry(height, target, contentHeight = height) {
  if (!Number.isFinite(height) || height <= 0
    || !Number.isFinite(contentHeight) || contentHeight <= 0) return false;
  const targetBottom = GROUP_GAP + GROUP_HEADER_HEIGHT
    + (target.row + 1) * MARKET_ROW_HEIGHT;
  const expectedHeight = GROUP_GAP + GROUP_HEADER_HEIGHT
    + target.rowCount * MARKET_ROW_HEIGHT + FILTER_BOTTOM_GAP;
  // Short filtered markets shrink to their feed-derived height. Long markets
  // remain virtualized: their viewport is shorter than the group and only the
  // target row must exist in the current scrollable extent. MelBet can retain a
  // stale, oversized scrollHeight after shrinking a short result, so never use
  // that value to reject an otherwise exact-height isolated market.
  const maximumIsolatedHeight = Math.max(1000, expectedHeight + 4 * MARKET_ROW_HEIGHT);
  const exactHeight = Math.abs(height - expectedHeight) <= 24;
  const retainedViewport = height > expectedHeight + 24
    && height <= expectedHeight + 4 * MARKET_ROW_HEIGHT
    && contentHeight >= targetBottom - 8;
  const virtualizedLongMarket = expectedHeight > height + 24
    && contentHeight >= targetBottom - 8;
  return height <= maximumIsolatedHeight
    && (exactHeight || retainedViewport || virtualizedLongMarket);
}

async function filterToExactMarket(entry, target) {
  const prop = canonicalProp(entry.automation.prop, entry.automation.marketLabel);
  const exactLabel = String(entry.automation.melbetMarketLabel || "").trim();
  const query = exactLabel ? `${exactLabel}. Players' stats` : PROP_MARKET_SEARCH[prop];
  if (!query) throw stopBeforeClick(`The helper has no exact MelBet market filter for ${entry.automation.marketLabel}.`);
  const toolbar = document.querySelector(".game-toolbar__search");
  if (!toolbar) throw stopBeforeClick("MelBet's market search control is unavailable.");
  let input = toolbar.querySelector("input");
  if (!input) {
    assertActive();
    toolbar.querySelector("button")?.click();
    for (let attempt = 0; attempt < 12 && !input; attempt += 1) {
      await sleep(100);
      input = toolbar.querySelector("input");
    }
  }
  if (!input) throw stopBeforeClick("MelBet's market search did not open.");
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  if (!setter) throw stopBeforeClick("MelBet's market search input changed.");
  setter.call(input, query);
  input.dispatchEvent(new InputEvent("input", {
    bubbles: true, inputType: "insertText", data: query,
  }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  input.focus();
  // Vue updates the search model on the input event, then MelBet applies it
  // only after a real Enter key. Submitting too early applies the previous
  // query, so allow one render turn before the trusted key event.
  await sleep(200);
  await trustedEnter();

  let previousHeight = null;
  let stableSamples = 0;
  let lastHeight = 0;
  let lastContentHeight = 0;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await sleep(100);
    const container = document.querySelector(".market-grid-canvas__container");
    const height = container?.getBoundingClientRect().height || 0;
    const contentHeight = Math.max(height, Number(container?.scrollHeight) || 0);
    const canvas = container?.querySelector("canvas.market-grid-canvas__canvas")
      || document.querySelector("canvas.market-grid-canvas__canvas");
    const canvasReady = (canvas?.getBoundingClientRect().width || 0) > 300;
    stableSamples = previousHeight != null && Math.abs(height - previousHeight) <= 2
      ? stableSamples + 1
      : 0;
    previousHeight = height;
    lastHeight = height;
    lastContentHeight = contentHeight;
    // Wait for the filtered renderer to settle instead of requiring its
    // height to exactly match feed-derived rows. Current MelBet layouts can
    // retain additional viewport space even though only one group is shown.
    if (attempt >= 12 && input.value === query && canvasReady
      && stableSamples >= 2 && isolatedGridGeometry(height, target, contentHeight)) {
      return true;
    }
    // Some MelBet event pages apply the previous Vue search model on the first
    // Enter even though the visible input already contains the new text.
    // A second idempotent submission applies the current exact query.
    if (attempt === 9) {
      input.focus();
      await trustedEnter();
    }
  }
  throw stopBeforeClick(
    `${entry.automation.marketLabel} could not be safely confirmed as isolated in MelBet's market grid `
    + `(viewport ${Math.round(lastHeight)}px, content ${Math.round(lastContentHeight)}px). Nothing was clicked.`,
  );
}

async function marketViewportBounds(canvas) {
  let rect;
  let parentRect;
  let top;
  let bottom;
  const desiredTop = Math.min(180, Math.max(110, Math.round(innerHeight * 0.2)));

  // Event headers can be taller than the browser viewport. First ask the
  // browser to reveal the canvas, then correct any remaining offset with
  // bounded document scrolling. Never mutate MelBet's custom canvas scrollTop.
  for (let attempt = 0; attempt < 4; attempt += 1) {
    rect = canvas.getBoundingClientRect();
    parentRect = canvas.parentElement?.getBoundingClientRect() || rect;
    top = Math.max(rect.top, parentRect.top);
    bottom = Math.min(rect.bottom, parentRect.bottom);
    if (bottom > 36 && top < innerHeight - 36 && bottom - Math.max(0, top) > 48) break;

    if (attempt === 0 && typeof canvas.scrollIntoView === "function") {
      canvas.scrollIntoView({ block: "center", inline: "nearest" });
    } else {
      const delta = top - desiredTop;
      if (Number.isFinite(delta) && Math.abs(delta) > 1) window.scrollBy(0, delta);
    }
    await sleep(250);
  }

  // The fourth correction can be the one that finally reveals the canvas.
  // Measure once more after the loop so callers never validate the stale
  // off-screen rectangle captured immediately before that final scroll.
  rect = canvas.getBoundingClientRect();
  parentRect = canvas.parentElement?.getBoundingClientRect() || rect;
  top = Math.max(rect.top, parentRect.top);
  bottom = Math.min(rect.bottom, parentRect.bottom);

  return { rect, parentRect, top, bottom };
}

async function visibleTargetPoint(canvas, target) {
  // The market uses a fixed viewport canvas and a wheel-driven renderer.
  // DOM scrollTop manipulation moves the canvas itself and blanks the rows.
  const bounds = await marketViewportBounds(canvas);
  let rect = bounds.rect;
  const probeTop = Math.max(0, bounds.top) + 12;
  const probeBottom = Math.min(innerHeight, bounds.bottom) - 12;
  const probeXs = [0.45, 0.25, 0.75].map((ratio) => rect.left + rect.width * ratio);
  const probeYs = [
    (probeTop + probeBottom) / 2,
    probeTop + Math.min(28, Math.max(0, probeBottom - probeTop)),
    probeBottom - Math.min(28, Math.max(0, probeBottom - probeTop)),
  ];
  let wheelPoint = null;
  for (const y of probeYs) {
    for (const x of probeXs) {
      if (probeBottom > probeTop && document.elementFromPoint(x, y) === canvas) {
        wheelPoint = { x, y };
        break;
      }
    }
    if (wheelPoint) break;
  }
  if (!wheelPoint) {
    if (probeBottom <= probeTop) {
      throw stopBeforeClick("MelBet's filtered market is outside the browser viewport. Nothing was clicked.");
    }
    // The wheel reset cannot select a bet. MelBet sometimes places a
    // transparent renderer layer above the visible canvas, so use the
    // verified content bounds here and reserve strict elementFromPoint
    // validation for the final selection click below.
    wheelPoint = {
      x: rect.left + rect.width * 0.45,
      y: (probeTop + probeBottom) / 2,
    };
  }
  const wheelX = wheelPoint.x;
  const wheelY = wheelPoint.y;
  // Always return MelBet's retained custom renderer to its first row.
  await trustedWheel(wheelX, wheelY, -100000);
  await sleep(350);

  rect = canvas.getBoundingClientRect();
  const contentHeight = Math.max(rect.height, canvas.parentElement?.getBoundingClientRect().height || rect.height);
  const visibleBottom = Math.min(rect.height - 35, innerHeight - rect.top - 45);
  const desiredWithin = Math.max(80, Math.min(220, visibleBottom));
  const maximumOffset = Math.max(0, contentHeight - rect.height);
  const requestedOffset = Math.min(Math.max(0, target.contentY - desiredWithin), maximumOffset);
  if (requestedOffset > 0) {
    await trustedWheel(wheelX, wheelY, requestedOffset);
    await sleep(400);
  }
  const yWithin = target.contentY - requestedOffset;
  let targetY = rect.top + yWithin;
  const safeTop = 130;
  const safeBottom = innerHeight - 45;
  if (targetY < safeTop || targetY > safeBottom) {
    const desiredY = Math.min(safeBottom - 20, Math.max(safeTop + 20, 240));
    window.scrollBy(0, targetY - desiredY);
    await sleep(250);
    rect = canvas.getBoundingClientRect();
    targetY = rect.top + yWithin;
  }
  return {
    x: rect.left + rect.width * ((target.sideIndex + 0.5) / Math.max(2, target.columnCount || 2)),
    y: targetY,
  };
}

async function waitForCanvas() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const canvas = document.querySelector("canvas.market-grid-canvas__canvas");
    if (canvas && canvas.getBoundingClientRect().width > 300) return canvas;
    await sleep(250);
  }
  throw new Error("MelBet did not finish rendering the market grid.");
}

async function fetchFeed(eventId) {
  const request = async (count) => {
    const url = `/service-api/LineFeed/GetGameZip?id=${encodeURIComponent(eventId)}&lng=en&cfview=0&isSubGames=true&GroupEvents=true&countevents=${count}&partner=1&country=87`;
    const response = await fetch(url, { credentials: "include", cache: "no-store" });
    if (!response.ok) throw new Error(`MelBet market validation failed (${response.status}).`);
    return response.json();
  };
  let feed = await request(2000);
  const advertised = Number(feed?.Value?.EC || feed?.EC || 0);
  if (advertised > 2000) feed = await request(Math.ceil(advertised + 100));
  return feed;
}

function exactTotalTarget(feed, entry) {
  const group = groupRows(feed).find((candidate) => candidate.id === TOTAL_GROUP_ID);
  if (!group) throw new Error("The Regular time Total market is no longer listed for this event.");
  const side = entry.automation.side;
  const sideTypes = TOTAL_SIDE_TYPES[side] || [];
  let sideIndex = group.columns.findIndex((column) =>
    column.some((market) => sideTypes.includes(Number(market?.T))),
  );
  if (sideIndex < 0) sideIndex = side === "under" ? 1 : 0;
  const column = group.columns[sideIndex];
  const row = column?.findIndex((market) => closeEnough(market?.P, entry.automation.line)) ?? -1;
  if (row < 0) {
    throw new Error(`${side.toUpperCase()} ${entry.automation.line} is no longer an exact MelBet Regular time total.`);
  }
  const oppositeSide = side === "under" ? "over" : "under";
  let oppositeIndex = group.columns.findIndex((candidate) =>
    candidate.some((market) => TOTAL_SIDE_TYPES[oppositeSide].includes(Number(market?.T))),
  );
  if (oppositeIndex < 0) oppositeIndex = sideIndex === 0 ? 1 : 0;
  const opposite = group.columns[oppositeIndex]?.find((market) =>
    closeEnough(market?.P, entry.automation.line),
  );
  if (!opposite) {
    throw new Error(`The paired Regular time total ${entry.automation.line} changed. Nothing was clicked.`);
  }
  return {
    contentY: GROUP_GAP + GROUP_HEADER_HEIGHT + row * MARKET_ROW_HEIGHT + MARKET_ROW_HEIGHT / 2,
    groupId: TOTAL_GROUP_ID,
    row,
    rowCount: Math.max(...group.columns.map((candidate) => candidate.length)),
    sideIndex,
    columnCount: group.columns.length,
  };
}

async function activateRegularTimeTotals() {
  let input = null;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    input = [...document.querySelectorAll('input[type="radio"]')]
      .find((candidate) => candidate.name === "Total");
    if (input) break;
    await sleep(250);
  }
  if (!input) throw new Error("MelBet's Regular time Total tab is unavailable.");
  if (!input.checked) {
    assertActive();
    input.click();
  }
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await sleep(100);
    const canvas = document.querySelector("canvas.market-grid-canvas__canvas");
    if (input.checked && canvas && canvas.parentElement?.getBoundingClientRect().height > 0) return canvas;
  }
  throw new Error("MelBet did not finish opening the Regular time Total market.");
}

async function moneylineArticle(entry) {
  const eventId = String(entry.automation.eventId);
  const home = normalized(entry.automation.homeTeam);
  const away = normalized(entry.automation.awayTeam);
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const article = [...document.querySelectorAll(`a[href*="/${eventId}-"]`)]
      .map((link) => link.closest("article,.dashboard-game"))
      .find((candidate) => {
        const text = normalized(candidate?.textContent);
        return candidate && text.includes(home) && text.includes(away);
      });
    if (article) return article;
    await sleep(250);
  }
  throw new Error(`${entry.automation.homeTeam} vs ${entry.automation.awayTeam} is no longer listed on MelBet's baseball board.`);
}

async function clickMoneyline(entry, session, ordinal, totalEntries) {
  const expectedCode = entry.automation.side === "home" ? "w1" : "w2";
  const maximumAttempts = 3;
  for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
    if (couponContains(entry)) return { alreadyPresent: true, attempts: attempt - 1 };
    if (attempt > 1) {
      progress(session, "working", `MelBet did not confirm ${entry.selection}. Revalidating and retrying (${attempt}/${maximumAttempts})...`);
    }
    const article = await moneylineArticle(entry);
    const buttons = [...article.querySelectorAll("button.ui-market__toggle")];
    const button = buttons.find((candidate) =>
      normalized(candidate.getAttribute("aria-label")) === expectedCode
        || normalized(candidate.closest(".ui-market")?.textContent).startsWith(expectedCode),
    );
    if (!button) throw new Error(`${expectedCode.toUpperCase()} is no longer listed for ${entry.game}.`);
    article.scrollIntoView({ block: "center", inline: "nearest" });
    await sleep(250);
    const rect = button.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const hit = document.elementFromPoint(x, y);
    if (!(hit === button || hit?.closest("button") === button)) {
      throw new Error(`${entry.game}'s ${expectedCode.toUpperCase()} control is not visible. Nothing was clicked.`);
    }
    const previousCouponCount = couponBetCount();
    progress(session, "working", `Adding ${ordinal}/${totalEntries}: ${entry.selection}`);
    if (attempt === 1) {
      // Moneyline markets are normal DOM controls, unlike MelBet's canvas
      // props/totals. Using the already exact-validated button avoids a
      // debugger bridge stall on long cards.
      assertActive();
      button.click();
    } else {
      await trustedClick(x, y);
    }
    progress(session, "working", `Click sent for ${entry.selection}. Waiting for MelBet bet-slip confirmation...`);
    const verification = await waitForMoneylineConfirmation(entry, button, previousCouponCount);
    if (verification) return { alreadyPresent: false, verification, attempts: attempt };
    const delayedVerification = await waitForMoneylineConfirmation(entry, button, previousCouponCount, 10);
    if (delayedVerification) return { alreadyPresent: false, verification: delayedVerification, attempts: attempt };
  }
  const error = new Error(`${entry.selection} was clicked 3 times, but MelBet did not add it to the bet slip.`);
  error.skipPageRecovery = true;
  throw error;
}

async function clickTotalTarget(canvas, target, entry, session) {
  const maximumAttempts = 3;
  for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
    if (couponContains(entry)) return { alreadyPresent: true, attempts: attempt - 1 };
    if (attempt > 1) {
      progress(session, "working", `MelBet did not confirm ${entry.selection}. Revalidating and retrying (${attempt}/${maximumAttempts})...`);
    }
    canvas = await activateRegularTimeTotals();
    const previousCouponCount = couponBetCount();
    const { x, y } = await visibleTargetPoint(canvas, target);
    if (y < 120 || y > innerHeight - 30) {
      throw stopBeforeClick("The exact Regular time total is outside MelBet's visible market grid. Nothing was clicked.");
    }
    const element = document.elementFromPoint(x, y);
    if (!(element instanceof HTMLCanvasElement) || !element.classList.contains("market-grid-canvas__canvas")) {
      throw stopBeforeClick("MelBet's Regular time Total layout changed. Nothing was clicked.");
    }
    await trustedClick(x, y);
    const verification = await waitForCoupon(entry, previousCouponCount);
    if (verification) return { alreadyPresent: false, verification, attempts: attempt };
    const delayedVerification = await waitForCoupon(entry, previousCouponCount, 10);
    if (delayedVerification) return { alreadyPresent: false, verification: delayedVerification, attempts: attempt };
  }
  const error = new Error(`${entry.selection} was clicked 3 times, but MelBet did not add it to the bet slip.`);
  error.skipPageRecovery = true;
  throw error;
}

async function clickTarget(canvas, target, entry, session) {
  const maximumAttempts = 3;
  const filteredTarget = {
    ...target,
    contentY: GROUP_GAP + GROUP_HEADER_HEIGHT + target.row * MARKET_ROW_HEIGHT + MARKET_ROW_HEIGHT / 2,
  };

  for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
    // A slow response from an earlier click must never be toggled off by a retry.
    if (couponContains(entry)) {
      return { alreadyPresent: attempt === 1, verification: "exact", attempts: attempt - 1 };
    }

    if (attempt > 1) {
      progress(
        session,
        "working",
        `MelBet did not confirm ${entry.selection}. Revalidating and retrying (${attempt}/${maximumAttempts})...`,
      );
    }

    const previousCouponCount = couponBetCount();
    await filterToExactMarket(entry, target);
    // MelBet replaces the canvas element when the market search is applied.
    // Never position or click using the pre-filter reference: a detached
    // canvas reports zero bounds and looks falsely outside the viewport.
    canvas = await waitForCanvas();
    const { x, y } = await visibleTargetPoint(canvas, filteredTarget);
    if (y < 120 || y > innerHeight - 30) {
      throw stopBeforeClick("The exact line is outside MelBet's visible market grid. Nothing was clicked.");
    }
    const element = document.elementFromPoint(x, y);
    if (!(element instanceof HTMLCanvasElement) || !element.classList.contains("market-grid-canvas__canvas")) {
      throw stopBeforeClick("MelBet's market layout changed. Nothing was clicked.");
    }
    await trustedClick(x, y);

    const verification = await waitForCoupon(entry, previousCouponCount);
    if (verification) {
      return { alreadyPresent: false, verification, attempts: attempt };
    }

    // Give a delayed MelBet response one final grace window before another click.
    const delayedVerification = await waitForCoupon(entry, previousCouponCount, 10);
    if (delayedVerification) {
      return { alreadyPresent: false, verification: delayedVerification, attempts: attempt };
    }
  }

  const error = new Error(
    `${entry.automation.player} ${entry.automation.side.toUpperCase()} ${entry.automation.line} was found and clicked 3 times, but MelBet did not add it to the bet slip.`,
  );
  error.skipPageRecovery = true;
  throw error;
}

function nextUrl(entry, sessionId, step) {
  const url = new URL(entry.url);
  if (location.hostname === FALLBACK_HOST) url.hostname = FALLBACK_HOST;
  url.hash = `ninth-session=${encodeURIComponent(sessionId)}&step=${step}`;
  return url.toString();
}

async function advanceSession(session, request, nextStep) {
  if (nextStep < session.entries.length) {
    progress(session, "working", `Added ${nextStep}/${session.entries.length}. Opening the next exact event...`);
    location.href = nextUrl(session.entries[nextStep], request.id, nextStep);
    return;
  }
  progress(session, "done", `All ${session.entries.length} click(s) completed. Review every selection and line before entering any stake.`);
  await extensionMessage({ type: "NINTH_REMOVE_MELBET_SESSION", id: request.id });
}

async function run() {
  const request = parseSession();
  if (!request) return;
  activeSessionId = request.id;
  overlay();
  await extensionMessage({ type: "NINTH_MELBET_PAGE_BOOTSTRAPPED", id: request.id }).catch(() => {});
  const session = await getSession(request.id);
  if (session?.cancelled) cancelledSessions.add(request.id);
  assertActive();
  if (!session || Date.now() > Number(session.expiresAt)) throw new Error("This NINTH handoff expired. Start it again from the builder.");
  const entry = session.entries[request.step];
  if (!entry) throw new Error("This handoff step is invalid.");
  const kind = entry.automation.kind;
  if (kind === "moneyline") {
    if (!location.pathname.startsWith("/en/line/baseball")) {
      throw new Error("The open MelBet page is not the baseball moneyline board.");
    }
  } else if (!location.pathname.includes(`/${entry.automation.eventId}-`)) {
    throw new Error("The open MelBet event does not match NINTH's event ID.");
  }

  progress(session, "working", `Checking MelBet sign-in before selection ${request.step + 1}/${session.entries.length}...`);
  const recovered = Boolean(sessionStorage.getItem(recoveryKey(request)));
  if (!await waitForAuthentication(recovered)) {
    if (recoverPageOnce(
      session,
      request,
      `MelBet has not restored your signed-in account. Refreshing this exact event once before selection ${request.step + 1}/${session.entries.length}...`,
    )) return;
    throw new Error("MelBet still shows that you are signed out after the recovery refresh. Sign in on MelBet, then start this NINTH handoff again.");
  }

  await extensionMessage({ type: "NINTH_MELBET_PAGE_READY", id: request.id });

  if (kind === "moneyline") {
    let nextStep = request.step;
    try {
      while (nextStep < session.entries.length
        && session.entries[nextStep].automation.kind === "moneyline") {
        const moneylineEntry = session.entries[nextStep];
        const clickResult = await clickMoneyline(
          moneylineEntry,
          session,
          nextStep + 1,
          session.entries.length,
        );
        if (clickResult.alreadyPresent) {
          progress(session, "working", `${moneylineEntry.selection} is already in the MelBet bet slip. Continuing without clicking it again...`);
        }
        nextStep += 1;
        await sleep(500);
      }
    } catch (error) {
      if (shouldRecoverPage(error) && recoverPageOnce(session, request)) return;
      throw error;
    }
    sessionStorage.removeItem(recoveryKey(request));
    await advanceSession(session, request, nextStep);
    return;
  }

  progress(session, "working", `Validating ${request.step + 1}/${session.entries.length}: ${entry.selection}`);
  let canvas;
  let feed;
  try {
    canvas = await waitForCanvas();
    feed = await fetchFeed(entry.automation.eventId);
  } catch (error) {
    if (shouldRecoverPage(error) && recoverPageOnce(session, request)) return;
    throw error;
  }
  const target = kind === "totals" ? exactTotalTarget(feed, entry) : exactTarget(feed, entry);
  try {
    const clickResult = kind === "totals"
      ? await clickTotalTarget(canvas, target, entry, session)
      : await clickTarget(canvas, target, entry, session);
    if (clickResult.alreadyPresent) {
      progress(session, "working", `${entry.selection} is already in the MelBet bet slip. Continuing without clicking it again...`);
    }
  } catch (error) {
    if (shouldRecoverPage(error) && recoverPageOnce(session, request)) return;
    throw error;
  }
  await sleep(700);
  sessionStorage.removeItem(recoveryKey(request));

  const nextStep = request.step + 1;
  await advanceSession(session, request, nextStep);
}

const bootstrapId = new URLSearchParams(location.hash.replace(/^#/, "")).get("ninth-bootstrap");
if (bootstrapId) {
  overlay().querySelector("button").style.display = "none";
  show("MelBet opened. Waiting for NINTH to validate this card and start the helper...", "working");
  setTimeout(() => {
    if (location.hash.includes(`ninth-bootstrap=${encodeURIComponent(bootstrapId)}`)) {
      show("The helper did not claim this MelBet tab. Return to NINTH and read the connection message beside Autofill.", "error");
    }
  }, 12000);
}

run().catch((error) => {
  const request = parseSession();
  if (!request) return;
  getSession(request.id).then((session) => {
    session ||= {};
    progress(session, error?.cancelled ? "cancelled" : "error", error?.message || "Autofill stopped before clicking the next line.");
  });
});

// Alter Ego's history reader uses extension storage as a cross-tab mailbox.
// Keeping this in the already-registered MelBet content script lets an updated
// unpacked helper reconnect after an ordinary page refresh, without requiring
// access to Chrome's internal extension-management page.
(() => {
  if (globalThis.__ninthMelbetHistoryInstalled) return;
  globalThis.__ninthMelbetHistoryInstalled = true;
  const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const numeric = (value) => {
    const match = clean(value).replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : null;
  };
  const labeled = (root, label) => {
    const item = [...root.querySelectorAll(".bets-history-coupon-info-item, .bets-history-coupon-bet-event-info-item")]
      .find((node) => clean(node.querySelector(".bets-history-coupon-info-item__name, .bets-history-coupon-bet-event-info-item__label")?.textContent).toLowerCase() === label.toLowerCase());
    return clean(item?.querySelector(".bets-history-coupon-info-item__value, .bets-history-coupon-bet-event-info-item__value, .bets-history-coupon-bet-event-info-item-score")?.textContent);
  };
  const parseHistoryLeg = (node, index) => {
    const selection = labeled(node, "Event") || clean(node.querySelector(".bets-history-default-coupon-bet-info")?.textContent);
    const eventLink = node.querySelector(".bets-history-default-coupon-bet-game-name");
    const league = clean(node.querySelector(".bets-history-coupon-bet-champ__name")?.textContent);
    return { index:index+1, league, event:clean(eventLink?.textContent), event_url:eventLink?.href||"", status:clean(node.querySelector(".bets-history-coupon-bet__status .ui-status")?.textContent), processed_at:labeled(node,"Time of processing"), starts_at:labeled(node,"Start date and time"), game_status:labeled(node,"Game status"), odds:numeric(labeled(node,"Odds")), selection, result:labeled(node,"Result"), is_bonus:/bonus/i.test(league)||/^(accumulator )?bonus$/i.test(selection) };
  };
  async function extractHistorySlip() {
    if (!/\/office\/history(?:[/?#]|$)/i.test(location.pathname)) throw new Error("Open MelBet Bet history before importing into Alter Ego.");
    const coupon = document.querySelector(".bets-history-default-coupon");
    const drawer = coupon?.querySelector(".bets-history-coupon__body");
    if (!coupon || !drawer) throw new Error("Select a MelBet slip so its detail drawer is open, then import again.");
    const originalTop = drawer.scrollTop;
    let previousHeight = -1, stable = 0;
    for (let pass=0; pass<40 && stable<2; pass+=1) {
      drawer.scrollTop = drawer.scrollHeight;
      await new Promise((resolve)=>setTimeout(resolve,80));
      if (drawer.scrollHeight===previousHeight && drawer.scrollTop+drawer.clientHeight>=drawer.scrollHeight-3) stable+=1; else stable=0;
      previousHeight=drawer.scrollHeight;
    }
    const complete = stable>=2 && drawer.scrollTop+drawer.clientHeight>=drawer.scrollHeight-3;
    drawer.scrollTop=originalTop;
    if (!complete) throw new Error("MelBet's selected slip could not be scrolled to its end. Nothing was imported.");
    const title=clean(coupon.querySelector(".bets-history-coupon-name__title")?.textContent);
    const slipId=title.match(/(?:№|#)\s*([0-9A-Za-z_-]+)/)?.[1]||"";
    const stakeText=labeled(coupon,"Stake");
    const legs=[...coupon.querySelectorAll(".bets-history-coupon-bet")].map(parseHistoryLeg).filter((leg)=>leg.selection);
    if (!slipId||!legs.length) throw new Error("The selected MelBet slip is incomplete or unreadable. Nothing was imported.");
    const bettingLegs=legs.filter((leg)=>!leg.is_bonus);
    const status=bettingLegs.some((leg)=>/loss|lost/i.test(leg.status))?"Loss":bettingLegs.length&&bettingLegs.every((leg)=>/win|void|refund/i.test(leg.status))?"Win":"Pending";
    return { slip_id:slipId, placed_at:clean(coupon.querySelector(".bets-history-coupon-name__content")?.textContent).replace(title,"").trim(), status, bet_type:labeled(coupon,"Bet type"), total_odds:numeric(labeled(coupon,"Overall odds")), stake:numeric(stakeText), currency:clean(stakeText).match(/[A-Za-z]{3}/)?.[0]?.toUpperCase()||"ETB", potential_winnings:numeric(labeled(coupon,"Potential winnings")), legs, extraction:{viewport:drawer.clientHeight,content:drawer.scrollHeight,complete,extracted_legs:bettingLegs.length} };
  }
  async function handleHistoryRequest(request) {
    if (!request?.requestId || Date.now()-Number(request.requestedAt||0)>30000) return;
    try { await chrome.storage.local.set({ninthMelbetHistoryResponse:{requestId:request.requestId,ok:true,slip:await extractHistorySlip(),respondedAt:Date.now()}}); }
    catch (error) { await chrome.storage.local.set({ninthMelbetHistoryResponse:{requestId:request.requestId,ok:false,error:error?.message||"The selected MelBet slip could not be read.",respondedAt:Date.now()}}); }
    finally { await chrome.storage.local.remove("ninthMelbetHistoryRequest"); }
  }
  const historySleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
  const historyRowId = (row) => (clean(row?.innerText).match(/\b\d{9,15}\b/) || [""])[0];
  const renderedHistoryRows = () => [...document.querySelectorAll(".bets-history-default-body__row")]
    .map((row) => ({ row, id: historyRowId(row), button: row.querySelector('button[aria-label="View bet slip"]') }))
    .filter((item) => item.id && item.button);
  async function waitForHistorySlip(id, timeout=5000) {
    const deadline=Date.now()+timeout;
    while(Date.now()<deadline){
      const title=clean(document.querySelector(".bets-history-coupon-name__title")?.textContent);
      if(title.includes(id)&&document.querySelectorAll(".bets-history-coupon-bet").length) return;
      await historySleep(80);
    }
    throw new Error(`MelBet did not open slip ${id} in time.`);
  }
  async function reportHistoryProgress(requestId, detail) {
    await chrome.storage.local.set({ninthMelbetHistoryProgress:{requestId,...detail,updatedAt:Date.now()}});
  }
  async function extractAllMissingHistory(request) {
    if(!/\/office\/history(?:[/?#]|$)/i.test(location.pathname)) throw new Error("Open MelBet Bet history before importing all slips.");
    const scroller=document.querySelector(".vue-recycle-scroller");
    if(!scroller) throw new Error("MelBet's history list is not ready. Apply the desired history filter and try again.");
    const existing=new Set((request.existingSlipIds||[]).map(String));
    const seen=new Set(), slips=[], failures=[];
    const originalY=window.scrollY;
    const originalSelected=(clean(document.querySelector(".bets-history-coupon-name__title")?.textContent).match(/(?:№|#)\s*([0-9A-Za-z_-]+)/)||[])[1]||"";
    const expected=Number((clean(document.body.innerText).match(/Bet slips:\s*(\d+)/i)||[])[1]||0);
    const rect=scroller.getBoundingClientRect();
    const start=Math.max(0,rect.top+window.scrollY-140);
    const end=Math.max(start,start+scroller.getBoundingClientRect().height-window.innerHeight+260);
    const step=Math.max(420,Math.floor(window.innerHeight*0.68));
    let scannedPositions=0;
    try {
      for(let y=start;y<=end+step/2;y+=step){
        window.scrollTo({top:Math.min(y,end),behavior:"auto"});
        await historySleep(160);
        scannedPositions+=1;
        for(const item of renderedHistoryRows()){
          if(seen.has(item.id)) continue;
          seen.add(item.id);
          if(existing.has(item.id)){
            await reportHistoryProgress(request.requestId,{state:"scanning",scanned:seen.size,expected,imported:slips.length,skipped:seen.size-slips.length-failures.length,currentSlip:item.id});
            continue;
          }
          try{
            item.button.click();
            await waitForHistorySlip(item.id);
            const slip=await extractHistorySlip();
            if(String(slip.slip_id)!==item.id) throw new Error(`MelBet opened slip ${slip.slip_id} instead of ${item.id}.`);
            slips.push(slip);
          }catch(error){
            failures.push({slip_id:item.id,error:error?.message||"Slip could not be read."});
          }
          await reportHistoryProgress(request.requestId,{state:"importing",scanned:seen.size,expected,imported:slips.length,skipped:seen.size-slips.length-failures.length,failed:failures.length,currentSlip:item.id});
        }
        if(expected&&seen.size>=expected) break;
      }
    } finally {
      window.scrollTo({top:originalY,behavior:"auto"});
      await historySleep(180);
      if(originalSelected){
        const original=renderedHistoryRows().find((item)=>item.id===originalSelected);
        original?.button?.click();
      }
    }
    if(!seen.size) throw new Error("No MelBet history rows were found in the current filter.");
    await reportHistoryProgress(request.requestId,{state:"complete",scanned:seen.size,expected,imported:slips.length,skipped:seen.size-slips.length-failures.length,failed:failures.length,currentSlip:""});
    return {slips,failures,scanned:seen.size,expected,skipped:seen.size-slips.length-failures.length,positions:scannedPositions};
  }
  async function handleAllHistoryRequest(request){
    if(!request?.requestId||Date.now()-Number(request.requestedAt||0)>30000) return;
    try{await chrome.storage.local.set({ninthMelbetHistoryAllResponse:{requestId:request.requestId,ok:true,...await extractAllMissingHistory(request),respondedAt:Date.now()}});}
    catch(error){await chrome.storage.local.set({ninthMelbetHistoryAllResponse:{requestId:request.requestId,ok:false,error:error?.message||"MelBet history could not be imported.",respondedAt:Date.now()}});}
    finally{await chrome.storage.local.remove("ninthMelbetHistoryAllRequest");}
  }
  chrome.runtime?.onMessage?.addListener((message,_sender,sendResponse)=>{
    if(message?.type!=="NINTH_EXTRACT_SELECTED_MELBET_SLIP") return false;
    extractHistorySlip().then((slip)=>sendResponse({ok:true,slip}),(error)=>sendResponse({ok:false,error:error?.message||"The selected MelBet slip could not be read."}));
    return true;
  });
  chrome.storage?.onChanged?.addListener((changes,area)=>{ if(area==="local"&&changes.ninthMelbetHistoryRequest?.newValue) handleHistoryRequest(changes.ninthMelbetHistoryRequest.newValue); });
  chrome.storage?.onChanged?.addListener((changes,area)=>{ if(area==="local"&&changes.ninthMelbetHistoryAllRequest?.newValue) handleAllHistoryRequest(changes.ninthMelbetHistoryAllRequest.newValue); });
  chrome.storage?.local?.get?.("ninthMelbetHistoryRequest")?.then((stored)=>handleHistoryRequest(stored.ninthMelbetHistoryRequest));
  chrome.storage?.local?.get?.("ninthMelbetHistoryAllRequest")?.then((stored)=>handleAllHistoryRequest(stored.ninthMelbetHistoryAllRequest));
})();
