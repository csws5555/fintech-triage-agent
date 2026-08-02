export const MAX_CHAT_MESSAGE_CHARACTERS = 2_000

export const PUBLIC_STATUS_VALUES = [
  'answered',
  'clarification_required',
  'safety_guidance',
  'request_refused',
  'action_not_confirmed',
  'unsupported',
  'service_fallback',
] as const

export const RESPONSE_MODE_VALUES = [
  'static_fallback',
  'deterministic_clarification',
  'deterministic_safety',
  'grounded_generation',
] as const

export const RISK_LEVEL_VALUES = [
  'low',
  'medium',
  'high',
  'critical',
] as const

export const READINESS_STATUS_VALUES = ['ready', 'degraded'] as const
export const COMPONENT_STATUS_VALUES = ['ready', 'unavailable'] as const
export const SSE_EVENT_NAME_VALUES = [
  'metadata',
  'chunk',
  'done',
  'error',
] as const

export type PublicStatus = (typeof PUBLIC_STATUS_VALUES)[number]
export type ResponseMode = (typeof RESPONSE_MODE_VALUES)[number]
export type RiskLevel = (typeof RISK_LEVEL_VALUES)[number]
export type ReadinessStatus = (typeof READINESS_STATUS_VALUES)[number]
export type ComponentStatus = (typeof COMPONENT_STATUS_VALUES)[number]
export type SseEventName = (typeof SSE_EVENT_NAME_VALUES)[number]

export type ChatRequest = Readonly<{
  message: string
}>

export type PublicAnswerMetadata = Readonly<{
  request_id: string
  status: PublicStatus
  response_mode: ResponseMode
  risk_level: RiskLevel
  requires_human: boolean
}>

export type ChatResponse = Readonly<
  PublicAnswerMetadata & {
    answer: string
  }
>

export type ErrorDetail = Readonly<{
  code: string
  message: string
  retryable: boolean
}>

export type ErrorResponse = Readonly<{
  request_id: string
  error: ErrorDetail
}>

export type LivenessResponse = Readonly<{
  status: 'alive'
  service: 'fintech-triage-api'
}>

export type ReadinessComponents = Readonly<{
  configuration: ComponentStatus
  classifier: ComponentStatus
  pipeline: ComponentStatus
  vector_store: ComponentStatus
  ollama_chat_model: ComponentStatus
  ollama_embedding_model: ComponentStatus
}>

export type ReadinessResponse = Readonly<{
  status: ReadinessStatus
  components: ReadinessComponents
}>

export type StreamMetadataEvent = PublicAnswerMetadata

export type StreamChunkEvent = Readonly<{
  request_id: string
  sequence: number
  text: string
}>

export type StreamDoneEvent = Readonly<{
  request_id: string
  chunks: number
}>

export type StreamErrorEvent = Readonly<{
  request_id: string
  error: ErrorDetail
}>

export type SseEventPayloads = Readonly<{
  metadata: StreamMetadataEvent
  chunk: StreamChunkEvent
  done: StreamDoneEvent
  error: StreamErrorEvent
}>
