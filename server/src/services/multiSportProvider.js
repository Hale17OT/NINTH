import { cache } from './cache.js'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { asyncBufferFromUrl, parquetReadObjects } from 'hyparquet'
import { esportsDirectory, esportsStatus } from './esportsProvider.js'

const SPORTS_DB_KEY = process.env.THESPORTSDB_API_KEY || '123'
const SPORTS_DB = `https://www.thesportsdb.com/api/v1/json/${SPORTS_DB_KEY}`
const FOOTBALL_DATA_CSV = 'https://www.football-data.co.uk/mmz4281'
const FPL_API = 'https://fantasy.premierleague.com/api'
const FOOTBALL_DATA_ORG = 'https://api.football-data.org/v4'
const NFLVERSE_SCHEDULE = 'https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv'
const HOUR = 60 * 60 * 1000
let sportsDbQueue = Promise.resolve()
let sportsDbLastRequest = 0

const configured = (...names) => names.some(name => Boolean(process.env[name]))
const sourceStatus = sport => {
  const presentation = {
    id: 'presentation', name: 'TheSportsDB', role: 'Fixtures, results, teams and player presentation',
    env: 'THESPORTSDB_API_KEY', configured: true, state: SPORTS_DB_KEY === '123' ? 'limited' : 'ready',
    detail: SPORTS_DB_KEY === '123' ? 'Public key connected; response depth and request volume are limited.' : 'Custom presentation key connected.',
  }
  if (sport === 'football') return [
    presentation,
    { id: 'fpl-open', name: 'Fantasy Premier League', role: 'Current Premier League fixtures, clubs, players and availability', env: 'No key', configured: true, state: 'ready', detail: 'Keyless read-only season feed; cached to avoid unnecessary requests.' },
    { id: 'open-results', name: 'Football-Data.co.uk', role: 'Top-five fixtures, results, shots, corners and discipline', env: 'No key', configured: true, state: 'ready', detail: 'Odds columns are discarded. Rolling shot-quality, territorial and discipline features are locked before each result.' },
    { id: 'open-events', name: 'StatsBomb Open Data', role: 'xG, pressures, progressive actions, events and selected 360 data', env: 'No key', configured: true, state: 'available', detail: 'The collector enriches only openly covered league-seasons and reports the missing coverage explicitly.' },
    { id: 'free-supplement', name: 'football-data.org free tier', role: 'Top-five clubs, squads and competition supplement', env: 'NINTH_FOOTBALL_DATA_TOKEN', configured: configured('NINTH_FOOTBALL_DATA_TOKEN'), state: configured('NINTH_FOOTBALL_DATA_TOKEN') ? 'ready' : 'optional', detail: 'A free account token completes squad coverage outside the Premier League; no paid plan is required.' },
  ]
  if (sport === 'american-football') return [
    presentation,
    { id: 'historical', name: 'nflverse', role: 'Play-by-play EPA, success, explosives, pressure, schedules and current market anchors', env: 'Open data', configured: true, state: 'ready', detail: 'Three recent seasons are aggregated before each game. Pregame prices are displayed and lines are evaluated as thresholds, but neither is fitted as a forecast feature.' },
    { id: 'tracking', name: 'Tracking / availability supplement', role: 'Tracking aggregates, injuries and confirmed participants', env: 'Optional', configured: false, state: 'optional', detail: 'Improves the model but does not block the open nflverse baseline.' },
  ]
  if (sport === 'basketball') return [
    presentation,
    { id: 'official', name: 'NBA Stats + ESPN open mirror', role: 'Possessions, four factors, shot profile and possession-value components', env: 'No key', configured: true, state: 'ready', detail: '20k+ team-game advanced rows are available through the keyless parquet mirror and joined point-in-time.' },
    { id: 'availability', name: 'Availability / market supplement', role: 'Point-in-time injuries, minutes expectations and prices', env: 'Optional', configured: false, state: 'optional', detail: 'Improves player props but does not block an open team-market baseline.' },
  ]
  return []
}

