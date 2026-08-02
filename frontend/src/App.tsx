import { useState } from 'react'
import type { StoreApi } from 'zustand/vanilla'

import { createApiClient } from './api/client'
import { loadApiConfig } from './api/config'
import { ChatPage } from './features/chat/components/ChatPage'
import {
  createChatStore,
  type ChatStore,
} from './features/chat/chatStore'

export type AppProps = Readonly<{
  store?: StoreApi<ChatStore>
}>

function createProductionStore(): StoreApi<ChatStore> {
  const { baseUrl } = loadApiConfig()
  return createChatStore({
    apiClient: createApiClient({ baseUrl }),
  })
}

function App({ store }: AppProps) {
  const [chatStore] = useState(() => store ?? createProductionStore())

  return <ChatPage store={chatStore} />
}

export default App
