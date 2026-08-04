import { useEffect, useId, useRef } from 'react'

import type { ChatRequestError } from '../chatTypes'

export const REQUEST_ERROR_NOTICE_ID = 'chat-request-error-notice'

export type RequestErrorNoticeProps = Readonly<{
  error: ChatRequestError | null
  retryDisabled: boolean
  onRetry(): void
  onEditAndResend(): void
}>

function errorTitle(error: ChatRequestError): string {
  if (error.code === 'payload_too_large' || error.code === 'invalid_request') {
    return 'Message could not be sent'
  }
  if (error.kind === 'timeout' || error.code === 'request_timeout') {
    return 'Request timed out'
  }
  if (error.kind === 'network' || error.code === 'stream_interrupted') {
    return 'Connection interrupted'
  }
  return 'Request could not be completed'
}

function recoveryGuidance(error: ChatRequestError): string {
  if (error.code === 'payload_too_large') {
    return 'Use a shorter message before sending another request.'
  }
  if (error.code === 'invalid_request') {
    return 'Review the message before sending another request.'
  }
  if (
    error.code === 'unsupported_media_type' ||
    error.code === 'not_found' ||
    error.code === 'method_not_allowed'
  ) {
    return 'Reload the page. If this continues, check the frontend API configuration.'
  }
  if (error.retryable) {
    return 'The request was not retried automatically. Check the service status before trying again.'
  }
  return 'The request was not retried. Use an official support channel if help is urgent.'
}

export function RequestErrorNotice({
  error,
  retryDisabled,
  onRetry,
  onEditAndResend,
}: RequestErrorNoticeProps) {
  const titleId = useId()
  const noticeRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (error !== null) {
      noticeRef.current?.focus()
    }
  }, [error])

  if (error === null) {
    return null
  }

  return (
    <section
      id={REQUEST_ERROR_NOTICE_ID}
      ref={noticeRef}
      className="min-w-0 rounded-3xl border border-rose-300/30 bg-rose-300/10 p-5 text-rose-50 [overflow-wrap:anywhere] sm:p-6"
      role="alert"
      aria-labelledby={titleId}
      tabIndex={-1}
    >
      <h2 id={titleId} className="text-lg font-bold">
        {errorTitle(error)}
      </h2>
      <p className="mt-2 leading-7">{error.message}</p>
      <p className="mt-2 text-sm leading-6 text-rose-50/80">
        {recoveryGuidance(error)}
      </p>

      <div className="mt-4 flex flex-wrap gap-3">
        {error.retryable ? (
          <button
            className="min-h-11 w-full rounded-xl bg-rose-100 px-4 py-2 text-sm font-bold text-rose-950 transition hover:bg-white disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400 sm:w-auto"
            type="button"
            disabled={retryDisabled}
            onClick={onRetry}
          >
            Retry request
          </button>
        ) : (
          <button
            className="min-h-11 w-full rounded-xl bg-rose-100 px-4 py-2 text-sm font-bold text-rose-950 transition hover:bg-white sm:w-auto"
            type="button"
            onClick={onEditAndResend}
          >
            Edit and resend
          </button>
        )}
      </div>

      <details className="mt-4 border-t border-rose-100/15 pt-3 text-sm">
        <summary className="cursor-pointer rounded-md font-semibold marker:text-rose-100/70">
          Error details
        </summary>
        <dl className="mt-3 grid gap-3">
          <div>
            <dt className="text-xs font-semibold uppercase tracking-[0.12em] text-rose-100/65">
              Error code
            </dt>
            <dd className="mt-1 break-all font-mono text-xs">{error.code}</dd>
          </div>
          {error.requestId !== null ? (
            <div>
              <dt className="text-xs font-semibold uppercase tracking-[0.12em] text-rose-100/65">
                Request reference
              </dt>
              <dd className="mt-1 select-all break-all font-mono text-xs">
                {error.requestId}
              </dd>
            </div>
          ) : null}
        </dl>
      </details>
    </section>
  )
}
