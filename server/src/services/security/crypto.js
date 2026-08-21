import { createHash, createHmac, randomBytes, timingSafeEqual } from 'node:crypto'
import { authConfig } from '../../config/auth.js'

export const randomToken = (bytes = 32) => randomBytes(bytes).toString('base64url')
export const hashToken = token => createHash('sha256').update(String(token)).digest('hex')
export const hashIp = ip => ip ? createHmac('sha256', authConfig.sessionSecret).update(String(ip)).digest('hex') : null
export const safeEqual = (left, right) => {
  const a = Buffer.from(String(left || ''))
  const b = Buffer.from(String(right || ''))
  return a.length === b.length && timingSafeEqual(a, b)
}
