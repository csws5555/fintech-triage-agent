// @vitest-environment jsdom

import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import App from '../../../App'
import type { ApiClient } from '../../../api/client'
import type { ReadinessResponse } from '../../../api/contracts'
import { ApiClientError } from '../../../api/errors'
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

function apiClientWith(
  checkReadiness: ApiClient['checkReadiness'],
): ApiClient {
  return {
    checkLiveness: vi.fn<ApiClient['checkLiveness']>(),
    checkReadiness,
    sendChatMessage: vi.fn<ApiClient['sendChatMessage']>(),
    streamChatMessage: vi.fn<ApiClient['streamChatMessage']>(),
  }
}

function storeWith(checkReadiness: ApiClient['checkReadiness']) {
  return createChatStore({ apiClient: apiClientWith(checkReadiness) })
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

    render(<ChatPage store={storeWith(checkReadiness)} />)

    expect(await screen.findByText('Service unavailable')).toBeVisible()
    expect(
      screen.getByText('The local support service could not be reached.'),
    ).toBeVisible()
    expect(document.body).not.toHaveTextContent('C:\\private')

    await user.click(
      screen.getByRole('button', { name: 'Retry connection' }),
    )

    expect(await screen.findByText('Service ready')).toBeVisible()
    expect(checkReadiness).toHaveBeenCalledTimes(2)
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
})
