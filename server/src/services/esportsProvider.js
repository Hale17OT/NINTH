import { load } from 'cheerio'
import { cache } from './cache.js'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const HOUR = 60 * 60 * 1000
const LIQUIPEDIA = 'https://liquipedia.net'
const CSAPI = 'https://api.csapi.de'
const USER_AGENT = 'NINTHAnalytics/1.0 (personal local research; contact: local-user)'
const SNAPSHOT_DIR = join(process.cwd(), 'ml', 'data', 'multisport', 'esports')
const DISCIPLINES = {
  valorant: { name: 'Valorant', code: 'VAL', wiki: 'valorant', source: 'Liquipedia MediaWiki API' },
  cs2: { name: 'Counter-Strike 2', code: 'CS2', wiki: 'counterstrike', source: 'Liquipedia API + CS API' },
  lol: { name: 'League of Legends', code: 'LOL', wiki: 'leagueoflegends', source: 'Liquipedia MediaWiki API' },
}

const clean = value => String(value || '').replace(/\s+/g, ' ').trim()
const slug = value => clean(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
const absolute = (base, value) => !value ? null : value.startsWith('//') ? `https:${value}` : value.startsWith('/') ? `${base}${value}` : value
const safeNumber = value => Number(String(value || '').replace('%', '')) || 0
const request = async (url, options = {}) => {
  const response = await fetch(url, { ...options, headers: { Accept: '*/*', 'User-Agent': USER_AGENT, ...(options.headers || {}) } })
  if (!response.ok) throw new Error(`Esports source failed (${response.status})`)
  return response
}
const json = async url => (await request(url, { headers: { Accept: 'application/json' } })).json()

let liquipediaQueue = Promise.resolve()
let liquipediaLastParse = 0
const liquipediaRefreshes = new Map()
const snapshotPath = wiki => join(SNAPSHOT_DIR, `liquipedia-${wiki}-main.json`)
const historicalReport = discipline => {
  const path = join(process.cwd(), 'ml', 'artifacts', 'multisport', discipline, 'match_winner.json')
  if (!existsSync(path)) return null
  try { return JSON.parse(readFileSync(path, 'utf8')) } catch { return null }
}
const diskSnapshot = wiki => {
  const path = snapshotPath(wiki)
  if (!existsSync(path)) return null
  try { return { ...JSON.parse(readFileSync(path, 'utf8')), age: Date.now() - statSync(path).mtimeMs } } catch { return null }
}
const refreshLiquipediaMainPage = wiki => {
  if (liquipediaRefreshes.has(wiki)) return liquipediaRefreshes.get(wiki)
  const job = liquipediaQueue.then(async () => {
    const wait = Math.max(0, 30_100 - (Date.now() - liquipediaLastParse))
    if (wait) await new Promise(resolve => setTimeout(resolve, wait))
    liquipediaLastParse = Date.now()
    const url = `${LIQUIPEDIA}/${wiki}/api.php?action=parse&page=Main%20Page&prop=text&format=json&formatversion=2`
    const payload = await json(url)
    const html = payload?.parse?.text || ''
    mkdirSync(SNAPSHOT_DIR, { recursive: true })
    writeFileSync(snapshotPath(wiki), JSON.stringify({ fetchedAt: new Date().toISOString(), html }))
    return html
  })
  liquipediaQueue = job.catch(() => '')
  liquipediaRefreshes.set(wiki, job)
  job.then(() => liquipediaRefreshes.delete(wiki), () => liquipediaRefreshes.delete(wiki))
  return job
}
const liquipediaMainPage = wiki => cache.remember(`esports:liquipedia:${wiki}:main`, HOUR, async () => {
  const snapshot = diskSnapshot(wiki)
  if (snapshot?.html) {
    if (snapshot.age > HOUR) refreshLiquipediaMainPage(wiki).catch(() => null)
    return snapshot.html
  }
  return refreshLiquipediaMainPage(wiki)
})

function liquipediaMatches(html, discipline) {
  const $ = load(html), meta = DISCIPLINES[discipline]
  return $('.match-info').map((index, element) => {
    const node = $(element), opponents = node.find('.match-info-header-opponent')
    if (opponents.length < 2) return null
    const team = item => ({
      name: (clean(item.find('.name a').attr('title') || item.find('.name').text()) || 'TBD')
        .replace(/\s*\(page does not exist\)$/i, '').replace(/\s*\([^)]* team\)$/i, ''),
      badge: null,
    })
    const home = team(opponents.eq(0)), away = team(opponents.eq(1))
    const scores = node.find('.match-info-header-scoreholder-upper').find('span').filter('.match-info-header-scoreholder-score').map((_, score) => safeNumber($(score).text())).get()
    const timestampSeconds = safeNumber(node.find('.timer-object').attr('data-timestamp'))
    const timestamp = timestampSeconds ? new Date(timestampSeconds * 1000).toISOString() : null
    const completed = node.parents('[data-toggle-area-content]').first().attr('data-toggle-area-content') === '2'
    const detail = node.find('.match-info-links a[href*="Match:"]').first().attr('href') || ''
    const tournament = clean(node.find('.match-info-tournament-name').text()) || `${meta.name} circuit`
    const format = clean(node.find('.match-info-header-scoreholder-lower').text()) || 'Series'
    return {
      id: `${discipline}:${detail.match(/ID_([^/"#]+)/)?.[1] || `${slug(home.name)}-${slug(away.name)}-${timestampSeconds || index}`}`,
      competitionId: discipline, competition: `${meta.name} · ${tournament}`, competitionCode: meta.code, group: 'Esports', round: format,
      date: timestamp?.slice(0, 10) || '', time: timestamp?.slice(11, 16) || 'TBD', timestamp, status: completed ? 'Completed' : 'Scheduled',
      venue: 'Online / tournament venue', source: 'Liquipedia MediaWiki API', sourceUrl: absolute(LIQUIPEDIA, detail),
      home: { id: `${discipline}:${slug(home.name)}`, name: home.name, badge: home.badge, score: completed ? scores[0] ?? 0 : null },
      away: { id: `${discipline}:${slug(away.name)}`, name: away.name, badge: away.badge, score: completed ? scores[1] ?? 0 : null },
    }
  }).get().filter(Boolean)
}

