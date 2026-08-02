import {
  COMPONENT_STATUS_VALUES,
  MAX_CHAT_MESSAGE_CHARACTERS,
  PUBLIC_STATUS_VALUES,
  READINESS_STATUS_VALUES,
  RESPONSE_MODE_VALUES,
  RISK_LEVEL_VALUES,
  SSE_EVENT_NAME_VALUES,
  type ChatRequest,
  type ChatResponse,
  type ErrorDetail,
  type ErrorResponse,
  type LivenessResponse,
  type PublicAnswerMetadata,
  type ReadinessComponents,
  type ReadinessResponse,
  type SseEventName,
  type StreamChunkEvent,
  type StreamDoneEvent,
  type StreamErrorEvent,
  type StreamMetadataEvent,
} from './contracts'

type UnknownRecord = Record<string, unknown>

const CHAT_REQUEST_KEYS = ['message'] as const
const ANSWER_METADATA_KEYS = [
  'request_id',
  'status',
  'response_mode',
  'risk_level',
  'requires_human',
] as const
const CHAT_RESPONSE_KEYS = [...ANSWER_METADATA_KEYS, 'answer'] as const
const ERROR_DETAIL_KEYS = ['code', 'message', 'retryable'] as const
const ERROR_RESPONSE_KEYS = ['request_id', 'error'] as const
const LIVENESS_KEYS = ['status', 'service'] as const
const READINESS_COMPONENT_KEYS = [
  'configuration',
  'classifier',
  'pipeline',
  'vector_store',
  'ollama_chat_model',
  'ollama_embedding_model',
] as const
const READINESS_KEYS = ['status', 'components'] as const
const STREAM_CHUNK_KEYS = ['request_id', 'sequence', 'text'] as const
const STREAM_DONE_KEYS = ['request_id', 'chunks'] as const

function hasExactKeys(
  value: unknown,
  expectedKeys: readonly string[],
): value is UnknownRecord {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return false
  }

  const actualKeys = Object.keys(value)
  return (
    actualKeys.length === expectedKeys.length &&
    expectedKeys.every((key) =>
      Object.prototype.hasOwnProperty.call(value, key),
    )
  )
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function isOneOf<const Values extends readonly string[]>(
  value: unknown,
  allowedValues: Values,
): value is Values[number] {
  return (
    typeof value === 'string' &&
    (allowedValues as readonly string[]).includes(value)
  )
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function hasValidAnswerMetadata(value: UnknownRecord): boolean {
  return (
    isNonEmptyString(value.request_id) &&
    isOneOf(value.status, PUBLIC_STATUS_VALUES) &&
    isOneOf(value.response_mode, RESPONSE_MODE_VALUES) &&
    isOneOf(value.risk_level, RISK_LEVEL_VALUES) &&
    typeof value.requires_human === 'boolean'
  )
}

export function isChatRequest(value: unknown): value is ChatRequest {
  if (!hasExactKeys(value, CHAT_REQUEST_KEYS)) {
    return false
  }

  if (typeof value.message !== 'string') {
    return false
  }

  const normalizedMessage = value.message.trim()
  return (
    normalizedMessage.length > 0 &&
    normalizedMessage.length <= MAX_CHAT_MESSAGE_CHARACTERS
  )
}

export function isSseEventName(value: unknown): value is SseEventName {
  return isOneOf(value, SSE_EVENT_NAME_VALUES)
}

export function isPublicAnswerMetadata(
  value: unknown,
): value is PublicAnswerMetadata {
  return (
    hasExactKeys(value, ANSWER_METADATA_KEYS) &&
    hasValidAnswerMetadata(value)
  )
}

export function isChatResponse(value: unknown): value is ChatResponse {
  return (
    hasExactKeys(value, CHAT_RESPONSE_KEYS) &&
    hasValidAnswerMetadata(value) &&
    isNonEmptyString(value.answer)
  )
}

export function isErrorDetail(value: unknown): value is ErrorDetail {
  return (
    hasExactKeys(value, ERROR_DETAIL_KEYS) &&
    isNonEmptyString(value.code) &&
    isNonEmptyString(value.message) &&
    typeof value.retryable === 'boolean'
  )
}

export function isErrorResponse(value: unknown): value is ErrorResponse {
  return (
    hasExactKeys(value, ERROR_RESPONSE_KEYS) &&
    isNonEmptyString(value.request_id) &&
    isErrorDetail(value.error)
  )
}

export function isLivenessResponse(
  value: unknown,
): value is LivenessResponse {
  return (
    hasExactKeys(value, LIVENESS_KEYS) &&
    value.status === 'alive' &&
    value.service === 'fintech-triage-api'
  )
}

export function isReadinessComponents(
  value: unknown,
): value is ReadinessComponents {
  return (
    hasExactKeys(value, READINESS_COMPONENT_KEYS) &&
    READINESS_COMPONENT_KEYS.every((key) =>
      isOneOf(value[key], COMPONENT_STATUS_VALUES),
    )
  )
}

export function isReadinessResponse(
  value: unknown,
): value is ReadinessResponse {
  if (!hasExactKeys(value, READINESS_KEYS)) {
    return false
  }

  const components = value.components
  if (
    !isOneOf(value.status, READINESS_STATUS_VALUES) ||
    !isReadinessComponents(components)
  ) {
    return false
  }

  const allComponentsReady = READINESS_COMPONENT_KEYS.every(
    (key) => components[key] === 'ready',
  )
  return value.status === (allComponentsReady ? 'ready' : 'degraded')
}

export function isStreamMetadataEvent(
  value: unknown,
): value is StreamMetadataEvent {
  return isPublicAnswerMetadata(value)
}

export function isStreamChunkEvent(
  value: unknown,
): value is StreamChunkEvent {
  return (
    hasExactKeys(value, STREAM_CHUNK_KEYS) &&
    isNonEmptyString(value.request_id) &&
    isNonNegativeInteger(value.sequence) &&
    isNonEmptyString(value.text)
  )
}

export function isStreamDoneEvent(
  value: unknown,
): value is StreamDoneEvent {
  return (
    hasExactKeys(value, STREAM_DONE_KEYS) &&
    isNonEmptyString(value.request_id) &&
    isNonNegativeInteger(value.chunks)
  )
}

export function isStreamErrorEvent(
  value: unknown,
): value is StreamErrorEvent {
  return isErrorResponse(value)
}
