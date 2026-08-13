const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = __dirname;
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
const bridge = fs.readFileSync(path.join(root, 'ninth-bridge.js'), 'utf8');
const melbet = fs.readFileSync(path.join(root, 'melbet-autofill.js'), 'utf8');
const worker = fs.readFileSync(path.join(root, 'service-worker.js'), 'utf8');

assert.equal(manifest.version, '1.1.1');
assert.ok(manifest.permissions.includes('storage'));
assert.match(bridge, /NINTH_MELBET_HISTORY_REQUEST/);
assert.match(bridge, /ninthMelbetHistoryRequest/);
assert.match(bridge, /ninthMelbetHistoryResponse/);
assert.match(bridge, /NINTH_MELBET_HISTORY_ALL_REQUEST/);
assert.match(bridge, /ninthMelbetHistoryAllResponse/);
assert.match(melbet, /drawer\.scrollTop = drawer\.scrollHeight/);
assert.match(melbet, /drawer\.scrollTop=originalTop/);
assert.match(melbet, /Nothing was imported/);
assert.match(melbet, /NINTH_EXTRACT_SELECTED_MELBET_SLIP/);
assert.match(melbet, /extractAllMissingHistory/);
assert.match(melbet, /vue-recycle-scroller/);
assert.match(worker, /office\\\/history/);

console.log('MelBet helper history contract: OK');