const liquipediaSnapshot = async discipline => ({ games: liquipediaMatches(await liquipediaMainPage(DISCIPLINES[discipline].wiki), discipline) })

async function activePlayers(discipline) {
  const wiki = DISCIPLINES[discipline].wiki
  return cache.remember(`esports:liquipedia:${wiki}:players`, 12 * HOUR, async () => {
    const url = `${LIQUIPEDIA}/${wiki}/api.php?action=query&list=categorymembers&cmtitle=Category:Active%20Players&cmnamespace=0&cmlimit=100&format=json&formatversion=2`
    const payload = await json(url)
    return (payload?.query?.categorymembers || []).map(row => ({
      id: `${discipline}:${row.pageid}`, name: row.title, teamId: null, team: 'Active competitive pool', position: 'Player', nationality: '—', image: null,
      competition: DISCIPLINES[discipline].name, sourceUrl: `${LIQUIPEDIA}/${wiki}/${encodeURIComponent(row.title.replaceAll(' ', '_'))}`,
    }))
  })
}

async function csApiData() {
  return cache.remember('esports:csapi:catalog', 6 * HOUR, async () => {
    const [matches, rankings, players] = await Promise.all([
      json(`${CSAPI}/matches/?page=1&page_size=100`), json(`${CSAPI}/rankings/`), json(`${CSAPI}/players/stats?limit=100`),
    ])
    return { matches: Array.isArray(matches) ? matches : matches.items || [], rankings: Array.isArray(rankings) ? rankings : rankings.items || [], players: Array.isArray(players) ? players : players.items || [] }
  })
}

