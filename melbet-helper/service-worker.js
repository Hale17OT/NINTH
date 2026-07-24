const SESSION_TTL_MS = 15 * 60 * 1000;
const PRIMARY_HOST = "mel-bet.et";
const FALLBACK_HOST = "melbet-322491.top";
const FALLBACK_DELAY_MINUTES = 0.25;
const MELBET_HOSTS = new Set([PRIMARY_HOST, FALLBACK_HOST]);

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
  doubles: "doubles",
  rbi: "rbi",
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
    if (["localhost", "127.0.0.1"].includes(parsed.hostname)) return true;
    return [PRIMARY_HOST, FALLBACK_HOST].includes(parsed.hostname)
      && parsed.hash.includes("ninth-session=");
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

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "NINTH_CREATE_MELBET_SESSION") return false;
  const requestedEntries = Array.isArray(message.payload?.entries) ? message.payload.entries : [];
  if (!requestedEntries.length || requestedEntries.length > 20 || !requestedEntries.every(isValidEntry)) {
    sendResponse({ ok: false, error: "Only complete, currently listed moneyline, total, or player-prop legs can be autofilled." });
    return false;
  }
  const kindPriority = { moneyline: 0, totals: 1, player_prop: 2 };
  const entries = requestedEntries.slice().sort((left, right) =>
    (kindPriority[left.automation.kind] ?? 9) - (kindPriority[right.automation.kind] ?? 9),
  );

  const id = crypto.randomUUID();
  const now = Date.now();
  const session = {
    id,
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
        prop: entry.automation.kind === "player_prop"
          ? canonicalProp(entry.automation.prop, entry.automation.marketLabel)
          : "",
        marketLabel: String(entry.automation.marketLabel || "Player prop"),
        homeTeam: String(entry.automation.homeTeam || ""),
        awayTeam: String(entry.automation.awayTeam || ""),
        side: String(entry.automation.side).toLowerCase(),
        line: entry.automation.line == null ? null : Number(entry.automation.line),
      },
    })),
  };

  chrome.storage.session.set({ [`ninth:${id}`]: session }).then(() =>
    chrome.tabs.create({ url: sessionUrl(session.entries[0].url, id, 0) }),
  ).then((tab) => sendResponse({ ok: true, sessionId: id, tabId: tab.id }))
    .catch((error) => sendResponse({ ok: false, error: error?.message || "Could not open MelBet." }));
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
  if (message?.type !== "NINTH_MELBET_PAGE_READY" || !sender.tab?.id) return false;
  chrome.alarms.clear(fallbackAlarmName(String(message.id || ""), sender.tab.id))
    .then((cleared) => sendResponse({ ok: true, fallbackAlarmCleared: cleared }))
    .catch((error) => sendResponse({
      ok: false,
      error: error?.message || "Could not clear the MelBet fallback timer.",
    }));
  // Keep the request port alive until alarms.clear settles. Without this,
  // Chrome reports "The message port closed before a response was received"
  // as soon as the MelBet page announces that its market canvas is ready.
  return true;
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (!alarm.name.startsWith("ninth-fallback:")) return;
  const [, sessionId, tabIdText] = alarm.name.split(":");
  const tabId = Number(tabIdText);
  if (!sessionId || !Number.isInteger(tabId)) return;
  const stored = await chrome.storage.session.get(`ninth:${sessionId}`).catch(() => ({}));
  const session = stored[`ninth:${sessionId}`];
  if (!session || Date.now() > Number(session.expiresAt)) return;
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
