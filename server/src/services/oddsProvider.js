import { cache } from './cache.js'
import { MarketType, canonicalMarket } from '../domain/markets.js'
import { oddsHistory } from './oddsHistoryStore.js'

const baseUrl = 'https://api.the-odds-api.com/v4'
const apiKey = () => process.env.THE_ODDS_API_KEY?.trim()
const region = () => process.env.ODDS_REGION || 'us'
const format = () => process.env.ODDS_FORMAT || 'american'

async function request(path, params = {}) {
  if (!apiKey()) throw new Error('THE_ODDS_API_KEY is not configured')
  const query = new URLSearchParams({ ...params, apiKey: apiKey() })
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 10000)
  try {
    const response = await fetch(`${baseUrl}${path}?${query}`, { signal: controller.signal })
    if (!response.ok) {
      const body = await response.text()
      throw new Error(`The Odds API returned ${response.status}: ${body.slice(0, 160)}`)
    }
    return {
      data: await response.json(),
      quota: {
        remaining: response.headers.get('x-requests-remaining'),
        used: response.headers.get('x-requests-used'),
        last: response.headers.get('x-requests-last'),
      },
    }
  } finally {
    clearTimeout(timeout)
  }
}

function normalizeEvent(event) {
  const bookmakers = (event.bookmakers || []).map(bookmaker => ({
    key: bookmaker.key,
    title: bookmaker.title,
    updatedAt: bookmaker.last_update,
    markets: Object.fromEntries((bookmaker.markets || []).map(market => [market.key, market.outcomes || []])),
  }))
  const prices = team => bookmakers.flatMap(book => (book.markets.h2h || []).filter(outcome => outcome.name === team).map(outcome => ({ bookmaker: book.title, price: outcome.price })))
  const awayPrices = prices(event.away_team), homePrices = prices(event.home_team)
  const firstSpread = bookmakers.find(book => book.markets.spreads)?.markets.spreads || []
  const firstTotal = bookmakers.find(book => book.markets.totals)?.markets.totals || []
  return {
    id: event.id,
    commenceTime: event.commence_time,
    awayTeam: event.away_team,
    homeTeam: event.home_team,
    awayMoneyline: awayPrices[0]?.price ?? null,
    homeMoneyline: homePrices[0]?.price ?? null,
    awaySpread: firstSpread.find(item => item.name === event.away_team) || null,
    homeSpread: firstSpread.find(item => item.name === event.home_team) || null,
    over: firstTotal.find(item => item.name === 'Over') || null,
    under: firstTotal.find(item => item.name === 'Under') || null,
    bookmakers,
  }
}

export class OddsProvider {
  constructor(name) { this.name = name }
  configured() { return false }
  status() { return { provider: this.name, status: this.configured() ? 'configured' : 'unavailable' } }
}

export class TheOddsApiProvider extends OddsProvider {
  constructor() { super('The Odds API') }
  configured() { return Boolean(apiKey()) }
  async mlbOdds() {
    return cache.remember('odds:mlb', 2 * 60_000, async () => {
      const response = await request('/sports/baseball_mlb/odds', {
        regions: region(), markets: 'h2h,spreads,totals', oddsFormat: format(), dateFormat: 'iso',
      })
      return { events: response.data.map(normalizeEvent), quota: response.quota }
    })
  }
  status() {
    return { provider: 'The Odds API', status: apiKey() ? 'configured' : 'awaiting-key', region: region(), format: format() }
  }
}

const MELBET_COMPETITIONS = Object.freeze({
  '4328': { championId: 88637, slug: 'england-premier-league' },
  '4329': { championId: 105759, slug: 'england-championship' },
})
const MELBET_HOSTS = ['https://mel-bet.et', 'https://melbet-322491.top']
const melbetMarketType = label => {
  const value = String(label || '').toLowerCase()
  if (/both teams.*score|btts/.test(value)) return MarketType.BTTS
  if (/total/.test(value)) return MarketType.TOTAL_GOALS
  if (/double chance/.test(value)) return MarketType.DOUBLE_CHANCE
  if (/correct score/.test(value)) return MarketType.CORRECT_SCORE
  if (/corner/.test(value)) return MarketType.CORNERS
  if (/card/.test(value)) return MarketType.CARDS
  if (/1x2|match result|winner/.test(value)) return MarketType.MATCH_WINNER_3WAY
  return null
}

