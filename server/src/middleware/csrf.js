import { authConfig } from '../config/auth.js'
import { AppError } from '../modules/auth/auth.errors.js'
import { randomToken, safeEqual } from '../services/security/crypto.js'

const csrfCookieOptions = {
  httpOnly: false,
  secure: authConfig.cookieSecure,
  sameSite: authConfig.cookieSameSite,
  path: '/',
}

const originAllowed = req => {
  const origin = req.get('origin')
  if (!origin) return process.env.NODE_ENV === 'test'
  return authConfig.trustedOrigins.includes(origin)
}

export const issueCsrf = (req, res) => {
  const current = req.cookies?.[authConfig.csrfCookieName]
  const token = current && current.length >= 32 ? current : randomToken(32)
  res.cookie(authConfig.csrfCookieName, token, csrfCookieOptions)
  res.set('Cache-Control', 'no-store')
  res.json({ csrfToken: token })
}

export const requireCsrf = (req, _res, next) => {
  if (['GET', 'HEAD', 'OPTIONS'].includes(req.method)) return next()
  const cookie = req.cookies?.[authConfig.csrfCookieName]
  const header = req.get('x-csrf-token')
  if (!originAllowed(req) || !cookie || !header || !safeEqual(cookie, header)) {
    return next(new AppError('Your security token expired. Refresh the page and try again.', 403, 'CSRF_INVALID'))
  }
  next()
}
