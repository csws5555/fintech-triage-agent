import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  API_CLIENT_TIMEOUT_MILLISECONDS,
  createApiClient,
} from '../client'
import { MAX_CHAT_MESSAGE_CHARACTERS } from '../contracts'
import { ApiClientError } from '../errors'
import {
  validChatResponse,
  validErrorResponse,
  validLivenessResponse,
  validReadinessResponse,
  validStreamChunkEvent,
  validStreamDoneEvent,
  validStreamMetadataEvent,
} from './contractFixtures'

const BASE_URL = 'http://127.0.0.1:8000'
const REQUEST_ID = 'server-request-id'

type FetchMock = ReturnType<typeof vi.fn<typeof fetch>>

function sseFrame(eventName: string, payload: unknown): string {
  return `event: ${eventName}\ndata: ${JSON.stringify(payload)}\n\n`
}

function completeSseBody(): ReadableStream<Uint8Array> {
  const source =
    sseFrame('metadata', validStreamMetadataEvent) +
    sseFrame('chunk', validStreamChunkEvent) +
    sseFrame('done', validStreamDoneEvent)
  const encoded = new TextEncoder().encode(source)
  return new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoded)
      controller.close()
    },
  })
}

function jsonResponse(
  payload: unknown,
  options: Readonly<{
    status?: number
    requestId?: string | null
    contentType?: string | null
  }> = {},
): Response {
  const headers = new Headers()
  if (options.requestId !== null) {
    headers.set('X-Request-ID', options.requestId ?? REQUEST_ID)
  }
  if (options.contentType !== null) {
    headers.set(
      'Content-Type',
      options.contentType ?? 'application/json; charset=utf-8',
    )
  }
  return new Response(JSON.stringify(payload), {
    status: options.status ?? 200,
    headers,
  })
}

function streamResponse(
  options: Readonly<{
    requestId?: string | null
    contentType?: string | null
    body?: ReadableStream<Uint8Array> | null
  }> = {},
): Response {
  const headers = new Headers()
  if (options.requestId !== null) {
    headers.set('X-Request-ID', options.requestId ?? REQUEST_ID)
  }
  if (options.contentType !== null) {
    headers.set(
      'Content-Type',
      options.contentType ?? 'text/event-stream; charset=utf-8',
    )
  }
  const body =
    options.body === undefined
      ? completeSseBody()
      : options.body
  return new Response(body, { status: 200, headers })
}

function fetchReturning(response: Response): FetchMock {
  return vi.fn<typeof fetch>().mockResolvedValue(response)
}

function clientFor(fetchImpl: typeof fetch) {
  return createApiClient({ baseUrl: BASE_URL, fetchImpl })
}

function headersFrom(fetchMock: FetchMock): Headers {
  return new Headers(fetchMock.mock.calls[0]?.[1]?.headers)
}

function expectSafeInvalidResponse(error: unknown): void {
  expect(error).toBeInstanceOf(ApiClientError)
  expect(error).toMatchObject({
    kind: 'invalid_response',
    code: 'invalid_api_response',
    message: 'The local support service returned an invalid response.',
    retryable: false,
    status: null,
    requestId: null,
  })
}

afterEach(() => {
  vi.useRealTimers()
})