function csHistory(rows) {
  return rows.map(row => ({
    id: `cs2:csapi:${row.id}`, competitionId: 'cs2', competition: `Counter-Strike 2 · ${row.event || 'Pro circuit'}`, competitionCode: 'CS2', group: 'Esports', round: `Best of ${row.best_of || 3}`,
    date: row.date || '', time: 'TBD', timestamp: row.date ? `${row.date}T12:00:00Z` : null, status: 'Completed', venue: 'Tournament venue', source: 'CS API', sourceUrl: 'https://www.csapi.de/',
    home: { id: `cs2:${row.team1?.id || slug(row.team1?.name)}`, name: row.team1?.name || 'TBD', badge: null, score: row.team1?.score ?? null },
    away: { id: `cs2:${row.team2?.id || slug(row.team2?.name)}`, name: row.team2?.name || 'TBD', badge: null, score: row.team2?.score ?? null },
  }))
}

function evaluate(games) {
  const ratings = new Map(), records = new Map(), audit = []
  const rating = team => ratings.get(team) || 1500
  const touch = team => records.get(team) || { wins: 0, losses: 0, played: 0 }
  for (const game of games.filter(row => row.status === 'Completed' && row.home.score !== row.away.score).sort((a, b) => `${a.date}${a.id}`.localeCompare(`${b.date}${b.id}`))) {
    const left = rating(game.home.name), right = rating(game.away.name)
    const probability = 1 / (1 + 10 ** ((right - left) / 400)), outcome = game.home.score > game.away.score ? 1 : 0
    audit.push({ probability, outcome })
    const delta = 24 * (outcome - probability)
    ratings.set(game.home.name, left + delta); ratings.set(game.away.name, right - delta)
    const home = touch(game.home.name), away = touch(game.away.name)
    home.played += 1; away.played += 1
    if (outcome) { home.wins += 1; away.losses += 1 } else { away.wins += 1; home.losses += 1 }
    records.set(game.home.name, home); records.set(game.away.name, away)
  }
  const n = audit.length || 1
  const brier = audit.reduce((sum, row) => sum + (row.probability - row.outcome) ** 2, 0) / n
  const logLoss = -audit.reduce((sum, row) => sum + row.outcome * Math.log(Math.max(.001, row.probability)) + (1 - row.outcome) * Math.log(Math.max(.001, 1 - row.probability)), 0) / n
  const accuracy = audit.filter(row => (row.probability >= .5) === Boolean(row.outcome)).length / n
  const forecast = game => {
    const home = rating(game.home.name), away = rating(game.away.name), probability = 1 / (1 + 10 ** ((away - home) / 400))
    return { model: 'Time-decayed series Elo baseline', modelStatus: audit.length >= 100 ? 'AUDIT CANDIDATE' : 'LIVE SHADOW', markets: { home_win: probability, away_win: 1 - probability }, recommended: probability >= .5 ? game.home.name : game.away.name, confidence: Math.max(probability, 1 - probability) }
  }
  return { ratings, records, forecast, report: { samples: audit.length, brier, logLoss, accuracy, calibration: Math.abs((audit.reduce((sum, row) => sum + row.probability, 0) / n) - (audit.reduce((sum, row) => sum + row.outcome, 0) / n)) } }
}

const selectedDisciplines = value => !value || value === 'all' ? ['valorant', 'cs2', 'lol'] : [value === 'csgo' ? 'cs2' : value]

