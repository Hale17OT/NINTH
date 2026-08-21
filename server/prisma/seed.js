import 'dotenv/config'
import { PrismaClient } from '@prisma/client'
import argon2 from 'argon2'

if (process.env.NODE_ENV === 'production') throw new Error('Development seed is disabled in production.')

const email = String(process.env.DEV_SEED_EMAIL || '').trim()
const password = String(process.env.DEV_SEED_PASSWORD || '')
const displayName = String(process.env.DEV_SEED_DISPLAY_NAME || 'NINTH Developer').trim()
if (!email || !password) throw new Error('Set DEV_SEED_EMAIL and DEV_SEED_PASSWORD in the ignored .env file before seeding.')
if (password.length < 12) throw new Error('DEV_SEED_PASSWORD must be at least 12 characters.')

const prisma = new PrismaClient()
try {
  const emailNormalized = email.toLowerCase()
  const passwordHash = await argon2.hash(password, { type: argon2.argon2id, memoryCost: 19456, timeCost: 2, parallelism: 1 })
  const user = await prisma.user.upsert({
    where: { emailNormalized },
    update: { displayName, status: 'ACTIVE', emailVerifiedAt: new Date() },
    create: {
      email, emailNormalized, displayName, status: 'ACTIVE', emailVerifiedAt: new Date(),
      preferences: { create: { preferredSport: 'baseball', oddsFormat: 'DECIMAL', timezone: 'Africa/Addis_Ababa', notificationPreferences: {} } },
    },
  })
  await prisma.authAccount.upsert({
    where: { provider_providerAccountId: { provider: 'PASSWORD', providerAccountId: emailNormalized } },
    update: { passwordHash },
    create: { userId: user.id, provider: 'PASSWORD', providerAccountId: emailNormalized, passwordHash },
  })
  await prisma.userPreference.upsert({
    where: { userId: user.id },
    update: { preferredSport: 'baseball', oddsFormat: 'DECIMAL', timezone: 'Africa/Addis_Ababa' },
    create: { userId: user.id, preferredSport: 'baseball', oddsFormat: 'DECIMAL', timezone: 'Africa/Addis_Ababa', notificationPreferences: {} },
  })
  if (!await prisma.savedPrediction.count({ where: { userId: user.id } })) {
    await prisma.savedPrediction.create({ data: {
      userId: user.id, sport: 'baseball', league: 'MLB', eventId: 'seed-example', predictionType: 'moneyline',
      selection: 'Example saved selection', probability: 0.6, modelName: 'development-seed', modelVersion: 'seed-1',
      generatedAt: new Date(), metadata: { example: true },
    } })
  }
  process.stdout.write(`Seeded development account ${email}.\n`)
} finally {
  await prisma.$disconnect()
}
