import type {
  ChatRequest,
  ChatResponse,
  ErrorResponse,
  LivenessResponse,
  ReadinessResponse,
  StreamChunkEvent,
  StreamDoneEvent,
  StreamErrorEvent,
  StreamMetadataEvent,
} from '../contracts'

export const validChatRequest = {
  message: 'When should my first physical card arrive?',
} satisfies ChatRequest

export const validChatResponse = {
  request_id: 'server-request-id',
  answer: 'Check the delivery estimate shown in the app.',
  status: 'answered',
  response_mode: 'grounded_generation',
  risk_level: 'low',
  requires_human: false,
} satisfies ChatResponse

export const validErrorResponse = {
  request_id: 'server-request-id',
  error: {
    code: 'invalid_request',
    message: 'The request is invalid.',
    retryable: false,
  },
} satisfies ErrorResponse

export const validLivenessResponse = {
  status: 'alive',
  service: 'fintech-triage-api',
} satisfies LivenessResponse

export const validReadinessResponse = {
  status: 'ready',
  components: {
    configuration: 'ready',
    classifier: 'ready',
    pipeline: 'ready',
    vector_store: 'ready',
    ollama_chat_model: 'ready',
    ollama_embedding_model: 'ready',
  },
} satisfies ReadinessResponse

export const validStreamMetadataEvent = {
  request_id: 'server-request-id',
  status: 'safety_guidance',
  response_mode: 'deterministic_safety',
  risk_level: 'high',
  requires_human: false,
} satisfies StreamMetadataEvent

export const validStreamChunkEvent = {
  request_id: 'server-request-id',
  sequence: 0,
  text: 'Approved answer text',
} satisfies StreamChunkEvent

export const validStreamDoneEvent = {
  request_id: 'server-request-id',
  chunks: 1,
} satisfies StreamDoneEvent

export const validStreamErrorEvent = {
  request_id: 'server-request-id',
  error: {
    code: 'stream_interrupted',
    message: 'The response stream was interrupted.',
    retryable: true,
  },
} satisfies StreamErrorEvent
