import test from 'node:test'
import assert from 'node:assert/strict'
import { canonicalMarketId, fairDecimalOdds, removeVig } from './markets.js'
import { EntityResolver } from '../services/entityResolver.js'

test('canonical markets do not depend on bookmaker labels', () => {
  const id = canonicalMarketId({ sport:'football', eventId:'1', market:'TOTAL_GOALS', selection:'over', line:2.5 })
  assert.equal(id, 'football:1:FULL_TIME:TOTAL_GOALS:-:OVER:2.5')
  assert.equal(fairDecimalOdds(.5), 2)
  assert.ok(Math.abs(removeVig([2, 3.5, 4]).reduce((a,b)=>a+b,0)-1) < 1e-12)
})

test('entity resolution fails closed on ambiguous aliases', () => {
  const resolver = new EntityResolver([{id:1,name:'United',competitionId:'a'},{id:2,name:'United',competitionId:'b'}])
  assert.equal(resolver.resolve('United').state, 'ambiguous')
  assert.equal(resolver.resolve('United',{competitionId:'b'}).entity.id, 2)
})
