const REQUEST = "NINTH_MELBET_AUTOFILL";
const CANCEL_REQUEST = "NINTH_MELBET_AUTOFILL_CANCEL";
const STATUS_REQUEST = "NINTH_MELBET_HELPER_STATUS_REQUEST";
const STATUS = "NINTH_MELBET_AUTOFILL_STATUS";
const HISTORY_REQUEST = "NINTH_MELBET_HISTORY_REQUEST";
const HISTORY_RESULT = "NINTH_MELBET_HISTORY_RESULT";
const HISTORY_ALL_REQUEST = "NINTH_MELBET_HISTORY_ALL_REQUEST";
const HISTORY_ALL_RESULT = "NINTH_MELBET_HISTORY_ALL_RESULT";
const HISTORY_ALL_PROGRESS = "NINTH_MELBET_HISTORY_ALL_PROGRESS";
const sessionsByRequest = new Map();
const cancelledRequests = new Set();

function report(detail) {
  const helperVersion = extensionRuntime()?.getManifest?.().version || "";
  window.postMessage({ source: "NINTH_EXTENSION", type: STATUS, detail: { ...detail, helperVersion } }, window.location.origin);
}

function extensionRuntime() {
  const runtime = globalThis.chrome?.runtime;
  return runtime?.id && typeof runtime.sendMessage === "function" ? runtime : null;
}

window.addEventListener("message", (event) => {
  if (event.source !== window || event.origin !== window.location.origin) return;
  if (event.data?.source !== "NINTH_APP") return;
  const requestId = String(event.data.requestId || "");
  const runtime = extensionRuntime();
  if (!runtime) {
    report({
      state: "error",
      requestId,
      message: "The helper was updated while this NINTH tab was open. Refresh NINTH once, then start Autofill again.",
    });
    return;
  }
  if (event.data?.type === STATUS_REQUEST) {
    runtime.sendMessage({ type: "NINTH_MELBET_HELPER_PING" }, (response) => {
      const lastError = globalThis.chrome?.runtime?.lastError;
      report(lastError || !response?.ok
        ? { state: "error", message: lastError?.message || "The helper background service did not answer." }
        : { state: "ready", message: `NINTH helper v${response.version || runtime.getManifest().version} connected and ready.` });
    });
    return;
  }
  if (event.data?.type === HISTORY_REQUEST) {
    globalThis.chrome.storage.local.set({ ninthMelbetHistoryRequest: { requestId, requestedAt: Date.now() } });
    return;
  }
  if (event.data?.type === HISTORY_ALL_REQUEST) {
    globalThis.chrome.storage.local.set({
      ninthMelbetHistoryAllRequest: {
        requestId,
        requestedAt: Date.now(),
        existingSlipIds: Array.isArray(event.data.existingSlipIds) ? event.data.existingSlipIds.slice(0, 500) : [],
      },
    });
    return;
  }
  if (event.data?.type === CANCEL_REQUEST) {
    cancelledRequests.add(requestId);
    const sessionId = String(event.data.sessionId || sessionsByRequest.get(requestId) || "");
    if (!sessionId) {
      report({ state: "cancelling", requestId, message: "Stop requested. Waiting for the helper startup request to finish safely..." });
      return;
    }
    runtime.sendMessage({ type: "NINTH_CANCEL_MELBET_SESSION", id: sessionId }, (response) => {
      const lastError = globalThis.chrome?.runtime?.lastError;
      if (lastError || !response?.ok) {
        report({ state: "error", requestId, message: lastError?.message || response?.error || "The helper could not be stopped." });
        return;
      }
      sessionsByRequest.delete(requestId);
      report({ state: "cancelled", requestId, message: "Autofill stopped. The MelBet tab was left open and no more selections will be clicked." });
    });
    return;
  }
  if (event.data?.type !== REQUEST) return;
  report({ state: "detected", requestId, message: "Helper detected. Starting the validated MelBet session..." });
  let settled = false;
  const timeout = window.setTimeout(() => {
    if (settled) return;
    settled = true;
    report({ state: "error", requestId, message: "The extension background service did not respond. Reload NINTH MelBet Helper in chrome://extensions." });
  }, 7000);
  try {
    runtime.sendMessage({ type: "NINTH_CREATE_MELBET_SESSION", requestId, payload: event.data.payload }, (response) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      const lastError = globalThis.chrome?.runtime?.lastError;
      if (lastError) {
        report({
          state: "error",
          requestId,
          message: lastError.message?.includes("Extension context invalidated")
            ? "The helper was updated while this NINTH tab was open. Refresh NINTH once, then start Autofill again."
            : lastError.message,
        });
        return;
      }
      if (response?.ok) sessionsByRequest.set(requestId, response.sessionId);
      if (response?.ok && cancelledRequests.has(requestId)) {
        runtime.sendMessage({ type: "NINTH_CANCEL_MELBET_SESSION", id: response.sessionId }, () => {
          sessionsByRequest.delete(requestId);
          cancelledRequests.delete(requestId);
          report({ state: "cancelled", requestId, message: "Autofill stopped before its first MelBet action." });
        });
        return;
      }
      report(response?.ok
        ? { state: "started", requestId, sessionId: response.sessionId, message: "MelBet opened. Keep that tab active while NINTH fills the card." }
        : { state: "error", requestId, message: response?.error || "The helper could not start." });
    });
  } catch (error) {
    settled = true;
    window.clearTimeout(timeout);
    report({ state: "error", requestId, message: error?.message || "The extension background service could not be reached." });
  }
});

extensionRuntime()?.onMessage.addListener((message) => {
  if (message?.type === "NINTH_AUTOFILL_PROGRESS") report(message.detail || {});
});

globalThis.chrome?.storage?.onChanged?.addListener((changes, area) => {
  if (area !== "local") return;
  const response = changes.ninthMelbetHistoryResponse?.newValue;
  if (response?.requestId) {
    window.postMessage({
      source: "NINTH_EXTENSION",
      type: HISTORY_RESULT,
      requestId: response.requestId,
      ok: Boolean(response.ok),
      slip: response.slip,
      error: response.error || "The selected MelBet slip could not be imported.",
      helperVersion: extensionRuntime()?.getManifest?.().version || "",
    }, window.location.origin);
  }
  const batch = changes.ninthMelbetHistoryAllResponse?.newValue;
  if (batch?.requestId) {
    window.postMessage({ source: "NINTH_EXTENSION", type: HISTORY_ALL_RESULT, ...batch, helperVersion: extensionRuntime()?.getManifest?.().version || "" }, window.location.origin);
  }
  const progress = changes.ninthMelbetHistoryProgress?.newValue;
  if (progress?.requestId) {
    window.postMessage({ source: "NINTH_EXTENSION", type: HISTORY_ALL_PROGRESS, ...progress }, window.location.origin);
  }
});

report(extensionRuntime()
  ? { state: "ready", message: "NINTH helper connected." }
  : { state: "error", message: "Refresh NINTH to reconnect the updated browser helper." });
