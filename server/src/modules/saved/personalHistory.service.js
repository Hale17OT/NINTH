import { prisma, assertDatabaseAvailable } from '../../db/prisma.js'
import { mlbStatsProvider } from '../../services/mlbStatsProvider.js'

const PDF_PROVIDER = 'MELBET_PDF'
const HISTORY_PROVIDER = 'MELBET_HISTORY'
const dateOrNull = value => {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

const persistPdfSlip = (userId, slip) => prisma.savedSlip.upsert({
  where: { userId_provider_externalId: { userId, provider: PDF_PROVIDER, externalId: String(slip.id) } },
  update: {
    status: slip.active ? 'active' : 'pending', placedAt: dateOrNull(slip.placed_at_iso), odds: slip.overall_odds,
    stake: slip.stake, payout: slip.potential_winnings, selections: slip.selections, metadata: slip,
  },
  create: {
    userId, provider: PDF_PROVIDER, externalId: String(slip.id), status: slip.active ? 'active' : 'pending',
    placedAt: dateOrNull(slip.placed_at_iso), odds: slip.overall_odds, stake: slip.stake,
    payout: slip.potential_winnings, selections: slip.selections, metadata: slip,
  },
})

const persistHistorySlip = (userId, slip) => prisma.savedSlip.upsert({
  where: { userId_provider_externalId: { userId, provider: HISTORY_PROVIDER, externalId: String(slip.slip_id) } },
  update: {
    status: slip.status, placedAt: dateOrNull(slip.placed_at), odds: slip.total_odds, stake: slip.stake,
    payout: slip.potential_winnings, selections: slip.legs, metadata: slip,
  },
  create: {
    userId, provider: HISTORY_PROVIDER, externalId: String(slip.slip_id), status: slip.status,
    placedAt: dateOrNull(slip.placed_at), odds: slip.total_odds, stake: slip.stake,
    payout: slip.potential_winnings, selections: slip.legs, metadata: slip,
  },
})

const historySlips = async userId => {
  const records = await prisma.savedSlip.findMany({
    where: { userId, provider: HISTORY_PROVIDER },
    orderBy: [{ placedAt: 'desc' }, { createdAt: 'desc' }],
    take: 5000,
  })
  return records.map(record => record.metadata).filter(value => value && typeof value === 'object')
}

export const personalHistoryService = {
  async slips(userId) {
    assertDatabaseAvailable()
    const records = await prisma.savedSlip.findMany({
      where: { userId, provider: PDF_PROVIDER },
      orderBy: [{ placedAt: 'desc' }, { createdAt: 'desc' }],
      take: 500,
    })
    return records.map(record => record.metadata).filter(value => value && typeof value === 'object')
  },

  async importSlip(userId, payload) {
    assertDatabaseAvailable()
    const slip = await mlbStatsProvider.parseSlip(payload)
    await persistPdfSlip(userId, slip)
    return slip
  },

  async alterEgo(userId) {
    assertDatabaseAvailable()
    return mlbStatsProvider.analyseMelbetHistory(await historySlips(userId))
  },

  async importMelbetHistory(userId, payload) {
    assertDatabaseAvailable()
    const slip = await mlbStatsProvider.normalizeMelbetHistory(payload)
    await persistHistorySlip(userId, slip)
    return mlbStatsProvider.analyseMelbetHistory(await historySlips(userId))
  },

  async importMelbetHistoryBatch(userId, payload) {
    assertDatabaseAvailable()
    const normalized = await mlbStatsProvider.normalizeMelbetHistoryBatch(payload)
    const slips = normalized.slips || []
    const ids = slips.map(slip => String(slip.slip_id))
    const existing = await prisma.savedSlip.findMany({
      where: { userId, provider: HISTORY_PROVIDER, externalId: { in: ids } }, select: { externalId: true },
    })
    const existingIds = new Set(existing.map(item => item.externalId))
    await prisma.$transaction(slips.map(slip => persistHistorySlip(userId, slip)))
    return {
      import: {
        slips, inserted: slips.filter(slip => !existingIds.has(String(slip.slip_id))).length,
        updated: slips.filter(slip => existingIds.has(String(slip.slip_id))).length,
        total: await prisma.savedSlip.count({ where: { userId, provider: HISTORY_PROVIDER } }),
      },
      analysis: await mlbStatsProvider.analyseMelbetHistory(await historySlips(userId)),
    }
  },
}
