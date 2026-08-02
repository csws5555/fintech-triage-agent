import type { ChatMessage } from '../chatTypes'

export type MessageBubbleProps = Readonly<{
  message: ChatMessage
}>

export function MessageBubble({ message }: MessageBubbleProps) {
  const isCustomer = message.role === 'user'
  const author = isCustomer ? 'You' : 'Support guide'

  return (
    <li
      className={`flex min-w-0 ${isCustomer ? 'justify-end' : 'justify-start'}`}
    >
      <article
        className={`min-w-0 max-w-[92%] rounded-2xl border px-4 py-3 shadow-sm sm:max-w-[82%] ${
          isCustomer
            ? 'border-cyan-300/25 bg-cyan-300/10 text-cyan-50'
            : 'border-white/10 bg-slate-950/70 text-slate-100'
        }`}
        aria-label={`${author} message`}
      >
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
          {author}
        </p>
        <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 [overflow-wrap:anywhere] sm:text-base">
          {message.content}
        </p>
      </article>
    </li>
  )
}
