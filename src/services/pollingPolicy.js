export const LIVE_VIEW_REFRESH_MS = 10_000
export const LIVE_SCOREBOARD_REFRESH_MS = 60_000
export const PREGAME_REFRESH_MS = 5 * 60_000

export const scoreboardRefreshMs = hasLiveGames =>
  hasLiveGames ? LIVE_SCOREBOARD_REFRESH_MS : PREGAME_REFRESH_MS

