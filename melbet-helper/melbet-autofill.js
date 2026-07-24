const PROP_GROUPS = {
  outs: 10710,
  strikeouts: 2891,
  hits_allowed: 10713,
  walks: 10712,
  home_runs: 10466,
  runs: 11328,
  hits: 8527,
  total_bases: 10465,
  doubles: 10956,
  rbi: 10714,
};
const PROP_SIDE_TYPES = {
  outs: { over: [14500], under: [14501] },
  strikeouts: { over: [3868], under: [3869] },
  hits_allowed: { over: [14506], under: [14507] },
  walks: { over: [14504], under: [14505] },
  home_runs: { over: [13829], under: [13830] },
  runs: { over: [16068], under: [16069] },
  hits: { over: [8091], under: [8092] },
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
  doubles: ["doubles"],
  rbi: ["rbi", "runs batted in"],
};
const GROUP_GAP = 13;
const GROUP_HEADER_HEIGHT = 33;
const MARKET_ROW_HEIGHT = 34;
const FILTER_BOTTOM_GAP = 16;
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
  doubles: "doubles", rbi: "rbi",
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
  doubles: "Batters. Doubles. Players' stats",
  rbi: "Batters. Runs Batted In. Players' stats",
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const normalized = (value) => String(value || "")
  .normalize("NFKD")
  .replace(/\p{M}+/gu, "")
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, " ")
  .trim();
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
  node.innerHTML = `<b style="display:block;color:#a9ff5b;font-size:10px;letter-spacing:.14em;margin-bottom:5px">NINTH / MELBET HELPER · v${HELPER_VERSION}</b><span>Preparing selection...</span>`;
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
  const groupId = PROP_GROUPS[prop];
  if (!groupId) throw new Error(`Unsupported prop: ${entry.automation.marketLabel}.`);
  const groups = groupRows(feed);
  for (const group of groups) {
    if (group.id !== groupId) continue;
    const player = normalized(entry.automation.player);
    const sideTypes = PROP_SIDE_TYPES[prop]?.[entry.automation.side] || [];
    let sideIndex = group.columns.findIndex((column) =>
      column.some((market) => sideTypes.includes(Number(market?.T))),
    );
    // Older feeds do not always expose a stable selection type ID. Their
    // visual columns remain Over then Under, so retain that as a fallback.
    if (sideIndex < 0) sideIndex = entry.automation.side === "under" ? 1 : 0;
    const column = group.columns[sideIndex];
    if (!column) throw new Error(`${entry.automation.side.toUpperCase()} is no longer listed for ${entry.automation.marketLabel}.`);
    const row = column.findIndex((market) => normalized(market?.PL?.N) === player && closeEnough(market?.P, entry.automation.line));
    if (row < 0) throw new Error(`${entry.automation.player} ${entry.automation.side.toUpperCase()} ${entry.automation.line} is no longer an exact MelBet line.`);
    const oppositeSide = entry.automation.side === "under" ? "over" : "under";
    const oppositeTypes = PROP_SIDE_TYPES[prop]?.[oppositeSide] || [];
    let oppositeIndex = group.columns.findIndex((candidate) =>
      candidate.some((market) => oppositeTypes.includes(Number(market?.T))),
    );
    if (oppositeIndex < 0) oppositeIndex = sideIndex === 0 ? 1 : 0;
    const opposite = group.columns[oppositeIndex]?.find((market) => normalized(market?.PL?.N) === player && closeEnough(market?.P, entry.automation.line));
    if (!opposite) throw new Error(`The paired line for ${entry.automation.player} ${entry.automation.line} changed. Nothing was clicked.`);
    return {
      contentY: GROUP_GAP + GROUP_HEADER_HEIGHT + row * MARKET_ROW_HEIGHT + MARKET_ROW_HEIGHT / 2,
      groupId,
      row,
      rowCount: Math.max(...group.columns.map((column) => column.length)),
      sideIndex,
      columnCount: group.columns.length,
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
  const player = normalized(entry.automation.player);
  const side = normalized(entry.automation.side);
  const line = Number(entry.automation.line);
  const prop = canonicalProp(entry.automation.prop, entry.automation.marketLabel);
  const labels = PROP_COUPON_LABELS[prop] || [normalized(entry.automation.marketLabel)];
  return [...document.querySelectorAll(".coupon-bets__bet, .coupon-bet")].some((bet) => {
    const text = normalized(bet.textContent);
    const numbers = String(bet.textContent || "").match(/-?\d+(?:\.\d+)?/g) || [];
    return text.includes(player)
      && text.includes(side)
      && labels.some((label) => text.includes(label))
      && numbers.some((value) => closeEnough(value, line));
  });
}

function couponBetCount() {
  return document.querySelectorAll(".coupon-bets__bet, .coupon-bet").length;
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
    const market = button.closest(".ui-market");
    if (market?.classList.contains("ui-market--toggled")
      || button.getAttribute("aria-pressed") === "true") {
      return "selected";
    }
    if (couponBetCount() > previousCount) return "count";
    await sleep(150);
  }
  return "";
}

async function trustedWheel(x, y, deltaY) {
  const response = await extensionMessage({
    type: "NINTH_MELBET_TRUSTED_WHEEL",
    x: Math.round(x),
    y: Math.round(y),
    deltaY: Math.round(deltaY),
  });
  if (!response.ok) throw new Error(response.error || "MelBet's market grid could not be scrolled.");
}

