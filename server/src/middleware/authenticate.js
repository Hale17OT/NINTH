import { authConfig } from '../config/auth.js'
import { AppError } from '../modules/auth/auth.errors.js'
import { resolveSession } from '../modules/auth/session.service.js'

export const optionalAuth = async (req, _res, next) => {
  try {
    const token = req.cookies?.[authConfig.sessionCookieName]
    const session = await resolveSession(token)
    req.auth = session ? { user: session.user, session } : null
    next()
  } catch (error) {
    next(error)
  }
}

export const requireAuth = [optionalAuth, (req, _res, next) => {
  if (!req.auth) return next(new AppError('Sign in to continue.', 401, 'AUTH_REQUIRED'))
  next()
}]

export const requireRole = role => [...requireAuth, (req, _res, next) => {
  if (req.auth.user.role !== role) return next(new AppError('You do not have access to this feature.', 403, 'FORBIDDEN'))
  next()
}]
