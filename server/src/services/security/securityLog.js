import { prisma, databaseAvailable } from '../../db/prisma.js'
import { hashIp } from './crypto.js'

const safeMetadata = metadata => {
  if (!metadata || typeof metadata !== 'object') return undefined
  const blocked = /password|token|secret|authorization|cookie|code/i
  return Object.fromEntries(Object.entries(metadata).filter(([key]) => !blocked.test(key)))
}

export const recordSecurityEvent = async ({ type, userId = null, req, metadata }) => {
  if (!databaseAvailable()) return
  try {
    await prisma.securityEvent.create({ data: {
      type,
      userId,
      ipHash: hashIp(req?.ip),
      metadata: safeMetadata(metadata),
    } })
  } catch {
    console.warn(`[NINTH security] Unable to persist event type ${type}.`)
  }
}
