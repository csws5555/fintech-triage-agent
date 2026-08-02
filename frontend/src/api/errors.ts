export const API_CLIENT_ERROR_KIND_VALUES = [
  'configuration',
  'validation',
  'http',
  'network',
  'timeout',
  'cancelled',
  'invalid_response',
] as const

export type ApiClientErrorKind =
  (typeof API_CLIENT_ERROR_KIND_VALUES)[number]

export type ApiClientErrorOptions = Readonly<{
  kind: ApiClientErrorKind
  code: string
  message: string
  retryable: boolean
  status?: number
  requestId?: string
}>

/** A normalized, presentation-safe failure from the frontend API boundary. */
export class ApiClientError extends Error {
  readonly kind: ApiClientErrorKind
  readonly code: string
  readonly retryable: boolean
  readonly status: number | null
  readonly requestId: string | null

  constructor(options: ApiClientErrorOptions) {
    super(options.message)
    this.name = 'ApiClientError'
    this.kind = options.kind
    this.code = options.code
    this.retryable = options.retryable
    this.status = options.status ?? null
    this.requestId = options.requestId ?? null
  }
}
