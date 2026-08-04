/// <reference types="node" />
// @vitest-environment jsdom

import { readFileSync } from 'node:fs'

import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { ReadinessComponents } from '../../../api/contracts'
import type { ChatMessage } from '../chatTypes'
import { ChatComposer } from '../components/ChatComposer'
import { MessageBubble } from '../components/MessageBubble'
import { MessageList } from '../components/MessageList'
import { RequestErrorNotice } from '../components/RequestErrorNotice'
import { ServiceStatus } from '../components/ServiceStatus'

const COMPONENTS: ReadinessComponents = {
  configuration: 'ready',
  classifier: 'ready',
  pipeline: 'ready',
  vector_store: 'unavailable',
  ollama_chat_model: 'unavailable',
  ollama_embedding_model: 'unavailable',
}

const LONG_TOKEN = `https://support.example.invalid/${'segment'.repeat(120)}`

const LONG_ASSISTANT_MESSAGE: ChatMessage = {
  id: 'assistant-long',
  turnId: 'turn-long',
  role: 'assistant',
  content: `Approved multiline guidance:\n${LONG_TOKEN}\n安全に確認してください。`,
  delivery: 'complete',
  metadata: {
    request_id: `request-${'reference'.repeat(80)}`,
    status: 'safety_guidance',
    response_mode: 'deterministic_safety',
    risk_level: 'critical',
    requires_human: true,
  },
}

describe('responsive chat layout', () => {
  it('does not force the document wider than a 320px viewport', () => {
    const styles = readFileSync('src/index.css', 'utf8')

    expect(styles).not.toContain('min-width: 320px')
    expect(styles).toContain('min-height: 100dvh')
    expect(styles).toMatch(/#root\s*{[^}]*min-width:\s*0;/s)
  })

  it('wraps long response content and bounds nested metadata', () => {
    render(<MessageBubble message={LONG_ASSISTANT_MESSAGE} />)

    const article = screen.getByLabelText('Support guide message')
    expect(article).toHaveClass('min-w-0', 'max-w-full', 'sm:max-w-[82%]')
    expect(within(article).getByText(/Approved multiline guidance/)).toHaveClass(
      'break-words',
      '[overflow-wrap:anywhere]',
    )
    expect(screen.getByText(LONG_ASSISTANT_MESSAGE.metadata!.request_id))
      .toHaveClass('break-all')
    expect(screen.getByRole('alert')).toHaveClass(
      'min-w-0',
      '[overflow-wrap:anywhere]',
    )
  })

  it('uses mobile-height transcript bounds and full-width urgent controls', () => {
    const { rerender } = render(
      <MessageList messages={[LONG_ASSISTANT_MESSAGE]} onClear={vi.fn()} />,
    )

    expect(
      screen.getByRole('list', { name: 'Conversation messages' }),
    ).toHaveClass('max-h-[55dvh]', 'sm:max-h-[34rem]', 'min-w-0')
    expect(
      screen.getByRole('button', { name: 'Clear conversation' }),
    ).toHaveClass('w-full', 'sm:w-auto')

    rerender(
      <ChatComposer
        draft=""
        inputError={null}
        disabled={false}
        isSubmitting
        onDraftChange={vi.fn()}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: 'Cancel request' })).toHaveClass(
      'w-full',
      'sm:w-auto',
    )
    expect(
      screen.getByRole('button', { name: 'Request in progress' }),
    ).toHaveClass('w-full', 'sm:w-auto')
  })

  it('allows service details and recovery controls to wrap on narrow screens', () => {
    const { rerender } = render(
      <ServiceStatus
        availability="degraded"
        components={COMPONENTS}
        errorMessage={null}
        onRetry={vi.fn()}
      />,
    )

    const componentList = screen.getByRole('list', {
      name: 'Service components',
    })
    for (const row of within(componentList).getAllByRole('listitem')) {
      expect(row).toHaveClass('min-w-0', 'flex-wrap')
    }

    rerender(
      <ServiceStatus
        availability="unavailable"
        components={null}
        errorMessage={LONG_TOKEN}
        onRetry={vi.fn()}
      />,
    )
    expect(
      screen.getByRole('button', { name: 'Retry connection' }),
    ).toHaveClass('w-full', 'sm:w-auto')

    rerender(
      <RequestErrorNotice
        error={{
          kind: 'network',
          code: 'stream_interrupted',
          message: LONG_TOKEN,
          retryable: true,
          status: null,
          requestId: `request-${'x'.repeat(200)}`,
        }}
        retryDisabled={false}
        onRetry={vi.fn()}
        onEditAndResend={vi.fn()}
      />,
    )
    expect(screen.getByRole('alert')).toHaveClass(
      'min-w-0',
      '[overflow-wrap:anywhere]',
    )
    expect(screen.getByRole('button', { name: 'Retry request' })).toHaveClass(
      'w-full',
      'sm:w-auto',
    )
  })
})
