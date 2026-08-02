import { createStore, type StoreApi } from 'zustand/vanilla'

import type { ApiClient } from '../../api/client'
import {
  MAX_CHAT_MESSAGE_CHARACTERS,
  type PublicAnswerMetadata,
  type ReadinessResponse,
  type StreamChunkEvent,
} from '../../api/contracts'
import { ApiClientError } from '../../api/errors'
import type { CompletedStream } from '../../api/sseParser'
import {
  canTransitionRequestPhase,
  isActiveRequestPhase,
} from './chatStateMachine'
import type {
  Availability,
  ChatConversationState,
  ChatInputError,
  ChatMessage,
  ChatRequestError,
} from './chatTypes'

export type ChatStoreActions = Readonly<{
  initializeAvailability(): Promise<Availability>
  setDraft(draft: string): void
  submitMessage(): Promise<boolean>
  acceptMetadata(
    operationId: string,
    metadata: PublicAnswerMetadata,
  ): boolean
  appendChunk(operationId: string, chunk: StreamChunkEvent): boolean
  completeStream(operationId: string, completed: CompletedStream): boolean
  failRequest(operationId: string, error: unknown): boolean
  cancelRequest(): boolean
  retryRequest(): Promise<boolean>
  clearConversation(): void
}>

export type ChatStore = ChatConversationState & ChatStoreActions

export type CreateChatStoreOptions = Readonly<{
  apiClient: ApiClient
  idFactory?: () => string
  abortControllerFactory?: () => AbortController
}>

const MANDATORY_READINESS_COMPONENTS = [
  'configuration',
  'classifier',
  'pipeline',
] as const

const INITIAL_CONVERSATION_STATE: ChatConversationState = Object.freeze({
  messages: Object.freeze([]),
  draft: '',
  inputError: null,
  availability: 'checking',
  readinessComponents: null,
  operationId: null,
  activeTurnId: null,
  requestPhase: 'idle',
  nextExpectedSequence: 0,
  serverRequestId: null,
  abortController: null,
  error: null,
  retrySourceText: null,
  retryTurnId: null,
})

function defaultIdFactory(): string {
  return globalThis.crypto.randomUUID()
}

function inputError(message: string): ChatInputError | null {
  if (!message.trim()) {
    return Object.freeze({
      code: 'empty_message',
      message: 'Enter a message before sending.',
    })
  }
  if (message.trim().length > MAX_CHAT_MESSAGE_CHARACTERS) {
    return Object.freeze({
      code: 'message_too_long',
      message: `Messages must be ${MAX_CHAT_MESSAGE_CHARACTERS.toLocaleString(
        'en-US',
      )} characters or fewer.`,
    })
  }
  return null
}

function normalizedError(error: unknown): ChatRequestError {
  if (error instanceof ApiClientError) {
    return Object.freeze({
      kind: error.kind,
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      status: error.status,
      requestId: error.requestId,
    })
  }
  return Object.freeze({
    kind: 'invalid_response',
    code: 'unexpected_client_error',
    message: 'The request could not be completed.',
    retryable: false,
    status: null,
    requestId: null,
  })
}

function availabilityFrom(readiness: ReadinessResponse): Availability {
  const mandatoryReady = MANDATORY_READINESS_COMPONENTS.every(
    (component) => readiness.components[component] === 'ready',
  )
  const allReady = Object.values(readiness.components).every(
    (component) => component === 'ready',
  )
  if (readiness.status === 'ready') {
    return mandatoryReady && allReady ? 'ready' : 'unavailable'
  }
  return mandatoryReady && !allReady ? 'degraded' : 'unavailable'
}

function freezeMetadata(
  metadata: PublicAnswerMetadata,
): PublicAnswerMetadata {
  return Object.freeze({ ...metadata })
}

function freezeMessage(message: ChatMessage): ChatMessage {
  return Object.freeze(message)
}

function replaceAssistantMessage(
  messages: readonly ChatMessage[],
  turnId: string,
  update: (message: ChatMessage) => ChatMessage,
): readonly ChatMessage[] {
  return Object.freeze(
    messages.map((message) =>
      message.turnId === turnId && message.role === 'assistant'
        ? freezeMessage(update(message))
        : message,
    ),
  )
}

function validIdentifier(value: string): boolean {
  return typeof value === 'string' && value.trim().length > 0
}

