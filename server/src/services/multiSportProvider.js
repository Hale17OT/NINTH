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
const NFLVERSE_PLAYER_STATS = 'https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv'
const HOUR = 60 * 60 * 1000
let sportsDbQueue = Promise.resolve()
let sportsDbLastRequest = 0
let nflPlayerStatsCache = null
const artifactRoot = () => process.env.NINTH_ML_ARTIFACT_DIR || join(process.cwd(), 'ml', 'artifacts')
const dataRoot = () => process.env.NINTH_ML_DATA_DIR || join(process.cwd(), 'ml', 'data')

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
    { id: 'open-results', name: 'Football-Data.co.uk', role: 'Top-five and Championship results, shots, corners, discipline and archived market snapshots', env: 'No key', configured: true, state: 'ready', detail: 'Archived opening/closing prices are isolated from model features and retained only for labelled post-prediction evaluation. Rolling form features are locked before each result.' },
    { id: 'open-events', name: 'StatsBomb Open Data', role: 'xG, pressures, progressive actions, events and selected 360 data', env: 'No key', configured: true, state: 'available', detail: 'The collector enriches only openly covered league-seasons and reports the missing coverage explicitly.' },
    { id: 'free-supplement', name: 'football-data.org free tier', role: 'Top-five clubs, squads and competition supplement', env: 'NINTH_FOOTBALL_DATA_TOKEN', configured: configured('NINTH_FOOTBALL_DATA_TOKEN'), state: configured('NINTH_FOOTBALL_DATA_TOKEN') ? 'ready' : 'optional', detail: 'A free account token completes squad coverage outside the Premier League; no paid plan is required.' },
  ]
  if (sport === 'american-football') return [
    presentation,
    { id: 'historical', name: 'nflverse', role: 'Play-by-play EPA, success, explosives, pressure, schedules and archived market anchors', env: 'Open data', configured: true, state: 'ready', detail: '2018–2025 play-by-play is aggregated before each game. Prices and lines are excluded from model features and retained only for evaluation and display.' },
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
  if (['football', 'american-football'].includes(sport)) {
    const consolidatedPath = join(artifactRoot(), 'multisport', 'football_nfl_model_report.json')
    if (existsSync(consolidatedPath)) {
      try {
        const payload = JSON.parse(readFileSync(consolidatedPath, 'utf8'))
        return (payload.models || []).filter(row => row.sport === sport).map(row => ({
          sport:row.sport, market:row.market, modelName:row.model_name, modelFamily:row.model_family,
          modelVersion:row.model_version, featureVersion:row.feature_version, datasetVersion:row.dataset_version,
          decision:row.decision, status:'evaluated', method:typeof row.algorithm === 'string' ? row.algorithm : Object.values(row.algorithm || {}).join(' + '),
          samples:{ untouched_test:row.prediction_count }, metrics:row.combined_holdout_results || {},
          baseline:row.comparison_to_baseline || {}, promotion:{ builder_eligible:row.decision === 'USE' },
          historicalReadiness:{ passed:['USE','LIMITED'].includes(row.decision), detail:row.overall_assessment },
          oddsIndependent:true,
          timeRange:{ first:row.development_dataset_start, trainingThrough:row.development_dataset_end, holdoutThrough:row.holdout_seasons?.at(-1) },
          holdoutResults:{ season_by_season:row.season_by_season_results, combined:row.combined_holdout_results, stability_assessment:row.holdout_stability_assessment },
          betting:{ roi:row.holdout_roi, yield:row.holdout_yield, clv:row.holdout_clv, maximumDrawdown:row.holdout_maximum_drawdown },
        })).sort((a,b) => a.modelFamily.localeCompare(b.modelFamily) || a.market.localeCompare(b.market))
      } catch { /* Fall back to individual artifact reports below. */ }
    }
  }
  const directories = sport === 'esports' ? ['valorant', 'cs2', 'lol'] : [sport]
  return directories.flatMap(directory => {
    const path = join(artifactRoot(), 'multisport', directory)
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
            timeRange: { first:report.development_dataset_start, trainingThrough:report.development_dataset_end, holdoutThrough:report.holdout_dataset_end },
            holdoutResults: report.holdout_results, datasetSha256: report.dataset_sha256,
          }))
        }
        if (report.sport === 'football' && report.market === 'score_distribution') {
          const metrics = report.holdout_results?.combined?.markets?.score || {}
          return [{
            sport:report.sport, market:'score_distribution', status:report.status, method:report.method,
            samples:report.samples, metrics, baseline:{}, promotion:report.promotion,
            historicalReadiness:{ passed:false, detail:'Exact-score output is contextual evidence, not an automatic builder market.' },
            oddsIndependent:report.odds_used_as_features === false,
            timeRange:{ first:report.development_dataset_start, trainingThrough:report.development_dataset_end, holdoutThrough:report.holdout_dataset_end },
            holdoutResults:report.holdout_results,
          }]
        }
        const combined = report.holdout_results?.combined || {}
        return [{
          sport: report.sport, market: report.market, status: report.status, method: report.method,
          samples: report.samples, metrics: combined.candidate || report.untouched_candidate || {},
          baseline: combined.baseline || report.untouched_climatology || {}, promotion: report.promotion,
          historical: report.development_validation || report.historical_walk_forward,
          historicalReadiness: report.historical_readiness,
          oddsIndependent: report.odds_independent === true,
          timeRange: report.time_range || { first:report.development_dataset_start, trainingThrough:report.development_dataset_end, holdoutThrough:report.holdout_dataset_end },
          holdoutResults:report.holdout_results, datasetSha256: report.dataset_sha256,
        }]
      } catch { return [] }
    })
  }).sort((a, b) => a.market.localeCompare(b.market))
}
const sportPredictions = sport => {
  const path = join(dataRoot(), 'multisport', sport, 'predictions.json')
  if (!existsSync(path)) return new Map()
  try {
    const payload = JSON.parse(readFileSync(path, 'utf8'))
    return new Map((payload.predictions || []).map(row => [String(row.event_id), row]))
  } catch { return new Map() }
}
const sportPredictionPayload = sport => {
  const path = join(dataRoot(), 'multisport', sport, 'predictions.json')
  if (!existsSync(path)) return {}
  try { return JSON.parse(readFileSync(path, 'utf8')) } catch { return {} }
}

