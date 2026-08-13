const SESSION_TTL_MS = 15 * 60 * 1000;
const PRIMARY_HOST = "mel-bet.et";
const FALLBACK_HOST = "melbet-322491.top";
const FALLBACK_DELAY_MINUTES = 0.25;
const MELBET_HOSTS = new Set([PRIMARY_HOST, FALLBACK_HOST]);
const NINTH_HOSTS = new Set(["localhost", "127.0.0.1", "192.168.1.9", "192.168.137.1", "172.18.80.1"]);
const sessionCreationByRequest = new Map();

function boundedDebugger(operation, label, timeoutMs = 6000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error(`${label} timed out.`));
    }, timeoutMs);
    Promise.resolve(operation).then((value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve(value);
    }, (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      reject(error);
    });
  });
}
const PROP_ALIASES = {
  outs: "outs",
  total_outs: "outs",
  pitcher_outs: "outs",
  strikeout: "strikeouts",
  strikeouts: "strikeouts",
  total_strikeouts: "strikeouts",
  pitcher_strikeouts: "strikeouts",
  hits_allowed: "hits_allowed",
  pitcher_hits_allowed: "hits_allowed",
  walks: "walks",
  total_walks: "walks",
  home_run: "home_runs",
  home_runs: "home_runs",
  runs: "runs",
  hits: "hits",
  total_bases: "total_bases",
  single: "singles",
  singles: "singles",
  total_singles: "singles",
  doubles: "doubles",
  triple: "triples",
  triples: "triples",
  total_triples: "triples",
  rbi: "rbi",
  hits_runs_rbi: "hits_runs_rbi",
  hits_runs_rbis: "hits_runs_rbi",
  hits_runs_and_rbi: "hits_runs_rbi",
  hits_runs_and_rbis: "hits_runs_rbi",
  stolen_base: "stolen_bases",
  stolen_bases: "stolen_bases",
  win: "win",
  pitcher_to_win: "win",
  pitchers_to_win: "win",
};

function canonicalProp(...values) {
  for (const value of values) {
    const key = String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
    if (PROP_ALIASES[key]) return PROP_ALIASES[key];
  }
  return "";
}

function sessionRequest(url) {
  try {
    const parsed = new URL(url);
    const params = new URLSearchParams(parsed.hash.replace(/^#/, ""));
    return { host: parsed.hostname, id: params.get("ninth-session") };
  } catch {
    return { host: "", id: null };
  }
}

function fallbackAlarmName(sessionId, tabId) {
  return `ninth-fallback:${sessionId}:${tabId}`;
}

function shouldReconnectTab(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "http:" && NINTH_HOSTS.has(parsed.hostname)) return true;
    return [PRIMARY_HOST, FALLBACK_HOST].includes(parsed.hostname)
      && (parsed.hash.includes("ninth-session=") || /\/office\/history(?:\/|$)/i.test(parsed.pathname));
  } catch {
    return false;
  }
}

chrome.runtime.onInstalled.addListener(() => {
  // Reload only NINTH and active helper-session tabs so a freshly updated
  // unpacked extension cannot leave an old, invalidated content script behind.
  chrome.tabs.query({}).then((tabs) =>
    Promise.all(
      tabs
        .filter((tab) => tab.id && shouldReconnectTab(tab.url || ""))
        .map((tab) => chrome.tabs.reload(tab.id).catch(() => {})),
    ),
  ).catch(() => {});
});

function isValidEntry(entry) {
  const automation = entry?.automation;
  if (!entry?.url || !automation?.eventId) return false;
  if (automation.kind === "player_prop") {
    return Boolean(
      automation.player
        && canonicalProp(automation.prop, automation.marketLabel)
        && ["over", "under"].includes(automation.side)
        && Number.isFinite(Number(automation.line)),
    );
  }
  if (automation.kind === "moneyline") {
    return Boolean(
      automation.homeTeam && automation.awayTeam
        && ["home", "away"].includes(String(automation.side).toLowerCase()),
    );
  }
  if (automation.kind === "totals") {
    return Boolean(
      automation.homeTeam && automation.awayTeam
        && ["over", "under"].includes(String(automation.side).toLowerCase())
        && Number.isFinite(Number(automation.line)),
    );
  }
  return false;
}

