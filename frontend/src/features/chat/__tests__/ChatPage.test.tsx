// @vitest-environment jsdom

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import App from '../../../App'
import type { ApiClient } from '../../../api/client'
import type {
  LivenessResponse,
  PublicAnswerMetadata,
  ReadinessResponse,
} from '../../../api/contracts'
import { ApiClientError } from '../../../api/errors'
import type {
  CompletedStream,
  StreamEventHandlers,
} from '../../../api/sseParser'
import { createChatStore } from '../chatStore'
import { ChatPage } from '../components/ChatPage'

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

function apiClientWith(
  checkReadiness: ApiClient['checkReadiness'],
  checkLiveness: ApiClient['checkLiveness'] = vi
    .fn<ApiClient['checkLiveness']>()
    .mockResolvedValue(ALIVE),
): ApiClient {
  return {
    checkLiveness,
    checkReadiness,
    sendChatMessage: vi.fn<ApiClient['sendChatMessage']>(),
    streamChatMessage: vi.fn<ApiClient['streamChatMessage']>(),
  }
}

function storeWith(checkReadiness: ApiClient['checkReadiness']) {
  return createChatStore({ apiClient: apiClientWith(checkReadiness) })
}

function pendingStreamHarness() {
  let handlers: StreamEventHandlers | undefined
  let resolveStream: ((value: CompletedStream) => void) | undefined
  let rejectStream: ((reason: unknown) => void) | undefined
  const streamChatMessage = vi.fn<ApiClient['streamChatMessage']>(
    (_message, streamHandlers) => {
      handlers = streamHandlers
      return new Promise<CompletedStream>((resolve, reject) => {
        resolveStream = resolve
        rejectStream = reject
      })
    },
  )

  const requireHandlers = (): StreamEventHandlers => {
    if (handlers === undefined) {
      throw new Error('The mocked stream has not started.')
    }
    return handlers
  }

  return {
    apiClient: {
      ...apiClientWith(
        vi.fn<ApiClient['checkReadiness']>().mockResolvedValue(READY),
      ),
      streamChatMessage,
    },
    streamChatMessage,
    handlers: requireHandlers,
    resolve(value: CompletedStream) {
      if (resolveStream === undefined) {
        throw new Error('The mocked stream has not started.')
      }
      resolveStream(value)
    },
    reject(reason: unknown) {
      if (rejectStream === undefined) {
        throw new Error('The mocked stream has not started.')
      }
      rejectStream(reason)
    },
  }
}