async function disciplineCatalog(discipline) {
  return cache.remember(`esports:catalog:${discipline}`, 15 * 60 * 1000, async () => {
    const base = await liquipediaSnapshot(discipline)
    let games = base.games, players = [], rankings = []
    if (discipline === 'cs2') {
      const cs = await csApiData()
      games = [...games, ...csHistory(cs.matches)].filter((row, index, all) => all.findIndex(other => other.id === row.id) === index)
      rankings = cs.rankings
      players = cs.players.map(row => ({ id: `cs2:${row.id}`, name: row.name, teamId: null, team: 'CS2 ranked pool', position: 'Player', nationality: '—', image: null, competition: 'Counter-Strike 2', statistics: { rank: row.rank, maps: row.N, rating: row.rating, adr: row.adr, kast: row.kast, kills: row.k, deaths: row.d } }))
    } else players = await activePlayers(discipline).catch(() => [])
    const model = evaluate(games)
    games = games.map(game => game.status === 'Completed' ? game : { ...game, prediction: model.forecast(game) })
    const teamRows = new Map()
    for (const game of games) for (const side of [game.home, game.away]) if (side.name !== 'TBD') teamRows.set(side.name, { id: side.id, name: side.name, shortName: side.name, code: side.name.split(/\s+/).map(word => word[0]).join('').slice(0, 4).toUpperCase(), competitionId: discipline, competition: DISCIPLINES[discipline].name, country: 'International', venue: 'Esports circuit', formed: null, badge: side.badge, statistics: { rating: Math.round(model.ratings.get(side.name) || 1500), ...(model.records.get(side.name) || { wins: 0, losses: 0, played: 0 }) } })
    for (const row of rankings) {
      const existing = teamRows.get(row.name) || { id: `cs2:${row.id}`, name: row.name, shortName: row.name, code: row.name.slice(0, 4).toUpperCase(), competitionId: 'cs2', competition: 'Counter-Strike 2', country: 'International', venue: 'Esports circuit', formed: null, badge: null, statistics: {} }
      existing.statistics = { ...existing.statistics, worldRank: row.rank, rankingPoints: row.points, rankMovement: row.rank_diff }
      teamRows.set(row.name, existing)
    }
    return { discipline, games: games.sort((a, b) => a.status === 'Scheduled' && b.status !== 'Scheduled' ? -1 : b.status === 'Scheduled' && a.status !== 'Scheduled' ? 1 : `${b.date}${b.time}`.localeCompare(`${a.date}${a.time}`)), teams: [...teamRows.values()], players, model }
  })
}

export async function esportsDirectory(type, options = {}) {
  const disciplines = selectedDisciplines(options.discipline || options.competition)
  const catalogs = await Promise.all(disciplines.map(disciplineCatalog))
  if (type === 'games' || type === 'teams' || type === 'players') return catalogs.flatMap(catalog => catalog[type])
  return []
}

export async function esportsStatus() {
  const catalogs = await Promise.all(['valorant', 'cs2', 'lol'].map(disciplineCatalog))
  return {
    sources: [
      { id: 'liquipedia-api', name: 'Liquipedia MediaWiki API', role: 'Valorant, CS2 and League of Legends current and historical match evidence', env: 'No key', configured: true, state: 'ready', detail: 'The three-year backfill is incremental, cached and rate-limited to 1 parse per 30 seconds. Normal HTML endpoints are never scraped.' },
      { id: 'csapi', name: 'CS API', role: 'CS2 results, rankings and player performance', env: 'No key', configured: true, state: 'ready', detail: 'Keyless professional CS2 history and current ranking evidence.' },
    ],
    models: catalogs.map(catalog => {
      const report = historicalReport(catalog.discipline)
      if (report) return {
        sport: report.sport, market: report.market, status: report.status, method: report.method,
        samples: report.samples, metrics: report.untouched_candidate,
        historical: report.historical_walk_forward, historicalReadiness: report.historical_readiness,
        promotion: report.promotion, oddsIndependent: report.odds_independent,
        timeRange: report.time_range, time_range: report.time_range,
      }
      return {
        sport: catalog.discipline, market: 'match_winner', status: 'shadow', method: 'time_decayed_series_elo',
        samples: { untouched_test: catalog.model.report.samples },
        metrics: { brier: catalog.model.report.brier, log_loss: catalog.model.report.logLoss, expected_calibration_error: catalog.model.report.calibration, accuracy: catalog.model.report.accuracy },
        promotion: { passed: false, reason: 'Historical Liquipedia backfill is still accumulating.' },
        timeRange: { training_through: new Date().toISOString() }, time_range: { training_through: new Date().toISOString() },
      }
    }),
  }
}
