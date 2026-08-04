import type { ChatMessage, MessageDelivery } from '../chatTypes'
import { HumanAssistanceBanner } from './HumanAssistanceBanner'
import { ResponseMetadata } from './ResponseMetadata'

export type MessageBubbleProps = Readonly<{
  message: ChatMessage
  showRetry?: boolean
  retryDisabled?: boolean
  onRetry?(): void
}>

const DELIVERY_PRESENTATION: Readonly<
  Record<
    MessageDelivery,
    Readonly<{ label: string; className: string }>
  >
> = {
  pending: {
    label: 'Processing your request.',
    className: 'text-cyan-200',
  },
  streaming: {
    label: 'Delivering an approved response.',
    className: 'text-cyan-200',
  },
  complete: {
    label: 'Response complete.',
    className: 'text-emerald-300',
  },
  interrupted: {
    label: 'Incomplete response - delivery was interrupted.',
    className: 'text-amber-200',
  },
  cancelled: {
    label: 'Response cancelled.',
    className: 'text-slate-300',
  },
  failed: {
    label: 'Response unavailable.',
    className: 'text-rose-200',
  },
}

export function MessageBubble({
  message,
  showRetry = false,
  retryDisabled = false,
  onRetry,
}: MessageBubbleProps) {
  const isCustomer = message.role === 'user'
  const author = isCustomer ? 'You' : 'Support guide'
  const delivery = DELIVERY_PRESENTATION[message.delivery]
  const metadata = isCustomer ? undefined : message.metadata
  const requestInProgress =
    message.delivery === 'pending' || message.delivery === 'streaming'

  return (
    <li
      className={`flex min-w-0 ${isCustomer ? 'justify-end' : 'justify-start'}`}
    >
      <article
        className={`min-w-0 max-w-full rounded-2xl border px-4 py-3 shadow-sm sm:max-w-[82%] ${
          isCustomer
            ? 'border-cyan-300/25 bg-cyan-300/10 text-cyan-50'
            : 'border-white/10 bg-slate-950/70 text-slate-100'
        }`}
        aria-label={`${author} message`}
        aria-busy={!isCustomer && requestInProgress}
      >
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
          {author}
        </p>
        {message.content.length > 0 ? (
          <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 [overflow-wrap:anywhere] sm:text-base">
            {message.content}
          </p>
        ) : null}
        {metadata !== undefined ? (
          <>
            <HumanAssistanceBanner
              requiresHuman={metadata.requires_human}
              riskLevel={metadata.risk_level}
            />
            <ResponseMetadata metadata={metadata} />
          </>
        ) : null}
        {!isCustomer ? (
          <>
            <p
              className={`mt-3 text-xs font-semibold ${delivery.className}`}
              role="status"
              aria-live="polite"
              aria-atomic="true"
            >
              {delivery.label}
            </p>
            {showRetry && message.delivery === 'cancelled' ? (
              <button
                className="mt-3 min-h-11 w-full rounded-xl border border-white/15 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
                type="button"
                disabled={retryDisabled}
                onClick={onRetry}
              >
                Retry cancelled request
              </button>
            ) : null}
          </>
        ) : null}
      </article>
    </li>
  )
}
