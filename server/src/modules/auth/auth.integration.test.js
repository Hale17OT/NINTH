import test, { after, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import express from 'express'
import request from 'supertest'

process.env.NODE_ENV = 'test'
process.env.DATABASE_URL = process.env.TEST_DATABASE_URL || 'postgresql://ninth@127.0.0.1:54329/ninth_test?schema=public'
process.env.SESSION_SECRET ||= 'ninth-auth-integration-test-session-secret'
process.env.DISABLE_AUTH_RATE_LIMITS = '1'

const { default: app } = await import('../../app.js')
const { prisma } = await import('../../db/prisma.js')
const { __testEmailOutbox } = await import('../../services/email/emailService.js')
const { completeGoogleIdentity } = await import('./auth.service.js')
const { passwordResetLimiter } = await import('../../middleware/rateLimit.js')
const { mlbStatsProvider } = await import('../../services/mlbStatsProvider.js')

const userFixture = suffix => ({
  displayName: `Ninth Tester ${suffix}`,
  email: `ninth-${suffix}@example.com`,
  password: 'Correct-Horse-99!',
  passwordConfirmation: 'Correct-Horse-99!',
  termsAccepted: true,
  remember: true,
})

const csrf = async agent => {
  const response = await agent.get('/api/auth/csrf').expect(200)
  assert.ok(response.headers['set-cookie']?.length, 'CSRF response must set a cookie')
  assert.equal(response.headers['set-cookie'][0].includes('Secure'), false, response.headers['set-cookie'][0].replace(/=.*/, '=<redacted>'))
  return response.body.csrfToken
}
const post = async (agent, path, body, expected = 200) => {
  const csrfToken = await csrf(agent)
  const response = await agent.post(path).set('x-csrf-token', csrfToken).send(body)
  assert.equal(response.status, expected, `${path}: ${response.body.code || response.body.error || response.status}`)
  return response
}
const register = async (agent, suffix, expected = 201) => post(agent, '/api/auth/register', userFixture(suffix), expected)
const tokenFromLatestEmail = kind => {
  const message = __testEmailOutbox.all().filter(item => item.kind === kind).at(-1)
  assert.ok(message?.url, `Expected a ${kind} email`)
  return new URL(message.url).searchParams.get('token')
}

beforeEach(async () => {
  process.env.DISABLE_AUTH_RATE_LIMITS = '1'
  __testEmailOutbox.clear()
  await prisma.securityEvent.deleteMany()
  await prisma.oAuthState.deleteMany()
  await prisma.user.deleteMany()
})

after(async () => prisma.$disconnect())

test('registration creates a hashed password identity, session and restorable user', async () => {
  const agent = request.agent(app)
  const response = await register(agent, 'register')
  assert.equal(response.body.user.email, 'ninth-register@example.com')
  assert.equal(response.body.user.providers[0], 'PASSWORD')
  assert.equal(response.body.verificationSent, true)
  assert.match(response.headers['set-cookie'][0], /ninth_session=/)
  const account = await prisma.authAccount.findFirst({ where: { userId: response.body.user.id } })
  assert.ok(account.passwordHash.startsWith('$argon2id$'))
  assert.equal(account.passwordHash.includes('Correct-Horse-99!'), false)
  const restored = await agent.get('/api/auth/me').expect(200)
  assert.equal(restored.body.user.id, response.body.user.id)
})

test('duplicate registration and incorrect password return safe failures', async () => {
  const agent = request.agent(app)
  await register(agent, 'duplicate')
  await register(request.agent(app), 'duplicate', 409)
  const failure = await post(request.agent(app), '/api/auth/login', { email: 'ninth-duplicate@example.com', password: 'not-the-password' }, 401)
  assert.equal(failure.body.error, 'Invalid email or password.')
})

test('password login, logout and expired sessions are enforced', async () => {
  const registered = request.agent(app)
  await register(registered, 'session')
  await post(registered, '/api/auth/logout', {}, 204)
  assert.equal((await registered.get('/api/auth/me').expect(200)).body.user, null)

  const agent = request.agent(app)
  await post(agent, '/api/auth/login', { email: 'ninth-session@example.com', password: 'Correct-Horse-99!', remember: false })
  const databaseSession = await prisma.session.findFirst({ orderBy: { createdAt: 'desc' } })
  await prisma.session.update({ where: { id: databaseSession.id }, data: { idleExpiresAt: new Date(Date.now() - 1000) } })
  assert.equal((await agent.get('/api/auth/me').expect(200)).body.user, null)
  await agent.get('/api/saved/predictions').expect(401)
})

test('email verification is single-use and activates the account', async () => {
  const agent = request.agent(app)
  await register(agent, 'verify')
  const token = tokenFromLatestEmail('verification')
  const verified = await post(agent, '/api/auth/verify-email', { token })
  assert.equal(verified.body.user.emailVerified, true)
  assert.equal(verified.body.user.status, 'ACTIVE')
  await post(agent, '/api/auth/verify-email', { token }, 400)
})

test('forgot/reset password is neutral, expiring and single-use', async () => {
  const agent = request.agent(app)
  await register(agent, 'reset')
  __testEmailOutbox.clear()
  const neutral = await post(request.agent(app), '/api/auth/forgot-password', { email: 'missing@example.com' })
  assert.match(neutral.body.message, /If an account exists/)
  await post(agent, '/api/auth/forgot-password', { email: 'ninth-reset@example.com' })
  const token = tokenFromLatestEmail('password-reset')
  await post(agent, '/api/auth/reset-password', { token, password: 'New-Password-2026!', passwordConfirmation: 'New-Password-2026!' })
  await post(agent, '/api/auth/reset-password', { token, password: 'Another-Password-2026!', passwordConfirmation: 'Another-Password-2026!' }, 400)
  await post(request.agent(app), '/api/auth/login', { email: 'ninth-reset@example.com', password: 'New-Password-2026!' })
})

test('expired password reset links are rejected without changing the password', async () => {
  const agent = request.agent(app)
  await register(agent, 'expired-reset')
  __testEmailOutbox.clear()
  await post(agent, '/api/auth/forgot-password', { email: 'ninth-expired-reset@example.com' })
  const token = tokenFromLatestEmail('password-reset')
  const latest = await prisma.passwordResetToken.findFirst({ orderBy: { createdAt: 'desc' } })
  await prisma.passwordResetToken.update({ where: { id: latest.id }, data: { expiresAt: new Date(Date.now() - 1000) } })
  await post(agent, '/api/auth/reset-password', { token, password: 'Rejected-Password-2026!', passwordConfirmation: 'Rejected-Password-2026!' }, 400)
  await post(request.agent(app), '/api/auth/login', { email: 'ninth-expired-reset@example.com', password: 'Correct-Horse-99!' })
})

test('Google identity creates once and reuses the same application user', async () => {
  const req = { ip: '127.0.0.8', get: header => header === 'user-agent' ? 'NINTH test' : undefined }
  const profile = { subject: 'google-subject-1', email: 'google-user@example.com', emailVerified: true, displayName: 'Google User', avatarUrl: 'https://example.com/avatar.png' }
  const first = await completeGoogleIdentity({ profile, remember: true, req })
  const second = await completeGoogleIdentity({ profile, remember: true, req })
  assert.equal(first.user.id, second.user.id)
  assert.equal(await prisma.user.count(), 1)
  assert.equal(await prisma.authAccount.count({ where: { provider: 'GOOGLE' } }), 1)
  assert.equal(first.user.emailVerified, true)
})

test('Google authentication cannot reactivate a suspended account', async () => {
  const req = { ip: '127.0.0.9', get: header => header === 'user-agent' ? 'NINTH test' : undefined }
  const profile = { subject: 'google-suspended-1', email: 'google-suspended@example.com', emailVerified: true, displayName: 'Suspended User' }
  const created = await completeGoogleIdentity({ profile, remember: true, req })
  await prisma.user.update({ where: { id: created.user.id }, data: { status: 'SUSPENDED' } })
  await assert.rejects(() => completeGoogleIdentity({ profile, remember: true, req }), error => error.code === 'ACCOUNT_UNAVAILABLE')
})

test('every saved resource is owned server-side and inaccessible cross-user', async () => {
  const owner = request.agent(app)
  const other = request.agent(app)
  await register(owner, 'owner')
  await register(other, 'other')
  const created = await post(owner, '/api/saved/predictions', {
    sport: 'baseball', eventId: 'game-42', predictionType: 'moneyline', selection: 'Home', probability: 0.64,
    modelName: 'moneyline-v5', modelVersion: '5.2.0', generatedAt: new Date().toISOString(), metadata: { source: 'builder' },
    userId: 'attacker-controlled-id',
  }, 201)
  const item = await prisma.savedPrediction.findUnique({ where: { id: created.body.item.id } })
  const ownerUser = await prisma.user.findUnique({ where: { emailNormalized: 'ninth-owner@example.com' } })
  assert.equal(item.userId, ownerUser.id)
  await other.get(`/api/saved/predictions/${item.id}`).expect(404)
  const deleteRequest = other.delete(`/api/saved/predictions/${item.id}`).set('x-csrf-token', await csrf(other))
  await deleteRequest.expect(404)
  await owner.get(`/api/saved/predictions/${item.id}`).expect(200)

  const builder = await post(owner, '/api/saved/builders', {
    name: 'Owned sweep', sport: 'baseball', buildStyle: 'sweep', selections: [{ eventId: 'game-42', selection: 'Home' }],
    modelName: 'builder-reranker', modelVersion: '2.1.0', userId: 'attacker-controlled-id',
  }, 201)
  await other.get(`/api/saved/builders/${builder.body.item.id}`).expect(404)
  await other.delete(`/api/saved/builders/${builder.body.item.id}`).set('x-csrf-token', await csrf(other)).expect(404)
  await owner.get(`/api/saved/builders/${builder.body.item.id}`).expect(200)

  const slip = await post(owner, '/api/saved/slips', {
    externalId: 'MEL-42', provider: 'MELBET', status: 'pending', odds: 2.4,
    selections: [{ eventId: 'game-42', selection: 'Home' }], userId: 'attacker-controlled-id',
  }, 201)
  await other.get(`/api/saved/slips/${slip.body.item.id}`).expect(404)
  await other.delete(`/api/saved/slips/${slip.body.item.id}`).set('x-csrf-token', await csrf(other)).expect(404)
  await owner.get(`/api/saved/slips/${slip.body.item.id}`).expect(200)
})

test('personal slip and Alter Ego APIs never expose another user history', async () => {
  const owner = request.agent(app)
  const other = request.agent(app)
  const ownerResponse = await register(owner, 'history-owner')
  const otherResponse = await register(other, 'history-other')
  await prisma.savedSlip.createMany({ data: [
    {
      userId: ownerResponse.body.user.id, provider: 'MELBET_PDF', externalId: 'PDF-OWNER', status: 'pending',
      selections: [{ selection: 'Owner PDF selection' }], metadata: { id: 'PDF-OWNER', selections: [{ selection: 'Owner PDF selection' }] },
    },
    {
      userId: ownerResponse.body.user.id, provider: 'MELBET_HISTORY', externalId: 'HISTORY-OWNER', status: 'win',
      selections: [{ selection: 'Owner history selection' }], metadata: { slip_id: 'HISTORY-OWNER', legs: [{ selection: 'Owner history selection' }] },
    },
    {
      userId: otherResponse.body.user.id, provider: 'MELBET_HISTORY', externalId: 'HISTORY-OTHER', status: 'loss',
      selections: [{ selection: 'Other history selection' }], metadata: { slip_id: 'HISTORY-OTHER', legs: [{ selection: 'Other history selection' }] },
    },
  ] })

  const pdf = await owner.get('/api/slips').expect(200)
  assert.deepEqual(pdf.body.map(item => item.id), ['PDF-OWNER'])

  const analyse = mlbStatsProvider.analyseMelbetHistory
  mlbStatsProvider.analyseMelbetHistory = async slips => ({ slips })
  try {
    const ownerHistory = await owner.get('/api/alter-ego').expect(200)
    const otherHistory = await other.get('/api/alter-ego').expect(200)
    assert.deepEqual(ownerHistory.body.slips.map(item => item.slip_id), ['HISTORY-OWNER'])
    assert.deepEqual(otherHistory.body.slips.map(item => item.slip_id), ['HISTORY-OTHER'])
  } finally {
    mlbStatsProvider.analyseMelbetHistory = analyse
  }
})

test('authentication limiter returns 429 after repeated requests', async () => {
  process.env.DISABLE_AUTH_RATE_LIMITS = '0'
  const limiterApp = express()
  limiterApp.get('/limited', passwordResetLimiter, (_req, res) => res.json({ ok: true }))
  for (let attempt = 0; attempt < 6; attempt += 1) await request(limiterApp).get('/limited').expect(200)
  await request(limiterApp).get('/limited').expect(429)
})
