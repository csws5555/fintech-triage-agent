// @vitest-environment jsdom

import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { describe, expect, it, vi } from 'vitest'

import { MAX_CHAT_MESSAGE_CHARACTERS } from '../../../api/contracts'
import type { ChatInputError } from '../chatTypes'
import { ChatComposer } from '../components/ChatComposer'

function ComposerHarness({
  error = null,
  disabled = false,
  isSubmitting = false,
  onSubmit = vi.fn(),
}: Readonly<{
  error?: ChatInputError | null
  disabled?: boolean
  isSubmitting?: boolean
  onSubmit?: () => void
}>) {
  const [draft, setDraft] = useState('')

  return (
    <ChatComposer
      draft={draft}
      inputError={error}
      disabled={disabled}
      isSubmitting={isSubmitting}
      onDraftChange={setDraft}
      onSubmit={onSubmit}
    />
  )
}

describe('ChatComposer', () => {
  it('submits with Enter and keeps Shift+Enter as a newline', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<ComposerHarness onSubmit={onSubmit} />)
    const textarea = screen.getByRole('textbox', { name: 'Message' })

    await user.type(
      textarea,
      'First line{Shift>}{Enter}{/Shift}Second line',
    )
    expect(textarea).toHaveValue('First line\nSecond line')
    expect(onSubmit).not.toHaveBeenCalled()

    await user.type(textarea, '{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(textarea).toHaveValue('First line\nSecond line')
  })

  it('does not submit an Enter key while IME composition is active', () => {
    const onSubmit = vi.fn()
    render(<ComposerHarness onSubmit={onSubmit} />)
    const textarea = screen.getByRole('textbox', { name: 'Message' })

    fireEvent.compositionStart(textarea)
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter' })
    expect(onSubmit).not.toHaveBeenCalled()

    fireEvent.compositionEnd(textarea)
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter' })
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('shows the normalized character count and associated inline errors', async () => {
    const user = userEvent.setup()
    const error: ChatInputError = {
      code: 'message_too_long',
      message: `Messages must be ${MAX_CHAT_MESSAGE_CHARACTERS.toLocaleString(
        'en-US',
      )} characters or fewer.`,
    }
    render(<ComposerHarness error={error} />)
    const textarea = screen.getByRole('textbox', { name: 'Message' })

    await user.type(textarea, '  support question  ')

    expect(
      screen.getByText(`16 of ${MAX_CHAT_MESSAGE_CHARACTERS.toLocaleString('en-US')} characters`),
    ).toBeVisible()
    expect(textarea).toHaveAttribute('aria-invalid', 'true')
    expect(textarea).toHaveAccessibleDescription(
      expect.stringContaining(error.message),
    )
    expect(screen.getByRole('alert')).toHaveTextContent(error.message)
  })

  it('disables duplicate submission while a request is active', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<ComposerHarness isSubmitting onSubmit={onSubmit} />)

    expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled()
    const submit = screen.getByRole('button', {
      name: 'Request in progress',
    })
    expect(submit).toBeDisabled()
    await user.click(submit)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('has no detectable axe violations', async () => {
    const { container } = render(<ComposerHarness />)

    const results = await axe(container, {
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(results.violations).toEqual([])
  })
})
