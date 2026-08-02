import { describe, expect, it, vi } from 'vitest'

import { ApiClientError } from '../errors'
import { parseSseStream } from '../sseParser'
import {
  validStreamChunkEvent,
  validStreamDoneEvent,
  validStreamErrorEvent,
  validStreamMetadataEvent,
} from './contractFixtures'

const REQUEST_ID = validStreamMetadataEvent.request_id

function frame(
  eventName: string,
  payload: unknown,
  lineEnding = '\n',
): string {
  return [
    `event: ${eventName}`,
    `data: ${JSON.stringify(payload)}`,
    '',
    '',
  ].join(lineEnding)
}

function completeStream(lineEnding = '\n'): string {
  return (
    frame('metadata', validStreamMetadataEvent, lineEnding) +
    frame('chunk', validStreamChunkEvent, lineEnding) +
    frame('done', validStreamDoneEvent, lineEnding)
  )
}

function byteStream(chunks: readonly Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk)
      }
      controller.close()
    },
  })
}

function textStream(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return byteStream(chunks.map((chunk) => encoder.encode(chunk)))
}

function parserHarness(body: ReadableStream<Uint8Array>) {
  const metadata: unknown[] = []
  const chunks: unknown[] = []
  const promise = parseSseStream({
    body,
    requestId: REQUEST_ID,
    handlers: {
      onMetadata(value) {
        metadata.push(value)
      },
      onChunk(value) {
        chunks.push(value)
      },
    },
  })
  return { chunks, metadata, promise }
}

function expectInvalidStream(error: unknown): boolean {
  expect(error).toBeInstanceOf(ApiClientError)
  expect(error).toMatchObject({
    kind: 'invalid_response',
    code: 'invalid_stream_response',
    retryable: false,
  })
  return true
}

describe('parseSseStream framing and decoding', () => {
  it.each([
    ['LF', '\n'],
    ['CRLF', '\r\n'],
    ['CR', '\r'],
  ])('parses one complete event per read with %s endings', async (_name, ending) => {
    const harness = parserHarness(
      textStream(
        frame('metadata', validStreamMetadataEvent, ending),
        frame('chunk', validStreamChunkEvent, ending),
        frame('done', validStreamDoneEvent, ending),
      ),
    )

    await expect(harness.promise).resolves.toEqual({
      requestId: REQUEST_ID,
      chunks: 1,
    })
    expect(harness.metadata).toEqual([validStreamMetadataEvent])
    expect(harness.chunks).toEqual([validStreamChunkEvent])
  })

  it('retains an event divided across arbitrary network reads', async () => {
    const source = completeStream()
    const harness = parserHarness(
      textStream(...Array.from(source)),
    )

    await expect(harness.promise).resolves.toEqual({
      requestId: REQUEST_ID,
      chunks: 1,
    })
    expect(harness.chunks).toEqual([validStreamChunkEvent])
  })

  it('parses several frames delivered in one network read', async () => {
    const harness = parserHarness(textStream(completeStream()))

    await expect(harness.promise).resolves.toEqual({
      requestId: REQUEST_ID,
      chunks: 1,
    })
    expect(harness.metadata).toHaveLength(1)
    expect(harness.chunks).toHaveLength(1)
  })

  it('preserves Unicode divided across byte boundaries', async () => {
    const unicodeChunk = {
      ...validStreamChunkEvent,
      text: 'Card café 💳 安全 guidance',
    }
    const source =
      frame('metadata', validStreamMetadataEvent) +
      frame('chunk', unicodeChunk) +
      frame('done', validStreamDoneEvent)
    const encoded = new TextEncoder().encode(source)
    const splitBytes = Array.from(encoded, (value) =>
      Uint8Array.of(value),
    )
    const harness = parserHarness(byteStream(splitBytes))

    await expect(harness.promise).resolves.toEqual({
      requestId: REQUEST_ID,
      chunks: 1,
    })
    expect(harness.chunks).toEqual([unicodeChunk])
    expect(JSON.stringify(harness.chunks)).not.toContain('�')
  })

  it('ignores comment-only heartbeat frames and comment lines', async () => {
    const source =
      ': keep-alive\n\n' +
      ': comment\n' +
      frame('metadata', validStreamMetadataEvent) +
      frame('done', { ...validStreamDoneEvent, chunks: 0 })
    const harness = parserHarness(textStream(source))

    await expect(harness.promise).resolves.toEqual({
      requestId: REQUEST_ID,
      chunks: 0,
    })
    expect(harness.metadata).toEqual([validStreamMetadataEvent])
    expect(harness.chunks).toEqual([])
  })
})

