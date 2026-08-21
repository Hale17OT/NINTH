import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { OddsHistoryStore } from './oddsHistoryStore.js'

test('odds history is append-only and deduplicates unchanged provider snapshots', t => {
  const directory = mkdtempSync(join(tmpdir(), 'ninth-odds-'))
  t.after(() => rmSync(directory, { recursive:true, force:true }))
  const path = join(directory, 'snapshots.jsonl')
  const store = new OddsHistoryStore(path)
  const base = {
    sport:'football', eventId:'fixture-1', market:'TOTAL_GOALS', selection:'OVER',
    line:2.5, period:'FULL_TIME', provider:'MelBet', price:1.9,
  }
  store.record({...base, observedAt:'2026-08-19T00:00:00Z'})
  store.record({...base, observedAt:'2026-08-19T00:01:00Z'})
  store.record({...base, price:1.95, observedAt:'2026-08-19T00:02:00Z'})
  const rows = readFileSync(path, 'utf8').trim().split(/\r?\n/).map(JSON.parse)
  assert.equal(rows.length, 2)
  assert.deepEqual(rows.map(row => row.price), [1.9, 1.95])
  assert.equal(store.latest(base).observedAt, '2026-08-19T00:02:00Z')
})
