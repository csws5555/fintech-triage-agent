import {
  isSseEventName,
  isStreamChunkEvent,
  isStreamDoneEvent,
  isStreamErrorEvent,
  isStreamMetadataEvent,
} from './contractGuards'
import type {
  StreamChunkEvent,
  StreamDoneEvent,
  StreamErrorEvent,
  StreamMetadataEvent,
} from './contracts'
import { ApiClientError } from './errors'

export type StreamEventHandlers = Readonly<{
  onMetadata(metadata: StreamMetadataEvent): void
  onChunk(chunk: StreamChunkEvent): void
}>

export type CompletedStream = Readonly<{
  requestId: string
  chunks: number
}>

export type ParseSseStreamOptions = Readonly<{
  body: ReadableStream<Uint8Array>
  requestId: string
  handlers: StreamEventHandlers
  signal?: AbortSignal
}>

type TerminalEvent =
  | Readonly<{ kind: 'done'; payload: StreamDoneEvent }>
  | Readonly<{ kind: 'error'; payload: StreamErrorEvent }>

function invalidStreamError(): ApiClientError {
  return new ApiClientError({
    kind: 'invalid_response',
    code: 'invalid_stream_response',
    message: 'The local support service returned an invalid response stream.',
    retryable: false,
  })
}

function interruptedStreamError(requestId?: string): ApiClientError {
  return new ApiClientError({
    kind: 'network',
    code: 'stream_interrupted',
    message: 'The response stream was interrupted.',
    retryable: true,
    ...(requestId === undefined ? {} : { requestId }),
  })
}

function cancelledStreamError(): ApiClientError {
  return new ApiClientError({
    kind: 'cancelled',
    code: 'request_cancelled',
    message: 'The request was cancelled.',
    retryable: true,
  })
}

function serverStreamError(payload: StreamErrorEvent): ApiClientError {
  return new ApiClientError({
    kind: 'http',
    code: payload.error.code,
    message: payload.error.message,
    retryable: payload.error.retryable,
    requestId: payload.request_id,
  })
}

function requireHandlers(handlers: StreamEventHandlers): void {
  if (
    typeof handlers !== 'object' ||
    handlers === null ||
    typeof handlers.onMetadata !== 'function' ||
    typeof handlers.onChunk !== 'function'
  ) {
    throw invalidStreamError()
  }
}

function requireRequestId(
  expectedRequestId: string,
  payloadRequestId: string,
): void {
  if (payloadRequestId !== expectedRequestId) {
    throw invalidStreamError()
  }
}

function fieldValue(line: string, fieldName: string): string {
  const separator = line.indexOf(':')
  const actualField = separator === -1 ? line : line.slice(0, separator)
  if (actualField !== fieldName) {
    throw invalidStreamError()
  }

  const value = separator === -1 ? '' : line.slice(separator + 1)
  return value.startsWith(' ') ? value.slice(1) : value
}

function parseFrame(lines: readonly string[]): {
  eventName: string
  payload: unknown
} | null {
  const protocolLines = lines.filter((line) => !line.startsWith(':'))
  if (protocolLines.length === 0) {
    return null
  }

  const eventLines = protocolLines.filter(
    (line) => line === 'event' || line.startsWith('event:'),
  )
  const dataLines = protocolLines.filter(
    (line) => line === 'data' || line.startsWith('data:'),
  )
  if (
    eventLines.length !== 1 ||
    dataLines.length !== 1 ||
    protocolLines.length !== 2
  ) {
    throw invalidStreamError()
  }

  const eventName = fieldValue(eventLines[0] ?? '', 'event')
  if (!isSseEventName(eventName)) {
    throw invalidStreamError()
  }

  const rawData = fieldValue(dataLines[0] ?? '', 'data')
  let payload: unknown
  try {
    payload = JSON.parse(rawData)
  } catch {
    throw invalidStreamError()
  }
  return { eventName, payload }
}