export class MelBetOddsProvider extends OddsProvider {
  constructor({ hosts = MELBET_HOSTS, fetcher = fetch, history = oddsHistory } = {}) {
    super('MelBet'); this.hosts = hosts; this.fetcher = fetcher; this.history = history
  }
  configured() { return true }
  async request(path, params, usable = value => Boolean(value)) {
    const errors = []
    for (const host of this.hosts) {
      for (let attempt = 0; attempt < 2; attempt += 1) {
        const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 8000)
        try {
          const query = new URLSearchParams(params)
          const response = await this.fetcher(`${host}${path}?${query}`, { signal: controller.signal, headers: { Accept:'application/json', Referer:`${host}/en/line/football` } })
          if (!response.ok) throw new Error(`HTTP ${response.status}`)
          const value = (await response.json()).Value || {}
          if (!usable(value)) throw new Error('empty market payload')
          return { value, host, observedAt: new Date().toISOString() }
        } catch (error) {
          errors.push(`${host} attempt ${attempt + 1}: ${error.message}`)
          if (attempt === 0) await new Promise(resolve => setTimeout(resolve, 250))
        } finally { clearTimeout(timeout) }
      }
    }
    throw new Error(`MelBet unavailable: ${errors.join(' | ')}`)
  }
  discoverMarkets(payload, context) {
    const discovered = (payload?.GE || []).map(group => {
      const providerLabel = group.GN || group.N || group.Name || `MelBet group ${group.G}`
      const market = melbetMarketType(providerLabel)
      return {
        provider: this.name, providerMarketId: String(group.G || ''), providerLabel,
        canonicalMarket: market,
        supported: Boolean(market),
        selections: flattenMelBetSelections(group.E).map(row => ({
          providerTypeId: String(row.T || ''), providerLabel: row.N || row.PL?.N || '',
          line: row.P == null ? null : Number(row.P), price: row.C == null ? null : Number(row.C),
          canonical: market ? canonicalMarket({ ...context, market, selection: row.N || row.PL?.N, line: row.P }) : null,
        })),
      }
    })
    if (context?.sport && context?.eventId) {
      for (const group of discovered) {
        for (const selection of group.selections) {
          if (!selection.canonical || !Number.isFinite(selection.price) || selection.price <= 1) continue
          this.history.record({
            ...selection.canonical,
            price: selection.price,
            provider: this.name,
            providerMarketId: group.providerMarketId,
            providerTypeId: selection.providerTypeId,
          })
        }
      }
    }
    return discovered
  }
  async footballCompetition(competitionId) {
    const competition = MELBET_COMPETITIONS[String(competitionId)]
    if (!competition) throw new Error(`MelBet competition ${competitionId} is not mapped and will not be guessed`)
    const result = await cache.remember(`odds:melbet:football:${competitionId}`, 5 * 60_000, () => this.request(
      '/service-api/LineFeed/GetChampZip',
      { sport:1, champ:competition.championId, lng:'en', partner:1 },
      value => Boolean(value.G),
    ))
    return { ...result, competitionId:String(competitionId), championId:competition.championId }
  }
  status() { return { provider:this.name, status:'available-with-fallback', competitions:Object.keys(MELBET_COMPETITIONS), freshnessSeconds:300 } }
}

function flattenMelBetSelections(value) {
  if (Array.isArray(value)) return value.flatMap(flattenMelBetSelections)
  if (!value || typeof value !== 'object') return []
  if ('T' in value) return [value]
  return Object.values(value).flatMap(flattenMelBetSelections)
}

export const oddsProvider = new TheOddsApiProvider()
export const melBetOddsProvider = new MelBetOddsProvider()
export const oddsProviders = new Map([[oddsProvider.name, oddsProvider], [melBetOddsProvider.name, melBetOddsProvider]])
