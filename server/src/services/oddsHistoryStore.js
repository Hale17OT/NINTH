import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { canonicalMarketId } from '../domain/markets.js'

export class OddsHistoryStore {
  constructor(path = join(process.cwd(), 'ml', 'data', 'odds', 'snapshots.jsonl')) {
    this.path = path; this.latestByKey = new Map(); this.loaded = false
  }
  load() {
    if (this.loaded) return
    this.loaded = true
    if (!existsSync(this.path)) return
    for (const line of readFileSync(this.path, 'utf8').split(/\r?\n/).filter(Boolean)) {
      try { const row = JSON.parse(line); this.latestByKey.set(row.key, row) } catch {}
    }
  }
  record(snapshot) {
    this.load()
    const observedAt = snapshot.observedAt || new Date().toISOString()
    const key = canonicalMarketId(snapshot)
    const row = { ...snapshot, key, observedAt, price: Number(snapshot.price), provider: String(snapshot.provider) }
    if (!Number.isFinite(row.price) || row.price <= 1) throw new Error('Odds snapshot requires decimal price above 1.0')
    const previous = this.latestByKey.get(key)
    if (previous && previous.price === row.price && previous.line === row.line && previous.provider === row.provider) return previous
    mkdirSync(dirname(this.path), { recursive: true })
    appendFileSync(this.path, `${JSON.stringify(row)}\n`, 'utf8')
    this.latestByKey.set(key, row)
    return row
  }
  latest(input) { this.load(); return this.latestByKey.get(canonicalMarketId(input)) || null }
}

export const oddsHistory = new OddsHistoryStore()