const modelReports = sport => {
  const directories = sport === 'esports' ? ['valorant', 'cs2', 'lol'] : [sport]
  return directories.flatMap(directory => {
    const path = join(process.cwd(), 'ml', 'artifacts', 'multisport', directory)
    if (!existsSync(path)) return []
    return readdirSync(path).filter(file => file.endsWith('.json')).flatMap(file => {
      try {
        const report = JSON.parse(readFileSync(join(path, file), 'utf8'))
        if (report.sport === 'american-football' && ['over_total', 'over_44_5'].includes(report.market)) return []
        if (report.sport === 'american-football' && report.market === 'joint_score_distribution') {
          return ['spread', 'total'].map(market => ({
            sport: report.sport, market, status: report.status, method: report.method,
            samples: report.samples, metrics: report.line_aware_audit?.[market] || {}, baseline: { brier: .25 },
            promotion: report.promotion,
            historicalReadiness: { passed: report.historical_readiness?.[market] === true },
            oddsIndependent: report.odds_used_as_features === false,
            timeRange: report.time_range, datasetSha256: report.dataset_sha256,
          }))
        }
        return [{
          sport: report.sport, market: report.market, status: report.status, method: report.method,
          samples: report.samples, metrics: report.untouched_candidate,
          baseline: report.untouched_climatology, promotion: report.promotion,
          historical: report.historical_walk_forward, historicalReadiness: report.historical_readiness,
          oddsIndependent: report.odds_independent === true,
          timeRange: report.time_range, datasetSha256: report.dataset_sha256,
        }]
      } catch { return [] }
    })
  }).sort((a, b) => a.market.localeCompare(b.market))
}
const sportPredictions = sport => {
  const path = join(process.cwd(), 'ml', 'data', 'multisport', sport, 'predictions.json')
  if (!existsSync(path)) return new Map()
  try {
    const payload = JSON.parse(readFileSync(path, 'utf8'))
    return new Map((payload.predictions || []).map(row => [String(row.event_id), row]))
  } catch { return new Map() }
}
const sportPredictionPayload = sport => {
  const path = join(process.cwd(), 'ml', 'data', 'multisport', sport, 'predictions.json')
  if (!existsSync(path)) return {}
  try { return JSON.parse(readFileSync(path, 'utf8')) } catch { return {} }
}

export const competitionCatalog = {
  football: [
    { id: '4328', code: 'EPL', name: 'Premier League', country: 'England', group: 'Domestic league' },
    { id: '4335', code: 'LAL', name: 'La Liga', country: 'Spain', group: 'Domestic league' },
    { id: '4331', code: 'BUN', name: 'Bundesliga', country: 'Germany', group: 'Domestic league' },
    { id: '4332', code: 'SEA', name: 'Serie A', country: 'Italy', group: 'Domestic league' },
    { id: '4334', code: 'L1', name: 'Ligue 1', country: 'France', group: 'Domestic league' },
    { id: '4480', code: 'UCL', name: 'UEFA Champions League', country: 'Europe', group: 'European competition' },
    { id: '4481', code: 'UEL', name: 'UEFA Europa League', country: 'Europe', group: 'European competition' },
    { id: '5071', code: 'UECL', name: 'UEFA Conference League', country: 'Europe', group: 'European competition' },
    { id: '4482', code: 'FAC', name: 'FA Cup', country: 'England', group: 'Domestic cup' },
    { id: '4570', code: 'EFL', name: 'EFL Cup', country: 'England', group: 'Domestic cup' },
    { id: '4483', code: 'CDR', name: 'Copa del Rey', country: 'Spain', group: 'Domestic cup' },
    { id: '4485', code: 'DFB', name: 'DFB-Pokal', country: 'Germany', group: 'Domestic cup' },
    { id: '4506', code: 'CIT', name: 'Coppa Italia', country: 'Italy', group: 'Domestic cup' },
    { id: '4484', code: 'CDF', name: 'Coupe de France', country: 'France', group: 'Domestic cup' },
  ],
  'american-football': [{ id: '4391', code: 'NFL', name: 'NFL', country: 'United States', group: 'League' }],
  basketball: [{ id: '4387', code: 'NBA', name: 'NBA', country: 'United States', group: 'League' }],
  esports: [
    { id: 'valorant', code: 'VAL', name: 'Valorant', country: 'International', group: 'Discipline' },
    { id: 'cs2', code: 'CS2', name: 'Counter-Strike 2', country: 'International', group: 'Discipline' },
    { id: 'lol', code: 'LOL', name: 'League of Legends', country: 'International', group: 'Discipline' },
  ],
}

