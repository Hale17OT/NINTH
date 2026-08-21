import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveStatsBaseUrl } from './mlbStatsProvider.js'

test('prefers the deployment-local stats binding', () => {
  assert.equal(resolveStatsBaseUrl({
    NINTH_STATS_INTERNAL_URL: 'https://internal.vercel.test/',
    MLB_STATS_URL: 'https://legacy.example/api/stats',
    VERCEL_URL: 'public.vercel.test',
  }), 'https://internal.vercel.test')
})

test('falls back to configured, deployment, and local stats URLs', () => {
  assert.equal(resolveStatsBaseUrl({ MLB_STATS_URL: 'https://stats.example/' }), 'https://stats.example')
  assert.equal(resolveStatsBaseUrl({ VERCEL_URL: 'deploy.vercel.app' }), 'https://deploy.vercel.app/api/stats')
  assert.equal(resolveStatsBaseUrl({}), 'http://127.0.0.1:3002')
})
