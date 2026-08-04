import { describe, expect, it, vi } from 'vitest'

import type { ApiClient, ApiRequestOptions } from '../../../api/client'
import {
  MAX_CHAT_MESSAGE_CHARACTERS,
  type ChatResponse,
  type LivenessResponse,
  type PublicAnswerMetadata,
  type ReadinessResponse,
} from '../../../api/contracts'
import { ApiClientError } from '../../../api/errors'
import type {
  CompletedStream,
  StreamEventHandlers,
} from '../../../api/sseParser'
import { createChatStore, type ChatStore } from '../chatStore'

const READY: ReadinessResponse = {
  status: 'ready',
  components: {
    configuration: 'ready',
    classifier: 'ready',
    pipeline: 'ready',
    vector_store: 'ready',
    ollama_chat_model: 'ready',
    ollama_embedding_model: 'ready',
  },
}

const ALIVE: LivenessResponse = {
  status: 'alive',
  service: 'fintech-triage-api',
}

const METADATA: PublicAnswerMetadata = {
  request_id: 'server-request-id',
  status: 'answered',
  response_mode: 'grounded_generation',
  risk_level: 'low',
  requires_human: false,
}

type PendingStream = {
  message: string
  handlers: StreamEventHandlers
  signal: AbortSignal | undefined
  resolve: (value: CompletedStream) => void
  reject: (reason: unknown) => void
}

type Harness = {
  store: ReturnType<typeof createChatStore>
  pending: PendingStream[]
  checkLiveness: ReturnType<typeof vi.fn<ApiClient['checkLiveness']>>
  checkReadiness: ReturnType<typeof vi.fn<ApiClient['checkReadiness']>>
  streamChatMessage: ReturnType<
    typeof vi.fn<ApiClient['streamChatMessage']>
  >
}

function cancellationError(): ApiClientError {
  return new ApiClientError({
    kind: 'cancelled',
    code: 'request_cancelled',
    message: 'The request was cancelled.',
    retryable: true,
  })
}

function requestError(
  code = 'stream_interrupted',
  requestId = 'server-request-id',
): ApiClientError {
  return new ApiClientError({
    kind: 'network',
    code,
    message: 'The response stream was interrupted.',
    retryable: true,
    requestId,
  })
}

function createHarness(
  readiness: ReadinessResponse = READY,
): Harness {
  const pending: PendingStream[] = []
  const checkReadiness = vi
    .fn<ApiClient['checkReadiness']>()
    .mockResolvedValue(readiness)
  const checkLiveness = vi
    .fn<ApiClient['checkLiveness']>()
    .mockResolvedValue(ALIVE)
  const streamChatMessage = vi.fn<ApiClient['streamChatMessage']>(
    (message, handlers, options: ApiRequestOptions = {}) =>
      new Promise<CompletedStream>((resolve, reject) => {
        const stream = {
          message,
          handlers,
          signal: options.signal,
          resolve,
          reject,
        }
        pending.push(stream)
        options.signal?.addEventListener(
          'abort',
          () => reject(cancellationError()),
          { once: true },
        )
      }),
  )
  const apiClient: ApiClient = {
    checkLiveness,
    checkReadiness,
    sendChatMessage: vi.fn<ApiClient['sendChatMessage']>() as (
      message: string,
      options?: ApiRequestOptions,
    ) => Promise<ChatResponse>,
    streamChatMessage,
  }
  let nextId = 0
  return {
    store: createChatStore({
      apiClient,
      idFactory: () => String(++nextId),
    }),
    pending,
    checkLiveness,
    checkReadiness,
    streamChatMessage,
  }
}

async function makeReady(harness: Harness): Promise<void> {
  await expect(
    harness.store.getState().initializeAvailability(),
  ).resolves.toBe('ready')
}

async function beginSubmission(
  harness: Harness,
  message = '  When should my card arrive?  ',
): Promise<{ submission: Promise<boolean> }> {
  await makeReady(harness)
  harness.store.getState().setDraft(message)
  const submission = harness.store.getState().submitMessage()
  await vi.waitFor(() => expect(harness.pending).toHaveLength(1))
  return { submission }
}

function activeOperation(state: ChatStore): string {
  expect(state.operationId).not.toBeNull()
  return state.operationId ?? ''
}

