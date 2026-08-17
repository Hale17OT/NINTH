export const sportLabel = sport => ({
  baseball: 'MLB', football: 'Football', 'american-football': 'NFL',
  basketball: 'NBA', esports: 'Esports',
}[sport] || sport)

export const sportUnit = sport => ({ football: 'match', 'american-football': 'game', basketball: 'game', esports: 'series' }[sport] || 'game')

export const entityRoute = (sport, scope, entity, extra = {}) => {
  const id = typeof entity === 'object' ? entity?.id : entity
  const query = { ...extra }
  if (typeof entity === 'object') {
    if (entity.competitionId && !query.competition) query.competition = entity.competitionId
    if (entity.teamId && !query.team) query.team = entity.teamId
    if (sport === 'esports' && entity.competitionId && !query.discipline) query.discipline = entity.competitionId
  }
  return { path: `/${sport}/${scope}/${encodeURIComponent(String(id || ''))}`, query }
}

export const identityInitials = identity => String(identity?.code || identity?.shortName || identity?.name || '?')
  .split(/\s+/).map(value => value[0]).join('').slice(0, 4).toUpperCase()

const canonicalCodes = {
  nfl: { JAC: 'jax', LA: 'lar', LAR: 'lar', LV: 'lv', OAK: 'lv', SD: 'lac', LAC: 'lac', STL: 'lar', WSH: 'wsh', WAS: 'wsh' },
  nba: { BRK: 'bkn', CHO: 'cha', NOH: 'no', NOK: 'no', NOP: 'no', PHO: 'phx', SAN: 'sas', UTA: 'utah' },
}
export const resolveTeamIdentity = identity => {
  const value = identity || {}, rawId = String(value.id || ''), [namespace, suffix] = rawId.includes(':') ? rawId.split(':', 2) : ['', '']
  const code = String(suffix || value.code || '').toUpperCase()
  let generated = null
  if (namespace === 'nfl' && code) generated = `https://a.espncdn.com/i/teamlogos/nfl/500/${canonicalCodes.nfl[code] || code.toLowerCase()}.png`
  if (namespace === 'nba' && code) generated = `https://a.espncdn.com/i/teamlogos/nba/500/${canonicalCodes.nba[code] || code.toLowerCase()}.png`
  return { ...value, code: value.code || code || identityInitials(value), badge: value.badge || value.logo || generated, canonicalKey: `${namespace || 'generic'}:${code || String(value.name || '').toLowerCase().replace(/\W+/g, '-')}`, fallback: !(value.badge || value.logo || generated) }
}

export const probability = value => `${(Number(value || 0) * 100).toFixed(1)}%`
export const metricValue = (value, digits = 1) => value == null || Number.isNaN(Number(value)) ? '—' : Number(value).toFixed(digits)
export const sentenceCase = value => String(value || '').replaceAll('_', ' ').replace(/([A-Z])/g, ' $1').replace(/^./, letter => letter.toUpperCase())

export const gamePrediction = game => {
  const markets = game?.prediction?.markets || {}
  const rows = Object.entries(markets).filter(([, value]) => Number.isFinite(Number(value)))
  if (!rows.length) return null
  const [market, value] = rows.sort((a, b) => Number(b[1]) - Number(a[1]))[0]
  const names = {
    home_win: `${game.home?.name} win`, away_win: `${game.away?.name} win`, draw: 'Draw',
    over_2_5: 'Over 2.5 goals', under_2_5: 'Under 2.5 goals', both_teams_score: 'Both teams score',
    over_total: `Over ${game.prediction?.total_line}`, under_total: `Under ${game.prediction?.total_line}`,
    home_spread: `${game.home?.name} spread`, away_spread: `${game.away?.name} spread`,
  }
  return { market, label: names[market] || sentenceCase(market), probability: Number(value) }
}
