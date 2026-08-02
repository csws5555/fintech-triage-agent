import type { RequestPhase } from './chatTypes'

const ALLOWED_REQUEST_TRANSITIONS: Readonly<
  Record<RequestPhase, ReadonlySet<RequestPhase>>
> = Object.freeze({
  idle: new Set<RequestPhase>(['processing']),
  processing: new Set<RequestPhase>([
    'streaming',
    'completed',
    'failed',
    'cancelled',
  ]),
  streaming: new Set<RequestPhase>([
    'completed',
    'failed',
    'cancelled',
  ]),
  completed: new Set<RequestPhase>(['processing', 'idle']),
  failed: new Set<RequestPhase>(['processing', 'idle']),
  cancelled: new Set<RequestPhase>(['processing', 'idle']),
})

export function canTransitionRequestPhase(
  current: RequestPhase,
  next: RequestPhase,
): boolean {
  return ALLOWED_REQUEST_TRANSITIONS[current].has(next)
}

export function isActiveRequestPhase(phase: RequestPhase): boolean {
  return phase === 'processing' || phase === 'streaming'
}

export function isTerminalRequestPhase(phase: RequestPhase): boolean {
  return phase === 'completed' || phase === 'failed' || phase === 'cancelled'
}
