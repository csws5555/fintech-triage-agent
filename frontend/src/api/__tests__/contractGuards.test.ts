import { describe, expect, it } from 'vitest'

import {
  isChatRequest,
  isChatResponse,
  isErrorDetail,
  isErrorResponse,
  isLivenessResponse,
  isPublicAnswerMetadata,
  isReadinessComponents,
  isReadinessResponse,
  isSseEventName,
  isStreamChunkEvent,
  isStreamDoneEvent,
  isStreamErrorEvent,
  isStreamMetadataEvent,
} from '../contractGuards'
import {
  MAX_CHAT_MESSAGE_CHARACTERS,
  PUBLIC_STATUS_VALUES,
  RESPONSE_MODE_VALUES,
  RISK_LEVEL_VALUES,
  SSE_EVENT_NAME_VALUES,
} from '../contracts'
import {
  validChatRequest,
  validChatResponse,
  validErrorResponse,
  validLivenessResponse,
  validReadinessResponse,
  validStreamChunkEvent,
  validStreamDoneEvent,
  validStreamErrorEvent,
  validStreamMetadataEvent,
} from './contractFixtures'

describe('chat contract guards', () => {
  it('accepts the exact request and normalized character boundary', () => {
    expect(isChatRequest(validChatRequest)).toBe(true)
    expect(
      isChatRequest({ message: `  ${'x'.repeat(MAX_CHAT_MESSAGE_CHARACTERS)}  ` }),
    ).toBe(true)
  })

  it.each([
    {},
    { message: '' },
    { message: '   ' },
    { message: 42 },
    { message: 'x'.repeat(MAX_CHAT_MESSAGE_CHARACTERS + 1) },
    { message: 'hello', request_id: 'client-controlled' },
  ])('rejects malformed or privileged request payload %#', (payload) => {
    expect(isChatRequest(payload)).toBe(false)
  })

  it('accepts every exact public chat enum value', () => {
    for (const status of PUBLIC_STATUS_VALUES) {
      for (const responseMode of RESPONSE_MODE_VALUES) {
        for (const riskLevel of RISK_LEVEL_VALUES) {
          expect(
            isChatResponse({
              ...validChatResponse,
              status,
              response_mode: responseMode,
              risk_level: riskLevel,
            }),
          ).toBe(true)
        }
      }
    }
  })

  it.each([
    { ...validChatResponse, request_id: '' },
    { ...validChatResponse, answer: '' },
    { ...validChatResponse, status: 'complete' },
    { ...validChatResponse, response_mode: 'raw_generation' },
    { ...validChatResponse, risk_level: 'urgent' },
    { ...validChatResponse, requires_human: 0 },
    { ...validChatResponse, reason_code: 'private' },
  ])('rejects malformed or internal chat response %#', (payload) => {
    expect(isChatResponse(payload)).toBe(false)
  })

  it('validates the metadata subset independently of a complete answer', () => {
    const metadata = {
      request_id: validChatResponse.request_id,
      status: validChatResponse.status,
      response_mode: validChatResponse.response_mode,
      risk_level: validChatResponse.risk_level,
      requires_human: validChatResponse.requires_human,
    }

    expect(isPublicAnswerMetadata(metadata)).toBe(true)
    expect(isPublicAnswerMetadata(validChatResponse)).toBe(false)
  })
})

describe('error contract guards', () => {
  it('accepts exact error details and envelopes', () => {
    expect(isErrorDetail(validErrorResponse.error)).toBe(true)
    expect(isErrorResponse(validErrorResponse)).toBe(true)
  })

  it.each([
    { ...validErrorResponse, request_id: '' },
    { ...validErrorResponse, error: null },
    { ...validErrorResponse, error: { ...validErrorResponse.error, code: '' } },
    {
      ...validErrorResponse,
      error: { ...validErrorResponse.error, message: '' },
    },
    {
      ...validErrorResponse,
      error: { ...validErrorResponse.error, retryable: 'false' },
    },
    {
      ...validErrorResponse,
      error: { ...validErrorResponse.error, exception: 'private' },
    },
    { ...validErrorResponse, stack_trace: 'private' },
  ])('rejects malformed or leaking error envelope %#', (payload) => {
    expect(isErrorResponse(payload)).toBe(false)
  })
})

