const REQUEST_TIMEOUT_MS = 12_000;
const RETRY_DELAY_MS = 350;
const inFlight = new Map();
let csrfToken = "";
let csrfPromise;

const wait = (milliseconds) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

async function ensureCsrf() {
  if (csrfToken) return csrfToken;
  if (!csrfPromise) csrfPromise = fetch("/api/auth/csrf", {
    credentials: "include",
    cache: "no-store",
  }).then(async response => {
    if (!response.ok) throw new Error("Account security could not be initialized.");
    const payload = await response.json();
    csrfToken = payload.csrfToken;
    return csrfToken;
  }).finally(() => { csrfPromise = null; });
  return csrfPromise;
}

async function fetchOnce(path, options = {}) {
  const { timeoutMs = REQUEST_TIMEOUT_MS, ...fetchOptions } = options;
  const method = String(fetchOptions.method || "GET").toUpperCase();
  const headers = new Headers(fetchOptions.headers || {});
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRF-Token", await ensureCsrf());
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    timeoutMs,
  );
  try {
    const response = await fetch(`/api${path}`, {
      ...fetchOptions,
      headers,
      credentials: "include",
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const error = new Error(
        payload?.error || `Official data request failed (${response.status})`,
      );
      error.status = response.status;
      error.code = payload?.code;
      error.fields = payload?.fields || {};
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
  authConfig: () => request("/auth/config"),
  authMe: () => request("/auth/me", { timeoutMs: 8000 }),
  authRegister: payload => request("/auth/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  authLogin: payload => request("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  authLogout: () => request("/auth/logout", { method: "POST" }),
  authForgotPassword: email => request("/auth/forgot-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) }),
  authResetPassword: payload => request("/auth/reset-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  authVerifyEmail: token => request("/auth/verify-email", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) }),
  authResendVerification: () => request("/auth/resend-verification", { method: "POST" }),
  authGoogleUrl: (returnTo = "/", remember = true) => request(`/auth/google?${new URLSearchParams({ format: "json", returnTo, remember: remember ? "1" : "0" })}`),
  account: () => request("/user/account"),
  updateProfile: payload => request("/user/profile", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  updatePreferences: payload => request("/user/preferences", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  changePassword: payload => request("/user/change-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  accountSessions: () => request("/user/sessions"),
  revokeSession: id => request(`/user/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }),
  savedList: type => request(`/saved/${encodeURIComponent(type)}`),
  savedGet: (type, id) => request(`/saved/${encodeURIComponent(type)}/${encodeURIComponent(id)}`),
  savedCreate: (type, payload) => request(`/saved/${encodeURIComponent(type)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
  savedDelete: (type, id) => request(`/saved/${encodeURIComponent(type)}/${encodeURIComponent(id)}`, { method: "DELETE" }),
  sportDirectory: (sport, type, filters = {}) => request(`/multisport/${encodeURIComponent(sport)}/${encodeURIComponent(type)}?${new URLSearchParams(Object.fromEntries(Object.entries(filters).filter(([,value]) => value && value !== 'all')))}`, { timeoutMs: 120_000 }),
  sportWorkspace: (sport, scope, id, filters = {}) => request(`/multisport/${encodeURIComponent(sport)}/workspace/${encodeURIComponent(scope)}/${encodeURIComponent(id)}?${new URLSearchParams(Object.fromEntries(Object.entries(filters).filter(([,value]) => value && value !== 'all')))}`, { timeoutMs: 120_000 }),
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
      { timeoutMs: market === "player_props" ? 60000 : REQUEST_TIMEOUT_MS },
    ),
  dashboard: () => request("/dashboard"),
  scoreboard: () => request("/scoreboard"),
  projectionBoard: (startDate, days = 7) =>
    request(
      `/projection-board?start_date=${encodeURIComponent(startDate)}&days=${days}`,
      { timeoutMs: 120_000 },
    ),
  playerProps: (startDate, days = 1, refresh = false) =>
    request(
      `/player-props?start_date=${encodeURIComponent(startDate)}&days=${days}${refresh ? "&refresh=1" : ""}`,
      { timeoutMs: 120_000 },
    ),
  playerPropGuarantees: (minimumSamples = 1, search = "", propTypes) =>
    request(`/player-props/guarantees?${new URLSearchParams({
      minimum_samples: String(minimumSamples),
      ...(search ? { search } : {}),
      ...(Array.isArray(propTypes) ? { prop_types: propTypes.join(",") } : {}),
    })}`),
  recordPlayerPropBuild: (payload) =>
    request("/player-props/build-snapshots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  games: (kind = "today", date = "") =>
    request(`/games/${kind}${date ? `?date=${date}` : ""}`),
  game: (id) => request(`/games/${id}`, { timeoutMs: 45000 }),
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
  alterEgo: () => request("/alter-ego"),
  importMelbetHistory: (payload) =>
    request("/alter-ego/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  importMelbetHistoryBatch: (payload) =>
    request("/alter-ego/import-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      timeoutMs: 120_000,
    }),
  trends: () => request("/trends"),
  rankings: () => request("/rankings"),
  injuries: () => request("/injuries"),
  health: () => request("/health"),
  search: (q) => request(`/search?q=${encodeURIComponent(q)}`),
};
