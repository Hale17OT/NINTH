import { writeFile, mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { asyncBufferFromUrl, parquetReadObjects } from 'hyparquet'

const output = resolve(process.argv[2] || 'ml/data/multisport/american-football/nflverse_advanced.json')
const start = Number(process.argv[3] || new Date().getUTCFullYear() - 3)
const end = Number(process.argv[4] || new Date().getUTCFullYear() - 1)
const columns = ['game_id', 'posteam', 'play_type', 'epa', 'success', 'yards_gained', 'qb_dropback', 'sack', 'qb_hit', 'interception', 'fumble_lost', 'third_down_converted', 'third_down_failed', 'pass_oe', 'fixed_drive', 'drive', 'drive_ended_with_score']
const number = value => Number.isFinite(Number(value)) ? Number(value) : 0
const aggregate = new Map()

for (let season = start; season <= end; season += 1) {
  const file = await asyncBufferFromUrl({ url: `https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_${season}.parquet` })
  const rows = await parquetReadObjects({ file, columns })
  for (const row of rows) {
    if (!row.game_id || !row.posteam || !['pass', 'run'].includes(row.play_type)) continue
    const key = `${row.game_id}:${row.posteam}`
    const item = aggregate.get(key) || { game_id: row.game_id, team: row.posteam, plays: 0, epa: 0, success: 0, explosive: 0, dropbacks: 0, sacks: 0, qb_hits: 0, turnovers: 0, third_attempts: 0, third_converted: 0, pass_oe: [], drives: new Set(), scoring_drives: new Set() }
    item.plays += 1; item.epa += number(row.epa); item.success += number(row.success)
    item.explosive += Number((row.play_type === 'pass' && number(row.yards_gained) >= 20) || (row.play_type === 'run' && number(row.yards_gained) >= 10))
    item.dropbacks += Number(number(row.qb_dropback) > 0); item.sacks += Number(number(row.sack) > 0); item.qb_hits += Number(number(row.qb_hit) > 0)
    item.turnovers += Number(number(row.interception) > 0 || number(row.fumble_lost) > 0)
    const third = number(row.third_down_converted) > 0 || number(row.third_down_failed) > 0
    item.third_attempts += Number(third); item.third_converted += Number(number(row.third_down_converted) > 0)
    if (row.pass_oe != null) item.pass_oe.push(number(row.pass_oe) / 100)
    const drive = row.fixed_drive ?? row.drive
    if (drive != null) { item.drives.add(String(drive)); if (number(row.drive_ended_with_score) > 0) item.scoring_drives.add(String(drive)) }
    aggregate.set(key, item)
  }
}
const rows = [...aggregate.values()].map(item => ({
  game_id: item.game_id, team: item.team,
  epa_per_play: item.epa / Math.max(1, item.plays), success_rate: item.success / Math.max(1, item.plays), explosive_rate: item.explosive / Math.max(1, item.plays),
  sack_rate: item.sacks / Math.max(1, item.dropbacks), pressure_rate: item.qb_hits / Math.max(1, item.dropbacks), turnover_rate: item.turnovers / Math.max(1, item.plays),
  third_down_rate: item.third_converted / Math.max(1, item.third_attempts), drive_score_rate: item.scoring_drives.size / Math.max(1, item.drives.size),
  pass_over_expected: item.pass_oe.length ? item.pass_oe.reduce((sum, value) => sum + value, 0) / item.pass_oe.length : 0,
}))
await mkdir(dirname(output), { recursive: true })
await writeFile(output, JSON.stringify({ generated_at: new Date().toISOString(), source: 'nflverse play-by-play parquet', seasons: [start, end], rows }))
console.log(JSON.stringify({ output, seasons: [start, end], team_games: rows.length }))
