import { Router } from 'express'
import { requireAuth } from '../../middleware/authenticate.js'
import { requireCsrf } from '../../middleware/csrf.js'
import { validate } from '../../middleware/validate.js'
import { changePasswordSchema, preferenceSchema, updateProfileSchema } from '../auth/auth.validation.js'
import { userController as c } from './user.controller.js'

const router = Router()
const wrap = fn => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next)
router.use(...requireAuth)
router.get('/account', wrap(c.account))
router.patch('/profile', requireCsrf, validate(updateProfileSchema), wrap(c.profile))
router.put('/preferences', requireCsrf, validate(preferenceSchema), wrap(c.preferences))
router.post('/change-password', requireCsrf, validate(changePasswordSchema), wrap(c.changePassword))
router.get('/sessions', wrap(c.sessions))
router.delete('/sessions/:id', requireCsrf, wrap(c.revokeSession))
export default router