export const competitionCatalog = {
  football: [
    { id: '4328', code: 'EPL', name: 'Premier League', country: 'England', group: 'Domestic league' },
    { id: '4329', code: 'ECH', name: 'Championship', country: 'England', group: 'Domestic league' },
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
const footballCsvCodes = { '4328': 'E0', '4329': 'E1', '4335': 'SP1', '4331': 'D1', '4332': 'I1', '4334': 'F1' }
const footballDataOrgCodes = { '4328': 'PL', '4335': 'PD', '4331': 'BL1', '4332': 'SA', '4334': 'FL1', '4480': 'CL', '4481': 'EL' }
const FPL_COMPETITION_ID = '4328'
const nflNames = {
  ARI:'Arizona Cardinals', ATL:'Atlanta Falcons', BAL:'Baltimore Ravens', BUF:'Buffalo Bills', CAR:'Carolina Panthers', CHI:'Chicago Bears', CIN:'Cincinnati Bengals', CLE:'Cleveland Browns', DAL:'Dallas Cowboys', DEN:'Denver Broncos', DET:'Detroit Lions', GB:'Green Bay Packers', HOU:'Houston Texans', IND:'Indianapolis Colts', JAX:'Jacksonville Jaguars', KC:'Kansas City Chiefs', LA:'Los Angeles Rams', LAC:'Los Angeles Chargers', LV:'Las Vegas Raiders', MIA:'Miami Dolphins', MIN:'Minnesota Vikings', NE:'New England Patriots', NO:'New Orleans Saints', NYG:'New York Giants', NYJ:'New York Jets', PHI:'Philadelphia Eagles', PIT:'Pittsburgh Steelers', SEA:'Seattle Seahawks', SF:'San Francisco 49ers', TB:'Tampa Bay Buccaneers', TEN:'Tennessee Titans', WAS:'Washington Commanders',
}
const nbaNames = {
  ATL:'Atlanta Hawks', BOS:'Boston Celtics', BKN:'Brooklyn Nets', CHA:'Charlotte Hornets', CHI:'Chicago Bulls', CLE:'Cleveland Cavaliers', DAL:'Dallas Mavericks', DEN:'Denver Nuggets', DET:'Detroit Pistons', GSW:'Golden State Warriors', HOU:'Houston Rockets', IND:'Indiana Pacers', LAC:'Los Angeles Clippers', LAL:'Los Angeles Lakers', MEM:'Memphis Grizzlies', MIA:'Miami Heat', MIL:'Milwaukee Bucks', MIN:'Minnesota Timberwolves', NOP:'New Orleans Pelicans', NYK:'New York Knicks', OKC:'Oklahoma City Thunder', ORL:'Orlando Magic', PHI:'Philadelphia 76ers', PHX:'Phoenix Suns', POR:'Portland Trail Blazers', SAC:'Sacramento Kings', SAS:'San Antonio Spurs', TOR:'Toronto Raptors', UTA:'Utah Jazz', WAS:'Washington Wizards',
}
const nbaAliases = { BRK:'BKN', CHO:'CHA', NOH:'NOP', NOK:'NOP', NOR:'NOP', PHO:'PHX', SAN:'SAS' }
let nbaAdvancedCache = null
let footballMatchCache = null
const readJson = path => {
  try { return JSON.parse(readFileSync(path, 'utf8')) } catch { return null }
}
const nbaAdvancedRows = () => {
  if (nbaAdvancedCache) return nbaAdvancedCache
  const payload = readJson(join(process.cwd(), 'ml', 'data', 'multisport', 'basketball', 'nba_advanced.json'))
  nbaAdvancedCache = payload?.rows || []
  return nbaAdvancedCache
}
const footballMatchRows = () => {
  if (footballMatchCache) return footballMatchCache
  const path = join(process.cwd(), 'ml', 'data', 'multisport', 'football', 'raw_matches.jsonl')
  if (!existsSync(path)) return []
  footballMatchCache = readFileSync(path, 'utf8').split(/\r?\n/).filter(Boolean).flatMap(line => { try { return [JSON.parse(line)] } catch { return [] } })
  return footballMatchCache
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

const sumRows = (rows, key) => rows.reduce((total, row) => total + (Number(row[key]) || 0), 0)
const safeRate = (numerator, denominator, scale = 1) => denominator ? numerator / denominator * scale : null
const roundMetric = (value, digits = 2) => Number.isFinite(Number(value)) ? Number(Number(value).toFixed(digits)) : null
const nflPositionProfile = rows => {
  const first = rows[0] || {}, position = String(first.position || '').toUpperCase()
  const games = rows.length, attempts = sumRows(rows, 'attempts'), completions = sumRows(rows, 'completions')
  const carries = sumRows(rows, 'carries'), targets = sumRows(rows, 'targets'), receptions = sumRows(rows, 'receptions')
  const passingYards = sumRows(rows, 'passing_yards'), rushingYards = sumRows(rows, 'rushing_yards'), receivingYards = sumRows(rows, 'receiving_yards')
  const base = { games }
  let statistics, primaryKey, secondaryKey
  if (position === 'QB') {
    statistics = { ...base, completions, attempts, completionRate: roundMetric(safeRate(completions, attempts, 100), 1), passingYards, passingYardsPerGame: roundMetric(safeRate(passingYards, games), 1), passingTouchdowns: sumRows(rows, 'passing_tds'), interceptions: sumRows(rows, 'interceptions'), sacks: sumRows(rows, 'sacks'), passingEpaPerDropback: roundMetric(safeRate(sumRows(rows, 'passing_epa'), attempts + sumRows(rows, 'sacks')), 3) }
    primaryKey = 'passing_yards'; secondaryKey = 'passing_tds'
  } else if (position === 'RB' || position === 'FB') {
    statistics = { ...base, carries, rushingYards, rushingYardsPerGame: roundMetric(safeRate(rushingYards, games), 1), yardsPerCarry: roundMetric(safeRate(rushingYards, carries), 2), rushingTouchdowns: sumRows(rows, 'rushing_tds'), targets, receptions, receivingYards, scrimmageYards: rushingYards + receivingYards, epaPerTouch: roundMetric(safeRate(sumRows(rows, 'rushing_epa') + sumRows(rows, 'receiving_epa'), carries + targets), 3) }
    primaryKey = 'rushing_yards'; secondaryKey = 'receiving_yards'
  } else if (['WR', 'TE'].includes(position)) {
    statistics = { ...base, targets, receptions, catchRate: roundMetric(safeRate(receptions, targets, 100), 1), receivingYards, receivingYardsPerGame: roundMetric(safeRate(receivingYards, games), 1), yardsPerTarget: roundMetric(safeRate(receivingYards, targets), 2), receivingTouchdowns: sumRows(rows, 'receiving_tds'), targetShare: roundMetric(rows.reduce((total, row) => total + (Number(row.target_share) || 0), 0) / games * 100, 1), airYardsShare: roundMetric(rows.reduce((total, row) => total + (Number(row.air_yards_share) || 0), 0) / games * 100, 1), receivingEpaPerTarget: roundMetric(safeRate(sumRows(rows, 'receiving_epa'), targets), 3) }
    primaryKey = 'receiving_yards'; secondaryKey = 'targets'
  } else {
    statistics = { ...base, fantasyPointsPpr: roundMetric(sumRows(rows, 'fantasy_points_ppr'), 1), specialTeamsTouchdowns: sumRows(rows, 'special_teams_tds') }
    primaryKey = 'fantasy_points_ppr'; secondaryKey = 'special_teams_tds'
  }
  const gameLog = rows.slice(-18).map(row => ({ label: `W${row.week}`, week: Number(row.week), opponent: row.opponent_team, primary: Number(row[primaryKey]) || 0, secondary: Number(row[secondaryKey]) || 0 }))
  return { statistics, gameLog, primaryKey, secondaryKey, season: Number(first.season), source: 'nflverse weekly player statistics' }
}
async function nflPlayerProfiles(requestedSeason) {
  if (!nflPlayerStatsCache) {
    const body = await cache.remember('nflverse:player-stats', 12 * HOUR, () => textResponse(NFLVERSE_PLAYER_STATS))
    const allRows = parseCsv(body).filter(row => row.player_id && row.season_type === 'REG')
    const seasons = [...new Set(allRows.map(row => Number(row.season)).filter(Number.isFinite))].sort((a, b) => b - a)
    const selectedSeason = seasons.find(season => season <= Number(requestedSeason)) || seasons[0]
    const groups = new Map()
    allRows.filter(row => Number(row.season) === selectedSeason).forEach(row => {
      if (!groups.has(row.player_id)) groups.set(row.player_id, [])
      groups.get(row.player_id).push(row)
    })
    nflPlayerStatsCache = new Map([...groups].map(([id, rows]) => [id, nflPositionProfile(rows.sort((a, b) => Number(a.week) - Number(b.week)))]))
  }
  return nflPlayerStatsCache
}

async function sportsDbPlayers(sport, options) {
  if (sport === 'american-football') {
    const season = Number(options.season || new Date().getUTCFullYear())
    const profiles = await nflPlayerProfiles(season).catch(() => new Map())
    const body = await cache.remember(`nflverse:roster:${season}`, 12 * HOUR, () => textResponse(`https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_${season}.csv`))
    const latest = new Map()
    for (const row of parseCsv(body)) {
      if (!row.full_name || !row.team) continue
      const id = row.gsis_id || row.espn_id || `${row.team}:${row.full_name}`
      const current = latest.get(id)
      if (!current || Number(row.week || 0) >= Number(current.week || 0)) latest.set(id, row)
    }
    const players = [...latest.values()].map(row => {
      const id = row.gsis_id || row.espn_id || `${row.team}:${row.full_name}`, profile = profiles.get(id)
      return ({
      id, name: row.full_name,
      teamId: `nfl:${row.team}`, team: nflNames[row.team] || row.team, position: row.position || 'Player',
      nationality: 'United States', born: row.birth_date || null,
      height: row.height ? `${Math.floor(Number(row.height) / 12)}' ${Number(row.height) % 12}"` : null,
      weight: row.weight ? `${row.weight} lb` : null, number: row.jersey_number || null,
      image: row.headshot_url || null, competition: 'NFL', status: row.status_description_abbr || row.status,
      statistics: profile?.statistics || {}, gameLog: profile?.gameLog || [], statisticsSeason: profile?.season || null,
      statisticsSource: profile?.source || null, primaryMetric: profile?.primaryKey || null, secondaryMetric: profile?.secondaryKey || null,
    })}).sort((a, b) => a.name.localeCompare(b.name))
    return options.team ? players.filter(row => String(row.teamId) === String(options.team)) : players
  }
  if (sport === 'basketball') {
    const season = Number(options.season || new Date().getUTCFullYear())
    const rows = await cache.remember(`open-nba:players:${season}`, 12 * HOUR, async () => {
      const path = `players_${season}.parquet`
      try {
        const file = await asyncBufferFromUrl({ url: `https://raw.githubusercontent.com/llimllib/nba_data/main/data/${path}` })
        return await parquetReadObjects({ file })
      } catch {
        const payload = await json(`https://api.github.com/repos/llimllib/nba_data/contents/data/${path}`, { 'X-GitHub-Api-Version': '2022-11-28' })
        if (payload.encoding !== 'base64' || !payload.content) throw new Error(`Open NBA roster payload unavailable for ${season}`)
        const buffer = Buffer.from(payload.content.replace(/\s/g, ''), 'base64')
        const file = buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength)
        return parquetReadObjects({ file })
      }
    })
    const players = rows.filter(row => row.player_name && row.team_abbreviation && Number(row.gp || 0) > 0).map(row => ({
      id: String(row.player_id), name: row.player_name, teamId: `nba:${row.team_abbreviation}`,
      team: nbaNames[row.team_abbreviation] || row.team_abbreviation, position: row.position || 'NBA player',
      nationality: row.country || '—', height: row.player_height || null,
      weight: row.player_weight ? `${row.player_weight} lb` : null, number: null,
      image: `https://cdn.nba.com/headshots/nba/latest/1040x760/${row.player_id}.png`, competition: 'NBA',
      statistics: { games: Number(row.gp), pointsPerGame: Number(row.pts_pergame || 0), assistsPerGame: Number(row.ast_pergame || 0), reboundsPerGame: Number(row.reb_pergame || 0), minutesPerGame: Number(row.min_pergame || 0) },
    })).sort((a, b) => a.name.localeCompare(b.name))
    return options.team ? players.filter(row => String(row.teamId) === String(options.team)) : players
  }
  const fplPlayers = sport === 'football' && (!options.competition || options.competition === 'all' || String(options.competition).split(',').includes(FPL_COMPETITION_ID))
    ? await openFplPlayers().catch(() => []) : []
  const footballCompetitions = sport === 'football' ? filterCompetitions(sport, options.competition) : []
  const freePlayers = sport === 'football' && configured('NINTH_FOOTBALL_DATA_TOKEN') ? await openFootballDataOrgPlayers(footballCompetitions) : []
  const teams = await sportsDbTeams(sport, options)
  const freeCovered = new Set(configured('NINTH_FOOTBALL_DATA_TOKEN') ? footballCompetitions.filter(competition => footballDataOrgCodes[competition.id]).map(competition => String(competition.id)) : [])
  const requestedTeam = String(options.team || '')
  const selectedTeams = teams.filter(team => (!requestedTeam || String(team.id) === requestedTeam) && !(sport === 'football' && (String(team.competitionId) === FPL_COMPETITION_ID || freeCovered.has(String(team.competitionId))))).slice(0, SPORTS_DB_KEY === '123' ? 20 : teams.length)
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
  if (selectedTeams.length && !successfulRequests && lastError && !fplPlayers.length && !freePlayers.length) throw lastError
  const unique = new Map([...fplPlayers, ...freePlayers, ...batches.flat()].map(row => [row.id, row]))
  const players = [...unique.values()].sort((a, b) => a.name.localeCompare(b.name))
  return requestedTeam ? players.filter(row => String(row.teamId) === requestedTeam) : players
}

const average = (rows, key) => rows.length ? rows.reduce((sum, row) => sum + Number(row?.[key] || 0), 0) / rows.length : null
const last = (rows, count = 10) => [...rows].slice(-count)
const completed = game => /completed|final/i.test(String(game.status || '')) || (game.home?.score != null && game.away?.score != null)
const includesTeam = (game, team) => [game.home, game.away].some(side => String(side?.id) === String(team.id) || side?.name?.toLowerCase() === team.name?.toLowerCase())
const teamGameResult = (game, team) => {
  const home = String(game.home?.id) === String(team.id) || game.home?.name?.toLowerCase() === team.name?.toLowerCase()
  const scored = Number((home ? game.home : game.away)?.score || 0), allowed = Number((home ? game.away : game.home)?.score || 0)
  return { id: game.id, date: game.date, opponent: (home ? game.away : game.home)?.name, home, scored, allowed, result: scored > allowed ? 'W' : scored < allowed ? 'L' : 'D' }
}
const buildStandings = (sport, teams, games) => {
  if (sport === 'basketball') {
    const rows = nbaAdvancedRows(), season = Math.max(...rows.map(row => Number(row.season || 0)))
    return teams.map(team => {
      const code = String(team.code || team.id?.split(':').pop()), aliases = new Set([code, ...Object.entries(nbaAliases).filter(([, value]) => value === code).map(([key]) => key)])
      const teamRows = rows.filter(row => Number(row.season) === season && aliases.has(String(row.tmName)))
      const wins = teamRows.filter(row => Number(row.win) === 1).length
      return { ...team, played: teamRows.length, wins, losses: teamRows.length - wins, pct: teamRows.length ? wins / teamRows.length : 0, pointsFor: average(teamRows, 'pts'), pointsAgainst: average(teamRows, 'oppPts') }
    }).sort((a, b) => b.pct - a.pct)
  }
  return teams.map(team => {
    const results = games.filter(game => completed(game) && includesTeam(game, team)).map(game => teamGameResult(game, team))
    const wins = results.filter(row => row.result === 'W').length, draws = results.filter(row => row.result === 'D').length
    return { ...team, played: results.length, wins, draws, losses: results.length - wins - draws, points: sport === 'football' ? wins * 3 + draws : wins, scored: results.reduce((sum, row) => sum + row.scored, 0), allowed: results.reduce((sum, row) => sum + row.allowed, 0), form: last(results, 5).map(row => row.result) }
  }).sort((a, b) => b.points - a.points || (b.scored - b.allowed) - (a.scored - a.allowed))
}
const percentileRank = (value, peers, lowerIsBetter = false) => {
  const numericPeers = peers.map(Number).filter(Number.isFinite)
  if (!Number.isFinite(Number(value)) || !numericPeers.length) return null
  const favorable = numericPeers.filter(peer => lowerIsBetter ? peer >= Number(value) : peer <= Number(value)).length
  return Math.round(favorable / numericPeers.length * 100)
}
const nbaMetricsForRows = rows => [
  { label: 'Offensive rating', value: rows.length ? average(rows, 'pts') / average(rows, 'totPoss') * 100 : null, unit: 'PTS / 100' },
  { label: 'Defensive rating', value: rows.length ? average(rows, 'oppPts') / average(rows, 'oppPoss') * 100 : null, unit: 'OPP / 100', lowerIsBetter: true },
  { label: 'Pace', value: average(rows, 'totPoss'), unit: 'POSS' },
  { label: 'Effective FG', value: average(rows, 'eFG'), unit: 'RATE' },
  { label: 'Turnovers', value: average(rows, 'tov1'), unit: 'PER GAME', lowerIsBetter: true },
  { label: 'Rebounds', value: average(rows, 'rebounder'), unit: 'PER GAME' },
]
const nbaAnalytics = team => {
  const code = String(team?.code || team?.id?.split(':').pop() || ''), normalized = nbaAliases[code] || code
  const rows = nbaAdvancedRows(), season = Math.max(...rows.map(row => Number(row.season || 0)))
  const seasonRows = rows.filter(row => Number(row.season) === season)
  const teamRows = seasonRows.filter(row => (nbaAliases[String(row.tmName)] || String(row.tmName)) === normalized)
  const peerGroups = new Map()
  seasonRows.forEach(row => { const key = nbaAliases[String(row.tmName)] || String(row.tmName); if (!peerGroups.has(key)) peerGroups.set(key, []); peerGroups.get(key).push(row) })
  const peerMetrics = [...peerGroups.values()].map(nbaMetricsForRows)
  const metrics = nbaMetricsForRows(teamRows).map((metric, index) => ({ ...metric, percentile: percentileRank(metric.value, peerMetrics.map(profile => profile[index]?.value), metric.lowerIsBetter) }))
  const recent = last(teamRows, 10)
  return {
    season, sample: teamRows.length, peerSample: peerGroups.size,
    metrics,
    trends: { labels: recent.map((_, index) => `G${Math.max(1, teamRows.length - recent.length + index + 1)}`), scored: recent.map(row => Number(row.pts)), allowed: recent.map(row => Number(row.oppPts)), pace: recent.map(row => Number(row.totPoss)), efficiency: recent.map(row => Number(row.eFG)) },
    question: recent.length ? `${team?.name} has averaged ${average(recent, 'pts').toFixed(1)} points across its latest ${recent.length} captured games at ${average(recent, 'totPoss').toFixed(1)} possessions.` : 'No captured NBA team-game sample is available.',
  }
}
const footballAnalytics = team => {
  const name = String(team?.name || '').toLowerCase(), ledger = footballMatchRows(), rows = ledger.filter(row => [row.HomeTeam, row.AwayTeam].some(value => String(value || '').toLowerCase() === name))
  const metricsFor = (club, sourceRows) => {
    const recentRows = last(sourceRows.filter(row => [row.HomeTeam, row.AwayTeam].some(value => String(value || '').toLowerCase() === club)), 10).map(row => {
      const home = String(row.HomeTeam || '').toLowerCase() === club
      return { scored: Number(home ? row.FTHG : row.FTAG), allowed: Number(home ? row.FTAG : row.FTHG), shots: Number(home ? row.HS : row.AS), shotsOnTarget: Number(home ? row.HST : row.AST), corners: Number(home ? row.HC : row.AC) }
    })
    return [
      { label: 'Goals for', value: average(recentRows, 'scored'), unit: 'LAST 10' }, { label: 'Goals against', value: average(recentRows, 'allowed'), unit: 'LAST 10', lowerIsBetter: true },
      { label: 'Shots', value: average(recentRows, 'shots'), unit: 'LAST 10' }, { label: 'Shots on target', value: average(recentRows, 'shotsOnTarget'), unit: 'LAST 10' },
      { label: 'Corners', value: average(recentRows, 'corners'), unit: 'LAST 10' },
    ]
  }
  const recent = last(rows, 10).map(row => {
    const home = String(row.HomeTeam || '').toLowerCase() === name
    return { date: row.Date, scored: Number(home ? row.FTHG : row.FTAG), allowed: Number(home ? row.FTAG : row.FTHG), shots: Number(home ? row.HS : row.AS), shotsOnTarget: Number(home ? row.HST : row.AST), corners: Number(home ? row.HC : row.AC) }
  })
  const division = rows.at(-1)?.Div, peerRows = division ? ledger.filter(row => row.Div === division) : ledger
  const clubs = [...new Set(peerRows.flatMap(row => [row.HomeTeam, row.AwayTeam]).filter(Boolean).map(value => String(value).toLowerCase()))]
  const peers = clubs.map(club => metricsFor(club, peerRows))
  const metrics = metricsFor(name, peerRows).map((metric, index) => ({ ...metric, percentile: percentileRank(metric.value, peers.map(profile => profile[index]?.value), metric.lowerIsBetter) }))
  return { sample: rows.length, peerSample: clubs.length, metrics, trends: { labels: recent.map((_, index) => `M${index + 1}`), scored: recent.map(row => row.scored), allowed: recent.map(row => row.allowed), shots: recent.map(row => row.shots) },
  question: recent.length ? `${team?.name} has a ${average(recent, 'scored').toFixed(2)} to ${average(recent, 'allowed').toFixed(2)} average-goal profile across the latest ${recent.length} open-data matches.` : 'This club has no matching advanced open-data history in the current ledger.' }
}
const genericAnalytics = (team, games) => {
  const results = games.filter(game => completed(game) && includesTeam(game, team)).map(game => teamGameResult(game, team)), recent = last(results, 10)
  const teamStats = team?.statistics || {}
  return { sample: results.length, metrics: Object.entries(teamStats).filter(([, value]) => Number.isFinite(Number(value))).slice(0, 6).map(([label, value]) => ({ label: label.replace(/([A-Z])/g, ' $1'), value: Number(value), unit: 'CURRENT' })), trends: { labels: recent.map((_, index) => `M${index + 1}`), scored: recent.map(row => row.scored), allowed: recent.map(row => row.allowed) }, question: recent.length ? `${team?.name} is ${recent.filter(row => row.result === 'W').length}-${recent.filter(row => row.result !== 'W').length} across its latest ${recent.length} captured decisions.` : 'No completed match sample is available for this team.' }
}

const metricDefinitions = {
  completionRate: 'Completed passes divided by pass attempts.', passingEpaPerDropback: 'Expected points added on passing plays divided by attempts plus sacks.',
  epaPerTouch: 'Rushing and receiving expected points added divided by carries plus targets.', receivingEpaPerTarget: 'Receiving expected points added divided by targets.',
  targetShare: 'Average share of team pass targets in games played.', airYardsShare: 'Average share of team intended air yards in games played.',
  pointsPerGame: 'Points scored divided by games played.', pointsPer36: 'Points per game scaled to 36 minutes using the captured minutes rate.',
  assistsPer36: 'Assists per game scaled to 36 minutes.', reboundsPer36: 'Rebounds per game scaled to 36 minutes.',
  goalsPer90: 'Goals divided by minutes played and scaled to 90 minutes.', assistsPer90: 'Assists divided by minutes played and scaled to 90 minutes.',
  expectedGoalsPer90: 'Expected goals divided by minutes played and scaled to 90 minutes.', expectedAssistsPer90: 'Expected assists divided by minutes played and scaled to 90 minutes.',
}
const playerDerivedStats = (sport, player) => {
  const stats = { ...(player?.statistics || {}) }
  if (sport === 'basketball' && Number(stats.minutesPerGame) > 0) {
    stats.pointsPer36 = roundMetric(Number(stats.pointsPerGame) / Number(stats.minutesPerGame) * 36, 1)
    stats.assistsPer36 = roundMetric(Number(stats.assistsPerGame) / Number(stats.minutesPerGame) * 36, 1)
    stats.reboundsPer36 = roundMetric(Number(stats.reboundsPerGame) / Number(stats.minutesPerGame) * 36, 1)
  }
  if (sport === 'football' && Number(stats.minutes) > 0) {
    const per90 = 90 / Number(stats.minutes)
    stats.goalsPer90 = roundMetric(Number(stats.goals || 0) * per90, 2)
    stats.assistsPer90 = roundMetric(Number(stats.assists || 0) * per90, 2)
    stats.expectedGoalsPer90 = roundMetric(Number(stats.expectedGoals || 0) * per90, 2)
    stats.expectedAssistsPer90 = roundMetric(Number(stats.expectedAssists || 0) * per90, 2)
  }
  return stats
}
const ordinal = value => { const number = Number(value), mod100 = number % 100, suffix = mod100 >= 11 && mod100 <= 13 ? 'th' : ({1:'st',2:'nd',3:'rd'}[number % 10] || 'th'); return `${number}${suffix}` }
const playerAnalytics = (sport, player, peers) => {
  const position = String(player?.position || '').toLowerCase()
  const peerGroup = peers.filter(row => !position || String(row.position || '').toLowerCase() === position)
  const stats = playerDerivedStats(sport, player)
  const peerStats = peerGroup.map(row => playerDerivedStats(sport, row))
  const exclude = new Set(['games', 'starts', 'minutes', 'attempts', 'completions', 'carries', 'targets', 'receptions'])
  const keys = Object.keys(stats).filter(key => Number.isFinite(Number(stats[key])) && (!exclude.has(key) || Object.keys(stats).length < 6))
  const prioritized = keys.sort((a, b) => Number(metricDefinitions[b] != null) - Number(metricDefinitions[a] != null)).slice(0, 10)
  const metrics = prioritized.map(key => ({
    key, label: key.replace(/([A-Z])/g, ' $1').replace(/^./, value => value.toUpperCase()), value: Number(stats[key]),
    percentile: percentileRank(stats[key], peerStats.map(row => row[key])), definition: metricDefinitions[key] || 'Current source-backed season production.',
  }))
  const gameLog = Array.isArray(player.gameLog) ? player.gameLog : []
  const recent = last(gameLog, 5), seasonAverage = average(gameLog, 'primary'), recentAverage = average(recent, 'primary')
  const lead = [...metrics].filter(metric => metric.percentile != null).sort((a, b) => b.percentile - a.percentile)[0]
  let interpretation = lead ? `${player.name}'s strongest captured peer signal is ${lead.label.toLowerCase()} at the ${ordinal(lead.percentile)} percentile among ${peerGroup.length} ${player.position || 'role'} peers.` : `NINTH has ${metrics.length} comparable source-backed fields for this profile.`
  if (recent.length && seasonAverage != null) {
    const delta = recentAverage - seasonAverage
    interpretation += ` The latest ${recent.length} games average ${recentAverage.toFixed(1)} ${String(player.primaryMetric || 'primary output').replaceAll('_', ' ')}, ${Math.abs(delta).toFixed(1)} ${delta >= 0 ? 'above' : 'below'} the captured season-game average.`
  }
  return {
    positionGroup: player.position || 'Player', peerSample: peerGroup.length, metrics,
    trends: { labels: gameLog.map(row => row.label), primary: gameLog.map(row => row.primary), secondary: gameLog.map(row => row.secondary), primaryLabel: String(player.primaryMetric || 'Primary output').replaceAll('_', ' '), secondaryLabel: String(player.secondaryMetric || 'Secondary output').replaceAll('_', ' ') },
    splits: recent.length ? [{ label: 'Latest 5', value: roundMetric(recentAverage, 1), comparison: roundMetric(seasonAverage, 1), context: 'Season game average' }] : [],
    interpretation, source: player.statisticsSource || (sport === 'basketball' ? 'Open NBA season player table' : sport === 'football' ? 'Fantasy Premier League open season feed' : 'Current provider profile'),
    season: player.statisticsSeason || new Date().getUTCFullYear(),
  }
}
const attachSportPredictions = (sport, games) => {
  if (!['football', 'american-football'].includes(sport)) return games
  const predictions = sportPredictions(sport)
  return games.map(game => ({ ...game, prediction: predictions.get(String(game.id)) || game.prediction || null }))
}
export const predictionGame = row => {
  const at = String(row.event_time || '')
  return {
    id:String(row.event_id), competitionId:String(row.competition_id || (row.event_id?.match(/^\d{4}_/) ? '4391' : '')),
    competition:row.competition || (row.event_id?.match(/^\d{4}_/) ? 'NFL' : 'Football'), competitionCode:row.competition_code || '',
    group:'Source-backed fixture', round:row.round || 'Scheduled', date:at.slice(0,10), time:at.slice(11,16) || 'TBD', timestamp:at,
    status:'Scheduled', venue:row.venue || 'Venue pending source confirmation',
    home:{id:`prediction:${teamSlug(row.home_team)}`,name:row.home_team,badge:null,score:null},
    away:{id:`prediction:${teamSlug(row.away_team)}`,name:row.away_team,badge:null,score:null},
    prediction:row, source:row.source || 'NINTH immutable prediction feed', sourceUrl:null,
  }
}
const mergePredictionGames = (sport, games, competition = null) => {
  if (!['football','american-football'].includes(sport)) return attachSportPredictions(sport, games)
  const payload = sportPredictionPayload(sport), predictions = new Map((payload.predictions || []).map(row => [String(row.event_id), row]))
  const merged = games.map(game => ({...game,prediction:predictions.get(String(game.id))||game.prediction||null}))
  const existing = new Set(merged.map(game=>String(game.id)))
  for (const row of payload.predictions || []) {
    if (competition && String(row.competition_id || (sport==='american-football'?'4391':'')) !== String(competition)) continue
    if (!existing.has(String(row.event_id))) merged.push(predictionGame(row))
  }
  return merged.sort(sortDirectoryEvents)
}

function filterCompetitions(sport, requested) {
  const all = competitionCatalog[sport] || []
  if (!requested || requested === 'all') return all
  const wanted = new Set(String(requested).split(','))
  return all.filter(item => wanted.has(item.id) || wanted.has(item.code))
}

export const multiSportProvider = {
  async workspace(sport, scope, id, options = {}) {
    if (!competitionCatalog[sport]) throw Object.assign(new Error(`Unsupported sport: ${sport}`), { status: 404 })
    const requestedId = String(id)
    if (scope === 'league') {
      const leagues = sport === 'esports' ? await esportsDirectory('leagues', options) : competitionCatalog[sport]
      const league = leagues.find(row => String(row.id) === requestedId)
      if (!league) throw Object.assign(new Error('Competition not found'), { status: 404 })
      let identity = league
      if (sport !== 'esports' && /^\d+$/.test(requestedId)) {
        const payload = await get(`lookupleague.php?id=${requestedId}`, 24 * HOUR).catch(() => null)
        const row = payload?.leagues?.[0]
        if (row) identity = { ...league, badge: row.strBadge || row.strLogo || null, banner: row.strFanart1 || row.strPoster || null, formed: row.intFormedYear || null, description: row.strDescriptionEN || '' }
      }
      const query = sport === 'esports' ? { discipline: league.discipline, tournament: league.id } : { competition: league.id }
      const [rawGames, allTeams] = sport === 'esports'
        ? await Promise.all([esportsDirectory('games', query), esportsDirectory('teams', query)])
        : await Promise.all([sportsDbGames(sport, query), sportsDbTeams(sport, query)])
      const allGames = mergePredictionGames(sport, rawGames, league.id)
      const teamNames = new Set(allGames.flatMap(game => [game.home?.name, game.away?.name]).filter(Boolean))
      const teams = sport === 'esports' ? allTeams.filter(team => teamNames.has(team.name)) : allTeams
      const standings = buildStandings(sport, teams, allGames)
      const upcoming = allGames.filter(game => !completed(game)).slice(0, 18)
      const recent = allGames.filter(completed).slice(0, 18)
      const predictions = upcoming.filter(game => game.prediction).sort((a, b) => Math.max(...Object.values(b.prediction?.markets || {}).map(Number)) - Math.max(...Object.values(a.prediction?.markets || {}).map(Number)))
      return { sport, scope, identity, games: { upcoming, recent }, teams, standings, predictions: predictions.slice(0, 8), generatedAt: new Date().toISOString(), source: sport === 'esports' ? 'Liquipedia MediaWiki API + CS API supplement' : sport === 'football' ? 'Open Football Data + FPL + TheSportsDB' : sport === 'basketball' ? 'Open NBA data + TheSportsDB' : 'nflverse + TheSportsDB' }
    }
    if (scope === 'team') {
      const query = { competition: options.competition, discipline: options.discipline }
      const teams = sport === 'esports' ? await esportsDirectory('teams', query) : await sportsDbTeams(sport, query)
      const requestedCode = requestedId.includes(':') ? requestedId.split(':').pop().toUpperCase() : ''
      const canonicalCode = sport === 'basketball' ? (nbaAliases[requestedCode] || requestedCode) : requestedCode
      const requestedName = sport === 'basketball' ? nbaNames[canonicalCode] : sport === 'american-football' ? nflNames[canonicalCode] : ''
      const predictionSlug = requestedId.startsWith('prediction:') ? requestedId.slice('prediction:'.length) : ''
      const predicted = predictionSlug ? (sportPredictionPayload(sport).predictions || []).find(row => [row.home_team,row.away_team].some(name=>teamSlug(name)===predictionSlug)) : null
      const predictedName = predicted && (teamSlug(predicted.home_team)===predictionSlug ? predicted.home_team : predicted.away_team)
      const team = teams.find(row => String(row.id) === requestedId)
        || teams.find(row => canonicalCode && String(row.code || '').toUpperCase() === canonicalCode)
        || teams.find(row => requestedName && String(row.name || '').toLowerCase() === requestedName.toLowerCase())
        || teams.find(row => predictedName && teamSlug(row.name) === teamSlug(predictedName))
        || (predictedName ? {id:requestedId,name:predictedName,code:'',badge:null,competitionId:String(predicted.competition_id || options.competition || (sport==='american-football'?'4391':''))} : null)
      if (!team) throw Object.assign(new Error('Team not found'), { status: 404 })
      const gameQuery = sport === 'esports' ? { discipline: team.competitionId } : { competition: team.competitionId }
      const rawGames = sport === 'esports' ? await esportsDirectory('games', gameQuery) : await sportsDbGames(sport, gameQuery)
      const games = mergePredictionGames(sport, rawGames, team.competitionId)
      const teamGames = games.filter(game => includesTeam(game, team))
      let roster = []
      const rosterTeamId = sport === 'basketball' ? `nba:${team.code}` : team.id
      try { roster = sport === 'esports' ? await esportsDirectory('players', { discipline: team.competitionId, team: rosterTeamId }) : await sportsDbPlayers(sport, { competition: team.competitionId, team: rosterTeamId }) } catch { roster = [] }
      const analytics = sport === 'basketball' ? nbaAnalytics(team) : sport === 'football' ? footballAnalytics(team) : genericAnalytics(team, teamGames)
      const standing = buildStandings(sport, teams, games).find(row => String(row.id) === String(team.id)) || null
      return { sport, scope, identity: team, league: (competitionCatalog[sport] || []).find(row => String(row.id) === String(team.competitionId)) || null, standing, roster, games: { upcoming: teamGames.filter(game => !completed(game)).slice(0, 12), recent: teamGames.filter(completed).slice(0, 12) }, analytics, generatedAt: new Date().toISOString() }
    }
    if (scope === 'player') {
      const teamId = options.team || ''
      const query = { competition: options.competition, discipline: options.discipline, team: teamId }
      // FPL identities already carry a complete, canonical competition context.
      // Taking the direct open-data path avoids querying every unrelated football
      // competition before a Premier League player page can render.
      const directFpl = sport === 'football' && requestedId.startsWith('fpl:')
      const players = directFpl
        ? await openFplPlayers()
        : sport === 'esports' ? await esportsDirectory('players', query) : await sportsDbPlayers(sport, query)
      const player = players.find(row => String(row.id) === requestedId)
      if (!player) throw Object.assign(new Error('Player not found. Open the player from a team roster so its competition context is preserved.'), { status: 404 })
      const teams = directFpl
        ? await openFplTeams()
        : sport === 'esports' ? await esportsDirectory('teams', query) : await sportsDbTeams(sport, query)
      const teamCode = String(player.teamId || '').split(':').pop()
      const team = teams.find(row => String(row.id) === String(player.teamId) || String(row.code) === teamCode) || null
      let peers = players
      if (!directFpl && ['basketball', 'american-football', 'football'].includes(sport)) {
        try { peers = await sportsDbPlayers(sport, { competition: options.competition || team?.competitionId, season: options.season }) } catch { peers = players }
      }
      return { sport, scope, identity: player, team, league: (competitionCatalog[sport] || []).find(row => String(row.id) === String(team?.competitionId)) || null, analytics: playerAnalytics(sport, player, peers), generatedAt: new Date().toISOString() }
    }
    if (scope === 'game') {
      const query = { competition: options.competition, discipline: options.discipline, tournament: options.tournament }
      const rawGames = sport === 'esports' ? await esportsDirectory('games', query) : await sportsDbGames(sport, query)
      const games = mergePredictionGames(sport, rawGames, options.competition)
      const game = games.find(row => String(row.id) === requestedId)
      if (!game) throw Object.assign(new Error('Match not found'), { status: 404 })
      return { sport, scope, identity: game, league: (competitionCatalog[sport] || []).find(row => String(row.id) === String(game.competitionId)) || null, generatedAt: new Date().toISOString() }
    }
    throw Object.assign(new Error(`Unsupported workspace: ${scope}`), { status: 404 })
  },
  async directory(sport, type, options = {}) {
    if (!competitionCatalog[sport]) throw Object.assign(new Error(`Unsupported sport: ${sport}`), { status: 404 })
    if (!['leagues', 'games', 'teams', 'players', 'status'].includes(type)) throw Object.assign(new Error(`Unsupported directory: ${type}`), { status: 404 })
    let competitions = competitionCatalog[sport]
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
        modelState: models.some(model => model.historicalReadiness?.passed) ? 'HISTORICAL EVIDENCE AVAILABLE' : models.length ? 'EVALUATED / MORE EVIDENCE REQUIRED' : modelSourcesReady ? 'COLLECTION READY / EVALUATION REQUIRED' : 'SOURCE REQUIREMENTS OPEN',
        builderEligible: Object.values(predictionPayload.readiness?.automatic_builder_eligible || {}).some(Boolean),
        liveAudit: predictionPayload.live_audit || null,
        evaluationMode: ['football','american-football'].includes(sport) ? 'fixed development seasons with two untouched season holdouts' : 'odds-independent chronological walk-forward',
      }
    }
    let items
    if (type === 'leagues') {
      items = sport === 'esports' ? await esportsDirectory('leagues', options) : competitions
      if (sport === 'esports') competitions = competitionCatalog.esports
    }
    else if (sport === 'esports') items = await esportsDirectory(type, options)
    else if (type === 'games') {
      items = await sportsDbGames(sport, options)
      if (sport === 'football') {
        const requested = !options.competition || options.competition === 'all' ? null : String(options.competition).split(',')[0]
        items = mergePredictionGames('football', items, requested)
      }
      if (sport === 'american-football') {
        items = mergePredictionGames('american-football', items, options.competition || '4391')
      }
    }
    else if (type === 'teams') items = await sportsDbTeams(sport, options)
    else items = await sportsDbPlayers(sport, options)
    return {
      sport, type, items, competitions, count: items.length, generatedAt: new Date().toISOString(),
      source: sport === 'esports' ? 'Liquipedia MediaWiki API + CS API supplement' : sport === 'football' ? 'Open Football Data + FPL + TheSportsDB' : sport === 'american-football' ? 'nflverse + TheSportsDB' : 'Open NBA data + TheSportsDB',
      presentationOnly: false,
      coverage: sport === 'esports' ? 'Keyless Valorant, CS2 and League of Legends schedules, results, teams, players and evaluated forecasts' : sport === 'football' && type === 'players' ? configured('NINTH_FOOTBALL_DATA_TOKEN') ? 'Free-tier top-five squad coverage plus keyless Premier League roster' : 'Complete keyless Premier League roster; add the optional free token for the other top-five leagues' : 'Keyless open and public coverage',
      limited: sport === 'football' && type === 'players' && !configured('NINTH_FOOTBALL_DATA_TOKEN'),
      modelTrainingAllowed: true,
      warning: sport === 'esports' ? 'Forecasts remain unavailable for automatic builder use until their chronological evidence gate passes.' : 'Presentation rows remain separate from the immutable model-training ledger.',
    }
  },
}