/** Parse one validated buffered SSE response without exposing raw frames. */
export async function parseSseStream({
  body,
  requestId,
  handlers,
  signal,
}: ParseSseStreamOptions): Promise<CompletedStream> {
  if (
    !(body instanceof ReadableStream) ||
    typeof requestId !== 'string' ||
    requestId.length === 0
  ) {
    throw invalidStreamError()
  }
  requireHandlers(handlers)
  if (signal?.aborted) {
    throw cancelledStreamError()
  }

  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8', { fatal: true })
  let textBuffer = ''
  let frameLines: string[] = []
  let metadataSeen = false
  let expectedSequence = 0
  let terminalEvent: TerminalEvent | null = null
  let aborted = false

  const abortReading = () => {
    aborted = true
    void reader.cancel().catch(() => undefined)
  }
  signal?.addEventListener('abort', abortReading, { once: true })

  const dispatchFrame = (lines: readonly string[]) => {
    const parsed = parseFrame(lines)
    if (parsed === null) {
      return
    }
    if (terminalEvent !== null) {
      throw invalidStreamError()
    }

    const { eventName, payload } = parsed
    if (eventName === 'metadata') {
      if (metadataSeen || !isStreamMetadataEvent(payload)) {
        throw invalidStreamError()
      }
      requireRequestId(requestId, payload.request_id)
      metadataSeen = true
      handlers.onMetadata(payload)
      return
    }

    if (!metadataSeen) {
      throw invalidStreamError()
    }

    if (eventName === 'chunk') {
      if (
        !isStreamChunkEvent(payload) ||
        payload.sequence !== expectedSequence
      ) {
        throw invalidStreamError()
      }
      requireRequestId(requestId, payload.request_id)
      expectedSequence += 1
      handlers.onChunk(payload)
      return
    }

    if (eventName === 'done') {
      if (
        !isStreamDoneEvent(payload) ||
        payload.chunks !== expectedSequence
      ) {
        throw invalidStreamError()
      }
      requireRequestId(requestId, payload.request_id)
      terminalEvent = { kind: 'done', payload }
      return
    }

    if (!isStreamErrorEvent(payload)) {
      throw invalidStreamError()
    }
    requireRequestId(requestId, payload.request_id)
    terminalEvent = { kind: 'error', payload }
  }

  const consumeCompleteLines = (atEndOfStream: boolean) => {
    let offset = 0
    while (offset < textBuffer.length) {
      let lineEnd = offset
      while (
        lineEnd < textBuffer.length &&
        textBuffer[lineEnd] !== '\n' &&
        textBuffer[lineEnd] !== '\r'
      ) {
        lineEnd += 1
      }
      if (lineEnd === textBuffer.length) {
        break
      }

      const ending = textBuffer[lineEnd]
      if (
        ending === '\r' &&
        lineEnd + 1 === textBuffer.length &&
        !atEndOfStream
      ) {
        break
      }

      const line = textBuffer.slice(offset, lineEnd)
      const endingLength =
        ending === '\r' && textBuffer[lineEnd + 1] === '\n' ? 2 : 1
      offset = lineEnd + endingLength

      if (line.length === 0) {
        dispatchFrame(frameLines)
        frameLines = []
      } else {
        frameLines.push(line)
      }
    }
    textBuffer = textBuffer.slice(offset)
  }

  try {
    while (true) {
      let result: ReadableStreamReadResult<Uint8Array>
      try {
        result = await reader.read()
      } catch {
        if (aborted || signal?.aborted) {
          throw cancelledStreamError()
        }
        throw interruptedStreamError(requestId)
      }

      if (aborted || signal?.aborted) {
        throw cancelledStreamError()
      }
      if (result.done) {
        try {
          textBuffer += decoder.decode()
        } catch {
          throw invalidStreamError()
        }
        consumeCompleteLines(true)
        break
      }

      if (!(result.value instanceof Uint8Array)) {
        throw invalidStreamError()
      }
      try {
        textBuffer += decoder.decode(result.value, { stream: true })
      } catch {
        throw invalidStreamError()
      }
      consumeCompleteLines(false)
    }

    if (textBuffer.length > 0 || frameLines.length > 0) {
      throw invalidStreamError()
    }
    const completedTerminal = terminalEvent as TerminalEvent | null
    if (completedTerminal === null) {
      throw interruptedStreamError(requestId)
    }
    if (completedTerminal.kind === 'error') {
      throw serverStreamError(completedTerminal.payload)
    }
    return Object.freeze({
      requestId,
      chunks: completedTerminal.payload.chunks,
    })
  } catch (error: unknown) {
    if (!aborted) {
      await reader.cancel().catch(() => undefined)
    }
    throw error
  } finally {
    signal?.removeEventListener('abort', abortReading)
    reader.releaseLock()
  }
}
