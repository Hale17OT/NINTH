import { z } from 'zod'

const jsonValue = z.unknown()
export const savedPredictionSchema = z.object({
  sport: z.string().trim().min(1).max(50),
  league: z.string().trim().max(100).nullable().optional(),
  eventId: z.string().trim().min(1).max(150),
  predictionType: z.string().trim().min(1).max(100),
  selection: z.string().trim().min(1).max(300),
  probability: z.number().min(0).max(1).nullable().optional(),
  modelName: z.string().trim().min(1).max(120),
  modelVersion: z.string().trim().min(1).max(120),
  generatedAt: z.coerce.date(),
  inputSnapshot: jsonValue.optional(), output: jsonValue.optional(), oddsSnapshot: jsonValue.optional(), metadata: jsonValue.optional(),
})
export const savedBuilderSchema = z.object({
  name: z.string().trim().min(1).max(120),
  sport: z.string().trim().min(1).max(50),
  buildStyle: z.string().trim().max(80).nullable().optional(),
  selections: z.array(jsonValue).min(1).max(100),
  configuration: jsonValue.optional(),
  modelName: z.string().trim().max(120).nullable().optional(),
  modelVersion: z.string().trim().max(120).nullable().optional(),
  generatedAt: z.coerce.date().optional(),
})
export const savedSlipSchema = z.object({
  externalId: z.string().trim().max(180).nullable().optional(),
  provider: z.string().trim().min(1).max(50).default('MELBET'),
  status: z.string().trim().max(50).nullable().optional(),
  placedAt: z.coerce.date().nullable().optional(),
  odds: z.number().positive().nullable().optional(),
  stake: z.number().nonnegative().nullable().optional(),
  payout: z.number().nonnegative().nullable().optional(),
  selections: z.array(jsonValue).min(1).max(250),
  metadata: jsonValue.optional(),
})
