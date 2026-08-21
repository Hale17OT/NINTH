import { Router } from 'express'
import { optionalAuth, requireAuth } from '../../middleware/authenticate.js'
import { requireCsrf } from '../../middleware/csrf.js'
import { loginLimiter, passwordResetLimiter, registrationLimiter, verificationLimiter } from '../../middleware/rateLimit.js'
import { validate } from '../../middleware/validate.js'
import { authController as c } from './auth.controller.js'
import { forgotPasswordSchema, loginSchema, registerSchema, resetPasswordSchema, verifyEmailSchema } from './auth.validation.js'

const router = Router()
const wrap = fn => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next)

router.get('/csrf', c.csrf)
router.get('/config', c.config)
router.get('/me', optionalAuth, c.me)
router.get('/google', wrap(c.googleStart))
router.get('/google/callback', wrap(c.googleCallback))
router.post('/register', registrationLimiter, requireCsrf, validate(registerSchema), wrap(c.register))
router.post('/login', loginLimiter, requireCsrf, validate(loginSchema), wrap(c.login))
router.post('/logout', requireCsrf, ...requireAuth, wrap(c.logout))
router.post('/forgot-password', passwordResetLimiter, requireCsrf, validate(forgotPasswordSchema), wrap(c.forgotPassword))
router.post('/reset-password', passwordResetLimiter, requireCsrf, validate(resetPasswordSchema), wrap(c.resetPassword))
router.post('/verify-email', verificationLimiter, requireCsrf, validate(verifyEmailSchema), wrap(c.verifyEmail))
router.post('/resend-verification', verificationLimiter, requireCsrf, ...requireAuth, wrap(c.resendVerification))

export default router
