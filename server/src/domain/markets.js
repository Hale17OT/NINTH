export const MarketType = Object.freeze({
  MATCH_WINNER_3WAY: 'MATCH_WINNER_3WAY', HOME_WIN: 'HOME_WIN', DRAW: 'DRAW', AWAY_WIN: 'AWAY_WIN',
  DRAW_NO_BET: 'DRAW_NO_BET', DOUBLE_CHANCE: 'DOUBLE_CHANCE', TOTAL_GOALS: 'TOTAL_GOALS',
  ASIAN_TOTAL: 'ASIAN_TOTAL', BTTS: 'BTTS', ASIAN_HANDICAP: 'ASIAN_HANDICAP', TEAM_TOTAL: 'TEAM_TOTAL',
  CORRECT_SCORE: 'CORRECT_SCORE', CORNERS: 'CORNERS', CARDS: 'CARDS',
  PLAYER_SHOTS: 'PLAYER_SHOTS', PLAYER_SHOTS_ON_TARGET: 'PLAYER_SHOTS_ON_TARGET',
  PLAYER_GOALS: 'PLAYER_GOALS', PLAYER_ASSISTS: 'PLAYER_ASSISTS',
  MONEYLINE: 'MONEYLINE', SPREAD: 'SPREAD', GAME_TOTAL: 'GAME_TOTAL',
  PLAYER_PASSING_YARDS: 'PLAYER_PASSING_YARDS', PLAYER_PASSING_TDS: 'PLAYER_PASSING_TDS',
  PLAYER_INTERCEPTIONS: 'PLAYER_INTERCEPTIONS', PLAYER_RUSHING_YARDS: 'PLAYER_RUSHING_YARDS',
  PLAYER_RUSH_ATTEMPTS: 'PLAYER_RUSH_ATTEMPTS', PLAYER_RECEIVING_YARDS: 'PLAYER_RECEIVING_YARDS',
  PLAYER_RECEPTIONS: 'PLAYER_RECEPTIONS', ANYTIME_TOUCHDOWN: 'ANYTIME_TOUCHDOWN',
})

const selections = new Set(['HOME', 'DRAW', 'AWAY', 'OVER', 'UNDER', 'YES', 'NO'])
export const canonicalSelection = value => {
  const normalized = String(value || '').trim().toUpperCase().replace(/[\s-]+/g, '_')
  return selections.has(normalized) ? normalized : normalized
}

export function canonicalMarket(input) {
  const market = String(input.market || '').toUpperCase()
  if (!Object.hasOwn(MarketType, market)) throw new Error(`Unsupported canonical market ${market || '(empty)'}`)
  const line = input.line == null || input.line === '' ? null : Number(input.line)
  if (line != null && !Number.isFinite(line)) throw new Error('Canonical market line must be numeric')
  return {
    sport: String(input.sport || '').toLowerCase(), eventId: String(input.eventId || ''),
    market, selection: canonicalSelection(input.selection), line,
    participantId: input.participantId == null ? null : String(input.participantId),
    period: String(input.period || 'FULL_TIME').toUpperCase(),
  }
}

export function canonicalMarketId(input) {
  const row = canonicalMarket(input)
  return [row.sport, row.eventId, row.period, row.market, row.participantId || '-', row.selection || '-', row.line ?? '-'].join(':')
}

export const fairDecimalOdds = probability => {
  const value = Number(probability)
  return value > 0 && value < 1 ? 1 / value : null
}

export const removeVig = prices => {
  const valid = prices.map(Number)
  if (!valid.length || valid.some(value => !Number.isFinite(value) || value <= 1)) return prices.map(() => null)
  const implied = valid.map(value => 1 / value), margin = implied.reduce((sum, value) => sum + value, 0)
  return implied.map(value => value / margin)
}
