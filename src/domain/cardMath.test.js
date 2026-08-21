import test from 'node:test'
import assert from 'node:assert/strict'
import { cardProbability, footballScoreJointProbability, independentEventJointProbability } from './cardMath.js'

test('independent card probability accepts only distinct events', () => {
  assert.equal(independentEventJointProbability([{ gameId:1, probability:.6 }, { gameId:2, probability:.5 }]), .3)
  assert.throws(() => independentEventJointProbability([{ gameId:1, probability:.6 }, { gameId:1, probability:.5 }]), /joint model/)
})

test('football same-event probability is integrated over the score distribution', () => {
  const matrix = [[.1,.2],[.3,.4]]
  const homeWin = ({ homeGoals, awayGoals }) => homeGoals > awayGoals
  const overHalf = ({ homeGoals, awayGoals }) => homeGoals + awayGoals > .5
  assert.equal(footballScoreJointProbability(matrix, [homeWin, overHalf]), .3)
})

test('card probability requires an explicit joint value for same-event legs', () => {
  const legs = [{ eventId:'a', probability:.6 }, { eventId:'a', probability:.7 }, { eventId:'b', probability:.5 }]
  assert.throws(() => cardProbability(legs), /joint model/)
  assert.equal(cardProbability(legs, { sameEventJointProbability: () => .45 }), .225)
})
