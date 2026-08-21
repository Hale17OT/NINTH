const numericProbability = value => {
  const probability = Number(value)
  if (!Number.isFinite(probability) || probability < 0 || probability > 1) {
    throw new RangeError(`Invalid probability: ${value}`)
  }
  return probability
}

const eventIdentity = leg => String(leg.eventId ?? leg.gameId ?? leg.game?.id ?? leg.game?.game_id ?? '')

/**
 * Multiply probabilities only when every leg belongs to a different event.
 * Same-event legs require a modelled joint distribution; silently treating them
 * as independent is not a safe card estimate.
 */
export function independentEventJointProbability(legs = []) {
  const events = new Set()
  return legs.reduce((joint, leg) => {
    const event = eventIdentity(leg)
    if (!event) throw new Error('Every card leg requires a stable event identity')
    if (events.has(event)) throw new Error(`Same-event legs require a joint model: ${event}`)
    events.add(event)
    return joint * numericProbability(leg.probability ?? leg.option?.probability)
  }, 1)
}

/** Integrate compatible football selections over one calibrated score matrix. */
export function footballScoreJointProbability(scoreMatrix, predicates = []) {
  if (!Array.isArray(scoreMatrix) || !scoreMatrix.length || !predicates.length) return null
  if (predicates.some(predicate => typeof predicate !== 'function')) throw new TypeError('Score predicates must be functions')
  let joint = 0
  scoreMatrix.forEach((row, homeGoals) => {
    if (!Array.isArray(row)) throw new TypeError('Score matrix rows must be arrays')
    row.forEach((cell, awayGoals) => {
      const probability = numericProbability(cell)
      if (predicates.every(predicate => predicate({ homeGoals, awayGoals }))) joint += probability
    })
  })
  return Math.min(1, joint)
}

export function cardProbability(legs = [], { sameEventJointProbability = null } = {}) {
  const grouped = new Map()
  for (const leg of legs) {
    const event = eventIdentity(leg)
    if (!event) throw new Error('Every card leg requires a stable event identity')
    grouped.set(event, [...(grouped.get(event) || []), leg])
  }
  let card = 1
  for (const [event, eventLegs] of grouped) {
    if (eventLegs.length === 1) card *= numericProbability(eventLegs[0].probability ?? eventLegs[0].option?.probability)
    else {
      if (typeof sameEventJointProbability !== 'function') throw new Error(`Same-event legs require a joint model: ${event}`)
      card *= numericProbability(sameEventJointProbability(event, eventLegs))
    }
  }
  return card
}
