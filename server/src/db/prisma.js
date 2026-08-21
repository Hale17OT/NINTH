import { PrismaClient } from '@prisma/client'

const globalPrisma = globalThis

export const prisma = globalPrisma.__ninthPrisma || new PrismaClient({
  log: process.env.NODE_ENV === 'development' && process.env.PRISMA_QUERY_LOG === '1' ? ['warn', 'error'] : ['error'],
})

if (process.env.NODE_ENV !== 'production') globalPrisma.__ninthPrisma = prisma

export const databaseAvailable = () => Boolean(process.env.DATABASE_URL)

export const assertDatabaseAvailable = () => {
  if (!databaseAvailable()) {
    const error = new Error('Account services are not configured on this server.')
    error.status = 503
    error.publicMessage = error.message
    throw error
  }
}