describe('parseSseStream protocol validation', () => {
  it.each([
    ['unknown event', 'event: token\ndata: {}\n\n'],
    ['unexpected field', 'event: metadata\nid: private\ndata: {}\n\n'],
    [
      'duplicate event declaration',
      'event: metadata\nevent: metadata\ndata: {}\n\n',
    ],
    ['duplicate data declaration', 'event: metadata\ndata: {}\ndata: {}\n\n'],
    ['missing event', 'data: {}\n\n'],
    ['missing data', 'event: metadata\n\n'],
    ['malformed JSON', 'event: metadata\ndata: {private\n\n'],
  ])('rejects an %s', async (_name, invalidFrame) => {
    const { promise } = parserHarness(textStream(invalidFrame))

    await expect(promise).rejects.toSatisfy(expectInvalidStream)
  })

  it.each([
    [
      'metadata with an extra field',
      'metadata',
      { ...validStreamMetadataEvent, reason_code: 'private' },
    ],
    [
      'chunk with an extra field',
      'chunk',
      { ...validStreamChunkEvent, document_id: 'private' },
    ],
    [
      'done with an extra field',
      'done',
      { ...validStreamDoneEvent, prompt: 'private' },
    ],
    [
      'error with an extra field',
      'error',
      { ...validStreamErrorEvent, traceback: 'private' },
    ],
  ])('rejects %s', async (_name, eventName, payload) => {
    const prefix =
      eventName === 'metadata'
        ? ''
        : frame('metadata', validStreamMetadataEvent)
    const { promise } = parserHarness(
      textStream(prefix + frame(eventName, payload)),
    )

    await expect(promise).rejects.toSatisfy(expectInvalidStream)
  })

  it('requires metadata before chunks or terminal events', async () => {
    for (const [eventName, payload] of [
      ['chunk', validStreamChunkEvent],
      ['done', { ...validStreamDoneEvent, chunks: 0 }],
      ['error', validStreamErrorEvent],
    ] as const) {
      const { promise } = parserHarness(
        textStream(frame(eventName, payload)),
      )
      await expect(promise).rejects.toSatisfy(expectInvalidStream)
    }
  })

  it('rejects duplicate metadata', async () => {
    const { promise } = parserHarness(
      textStream(
        frame('metadata', validStreamMetadataEvent) +
          frame('metadata', validStreamMetadataEvent),
      ),
    )

    await expect(promise).rejects.toSatisfy(expectInvalidStream)
  })

  it.each([
    ['starts above zero', 1],
    ['duplicates a sequence', 0],
    ['skips a sequence', 2],
  ])('rejects a chunk sequence that %s', async (_name, secondSequence) => {
    const firstChunk =
      secondSequence === 1 ? '' : frame('chunk', validStreamChunkEvent)
    const invalidChunk = {
      ...validStreamChunkEvent,
      sequence: secondSequence,
    }
    const { promise } = parserHarness(
      textStream(
        frame('metadata', validStreamMetadataEvent) +
          firstChunk +
          frame('chunk', invalidChunk),
      ),
    )

    await expect(promise).rejects.toSatisfy(expectInvalidStream)
  })

  it.each(['metadata', 'chunk', 'done', 'error'] as const)(
    'rejects a response/event request-ID mismatch on %s',
    async (eventName) => {
      const payloads = {
        metadata: validStreamMetadataEvent,
        chunk: validStreamChunkEvent,
        done: { ...validStreamDoneEvent, chunks: 0 },
        error: validStreamErrorEvent,
      }
      const prefix =
        eventName === 'metadata'
          ? ''
          : frame('metadata', validStreamMetadataEvent)
      const payload = {
        ...payloads[eventName],
        request_id: 'different-request-id',
      }
      const { promise } = parserHarness(
        textStream(prefix + frame(eventName, payload)),
      )

      await expect(promise).rejects.toSatisfy(expectInvalidStream)
    },
  )

  it('verifies the done chunk count', async () => {
    const { promise } = parserHarness(
      textStream(
        frame('metadata', validStreamMetadataEvent) +
          frame('chunk', validStreamChunkEvent) +
          frame('done', { ...validStreamDoneEvent, chunks: 2 }),
      ),
    )

    await expect(promise).rejects.toSatisfy(expectInvalidStream)
  })

  it.each(['done', 'error'] as const)(
    'rejects an event after terminal %s',
    async (terminalName) => {
      const terminalPayload =
        terminalName === 'done'
          ? validStreamDoneEvent
          : validStreamErrorEvent
      const { promise } = parserHarness(
        textStream(
          frame('metadata', validStreamMetadataEvent) +
            frame('chunk', validStreamChunkEvent) +
            frame(terminalName, terminalPayload) +
            frame('chunk', {
              ...validStreamChunkEvent,
              sequence: 1,
            }),
        ),
      )

      await expect(promise).rejects.toSatisfy(expectInvalidStream)
    },
  )

  it('rejects malformed UTF-8 instead of accepting replacement text', async () => {
    const validPrefix = new TextEncoder().encode(
      frame('metadata', validStreamMetadataEvent),
    )
    const { promise } = parserHarness(
      byteStream([validPrefix, Uint8Array.of(0xc3, 0x28)]),
    )

    await expect(promise).rejects.toSatisfy(expectInvalidStream)
  })
})