/** Create one memory-only chat state authority with an injected API boundary. */
export function createChatStore({
  apiClient,
  idFactory = defaultIdFactory,
  abortControllerFactory = () => new AbortController(),
}: CreateChatStoreOptions): StoreApi<ChatStore> {
  if (
    typeof apiClient !== 'object' ||
    apiClient === null ||
    typeof apiClient.checkReadiness !== 'function' ||
    typeof apiClient.streamChatMessage !== 'function' ||
    typeof idFactory !== 'function' ||
    typeof abortControllerFactory !== 'function'
  ) {
    throw new TypeError('A valid API client and store factories are required.')
  }

  let availabilityCheckVersion = 0

  return createStore<ChatStore>()((set, get) => {
    const newId = (kind: 'operation' | 'turn' | 'message'): string => {
      const value = idFactory()
      if (!validIdentifier(value)) {
        throw new TypeError('The chat ID factory returned an invalid value.')
      }
      return `${kind}-${value}`
    }

    const finishActiveOperation = () => ({
      operationId: null,
      activeTurnId: null,
      nextExpectedSequence: 0,
      serverRequestId: null,
      abortController: null,
    })

    const cancelOperation = (operationId: string): boolean => {
      const state = get()
      if (
        state.operationId !== operationId ||
        state.activeTurnId === null ||
        !isActiveRequestPhase(state.requestPhase) ||
        !canTransitionRequestPhase(state.requestPhase, 'cancelled')
      ) {
        return false
      }
      const turnId = state.activeTurnId
      set({
        messages: replaceAssistantMessage(
          state.messages,
          turnId,
          (message) => ({ ...message, delivery: 'cancelled' }),
        ),
        requestPhase: 'cancelled',
        error: null,
        ...finishActiveOperation(),
      })
      return true
    }

    const runOperation = async (
      sourceText: string,
      existingTurnId: string | null,
    ): Promise<boolean> => {
      const state = get()
      if (
        isActiveRequestPhase(state.requestPhase) ||
        !canTransitionRequestPhase(state.requestPhase, 'processing') ||
        (state.availability !== 'ready' &&
          state.availability !== 'degraded')
      ) {
        return false
      }

      const operationId = newId('operation')
      const turnId = existingTurnId ?? newId('turn')
      const abortController = abortControllerFactory()
      if (!(abortController instanceof AbortController)) {
        throw new TypeError(
          'The abort-controller factory returned an invalid value.',
        )
      }

      let messages: readonly ChatMessage[]
      if (existingTurnId === null) {
        const userMessage = freezeMessage({
          id: newId('message'),
          turnId,
          role: 'user',
          content: sourceText,
          delivery: 'complete',
        })
        const assistantMessage = freezeMessage({
          id: newId('message'),
          turnId,
          role: 'assistant',
          content: '',
          delivery: 'pending',
        })
        messages = Object.freeze([
          ...state.messages,
          userMessage,
          assistantMessage,
        ])
      } else {
        const hasRetryTurn = state.messages.some(
          (message) => message.turnId === turnId,
        )
        if (!hasRetryTurn) {
          return false
        }
        messages = replaceAssistantMessage(
          state.messages,
          turnId,
          (message) => ({
            id: message.id,
            turnId: message.turnId,
            role: 'assistant',
            content: '',
            delivery: 'pending',
          }),
        )
      }

      set({
        messages,
        draft: existingTurnId === null ? '' : state.draft,
        inputError: null,
        operationId,
        activeTurnId: turnId,
        requestPhase: 'processing',
        nextExpectedSequence: 0,
        serverRequestId: null,
        abortController,
        error: null,
        retrySourceText: sourceText,
        retryTurnId: turnId,
      })

      try {
        const completed = await apiClient.streamChatMessage(
          sourceText,
          {
            onMetadata(metadata) {
              get().acceptMetadata(operationId, metadata)
            },
            onChunk(chunk) {
              get().appendChunk(operationId, chunk)
            },
          },
          { signal: abortController.signal },
        )
        get().completeStream(operationId, completed)
      } catch (error: unknown) {
        if (error instanceof ApiClientError && error.kind === 'cancelled') {
          cancelOperation(operationId)
        } else {
          get().failRequest(operationId, error)
        }
      }
      return true
    }

    return {
      ...INITIAL_CONVERSATION_STATE,

      async initializeAvailability() {
        const checkVersion = ++availabilityCheckVersion
        set({
          availability: 'checking',
          readinessComponents: null,
          error: null,
        })
        try {
          const readiness = await apiClient.checkReadiness()
          if (checkVersion !== availabilityCheckVersion) {
            return get().availability
          }
          const availability = availabilityFrom(readiness)
          set({
            availability,
            readinessComponents: Object.freeze({
              ...readiness.components,
            }),
            error: null,
          })
          return availability
        } catch (error: unknown) {
          if (checkVersion !== availabilityCheckVersion) {
            return get().availability
          }
          set({
            availability: 'unavailable',
            readinessComponents: null,
            error: normalizedError(error),
          })
          return 'unavailable'
        }
      },

      setDraft(draft) {
        if (typeof draft !== 'string') {
          return
        }
        set({ draft, inputError: null })
      },

      async submitMessage() {
        const state = get()
        if (isActiveRequestPhase(state.requestPhase)) {
          return false
        }
        if (
          state.availability !== 'ready' &&
          state.availability !== 'degraded'
        ) {
          set({
            error: Object.freeze({
              kind: 'network',
              code: 'service_unavailable',
              message: 'The local support service is unavailable.',
              retryable: true,
              status: null,
              requestId: null,
            }),
          })
          return false
        }

        const validationError = inputError(state.draft)
        if (validationError !== null) {
          set({ inputError: validationError })
          return false
        }
        return runOperation(state.draft.trim(), null)
      },

      acceptMetadata(operationId, metadata) {
        const state = get()
        if (
          state.operationId !== operationId ||
          state.activeTurnId === null ||
          state.requestPhase !== 'processing' ||
          state.serverRequestId !== null ||
          !validIdentifier(metadata.request_id) ||
          !canTransitionRequestPhase('processing', 'streaming')
        ) {
          return false
        }
        const turnId = state.activeTurnId
        const acceptedMetadata = freezeMetadata(metadata)
        set({
          messages: replaceAssistantMessage(
            state.messages,
            turnId,
            (message) => ({
              ...message,
              delivery: 'streaming',
              requestId: metadata.request_id,
              metadata: acceptedMetadata,
            }),
          ),
          requestPhase: 'streaming',
          serverRequestId: metadata.request_id,
        })
        return true
      },

      appendChunk(operationId, chunk) {
        const state = get()
        if (
          state.operationId !== operationId ||
          state.activeTurnId === null ||
          state.requestPhase !== 'streaming' ||
          state.serverRequestId === null ||
          chunk.request_id !== state.serverRequestId ||
          chunk.sequence !== state.nextExpectedSequence
        ) {
          return false
        }
        const turnId = state.activeTurnId
        set({
          messages: replaceAssistantMessage(
            state.messages,
            turnId,
            (message) => ({
              ...message,
              content: message.content + chunk.text,
            }),
          ),
          nextExpectedSequence: state.nextExpectedSequence + 1,
        })
        return true
      },

      completeStream(operationId, completed) {
        const state = get()
        if (
          state.operationId !== operationId ||
          state.activeTurnId === null ||
          state.requestPhase !== 'streaming' ||
          state.serverRequestId === null ||
          completed.requestId !== state.serverRequestId ||
          completed.chunks !== state.nextExpectedSequence ||
          !canTransitionRequestPhase(state.requestPhase, 'completed')
        ) {
          return false
        }
        const turnId = state.activeTurnId
        set({
          messages: replaceAssistantMessage(
            state.messages,
            turnId,
            (message) => ({ ...message, delivery: 'complete' }),
          ),
          requestPhase: 'completed',
          error: null,
          retrySourceText: null,
          retryTurnId: null,
          ...finishActiveOperation(),
        })
        return true
      },

      failRequest(operationId, error) {
        const state = get()
        if (
          state.operationId !== operationId ||
          state.activeTurnId === null ||
          !isActiveRequestPhase(state.requestPhase) ||
          !canTransitionRequestPhase(state.requestPhase, 'failed')
        ) {
          return false
        }
        const turnId = state.activeTurnId
        const safeError = normalizedError(error)
        set({
          messages: replaceAssistantMessage(
            state.messages,
            turnId,
            (message) => ({
              ...message,
              delivery:
                message.content.length > 0 ? 'interrupted' : 'failed',
              ...(message.requestId === undefined &&
              safeError.requestId !== null
                ? { requestId: safeError.requestId }
                : {}),
            }),
          ),
          requestPhase: 'failed',
          error: safeError,
          ...finishActiveOperation(),
        })
        return true
      },

      cancelRequest() {
        const state = get()
        if (
          state.operationId === null ||
          state.abortController === null ||
          !isActiveRequestPhase(state.requestPhase)
        ) {
          return false
        }
        const { operationId, abortController } = state
        abortController.abort()
        return cancelOperation(operationId)
      },

      async retryRequest() {
        const state = get()
        if (
          (state.requestPhase !== 'failed' &&
            state.requestPhase !== 'cancelled') ||
          state.retrySourceText === null ||
          state.retryTurnId === null
        ) {
          return false
        }
        return runOperation(state.retrySourceText, state.retryTurnId)
      },

      clearConversation() {
        const state = get()
        if (state.abortController !== null) {
          state.abortController.abort()
        }
        set({
          messages: Object.freeze([]),
          draft: '',
          inputError: null,
          operationId: null,
          activeTurnId: null,
          requestPhase: 'idle',
          nextExpectedSequence: 0,
          serverRequestId: null,
          abortController: null,
          error: null,
          retrySourceText: null,
          retryTurnId: null,
        })
      },
    }
  })
}
