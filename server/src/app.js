import express from 'express'
import cors from 'cors'
import cookieParser from 'cookie-parser'
import helmet from 'helmet'
import routes from './routes/api.js'
import authRoutes from './modules/auth/auth.routes.js'
import userRoutes from './modules/users/user.routes.js'
import savedRoutes from './modules/saved/saved.routes.js'
import { authConfig } from './config/auth.js'

const app = express()

if (authConfig.production) app.set('trust proxy', 1)

app.disable('x-powered-by')
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'"],
      styleSrc: ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com'],
      fontSrc: ["'self'", 'https://fonts.gstatic.com', 'data:'],
      imgSrc: ["'self'", 'data:', 'https:'],
      connectSrc: ["'self'"],
      frameAncestors: ["'none'"],
      baseUri: ["'self'"],
      formAction: ["'self'", 'https://accounts.google.com'],
    },
  },
  crossOriginResourcePolicy: { policy: 'cross-origin' },
  strictTransportSecurity: authConfig.production ? { maxAge: 31536000, includeSubDomains: true, preload: true } : false,
  referrerPolicy: { policy: 'strict-origin-when-cross-origin' },
}))
app.use(cors({
  origin(origin, callback) {
    if (!origin || authConfig.trustedOrigins.includes(origin)) return callback(null, true)
    const error = new Error('Origin is not allowed.')
    error.status = 403
    callback(error)
  },
  credentials: true,
  methods: ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'X-CSRF-Token'],
}))
app.use(cookieParser())
app.use(express.json({ limit: '12mb' }))

app.use('/api/auth', authRoutes)
app.use('/api/user', userRoutes)
app.use('/api/saved', savedRoutes)
app.use('/api', routes)

app.use((req, res) => res.status(404).json({ error: 'Endpoint not found.', code: 'NOT_FOUND' }))
app.use((error, req, res, _next) => {
  const oversized = error.type === 'entity.too.large'
  const status = oversized ? 413 : (Number(error.status) >= 400 && Number(error.status) < 600 ? Number(error.status) : 500)
  if (status >= 500) console.error(`[NINTH API] ${req.method} ${req.path} failed: ${error.code || error.name || 'SERVER_ERROR'}`)
  const errorMessage = oversized
    ? 'The upload is too large. Maximum request size is 12 MB.'
    : error.publicMessage || (status < 500 ? error.message : 'The service could not complete this request.')
  res.status(status).json({
    error: errorMessage,
    code: error.code || (status >= 500 ? 'SERVER_ERROR' : 'REQUEST_FAILED'),
    ...(error.fields ? { fields: error.fields } : {}),
  })
})

export default app
