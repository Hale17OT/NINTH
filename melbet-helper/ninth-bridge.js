const REQUEST = "NINTH_MELBET_AUTOFILL";
const STATUS = "NINTH_MELBET_AUTOFILL_STATUS";

function report(detail) {
  window.postMessage({ source: "NINTH_EXTENSION", type: STATUS, detail }, window.location.origin);
}

function extensionRuntime() {
  const runtime = globalThis.chrome?.runtime;
  return runtime?.id && typeof runtime.sendMessage === "function" ? runtime : null;
}

window.addEventListener("message", (event) => {
  if (event.source !== window || event.origin !== window.location.origin) return;
  if (event.data?.source !== "NINTH_APP" || event.data?.type !== REQUEST) return;
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
      report(response?.ok
        ? { state: "started", requestId, message: "MelBet opened. Keep that tab active while NINTH fills the card." }
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

report(extensionRuntime()
  ? { state: "ready", message: "NINTH helper connected." }
  : { state: "error", message: "Refresh NINTH to reconnect the updated browser helper." });
