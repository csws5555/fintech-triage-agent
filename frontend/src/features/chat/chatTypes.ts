import type { ApiClientErrorKind } from '../../api/errors'
import type {
  PublicAnswerMetadata,
  ReadinessComponents,
} from '../../api/contracts'

export const REQUEST_PHASE_VALUES = [
  'idle',
  'processing',
  'streaming',
  'completed',
  'failed',
  'cancelled',
] as const

export const AVAILABILITY_VALUES = [
  'checking',
  'ready',
  'degraded',
  'unavailable',
] as const

export const MESSAGE_DELIVERY_VALUES = [
  'pending',
  'streaming',
  'complete',
  'interrupted',
  'cancelled',
  'failed',
] as const

export type RequestPhase = (typeof REQUEST_PHASE_VALUES)[number]
export type Availability = (typeof AVAILABILITY_VALUES)[number]
export type MessageDelivery = (typeof MESSAGE_DELIVERY_VALUES)[number]

export type ChatMessage = Readonly<{
  id: string
  turnId: string
  role: 'user' | 'assistant'
  content: string
  delivery: MessageDelivery
  requestId?: string
  metadata?: PublicAnswerMetadata
}>

export type ChatInputError = Readonly<{
  code: 'empty_message' | 'message_too_long'
  message: string
}>

export type ChatRequestError = Readonly<{
  kind: ApiClientErrorKind
  code: string
  message: string
  retryable: boolean
  status: number | null
  requestId: string | null
}>

export type ChatConversationState = Readonly<{
  messages: readonly ChatMessage[]
  draft: string
  inputError: ChatInputError | null
  availability: Availability
  readinessComponents: ReadinessComponents | null
  operationId: string | null
  activeTurnId: string | null
  requestPhase: RequestPhase
  nextExpectedSequence: number
  serverRequestId: string | null
  abortController: AbortController | null
  availabilityError: ChatRequestError | null
  error: ChatRequestError | null
  retrySourceText: string | null
  retryTurnId: string | null
}>