function sessionUrl(url, sessionId, step) {
  const next = new URL(url);
  next.hash = `ninth-session=${encodeURIComponent(sessionId)}&step=${step}`;
  return next.toString();
}

function bootstrapRequestId(url) {
  try {
    return new URLSearchParams(new URL(url).hash.replace(/^#/, "")).get("ninth-bootstrap");
  } catch {
    return null;
  }
}

async function openSessionTab(session) {
  // NINTH opens a tab synchronously inside the user's click. Reuse it so the
  // helper cannot appear to do nothing while Chrome wakes a cold MV3 worker.
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const tabs = await chrome.tabs.query({});
    const bootstrap = tabs.find((tab) => tab.id && bootstrapRequestId(tab.url || "") === session.requestId);
    if (bootstrap?.id) {
      return chrome.tabs.update(bootstrap.id, {
        active: true,
        url: sessionUrl(session.entries[0].url, session.id, 0),
      });
    }
    if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, 75));
  }
  return chrome.tabs.create({ url: sessionUrl(session.entries[0].url, session.id, 0) });
}

async function notifyBootstrap(requestId, message) {
  if (!requestId) return;
  const tabs = await chrome.tabs.query({});
  const bootstrap = tabs.find((tab) => tab.id && bootstrapRequestId(tab.url || "") === requestId);
  if (bootstrap?.id) {
    await chrome.tabs.sendMessage(bootstrap.id, {
      type: "NINTH_MELBET_BOOTSTRAP_ERROR",
      message,
    }).catch(() => {});
  }
}

async function activeSession(id) {
  if (!id) return null;
  const stored = await chrome.storage.session.get(`ninth:${id}`);
  const session = stored[`ninth:${id}`];
  return session && !session.cancelled && Date.now() <= Number(session.expiresAt) ? session : null;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "NINTH_CREATE_MELBET_SESSION") return false;
  const requestId = String(message.requestId || "");
  const requestedEntries = Array.isArray(message.payload?.entries) ? message.payload.entries : [];
  if (!requestId || !requestedEntries.length || requestedEntries.length > 20 || !requestedEntries.every(isValidEntry)) {
    const error = "One or more legs no longer has complete MelBet player, market, side, or line metadata. Return to NINTH and refresh the card.";
    notifyBootstrap(requestId, error).catch(() => {});
    sendResponse({ ok: false, error });
    return false;
  }
  const pendingCreation = sessionCreationByRequest.get(requestId);
  if (pendingCreation) {
    pendingCreation.then(sendResponse, (error) => sendResponse({
      ok: false,
      error: error?.message || "Could not start the MelBet helper session.",
    }));
    return true;
  }
  const kindPriority = { moneyline: 0, totals: 1, player_prop: 2 };
  const entries = requestedEntries.slice().sort((left, right) =>
    (kindPriority[left.automation.kind] ?? 9) - (kindPriority[right.automation.kind] ?? 9),
  );

  const id = crypto.randomUUID();
  const now = Date.now();
  const session = {
    id,
    requestId,
    createdAt: now,
    expiresAt: now + SESSION_TTL_MS,
    sourceTabId: sender.tab?.id || null,
    entries: entries.map((entry) => ({
      key: String(entry.key || ""),
      game: String(entry.game || ""),
      selection: String(entry.selection || ""),
      url: String(entry.url),
      automation: {
        kind: String(entry.automation.kind),
        eventId: String(entry.automation.eventId),
        player: String(entry.automation.player),
        melbetPlayerName: String(entry.automation.melbetPlayerName || ""),
        prop: entry.automation.kind === "player_prop"
          ? canonicalProp(entry.automation.prop, entry.automation.marketLabel)
          : "",
        marketLabel: String(entry.automation.marketLabel || "Player prop"),
        homeTeam: String(entry.automation.homeTeam || ""),
        awayTeam: String(entry.automation.awayTeam || ""),
        side: String(entry.automation.side).toLowerCase(),
        line: entry.automation.line == null ? null : Number(entry.automation.line),
        melbetMarketLabel: String(entry.automation.melbetMarketLabel || ""),
        melbetSelectionName: String(entry.automation.melbetSelectionName || ""),
        melbetDisplayLine: entry.automation.melbetDisplayLine == null ? null : Number(entry.automation.melbetDisplayLine),
        melbetFormat: String(entry.automation.melbetFormat || ""),
        melbetGroupId: entry.automation.melbetGroupId == null ? null : Number(entry.automation.melbetGroupId),
        melbetTypeId: entry.automation.melbetTypeId == null ? null : Number(entry.automation.melbetTypeId),
      },
    })),
  };

  const creation = chrome.storage.session.set({ [`ninth:${id}`]: session }).then(() =>
    openSessionTab(session),
  ).then(async (tab) => {
    session.melbetTabId = tab.id || null;
    await chrome.storage.session.set({ [`ninth:${id}`]: session });
    return { ok: true, sessionId: id, tabId: tab.id };
  });
  sessionCreationByRequest.set(requestId, creation);
  const releaseRequest = () => {
    const releaseTimer = setTimeout(() => {
      if (sessionCreationByRequest.get(requestId) === creation) sessionCreationByRequest.delete(requestId);
    }, 60000);
    // Node contract tests expose unref(); browsers return a numeric timer ID.
    releaseTimer?.unref?.();
  };
  creation.then(releaseRequest, releaseRequest);
  creation.then(sendResponse).catch((error) => {
    const detail = error?.message || "Could not start the MelBet helper session.";
    notifyBootstrap(requestId, detail).catch(() => {});
    sendResponse({ ok: false, error: detail });
  });
  return true;
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "NINTH_MELBET_HELPER_PING") return false;
  sendResponse({ ok: true, version: chrome.runtime.getManifest().version });
  return false;
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "NINTH_GET_SELECTED_MELBET_SLIP") return false;
  (async () => {
    const tabs = await chrome.tabs.query({});
    const candidates = tabs
      .filter((tab) => tab.id && [...MELBET_HOSTS].some((host) => String(tab.url || "").includes(`://${host}/`)))
      .sort((left, right) => Number(/\/office\/history/i.test(right.url || "")) - Number(/\/office\/history/i.test(left.url || "")));
    if (!candidates.length) throw new Error("No open MelBet tab was found. Open Bet history and select a slip first.");
    let lastError = "Open MelBet Bet history and select a slip first.";
    for (const tab of candidates) {
      try {
        const response = await chrome.tabs.sendMessage(tab.id, { type: "NINTH_EXTRACT_SELECTED_MELBET_SLIP" });
        if (response?.ok) return response;
        lastError = response?.error || lastError;
      } catch (error) {
        lastError = error?.message || lastError;
      }
    }
    throw new Error(lastError);
  })().then(sendResponse, (error) => sendResponse({ ok: false, error: error?.message || "The selected MelBet slip could not be imported." }));
  return true;
});

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type !== "NINTH_AUTOFILL_PROGRESS") return;
  const sourceTabId = Number(message.sourceTabId);
  if (!Number.isInteger(sourceTabId)) return;
  chrome.tabs.sendMessage(sourceTabId, message).catch(() => {});
});

chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (change.status !== "loading") return;
  const request = sessionRequest(change.url || tab.url || "");
  if (!request.id || request.host !== PRIMARY_HOST) return;
  chrome.alarms.create(fallbackAlarmName(request.id, tabId), { delayInMinutes: FALLBACK_DELAY_MINUTES });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!["NINTH_MELBET_PAGE_BOOTSTRAPPED", "NINTH_MELBET_PAGE_READY"].includes(message?.type)
      || !sender.tab?.id) return false;
  const sessionId = String(message.id || "");
  let senderHost = "";
  try { senderHost = new URL(sender.url || "").hostname; } catch { senderHost = ""; }
  Promise.all([
    chrome.alarms.clear(fallbackAlarmName(sessionId, sender.tab.id)),
    senderHost === PRIMARY_HOST && message.type === "NINTH_MELBET_PAGE_BOOTSTRAPPED"
      ? chrome.storage.session.get(`ninth:${sessionId}`).then((stored) => {
        const session = stored[`ninth:${sessionId}`];
        if (!session) return;
        session.primaryHostBootstrapped = true;
        session.primaryHostBootstrappedAt = Date.now();
        return chrome.storage.session.set({ [`ninth:${sessionId}`]: session });
      })
      : Promise.resolve(),
  ])
    .then(([cleared]) => sendResponse({ ok: true, fallbackAlarmCleared: cleared }))
    .catch((error) => sendResponse({
      ok: false,
      error: error?.message || "Could not clear the MelBet fallback timer.",
    }));
  // Clear the primary-host timer as soon as the helper script boots. From
  // this point onward, authentication, validation, viewport, and click errors
  // belong to this healthy primary page and must never route to the proxy.
  // PAGE_READY remains an idempotent second acknowledgement.
  return true;
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (!alarm.name.startsWith("ninth-fallback:")) return;
  const [, sessionId, tabIdText] = alarm.name.split(":");
  const tabId = Number(tabIdText);
  if (!sessionId || !Number.isInteger(tabId)) return;
  const stored = await chrome.storage.session.get(`ninth:${sessionId}`).catch(() => ({}));
  const session = stored[`ninth:${sessionId}`];
  if (!session || session.cancelled || Date.now() > Number(session.expiresAt)) return;
  if (session.primaryHostBootstrapped) return;
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (!tab?.url) return;
  const current = new URL(tab.url);
  if (current.hostname !== PRIMARY_HOST) return;
  current.hostname = FALLBACK_HOST;
  await chrome.tabs.update(tabId, { url: current.toString() }).catch(() => {});
  if (Number.isInteger(Number(session.sourceTabId))) {
    chrome.tabs.sendMessage(Number(session.sourceTabId), {
      type: "NINTH_AUTOFILL_PROGRESS",
      detail: { state: "working", message: "The primary MelBet host did not become ready. Retrying the same exact event through the proxy..." },
    }).catch(() => {});
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "NINTH_GET_MELBET_SESSION") return false;
  const id = String(message.id || "");
  chrome.storage.session.get(`ninth:${id}`)
    .then((stored) => sendResponse({ session: stored[`ninth:${id}`] || null }))
    .catch((error) => sendResponse({ session: null, error: error?.message || "Session lookup failed." }));
  return true;
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "NINTH_CANCEL_MELBET_SESSION") return false;
  const id = String(message.id || "");
  (async () => {
    const stored = await chrome.storage.session.get(`ninth:${id}`);
    const session = stored[`ninth:${id}`];
    if (!session) {
      sendResponse({ ok: true, alreadyStopped: true });
      return;
    }
    session.cancelled = true;
    session.cancelledAt = Date.now();
    await chrome.storage.session.set({ [`ninth:${id}`]: session });
    const alarms = await chrome.alarms.getAll();
    await Promise.all(alarms
      .filter((alarm) => alarm.name.startsWith(`ninth-fallback:${id}:`))
      .map((alarm) => chrome.alarms.clear(alarm.name)));
    const tabId = Number(session.melbetTabId);
    if (Number.isInteger(tabId)) {
      await chrome.tabs.sendMessage(tabId, { type: "NINTH_CANCEL_MELBET_AUTOFILL", id }).catch(() => {});
      await boundedDebugger(chrome.debugger.detach({ tabId }), "Detaching the cancelled MelBet helper", 2500).catch(() => {});
    }
    sendResponse({ ok: true });
  })().catch((error) => sendResponse({ ok: false, error: error?.message || "The helper could not be stopped." }));
  return true;
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "NINTH_MELBET_TRUSTED_ENTER") return false;
  const tabId = sender.tab?.id;
  let host = "";
  try { host = new URL(sender.url || "").hostname; } catch { host = ""; }
  if (!Number.isInteger(tabId) || !MELBET_HOSTS.has(host)) {
    sendResponse({ ok: false, error: "The helper rejected an invalid MelBet search request." });
    return false;
  }
  const target = { tabId };
  (async () => {
    let attached = false;
    try {
      if (!await activeSession(String(message.sessionId || ""))) throw new Error("Autofill was cancelled before the keyboard action.");
      await boundedDebugger(chrome.debugger.attach(target, "1.3"), "Attaching the MelBet keyboard bridge");
      attached = true;
      const key = {
        key: "Enter", code: "Enter", windowsVirtualKeyCode: 13,
        nativeVirtualKeyCode: 13,
      };
      await boundedDebugger(chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
        type: "rawKeyDown", ...key,
      }), "Submitting the MelBet market search");
      await boundedDebugger(chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
        type: "keyUp", ...key,
      }), "Releasing the MelBet search key");
      sendResponse({ ok: true });
    } catch (error) {
      sendResponse({
        ok: false,
        error: error?.message?.includes("Another debugger is already attached")
          ? "Close DevTools on the MelBet tab, then run Autofill again."
          : `MelBet did not accept the market search: ${error?.message || "unknown browser error"}`,
      });
    } finally {
      if (attached) await boundedDebugger(chrome.debugger.detach(target), "Detaching the MelBet keyboard bridge", 2500).catch(() => {});
    }
  })();
  return true;
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "NINTH_MELBET_TRUSTED_WHEEL") return false;
  const tabId = sender.tab?.id;
  let host = "";
  try { host = new URL(sender.url || "").hostname; } catch { host = ""; }
  const x = Number(message.x);
  const y = Number(message.y);
  const deltaY = Number(message.deltaY);
  if (!Number.isInteger(tabId) || !MELBET_HOSTS.has(host)
      || !Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(deltaY)
      || x < 0 || y < 0 || x > 10000 || y > 10000 || Math.abs(deltaY) > 100000) {
    sendResponse({ ok: false, error: "The helper rejected an invalid MelBet wheel request." });
    return false;
  }
  const target = { tabId };
  (async () => {
    let attached = false;
    try {
      if (!await activeSession(String(message.sessionId || ""))) throw new Error("Autofill was cancelled before the scroll action.");
      await boundedDebugger(chrome.debugger.attach(target, "1.3"), "Attaching the MelBet wheel bridge");
      attached = true;
      await boundedDebugger(chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
        type: "mouseMoved", x, y,
      }), "Positioning the MelBet wheel");
      await boundedDebugger(chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
        type: "mouseWheel", x, y, deltaX: 0, deltaY,
      }), "Scrolling the MelBet market grid");
      sendResponse({ ok: true });
    } catch (error) {
      sendResponse({
        ok: false,
        error: error?.message?.includes("Another debugger is already attached")
          ? "Close DevTools on the MelBet tab, then run Autofill again."
          : `MelBet did not accept the browser-level wheel input: ${error?.message || "unknown browser error"}`,
      });
    } finally {
      if (attached) await boundedDebugger(chrome.debugger.detach(target), "Detaching the MelBet wheel bridge", 2500).catch(() => {});
    }
  })();
  return true;
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "NINTH_MELBET_TRUSTED_CLICK") return false;
  const tabId = sender.tab?.id;
  let host = "";
  try { host = new URL(sender.url || "").hostname; } catch { host = ""; }
  const x = Number(message.x);
  const y = Number(message.y);
  if (!Number.isInteger(tabId) || !MELBET_HOSTS.has(host)
      || !Number.isFinite(x) || !Number.isFinite(y)
      || x < 0 || y < 0 || x > 10000 || y > 10000) {
    sendResponse({ ok: false, error: "The helper rejected an invalid MelBet click request." });
    return false;
  }
  const target = { tabId };
  (async () => {
    let attached = false;
    try {
      if (!await activeSession(String(message.sessionId || ""))) throw new Error("Autofill was cancelled before the click.");
      await boundedDebugger(chrome.debugger.attach(target, "1.3"), "Attaching the MelBet click bridge");
      attached = true;
      await boundedDebugger(chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
        type: "mouseMoved", x, y,
      }), "Positioning the MelBet click");
      await boundedDebugger(chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
        type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1,
      }), "Pressing the MelBet selection");
      await boundedDebugger(chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
        type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1,
      }), "Releasing the MelBet selection");
      sendResponse({ ok: true });
    } catch (error) {
      sendResponse({
        ok: false,
        error: error?.message?.includes("Another debugger is already attached")
          ? "Close DevTools on the MelBet tab, then run Autofill again."
          : `MelBet did not accept the browser-level click: ${error?.message || "unknown browser error"}`,
      });
    } finally {
      if (attached) await boundedDebugger(chrome.debugger.detach(target), "Detaching the MelBet click bridge", 2500).catch(() => {});
    }
  })();
  return true;
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "NINTH_REMOVE_MELBET_SESSION") return false;
  const id = String(message.id || "");
  chrome.storage.session.remove(`ninth:${id}`)
    .then(async () => {
      const alarms = await chrome.alarms.getAll();
      await Promise.all(alarms.filter((alarm) => alarm.name.startsWith(`ninth-fallback:${id}:`)).map((alarm) => chrome.alarms.clear(alarm.name)));
      sendResponse({ ok: true });
    })
    .catch((error) => sendResponse({ ok: false, error: error?.message || "Session cleanup failed." }));
  return true;
});
