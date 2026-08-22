import test from 'node:test'
import assert from 'node:assert/strict'
import {
  LIVE_SCOREBOARD_REFRESH_MS,
  LIVE_VIEW_REFRESH_MS,
  PREGAME_REFRESH_MS,
  scoreboardRefreshMs,
} from './pollingPolicy.js'

test('only an actively viewed live screen retains ten-second polling', () => {
  assert.equal(LIVE_VIEW_REFRESH_MS, 10_000)
  assert.equal(scoreboardRefreshMs(true), LIVE_SCOREBOARD_REFRESH_MS)
  assert.equal(LIVE_SCOREBOARD_REFRESH_MS, 60_000)
})

test('ordinary pregame and heavy dashboard work refreshes every five minutes', () => {
  assert.equal(PREGAME_REFRESH_MS, 300_000)
  assert.equal(scoreboardRefreshMs(false), PREGAME_REFRESH_MS)
})

