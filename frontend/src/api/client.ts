import {
  isChatResponse,
  isErrorResponse,
  isLivenessResponse,
  isReadinessResponse,
} from './contractGuards'
import { loadApiConfig, type ApiConfig } from './config'
import {
  MAX_CHAT_MESSAGE_CHARACTERS,
  type ChatResponse,
  type LivenessResponse,
  type ReadinessResponse,
} from './contracts'
import { ApiClientError } from './errors'
import {
  parseSseStream,
  type CompletedStream,
  type StreamEventHandlers,
} from './sseParser'

export const API_CLIENT_TIMEOUT_MILLISECONDS = 100_000

const JSON_MEDIA_TYPE = 'application/json'
const SSE_MEDIA_TYPE = 'text/event-stream'
const REQUEST_ID_HEADER = 'X-Request-ID'

export type ApiRequestOptions = Readonly<{
  signal?: AbortSignal
}>

export type ApiClient = Readonly<{
  checkLiveness(options?: ApiRequestOptions): Promise<LivenessResponse>
  checkReadiness(options?: ApiRequestOptions): Promise<ReadinessResponse>
  sendChatMessage(
    message: string,
    options?: ApiRequestOptions,
  ): Promise<ChatResponse>
  streamChatMessage(
    message: string,
    handlers: StreamEventHandlers,
    options?: ApiRequestOptions,
  ): Promise<CompletedStream>
}>

export type CreateApiClientOptions = Readonly<{
  baseUrl: string
  fetchImpl?: typeof fetch
}>

type AbortSource = 'caller' | 'timeout'

function configurationError(): ApiClientError {
  return new ApiClientError({
    kind: 'configuration',
    code: 'api_configuration_invalid',
    message: 'The local support service is not configured correctly.',
    retryable: false,
  })
}

function validationError(code: string, message: string): ApiClientError {
  return new ApiClientError({
    kind: 'validation',
    code,
    message,
    retryable: false,
  })
}

function invalidResponseError(): ApiClientError {
  return new ApiClientError({
    kind: 'invalid_response',
    code: 'invalid_api_response',
    message: 'The local support service returned an invalid response.',
    retryable: false,
  })
}

function networkError(): ApiClientError {
  return new ApiClientError({
    kind: 'network',
    code: 'api_unreachable',
    message: 'The local support service could not be reached.',
    retryable: true,
  })
}

function timeoutError(): ApiClientError {
  return new ApiClientError({
    kind: 'timeout',
    code: 'client_timeout',
    message: 'The request timed out locally. Please try again.',
    retryable: true,
  })
}

function cancellationError(): ApiClientError {
  return new ApiClientError({
    kind: 'cancelled',
    code: 'request_cancelled',
    message: 'The request was cancelled.',
    retryable: true,
  })
}

function normalizeMessage(message: string): string {
  if (typeof message !== 'string') {
    throw validationError(
      'invalid_message',
      'Enter a valid message before sending.',
    )
  }

  const normalized = message.trim()
  if (!normalized) {
    throw validationError(
      'empty_message',
      'Enter a message before sending.',
    )
  }
  if (normalized.length > MAX_CHAT_MESSAGE_CHARACTERS) {
    throw validationError(
      'message_too_long',
      `Messages must be ${MAX_CHAT_MESSAGE_CHARACTERS.toLocaleString(
        'en-US',
      )} characters or fewer.`,
    )
  }
  return normalized
}

function mediaType(response: Response): string | null {
  const contentType = response.headers.get('Content-Type')
  if (contentType === null) {
    return null
  }
  return contentType.split(';', 1)[0]?.trim().toLowerCase() ?? null
}

function requireMediaType(response: Response, expected: string): void {
  if (mediaType(response) !== expected) {
    throw invalidResponseError()
  }
}

function requireRequestId(response: Response): string {
  const requestId = response.headers.get(REQUEST_ID_HEADER)?.trim()
  if (!requestId) {
    throw invalidResponseError()
  }
  return requestId
}

function requireMatchingRequestId(
  responseRequestId: string,
  payloadRequestId: string,
): void {
  if (payloadRequestId !== responseRequestId) {
    throw invalidResponseError()
  }
}

async function readJson(response: Response): Promise<unknown> {
  requireMediaType(response, JSON_MEDIA_TYPE)
  try {
    return await response.json()
  } catch {
    throw invalidResponseError()
  }
}

async function throwHttpError(
  response: Response,
  requestId: string,
): Promise<never> {
  const payload = await readJson(response)
  if (!isErrorResponse(payload)) {
    throw invalidResponseError()
  }
  requireMatchingRequestId(requestId, payload.request_id)
  throw new ApiClientError({
    kind: 'http',
    code: payload.error.code,
    message: payload.error.message,
    retryable: payload.error.retryable,
    status: response.status,
    requestId,
  })
}

