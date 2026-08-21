import { prisma, assertDatabaseAvailable } from '../../db/prisma.js'
import { AppError } from '../auth/auth.errors.js'

const types = {
  predictions: { delegate: 'savedPrediction', order: { createdAt: 'desc' } },
  builders: { delegate: 'savedBuilder', order: { createdAt: 'desc' } },
  slips: { delegate: 'savedSlip', order: { createdAt: 'desc' } },
}
const descriptor = type => {
  const value = types[type]
  if (!value) throw new AppError('Saved resource type not found.', 404, 'RESOURCE_NOT_FOUND')
  return value
}

export const savedService = {
  async list(type, userId) {
    assertDatabaseAvailable()
    const { delegate, order } = descriptor(type)
    const items = await prisma[delegate].findMany({ where: { userId }, orderBy: order, take: 200 })
    return { items }
  },
  async get(type, userId, id) {
    const { delegate } = descriptor(type)
    const item = await prisma[delegate].findFirst({ where: { id, userId } })
    if (!item) throw new AppError('Saved item not found.', 404, 'RESOURCE_NOT_FOUND')
    return { item }
  },
  async create(type, userId, payload) {
    const { delegate } = descriptor(type)
    try {
      const item = await prisma[delegate].create({ data: { ...payload, userId } })
      return { item }
    } catch (error) {
      if (error?.code === 'P2002' && type === 'slips') {
        const item = await prisma.savedSlip.findFirst({ where: { userId, provider: payload.provider, externalId: payload.externalId } })
        return { item, duplicate: true }
      }
      throw error
    }
  },
  async remove(type, userId, id) {
    const { delegate } = descriptor(type)
    const result = await prisma[delegate].deleteMany({ where: { id, userId } })
    if (!result.count) throw new AppError('Saved item not found.', 404, 'RESOURCE_NOT_FOUND')
    return { deleted: true }
  },
}
