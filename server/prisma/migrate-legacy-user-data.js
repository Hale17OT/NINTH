import 'dotenv/config'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { PrismaClient } from '@prisma/client'

const ownerEmail = String(process.env.LEGACY_OWNER_EMAIL || '').trim().toLowerCase()
if (!ownerEmail) throw new Error('Set LEGACY_OWNER_EMAIL to the registered account that owns the existing local slip history.')

const prisma = new PrismaClient()
const load = async path => JSON.parse(await readFile(resolve(path), 'utf8'))
const dateOrNull = value => {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

try {
  const user = await prisma.user.findUnique({ where: { emailNormalized: ownerEmail } })
  if (!user) throw new Error('The LEGACY_OWNER_EMAIL account does not exist. Register it first, then rerun this command.')

  const pdfSlips = await load('ml/data/slips.json').catch(() => [])
  const melbetDocument = await load('ml/data/melbet_bet_history.json').catch(() => ({ slips: [] }))
  let migrated = 0
  for (const slip of Array.isArray(pdfSlips) ? pdfSlips : []) {
    if (!slip?.id || !Array.isArray(slip.selections)) continue
    await prisma.savedSlip.upsert({
      where: { userId_provider_externalId: { userId: user.id, provider: 'MELBET_PDF', externalId: String(slip.id) } },
      update: { metadata: slip, selections: slip.selections, status: slip.active ? 'active' : 'pending' },
      create: {
        userId: user.id, provider: 'MELBET_PDF', externalId: String(slip.id), status: slip.active ? 'active' : 'pending',
        placedAt: dateOrNull(slip.placed_at_iso), odds: slip.overall_odds, stake: slip.stake,
        payout: slip.potential_winnings, selections: slip.selections, metadata: slip,
      },
    })
    migrated += 1
  }
  for (const slip of Array.isArray(melbetDocument?.slips) ? melbetDocument.slips : []) {
    if (!slip?.slip_id || !Array.isArray(slip.legs)) continue
    await prisma.savedSlip.upsert({
      where: { userId_provider_externalId: { userId: user.id, provider: 'MELBET_HISTORY', externalId: String(slip.slip_id) } },
      update: { metadata: slip, selections: slip.legs, status: slip.status },
      create: {
        userId: user.id, provider: 'MELBET_HISTORY', externalId: String(slip.slip_id), status: slip.status,
        placedAt: dateOrNull(slip.placed_at), odds: slip.total_odds, stake: slip.stake,
        payout: slip.potential_winnings, selections: slip.legs, metadata: slip,
      },
    })
    migrated += 1
  }
  process.stdout.write(`Migrated or refreshed ${migrated} legacy slip records for the selected owner. Source files were not changed.\n`)
} finally {
  await prisma.$disconnect()
}
