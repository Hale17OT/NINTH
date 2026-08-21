import { AppError } from '../modules/auth/auth.errors.js'

export const validate = (schema, source = 'body') => (req, _res, next) => {
  const result = schema.safeParse(req[source])
  if (!result.success) {
    const fields = {}
    for (const issue of result.error.issues) {
      const key = issue.path.join('.') || 'form'
      if (!fields[key]) fields[key] = issue.message
    }
    const error = new AppError('Check the highlighted fields and try again.', 422, 'VALIDATION_FAILED')
    error.fields = fields
    return next(error)
  }
  req.validated = result.data
  next()
}
