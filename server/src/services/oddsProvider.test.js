import test from 'node:test'
import assert from 'node:assert/strict'
import { MelBetOddsProvider, OddsProvider, TheOddsApiProvider } from './oddsProvider.js'

test('odds providers share an abstraction without leaking provider labels into canonical markets', () => {
  assert.ok(new TheOddsApiProvider() instanceof OddsProvider)
  const snapshots = []
  const provider = new MelBetOddsProvider({ history: { record: snapshot => snapshots.push(snapshot) } })
  const markets = provider.discoverMarkets({GE:[{G:10,GN:'Total',E:[[{T:1,N:'Over',P:2.5,C:1.9}]]}]},{sport:'football',eventId:'game'})
  assert.equal(markets[0].canonicalMarket, 'TOTAL_GOALS')
  assert.equal(markets[0].selections[0].canonical.market, 'TOTAL_GOALS')
  assert.deepEqual(snapshots.map(({eventId, market, selection, line, price, provider}) => ({eventId, market, selection, line, price, provider})), [
    {eventId:'game', market:'TOTAL_GOALS', selection:'OVER', line:2.5, price:1.9, provider:'MelBet'},
  ])
})

test('unmapped MelBet competitions fail closed', async () => {
  await assert.rejects(() => new MelBetOddsProvider().footballCompetition('unknown'), /will not be guessed/)
})
