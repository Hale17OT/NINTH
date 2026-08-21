import { authConfig, publicUser, safeReturnTo } from '../../config/auth.js'
import { prisma } from '../../db/prisma.js'
import { issueCsrf } from '../../middleware/csrf.js'
import { emailService } from '../../services/email/emailService.js'
import { googleAuthService } from '../../services/google/googleAuthService.js'
import { recordSecurityEvent } from '../../services/security/securityLog.js'
import { authService } from './auth.service.js'
import { clearSessionCookieOptions, revokeSessionToken, sessionCookieOptions } from './session.service.js'

const setSession = (res, result) => {
  res.cookie(authConfig.sessionCookieName, result.token, sessionCookieOptions(result.session.expiresAt))
  return result.user
}

const frontendCallback = (status, returnTo = '/', reason) => {
  const target = new URL('/auth/callback', authConfig.frontendUrl)
  target.searchParams.set('status', status)
  target.searchParams.set('returnTo', safeReturnTo(returnTo))
  if (reason) target.searchParams.set('reason', reason)
  return target.toString()
}

export const authController = {
  csrf: issueCsrf,
  config: (_req, res) => res.json({ googleConfigured: googleAuthService.configured(), emailConfigured: emailService.configured() }),
  me: (req, res) => {
    res.set('Cache-Control', 'no-store')
    res.json({ user: req.auth ? publicUser(req.auth.user) : null })
  },
  register: async (req, res) => {
    const result = await authService.register(req.validated, req)
    res.status(201).json({ user: setSession(res, result), verificationSent: result.verificationSent })
  },
  login: async (req, res) => {
    const result = await authService.login(req.validated, req)
    res.json({ user: setSession(res, result) })
  },
  logout: async (req, res) => {
    const token = req.cookies?.[authConfig.sessionCookieName]
    await revokeSessionToken(token)
    await recordSecurityEvent({ type: 'SESSION_REVOKED', userId: req.auth?.user?.id, req })
    res.clearCookie(authConfig.sessionCookieName, clearSessionCookieOptions())
    res.status(204).end()
  },
  forgotPassword: async (req, res) => res.json(await authService.requestPasswordReset(req.validated.email, req)),
  resetPassword: async (req, res) => res.json(await authService.resetPassword(req.validated, req)),
  verifyEmail: async (req, res) => res.json(await authService.verifyEmail(req.validated.token, req)),
  resendVerification: async (req, res) => res.json(await authService.resendVerification(req.auth.user.id, req)),
  googleStart: async (req, res) => {
    const url = await googleAuthService.authorizationUrl({ returnTo: req.query.returnTo, remember: req.query.remember !== '0' })
    if (req.query.format === 'json') return res.json({ url })
    res.redirect(url)
  },
  googleCallback: async (req, res) => {
    try {
      if (req.query.error) return res.redirect(frontendCallback('error', '/', 'cancelled'))
      const result = await googleAuthService.callback({ code: req.query.code, state: req.query.state, req })
      setSession(res, result)
      return res.redirect(frontendCallback('success', result.returnTo))
    } catch (error) {
      console.warn(`[NINTH auth] Google callback failed with ${error.code || 'GOOGLE_CALLBACK_FAILED'}.`)
      return res.redirect(frontendCallback('error', '/', 'google'))
    }
  },
  cleanupExpired: async () => prisma.$transaction([
    prisma.session.deleteMany({ where: { OR: [{ expiresAt: { lt: new Date() } }, { idleExpiresAt: { lt: new Date() } }] } }),
    prisma.oAuthState.deleteMany({ where: { expiresAt: { lt: new Date() } } }),
    prisma.emailVerificationToken.deleteMany({ where: { expiresAt: { lt: new Date(Date.now() - 24 * 60 * 60 * 1000) } } }),
    prisma.passwordResetToken.deleteMany({ where: { expiresAt: { lt: new Date(Date.now() - 24 * 60 * 60 * 1000) } } }),
  ]),
}
