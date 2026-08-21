import { rateLimit } from 'express-rate-limit'

const createLimiter = (windowMs, limit, message) => rateLimit({
  windowMs,
  limit,
  standardHeaders: 'draft-8',
  legacyHeaders: false,
  message: { error: message, code: 'RATE_LIMITED' },
  skip: () => process.env.NODE_ENV === 'test' && process.env.DISABLE_AUTH_RATE_LIMITS === '1',
})

export const loginLimiter = createLimiter(15 * 60 * 1000, 10, 'Too many sign-in attempts. Wait a few minutes and try again.')
export const registrationLimiter = createLimiter(60 * 60 * 1000, 8, 'Too many account creation attempts. Try again later.')
export const passwordResetLimiter = createLimiter(60 * 60 * 1000, 6, 'Too many reset requests. Try again later.')
export const verificationLimiter = createLimiter(60 * 60 * 1000, 6, 'Too many verification requests. Try again later.')