const json = async (url, headers = {}) => {
  const response = await fetch(url, { headers: { Accept: 'application/json', 'User-Agent': 'NINTH-Analytics/2.0', ...headers } })
  if (!response.ok) throw new Error(`Provider request failed (${response.status})`)
  return response.json()
}
const textResponse = async url => {
  const response = await fetch(url, { headers: { Accept: 'text/csv,*/*', 'User-Agent': 'NINTH-Analytics/2.0' } })
  if (!response.ok) throw new Error(`Provider request failed (${response.status})`)
  return response.text()
}
const parseCsvLine = line => {
  const values = []
  let value = '', quoted = false
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index]
    if (character === '"' && quoted && line[index + 1] === '"') { value += '"'; index += 1 }
    else if (character === '"') quoted = !quoted
    else if (character === ',' && !quoted) { values.push(value); value = '' }
    else value += character
  }
  values.push(value)
  return values
}
const parseCsv = body => {
  const lines = String(body || '').replace(/^\uFEFF/, '').split(/\r?\n/).filter(Boolean)
  if (!lines.length) return []
  const headers = parseCsvLine(lines[0])
  return lines.slice(1).map(line => {
    const values = parseCsvLine(line)
    return Object.fromEntries(headers.map((header, index) => [header, values[index] || '']))
  })
}
const footballCsvCodes = { '4328': 'E0', '4335': 'SP1', '4331': 'D1', '4332': 'I1', '4334': 'F1' }
const footballDataOrgCodes = { '4328': 'PL', '4335': 'PD', '4331': 'BL1', '4332': 'SA', '4334': 'FL1', '4480': 'CL', '4481': 'EL' }
const FPL_COMPETITION_ID = '4328'
const nflNames = {
  ARI:'Arizona Cardinals', ATL:'Atlanta Falcons', BAL:'Baltimore Ravens', BUF:'Buffalo Bills', CAR:'Carolina Panthers', CHI:'Chicago Bears', CIN:'Cincinnati Bengals', CLE:'Cleveland Browns', DAL:'Dallas Cowboys', DEN:'Denver Broncos', DET:'Detroit Lions', GB:'Green Bay Packers', HOU:'Houston Texans', IND:'Indianapolis Colts', JAX:'Jacksonville Jaguars', KC:'Kansas City Chiefs', LA:'Los Angeles Rams', LAC:'Los Angeles Chargers', LV:'Las Vegas Raiders', MIA:'Miami Dolphins', MIN:'Minnesota Vikings', NE:'New England Patriots', NO:'New Orleans Saints', NYG:'New York Giants', NYJ:'New York Jets', PHI:'Philadelphia Eagles', PIT:'Pittsburgh Steelers', SEA:'Seattle Seahawks', SF:'San Francisco 49ers', TB:'Tampa Bay Buccaneers', TEN:'Tennessee Titans', WAS:'Washington Commanders',
}
const nbaNames = {
  ATL:'Atlanta Hawks', BOS:'Boston Celtics', BKN:'Brooklyn Nets', CHA:'Charlotte Hornets', CHI:'Chicago Bulls', CLE:'Cleveland Cavaliers', DAL:'Dallas Mavericks', DEN:'Denver Nuggets', DET:'Detroit Pistons', GSW:'Golden State Warriors', HOU:'Houston Rockets', IND:'Indiana Pacers', LAC:'Los Angeles Clippers', LAL:'Los Angeles Lakers', MEM:'Memphis Grizzlies', MIA:'Miami Heat', MIL:'Milwaukee Bucks', MIN:'Minnesota Timberwolves', NOP:'New Orleans Pelicans', NYK:'New York Knicks', OKC:'Oklahoma City Thunder', ORL:'Orlando Magic', PHI:'Philadelphia 76ers', PHX:'Phoenix Suns', POR:'Portland Trail Blazers', SAC:'Sacramento Kings', SAS:'San Antonio Spurs', TOR:'Toronto Raptors', UTA:'Utah Jazz', WAS:'Washington Wizards',
}
const seasonSlugs = () => {
  const now = new Date(), year = now.getUTCFullYear(), start = now.getUTCMonth() >= 6 ? year : year - 1
  const slug = value => `${String(value).slice(-2)}${String(value + 1).slice(-2)}`
  return [slug(start), slug(start - 1)]
}
const isoFootballDate = value => {
  const [day, month, year] = String(value || '').split(/[/-]/)
  if (!year) return ''
  const fullYear = year.length === 2 ? Number(year) + (Number(year) > 70 ? 1900 : 2000) : Number(year)
  return `${fullYear}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}
const teamSlug = value => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '-')
const sportsDbJson = url => {
  const run = sportsDbQueue.then(async () => {
    const pause = Math.max(0, 275 - (Date.now() - sportsDbLastRequest))
    if (pause) await new Promise(resolve => setTimeout(resolve, pause))
    sportsDbLastRequest = Date.now()
    return json(url)
  })
  sportsDbQueue = run.catch(() => null)
  return run
}
const get = (path, ttl = HOUR) => cache.remember(`multisport:${path}`, ttl, () => sportsDbJson(`${SPORTS_DB}/${path}`))
const fplBootstrap = () => cache.remember('multisport:fpl:bootstrap', HOUR, () => json(`${FPL_API}/bootstrap-static/`))
const fplFixtures = () => cache.remember('multisport:fpl:fixtures', HOUR, () => json(`${FPL_API}/fixtures/`))
const footballDataOrgTeams = competition => {
  const token = process.env.NINTH_FOOTBALL_DATA_TOKEN, code = footballDataOrgCodes[competition.id]
  if (!token || !code) return Promise.resolve([])
  return cache.remember(`multisport:football-data-org:${code}`, 6 * HOUR, async () => {
    const payload = await json(`${FOOTBALL_DATA_ORG}/competitions/${code}/teams`, { 'X-Auth-Token': token })
    return payload.teams || []
  })
}
const dateValue = row => row.dateEvent || row.strTimestamp?.slice(0, 10) || ''
const sortDirectoryEvents = (a, b) => {
  const today = new Date().toISOString().slice(0, 10)
  const aUpcoming = a.status !== 'Completed' && a.date >= today
  const bUpcoming = b.status !== 'Completed' && b.date >= today
  if (aUpcoming !== bUpcoming) return aUpcoming ? -1 : 1
  const left = `${a.date}T${a.time}`, right = `${b.date}T${b.time}`
  return aUpcoming ? left.localeCompare(right) : right.localeCompare(left)
}

const normalizeEvent = (row, competition) => ({
  id: String(row.idEvent), competitionId: String(row.idLeague || competition.id), competition: row.strLeague || competition.name,
  competitionCode: competition.code, group: competition.group, round: row.intRound || row.strRound || row.strGroup || '—',
  date: dateValue(row), time: row.strTime || row.strTimestamp?.slice(11, 16) || 'TBD', timestamp: row.strTimestamp || null,
  status: row.strStatus || (row.intHomeScore != null ? 'Completed' : 'Scheduled'), venue: row.strVenue || 'Venue TBD',
  home: { id: row.idHomeTeam, name: row.strHomeTeam, badge: row.strHomeTeamBadge || null, score: row.intHomeScore },
  away: { id: row.idAwayTeam, name: row.strAwayTeam, badge: row.strAwayTeamBadge || null, score: row.intAwayScore },
  sourceUrl: row.strEventAlternate || null,
})

const normalizeFootballCsvEvent = (row, competition, season) => {
  const date = isoFootballDate(row.Date)
  const completed = row.FTHG !== '' && row.FTAG !== ''
  return {
    id: `fdco:${competition.id}:${season}:${date}:${teamSlug(row.HomeTeam)}:${teamSlug(row.AwayTeam)}`,
    competitionId: competition.id, competition: competition.name, competitionCode: competition.code,
    group: competition.group, round: row.Round || 'League', date, time: row.Time || 'TBD',
    timestamp: date && row.Time ? `${date}T${row.Time}:00Z` : null,
    status: completed ? 'Completed' : 'Scheduled', venue: 'Venue listed on club page',
    home: { id: `fdco:${teamSlug(row.HomeTeam)}`, name: row.HomeTeam, badge: null, score: completed ? Number(row.FTHG) : null },
    away: { id: `fdco:${teamSlug(row.AwayTeam)}`, name: row.AwayTeam, badge: null, score: completed ? Number(row.FTAG) : null },
    prices: {
      home: Number(row.B365H || row.AvgH || 0) || null, draw: Number(row.B365D || row.AvgD || 0) || null,
      away: Number(row.B365A || row.AvgA || 0) || null, over25: Number(row.B365O25 || row.AvgO25 || 0) || null,
      under25: Number(row.B365U25 || row.AvgU25 || 0) || null,
    },
    sourceUrl: 'https://www.football-data.co.uk/data.php', source: 'Football-Data.co.uk',
  }
}

async function openFplEvents(competition) {
  if (String(competition.id) !== FPL_COMPETITION_ID) return []
  const [bootstrap, fixtures] = await Promise.all([fplBootstrap(), fplFixtures()])
  const teams = new Map((bootstrap.teams || []).map(team => [Number(team.id), team]))
  return (fixtures || []).map(row => {
    const home = teams.get(Number(row.team_h)), away = teams.get(Number(row.team_a))
    const kickoff = row.kickoff_time || ''
    return {
      id: `fpl:${row.id}`, competitionId: FPL_COMPETITION_ID, competition: 'Premier League', competitionCode: 'EPL',
      group: 'Domestic league', round: `GAMEWEEK ${row.event || '—'}`, date: kickoff.slice(0, 10), time: kickoff.slice(11, 16) || 'TBD',
      timestamp: kickoff || null, status: row.finished ? 'Completed' : row.started ? 'Live' : 'Scheduled', venue: 'Premier League venue',
      home: { id: `fpl:${home?.id}`, name: home?.name || 'TBD', badge: home?.code ? `https://resources.premierleague.com/premierleague/badges/70/t${home.code}.png` : null, score: row.team_h_score },
      away: { id: `fpl:${away?.id}`, name: away?.name || 'TBD', badge: away?.code ? `https://resources.premierleague.com/premierleague/badges/70/t${away.code}.png` : null, score: row.team_a_score },
      source: 'Fantasy Premier League', sourceUrl: 'https://fantasy.premierleague.com/',
    }
  })
}