function deliverCompleteStream(
  harness: Harness,
  index = 0,
  chunks: readonly string[] = ['Approved ', 'answer.'],
): void {
  const request = harness.pending[index]
  if (request === undefined) {
    throw new Error('Missing pending stream in test harness.')
  }
  request.handlers.onMetadata(METADATA)
  chunks.forEach((text, sequence) => {
    request.handlers.onChunk({
      request_id: METADATA.request_id,
      sequence,
      text,
    })
  })
  request.resolve({
    requestId: METADATA.request_id,
    chunks: chunks.length,
  })
}

describe('chat store availability', () => {
  it('starts checking with an empty memory-only conversation', () => {
    const { store } = createHarness()

    expect(store.getState()).toMatchObject({
      messages: [],
      draft: '',
      availability: 'checking',
      readinessComponents: null,
      requestPhase: 'idle',
      operationId: null,
      abortController: null,
      availabilityError: null,
      error: null,
      retrySourceText: null,
    })
  })

  it('maps fully ready and optional-only degraded readiness', async () => {
    const readyHarness = createHarness()
    await expect(
      readyHarness.store.getState().initializeAvailability(),
    ).resolves.toBe('ready')
    expect(readyHarness.store.getState().readinessComponents).toEqual(
      READY.components,
    )

    const degradedHarness = createHarness({
      status: 'degraded',
      components: {
        ...READY.components,
        vector_store: 'unavailable',
      },
    })
    await expect(
      degradedHarness.store.getState().initializeAvailability(),
    ).resolves.toBe('degraded')
  })

  it('fails closed for mandatory unavailability and readiness failure', async () => {
    const mandatoryUnavailable = createHarness({
      status: 'degraded',
      components: {
        ...READY.components,
        classifier: 'unavailable',
      },
    })
    await expect(
      mandatoryUnavailable.store
        .getState()
        .initializeAvailability(),
    ).resolves.toBe('unavailable')

    const failed = createHarness()
    failed.checkReadiness.mockRejectedValueOnce(
      new Error('private readiness exception'),
    )
    await expect(
      failed.store.getState().initializeAvailability(),
    ).resolves.toBe('unavailable')
    expect(failed.store.getState().availabilityError).toEqual({
      kind: 'invalid_response',
      code: 'unexpected_client_error',
      message: 'The request could not be completed.',
      retryable: false,
      status: null,
      requestId: null,
    })
    expect(JSON.stringify(failed.store.getState())).not.toContain(
      'private readiness exception',
    )
    expect(failed.checkLiveness).toHaveBeenCalledTimes(1)
    expect(failed.store.getState().error).toBeNull()
  })

  it('distinguishes a live backend whose readiness cannot be confirmed', async () => {
    const harness = createHarness()
    harness.checkReadiness.mockRejectedValueOnce(
      new ApiClientError({
        kind: 'network',
        code: 'api_unreachable',
        message: 'The local support service could not be reached.',
        retryable: true,
      }),
    )

    await expect(
      harness.store.getState().initializeAvailability(),
    ).resolves.toBe('unavailable')
    expect(harness.checkLiveness).toHaveBeenCalledTimes(1)
    expect(harness.store.getState().availabilityError).toMatchObject({
      code: 'readiness_unconfirmed',
      message:
        'The local support service is running, but readiness could not be confirmed.',
    })
  })

  it('uses a safe liveness failure when neither health endpoint is reachable', async () => {
    const harness = createHarness()
    harness.checkReadiness.mockRejectedValueOnce(
      new Error('private readiness failure'),
    )
    harness.checkLiveness.mockRejectedValueOnce(
      new ApiClientError({
        kind: 'network',
        code: 'api_unreachable',
        message: 'The local support service could not be reached.',
        retryable: true,
      }),
    )

    await expect(
      harness.store.getState().initializeAvailability(),
    ).resolves.toBe('unavailable')
    expect(harness.store.getState().availabilityError).toMatchObject({
      kind: 'network',
      code: 'api_unreachable',
      message: 'The local support service could not be reached.',
    })
    expect(JSON.stringify(harness.store.getState())).not.toContain('private')
  })

  it('fails closed for a status/component combination a bad client lets through', async () => {
    const malformed = createHarness({
      status: 'ready',
      components: {
        ...READY.components,
        ollama_chat_model: 'unavailable',
      },
    })

    await expect(
      malformed.store.getState().initializeAvailability(),
    ).resolves.toBe('unavailable')
  })

  it('blocks submission while unavailable without calling chat', async () => {
    const harness = createHarness({
      status: 'degraded',
      components: {
        ...READY.components,
        pipeline: 'unavailable',
      },
    })
    await harness.store.getState().initializeAvailability()
    harness.store.getState().setDraft('Customer message')

    await expect(
      harness.store.getState().submitMessage(),
    ).resolves.toBe(false)
    expect(harness.streamChatMessage).not.toHaveBeenCalled()
    expect(harness.store.getState().requestPhase).toBe('idle')
  })
})

