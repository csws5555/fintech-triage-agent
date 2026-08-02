const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000'

const ENDPOINT_PATHS = {
  liveness: '/health/live',
  readiness: '/health/ready',
  chat: '/api/v1/chat',
  chatStream: '/api/v1/chat/stream',
} as const

type ApiEnvironment = Readonly<
  Record<string, string | boolean | undefined>
>

export type ApiConfig = Readonly<{
  baseUrl: string
  livenessUrl: string
  readinessUrl: string
  chatUrl: string
  chatStreamUrl: string
}>

export class ApiConfigurationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ApiConfigurationError'
  }
}

function normalizedBaseUrl(rawValue: string | boolean | undefined): string {
  if (rawValue !== undefined && typeof rawValue !== 'string') {
    throw new ApiConfigurationError(
      'VITE_API_BASE_URL must be a string when configured.',
    )
  }

  const candidate = rawValue?.trim() || DEFAULT_API_BASE_URL
  let parsed: URL

  try {
    parsed = new URL(candidate)
  } catch {
    throw new ApiConfigurationError(
      'VITE_API_BASE_URL must be a valid absolute URL.',
    )
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new ApiConfigurationError(
      'VITE_API_BASE_URL must use http or https.',
    )
  }
  if (!parsed.hostname || parsed.origin === 'null') {
    throw new ApiConfigurationError(
      'VITE_API_BASE_URL must include a hostname.',
    )
  }
  if (parsed.username || parsed.password) {
    throw new ApiConfigurationError(
      'VITE_API_BASE_URL must not contain credentials.',
    )
  }
  if (candidate.includes('?') || candidate.includes('#')) {
    throw new ApiConfigurationError(
      'VITE_API_BASE_URL must not contain a query or fragment.',
    )
  }

  const authorityStart = candidate.indexOf('://') + 3
  const rawPathStart = candidate.indexOf('/', authorityStart)
  const rawPath = rawPathStart === -1 ? '' : candidate.slice(rawPathStart)
  if ((rawPath !== '' && rawPath !== '/') || parsed.pathname !== '/') {
    throw new ApiConfigurationError(
      'VITE_API_BASE_URL must be an origin without an embedded path.',
    )
  }

  return parsed.origin
}

export function loadApiConfig(
  environment: ApiEnvironment = import.meta.env,
): ApiConfig {
  const baseUrl = normalizedBaseUrl(environment.VITE_API_BASE_URL)

  return Object.freeze({
    baseUrl,
    livenessUrl: `${baseUrl}${ENDPOINT_PATHS.liveness}`,
    readinessUrl: `${baseUrl}${ENDPOINT_PATHS.readiness}`,
    chatUrl: `${baseUrl}${ENDPOINT_PATHS.chat}`,
    chatStreamUrl: `${baseUrl}${ENDPOINT_PATHS.chatStream}`,
  })
}
