import test from 'node:test'
import assert from 'node:assert/strict'
import { competitionCatalog, multiSportProvider } from './multiSportProvider.js'

test('football catalog covers top five, UEFA competitions and domestic cups', () => {
  const names = new Set(competitionCatalog.football.map(row => row.name))
  for (const expected of [
    'Premier League', 'La Liga', 'Bundesliga', 'Serie A', 'Ligue 1',
    'UEFA Champions League', 'UEFA Europa League', 'UEFA Conference League',
    'FA Cup', 'EFL Cup', 'Copa del Rey', 'DFB-Pokal', 'Coppa Italia', 'Coupe de France',
  ]) assert.equal(names.has(expected), true, `${expected} missing`)
})

test('directory catalog is operational without calling a remote provider', async () => {
  const result = await multiSportProvider.directory('football', 'leagues')
  assert.equal(result.count, 14)
  assert.equal(result.presentationOnly, false)
  assert.equal(result.modelTrainingAllowed, true)
})

test('status reports source requirements without exposing credentials', async () => {
  const result = await multiSportProvider.directory('football', 'status')
  assert.equal(result.type, 'status')
  assert.equal(result.builderEligible, false)
  assert.ok(result.sources.some(source => source.id === 'presentation' && source.configured))
  assert.ok(result.sources.every(source => !('value' in source) && !('token' in source)))
})

test('NFL status exposes independently gated moneyline, spread and total models', async () => {
  const result = await multiSportProvider.directory('american-football', 'status')
  assert.deepEqual(result.models.map(row => row.market), ['home_win', 'spread', 'total'])
  assert.equal(result.models.find(row => row.market === 'home_win').historicalReadiness.passed, true)
  assert.equal(result.models.find(row => row.market === 'spread').historicalReadiness.passed, false)
  assert.equal(result.models.find(row => row.market === 'total').historicalReadiness.passed, false)
  assert.equal(result.builderEligible, false)
  assert.equal(result.liveAudit.snapshot_rule, 'first generated forecast within 48 hours of kickoff')
})

test('esports exposes Valorant, CS2 and League of Legends with live shadow models', async () => {
  assert.deepEqual(competitionCatalog.esports.map(row => row.id), ['valorant', 'cs2', 'lol'])
  const result = await multiSportProvider.directory('esports', 'status')
  assert.equal(result.presentationReady, true)
  assert.match(result.modelState, /THREE-YEAR AUDITS|HISTORICAL READY/)
  assert.deepEqual(result.models.map(row => row.sport), ['valorant', 'cs2', 'lol'])
  assert.ok(result.models.every(row => Number.isFinite(row.metrics.brier)))
  assert.ok(result.sources.some(source => source.id === 'liquipedia-api' && source.state === 'ready'))
  assert.ok(result.sources.every(source => !source.name.toLowerCase().includes('pandascore')))
})

test('unsupported sport and directory fail explicitly', async () => {
  await assert.rejects(() => multiSportProvider.directory('hockey', 'games'), /Unsupported sport/)
  await assert.rejects(() => multiSportProvider.directory('football', 'stadiums'), /Unsupported directory/)
})
