import { Router } from 'express'
import { requireAuth } from '../../middleware/authenticate.js'
import { requireCsrf } from '../../middleware/csrf.js'
import { validate } from '../../middleware/validate.js'
import { savedController as c } from './saved.controller.js'
import { savedBuilderSchema, savedPredictionSchema, savedSlipSchema } from './saved.validation.js'

const router = Router()
const wrap = fn => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next)
const schemas = { predictions: savedPredictionSchema, builders: savedBuilderSchema, slips: savedSlipSchema }
const validateType = (req, res, next) => {
  const schema = schemas[req.params.type]
  if (!schema) return res.status(404).json({ error: 'Saved resource type not found.', code: 'RESOURCE_NOT_FOUND' })
  req.resourceSchema = schema
  next()
}
const validateResource = (req, res, next) => validate(req.resourceSchema)(req, res, next)

router.use(...requireAuth)
router.get('/:type', validateType, wrap(c.list))
router.post('/:type', validateType, requireCsrf, validateResource, wrap(c.create))
router.get('/:type/:id', validateType, wrap(c.get))
router.delete('/:type/:id', validateType, requireCsrf, wrap(c.remove))
export default router
