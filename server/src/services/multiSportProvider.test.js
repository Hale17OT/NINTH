import test from 'node:test'
import assert from 'node:assert/strict'
import { competitionCatalog, multiSportProvider, predictionGame } from './multiSportProvider.js'

test('football catalog covers top five, UEFA competitions and domestic cups', () => {
  const names = new Set(competitionCatalog.football.map(row => row.name))
  for (const expected of [
    'Premier League', 'Championship', 'La Liga', 'Bundesliga', 'Serie A', 'Ligue 1',
    'UEFA Champions League', 'UEFA Europa League', 'UEFA Conference League',
    'FA Cup', 'EFL Cup', 'Copa del Rey', 'DFB-Pokal', 'Coppa Italia', 'Coupe de France',
  ]) assert.equal(names.has(expected), true, `${expected} missing`)
})

test('an immutable prediction-only fixture remains routable as a real match', () => {
  const game = predictionGame({event_id:'fpl:1',competition_id:'4328',competition:'Premier League',competition_code:'E0',event_time:'2026-08-21T19:00:00Z',home_team:'Arsenal',away_team:'Coventry City',markets:{home_win:.55}})
  assert.equal(game.id, 'fpl:1')
  assert.equal(game.home.id, 'prediction:arsenal')
  assert.equal(game.prediction.markets.home_win, .55)
})

test('directory catalog is operational without calling a remote provider', async () => {
  const result = await multiSportProvider.directory('football', 'leagues')
  assert.equal(result.count, 15)
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

test('NFL status exposes every evaluated core model and its independent decision', async () => {
  const result = await multiSportProvider.directory('american-football', 'status')
  assert.deepEqual(result.models.map(row => row.market), ['home_win', 'away_team_points', 'home_margin', 'home_team_points', 'moneyline', 'spread', 'total', 'total_points'])
  assert.equal(result.models.find(row => row.market === 'home_win').historicalReadiness.passed, true)
  assert.equal(result.models.find(row => row.market === 'moneyline').decision, 'LIMITED')
  assert.equal(result.models.find(row => row.market === 'spread').historicalReadiness.passed, false)
  assert.equal(result.models.find(row => row.market === 'total').historicalReadiness.passed, false)
  assert.equal(result.builderEligible, false)
  assert.equal(result.liveAudit.snapshot_rule, 'first generated forecast within 48 hours of kickoff')
})

test('esports exposes Valorant, CS2 and League of Legends with evaluated models', async () => {
  assert.deepEqual(competitionCatalog.esports.map(row => row.id), ['valorant', 'cs2', 'lol'])
  const result = await multiSportProvider.directory('esports', 'status')
  assert.equal(result.presentationReady, true)
  assert.match(result.modelState, /EVALUATED|HISTORICAL EVIDENCE/)
  assert.deepEqual(result.models.map(row => row.sport), ['valorant', 'cs2', 'lol'])
  assert.ok(result.models.every(row => Number.isFinite(row.metrics.brier)))
  assert.ok(result.sources.some(source => source.id === 'liquipedia-api' && source.state === 'ready'))
  assert.ok(result.sources.every(source => !source.name.toLowerCase().includes('pandascore')))
})

test('unsupported sport and directory fail explicitly', async () => {
  await assert.rejects(() => multiSportProvider.directory('hockey', 'games'), /Unsupported sport/)
  await assert.rejects(() => multiSportProvider.directory('football', 'stadiums'), /Unsupported directory/)
})
