process.env.DATABASE_URL ||= process.env.POSTGRES_PRISMA_URL || process.env.POSTGRES_URL || ''

const { default: app } = await import('../server/src/app.js')
const { assertProductionAuthConfig } = await import('../server/src/config/auth.js')

assertProductionAuthConfig()

export default app
