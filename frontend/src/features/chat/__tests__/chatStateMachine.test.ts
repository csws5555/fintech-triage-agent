import { describe, expect, it } from 'vitest'

import {
  canTransitionRequestPhase,
  isActiveRequestPhase,
  isTerminalRequestPhase,
} from '../chatStateMachine'
import {
  REQUEST_PHASE_VALUES,
  type RequestPhase,
} from '../chatTypes'

const VALID_TRANSITIONS: readonly (readonly [RequestPhase, RequestPhase])[] = [
  ['idle', 'processing'],
  ['processing', 'streaming'],
  ['processing', 'completed'],
  ['processing', 'failed'],
  ['processing', 'cancelled'],
  ['streaming', 'completed'],
  ['streaming', 'failed'],
  ['streaming', 'cancelled'],
  ['completed', 'processing'],
  ['completed', 'idle'],
  ['failed', 'processing'],
  ['failed', 'idle'],
  ['cancelled', 'processing'],
  ['cancelled', 'idle'],
]

describe('request state machine', () => {
  it.each(VALID_TRANSITIONS)('allows %s -> %s', (current, next) => {
    expect(canTransitionRequestPhase(current, next)).toBe(true)
  })

  it('rejects every transition outside the explicit table', () => {
    for (const current of REQUEST_PHASE_VALUES) {
      for (const next of REQUEST_PHASE_VALUES) {
        const listed = VALID_TRANSITIONS.some(
          ([allowedCurrent, allowedNext]) =>
            allowedCurrent === current && allowedNext === next,
        )
        expect(canTransitionRequestPhase(current, next)).toBe(listed)
      }
    }
  })

  it('separates active and terminal phases', () => {
    expect(
      REQUEST_PHASE_VALUES.filter(isActiveRequestPhase),
    ).toEqual(['processing', 'streaming'])
    expect(
      REQUEST_PHASE_VALUES.filter(isTerminalRequestPhase),
    ).toEqual(['completed', 'failed', 'cancelled'])
    expect(isActiveRequestPhase('idle')).toBe(false)
    expect(isTerminalRequestPhase('idle')).toBe(false)
  })
})
