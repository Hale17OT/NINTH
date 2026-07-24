const weatherCodes = {
  0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast',
  45: 'Fog', 48: 'Icy fog', 51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle',
  61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 71: 'Light snow', 80: 'Rain showers',
  81: 'Rain showers', 82: 'Heavy showers', 95: 'Thunderstorms', 96: 'Storms with hail', 99: 'Storms with hail',
}

const DOCUMENT_TTL_MS = 60 * 60_000
const STALE_TTL_MS = 6 * 60 * 60_000
const documents = new Map()
const pending = new Map()
let backoffUntil = 0

const compass = degrees => ['N','NE','E','SE','S','SW','W','NW'][Math.round((degrees || 0) / 45) % 8]
const coordinateKey = (latitude, longitude) => `${Number(latitude).toFixed(3)}:${Number(longitude).toFixed(3)}`

function selectForecast(data, gameTime, stale = false) {
  const times = data?.hourly?.time || []
  if (!times.length) return null
  const target = new Date(gameTime).getTime()
  let index = 0
  times.forEach((time, candidate) => {
    if (Math.abs(new Date(`${time}Z`).getTime() - target) < Math.abs(new Date(`${times[index]}Z`).getTime() - target)) index = candidate
  })
  const get = key => data.hourly[key]?.[index]
  return {
    provider: 'Open-Meteo', time: times[index], available: true, stale,
    temperature: Math.round(get('temperature_2m')),
    humidity: get('relative_humidity_2m'),
    precipitation: get('precipitation_probability'),
    condition: weatherCodes[get('weather_code')] || 'Variable conditions',
    windSpeed: Math.round(get('wind_speed_10m')),
    windDirection: compass(get('wind_direction_10m')),
    source: stale ? 'Open-Meteo cached forecast' : 'Open-Meteo forecast',
  }
}

async function fetchDocument(latitude, longitude) {
  const params = new URLSearchParams({
    latitude, longitude, timezone: 'UTC', temperature_unit: 'fahrenheit', wind_speed_unit: 'mph',
    hourly: 'temperature_2m,relative_humidity_2m,precipitation_probability,weather_code,wind_speed_10m,wind_direction_10m',
    forecast_days: '7',
  })
  const response = await fetch(`https://api.open-meteo.com/v1/forecast?${params}`)
  if (response.status === 429) {
    const retryAfter = Number(response.headers.get('retry-after'))
    backoffUntil = Date.now() + (Number.isFinite(retryAfter) ? Math.max(60, Math.min(900, retryAfter)) * 1000 : 5 * 60_000)
    const error = new Error('Open-Meteo rate limited')
    error.rateLimited = true
    throw error
  }
  if (!response.ok) throw new Error(`Open-Meteo returned ${response.status}`)
  return response.json()
}

async function documentFor(latitude, longitude) {
  const key = coordinateKey(latitude, longitude)
  const current = documents.get(key)
  if (current && Date.now() - current.savedAt < DOCUMENT_TTL_MS) return { data:current.data, stale:false }
  if (Date.now() < backoffUntil) return current && Date.now() - current.savedAt < STALE_TTL_MS ? { data:current.data, stale:true } : null
  if (pending.has(key)) return pending.get(key)
  const request = fetchDocument(latitude, longitude)
    .then(data => { documents.set(key, { data, savedAt:Date.now() }); return { data, stale:false } })
    .catch(() => current && Date.now() - current.savedAt < STALE_TTL_MS ? { data:current.data, stale:true } : null)
    .finally(() => pending.delete(key))
  pending.set(key, request)
  return request
}

export const weatherProvider = {
  key(latitude, longitude) {
    if (latitude == null || longitude == null) return null
    return coordinateKey(latitude, longitude)
  },
  cached(latitude, longitude, gameTime) {
    const key = this.key(latitude, longitude)
    const current = key ? documents.get(key) : null
    return current ? selectForecast(current.data, gameTime, Date.now() - current.savedAt >= DOCUMENT_TTL_MS) : undefined
  },
  async forecast(latitude, longitude, gameTime) {
    if (latitude == null || longitude == null || !gameTime) return null
    const document = await documentFor(latitude, longitude)
    return document ? selectForecast(document.data, gameTime, document.stale) : null
  },
}