async function trustedClick(x, y) {
  const response = await extensionMessage({
    type: "NINTH_MELBET_TRUSTED_CLICK",
    x: Math.round(x),
    y: Math.round(y),
  });
  if (!response.ok) {
    throw new Error(response.error || "The browser-level MelBet click could not be completed.");
  }
}

async function trustedEnter() {
  const response = await extensionMessage({ type: "NINTH_MELBET_TRUSTED_ENTER" });
  if (!response.ok) throw new Error(response.error || "MelBet's market search could not be submitted.");
}

async function filterToExactMarket(entry, target) {
  const prop = canonicalProp(entry.automation.prop, entry.automation.marketLabel);
  const query = PROP_MARKET_SEARCH[prop];
  if (!query) throw new Error(`The helper has no exact MelBet market filter for ${entry.automation.marketLabel}.`);
  const toolbar = document.querySelector(".game-toolbar__search");
  if (!toolbar) throw new Error("MelBet's market search control is unavailable.");
  let input = toolbar.querySelector("input");
  if (!input) {
    toolbar.querySelector("button")?.click();
    for (let attempt = 0; attempt < 12 && !input; attempt += 1) {
      await sleep(100);
      input = toolbar.querySelector("input");
    }
  }
  if (!input) throw new Error("MelBet's market search did not open.");
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  if (!setter) throw new Error("MelBet's market search input changed.");
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

  const expectedHeight = GROUP_GAP + GROUP_HEADER_HEIGHT
    + target.rowCount * MARKET_ROW_HEIGHT + FILTER_BOTTOM_GAP;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await sleep(100);
    const container = document.querySelector(".market-grid-canvas__container");
    const height = container?.getBoundingClientRect().height || 0;
    // An exact market search leaves one group. Verifying its calculated
    // height prevents coordinates for a filtered row being used on the full
    // unfiltered canvas.
    if (input.value === query && Math.abs(height - expectedHeight) <= 24) {
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
  throw new Error(`${entry.automation.marketLabel} could not be isolated in MelBet's market grid. Nothing was clicked.`);
}

async function visibleTargetPoint(canvas, target) {
  // The market uses a fixed viewport canvas and a wheel-driven renderer.
  // DOM scrollTop manipulation moves the canvas itself and blanks the rows.
  window.scrollTo(0, 0);
  await sleep(250);
  let rect = canvas.getBoundingClientRect();
  const parentRect = canvas.parentElement?.getBoundingClientRect() || rect;
  const probeTop = Math.max(0, rect.top, parentRect.top) + 12;
  const probeBottom = Math.min(innerHeight, rect.bottom, parentRect.bottom) - 12;
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
      throw new Error("MelBet's filtered market is outside the browser viewport.");
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
  const url = `/service-api/LineFeed/GetGameZip?id=${encodeURIComponent(eventId)}&lng=en&cfview=0&isSubGames=true&GroupEvents=true&countevents=250&partner=1&country=87`;
  const response = await fetch(url, { credentials: "include", cache: "no-store" });
  if (!response.ok) throw new Error(`MelBet market validation failed (${response.status}).`);
  return response.json();
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
  if (!input.checked) input.click();
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
    const link = [...document.querySelectorAll("article a[href]")]
      .find((candidate) => String(candidate.getAttribute("href") || "").includes(`/${eventId}-`));
    const article = link?.closest("article");
    const text = normalized(article?.textContent);
    if (article && text.includes(home) && text.includes(away)) return article;
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
      normalized(candidate.closest(".ui-market")?.textContent).startsWith(expectedCode),
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
      throw new Error("The exact Regular time total is outside MelBet's visible market grid. Nothing was clicked.");
    }
    const element = document.elementFromPoint(x, y);
    if (!(element instanceof HTMLCanvasElement) || !element.classList.contains("market-grid-canvas__canvas")) {
      throw new Error("MelBet's Regular time Total layout changed. Nothing was clicked.");
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
    const { x, y } = await visibleTargetPoint(canvas, filteredTarget);
    if (y < 120 || y > innerHeight - 30) {
      throw new Error("The exact line is outside MelBet's visible market grid. Nothing was clicked.");
    }
    const element = document.elementFromPoint(x, y);
    if (!(element instanceof HTMLCanvasElement) || !element.classList.contains("market-grid-canvas__canvas")) {
      throw new Error("MelBet's market layout changed. Nothing was clicked.");
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
  overlay();
  const session = await getSession(request.id);
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
      if (!error?.skipPageRecovery && recoverPageOnce(session, request)) return;
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
    if (!error?.skipPageRecovery && recoverPageOnce(session, request)) return;
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
    if (!error?.skipPageRecovery && recoverPageOnce(session, request)) return;
    throw error;
  }
  await sleep(700);
  sessionStorage.removeItem(recoveryKey(request));

  const nextStep = request.step + 1;
  await advanceSession(session, request, nextStep);
}

run().catch((error) => {
  const request = parseSession();
  if (!request) return;
  getSession(request.id).then((session) => {
    session ||= {};
    progress(session, "error", error?.message || "Autofill stopped before clicking the next line.");
  });
});