async function openFplTeams() {
  const bootstrap = await fplBootstrap()
  return (bootstrap.teams || []).map(team => ({
    id: `fpl:${team.id}`, name: team.name, shortName: team.short_name || team.name, code: team.short_name,
    competitionId: FPL_COMPETITION_ID, competition: 'Premier League', country: 'England', venue: 'Premier League venue',
    formed: null, badge: team.code ? `https://resources.premierleague.com/premierleague/badges/70/t${team.code}.png` : null,
    statistics: { strength: Number(team.strength || 0), homeAttack: Number(team.strength_attack_home || 0), awayAttack: Number(team.strength_attack_away || 0), homeDefence: Number(team.strength_defence_home || 0), awayDefence: Number(team.strength_defence_away || 0) },
  }))
}

async function openFplPlayers() {
  const bootstrap = await fplBootstrap()
  const teams = new Map((bootstrap.teams || []).map(team => [Number(team.id), team]))
  const positions = new Map((bootstrap.element_types || []).map(type => [Number(type.id), type.singular_name]))
  return (bootstrap.elements || []).map(row => {
    const team = teams.get(Number(row.team))
    return {
      id: `fpl:${row.id}`, name: [row.first_name, row.second_name].filter(Boolean).join(' '), teamId: `fpl:${row.team}`,
      team: team?.name || 'Premier League', position: positions.get(Number(row.element_type)) || 'Player', nationality: '—',
      born: null, height: null, weight: null, number: row.squad_number || null,
      image: row.photo ? `https://resources.premierleague.com/premierleague/photos/players/110x140/p${String(row.photo).replace('.jpg', '')}.png` : null,
      competition: 'Premier League', status: row.status, availability: row.chance_of_playing_next_round,
      statistics: { starts: Number(row.starts || 0), minutes: Number(row.minutes || 0), goals: Number(row.goals_scored || 0), assists: Number(row.assists || 0), expectedGoals: Number(row.expected_goals || 0), expectedAssists: Number(row.expected_assists || 0) },
    }
  }).sort((a, b) => a.name.localeCompare(b.name))
}

