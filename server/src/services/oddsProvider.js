import { cache } from './cache.js'

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

export const oddsProvider = {
  configured: () => Boolean(apiKey()),
  async mlbOdds() {
    return cache.remember('odds:mlb', 2 * 60_000, async () => {
      const response = await request('/sports/baseball_mlb/odds', {
        regions: region(), markets: 'h2h,spreads,totals', oddsFormat: format(), dateFormat: 'iso',
      })
      return { events: response.data.map(normalizeEvent), quota: response.quota }
    })
  },
  status() {
    return { provider: 'The Odds API', status: apiKey() ? 'configured' : 'awaiting-key', region: region(), format: format() }
  },
}