describe('health contract guards', () => {
  it('accepts only the exact liveness literals', () => {
    expect(isLivenessResponse(validLivenessResponse)).toBe(true)
    expect(
      isLivenessResponse({ ...validLivenessResponse, status: 'ready' }),
    ).toBe(false)
    expect(
      isLivenessResponse({ ...validLivenessResponse, version: 'private' }),
    ).toBe(false)
  })

  it('accepts exact readiness payloads for HTTP 200 and HTTP 503', () => {
    expect(isReadinessResponse(validReadinessResponse)).toBe(true)
    expect(
      isReadinessResponse({
        status: 'degraded',
        components: {
          ...validReadinessResponse.components,
          vector_store: 'unavailable',
        },
      }),
    ).toBe(true)
  })

  it.each([
    {
      status: 'ready',
      components: {
        ...validReadinessResponse.components,
        vector_store: 'unavailable',
      },
    },
    {
      status: 'degraded',
      components: validReadinessResponse.components,
    },
    { ...validReadinessResponse, status: 'checking' },
    {
      ...validReadinessResponse,
      components: {
        ...validReadinessResponse.components,
        classifier: 'warming',
      },
    },
    {
      ...validReadinessResponse,
      components: {
        ...validReadinessResponse.components,
        model_path: 'private',
      },
    },
    { ...validReadinessResponse, diagnostics: 'private' },
  ])('rejects inconsistent, malformed, or internal readiness %#', (payload) => {
    expect(isReadinessResponse(payload)).toBe(false)
  })

  it('rejects a readiness component object with a missing field', () => {
    const incompleteComponents = {
      configuration: 'ready',
      classifier: 'ready',
      pipeline: 'ready',
      vector_store: 'ready',
      ollama_chat_model: 'ready',
    }

    expect(isReadinessComponents(incompleteComponents)).toBe(false)
  })
})

describe('SSE payload guards', () => {
  it('accepts only the four public SSE event names', () => {
    for (const eventName of SSE_EVENT_NAME_VALUES) {
      expect(isSseEventName(eventName)).toBe(true)
    }

    expect(isSseEventName('message')).toBe(false)
    expect(isSseEventName('token')).toBe(false)
    expect(isSseEventName(1)).toBe(false)
  })

  it('accepts all four exact event payloads', () => {
    expect(isStreamMetadataEvent(validStreamMetadataEvent)).toBe(true)
    expect(isStreamChunkEvent(validStreamChunkEvent)).toBe(true)
    expect(isStreamDoneEvent(validStreamDoneEvent)).toBe(true)
    expect(isStreamErrorEvent(validStreamErrorEvent)).toBe(true)
  })

  it.each([
    { ...validStreamMetadataEvent, answer: 'must not be present' },
    { ...validStreamMetadataEvent, status: 'unknown' },
    { ...validStreamMetadataEvent, retrieved_policy_ids: ['private'] },
  ])('rejects malformed or leaking metadata %#', (payload) => {
    expect(isStreamMetadataEvent(payload)).toBe(false)
  })

  it.each([
    { ...validStreamChunkEvent, request_id: '' },
    { ...validStreamChunkEvent, sequence: -1 },
    { ...validStreamChunkEvent, sequence: 0.5 },
    { ...validStreamChunkEvent, sequence: '0' },
    { ...validStreamChunkEvent, text: '' },
    { ...validStreamChunkEvent, document_id: 'private' },
  ])('rejects malformed or internal chunk payload %#', (payload) => {
    expect(isStreamChunkEvent(payload)).toBe(false)
  })

  it.each([
    { ...validStreamDoneEvent, request_id: '' },
    { ...validStreamDoneEvent, chunks: -1 },
    { ...validStreamDoneEvent, chunks: 1.5 },
    { ...validStreamDoneEvent, chunks: true },
    { ...validStreamDoneEvent, reason_code: 'private' },
  ])('rejects malformed or internal done payload %#', (payload) => {
    expect(isStreamDoneEvent(payload)).toBe(false)
  })

  it('applies the strict nested error envelope to stream errors', () => {
    expect(
      isStreamErrorEvent({
        ...validStreamErrorEvent,
        error: { ...validStreamErrorEvent.error, traceback: 'private' },
      }),
    ).toBe(false)
  })
})

describe('primitive and exact-shape behavior', () => {
  it.each([null, undefined, [], 'payload', 1, true])(
    'rejects non-object payload %s',
    (payload) => {
      expect(isChatResponse(payload)).toBe(false)
      expect(isErrorResponse(payload)).toBe(false)
      expect(isLivenessResponse(payload)).toBe(false)
      expect(isReadinessResponse(payload)).toBe(false)
      expect(isStreamMetadataEvent(payload)).toBe(false)
      expect(isStreamChunkEvent(payload)).toBe(false)
      expect(isStreamDoneEvent(payload)).toBe(false)
      expect(isStreamErrorEvent(payload)).toBe(false)
    },
  )
})
