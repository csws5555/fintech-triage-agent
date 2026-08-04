// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChatMessage } from '../chatTypes'
import { MessageList } from '../components/MessageList'

const MESSAGES: readonly ChatMessage[] = [
  {
    id: 'message-user',
    turnId: 'turn-1',
    role: 'user',
    content: 'When should my first card arrive?',
    delivery: 'complete',
  },
  {
    id: 'message-assistant',
    turnId: 'turn-1',
    role: 'assistant',
    content: 'Check the delivery estimate in the app.',
    delivery: 'complete',
  },
]

const scrollIntoView = vi.fn()

beforeEach(() => {
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    value: scrollIntoView,
  })
})

afterEach(() => {
  scrollIntoView.mockReset()
  Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
  vi.unstubAllGlobals()
})

describe('MessageList', () => {
  it('explains empty and stateless transcript behavior', () => {
    render(<MessageList messages={[]} onClear={vi.fn()} />)

    expect(screen.getByText('No messages yet')).toBeVisible()
    expect(
      screen.getByText(/Earlier messages are not sent with your next request/i),
    ).toBeVisible()
    expect(
      screen.queryByRole('button', { name: 'Clear conversation' }),
    ).toBeNull()
  })

  it('renders ordered messages and scrolls when transcript content changes', () => {
    const { rerender } = render(
      <MessageList messages={MESSAGES.slice(0, 1)} onClear={vi.fn()} />,
    )

    expect(screen.getByRole('list', { name: 'Conversation messages' }))
      .toBeVisible()
    expect(screen.getByLabelText('You message')).toBeVisible()
    expect(scrollIntoView).toHaveBeenCalledTimes(1)

    rerender(<MessageList messages={MESSAGES} onClear={vi.fn()} />)
    expect(screen.getByLabelText('Support guide message')).toBeVisible()
    expect(scrollIntoView).toHaveBeenCalledTimes(2)
    expect(scrollIntoView).toHaveBeenLastCalledWith({
      block: 'end',
      behavior: 'smooth',
    })
  })

  it('avoids smooth transcript scrolling when reduced motion is requested', () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({ matches: true }),
    )

    render(<MessageList messages={MESSAGES} onClear={vi.fn()} />)

    expect(scrollIntoView).toHaveBeenCalledWith({
      block: 'end',
      behavior: 'auto',
    })
  })

  it('requires confirmation before clearing the in-memory transcript', async () => {
    const user = userEvent.setup()
    const onClear = vi.fn()
    render(<MessageList messages={MESSAGES} onClear={onClear} />)

    await user.click(
      screen.getByRole('button', { name: 'Clear conversation' }),
    )
    expect(screen.getByRole('alertdialog')).toHaveAccessibleName(
      'Clear this conversation?',
    )
    expect(
      screen.getByRole('button', { name: 'Clear messages' }),
    ).toHaveFocus()
    expect(onClear).not.toHaveBeenCalled()

    await user.click(
      screen.getByRole('button', { name: 'Keep conversation' }),
    )
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(
      screen.getByRole('button', { name: 'Clear conversation' }),
    ).toHaveFocus()

    await user.click(
      screen.getByRole('button', { name: 'Clear conversation' }),
    )
    await user.click(screen.getByRole('button', { name: 'Clear messages' }))
    expect(onClear).toHaveBeenCalledTimes(1)
  })

  it('has no detectable axe violations', async () => {
    const { container } = render(
      <MessageList messages={MESSAGES} onClear={vi.fn()} />,
    )

    const results = await axe(container, {
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(results.violations).toEqual([])
  })
})