describe('ChatPage base UI', () => {
  it('shows the startup check before presenting the ready state', async () => {
    let resolveReadiness: (value: ReadinessResponse) => void = () => undefined
    const pendingReadiness = new Promise<ReadinessResponse>((resolve) => {
      resolveReadiness = resolve
    })
    const checkReadiness = vi
      .fn<ApiClient['checkReadiness']>()
      .mockReturnValue(pendingReadiness)

    render(<ChatPage store={storeWith(checkReadiness)} />)

    expect(screen.getByRole('status')).toHaveTextContent(
      'Checking local service',
    )
    expect(checkReadiness).toHaveBeenCalledTimes(1)

    await act(async () => {
      resolveReadiness(READY)
      await pendingReadiness
    })

    expect(screen.getByRole('status')).toHaveTextContent('Service ready')
    expect(
      screen.getByText('The local support service is available.'),
    ).toBeVisible()
  })

  it('renders the fictional-prototype and account-action limitations', async () => {
    const checkReadiness = vi
      .fn<ApiClient['checkReadiness']>()
      .mockResolvedValue(READY)
    const store = storeWith(checkReadiness)

    render(<App store={store} />)

    expect(
      screen.getByRole('heading', { name: 'Fintech Support Triage' }),
    ).toBeVisible()
    expect(screen.getByText('Local-only demo')).toBeVisible()
    expect(
      screen.getByRole('heading', {
        name: 'Guidance only - no account access',
      }),
    ).toBeVisible()
    expect(
      screen.getByText(/cannot access accounts, view transactions/i),
    ).toBeVisible()
    expect(screen.getByText(/Do not enter passwords/i)).toBeVisible()
    expect(
      screen.getByText(/Response status and priority labels describe/i),
    ).toHaveTextContent(/never confirm an account action/i)
    expect(
      screen.getByRole('link', { name: 'Skip to main content' }),
    ).toHaveAttribute('href', '#main-content')
    await screen.findByText('Service ready')
  })

  it('presents optional degradation with visible text and public details', async () => {
    const degraded: ReadinessResponse = {
      status: 'degraded',
      components: {
        ...READY.components,
        vector_store: 'unavailable',
      },
    }
    const checkReadiness = vi
      .fn<ApiClient['checkReadiness']>()
      .mockResolvedValue(degraded)

    render(<ChatPage store={storeWith(checkReadiness)} />)

    expect(await screen.findByText('Limited service')).toBeVisible()
    expect(
      screen.getByText(/Safe guidance and fallbacks remain available/i),
    ).toBeVisible()
    expect(screen.getByText('Service details')).toBeVisible()
    expect(screen.getByText('Policy search')).toBeInTheDocument()
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Retry connection' }),
    ).toBeNull()
  })

  it('fails closed for a mandatory unavailable component', async () => {
    const unavailable: ReadinessResponse = {
      status: 'degraded',
      components: {
        ...READY.components,
        pipeline: 'unavailable',
      },
    }
    const checkReadiness = vi
      .fn<ApiClient['checkReadiness']>()
      .mockResolvedValue(unavailable)

    render(<ChatPage store={storeWith(checkReadiness)} />)

    expect(await screen.findByText('Service unavailable')).toBeVisible()
    expect(
      screen.getByText(/Check the backend, then try again/i),
    ).toBeVisible()
    expect(
      screen.getByRole('button', { name: 'Retry connection' }),
    ).toBeVisible()
    expect(screen.getByText('Support pipeline')).toBeInTheDocument()
  })

  it('retries a failed connection without exposing private error details', async () => {
    const user = userEvent.setup()
    const checkReadiness = vi
      .fn<ApiClient['checkReadiness']>()
      .mockRejectedValueOnce(
        new ApiClientError({
          kind: 'network',
          code: 'api_unreachable',
          message: 'The local support service could not be reached.',
          retryable: true,
        }),
      )
      .mockResolvedValueOnce(READY)
    const checkLiveness = vi
      .fn<ApiClient['checkLiveness']>()
      .mockRejectedValueOnce(
        new ApiClientError({
          kind: 'network',
          code: 'api_unreachable',
          message: 'The local support service could not be reached.',
          retryable: true,
        }),
      )

    render(
      <ChatPage
        store={createChatStore({
          apiClient: apiClientWith(checkReadiness, checkLiveness),
        })}
      />,
    )

    expect(await screen.findByText('Service unavailable')).toBeVisible()
    expect(
      screen.getByText('The local support service could not be reached.'),
    ).toBeVisible()
    expect(document.body).not.toHaveTextContent('C:\\private')

    await user.click(
      screen.getByRole('button', { name: 'Retry connection' }),
    )

    expect(await screen.findByText('Service ready')).toBeVisible()
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveFocus()
    expect(checkReadiness).toHaveBeenCalledTimes(2)
    expect(checkLiveness).toHaveBeenCalledTimes(1)
  })

  it('returns focus to connection retry when the service remains unavailable', async () => {
    const user = userEvent.setup()
    const unavailableError = new ApiClientError({
      kind: 'network',
      code: 'api_unreachable',
      message: 'The local support service could not be reached.',
      retryable: true,
    })
    const checkReadiness = vi
      .fn<ApiClient['checkReadiness']>()
      .mockRejectedValue(unavailableError)
    const checkLiveness = vi
      .fn<ApiClient['checkLiveness']>()
      .mockRejectedValue(unavailableError)

    render(
      <ChatPage
        store={createChatStore({
          apiClient: apiClientWith(checkReadiness, checkLiveness),
        })}
      />,
    )

    const retry = await screen.findByRole('button', {
      name: 'Retry connection',
    })
    await user.click(retry)

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Retry connection' }),
      ).toHaveFocus(),
    )
    expect(checkReadiness).toHaveBeenCalledTimes(2)
    expect(checkLiveness).toHaveBeenCalledTimes(2)
  })

  it('shows inline input validation and prevents duplicate submission', async () => {
    const user = userEvent.setup()
    const streamChatMessage = vi.fn<ApiClient['streamChatMessage']>(
      (_message, _handlers, options = {}) =>
        new Promise((_resolve, reject) => {
          options.signal?.addEventListener(
            'abort',
            () =>
              reject(
                new ApiClientError({
                  kind: 'cancelled',
                  code: 'request_cancelled',
                  message: 'The request was cancelled.',
                  retryable: true,
                }),
              ),
            { once: true },
          )
        }),
    )
    const store = createChatStore({
      apiClient: {
        ...apiClientWith(
          vi.fn<ApiClient['checkReadiness']>().mockResolvedValue(READY),
        ),
        streamChatMessage,
      },
    })
    render(<ChatPage store={store} />)
    await screen.findByText('Service ready')

    const textarea = screen.getByRole('textbox', { name: 'Message' })
    const send = screen.getByRole('button', { name: 'Send message' })
    await user.click(send)
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Enter a message before sending.',
    )
    await waitFor(() => expect(textarea).toHaveFocus())
    expect(streamChatMessage).not.toHaveBeenCalled()

    fireEvent.change(textarea, { target: { value: 'x'.repeat(2_001) } })
    await user.click(send)
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Messages must be 2,000 characters or fewer.',
    )
    expect(streamChatMessage).not.toHaveBeenCalled()

    fireEvent.change(textarea, { target: { value: 'Supported question' } })
    await user.type(textarea, '{Enter}')
    expect(streamChatMessage).toHaveBeenCalledTimes(1)
    expect(
      screen.getByRole('button', { name: 'Request in progress' }),
    ).toBeDisabled()
    await user.click(
      screen.getByRole('button', { name: 'Request in progress' }),
    )
    expect(streamChatMessage).toHaveBeenCalledTimes(1)

    act(() => store.getState().clearConversation())
  })

  it('shows the pre-header wait, approved chunks, and completion in order', async () => {
    const user = userEvent.setup()
    const stream = pendingStreamHarness()
    const store = createChatStore({ apiClient: stream.apiClient })
    render(<ChatPage store={store} />)
    await screen.findByText('Service ready')

    const textarea = screen.getByRole('textbox', { name: 'Message' })
    await user.type(textarea, 'When should my card arrive?{Enter}')

    expect(await screen.findByText('Processing your request.')).toBeVisible()
    expect(screen.queryByText('Approved answer.')).toBeNull()
    expect(stream.streamChatMessage).toHaveBeenCalledTimes(1)

    act(() => {
      stream.handlers().onMetadata(METADATA)
    })
    expect(
      screen.getByText('Delivering an approved response.'),
    ).toBeVisible()
    expect(screen.getAllByText('Answered')[0]).toBeVisible()
    expect(screen.getByText('Low priority')).toBeVisible()
    expect(screen.getByText(METADATA.request_id)).toBeInTheDocument()

    act(() => {
      stream.handlers().onChunk({
        request_id: METADATA.request_id,
        sequence: 0,
        text: 'Approved ',
      })
      stream.handlers().onChunk({
        request_id: METADATA.request_id,
        sequence: 1,
        text: 'answer.',
      })
    })
    expect(screen.getByText('Approved answer.')).toBeVisible()

    await act(async () => {
      stream.resolve({ requestId: METADATA.request_id, chunks: 2 })
      await Promise.resolve()
    })
    expect(screen.getByText('Response complete.')).toBeVisible()
    expect(
      screen.queryByText('Delivering an approved response.'),
    ).toBeNull()
  })

  it('cancels during approved delivery and retries the same turn explicitly', async () => {
    const user = userEvent.setup()
    const stream = pendingStreamHarness()
    const store = createChatStore({ apiClient: stream.apiClient })
    render(<ChatPage store={store} />)
    await screen.findByText('Service ready')

    await user.type(
      screen.getByRole('textbox', { name: 'Message' }),
      'Supported cancellation question{Enter}',
    )
    const staleHandlers = stream.handlers()
    act(() => {
      staleHandlers.onMetadata(METADATA)
      staleHandlers.onChunk({
        request_id: METADATA.request_id,
        sequence: 0,
        text: 'Approved partial text.',
      })
    })

    expect(
      screen.getByText(/local processing may continue in the background/i),
    ).toBeVisible()
    await user.click(
      screen.getByRole('button', { name: 'Cancel request' }),
    )
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveFocus()
    expect(screen.getByText('Response cancelled.')).toBeVisible()
    expect(screen.getByText('Approved partial text.')).toBeVisible()
    expect(screen.queryByText('Response complete.')).toBeNull()

    act(() => {
      staleHandlers.onChunk({
        request_id: METADATA.request_id,
        sequence: 1,
        text: ' Late text.',
      })
    })
    expect(screen.queryByText(/Late text/)).toBeNull()

    await user.click(
      screen.getByRole('button', {
        name: 'Retry cancelled request',
      }),
    )
    expect(stream.streamChatMessage).toHaveBeenCalledTimes(2)
    expect(screen.getAllByLabelText('You message')).toHaveLength(1)
    expect(screen.getByText('Processing your request.')).toBeVisible()

    act(() => store.getState().clearConversation())
  })

  it('retries a retryable failure without duplicating the customer message', async () => {
    const user = userEvent.setup()
    const stream = pendingStreamHarness()
    const store = createChatStore({ apiClient: stream.apiClient })
    render(<ChatPage store={store} />)
    await screen.findByText('Service ready')

    await user.type(
      screen.getByRole('textbox', { name: 'Message' }),
      'Supported retry question{Enter}',
    )
    await act(async () => {
      stream.reject(
        new ApiClientError({
          kind: 'http',
          code: 'service_busy',
          message: 'The support service is busy. Please try again.',
          retryable: true,
          status: 503,
        }),
      )
      await Promise.resolve()
    })

    await user.click(screen.getByRole('button', { name: 'Retry request' }))
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveFocus()
    expect(stream.streamChatMessage).toHaveBeenCalledTimes(2)
    expect(screen.getAllByLabelText('You message')).toHaveLength(1)
    expect(screen.getByText('Processing your request.')).toBeVisible()

    act(() => store.getState().clearConversation())
  })

  it('restores a nonretryable request for editing before a new submission', async () => {
    const user = userEvent.setup()
    const stream = pendingStreamHarness()
    const store = createChatStore({ apiClient: stream.apiClient })
    render(<ChatPage store={store} />)
    await screen.findByText('Service ready')
    const textarea = screen.getByRole('textbox', { name: 'Message' })

    await user.type(textarea, 'Original request{Enter}')
    await act(async () => {
      stream.reject(
        new ApiClientError({
          kind: 'invalid_response',
          code: 'invalid_stream_response',
          message:
            'The local support service returned an invalid response stream.',
          retryable: false,
        }),
      )
      await Promise.resolve()
    })

    expect(
      screen.queryByRole('button', { name: 'Retry request' }),
    ).toBeNull()
    await user.click(
      screen.getByRole('button', { name: 'Edit and resend' }),
    )
    expect(textarea).toHaveValue('Original request')
    expect(textarea).toHaveFocus()
    expect(screen.queryByRole('alert')).toBeNull()

    await user.clear(textarea)
    await user.type(textarea, 'Edited request{Enter}')
    expect(stream.streamChatMessage).toHaveBeenCalledTimes(2)
    expect(stream.streamChatMessage).toHaveBeenLastCalledWith(
      'Edited request',
      expect.any(Object),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(screen.getAllByLabelText('You message')).toHaveLength(2)

    act(() => store.getState().clearConversation())
  })

  it('keeps approved partial text visibly incomplete after a stream failure', async () => {
    const user = userEvent.setup()
    const stream = pendingStreamHarness()
    const store = createChatStore({ apiClient: stream.apiClient })
    render(<ChatPage store={store} />)
    await screen.findByText('Service ready')

    await user.type(
      screen.getByRole('textbox', { name: 'Message' }),
      'Supported question{Enter}',
    )
    act(() => {
      stream.handlers().onMetadata(METADATA)
      stream.handlers().onChunk({
        request_id: METADATA.request_id,
        sequence: 0,
        text: 'Approved partial text.',
      })
    })

    await act(async () => {
      stream.reject(
        new ApiClientError({
          kind: 'invalid_response',
          code: 'invalid_stream_response',
          message:
            'The local support service returned an invalid response stream.',
          retryable: false,
          requestId: METADATA.request_id,
        }),
      )
      await Promise.resolve()
    })

    expect(screen.getByText('Approved partial text.')).toBeVisible()
    expect(
      screen.getByText(
        'Incomplete response - delivery was interrupted.',
      ),
    ).toBeVisible()
    expect(screen.queryByText('Response complete.')).toBeNull()
    expect(
      screen.getByRole('alert', {
        name: 'Request could not be completed',
      }),
    ).toHaveTextContent(
      'The local support service returned an invalid response stream.',
    )
    expect(document.activeElement).toBe(
      screen.getByRole('alert', {
        name: 'Request could not be completed',
      }),
    )
    expect(
      screen.getByRole('textbox', { name: 'Message' }),
    ).toHaveAccessibleDescription(
      expect.stringContaining(
        'The local support service returned an invalid response stream.',
      ),
    )

    act(() => {
      stream.handlers().onChunk({
        request_id: METADATA.request_id,
        sequence: 1,
        text: ' Stale text.',
      })
    })
    expect(screen.queryByText(/Stale text/)).toBeNull()
  })
})
