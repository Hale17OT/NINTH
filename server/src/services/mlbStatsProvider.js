import { cache } from "./cache.js";

export const resolveStatsBaseUrl = (environment = process.env) => {
  const internalUrl = String(environment.NINTH_STATS_INTERNAL_URL || "").replace(/\/$/, "");
  if (internalUrl) return internalUrl;
  const configuredUrl = String(environment.MLB_STATS_URL || "").replace(/\/$/, "");
  if (configuredUrl) return configuredUrl;
  return environment.VERCEL_URL
    ? `https://${environment.VERCEL_URL}/api/stats`
    : "http://127.0.0.1:3002";
};

const baseUrl = resolveStatsBaseUrl();

async function request(path, options = {}) {
  const { timeoutMs = 30000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      ...fetchOptions,
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const error = new Error(
        payload?.error || `MLB provider returned ${response.status}`,
      );
      error.status = response.status;
      throw error;
    }
    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

export const mlbStatsProvider = {
  health: () => request("/health"),
  model: () => request("/model"),
  modelResults(date, page = 1, pageSize = 10, market = "moneyline", propTypes) {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
      market,
    });
    if (date) params.set("date", date);
    if (Array.isArray(propTypes)) params.set("prop_types", propTypes.join(","));
    return request(`/model/results?${params}`, {
      timeoutMs: market === "player_props" ? 75000 : 30000,
    });
  },
  projectionBoard(startDate, days = 7) {
    return cache.remember(
      `mlb:projection-board:${startDate}:${days}`,
      1_000,
      () =>
        request(
          `/projection-board?start_date=${encodeURIComponent(startDate)}&days=${days}`,
          { timeoutMs: 105_000 },
        ),
    );
  },
  playerProps(startDate, days = 1, refresh = false) {
    const path = `/player-props?start_date=${encodeURIComponent(startDate)}&days=${days}${refresh ? "&refresh=1" : ""}`;
    if (refresh) {
      cache.clear(`mlb:player-props:${startDate}:${days}`);
      return request(path, { timeoutMs: 105_000 });
    }
    return cache.remember(
      `mlb:player-props:${startDate}:${days}`,
      30_000,
      () => request(path, { timeoutMs: 105_000 }),
    );
  },
  playerPropGuarantees(minimumSamples = 1, search = "", propTypes) {
    const params = new URLSearchParams({ minimum_samples: String(minimumSamples) });
    if (search) params.set("search", search);
    if (Array.isArray(propTypes)) params.set("prop_types", propTypes.join(","));
    return request(`/player-props/guarantees?${params}`, { timeoutMs: 30000 });
  },
  recordPlayerPropBuild(payload) {
    return request("/player-props/build-snapshots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  games(date) {
    return cache.remember(`mlb:games:${date}`, 10_000, () =>
      request(`/games?date=${date}`),
    );
  },
  game(id) {
    return cache.remember(`mlb:game:${id}`, 5_000, () =>
      request(`/games/${id}`, { timeoutMs: 60000 }),
    );
  },
  gameSummary(id) {
    return cache.remember(`mlb:game-summary:${id}`, 60_000, () =>
      request(`/games/${id}/summary`),
    );
  },
  searchPlayers(query) {
    return cache.remember(
      `mlb:players:${query.toLowerCase()}`,
      60 * 60_000,
      () => request(`/players/search?q=${encodeURIComponent(query)}`),
    );
  },
  player(id) {
    return cache.remember(`mlb:player:${id}`, 15 * 60_000, () =>
      request(`/players/${id}`),
    );
  },
  teams() {
    return cache.remember("mlb:teams", 10 * 60_000, () => request("/teams"));
  },
  players() {
    return cache.remember("mlb:players:directory", 30 * 60_000, () =>
      request("/players"),
    );
  },
  team(id) {
    return cache.remember(`mlb:team:${id}`, 10 * 60_000, () =>
      request(`/teams/${id}`),
    );
  },
  slips: () => request("/slips"),
  importSlip: (payload) =>
    request("/slips/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  parseSlip: (payload) =>
    request("/slips/parse", {
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
      timeoutMs: 120000,
    }),
  normalizeMelbetHistory: (payload) =>
    request("/alter-ego/normalize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  normalizeMelbetHistoryBatch: (payload) =>
    request("/alter-ego/normalize-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      timeoutMs: 120000,
    }),
  analyseMelbetHistory: (slips) =>
    request("/alter-ego/analyse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slips }),
      timeoutMs: 120000,
    }),
};
