import assert from 'node:assert/strict'
import test from 'node:test'

import { isAllowedModelObject } from './modelArtifactSigner.js'

test('allows only the production manifest and immutable release objects', () => {
  assert.equal(isAllowedModelObject('production/manifest.json'), true)
  assert.equal(isAllowedModelObject('releases/deploy-20260822-d73a8df/artifacts/moneyline.joblib'), true)
  assert.equal(isAllowedModelObject('releases/release.1/data/snapshots.jsonl.gz'), true)
})

test('rejects traversal, arbitrary buckets, and malformed release objects', () => {
  assert.equal(isAllowedModelObject('production/other.json'), false)
  assert.equal(isAllowedModelObject('releases/a/../secret'), false)
  assert.equal(isAllowedModelObject('releases/a/private/secret'), false)
  assert.equal(isAllowedModelObject('releases/a\\artifacts\\model.joblib'), false)
  assert.equal(isAllowedModelObject('/releases/a/artifacts/model.joblib'), false)
})
