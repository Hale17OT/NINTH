import { cache } from './cache.js'

const weatherCodes = {
  0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast',
  45: 'Fog', 48: 'Icy fog', 51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle',
  61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 71: 'Light snow', 80: 'Rain showers',
  81: 'Rain showers', 82: 'Heavy showers', 95: 'Thunderstorms', 96: 'Storms with hail', 99: 'Storms with hail',
}

const compass = degrees => ['N','NE','E','SE','S','SW','W','NW'][Math.round((degrees || 0) / 45) % 8]

async function fetchForecast(latitude, longitude, gameTime) {
  const params = new URLSearchParams({
    latitude, longitude, timezone: 'UTC', temperature_unit: 'fahrenheit', wind_speed_unit: 'mph',
    hourly: 'temperature_2m,relative_humidity_2m,precipitation_probability,weather_code,wind_speed_10m,wind_direction_10m',
    forecast_days: '7',
  })
  const response = await fetch(`https://api.open-meteo.com/v1/forecast?${params}`)
  if (!response.ok) throw new Error(`Open-Meteo returned ${response.status}`)
  const data = await response.json()
  const target = new Date(gameTime).getTime()
  let index = 0
  data.hourly.time.forEach((time, i) => {
    if (Math.abs(new Date(`${time}Z`).getTime() - target) < Math.abs(new Date(`${data.hourly.time[index]}Z`).getTime() - target)) index = i
  })
  const get = key => data.hourly[key]?.[index]
  return {
    provider: 'Open-Meteo', time: data.hourly.time[index],
    temperature: Math.round(get('temperature_2m')),
    humidity: get('relative_humidity_2m'),
    precipitation: get('precipitation_probability'),
    condition: weatherCodes[get('weather_code')] || 'Variable conditions',
    windSpeed: Math.round(get('wind_speed_10m')),
    windDirection: compass(get('wind_direction_10m')),
  }
}

export const weatherProvider = {
  key(latitude, longitude, gameTime) {
    if (latitude == null || longitude == null || !gameTime) return null
    return `weather:${latitude}:${longitude}:${new Date(gameTime).toISOString().slice(0, 13)}`
  },
  cached(latitude, longitude, gameTime) {
    const key = this.key(latitude, longitude, gameTime)
    return key ? cache.peek(key) : undefined
  },
  forecast(latitude, longitude, gameTime) {
    if (latitude == null || longitude == null || !gameTime) return Promise.resolve(null)
    return cache.remember(this.key(latitude, longitude, gameTime), 30 * 60_000, () => fetchForecast(latitude, longitude, gameTime))
  },
}