describe('parseSseStream terminal and interruption behavior', () => {
  it('returns success only after a validated done and clean EOF', async () => {
    const harness = parserHarness(textStream(completeStream()))

    const result = await harness.promise

    expect(result).toEqual({ requestId: REQUEST_ID, chunks: 1 })
    expect(Object.isFrozen(result)).toBe(true)
  })

  it('preserves approved callbacks but rejects EOF without completion', async () => {
    const harness = parserHarness(
      textStream(
        frame('metadata', validStreamMetadataEvent) +
          frame('chunk', validStreamChunkEvent),
      ),
    )

    await expect(harness.promise).rejects.toMatchObject({
      kind: 'network',
      code: 'stream_interrupted',
      retryable: true,
      requestId: REQUEST_ID,
    })
    expect(harness.metadata).toEqual([validStreamMetadataEvent])
    expect(harness.chunks).toEqual([validStreamChunkEvent])
  })

  it('rejects a terminal frame without its blank-line delimiter', async () => {
    const incompleteDone = frame('done', validStreamDoneEvent).slice(0, -1)
    const { promise } = parserHarness(
      textStream(
        frame('metadata', validStreamMetadataEvent) +
          frame('chunk', validStreamChunkEvent) +
          incompleteDone,
      ),
    )

    await expect(promise).rejects.toSatisfy(expectInvalidStream)
  })

  it('returns the validated terminal stream error after preserving partial text', async () => {
    const harness = parserHarness(
      textStream(
        frame('metadata', validStreamMetadataEvent) +
          frame('chunk', validStreamChunkEvent) +
          frame('error', validStreamErrorEvent),
      ),
    )

    await expect(harness.promise).rejects.toMatchObject({
      kind: 'http',
      code: 'stream_interrupted',
      message: 'The response stream was interrupted.',
      retryable: true,
      requestId: REQUEST_ID,
    })
    expect(harness.chunks).toEqual([validStreamChunkEvent])
  })

  it('normalizes a reader failure without exposing its exception', async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.error(new Error('private transport detail'))
      },
    })
    let captured: unknown
    try {
      await parserHarness(body).promise
    } catch (error: unknown) {
      captured = error
    }

    expect(captured).toMatchObject({
      kind: 'network',
      code: 'stream_interrupted',
      retryable: true,
    })
    expect(String(captured)).not.toContain('private transport detail')
  })

  it('cancels an active reader when the caller aborts', async () => {
    const cancel = vi.fn()
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            frame('metadata', validStreamMetadataEvent),
          ),
        )
      },
      cancel,
    })
    const controller = new AbortController()
    const promise = parseSseStream({
      body,
      requestId: REQUEST_ID,
      handlers: { onMetadata: vi.fn(), onChunk: vi.fn() },
      signal: controller.signal,
    })

    controller.abort('private reason')

    await expect(promise).rejects.toMatchObject({
      kind: 'cancelled',
      code: 'request_cancelled',
    })
    expect(cancel).toHaveBeenCalledTimes(1)
  })
})
