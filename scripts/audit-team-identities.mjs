const base = process.env.NINTH_API_URL || 'http://127.0.0.1:3001/api'
const nflAliases = { JAC:'jax',LA:'lar',LAR:'lar',LV:'lv',OAK:'lv',SD:'lac',LAC:'lac',STL:'lar',WSH:'wsh',WAS:'wsh' }
const nbaAliases = { BRK:'bkn',CHO:'cha',NOH:'no',NOK:'no',NOP:'no',PHO:'phx',SAN:'sas',UTA:'utah' }
const get = async path => { const response = await fetch(`${base}${path}`); if (!response.ok) throw new Error(`${path}: ${response.status}`); return response.json() }
const logoFor = (sport, team) => {
  if (team.badge || team.logo) return team.badge || team.logo
  const suffix = String(team.id || '').includes(':') ? String(team.id).split(':').pop() : ''
  const code = String(suffix || team.code || '').toUpperCase()
  if (sport === 'baseball' && Number(team.id)) return `https://www.mlbstatic.com/team-logos/${Number(team.id)}.svg`
  if (sport === 'american-football' && code) return `https://a.espncdn.com/i/teamlogos/nfl/500/${nflAliases[code] || code.toLowerCase()}.png`
  if (sport === 'basketball' && code) return `https://a.espncdn.com/i/teamlogos/nba/500/${nbaAliases[code] || code.toLowerCase()}.png`
  return null
}
const sources = [
  ['baseball','/teams'], ['football','/multisport/football/teams'], ['american-football','/multisport/american-football/teams'],
  ['basketball','/multisport/basketball/teams'], ['esports','/multisport/esports/teams'],
]
const rows = (await Promise.all(sources.map(async ([sport,path]) => {
  const payload = await get(path), items = payload.items || payload.teams || payload || []
  return items.map(team => ({ sport, id:team.id, name:team.name, logo:logoFor(sport,team) }))
}))).flat()
let cursor = 0
const checked = []
const worker = async () => {
  while (cursor < rows.length) {
    const row = rows[cursor++]
    if (!row.logo) { checked.push({ ...row, state:'intentional-fallback' }); continue }
    try {
      const response = await fetch(row.logo, { method:'GET', headers:{ Range:'bytes=0-32' }, redirect:'follow' })
      checked.push({ ...row, state:response.ok?'resolved':`http-${response.status}` })
    } catch (error) { checked.push({ ...row, state:'network-error', detail:error.message }) }
  }
}
await Promise.all(Array.from({length:12},worker))
const summary = Object.groupBy(checked, row => row.sport)
const report = Object.fromEntries(Object.entries(summary).map(([sport,items]) => [sport, {
  teams:items.length, resolved:items.filter(row=>row.state==='resolved').length,
  fallback:items.filter(row=>row.state==='intentional-fallback').length,
  failed:items.filter(row=>!['resolved','intentional-fallback'].includes(row.state)),
}]))
console.log(JSON.stringify({ generatedAt:new Date().toISOString(), report }, null, 2))
if (Object.values(report).some(row => row.failed.length)) process.exitCode = 1
