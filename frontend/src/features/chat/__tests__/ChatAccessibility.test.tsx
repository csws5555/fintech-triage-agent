// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '../../../api/client'
import type {
  LivenessResponse,
  PublicAnswerMetadata,
  ReadinessResponse,
} from '../../../api/contracts'
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
  request_id: 'accessibility-request-id',
  status: 'answered',
  response_mode: 'grounded_generation',
  risk_level: 'low',
  requires_human: false,
}

function accessibleApiClient(): ApiClient {
  return {
    checkLiveness: vi.fn<ApiClient['checkLiveness']>().mockResolvedValue(ALIVE),
    checkReadiness: vi
      .fn<ApiClient['checkReadiness']>()
      .mockResolvedValue(READY),
    sendChatMessage: vi.fn<ApiClient['sendChatMessage']>(),
    streamChatMessage: vi.fn<ApiClient['streamChatMessage']>(
      async (_message, handlers) => {
        handlers.onMetadata(METADATA)
        handlers.onChunk({
          request_id: METADATA.request_id,
          sequence: 0,
          text: 'Approved accessible response.',
        })
        return { requestId: METADATA.request_id, chunks: 1 }
      },
    ),
  }
}

describe('chat accessibility', () => {
  it('has no detectable axe violations in the ready application', async () => {
    const { container } = render(
      <ChatPage store={createChatStore({ apiClient: accessibleApiClient() })} />,
    )
    await screen.findByText('Service ready')

    const results = await axe(container, {
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(results.violations).toEqual([])
  })

  it('supports the primary request workflow using the keyboard alone', async () => {
    const user = userEvent.setup()
    render(
      <ChatPage store={createChatStore({ apiClient: accessibleApiClient() })} />,
    )
    await screen.findByText('Service ready')

    await user.tab()
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveFocus()
    await user.tab()
    const composer = screen.getByRole('textbox', { name: 'Message' })
    expect(composer).toHaveFocus()

    await user.tab()
    expect(screen.getByRole('button', { name: 'Send message' })).toHaveFocus()
    await user.tab({ shift: true })
    expect(composer).toHaveFocus()

    await user.type(composer, 'Keyboard support question{Enter}')

    expect(await screen.findByText('Approved accessible response.')).toBeVisible()
    expect(screen.getByText('Response complete.')).toBeVisible()
    expect(composer).toHaveFocus()
  })

  it('moves focus through destructive confirmation and back to the composer', async () => {
    const user = userEvent.setup()
    render(
      <ChatPage store={createChatStore({ apiClient: accessibleApiClient() })} />,
    )
    await screen.findByText('Service ready')
    const composer = screen.getByRole('textbox', { name: 'Message' })
    await user.type(composer, 'Clear focus question{Enter}')
    await screen.findByText('Response complete.')

    const clearConversation = screen.getByRole('button', {
      name: 'Clear conversation',
    })
    clearConversation.focus()
    await user.keyboard('{Enter}')
    const confirmClear = screen.getByRole('button', {
      name: 'Clear messages',
    })
    expect(confirmClear).toHaveFocus()

    await user.keyboard('{Enter}')
    expect(screen.getByText('No messages yet')).toBeVisible()
    expect(composer).toHaveFocus()
  })
})
