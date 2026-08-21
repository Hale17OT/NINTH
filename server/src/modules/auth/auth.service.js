import argon2 from 'argon2'
import { prisma, assertDatabaseAvailable } from '../../db/prisma.js'
import { publicUser } from '../../config/auth.js'
import { emailService } from '../../services/email/emailService.js'
import { hashToken, randomToken } from '../../services/security/crypto.js'
import { recordSecurityEvent } from '../../services/security/securityLog.js'
import { AppError } from './auth.errors.js'
import { createSession } from './session.service.js'

const VERIFICATION_TTL = 24 * 60 * 60 * 1000
const RESET_TTL = 60 * 60 * 1000
const passwordOptions = { type: argon2.argon2id, memoryCost: 19456, timeCost: 2, parallelism: 1 }
export const normalizeEmail = value => String(value || '').trim().normalize('NFKC').toLowerCase()
export const hashPassword = password => argon2.hash(password, passwordOptions)

const userInclude = { authAccounts: { select: { provider: true } } }

const createVerificationToken = async (userId, transaction = prisma) => {
  const token = randomToken(32)
  await transaction.emailVerificationToken.deleteMany({ where: { userId, usedAt: null } })
  await transaction.emailVerificationToken.create({ data: {
    userId,
    tokenHash: hashToken(token),
    expiresAt: new Date(Date.now() + VERIFICATION_TTL),
  } })
  return token
}

