// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { describe, expect, it, vi } from 'vitest'

import type { ChatRequestError } from '../chatTypes'
import { RequestErrorNotice } from '../components/RequestErrorNotice'

function requestError(
  overrides: Partial<ChatRequestError> = {},
): ChatRequestError {
  return {
    kind: 'http',
    code: 'internal_error',
    message: 'The request could not be completed.',
    retryable: false,
    status: 500,
    requestId: 'server-request-reference',
    ...overrides,
  }
}

const ACTIONS = {
  retryDisabled: false,
  onRetry: vi.fn(),
  onEditAndResend: vi.fn(),
}

describe('RequestErrorNotice', () => {
  it('renders nothing without a failed request', () => {
    const { container } = render(
      <RequestErrorNotice error={null} {...ACTIONS} />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it.each([
    [413, 'payload_too_large', 'The request body is too large.', false, 'Use a shorter message'],
    [415, 'unsupported_media_type', 'Chat requests require application/json.', false, 'Reload the page'],
    [422, 'invalid_request', 'The request is invalid.', false, 'Review the message'],
    [500, 'internal_error', 'The request could not be completed.', false, 'not retried'],
    [503, 'service_busy', 'The support service is busy. Please try again.', true, 'not retried automatically'],
    [503, 'classifier_unavailable', 'The classifier is temporarily unavailable. Please try again.', true, 'not retried automatically'],
    [503, 'support_service_unavailable', 'The support service is temporarily unavailable. Please try again or use an official support channel.', true, 'not retried automatically'],
    [504, 'request_timeout', 'The request timed out. Please try again.', true, 'not retried automatically'],
    [404, 'not_found', 'The requested resource was not found.', false, 'Reload the page'],
    [405, 'method_not_allowed', 'The request method is not allowed for this resource.', false, 'Reload the page'],
  ] as const)(
    'presents the safe HTTP %i/%s error contract',
    (status, code, message, retryable, guidance) => {
      render(
        <RequestErrorNotice
          {...ACTIONS}
          error={requestError({ status, code, message, retryable })}
        />,
      )

      expect(screen.getByRole('alert')).toHaveTextContent(message)
      expect(screen.getByRole('alert')).toHaveTextContent(guidance)
      expect(screen.getByRole('alert')).not.toHaveTextContent(
        'private exception',
      )
    },
  )

  it.each([
    ['network', 'api_unreachable', 'The local support service could not be reached.'],
    ['timeout', 'client_timeout', 'The request timed out locally. Please try again.'],
    ['network', 'stream_interrupted', 'The response stream was interrupted.'],
    ['invalid_response', 'invalid_stream_response', 'The local support service returned an invalid response stream.'],
  ] as const)(
    'presents the safe %s/%s browser failure',
    (kind, code, message) => {
      render(
        <RequestErrorNotice
          {...ACTIONS}
          error={requestError({
            kind,
            code,
            message,
            retryable: kind !== 'invalid_response',
            status: null,
            requestId: null,
          })}
        />,
      )

      expect(screen.getByRole('alert')).toHaveTextContent(message)
      expect(screen.getByRole('alert')).toHaveTextContent(code)
    },
  )

  it('focuses the alert and exposes only the safe code and request reference', async () => {
    const user = userEvent.setup()
    render(<RequestErrorNotice error={requestError()} {...ACTIONS} />)

    const alert = screen.getByRole('alert', {
      name: 'Request could not be completed',
    })
    expect(alert).toHaveFocus()
    await user.click(screen.getByText('Error details'))
    expect(screen.getByText('internal_error')).toBeVisible()
    expect(screen.getByText('server-request-reference')).toHaveClass(
      'select-all',
      'break-all',
    )
    expect(document.body).not.toHaveTextContent('reason_code')
    expect(document.body).not.toHaveTextContent('stack trace')
  })

  it('has no detectable axe violations', async () => {
    const { container } = render(
      <RequestErrorNotice
        {...ACTIONS}
        error={requestError({
          kind: 'network',
          code: 'stream_interrupted',
          message: 'The response stream was interrupted.',
          retryable: true,
        })}
      />,
    )

    const results = await axe(container, {
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(results.violations).toEqual([])
  })

  it('offers only the recovery action allowed by the error', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    const onEditAndResend = vi.fn()
    const { rerender } = render(
      <RequestErrorNotice
        error={requestError({ retryable: true })}
        retryDisabled={false}
        onRetry={onRetry}
        onEditAndResend={onEditAndResend}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Retry request' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
    expect(
      screen.queryByRole('button', { name: 'Edit and resend' }),
    ).toBeNull()

    rerender(
      <RequestErrorNotice
        error={requestError({ retryable: false })}
        retryDisabled={false}
        onRetry={onRetry}
        onEditAndResend={onEditAndResend}
      />,
    )
    await user.click(
      screen.getByRole('button', { name: 'Edit and resend' }),
    )
    expect(onEditAndResend).toHaveBeenCalledTimes(1)
    expect(
      screen.queryByRole('button', { name: 'Retry request' }),
    ).toBeNull()
  })
})