const normalizeFootballDataOrgTeam = (row, competition) => ({
  id: `fdo:${row.id}`, name: row.shortName || row.name, shortName: row.shortName || row.name, code: row.tla,
  competitionId: competition.id, competition: competition.name, country: competition.country,
  venue: row.venue || 'Venue TBD', formed: row.founded || null, badge: row.crest || null, website: row.website || null,
})

async function openFootballDataOrgPlayers(competitions) {
  const batches = await Promise.all(competitions.map(async competition => {
    const teams = await footballDataOrgTeams(competition).catch(() => [])
    return teams.flatMap(team => (team.squad || []).map(player => ({
      id: `fdo:${player.id}`, name: player.name, teamId: `fdo:${team.id}`, team: team.shortName || team.name,
      position: player.position || 'Player', nationality: player.nationality || '—', born: player.dateOfBirth || null,
      height: null, weight: null, number: player.shirtNumber || null, image: null, competition: competition.name,
    })))
  }))
  return batches.flat()
}

async function openFootballLeagueEvents(competition, allowCompletedFallback = false) {
  const code = footballCsvCodes[competition.id]
  if (!code) return []
  let fallback = []
  for (const season of seasonSlugs()) {
    try {
      const body = await cache.remember(`football-csv:${season}:${code}`, 30 * 60 * 1000, () => textResponse(`${FOOTBALL_DATA_CSV}/${season}/${code}.csv`))
      const events = parseCsv(body).filter(row => row.Div === code && row.HomeTeam && row.AwayTeam && row.Date).map(row => normalizeFootballCsvEvent(row, competition, season))
      if (events.some(event => event.status === 'Scheduled')) return events
      if (!fallback.length) fallback = events
    } catch { /* not every league publishes its new-season file on the same date */ }
  }
  return allowCompletedFallback ? fallback : []
}

async function openNflEvents(options = {}) {
  const body = await cache.remember('nflverse:schedules', 6 * HOUR, () => textResponse(NFLVERSE_SCHEDULE))
  const rows = parseCsv(body)
  const requestedSeason = Number(options.season || new Date().getUTCFullYear())
  const seasons = new Set([requestedSeason, requestedSeason - 1])
  return rows.filter(row => seasons.has(Number(row.season))).map(row => {
    const completed = row.home_score !== '' && row.away_score !== ''
    return {
      id: row.game_id, competitionId: '4391', competition: 'NFL', competitionCode: 'NFL',
      group: row.game_type === 'REG' ? 'Regular season' : row.game_type === 'POST' ? 'Postseason' : 'Preseason',
      round: `${row.game_type || 'NFL'} · WEEK ${row.week || '—'}`, date: row.gameday, time: row.gametime || 'TBD',
      timestamp: row.gameday && row.gametime ? `${row.gameday}T${row.gametime}:00` : null,
      status: completed ? 'Completed' : 'Scheduled', venue: row.stadium || 'Venue TBD',
      home: { id: `nfl:${row.home_team}`, name: nflNames[row.home_team] || row.home_team, badge: null, score: completed ? Number(row.home_score) : null },
      away: { id: `nfl:${row.away_team}`, name: nflNames[row.away_team] || row.away_team, badge: null, score: completed ? Number(row.away_score) : null },
      prices: { home: Number(row.home_moneyline || 0) || null, away: Number(row.away_moneyline || 0) || null, totalLine: Number(row.total_line || 0) || null },
      context: { homeRest: Number(row.home_rest || 0) || null, awayRest: Number(row.away_rest || 0) || null, roof: row.roof, surface: row.surface, temperature: Number(row.temp || 0) || null, wind: Number(row.wind || 0) || null },
      source: 'nflverse',
    }
  }).sort(sortDirectoryEvents)
}