export const authService = {
  async register(payload, req) {
    assertDatabaseAvailable()
    const emailNormalized = normalizeEmail(payload.email)
    const duplicate = await prisma.user.findUnique({ where: { emailNormalized }, select: { id: true } })
    if (duplicate) throw new AppError('An account already exists for this email. Sign in instead.', 409, 'EMAIL_REGISTERED')
    const passwordHash = await hashPassword(payload.password)
    const verificationToken = randomToken(32)
    let user
    try {
      user = await prisma.$transaction(async tx => {
        const created = await tx.user.create({ data: {
          email: payload.email.trim(),
          emailNormalized,
          displayName: payload.displayName.trim(),
          authAccounts: { create: { provider: 'PASSWORD', providerAccountId: emailNormalized, passwordHash } },
          preferences: { create: { timezone: 'UTC', notificationPreferences: {} } },
          verificationTokens: { create: { tokenHash: hashToken(verificationToken), expiresAt: new Date(Date.now() + VERIFICATION_TTL) } },
        }, include: userInclude })
        return created
      })
    } catch (error) {
      if (error?.code === 'P2002') throw new AppError('An account already exists for this email. Sign in instead.', 409, 'EMAIL_REGISTERED')
      throw error
    }
    const { token, session } = await createSession({ userId: user.id, remember: payload.remember, req })
    let verificationSent = false
    try {
      verificationSent = (await emailService.sendVerificationEmail({ to: user.email, displayName: user.displayName, token: verificationToken })).delivered
    } catch {
      verificationSent = false
    }
    await recordSecurityEvent({ type: 'ACCOUNT_REGISTERED', userId: user.id, req })
    return { user: publicUser(user), token, session, verificationSent }
  },

  async login(payload, req) {
    assertDatabaseAvailable()
    const emailNormalized = normalizeEmail(payload.email)
    const account = await prisma.authAccount.findUnique({
      where: { provider_providerAccountId: { provider: 'PASSWORD', providerAccountId: emailNormalized } },
      include: { user: { include: userInclude } },
    })
    const valid = account?.passwordHash ? await argon2.verify(account.passwordHash, payload.password).catch(() => false) : false
    if (!valid || !account?.user || ['SUSPENDED', 'DELETED'].includes(account.user.status)) {
      await recordSecurityEvent({ type: 'LOGIN_FAILED', userId: account?.userId, req })
      throw new AppError('Invalid email or password.', 401, 'INVALID_CREDENTIALS')
    }
    const { token, session } = await createSession({ userId: account.userId, remember: payload.remember, req })
    const user = await prisma.user.update({ where: { id: account.userId }, data: { lastLoginAt: new Date() }, include: userInclude })
    await recordSecurityEvent({ type: 'LOGIN_SUCCEEDED', userId: user.id, req, metadata: { provider: 'PASSWORD' } })
    return { user: publicUser(user), token, session }
  },

  async requestPasswordReset(emailValue, req) {
    assertDatabaseAvailable()
    const emailNormalized = normalizeEmail(emailValue)
    const account = await prisma.authAccount.findUnique({
      where: { provider_providerAccountId: { provider: 'PASSWORD', providerAccountId: emailNormalized } },
      include: { user: true },
    })
    if (account?.user && !['SUSPENDED', 'DELETED'].includes(account.user.status)) {
      const token = randomToken(32)
      await prisma.$transaction([
        prisma.passwordResetToken.deleteMany({ where: { userId: account.userId, usedAt: null } }),
        prisma.passwordResetToken.create({ data: { userId: account.userId, tokenHash: hashToken(token), expiresAt: new Date(Date.now() + RESET_TTL) } }),
      ])
      await emailService.sendPasswordResetEmail({ to: account.user.email, displayName: account.user.displayName, token }).catch(() => null)
      await recordSecurityEvent({ type: 'PASSWORD_RESET_REQUESTED', userId: account.userId, req })
    } else {
      await recordSecurityEvent({ type: 'PASSWORD_RESET_REQUESTED', req })
    }
    return { message: "If an account exists for this email, we've sent password reset instructions." }
  },

  async resetPassword(payload, req) {
    assertDatabaseAvailable()
    const record = await prisma.passwordResetToken.findUnique({ where: { tokenHash: hashToken(payload.token) }, include: { user: true } })
    if (!record || record.usedAt || record.expiresAt <= new Date()) throw new AppError('This password reset link is invalid or has expired.', 400, 'RESET_LINK_INVALID')
    const passwordHash = await hashPassword(payload.password)
    await prisma.$transaction(async tx => {
      const updated = await tx.authAccount.updateMany({ where: { userId: record.userId, provider: 'PASSWORD' }, data: { passwordHash } })
      if (!updated.count) throw new AppError('This account does not use password sign-in.', 400, 'PASSWORD_NOT_AVAILABLE')
      await tx.passwordResetToken.update({ where: { id: record.id }, data: { usedAt: new Date() } })
      await tx.passwordResetToken.deleteMany({ where: { userId: record.userId, id: { not: record.id } } })
      await tx.session.deleteMany({ where: { userId: record.userId } })
    })
    await recordSecurityEvent({ type: 'PASSWORD_CHANGED', userId: record.userId, req, metadata: { method: 'reset' } })
    await emailService.sendSecurityNotification({ to: record.user.email, displayName: record.user.displayName, subject: 'Your NINTH password changed', copy: 'Your password was reset and existing sessions were signed out.' }).catch(() => null)
    return { message: 'Your password has been reset. Sign in with the new password.' }
  },

  async verifyEmail(token, req) {
    assertDatabaseAvailable()
    const record = await prisma.emailVerificationToken.findUnique({ where: { tokenHash: hashToken(token) }, include: { user: true } })
    if (!record || record.usedAt || record.expiresAt <= new Date()) throw new AppError('This verification link is invalid or has expired.', 400, 'VERIFICATION_LINK_INVALID')
    const user = await prisma.$transaction(async tx => {
      await tx.emailVerificationToken.update({ where: { id: record.id }, data: { usedAt: new Date() } })
      return tx.user.update({ where: { id: record.userId }, data: { emailVerifiedAt: new Date(), status: 'ACTIVE' }, include: userInclude })
    })
    await recordSecurityEvent({ type: 'EMAIL_VERIFIED', userId: user.id, req })
    return { user: publicUser(user), message: 'Your email is verified.' }
  },

  async resendVerification(userId, req) {
    assertDatabaseAvailable()
    const user = await prisma.user.findUnique({ where: { id: userId } })
    if (!user || user.emailVerifiedAt) return { message: 'Your email is already verified.' }
    const token = await createVerificationToken(userId)
    await emailService.sendVerificationEmail({ to: user.email, displayName: user.displayName, token }).catch(() => null)
    await recordSecurityEvent({ type: 'VERIFICATION_RESENT', userId, req })
    return { message: 'A new verification email has been sent.' }
  },

  async changePassword(userId, payload, req) {
    assertDatabaseAvailable()
    const account = await prisma.authAccount.findUnique({ where: { provider_providerAccountId: { provider: 'PASSWORD', providerAccountId: req.auth.user.emailNormalized } } })
    const valid = account?.passwordHash ? await argon2.verify(account.passwordHash, payload.currentPassword).catch(() => false) : false
    if (!valid) throw new AppError('Your current password is incorrect.', 401, 'INVALID_CURRENT_PASSWORD')
    await prisma.$transaction([
      prisma.authAccount.update({ where: { id: account.id }, data: { passwordHash: await hashPassword(payload.password) } }),
      prisma.session.deleteMany({ where: { userId, id: { not: req.auth.session.id } } }),
    ])
    await recordSecurityEvent({ type: 'PASSWORD_CHANGED', userId, req, metadata: { method: 'account' } })
    return { message: 'Password updated. Other sessions were signed out.' }
  },
}

