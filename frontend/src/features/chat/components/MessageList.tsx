import { useState } from 'react'

import type { ChatMessage } from '../chatTypes'
import { useConversationScroll } from '../hooks/useConversationScroll'
import { MessageBubble } from './MessageBubble'

export type MessageListProps = Readonly<{
  messages: readonly ChatMessage[]
  onClear(): void
}>

export function MessageList({ messages, onClear }: MessageListProps) {
  const [confirmingClear, setConfirmingClear] = useState(false)
  const endRef = useConversationScroll(messages)
  const hasMessages = messages.length > 0

  return (
    <section
      className="rounded-3xl border border-white/10 bg-slate-900/70 p-4 sm:p-6"
      aria-labelledby="conversation-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2
            id="conversation-title"
            className="text-lg font-semibold text-white"
          >
            Conversation
          </h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-400">
            Each request is handled independently. Earlier messages are not
            sent with your next request.
          </p>
        </div>

        {hasMessages ? (
          <button
            className="min-h-11 rounded-xl border border-white/15 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-200 transition hover:border-white/25 hover:bg-white/10"
            type="button"
            onClick={() => setConfirmingClear(true)}
          >
            Clear conversation
          </button>
        ) : null}
      </div>

      {hasMessages ? (
        <ol
          className="mt-5 grid max-h-[34rem] gap-4 overflow-y-auto pr-1"
          aria-label="Conversation messages"
        >
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          <li aria-hidden="true">
            <div ref={endRef} />
          </li>
        </ol>
      ) : (
        <div className="mt-5 rounded-2xl border border-dashed border-white/15 bg-slate-950/35 px-4 py-8 text-center">
          <p className="font-medium text-slate-200">No messages yet</p>
          <p className="mt-1 text-sm leading-6 text-slate-400">
            Ask one supported banking question to start an in-memory
            conversation.
          </p>
        </div>
      )}

      {hasMessages && confirmingClear ? (
        <div
          className="mt-4 rounded-2xl border border-rose-300/25 bg-rose-300/10 p-4"
          role="alertdialog"
          aria-labelledby="clear-conversation-title"
          aria-describedby="clear-conversation-description"
        >
          <h3
            id="clear-conversation-title"
            className="font-semibold text-rose-50"
          >
            Clear this conversation?
          </h3>
          <p
            id="clear-conversation-description"
            className="mt-1 text-sm leading-6 text-rose-50/80"
          >
            This removes every message held in memory and stops any active
            request.
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            <button
              className="min-h-11 rounded-xl bg-rose-200 px-4 py-2 text-sm font-semibold text-rose-950 transition hover:bg-rose-100"
              type="button"
              onClick={() => {
                setConfirmingClear(false)
                onClear()
              }}
            >
              Clear messages
            </button>
            <button
              className="min-h-11 rounded-xl border border-white/15 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:bg-white/10"
              type="button"
              onClick={() => setConfirmingClear(false)}
            >
              Keep conversation
            </button>
          </div>
        </div>
      ) : null}
    </section>
  )
}
