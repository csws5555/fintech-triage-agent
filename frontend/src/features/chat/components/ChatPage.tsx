import { useEffect, useRef } from 'react'
import { useStore } from 'zustand'
import type { StoreApi } from 'zustand/vanilla'

import type { ChatStore } from '../chatStore'
import { isActiveRequestPhase } from '../chatStateMachine'
import { ChatComposer } from './ChatComposer'
import { MessageList } from './MessageList'
import { ServiceStatus } from './ServiceStatus'

export type ChatPageProps = Readonly<{
  store: StoreApi<ChatStore>
}>

export function ChatPage({ store }: ChatPageProps) {
  const availability = useStore(store, (state) => state.availability)
  const components = useStore(
    store,
    (state) => state.readinessComponents,
  )
  const errorMessage = useStore(
    store,
    (state) => state.error?.message ?? null,
  )
  const initializeAvailability = useStore(
    store,
    (state) => state.initializeAvailability,
  )
  const messages = useStore(store, (state) => state.messages)
  const draft = useStore(store, (state) => state.draft)
  const inputError = useStore(store, (state) => state.inputError)
  const requestPhase = useStore(store, (state) => state.requestPhase)
  const setDraft = useStore(store, (state) => state.setDraft)
  const submitMessage = useStore(store, (state) => state.submitMessage)
  const clearConversation = useStore(
    store,
    (state) => state.clearConversation,
  )
  const startupCheckStarted = useRef(false)
  const requestActive = isActiveRequestPhase(requestPhase)
  const composerDisabled =
    availability === 'checking' || availability === 'unavailable'

  useEffect(() => {
    if (startupCheckStarted.current) {
      return
    }
    startupCheckStarted.current = true
    void initializeAvailability()
  }, [initializeAvailability])

  return (
    <div className="min-h-svh bg-slate-950 text-slate-100">
      <a
        className="fixed left-3 top-3 z-50 -translate-y-24 rounded-lg bg-white px-4 py-2 font-semibold text-slate-950 shadow-lg transition focus:translate-y-0"
        href="#main-content"
      >
        Skip to main content
      </a>

      <header className="border-b border-white/10 bg-slate-950/95">
        <div className="mx-auto grid w-full max-w-5xl gap-5 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-center lg:px-8">
          <div className="min-w-0">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">
              Local-only demo
            </p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white sm:text-3xl">
              Fintech Support Triage
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
              A fictional portfolio prototype for reviewed support guidance.
            </p>
          </div>

          <ServiceStatus
            availability={availability}
            components={components}
            errorMessage={errorMessage}
            onRetry={() => {
              void initializeAvailability()
            }}
          />
        </div>
      </header>

      <main
        id="main-content"
        className="mx-auto grid w-full max-w-5xl gap-5 px-4 py-6 sm:px-6 sm:py-8 lg:px-8"
      >
        <section
          className="overflow-hidden rounded-3xl border border-cyan-300/20 bg-gradient-to-br from-cyan-300/10 via-slate-900 to-slate-900 p-6 shadow-2xl shadow-slate-950/35 sm:p-8"
          aria-labelledby="prototype-notice-title"
        >
          <p className="text-sm font-semibold text-cyan-200">
            Before you continue
          </p>
          <h2
            id="prototype-notice-title"
            className="mt-2 text-xl font-semibold tracking-tight text-white sm:text-2xl"
          >
            Guidance only - no account access
          </h2>
          <p className="mt-3 max-w-3xl leading-7 text-slate-300">
            This prototype cannot access accounts, view transactions, or
            perform or confirm actions such as freezing a card, approving a
            refund, filing a dispute, or ordering a replacement.
          </p>
          <div className="mt-5 rounded-2xl border border-amber-300/25 bg-amber-300/10 p-4">
            <p className="font-semibold text-amber-100">
              Keep authentication details private
            </p>
            <p className="mt-1 text-sm leading-6 text-amber-50/80">
              Do not enter passwords, full PINs, one-time codes, security
              codes, or full card numbers.
            </p>
          </div>
        </section>

        <section
          className="rounded-3xl border border-white/10 bg-slate-900/70 p-6 sm:p-8"
          aria-labelledby="supported-topics-title"
        >
          <h2
            id="supported-topics-title"
            className="text-lg font-semibold text-white"
          >
            Prototype scope
          </h2>
          <p className="mt-2 max-w-3xl leading-7 text-slate-300">
            The local demo is limited to selected card delivery, replacement,
            fraud-safety, and international-fee support topics. Use an official
            support channel for account-specific help or urgent assistance.
          </p>
        </section>

        <MessageList
          messages={messages}
          onClear={clearConversation}
        />

        <ChatComposer
          draft={draft}
          inputError={inputError}
          disabled={composerDisabled}
          isSubmitting={requestActive}
          onDraftChange={setDraft}
          onSubmit={() => {
            void submitMessage()
          }}
        />
      </main>

      <footer className="mx-auto w-full max-w-5xl px-4 pb-8 text-sm leading-6 text-slate-500 sm:px-6 lg:px-8">
        Conversation data is kept in memory only and clears when this page is
        refreshed.
      </footer>
    </div>
  )
}
