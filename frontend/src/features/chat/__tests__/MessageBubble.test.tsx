// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ChatMessage } from '../chatTypes'
import { MessageBubble } from '../components/MessageBubble'

const METADATA = {
  request_id: 'request-reference-123',
  status: 'safety_guidance',
  response_mode: 'deterministic_safety',
  risk_level: 'high',
  requires_human: true,
} as const

function message(
  overrides: Partial<ChatMessage> = {},
): ChatMessage {
  return {
    id: 'message-1',
    turnId: 'turn-1',
    role: 'assistant',
    content: 'Approved support text.',
    delivery: 'complete',
    ...overrides,
  }
}

describe('MessageBubble', () => {
  it('renders customer and assistant messages with explicit authors', () => {
    const { rerender } = render(
      <MessageBubble
        message={message({ role: 'user', content: 'Customer question' })}
      />,
    )

    expect(screen.getByLabelText('You message')).toHaveTextContent(
      'Customer question',
    )

    rerender(<MessageBubble message={message()} />)
    expect(screen.getByLabelText('Support guide message')).toHaveTextContent(
      'Approved support text.',
    )
  })

  it('renders HTML-like input as inert multiline text', () => {
    const unsafeText = '<img src=x onerror="alert(1)">\n<script>bad()</script>'
    render(<MessageBubble message={message({ content: unsafeText })} />)

    expect(screen.getByLabelText('Support guide message')).toHaveTextContent(
      '<img src=x onerror="alert(1)"> <script>bad()</script>',
    )
    expect(document.querySelector('img')).toBeNull()
    expect(document.querySelector('script')).toBeNull()
  })

  it('applies safe wrapping to long unbroken content', () => {
    render(<MessageBubble message={message({ content: 'x'.repeat(500) })} />)

    expect(screen.getByText('x'.repeat(500))).toHaveClass(
      'whitespace-pre-wrap',
      'break-words',
      '[overflow-wrap:anywhere]',
    )
  })

  it('renders public metadata and required-human guidance only for an assistant response', () => {
    const { rerender } = render(
      <MessageBubble message={message({ metadata: METADATA })} />,
    )

    expect(screen.getAllByText('Safety guidance')[0]).toBeVisible()
    expect(screen.getByText('High priority')).toBeVisible()
    expect(
      screen.getByRole('heading', { name: 'Human assistance required' }),
    ).toBeVisible()
    expect(screen.getByText('request-reference-123')).toBeInTheDocument()

    rerender(
      <MessageBubble
        message={message({ role: 'user', metadata: METADATA })}
      />,
    )
    expect(screen.queryByText('Safety guidance')).toBeNull()
    expect(
      screen.queryByRole('heading', { name: 'Human assistance required' }),
    ).toBeNull()
  })

  it('does not show a human-assistance banner when requires_human is false', () => {
    render(
      <MessageBubble
        message={message({
          metadata: { ...METADATA, requires_human: false },
        })}
      />,
    )

    expect(screen.getAllByText('Safety guidance')[0]).toBeVisible()
    expect(
      screen.queryByRole('heading', { name: 'Human assistance required' }),
    ).toBeNull()
  })

  it('uses one assertive announcement for combined critical and human-assistance metadata', () => {
    render(
      <MessageBubble
        message={message({
          metadata: { ...METADATA, risk_level: 'critical' },
        })}
      />,
    )

    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByRole('alert')).toHaveAccessibleName(
      'Human assistance required',
    )
    expect(screen.getByText('Critical priority')).toBeVisible()
  })

  it.each([
    ['pending', 'Processing your request.', 'true'],
    ['streaming', 'Delivering an approved response.', 'true'],
    ['complete', 'Response complete.', 'false'],
    [
      'interrupted',
      'Incomplete response - delivery was interrupted.',
      'false',
    ],
    ['cancelled', 'Response cancelled.', 'false'],
    ['failed', 'Response unavailable.', 'false'],
  ] as const)(
    'renders the %s delivery state as visible text',
    (delivery, label, busy) => {
      render(<MessageBubble message={message({ delivery })} />)

      expect(screen.getByRole('status')).toHaveTextContent(label)
      expect(screen.getByLabelText('Support guide message')).toHaveAttribute(
        'aria-busy',
        busy,
      )
    },
  )

  it('announces delivery transitions without announcing streamed chunks', () => {
    const { rerender } = render(
      <MessageBubble
        message={message({ content: 'First chunk', delivery: 'streaming' })}
      />,
    )
    const liveRegion = screen.getByRole('status')

    expect(liveRegion).toHaveTextContent('Delivering an approved response.')
    expect(liveRegion).not.toHaveTextContent('First chunk')

    rerender(
      <MessageBubble
        message={message({
          content: 'First chunk and second chunk',
          delivery: 'streaming',
        })}
      />,
    )
    expect(liveRegion).toHaveTextContent('Delivering an approved response.')
    expect(liveRegion).not.toHaveTextContent('second chunk')
  })

  it('offers retry only for the selected cancelled response', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    const { rerender } = render(
      <MessageBubble
        message={message({ delivery: 'cancelled' })}
        showRetry
        onRetry={onRetry}
      />,
    )

    await user.click(
      screen.getByRole('button', { name: 'Retry cancelled request' }),
    )
    expect(onRetry).toHaveBeenCalledTimes(1)

    rerender(
      <MessageBubble
        message={message({ delivery: 'failed' })}
        showRetry
        onRetry={onRetry}
      />,
    )
    expect(
      screen.queryByRole('button', { name: 'Retry cancelled request' }),
    ).toBeNull()
  })
})
