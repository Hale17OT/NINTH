import { prisma, assertDatabaseAvailable } from '../../db/prisma.js'
import { publicUser } from '../../config/auth.js'
import { AppError } from '../auth/auth.errors.js'

const accountInclude = { authAccounts: { select: { provider: true, createdAt: true } }, preferences: true }

export const userService = {
  async account(userId) {
    assertDatabaseAvailable()
    const user = await prisma.user.findUnique({ where: { id: userId }, include: accountInclude })
    if (!user) throw new AppError('Account not found.', 404, 'ACCOUNT_NOT_FOUND')
    return {
      user: publicUser(user),
      authenticationMethods: user.authAccounts.map(account => ({ provider: account.provider, connectedAt: account.createdAt })),
      preferences: user.preferences,
    }
  },

  async updateProfile(userId, payload) {
    const user = await prisma.user.update({ where: { id: userId }, data: { displayName: payload.displayName.trim() }, include: { authAccounts: { select: { provider: true } } } })
    return { user: publicUser(user) }
  },

  async updatePreferences(userId, payload) {
    const data = Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== undefined))
    const preferences = await prisma.userPreference.upsert({
      where: { userId },
      create: { userId, timezone: data.timezone || 'UTC', notificationPreferences: data.notificationPreferences || {}, ...data },
      update: data,
    })
    return { preferences }
  },

  async sessions(userId, currentSessionId) {
    const sessions = await prisma.session.findMany({ where: { userId }, orderBy: { lastActiveAt: 'desc' }, select: {
      id: true, createdAt: true, lastActiveAt: true, expiresAt: true, userAgent: true,
    } })
    return { sessions: sessions.map(session => ({ ...session, current: session.id === currentSessionId })) }
  },

  async revokeSession(userId, sessionId, currentSessionId) {
    const result = await prisma.session.deleteMany({ where: { id: sessionId, userId } })
    if (!result.count) throw new AppError('Session not found.', 404, 'SESSION_NOT_FOUND')
    return { revoked: true, current: sessionId === currentSessionId }
  },
}
