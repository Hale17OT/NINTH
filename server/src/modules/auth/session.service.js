import { prisma, assertDatabaseAvailable } from '../../db/prisma.js'
import { authConfig } from '../../config/auth.js'
import { hashIp, hashToken, randomToken } from '../../services/security/crypto.js'

const HOUR = 60 * 60 * 1000
const DAY = 24 * HOUR

export const sessionCookieOptions = expiresAt => ({
  httpOnly: true,
  secure: authConfig.cookieSecure,
  sameSite: authConfig.cookieSameSite,
  path: '/',
  expires: expiresAt,
})

export const clearSessionCookieOptions = () => ({
  httpOnly: true,
  secure: authConfig.cookieSecure,
  sameSite: authConfig.cookieSameSite,
  path: '/',
})

export const createSession = async ({ userId, remember = false, req, transaction = prisma }) => {
  assertDatabaseAvailable()
  const token = randomToken(32)
  const now = new Date()
  const absoluteDuration = (remember ? authConfig.sessionDays * DAY : authConfig.shortSessionHours * HOUR)
  const expiresAt = new Date(now.getTime() + absoluteDuration)
  const idleExpiresAt = new Date(Math.min(expiresAt.getTime(), now.getTime() + authConfig.sessionIdleHours * HOUR))
  const session = await transaction.session.create({ data: {
    userId,
    sessionTokenHash: hashToken(token),
    expiresAt,
    idleExpiresAt,
    userAgent: String(req?.get?.('user-agent') || '').slice(0, 500) || null,
    ipHash: hashIp(req?.ip),
  } })
  return { token, session }
}

export const resolveSession = async token => {
  if (!token || !process.env.DATABASE_URL) return null
  const now = new Date()
  const session = await prisma.session.findUnique({
    where: { sessionTokenHash: hashToken(token) },
    include: { user: { include: { authAccounts: { select: { provider: true } } } } },
  })
  if (!session) return null
  if (session.expiresAt <= now || session.idleExpiresAt <= now || ['SUSPENDED', 'DELETED'].includes(session.user.status)) {
    await prisma.session.delete({ where: { id: session.id } }).catch(() => {})
    return null
  }
  if (now.getTime() - session.lastActiveAt.getTime() > 5 * 60 * 1000) {
    const nextIdle = new Date(Math.min(session.expiresAt.getTime(), now.getTime() + authConfig.sessionIdleHours * HOUR))
    await prisma.session.update({ where: { id: session.id }, data: { lastActiveAt: now, idleExpiresAt: nextIdle } })
    session.lastActiveAt = now
    session.idleExpiresAt = nextIdle
  }
  return session
}

export const revokeSessionToken = token => token
  ? prisma.session.deleteMany({ where: { sessionTokenHash: hashToken(token) } })
  : Promise.resolve({ count: 0 })
