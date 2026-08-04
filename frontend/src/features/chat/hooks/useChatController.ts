import { useEffect, useRef } from 'react'
import { useStore } from 'zustand'
import type { StoreApi } from 'zustand/vanilla'

import type { ReadinessComponents } from '../../../api/contracts'
import type { ChatStore } from '../chatStore'
import { isActiveRequestPhase } from '../chatStateMachine'
import type {
  Availability,
  ChatInputError,
  ChatMessage,
  RequestPhase,
} from '../chatTypes'

export type ChatController = Readonly<{
  availability: Availability
  components: ReadinessComponents | null
  availabilityErrorMessage: string | null
  requestError: ChatStore['error']
  messages: readonly ChatMessage[]
  draft: string
  inputError: ChatInputError | null
  requestPhase: RequestPhase
  retryTurnId: string | null
  requestActive: boolean
  composerDisabled: boolean
  initializeAvailability: ChatStore['initializeAvailability']
  setDraft: ChatStore['setDraft']
  submitMessage: ChatStore['submitMessage']
  cancelRequest: ChatStore['cancelRequest']
  retryRequest: ChatStore['retryRequest']
  editAndResendRequest: ChatStore['editAndResendRequest']
  clearConversation: ChatStore['clearConversation']
}>

/** Connect the chat page to its single store and guarded startup check. */
export function useChatController(
  store: StoreApi<ChatStore>,
): ChatController {
  const availability = useStore(store, (state) => state.availability)
  const components = useStore(
    store,
    (state) => state.readinessComponents,
  )
  const availabilityErrorMessage = useStore(
    store,
    (state) => state.availabilityError?.message ?? null,
  )
  const requestError = useStore(
    store,
    (state) => (state.requestPhase === 'failed' ? state.error : null),
  )
  const messages = useStore(store, (state) => state.messages)
  const draft = useStore(store, (state) => state.draft)
  const inputError = useStore(store, (state) => state.inputError)
  const requestPhase = useStore(store, (state) => state.requestPhase)
  const retryTurnId = useStore(store, (state) => state.retryTurnId)
  const initializeAvailability = useStore(
    store,
    (state) => state.initializeAvailability,
  )
  const setDraft = useStore(store, (state) => state.setDraft)
  const submitMessage = useStore(store, (state) => state.submitMessage)
  const cancelRequest = useStore(store, (state) => state.cancelRequest)
  const retryRequest = useStore(store, (state) => state.retryRequest)
  const editAndResendRequest = useStore(
    store,
    (state) => state.editAndResendRequest,
  )
  const clearConversation = useStore(
    store,
    (state) => state.clearConversation,
  )
  const startupCheckStarted = useRef(false)

  useEffect(() => {
    if (startupCheckStarted.current) {
      return
    }
    startupCheckStarted.current = true
    void initializeAvailability()
  }, [initializeAvailability])

  const requestActive = isActiveRequestPhase(requestPhase)
  return {
    availability,
    components,
    availabilityErrorMessage,
    requestError,
    messages,
    draft,
    inputError,
    requestPhase,
    retryTurnId,
    requestActive,
    composerDisabled:
      availability === 'checking' || availability === 'unavailable',
    initializeAvailability,
    setDraft,
    submitMessage,
    cancelRequest,
    retryRequest,
    editAndResendRequest,
    clearConversation,
  }
}