export const completeGoogleIdentity = async ({ profile, remember, req }) => {
  assertDatabaseAvailable()
  if (!profile.subject || !profile.email || !profile.emailVerified) throw new AppError('Google did not provide a verified identity and email address.', 400, 'GOOGLE_EMAIL_REQUIRED')
  const emailNormalized = normalizeEmail(profile.email)
  const existingIdentity = await prisma.authAccount.findUnique({
    where: { provider_providerAccountId: { provider: 'GOOGLE', providerAccountId: profile.subject } },
    include: { user: { include: userInclude } },
  })
  if (existingIdentity) {
    if (!existingIdentity.user || ['SUSPENDED', 'DELETED'].includes(existingIdentity.user.status)) {
      await recordSecurityEvent({ type: 'LOGIN_FAILED', userId: existingIdentity.userId, req, metadata: { provider: 'GOOGLE' } })
      throw new AppError('This account is not available.', 403, 'ACCOUNT_UNAVAILABLE')
    }
    const { token, session } = await createSession({ userId: existingIdentity.userId, remember, req })
    const user = await prisma.user.update({ where: { id: existingIdentity.userId }, data: { lastLoginAt: new Date(), avatarUrl: profile.avatarUrl || existingIdentity.user.avatarUrl }, include: userInclude })
    await recordSecurityEvent({ type: 'LOGIN_SUCCEEDED', userId: user.id, req, metadata: { provider: 'GOOGLE' } })
    return { user: publicUser(user), token, session }
  }

  const result = await prisma.$transaction(async tx => {
    let user = await tx.user.findUnique({ where: { emailNormalized }, include: userInclude })
    if (user && ['SUSPENDED', 'DELETED'].includes(user.status)) throw new AppError('This account is not available.', 403, 'ACCOUNT_UNAVAILABLE')
    if (!user) {
      user = await tx.user.create({ data: {
        email: profile.email,
        emailNormalized,
        displayName: profile.displayName || profile.email.split('@')[0],
        avatarUrl: profile.avatarUrl || null,
        emailVerifiedAt: new Date(),
        status: 'ACTIVE',
        preferences: { create: { timezone: 'UTC', notificationPreferences: {} } },
      }, include: userInclude })
    } else {
      user = await tx.user.update({ where: { id: user.id }, data: {
        emailVerifiedAt: user.emailVerifiedAt || new Date(),
        status: 'ACTIVE',
        avatarUrl: user.avatarUrl || profile.avatarUrl || null,
      }, include: userInclude })
    }
    await tx.authAccount.create({ data: { userId: user.id, provider: 'GOOGLE', providerAccountId: profile.subject } })
    return user
  })
  const { token, session } = await createSession({ userId: result.id, remember, req })
  const user = await prisma.user.update({ where: { id: result.id }, data: { lastLoginAt: new Date() }, include: userInclude })
  await recordSecurityEvent({ type: 'GOOGLE_ACCOUNT_LINKED', userId: user.id, req })
  return { user: publicUser(user), token, session }
}