describe('chat store submission and streaming transitions', () => {
  it('creates one turn, trims the message, and keeps the operation ID local', async () => {
    const harness = createHarness()
    const { submission } = await beginSubmission(harness)
    const state = harness.store.getState()

    expect(state.requestPhase).toBe('processing')
    expect(state.messages).toHaveLength(2)
    expect(state.messages[0]).toMatchObject({
      role: 'user',
      content: 'When should my card arrive?',
      delivery: 'complete',
    })
    expect(state.messages[1]).toMatchObject({
      role: 'assistant',
      content: '',
      delivery: 'pending',
    })
    expect(state.messages[0]?.turnId).toBe(state.messages[1]?.turnId)
    expect(harness.streamChatMessage).toHaveBeenCalledWith(
      'When should my card arrive?',
      expect.objectContaining({
        onMetadata: expect.any(Function),
        onChunk: expect.any(Function),
      }),
      { signal: state.abortController?.signal },
    )
    expect(harness.pending[0]?.message).not.toContain(
      state.operationId ?? 'missing-operation',
    )

    deliverCompleteStream(harness)
    await expect(submission).resolves.toBe(true)
  })

  it('reconstructs approved chunks and completes only with matching counts', async () => {
    const harness = createHarness()
    const { submission } = await beginSubmission(harness)
    const operationId = activeOperation(harness.store.getState())
    const pending = harness.pending[0]
    if (pending === undefined) {
      throw new Error('Missing pending stream in test harness.')
    }

    pending.handlers.onMetadata(METADATA)
    expect(harness.store.getState()).toMatchObject({
      requestPhase: 'streaming',
      serverRequestId: METADATA.request_id,
      nextExpectedSequence: 0,
    })

    pending.handlers.onChunk({
      request_id: METADATA.request_id,
      sequence: 0,
      text: 'Card café ',
    })
    pending.handlers.onChunk({
      request_id: METADATA.request_id,
      sequence: 1,
      text: '安全 guidance.',
    })
    expect(harness.store.getState().messages[1]).toMatchObject({
      content: 'Card café 安全 guidance.',
      delivery: 'streaming',
      requestId: METADATA.request_id,
      metadata: METADATA,
    })
    expect(
      harness.store
        .getState()
        .completeStream(operationId, {
          requestId: METADATA.request_id,
          chunks: 1,
        }),
    ).toBe(false)
    expect(harness.store.getState().requestPhase).toBe('streaming')

    pending.resolve({ requestId: METADATA.request_id, chunks: 2 })
    await expect(submission).resolves.toBe(true)
    expect(harness.store.getState()).toMatchObject({
      requestPhase: 'completed',
      operationId: null,
      abortController: null,
      retrySourceText: null,
    })
    expect(harness.store.getState().messages[1]?.delivery).toBe('complete')
  })

  it('prevents duplicate submissions while one operation is active', async () => {
    const harness = createHarness()
    const { submission: first } = await beginSubmission(harness)
    harness.store.getState().setDraft('A second customer message')

    await expect(
      harness.store.getState().submitMessage(),
    ).resolves.toBe(false)
    expect(harness.pending).toHaveLength(1)
    expect(harness.store.getState().messages).toHaveLength(2)

    deliverCompleteStream(harness)
    await first
  })

  it('ignores invalid and stale callbacks without mutating active state', async () => {
    const harness = createHarness()
    const { submission } = await beginSubmission(harness)
    const operationId = activeOperation(harness.store.getState())
    const before = harness.store.getState()

    expect(
      before.appendChunk(operationId, {
        request_id: METADATA.request_id,
        sequence: 0,
        text: 'too early',
      }),
    ).toBe(false)
    expect(before.acceptMetadata('stale-operation', METADATA)).toBe(false)
    expect(harness.store.getState()).toBe(before)

    expect(before.acceptMetadata(operationId, METADATA)).toBe(true)
    const streaming = harness.store.getState()
    expect(streaming.acceptMetadata(operationId, METADATA)).toBe(false)
    expect(
      streaming.appendChunk(operationId, {
        request_id: 'wrong-request-id',
        sequence: 0,
        text: 'wrong request',
      }),
    ).toBe(false)
    expect(
      streaming.appendChunk(operationId, {
        request_id: METADATA.request_id,
        sequence: 1,
        text: 'skipped sequence',
      }),
    ).toBe(false)
    expect(harness.store.getState()).toBe(streaming)

    harness.pending[0]?.resolve({
      requestId: METADATA.request_id,
      chunks: 0,
    })
    await submission
  })

  it.each([
    ['', 'empty_message'],
    [' \t\n ', 'empty_message'],
    ['x'.repeat(MAX_CHAT_MESSAGE_CHARACTERS + 1), 'message_too_long'],
  ])('rejects invalid draft input without creating a turn', async (draft, code) => {
    const harness = createHarness()
    await makeReady(harness)
    harness.store.getState().setDraft(draft)

    await expect(
      harness.store.getState().submitMessage(),
    ).resolves.toBe(false)
    expect(harness.store.getState()).toMatchObject({
      requestPhase: 'idle',
      messages: [],
      inputError: { code },
    })
    expect(harness.streamChatMessage).not.toHaveBeenCalled()
  })
})

