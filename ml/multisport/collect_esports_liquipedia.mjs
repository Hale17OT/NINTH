/** Incremental, terms-compliant three-year Liquipedia historical backfill. */
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { resolve, join } from 'node:path'
import { load } from 'cheerio'

const config = {
  valorant: { wiki: 'valorant', label: 'Valorant' },
  cs2: { wiki: 'counterstrike', label: 'Counter-Strike 2' },
  lol: { wiki: 'leagueoflegends', label: 'League of Legends' },
}
const args = Object.fromEntries(process.argv.slice(2).map((value, index, all) => value.startsWith('--') ? [value.slice(2), all[index + 1]?.startsWith('--') ? true : all[index + 1]] : null).filter(Boolean))
const outputRoot = resolve(args.output || 'ml/data/multisport/esports-history')
const years = Number(args.years || 3)
const maxPages = Number(args['max-pages-per-year'] || 4)
const now = new Date()
const startYear = now.getUTCFullYear() - years
const userAgent = 'NINTHAnalytics/2.0 (personal local research; contact: research@example.invalid)'
const sleep = ms => new Promise(resolvePromise => setTimeout(resolvePromise, ms))
const clean = value => String(value || '').replace(/<[^>]+>/g, ' ').replace(/&[^;]+;/g, ' ').replace(/\s+/g, ' ').trim()
const slug = value => clean(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
let lastQuery = 0
let lastParse = 0

async function api(wiki, params, parse = false) {
  const minimum = parse ? 30_100 : 2_100
  const previous = parse ? lastParse : lastQuery
  if (Date.now() - previous < minimum) await sleep(minimum - (Date.now() - previous))
  if (parse) lastParse = Date.now(); else lastQuery = Date.now()
  const url = new URL(`https://liquipedia.net/${wiki}/api.php`)
  for (const [key, value] of Object.entries({ ...params, format: 'json', formatversion: 2 })) url.searchParams.set(key, value)
  const response = await fetch(url, { headers: { 'User-Agent': userAgent, Accept: 'application/json', 'Accept-Encoding': 'gzip' } })
  if (!response.ok) throw new Error(`Liquipedia ${wiki} API failed (${response.status})`)
  return response.json()
}

async function tournamentTitles(wiki, year) {
  const payload = await api(wiki, { action: 'query', list: 'search', srsearch: `intitle:${year} tournament`, srnamespace: 0, srlimit: 100 })
  const rows = payload?.query?.search || []
  const preferred = rows.filter(row => /(?:S|A)-Tier/i.test(row.snippet || '') || /(?:Champions|Masters|World|Major|League|Split|Stage|Playoffs|Finals)/i.test(row.title))
  return [...new Set((preferred.length ? preferred : rows).map(row => row.title))].slice(0, maxPages)
}

async function tournamentHtml(wiki, title) {
  const hash = createHash('sha1').update(`${wiki}:${title}`).digest('hex')
  const path = join(outputRoot, 'source-cache', wiki, `${hash}.json`)
  if (existsSync(path)) return JSON.parse(await readFile(path, 'utf8')).html
  const payload = await api(wiki, { action: 'parse', page: title, prop: 'text' }, true)
  const html = payload?.parse?.text || ''
  await mkdir(resolve(path, '..'), { recursive: true })
  await writeFile(path, JSON.stringify({ title, fetched_at: new Date().toISOString(), html }))
  return html
}

function parseMatches(html, discipline, tournament) {
  const $ = load(html)
  return $('.match-info, .brkts-match-info-popup').map((index, element) => {
    const node = $(element), opponents = node.find('.match-info-header-opponent')
    if (opponents.length < 2) return null
    const team = item => clean(item.find('.name a').attr('title') || item.find('.name').text()).replace(/\s*\(page does not exist\)$/i, '')
    const home = team(opponents.eq(0)), away = team(opponents.eq(1))
    if (!home || !away || /^(?:TBD|BYE)$/i.test(home) || /^(?:TBD|BYE)$/i.test(away)) return null
    const scores = node.find('.match-info-header-scoreholder-score').map((_, score) => Number(clean($(score).text()))).get()
    const timestamp = Number(node.find('.timer-object').attr('data-timestamp'))
    if (!timestamp || scores.length < 2 || !scores.every(Number.isFinite) || scores[0] === scores[1]) return null
    const format = clean(node.find('.match-info-header-scoreholder-lower').text())
    return { id: `${discipline}:${timestamp}:${slug(home)}:${slug(away)}`, discipline, tournament, event_time: new Date(timestamp * 1000).toISOString(), home, away, home_score: scores[0], away_score: scores[1], best_of: Number(format.match(/(?:bo|best of)\s*(\d)/i)?.[1] || 3) }
  }).get().filter(Boolean)
}

function ledger(matches, discipline) {
  const teams = new Map()
  const state = team => teams.get(team) || { elo: 1500, results: [], margins: [], last: null }
  const records = []
  for (const match of matches.sort((a, b) => a.event_time.localeCompare(b.event_time))) {
    const home = state(match.home), away = state(match.away), at = new Date(match.event_time)
    const average = (values, fallback) => values.length ? values.slice(-10).reduce((sum, value) => sum + value, 0) / Math.min(10, values.length) : fallback
    const rest = value => value ? Math.min(60, Math.max(0, (at - value) / 86_400_000)) : 30
    const probability = 1 / (1 + 10 ** ((away.elo - home.elo) / 400))
    const outcome = match.home_score > match.away_score ? 1 : 0
    records.push({
      event_id: match.id, event_time: match.event_time,
      knowledge_time: new Date(at.getTime() - 60_000).toISOString(), label: outcome,
      competition: match.tournament, home_team: match.home, away_team: match.away,
      features: {
        home_elo: home.elo, away_elo: away.elo, elo_difference: home.elo - away.elo,
        home_win_rate_10: average(home.results, .5), away_win_rate_10: average(away.results, .5),
        home_map_margin_10: average(home.margins, 0), away_map_margin_10: average(away.margins, 0),
        home_rest_days: rest(home.last), away_rest_days: rest(away.last),
        home_matches_seen: home.results.length, away_matches_seen: away.results.length,
        best_of: match.best_of,
      },
    })
    const delta = 24 * Math.log1p(Math.abs(match.home_score - match.away_score)) * (outcome - probability)
    home.elo += delta; away.elo -= delta
    home.results.push(outcome); away.results.push(1 - outcome)
    home.margins.push(match.home_score - match.away_score); away.margins.push(match.away_score - match.home_score)
    home.last = away.last = at; teams.set(match.home, home); teams.set(match.away, away)
  }
  return records
}

async function csApiHistory() {
  const matches = []
  for (let offset = 0; offset < 3000; offset += 100) {
    const response = await fetch(`https://api.csapi.de/matches/?limit=100&offset=${offset}`, { headers: { 'User-Agent': userAgent, Accept: 'application/json' } })
    if (!response.ok) break
    const rows = await response.json()
    if (!Array.isArray(rows) || !rows.length) break
    for (const row of rows) {
      const home = clean(row.team1?.name), away = clean(row.team2?.name)
      const homeScore = Number(row.team1?.score), awayScore = Number(row.team2?.score)
      if (!home || !away || !Number.isFinite(homeScore) || !Number.isFinite(awayScore) || homeScore === awayScore || !row.date) continue
      matches.push({ id: `cs2:csapi:${row.id}`, discipline: 'cs2', tournament: row.event || 'CS2 pro circuit', event_time: `${row.date}T12:00:00.000Z`, home, away, home_score: homeScore, away_score: awayScore, best_of: Number(row.best_of || 3) })
    }
    if (rows.length < 100) break
  }
  return matches
}

await mkdir(outputRoot, { recursive: true })
const report = { generated_at: new Date().toISOString(), source: 'Liquipedia MediaWiki API', odds_used: false, years: [startYear, now.getUTCFullYear()], disciplines: {} }
for (const [discipline, meta] of Object.entries(config)) {
  const matches = [], pages = []
  for (let year = startYear; year <= now.getUTCFullYear(); year += 1) {
    for (const title of await tournamentTitles(meta.wiki, year)) {
      try {
        const parsed = parseMatches(await tournamentHtml(meta.wiki, title), discipline, title)
        matches.push(...parsed); pages.push({ title, matches: parsed.length })
      } catch (error) { pages.push({ title, matches: 0, error: error.message }) }
    }
  }
  if (discipline === 'cs2') matches.push(...await csApiHistory())
  const unique = [...new Map(matches.map(row => [row.id, row])).values()]
  const records = ledger(unique, discipline)
  await writeFile(join(outputRoot, `${discipline}_match_winner.jsonl`), records.map(row => JSON.stringify(row)).join('\n') + (records.length ? '\n' : ''))
  report.disciplines[discipline] = { pages, matches: unique.length, ledger_rows: records.length }
}
await writeFile(join(outputRoot, 'collection.json'), JSON.stringify(report, null, 2))
console.log(JSON.stringify(report, null, 2))
