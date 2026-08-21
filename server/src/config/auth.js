const production = process.env.NODE_ENV === 'production'

const commaList = value => String(value || '').split(',').map(item => item.trim()).filter(Boolean)
const positiveNumber = (value, fallback) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

export const authConfig = {
  production,
  databaseUrl: process.env.DATABASE_URL || '',
  frontendUrl: process.env.FRONTEND_URL || (production ? '' : 'http://localhost:5173'),
  backendUrl: process.env.BACKEND_URL || (production ? '' : 'http://localhost:3001'),
  appUrl: process.env.APP_URL || process.env.FRONTEND_URL || (production ? '' : 'http://localhost:5173'),
  trustedOrigins: commaList(process.env.TRUSTED_FRONTEND_ORIGINS || process.env.FRONTEND_URL || (production ? '' : 'http://localhost:5173,http://127.0.0.1:5173')),
  sessionSecret: process.env.SESSION_SECRET || (production ? '' : 'ninth-development-only-session-secret'),
  sessionCookieName: production ? '__Host-ninth-session' : 'ninth_session',
  csrfCookieName: production ? '__Host-ninth-csrf' : 'ninth_csrf',
  cookieSecure: production || process.env.AUTH_COOKIE_SECURE === 'true',
  cookieSameSite: process.env.AUTH_COOKIE_SAME_SITE || 'lax',
  sessionDays: positiveNumber(process.env.SESSION_ABSOLUTE_DAYS, 30),
  sessionIdleHours: positiveNumber(process.env.SESSION_IDLE_HOURS, 24 * 7),
  shortSessionHours: positiveNumber(process.env.SESSION_SHORT_HOURS, 24),
  googleClientId: process.env.GOOGLE_CLIENT_ID || '',
  googleClientSecret: process.env.GOOGLE_CLIENT_SECRET || '',
  googleRedirectUri: process.env.GOOGLE_REDIRECT_URI || (production ? '' : 'http://localhost:3001/api/auth/google/callback'),
}

export const assertProductionAuthConfig = () => {
  if (!production) return
  const required = {
    DATABASE_URL: authConfig.databaseUrl,
    FRONTEND_URL: authConfig.frontendUrl,
    BACKEND_URL: authConfig.backendUrl,
    SESSION_SECRET: authConfig.sessionSecret,
    TRUSTED_FRONTEND_ORIGINS: authConfig.trustedOrigins.length,
    GOOGLE_CLIENT_ID: authConfig.googleClientId,
    GOOGLE_CLIENT_SECRET: authConfig.googleClientSecret,
    GOOGLE_REDIRECT_URI: authConfig.googleRedirectUri,
    SMTP_HOST: process.env.SMTP_HOST,
    SMTP_USER: process.env.SMTP_USER,
    SMTP_PASSWORD: process.env.SMTP_PASSWORD,
    SMTP_FROM: process.env.SMTP_FROM,
  }
  const missing = Object.entries(required).filter(([, value]) => !value).map(([key]) => key)
  if (missing.length) throw new Error(`Production authentication configuration is incomplete: ${missing.join(', ')}`)
  if (authConfig.sessionSecret.length < 32) throw new Error('SESSION_SECRET must contain at least 32 characters in production.')
  for (const value of [authConfig.frontendUrl, authConfig.backendUrl]) {
    if (!value.startsWith('https://')) throw new Error('Production frontend and backend URLs must use HTTPS.')
  }
  for (const value of authConfig.trustedOrigins) {
    if (!value.startsWith('https://')) throw new Error('Production trusted frontend origins must use HTTPS.')
  }
  const googleRedirect = new URL(authConfig.googleRedirectUri)
  if (googleRedirect.protocol !== 'https:' || googleRedirect.origin !== new URL(authConfig.backendUrl).origin) {
    throw new Error('The production Google redirect URI must use the configured HTTPS backend origin.')
  }
  if (!['lax', 'strict', 'none'].includes(String(authConfig.cookieSameSite).toLowerCase())) {
    throw new Error('AUTH_COOKIE_SAME_SITE must be lax, strict, or none.')
  }
}

export const isSafeReturnTo = value => {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return false
  try {
    const parsed = new URL(value, 'https://ninth.local')
    return parsed.origin === 'https://ninth.local' && !parsed.username && !parsed.password
  } catch {
    return false
  }
}

export const safeReturnTo = value => isSafeReturnTo(value) ? value : '/'

export const publicUser = user => user ? ({
  id: user.id,
  displayName: user.displayName,
  email: user.email,
  avatarUrl: user.avatarUrl,
  role: user.role,
  plan: user.plan,
  status: user.status,
  emailVerified: Boolean(user.emailVerifiedAt),
  createdAt: user.createdAt,
  providers: Array.isArray(user.authAccounts) ? user.authAccounts.map(account => account.provider) : undefined,
}) : null
