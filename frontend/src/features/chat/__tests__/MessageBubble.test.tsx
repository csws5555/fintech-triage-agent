// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ChatMessage } from '../chatTypes'
import { MessageBubble } from '../components/MessageBubble'

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
})