async function withRequestControls<Result>(
  operation: (signal: AbortSignal) => Promise<Result>,
  callerSignal?: AbortSignal,
): Promise<Result> {
  if (callerSignal?.aborted) {
    throw cancellationError()
  }

  const requestController = new AbortController()
  let abortSource: AbortSource | undefined
  const abortFromCaller = () => {
    if (abortSource === undefined) {
      abortSource = 'caller'
      requestController.abort()
    }
  }
  callerSignal?.addEventListener('abort', abortFromCaller, { once: true })
  const timeoutId = globalThis.setTimeout(() => {
    if (abortSource === undefined) {
      abortSource = 'timeout'
      requestController.abort()
    }
  }, API_CLIENT_TIMEOUT_MILLISECONDS)

  try {
    return await operation(requestController.signal)
  } catch (error: unknown) {
    if (abortSource === 'caller') {
      throw cancellationError()
    }
    if (abortSource === 'timeout') {
      throw timeoutError()
    }
    if (error instanceof ApiClientError) {
      throw error
    }
    throw networkError()
  } finally {
    globalThis.clearTimeout(timeoutId)
    callerSignal?.removeEventListener('abort', abortFromCaller)
  }
}

function jsonHeaders(): Headers {
  return new Headers({ Accept: JSON_MEDIA_TYPE })
}

function chatHeaders(accept: string): Headers {
  return new Headers({
    Accept: accept,
    'Content-Type': JSON_MEDIA_TYPE,
  })
}

function requestOptions(
  method: 'GET' | 'POST',
  headers: Headers,
  signal: AbortSignal,
  body?: string,
): RequestInit {
  return {
    method,
    headers,
    credentials: 'omit',
    signal,
    ...(body === undefined ? {} : { body }),
  }
}

function validatedConfiguration(baseUrl: string): ApiConfig {
  if (typeof baseUrl !== 'string') {
    throw configurationError()
  }
  try {
    return loadApiConfig({ VITE_API_BASE_URL: baseUrl })
  } catch {
    throw configurationError()
  }
}

export function createApiClient({
  baseUrl,
  fetchImpl = globalThis.fetch,
}: CreateApiClientOptions): ApiClient {
  const configuration = validatedConfiguration(baseUrl)
  if (typeof fetchImpl !== 'function') {
    throw configurationError()
  }

  async function checkLiveness(
    options: ApiRequestOptions = {},
  ): Promise<LivenessResponse> {
    return withRequestControls(async (signal) => {
      const response = await fetchImpl(
        configuration.livenessUrl,
        requestOptions('GET', jsonHeaders(), signal),
      )
      const requestId = requireRequestId(response)
      if (response.status !== 200) {
        return throwHttpError(response, requestId)
      }

      const payload = await readJson(response)
      if (!isLivenessResponse(payload)) {
        throw invalidResponseError()
      }
      return payload
    }, options.signal)
  }

  async function checkReadiness(
    options: ApiRequestOptions = {},
  ): Promise<ReadinessResponse> {
    return withRequestControls(async (signal) => {
      const response = await fetchImpl(
        configuration.readinessUrl,
        requestOptions('GET', jsonHeaders(), signal),
      )
      const requestId = requireRequestId(response)
      if (response.status !== 200 && response.status !== 503) {
        return throwHttpError(response, requestId)
      }

      const payload = await readJson(response)
      if (!isReadinessResponse(payload)) {
        throw invalidResponseError()
      }
      if (
        (response.status === 200 && payload.status !== 'ready') ||
        (response.status === 503 && payload.status !== 'degraded')
      ) {
        throw invalidResponseError()
      }
      return payload
    }, options.signal)
  }

  async function sendChatMessage(
    message: string,
    options: ApiRequestOptions = {},
  ): Promise<ChatResponse> {
    const normalizedMessage = normalizeMessage(message)
    const body = JSON.stringify({ message: normalizedMessage })

    return withRequestControls(async (signal) => {
      const response = await fetchImpl(
        configuration.chatUrl,
        requestOptions(
          'POST',
          chatHeaders(JSON_MEDIA_TYPE),
          signal,
          body,
        ),
      )
      const requestId = requireRequestId(response)
      if (response.status !== 200) {
        return throwHttpError(response, requestId)
      }

      const payload = await readJson(response)
      if (!isChatResponse(payload)) {
        throw invalidResponseError()
      }
      requireMatchingRequestId(requestId, payload.request_id)
      return payload
    }, options.signal)
  }

  async function streamChatMessage(
    message: string,
    handlers: StreamEventHandlers,
    options: ApiRequestOptions = {},
  ): Promise<CompletedStream> {
    const normalizedMessage = normalizeMessage(message)
    const body = JSON.stringify({ message: normalizedMessage })

    return withRequestControls(async (signal) => {
      const response = await fetchImpl(
        configuration.chatStreamUrl,
        requestOptions(
          'POST',
          chatHeaders(SSE_MEDIA_TYPE),
          signal,
          body,
        ),
      )
      const requestId = requireRequestId(response)
      if (response.status !== 200) {
        return throwHttpError(response, requestId)
      }

      requireMediaType(response, SSE_MEDIA_TYPE)
      if (response.body === null) {
        throw invalidResponseError()
      }
      return parseSseStream({
        body: response.body,
        requestId,
        handlers,
        signal,
      })
    }, options.signal)
  }

  return Object.freeze({
    checkLiveness,
    checkReadiness,
    sendChatMessage,
    streamChatMessage,
  })
}
