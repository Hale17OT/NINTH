import { timingSafeEqual } from 'node:crypto'

const RELEASE_OBJECT = /^releases\/[A-Za-z0-9._-]+\/(?:artifacts|data)\/[A-Za-z0-9._/-]+$/
const PRODUCTION_MANIFEST = 'production/manifest.json'

const bearerToken = request => {
  const authorization = String(request.headers.authorization || '')
  return authorization.startsWith('Bearer ') ? authorization.slice(7) : ''
}

const tokensMatch = (provided, expected) => {
  if (!provided || !expected) return false
  const left = Buffer.from(provided)
  const right = Buffer.from(expected)
  return left.length === right.length && timingSafeEqual(left, right)
}

export const isAllowedModelObject = value => {
  const objectPath = String(value || '')
  if (!objectPath || objectPath.includes('..') || objectPath.includes('\\')) return false
  return objectPath === PRODUCTION_MANIFEST || RELEASE_OBJECT.test(objectPath)
}

const encodedObjectPath = value => value.split('/').map(encodeURIComponent).join('/')

export const signModelArtifact = async (request, response) => {
  const expectedToken = process.env.NINTH_MODEL_PROXY_TOKEN || ''
  if (!tokensMatch(bearerToken(request), expectedToken)) {
    return response.status(401).json({ error: 'Model artifact access was denied.', code: 'ARTIFACT_ACCESS_DENIED' })
  }

  const objectPath = String(request.query.path || '')
  if (!isAllowedModelObject(objectPath)) {
    return response.status(400).json({ error: 'The model artifact path is invalid.', code: 'INVALID_ARTIFACT_PATH' })
  }

  const supabaseUrl = String(process.env.SUPABASE_URL || '').replace(/\/$/, '')
  const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SECRET_KEY || ''
  const bucket = process.env.NINTH_MODEL_BUCKET || 'ninth-models'
  if (!supabaseUrl || !supabaseKey) {
    return response.status(503).json({ error: 'Model artifact storage is not configured.', code: 'ARTIFACT_STORAGE_UNAVAILABLE' })
  }

  const endpoint = `${supabaseUrl}/storage/v1/object/sign/${encodeURIComponent(bucket)}/${encodedObjectPath(objectPath)}`
  const upstream = await fetch(endpoint, {
    method: 'POST',
    headers: {
      apikey: supabaseKey,
      Authorization: `Bearer ${supabaseKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ expiresIn: 600 }),
    signal: AbortSignal.timeout(20_000),
  })
  if (!upstream.ok) {
    const error = new Error(`Supabase rejected the model artifact signing request (${upstream.status}).`)
    error.code = 'ARTIFACT_SIGNING_FAILED'
    throw error
  }

  const payload = await upstream.json()
  const signedPath = payload.signedURL || payload.signedUrl
  if (!signedPath) {
    const error = new Error('Supabase did not return a signed model artifact URL.')
    error.code = 'ARTIFACT_SIGNING_FAILED'
    throw error
  }

  response.set('Cache-Control', 'no-store')
  return response.json({ url: new URL(signedPath, `${supabaseUrl}/`).toString(), expiresIn: 600 })
}

