import { createHash } from 'node:crypto'
import { OAuth2Client } from 'google-auth-library'
import { authConfig, safeReturnTo } from '../../config/auth.js'
import { prisma, assertDatabaseAvailable } from '../../db/prisma.js'
import { AppError } from '../../modules/auth/auth.errors.js'
import { completeGoogleIdentity } from '../../modules/auth/auth.service.js'
import { hashToken, randomToken } from '../security/crypto.js'

const configured = () => Boolean(authConfig.googleClientId && authConfig.googleClientSecret && authConfig.googleRedirectUri)
const client = () => new OAuth2Client(authConfig.googleClientId, authConfig.googleClientSecret, authConfig.googleRedirectUri)

export const googleAuthService = {
  configured,

  async authorizationUrl({ returnTo, remember = true }) {
    assertDatabaseAvailable()
    if (!configured()) throw new AppError('Google Sign-In is not configured yet.', 503, 'GOOGLE_NOT_CONFIGURED')
    const state = randomToken(32)
    const codeVerifier = randomToken(64)
    const codeChallenge = createHash('sha256').update(codeVerifier).digest('base64url')
    await prisma.oAuthState.deleteMany({ where: { expiresAt: { lt: new Date() } } })
    await prisma.oAuthState.create({ data: {
      stateHash: hashToken(state),
      codeVerifier,
      returnTo: safeReturnTo(returnTo),
      remember: Boolean(remember),
      expiresAt: new Date(Date.now() + 10 * 60 * 1000),
    } })
    return client().generateAuthUrl({
      access_type: 'online',
      scope: ['openid', 'email', 'profile'],
      state,
      code_challenge: codeChallenge,
      code_challenge_method: 'S256',
      include_granted_scopes: true,
      prompt: 'select_account',
    })
  },

  async callback({ code, state, req }) {
    assertDatabaseAvailable()
    if (!configured()) throw new AppError('Google Sign-In is not configured yet.', 503, 'GOOGLE_NOT_CONFIGURED')
    if (!code || !state) throw new AppError('Google Sign-In did not complete.', 400, 'GOOGLE_CALLBACK_INVALID')
    const stateRecord = await prisma.oAuthState.findUnique({ where: { stateHash: hashToken(state) } })
    if (!stateRecord || stateRecord.expiresAt <= new Date()) throw new AppError('Google Sign-In expired. Start again.', 400, 'GOOGLE_STATE_INVALID')
    await prisma.oAuthState.delete({ where: { id: stateRecord.id } })
    const oauth = client()
    const { tokens } = await oauth.getToken({ code, codeVerifier: stateRecord.codeVerifier, redirect_uri: authConfig.googleRedirectUri })
    if (!tokens.id_token) throw new AppError('Google did not return an identity token.', 400, 'GOOGLE_IDENTITY_MISSING')
    const ticket = await oauth.verifyIdToken({ idToken: tokens.id_token, audience: authConfig.googleClientId })
    const payload = ticket.getPayload()
    const result = await completeGoogleIdentity({
      profile: {
        subject: payload?.sub,
        email: payload?.email,
        emailVerified: payload?.email_verified === true,
        displayName: payload?.name,
        avatarUrl: payload?.picture,
      },
      remember: stateRecord.remember,
      req,
    })
    return { ...result, returnTo: stateRecord.returnTo }
  },
}