describe('chat store failure, cancellation, retry, and clear', () => {
  it.each([
    ['network', 'api_unreachable'],
    ['network', 'stream_interrupted'],
    ['http', 'classifier_unavailable'],
    ['http', 'support_service_unavailable'],
  ] as const)(
    'rechecks readiness after a %s/%s request failure without retrying chat',
    async (kind, code) => {
      const harness = createHarness()
      const { submission } = await beginSubmission(harness)
      harness.pending[0]?.reject(
        new ApiClientError({
          kind,
          code,
          message: 'Approved request failure.',
          retryable: true,
          ...(kind === 'http' ? { status: 503 } : {}),
        }),
      )

      await submission
      expect(harness.checkReadiness).toHaveBeenCalledTimes(2)
      expect(harness.streamChatMessage).toHaveBeenCalledTimes(1)
      expect(harness.store.getState()).toMatchObject({
        availability: 'ready',
        requestPhase: 'failed',
        error: { kind, code, message: 'Approved request failure.' },
      })
    },
  )

  it('does not recheck availability or retry chat after service busy', async () => {
    const harness = createHarness()
    const { submission } = await beginSubmission(harness)
    harness.pending[0]?.reject(
      new ApiClientError({
        kind: 'http',
        code: 'service_busy',
        message: 'The support service is busy. Please try again.',
        retryable: true,
        status: 503,
      }),
    )

    await submission
    expect(harness.checkReadiness).toHaveBeenCalledTimes(1)
    expect(harness.streamChatMessage).toHaveBeenCalledTimes(1)
    expect(harness.store.getState().requestPhase).toBe('failed')
  })

  it('preserves partial approved text as interrupted and stores only a safe error', async () => {
    const harness = createHarness()
    const { submission } = await beginSubmission(harness)
    const pending = harness.pending[0]
    if (pending === undefined) {
      throw new Error('Missing pending stream in test harness.')
    }
    pending.handlers.onMetadata(METADATA)
    pending.handlers.onChunk({
      request_id: METADATA.request_id,
      sequence: 0,
      text: 'Approved partial text.',
    })
    pending.reject(requestError())

    await submission
    expect(harness.store.getState()).toMatchObject({
      requestPhase: 'failed',
      operationId: null,
      error: {
        kind: 'network',
        code: 'stream_interrupted',
        message: 'The response stream was interrupted.',
        retryable: true,
        requestId: METADATA.request_id,
      },
    })
    expect(harness.store.getState().messages[1]).toMatchObject({
      content: 'Approved partial text.',
      delivery: 'interrupted',
    })
  })

  it('normalizes unexpected failures without retaining exception details', async () => {
    const harness = createHarness()
    const { submission } = await beginSubmission(harness)
    harness.pending[0]?.reject(
      new Error('private path C:\\secret and customer text'),
    )

    await submission
    expect(harness.store.getState().error).toEqual({
      kind: 'invalid_response',
      code: 'unexpected_client_error',
      message: 'The request could not be completed.',
      retryable: false,
      status: null,
      requestId: null,
    })
    expect(JSON.stringify(harness.store.getState())).not.toContain(
      'C:\\secret',
    )
  })

  it('cancels once and cannot later become completed', async () => {
    const harness = createHarness()
    const { submission } = await beginSubmission(harness)
    const staleHandlers = harness.pending[0]?.handlers

    expect(harness.store.getState().cancelRequest()).toBe(true)
    await submission
    expect(harness.pending[0]?.signal?.aborted).toBe(true)
    expect(harness.store.getState()).toMatchObject({
      requestPhase: 'cancelled',
      operationId: null,
      error: null,
    })
    expect(harness.store.getState().messages[1]?.delivery).toBe('cancelled')
    expect(harness.store.getState().cancelRequest()).toBe(false)

    staleHandlers?.onMetadata(METADATA)
    staleHandlers?.onChunk({
      request_id: METADATA.request_id,
      sequence: 0,
      text: 'late text',
    })
    expect(harness.store.getState().requestPhase).toBe('cancelled')
    expect(harness.store.getState().messages[1]?.content).toBe('')
  })

  it('keeps approved chunks incomplete when cancellation happens during delivery', async () => {
    const harness = createHarness()
    const { submission } = await beginSubmission(harness)
    const operationId = activeOperation(harness.store.getState())
    const pending = harness.pending[0]
    if (pending === undefined) {
      throw new Error('Missing pending stream in test harness.')
    }
    pending.handlers.onMetadata(METADATA)
    pending.handlers.onChunk({
      request_id: METADATA.request_id,
      sequence: 0,
      text: 'Approved partial text.',
    })

    expect(harness.store.getState().cancelRequest()).toBe(true)
    await submission

    expect(harness.store.getState().messages[1]).toMatchObject({
      content: 'Approved partial text.',
      delivery: 'cancelled',
    })
    expect(
      harness.store.getState().completeStream(operationId, {
        requestId: METADATA.request_id,
        chunks: 1,
      }),
    ).toBe(false)
    expect(harness.store.getState().requestPhase).toBe('cancelled')
  })

  it('retries the same turn without duplicating the user message', async () => {
    const harness = createHarness()
    const { submission: firstSubmission } = await beginSubmission(harness)
    const firstOperationId = activeOperation(harness.store.getState())
    const firstHandlers = harness.pending[0]?.handlers
    firstHandlers?.onMetadata(METADATA)
    firstHandlers?.onChunk({
      request_id: METADATA.request_id,
      sequence: 0,
      text: 'Old partial text.',
    })
    harness.pending[0]?.reject(requestError())
    await firstSubmission

    const originalIds = harness.store
      .getState()
      .messages.map((message) => message.id)
    const retry = harness.store.getState().retryRequest()
    await vi.waitFor(() => expect(harness.pending).toHaveLength(2))
    const retryState = harness.store.getState()
    expect(retryState.requestPhase).toBe('processing')
    expect(retryState.operationId).not.toBe(firstOperationId)
    expect(retryState.messages).toHaveLength(2)
    expect(retryState.messages.map((message) => message.id)).toEqual(
      originalIds,
    )
    expect(retryState.messages[1]).toMatchObject({
      content: '',
      delivery: 'pending',
    })

    firstHandlers?.onChunk({
      request_id: METADATA.request_id,
      sequence: 1,
      text: 'stale retry text',
    })
    expect(harness.store.getState().messages[1]?.content).toBe('')

    deliverCompleteStream(harness, 1, ['Fresh answer.'])
    await expect(retry).resolves.toBe(true)
    expect(harness.store.getState().messages).toHaveLength(2)
    expect(harness.store.getState().messages[1]).toMatchObject({
      content: 'Fresh answer.',
      delivery: 'complete',
    })
  })

  it('retries a cancellation in the same turn without duplicating the customer message', async () => {
    const harness = createHarness()
    const { submission: cancelledSubmission } = await beginSubmission(harness)
    const originalIds = harness.store
      .getState()
      .messages.map((message) => message.id)

    expect(harness.store.getState().cancelRequest()).toBe(true)
    await cancelledSubmission

    const retry = harness.store.getState().retryRequest()
    await vi.waitFor(() => expect(harness.pending).toHaveLength(2))
    expect(harness.store.getState().messages).toHaveLength(2)
    expect(
      harness.store.getState().messages.map((message) => message.id),
    ).toEqual(originalIds)
    expect(harness.store.getState().messages[1]).toMatchObject({
      content: '',
      delivery: 'pending',
    })

    deliverCompleteStream(harness, 1, ['Fresh answer after cancellation.'])
    await expect(retry).resolves.toBe(true)
    expect(harness.store.getState().messages[1]).toMatchObject({
      content: 'Fresh answer after cancellation.',
      delivery: 'complete',
    })
  })

  it('restores a nonretryable request for editing and resends it as a new turn', async () => {
    const harness = createHarness()
    const { submission: failedSubmission } = await beginSubmission(harness)
    harness.pending[0]?.reject(
      new ApiClientError({
        kind: 'invalid_response',
        code: 'invalid_stream_response',
        message:
          'The local support service returned an invalid response stream.',
        retryable: false,
      }),
    )
    await failedSubmission

    await expect(harness.store.getState().retryRequest()).resolves.toBe(false)
    expect(harness.store.getState().editAndResendRequest()).toBe(true)
    expect(harness.store.getState()).toMatchObject({
      draft: 'When should my card arrive?',
      requestPhase: 'idle',
      error: null,
      retrySourceText: null,
      retryTurnId: null,
    })

    harness.store.getState().setDraft('When should my edited card arrive?')
    const resend = harness.store.getState().submitMessage()
    await vi.waitFor(() => expect(harness.pending).toHaveLength(2))
    expect(harness.pending[1]?.message).toBe(
      'When should my edited card arrive?',
    )
    expect(harness.store.getState().messages).toHaveLength(4)
    expect(harness.store.getState().messages[2]).toMatchObject({
      role: 'user',
      content: 'When should my edited card arrive?',
    })

    deliverCompleteStream(harness, 1, ['Edited answer.'])
    await expect(resend).resolves.toBe(true)
  })

  it('aborts active work before clearing all conversation memory', async () => {
    const harness = createHarness()
    const { submission } = await beginSubmission(harness)
    const signal = harness.store.getState().abortController?.signal
    let messagesAtAbort = 0
    signal?.addEventListener(
      'abort',
      () => {
        messagesAtAbort = harness.store.getState().messages.length
      },
      { once: true },
    )

    harness.store.getState().clearConversation()
    await submission

    expect(messagesAtAbort).toBe(2)
    expect(harness.store.getState()).toMatchObject({
      messages: [],
      draft: '',
      requestPhase: 'idle',
      operationId: null,
      retrySourceText: null,
    })
    expect(harness.store.getState().availability).toBe('ready')
  })

  it.each(['completed', 'failed', 'cancelled'] as const)(
    'keeps a %s operation immutable against late callbacks',
    async (terminal) => {
      const harness = createHarness()
      const { submission } = await beginSubmission(harness)
      const operationId = activeOperation(harness.store.getState())

      if (terminal === 'completed') {
        deliverCompleteStream(harness)
      } else if (terminal === 'failed') {
        harness.pending[0]?.reject(requestError())
      } else {
        harness.store.getState().cancelRequest()
      }
      await submission
      const terminalState = harness.store.getState()
      expect(terminalState.requestPhase).toBe(terminal)

      expect(terminalState.acceptMetadata(operationId, METADATA)).toBe(false)
      expect(
        terminalState.appendChunk(operationId, {
          request_id: METADATA.request_id,
          sequence: 0,
          text: 'late text',
        }),
      ).toBe(false)
      expect(
        terminalState.completeStream(operationId, {
          requestId: METADATA.request_id,
          chunks: 0,
        }),
      ).toBe(false)
      expect(
        terminalState.failRequest(operationId, requestError('late_error')),
      ).toBe(false)
      expect(harness.store.getState()).toBe(terminalState)
    },
  )
})