const normalizeTeam = (row, competition) => ({
  id: String(row.idTeam), name: row.strTeam, shortName: row.strTeamShort || row.strTeam, code: row.strTeamBadge ? row.strTeamShort : row.strTeam?.slice(0, 3).toUpperCase(),
  competitionId: String(row.idLeague || competition?.id || ''), competition: row.strLeague || competition?.name || '', country: row.strCountry || competition?.country,
  venue: row.strStadium || 'Venue TBD', formed: row.intFormedYear || null, badge: row.strBadge || row.strTeamBadge || null,
  banner: row.strBanner || null, description: row.strDescriptionEN || '', website: row.strWebsite || null,
})

const normalizePlayer = (row, team) => ({
  id: String(row.idPlayer), name: row.strPlayer, teamId: String(row.idTeam || team.id), team: row.strTeam || team.name,
  position: row.strPosition || 'Player', nationality: row.strNationality || '—', born: row.dateBorn || null,
  height: row.strHeight || null, weight: row.strWeight || null, number: row.strNumber || null,
  image: row.strCutout || row.strThumb || null, description: row.strDescriptionEN || '',
})

async function leagueEvents(competition, sport, requestedSeason) {
  const seasons = requestedSeason ? [requestedSeason] : []
  let successfulRequests = 0
  let lastError = null
  const collected = []
  let next = null, past = null
  try { next = await get(`eventsnextleague.php?id=${competition.id}`, 15 * 60 * 1000); successfulRequests += 1 }
  catch (error) { lastError = error }
  try { past = await get(`eventspastleague.php?id=${competition.id}`, 15 * 60 * 1000); successfulRequests += 1 }
  catch (error) { lastError = error }
  collected.push(...(past?.events || []), ...(next?.events || []))
  for (const season of seasons) {
    let payload = null
    try { payload = await get(`eventsseason.php?id=${competition.id}&s=${encodeURIComponent(season)}`, 30 * 60 * 1000); successfulRequests += 1 }
    catch (error) { lastError = error }
    collected.push(...(payload?.events || []))
  }
  if (!successfulRequests && lastError) throw lastError
  const unique = new Map(collected.map(row => [String(row.idEvent), row]))
  return [...unique.values()].map(row => normalizeEvent(row, competition))
}

async function sportsDbGames(sport, options) {
  if (sport === 'american-football') return openNflEvents(options)
  const competitions = filterCompetitions(sport, options.competition)
  const batches = await Promise.all(competitions.map(async item => {
    const presentation = await leagueEvents(item, sport, options.season).catch(() => [])
    if (sport !== 'football') return presentation
    const [open, fpl] = await Promise.all([openFootballLeagueEvents(item), openFplEvents(item).catch(() => [])])
    return fpl.length ? fpl : [...presentation, ...open]
  }))
  const unique = new Map(batches.flat().map(row => [row.id, row]))
  return [...unique.values()].sort(sortDirectoryEvents)
}

async function sportsDbTeams(sport, options) {
  const competitions = filterCompetitions(sport, options.competition)
  const batches = await Promise.all(competitions.map(async competition => {
    const [direct, events, historical] = await Promise.all([
      get(`search_all_teams.php?l=${encodeURIComponent(competition.name)}`, 24 * HOUR).catch(() => null),
      sportsDbGames(sport, { ...options, competition: competition.id }).catch(() => []),
      sport === 'football' ? openFootballLeagueEvents(competition, true).catch(() => []) : [],
    ])
    const rows = (direct?.teams || []).map(row => normalizeTeam(row, competition))
    const known = new Set(rows.map(row => row.id))
    ;[...events, ...historical].flatMap(event => [event.home, event.away]).forEach(team => {
      if (!team.id || known.has(String(team.id))) return
      known.add(String(team.id))
      rows.push({
        id: String(team.id), name: team.name, shortName: team.name, code: team.name?.slice(0, 3).toUpperCase(),
        competitionId: competition.id, competition: competition.name, country: competition.country,
        venue: 'Venue available from event detail', formed: null, badge: team.badge || null,
      })
    })
    return rows
  }))
  if (sport === 'football' && configured('NINTH_FOOTBALL_DATA_TOKEN')) {
    const freeTeams = await Promise.all(competitions.map(async competition => (await footballDataOrgTeams(competition).catch(() => [])).map(row => normalizeFootballDataOrgTeam(row, competition))))
    batches.unshift(freeTeams.flat())
  }
  const fplTeams = sport === 'football' && (!options.competition || options.competition === 'all' || String(options.competition).split(',').includes(FPL_COMPETITION_ID)) ? await openFplTeams().catch(() => []) : []
  if (fplTeams.length) batches.unshift(fplTeams)
  if (sport === 'basketball') batches.unshift(Object.entries(nbaNames).map(([code, name]) => ({ id: `nba:${code}`, name, shortName: name, code, competitionId: '4387', competition: 'NBA', country: 'United States', venue: 'NBA arena', formed: null, badge: null })))
  const unique = new Map()
  for (const row of batches.flat()) {
    if (fplTeams.length && String(row.competitionId) === FPL_COMPETITION_ID && !String(row.id).startsWith('fpl:')) continue
    const key = ['american-football', 'basketball'].includes(sport) ? row.name.toLowerCase() : sport === 'football' ? `${row.competitionId}:${teamSlug(row.name).replace(/^man-utd$/, 'man-united').replace(/^spurs$/, 'tottenham')}` : row.id
    const current = unique.get(key)
    const quality = value => Number(Boolean(value?.badge)) * 3 + Number(Boolean(value?.formed)) + Number(Boolean(value?.venue && !/available|NBA arena/i.test(value.venue)))
    if (!current || quality(row) > quality(current)) unique.set(key, row)
  }
  return [...unique.values()].sort((a, b) => a.name.localeCompare(b.name))
}

