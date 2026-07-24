const REQUEST_TIMEOUT_MS = 12_000;
const RETRY_DELAY_MS = 350;
const inFlight = new Map();

const wait = (milliseconds) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

async function fetchOnce(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    REQUEST_TIMEOUT_MS,
  );
  try {
    const response = await fetch(`/api${path}`, {
      ...options,
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const error = new Error(
        payload?.error || `Official data request failed (${response.status})`,
      );
      error.status = response.status;
      throw error;
    }
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") {
      const timeoutError = new Error(
        "The official data feed took too long to respond.",
      );
      timeoutError.retryable = true;
      throw timeoutError;
    }
    if (!error?.status || error.status >= 500) error.retryable = true;
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function runRequest(path, options = {}) {
  try {
    return await fetchOnce(path, options);
  } catch (error) {
    const method = String(options.method || "GET").toUpperCase();
    if (method !== "GET" || !error.retryable) throw error;
    await wait(RETRY_DELAY_MS);
    return fetchOnce(path, options);
  }
}

const request = (path, options = {}) => {
  const method = String(options.method || "GET").toUpperCase();
  if (method !== "GET") return runRequest(path, options);
  const existing = inFlight.get(path);
  if (existing) return existing;
  const pending = runRequest(path, options).finally(() =>
    inFlight.delete(path),
  );
  inFlight.set(path, pending);
  return pending;
};

export const api = {
  model: () => request("/model"),
  modelResults: (
    date = "", page = 1, pageSize = 10, market = "moneyline", propTypes,
  ) =>
    request(
      `/model/results?${new URLSearchParams({
        ...(date ? { date } : {}),
        page: String(page),
        page_size: String(pageSize),
        market,
        ...(Array.isArray(propTypes) ? { prop_types: propTypes.join(",") } : {}),
      })}`,
    ),
  dashboard: (refresh = false) =>
    request(`/dashboard${refresh ? `?refresh=${Date.now()}` : ""}`),
  projectionBoard: (startDate, days = 7) =>
    request(
      `/projection-board?start_date=${encodeURIComponent(startDate)}&days=${days}`,
    ),
  playerProps: (startDate, days = 1, refresh = false) =>
    request(
      `/player-props?start_date=${encodeURIComponent(startDate)}&days=${days}${refresh ? "&refresh=1" : ""}`,
    ),
  games: (kind = "today", date = "") =>
    request(`/games/${kind}${date ? `?date=${date}` : ""}`),
  game: (id) => request(`/games/${id}`),
  gameSummary: (id) => request(`/games/${id}/summary`),
  live: (id) => request(`/games/${id}/live`),
  teams: () => request("/teams"),
  team: (id) => request(`/teams/${id}`),
  players: () => request("/players"),
  player: (id) => request(`/players/${id}`),
  slips: () => request("/slips"),
  importSlip: (payload) =>
    request("/slips/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  trends: () => request("/trends"),
  rankings: () => request("/rankings"),
  injuries: () => request("/injuries"),
  health: () => request("/health"),
  search: (q) => request(`/search?q=${encodeURIComponent(q)}`),
};