describe('createApiClient', () => {
  it('normalizes the configured origin without exposing configuration details', async () => {
    const fetchMock = fetchReturning(
      jsonResponse(validLivenessResponse),
    )
    const client = createApiClient({
      baseUrl: `${BASE_URL}/`,
      fetchImpl: fetchMock,
    })

    expect(Object.isFrozen(client)).toBe(true)
    await expect(client.checkLiveness()).resolves.toEqual(
      validLivenessResponse,
    )
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/health/live`,
      expect.any(Object),
    )

    expect(() =>
      createApiClient({
        baseUrl: 'https://user:secret@example.test/private',
        fetchImpl: fetchMock,
      }),
    ).toThrowError(
      expect.objectContaining({
        kind: 'configuration',
        message: 'The local support service is not configured correctly.',
      }),
    )
  })

  it('rejects a non-callable injected fetch implementation safely', () => {
    expect(() =>
      createApiClient({
        baseUrl: BASE_URL,
        fetchImpl: null as unknown as typeof fetch,
      }),
    ).toThrowError(
      expect.objectContaining({
        kind: 'configuration',
        code: 'api_configuration_invalid',
      }),
    )
  })
})

describe('health requests', () => {
  it('checks liveness with the exact endpoint and safe request options', async () => {
    const fetchMock = fetchReturning(
      jsonResponse(validLivenessResponse, {
        contentType: 'Application/JSON; charset=UTF-8',
      }),
    )

    await expect(
      clientFor(fetchMock).checkLiveness(),
    ).resolves.toEqual(validLivenessResponse)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe(`${BASE_URL}/health/live`)
    expect(options).toMatchObject({ method: 'GET', credentials: 'omit' })
    expect(options?.body).toBeUndefined()
    expect(options?.signal).toBeInstanceOf(AbortSignal)
    expect(headersFrom(fetchMock).get('Accept')).toBe('application/json')
    expect(headersFrom(fetchMock).has('Content-Type')).toBe(false)
    expect(headersFrom(fetchMock).has('X-Request-ID')).toBe(false)
  })

  it('accepts ready HTTP 200 readiness', async () => {
    const fetchMock = fetchReturning(jsonResponse(validReadinessResponse))

    await expect(
      clientFor(fetchMock).checkReadiness(),
    ).resolves.toEqual(validReadinessResponse)
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${BASE_URL}/health/ready`)
  })

  it('accepts degraded readiness only with HTTP 503', async () => {
    const degraded = {
      ...validReadinessResponse,
      status: 'degraded',
      components: {
        ...validReadinessResponse.components,
        vector_store: 'unavailable',
      },
    } as const
    const fetchMock = fetchReturning(
      jsonResponse(degraded, { status: 503 }),
    )

    await expect(
      clientFor(fetchMock).checkReadiness(),
    ).resolves.toEqual(degraded)
  })

  it.each([
    [200, { ...validReadinessResponse, status: 'degraded' }],
    [503, validReadinessResponse],
  ])(
    'rejects readiness payloads inconsistent with HTTP %i',
    async (status, payload) => {
      const promise = clientFor(
        fetchReturning(jsonResponse(payload, { status })),
      ).checkReadiness()

      await expect(promise).rejects.toSatisfy((error: unknown) => {
        expectSafeInvalidResponse(error)
        return true
      })
    },
  )
})