async function sportsDbPlayers(sport, options) {
  if (sport === 'american-football') {
    const season = Number(options.season || new Date().getUTCFullYear())
    const body = await cache.remember(`nflverse:roster:${season}`, 12 * HOUR, () => textResponse(`https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_${season}.csv`))
    const latest = new Map()
    for (const row of parseCsv(body)) {
      if (!row.full_name || !row.team) continue
      const id = row.gsis_id || row.espn_id || `${row.team}:${row.full_name}`
      const current = latest.get(id)
      if (!current || Number(row.week || 0) >= Number(current.week || 0)) latest.set(id, row)
    }
    return [...latest.values()].map(row => ({
      id: row.gsis_id || row.espn_id || `${row.team}:${row.full_name}`, name: row.full_name,
      teamId: `nfl:${row.team}`, team: nflNames[row.team] || row.team, position: row.position || 'Player',
      nationality: 'United States', born: row.birth_date || null,
      height: row.height ? `${Math.floor(Number(row.height) / 12)}' ${Number(row.height) % 12}"` : null,
      weight: row.weight ? `${row.weight} lb` : null, number: row.jersey_number || null,
      image: row.headshot_url || null, competition: 'NFL', status: row.status_description_abbr || row.status,
    })).sort((a, b) => a.name.localeCompare(b.name))
  }
  if (sport === 'basketball') {
    const season = Number(options.season || new Date().getUTCFullYear())
    const rows = await cache.remember(`open-nba:players:${season}`, 12 * HOUR, async () => {
      const file = await asyncBufferFromUrl({ url: `https://raw.githubusercontent.com/llimllib/nba_data/main/data/players_${season}.parquet` })
      return parquetReadObjects({ file })
    })
    return rows.filter(row => row.player_name && row.team_abbreviation && Number(row.gp || 0) > 0).map(row => ({
      id: String(row.player_id), name: row.player_name, teamId: `nba:${row.team_abbreviation}`,
      team: nbaNames[row.team_abbreviation] || row.team_abbreviation, position: row.position || 'NBA player',
      nationality: row.country || '—', height: row.player_height || null,
      weight: row.player_weight ? `${row.player_weight} lb` : null, number: null,
      image: `https://cdn.nba.com/headshots/nba/latest/1040x760/${row.player_id}.png`, competition: 'NBA',
      statistics: { games: Number(row.gp), pointsPerGame: Number(row.pts_pergame || 0), assistsPerGame: Number(row.ast_pergame || 0), reboundsPerGame: Number(row.reb_pergame || 0), minutesPerGame: Number(row.min_pergame || 0) },
    })).sort((a, b) => a.name.localeCompare(b.name))
  }
  const fplPlayers = sport === 'football' && (!options.competition || options.competition === 'all' || String(options.competition).split(',').includes(FPL_COMPETITION_ID))
    ? await openFplPlayers().catch(() => []) : []
  const footballCompetitions = sport === 'football' ? filterCompetitions(sport, options.competition) : []
  const freePlayers = sport === 'football' && configured('NINTH_FOOTBALL_DATA_TOKEN') ? await openFootballDataOrgPlayers(footballCompetitions) : []
  const teams = await sportsDbTeams(sport, options)
  const freeCovered = new Set(configured('NINTH_FOOTBALL_DATA_TOKEN') ? footballCompetitions.filter(competition => footballDataOrgCodes[competition.id]).map(competition => String(competition.id)) : [])
  const selectedTeams = teams.filter(team => !(sport === 'football' && (String(team.competitionId) === FPL_COMPETITION_ID || freeCovered.has(String(team.competitionId))))).slice(0, SPORTS_DB_KEY === '123' ? 20 : teams.length)
  let successfulRequests = 0, lastError = null
  const batches = await Promise.all(selectedTeams.map(async team => {
    let payload = null
    try {
      let resolved = team
      if (!/^\d+$/.test(String(team.id))) {
        const search = await get(`searchteams.php?t=${encodeURIComponent(team.name)}`, 24 * HOUR)
        const candidate = (search?.teams || []).find(row => row.strTeam?.toLowerCase() === team.name.toLowerCase()) || search?.teams?.[0]
        if (candidate) resolved = normalizeTeam(candidate, { id: team.competitionId, name: team.competition, country: team.country })
      }
      payload = await get(`lookup_all_players.php?id=${resolved.id}`, 24 * HOUR); successfulRequests += 1
      team = resolved
    }
    catch (error) { lastError = error }
    return (payload?.player || payload?.players || []).map(row => normalizePlayer(row, team))
  }))
  if (selectedTeams.length && !successfulRequests && lastError) throw lastError
  const unique = new Map([...fplPlayers, ...freePlayers, ...batches.flat()].map(row => [row.id, row]))
  return [...unique.values()].sort((a, b) => a.name.localeCompare(b.name))
}

