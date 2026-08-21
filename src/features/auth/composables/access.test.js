import test from 'node:test'
import assert from 'node:assert/strict'
import { safeReturnTo } from '../utils/returnTo.js'

test('return targets accept internal routes and reject open redirects', () => {
  assert.equal(safeReturnTo('/build?style=sweep'), '/build?style=sweep')
  assert.equal(safeReturnTo('https://example.com'), '/')
  assert.equal(safeReturnTo('//example.com/account'), '/')
  assert.equal(safeReturnTo('/\\example.com/account'), '/')
  assert.equal(safeReturnTo(undefined), '/')
})