describe('chat request construction', () => {
  it('trims the message and sends only the supported JSON field', async () => {
    const fetchMock = fetchReturning(jsonResponse(validChatResponse))

    await expect(
      clientFor(fetchMock).sendChatMessage(
        ' \tKeep   internal spacing.\n ',
      ),
    ).resolves.toEqual(validChatResponse)

    const [url, options] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe(`${BASE_URL}/api/v1/chat`)
    expect(options).toMatchObject({ method: 'POST', credentials: 'omit' })
    expect(options?.body).toBe(
      JSON.stringify({ message: 'Keep   internal spacing.' }),
    )
    expect(Object.keys(JSON.parse(String(options?.body)))).toEqual([
      'message',
    ])
    expect(headersFrom(fetchMock).get('Accept')).toBe('application/json')
    expect(headersFrom(fetchMock).get('Content-Type')).toBe(
      'application/json',
    )
    expect(headersFrom(fetchMock).has('X-Request-ID')).toBe(false)
  })

  it.each([
    ['', 'empty_message'],
    [' \t\n ', 'empty_message'],
    ['x'.repeat(MAX_CHAT_MESSAGE_CHARACTERS + 1), 'message_too_long'],
  ])('rejects invalid message input before fetch', async (message, code) => {
    const fetchMock = fetchReturning(jsonResponse(validChatResponse))

    await expect(
      clientFor(fetchMock).sendChatMessage(message),
    ).rejects.toMatchObject({
      kind: 'validation',
      code,
      retryable: false,
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('fails closed for a non-string value passed at runtime', async () => {
    const fetchMock = fetchReturning(jsonResponse(validChatResponse))

    await expect(
      clientFor(fetchMock).sendChatMessage(
        123 as unknown as string,
      ),
    ).rejects.toMatchObject({
      kind: 'validation',
      code: 'invalid_message',
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('still surfaces the backend-authoritative HTTP 413 envelope', async () => {
    const payload = {
      ...validErrorResponse,
      error: {
        code: 'payload_too_large',
        message: 'The request body is too large.',
        retryable: false,
      },
    }
    const fetchMock = fetchReturning(
      jsonResponse(payload, { status: 413 }),
    )

    await expect(
      clientFor(fetchMock).sendChatMessage('界'.repeat(1_500)),
    ).rejects.toMatchObject({
      kind: 'http',
      code: 'payload_too_large',
      status: 413,
      requestId: REQUEST_ID,
    })
  })
})

describe('stream transport request', () => {
  it('consumes the POST SSE response through validated event handlers', async () => {
    const response = streamResponse()
    const fetchMock = fetchReturning(response)
    const onMetadata = vi.fn()
    const onChunk = vi.fn()

    const completed = await clientFor(fetchMock).streamChatMessage(
      ' My card was stolen. ',
      { onMetadata, onChunk },
    )

    expect(Object.isFrozen(completed)).toBe(true)
    expect(completed).toEqual({
      requestId: REQUEST_ID,
      chunks: 1,
    })
    expect(onMetadata).toHaveBeenCalledWith(validStreamMetadataEvent)
    expect(onChunk).toHaveBeenCalledWith(validStreamChunkEvent)
    const [url, options] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe(`${BASE_URL}/api/v1/chat/stream`)
    expect(options).toMatchObject({ method: 'POST', credentials: 'omit' })
    expect(options?.body).toBe(
      JSON.stringify({ message: 'My card was stolen.' }),
    )
    expect(headersFrom(fetchMock).get('Accept')).toBe('text/event-stream')
    expect(headersFrom(fetchMock).get('Content-Type')).toBe(
      'application/json',
    )
  })

  it('rejects a successful stream without a response body', async () => {
    const promise = clientFor(
      fetchReturning(streamResponse({ body: null })),
    ).streamChatMessage('Customer message', {
      onMetadata: vi.fn(),
      onChunk: vi.fn(),
    })

    await expect(promise).rejects.toSatisfy((error: unknown) => {
      expectSafeInvalidResponse(error)
      return true
    })
  })

  it('uses the normal JSON error contract for pre-header stream failures', async () => {
    const fetchMock = fetchReturning(
      jsonResponse(validErrorResponse, { status: 422 }),
    )

    await expect(
      clientFor(fetchMock).streamChatMessage('Customer message', {
        onMetadata: vi.fn(),
        onChunk: vi.fn(),
      }),
    ).rejects.toMatchObject({
      kind: 'http',
      code: 'invalid_request',
      status: 422,
      requestId: REQUEST_ID,
    })
  })
})

describe('HTTP and response validation', () => {
  it.each([
    [413, 'payload_too_large', false],
    [415, 'unsupported_media_type', false],
    [422, 'invalid_request', false],
    [500, 'internal_error', false],
    [503, 'service_busy', true],
    [503, 'classifier_unavailable', true],
    [503, 'support_service_unavailable', true],
    [504, 'request_timeout', true],
    [404, 'not_found', false],
    [405, 'method_not_allowed', false],
  ])(
    'normalizes HTTP %i / %s and preserves retryability',
    async (status, code, retryable) => {
      const payload = {
        ...validErrorResponse,
        error: {
          code,
          message: `Approved ${code} message.`,
          retryable,
        },
      }
      const promise = clientFor(
        fetchReturning(jsonResponse(payload, { status })),
      ).sendChatMessage('Customer message')

      await expect(promise).rejects.toMatchObject({
        kind: 'http',
        code,
        message: `Approved ${code} message.`,
        retryable,
        status,
        requestId: REQUEST_ID,
      })
    },
  )

  it.each([
    ['liveness', () => validLivenessResponse, 'application/problem+json'],
    ['readiness', () => validReadinessResponse, 'text/plain'],
    ['chat', () => validChatResponse, 'text/html'],
  ])(
    'rejects the wrong %s response content type',
    async (method, payloadFactory, contentType) => {
      const client = clientFor(
        fetchReturning(
          jsonResponse(payloadFactory(), { contentType }),
        ),
      )
      const promise =
        method === 'liveness'
          ? client.checkLiveness()
          : method === 'readiness'
            ? client.checkReadiness()
            : client.sendChatMessage('Customer message')

      await expect(promise).rejects.toSatisfy((error: unknown) => {
        expectSafeInvalidResponse(error)
        return true
      })
    },
  )

  it('rejects the wrong successful stream content type', async () => {
    const promise = clientFor(
      fetchReturning(streamResponse({ contentType: 'application/json' })),
    ).streamChatMessage('Customer message', {
      onMetadata: vi.fn(),
      onChunk: vi.fn(),
    })

    await expect(promise).rejects.toSatisfy((error: unknown) => {
      expectSafeInvalidResponse(error)
      return true
    })
  })

  it.each(['liveness', 'readiness', 'chat', 'stream'])(
    'rejects a missing request ID for %s',
    async (method) => {
      const response =
        method === 'stream'
          ? streamResponse({ requestId: null })
          : jsonResponse(
              method === 'liveness'
                ? validLivenessResponse
                : method === 'readiness'
                  ? validReadinessResponse
                  : validChatResponse,
              { requestId: null },
            )
      const client = clientFor(fetchReturning(response))
      const promise =
        method === 'liveness'
          ? client.checkLiveness()
          : method === 'readiness'
            ? client.checkReadiness()
            : method === 'chat'
              ? client.sendChatMessage('Customer message')
              : client.streamChatMessage('Customer message', {
                  onMetadata: vi.fn(),
                  onChunk: vi.fn(),
                })

      await expect(promise).rejects.toSatisfy((error: unknown) => {
        expectSafeInvalidResponse(error)
        return true
      })
    },
  )

  it.each([
    ['chat success', 200, validChatResponse],
    ['HTTP error', 422, validErrorResponse],
  ])(
    'rejects a header/body request ID mismatch for %s',
    async (_label, status, payload) => {
      const promise = clientFor(
        fetchReturning(
          jsonResponse(payload, {
            status,
            requestId: 'different-request-id',
          }),
        ),
      ).sendChatMessage('Customer message')

      await expect(promise).rejects.toSatisfy((error: unknown) => {
        expectSafeInvalidResponse(error)
        return true
      })
    },
  )

  it.each([
    ['liveness', { ...validLivenessResponse, internal_path: 'private' }],
    ['readiness', { ...validReadinessResponse, diagnostics: 'private' }],
    ['chat', { ...validChatResponse, reason_code: 'private' }],
  ])('rejects malformed or extra-field %s payloads', async (method, payload) => {
    const client = clientFor(fetchReturning(jsonResponse(payload)))
    const promise =
      method === 'liveness'
        ? client.checkLiveness()
        : method === 'readiness'
          ? client.checkReadiness()
          : client.sendChatMessage('Customer message')

    await expect(promise).rejects.toSatisfy((error: unknown) => {
      expectSafeInvalidResponse(error)
      return true
    })
  })

  it('rejects malformed JSON without exposing the raw body', async () => {
    const response = new Response('private traceback and local path', {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'X-Request-ID': REQUEST_ID,
      },
    })

    let captured: unknown
    try {
      await clientFor(fetchReturning(response)).checkLiveness()
    } catch (error: unknown) {
      captured = error
    }

    expectSafeInvalidResponse(captured)
    expect(String(captured)).not.toContain('private traceback')
    expect(String(captured)).not.toContain('local path')
  })

  it('rejects a malformed error envelope instead of exposing its body', async () => {
    const response = jsonResponse(
      {
        request_id: REQUEST_ID,
        error: {
          code: 'internal_error',
          message: 'private exception detail',
          retryable: false,
          stack: 'private stack',
        },
      },
      { status: 500 },
    )

    let captured: unknown
    try {
      await clientFor(fetchReturning(response)).sendChatMessage(
        'Customer message',
      )
    } catch (error: unknown) {
      captured = error
    }

    expectSafeInvalidResponse(captured)
    expect(String(captured)).not.toContain('private')
  })
})

describe('network, timeout, and cancellation normalization', () => {
  it('normalizes a network or CORS failure without exposing exception details', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValue(
        new TypeError('Failed to fetch https://private.invalid/secret'),
      )

    let captured: unknown
    try {
      await clientFor(fetchMock).checkLiveness()
    } catch (error: unknown) {
      captured = error
    }

    expect(captured).toBeInstanceOf(ApiClientError)
    expect(captured).toMatchObject({
      kind: 'network',
      code: 'api_unreachable',
      message: 'The local support service could not be reached.',
      retryable: true,
    })
    expect(String(captured)).not.toContain('private.invalid')
  })

  it('aborts and normalizes the 100-second client timeout', async () => {
    vi.useFakeTimers()
    let observedSignal: AbortSignal | null = null
    const fetchMock = vi.fn<typeof fetch>((_input, options) => {
      observedSignal = options?.signal ?? null
      return new Promise<Response>((_resolve, reject) => {
        observedSignal?.addEventListener(
          'abort',
          () => reject(new DOMException('private abort', 'AbortError')),
          { once: true },
        )
      })
    })
    const promise = clientFor(fetchMock).checkLiveness()
    const rejection = expect(promise).rejects.toMatchObject({
      kind: 'timeout',
      code: 'client_timeout',
      retryable: true,
    })

    await vi.advanceTimersByTimeAsync(API_CLIENT_TIMEOUT_MILLISECONDS)

    await rejection
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true)
  })

  it('keeps the 100-second timeout active while reading the stream body', async () => {
    vi.useFakeTimers()
    const cancel = vi.fn()
    const body = new ReadableStream<Uint8Array>({ cancel })
    const promise = clientFor(
      fetchReturning(streamResponse({ body })),
    ).streamChatMessage(
      'Customer message',
      { onMetadata: vi.fn(), onChunk: vi.fn() },
    )
    const rejection = expect(promise).rejects.toMatchObject({
      kind: 'timeout',
      code: 'client_timeout',
      retryable: true,
    })

    await vi.advanceTimersByTimeAsync(API_CLIENT_TIMEOUT_MILLISECONDS)

    await rejection
    expect(cancel).toHaveBeenCalledTimes(1)
  })

  it('composes caller cancellation with the internal request signal', async () => {
    const callerController = new AbortController()
    let observedSignal: AbortSignal | null = null
    const fetchMock = vi.fn<typeof fetch>((_input, options) => {
      observedSignal = options?.signal ?? null
      return new Promise<Response>((_resolve, reject) => {
        observedSignal?.addEventListener(
          'abort',
          () => reject(new DOMException('private abort', 'AbortError')),
          { once: true },
        )
      })
    })
    const promise = clientFor(fetchMock).sendChatMessage(
      'Customer message',
      { signal: callerController.signal },
    )
    const rejection = expect(promise).rejects.toMatchObject({
      kind: 'cancelled',
      code: 'request_cancelled',
      retryable: true,
    })

    callerController.abort('private caller reason')

    await rejection
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true)
  })

  it('keeps caller cancellation active while reading the stream body', async () => {
    const callerController = new AbortController()
    const cancel = vi.fn()
    const body = new ReadableStream<Uint8Array>({ cancel })
    const promise = clientFor(
      fetchReturning(streamResponse({ body })),
    ).streamChatMessage(
      'Customer message',
      { onMetadata: vi.fn(), onChunk: vi.fn() },
      { signal: callerController.signal },
    )
    const rejection = expect(promise).rejects.toMatchObject({
      kind: 'cancelled',
      code: 'request_cancelled',
      retryable: true,
    })

    await Promise.resolve()
    await Promise.resolve()
    callerController.abort('private reason')

    await rejection
    expect(cancel).toHaveBeenCalledTimes(1)
  })

  it('does not call fetch when the caller signal is already aborted', async () => {
    const callerController = new AbortController()
    callerController.abort()
    const fetchMock = fetchReturning(jsonResponse(validLivenessResponse))

    await expect(
      clientFor(fetchMock).checkLiveness({
        signal: callerController.signal,
      }),
    ).rejects.toMatchObject({
      kind: 'cancelled',
      code: 'request_cancelled',
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