function filterCompetitions(sport, requested) {
  const all = competitionCatalog[sport] || []
  if (!requested || requested === 'all') return all
  const wanted = new Set(String(requested).split(','))
  return all.filter(item => wanted.has(item.id) || wanted.has(item.code))
}

export const multiSportProvider = {
  async directory(sport, type, options = {}) {
    if (!competitionCatalog[sport]) throw Object.assign(new Error(`Unsupported sport: ${sport}`), { status: 404 })
    if (!['leagues', 'games', 'teams', 'players', 'status'].includes(type)) throw Object.assign(new Error(`Unsupported directory: ${type}`), { status: 404 })
    const competitions = competitionCatalog[sport]
    if (type === 'status') {
      const esports = sport === 'esports' ? await esportsStatus() : null
      const sources = esports?.sources || sourceStatus(sport)
      const models = esports?.models || modelReports(sport)
      const modelSourcesReady = sources.filter(source => source.state === 'required').length === 0
      const predictionPayload = sportPredictionPayload(sport)
      return {
        sport, type, sources, competitions, models, generatedAt: new Date().toISOString(),
        presentationReady: sport === 'esports' ? sources.some(source => source.configured) : sources.some(source => source.id === 'presentation') && sources.some(source => source.configured),
        modelSourcesReady,
        modelState: models.some(model => model.historicalReadiness?.passed) ? 'HISTORICAL READY / LIVE PIPELINE CHECK' : models.length ? 'THREE-YEAR AUDITS TRAINED / SHADOW LOCKED' : modelSourcesReady ? 'COLLECTION READY / AUDIT REQUIRED' : 'SOURCE REQUIREMENTS OPEN',
        builderEligible: Object.values(predictionPayload.readiness?.automatic_builder_eligible || {}).some(Boolean),
        liveAudit: predictionPayload.live_audit || null,
        evaluationMode: 'odds-independent three-year chronological walk-forward',
      }
    }
    let items
    if (type === 'leagues') items = competitions
    else if (sport === 'esports') items = await esportsDirectory(type, options)
    else if (type === 'games') {
      items = await sportsDbGames(sport, options)
      if (sport === 'football') {
        const predictions = sportPredictions('football')
        items = items.map(item => ({ ...item, prediction: predictions.get(String(item.id)) || null }))
      }
      if (sport === 'american-football') {
        const predictions = sportPredictions('american-football')
        items = items.map(item => ({ ...item, prediction: predictions.get(String(item.id)) || null }))
      }
    }
    else if (type === 'teams') items = await sportsDbTeams(sport, options)
    else items = await sportsDbPlayers(sport, options)
    return {
      sport, type, items, competitions, count: items.length, generatedAt: new Date().toISOString(),
      source: sport === 'esports' ? 'Liquipedia MediaWiki API + CS API supplement' : sport === 'football' ? 'Open Football Data + FPL + TheSportsDB' : sport === 'american-football' ? 'nflverse + TheSportsDB' : 'Open NBA data + TheSportsDB',
      presentationOnly: false,
      coverage: sport === 'esports' ? 'Keyless Valorant, CS2 and League of Legends schedules, results, teams, players and shadow forecasts' : sport === 'football' && type === 'players' ? configured('NINTH_FOOTBALL_DATA_TOKEN') ? 'Free-tier top-five squad coverage plus keyless Premier League roster' : 'Complete keyless Premier League roster; add the optional free token for the other top-five leagues' : 'Keyless open and public coverage',
      limited: sport === 'football' && type === 'players' && !configured('NINTH_FOOTBALL_DATA_TOKEN'),
      modelTrainingAllowed: true,
      warning: sport === 'esports' ? 'Forecasts are live shadow outputs and remain builder-locked until the chronological audit gate passes.' : 'Presentation rows remain separate from the immutable model-training ledger.',
    }
  },
}
