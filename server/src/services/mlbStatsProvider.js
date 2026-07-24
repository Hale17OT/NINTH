import { cache } from "./cache.js";

const baseUrl = process.env.MLB_STATS_URL || "http://127.0.0.1:3002";

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      ...options,
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
    return request(`/model/results?${params}`);
  },
  projectionBoard(startDate, days = 7) {
    return cache.remember(
      `mlb:projection-board:${startDate}:${days}`,
      1_000,
      () =>
        request(
          `/projection-board?start_date=${encodeURIComponent(startDate)}&days=${days}`,
        ),
    );
  },
  playerProps(startDate, days = 1, refresh = false) {
    const path = `/player-props?start_date=${encodeURIComponent(startDate)}&days=${days}${refresh ? "&refresh=1" : ""}`;
    if (refresh) {
      cache.clear(`mlb:player-props:${startDate}:${days}`);
      return request(path);
    }
    return cache.remember(
      `mlb:player-props:${startDate}:${days}`,
      30_000,
      () => request(path),
    );
  },
  games(date) {
    return cache.remember(`mlb:games:${date}`, 10_000, () =>
      request(`/games?date=${date}`),
    );
  },
  game(id) {
    return cache.remember(`mlb:game:${id}`, 5_000, () =>
      request(`/games/${id}`),
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
};
