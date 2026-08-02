import {
  useRef,
  type FormEvent,
  type KeyboardEvent,
} from 'react'

import { MAX_CHAT_MESSAGE_CHARACTERS } from '../../../api/contracts'
import type { ChatInputError } from '../chatTypes'

export type ChatComposerProps = Readonly<{
  draft: string
  inputError: ChatInputError | null
  disabled: boolean
  isSubmitting: boolean
  onDraftChange(draft: string): void
  onSubmit(): void
}>

const DESCRIPTION_ID = 'chat-message-description'
const COUNTER_ID = 'chat-message-counter'
const ERROR_ID = 'chat-message-error'

export function ChatComposer({
  draft,
  inputError,
  disabled,
  isSubmitting,
  onDraftChange,
  onSubmit,
}: ChatComposerProps) {
  const formRef = useRef<HTMLFormElement>(null)
  const compositionActive = useRef(false)
  const normalizedLength = draft.trim().length
  const overLimit = normalizedLength > MAX_CHAT_MESSAGE_CHARACTERS
  const describedBy = [DESCRIPTION_ID, COUNTER_ID]
  if (inputError !== null) {
    describedBy.push(ERROR_ID)
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (disabled || isSubmitting || compositionActive.current) {
      return
    }
    onSubmit()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) {
      return
    }
    if (event.nativeEvent.isComposing || compositionActive.current) {
      return
    }
    event.preventDefault()
    formRef.current?.requestSubmit()
  }

  return (
    <section
      className="rounded-3xl border border-white/10 bg-slate-900/80 p-4 shadow-xl shadow-slate-950/20 sm:p-6"
      aria-labelledby="composer-title"
    >
      <h2 id="composer-title" className="text-lg font-semibold text-white">
        Ask for support guidance
      </h2>
      <p
        id={DESCRIPTION_ID}
        className="mt-1 text-sm leading-6 text-slate-400"
      >
        Send one self-contained question. Do not include authentication
        secrets.
      </p>

      <form ref={formRef} className="mt-4" onSubmit={handleSubmit}>
        <label
          className="text-sm font-semibold text-slate-200"
          htmlFor="chat-message"
        >
          Message
        </label>
        <textarea
          id="chat-message"
          className="mt-2 block min-h-32 w-full resize-y rounded-2xl border border-white/15 bg-slate-950/70 px-4 py-3 text-base leading-6 text-white shadow-inner shadow-black/20 placeholder:text-slate-500 disabled:cursor-not-allowed disabled:opacity-60"
          name="message"
          rows={4}
          value={draft}
          placeholder="For example: When should my first physical card arrive?"
          disabled={disabled || isSubmitting}
          aria-describedby={describedBy.join(' ')}
          aria-invalid={inputError !== null || overLimit}
          onChange={(event) => onDraftChange(event.currentTarget.value)}
          onCompositionStart={() => {
            compositionActive.current = true
          }}
          onCompositionEnd={() => {
            compositionActive.current = false
          }}
          onKeyDown={handleKeyDown}
        />

        <div className="mt-2 flex flex-wrap items-start justify-between gap-2 text-sm">
          <p
            id={COUNTER_ID}
            className={overLimit ? 'font-semibold text-rose-300' : 'text-slate-400'}
          >
            {normalizedLength.toLocaleString('en-US')} of{' '}
            {MAX_CHAT_MESSAGE_CHARACTERS.toLocaleString('en-US')} characters
          </p>
          <p className="text-slate-500">Enter to send · Shift+Enter for a new line</p>
        </div>

        {inputError !== null ? (
          <p
            id={ERROR_ID}
            className="mt-3 rounded-xl border border-rose-300/25 bg-rose-300/10 px-3 py-2 text-sm font-medium text-rose-100"
            role="alert"
          >
            {inputError.message}
          </p>
        ) : null}

        <div className="mt-4 flex justify-end">
          <button
            className="min-h-11 rounded-xl bg-cyan-300 px-5 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            type="submit"
            disabled={disabled || isSubmitting}
          >
            {isSubmitting ? 'Request in progress' : 'Send message'}
          </button>
        </div>
      </form>
    </section>
  )
}
