import { writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { mkdir } from 'node:fs/promises'
import { asyncBufferFromUrl, parquetReadObjects } from 'hyparquet'

const output = resolve(process.argv[2] || 'ml/data/multisport/basketball/nba_advanced.json')
const base = 'https://raw.githubusercontent.com/llimllib/nba_data/main/data/espn'
const normalize = value => typeof value === 'bigint' ? Number(value) : value
const loadRows = async name => {
  const file = await asyncBufferFromUrl({ url: `${base}/${name}.parquet` })
  return parquetReadObjects({ file })
}

const [teamBox, fourFactors] = await Promise.all([loadRows('team_box'), loadRows('four_factors')])
const fourByTeam = new Map(fourFactors.map(row => [`${row.gameId}:${row.team}`, row]))
const rows = teamBox.map(row => {
  const plain = Object.fromEntries(Object.entries(row).map(([key, value]) => [key, normalize(value)]))
  const four = fourByTeam.get(`${plain.game_id}:${plain.tmName}`) || {}
  return {
    ...plain,
    two_point_possessions: normalize(four['2pt_oPoss']),
    three_point_possessions: normalize(four['3pt_oPoss']),
    free_throw_possessions: normalize(four.freethrow_oPoss),
    rebound_possessions: normalize(four.rebound_oPoss),
    turnover_possessions: normalize(four.turnover_oPoss),
  }
})
await mkdir(dirname(output), { recursive: true })
await writeFile(output, JSON.stringify({
  generated_at: new Date().toISOString(),
  source: 'llimllib/nba_data NBA Stats + ESPN open parquet mirror',
  rows,
}))
console.log(JSON.stringify({ output, rows: rows.length }))
