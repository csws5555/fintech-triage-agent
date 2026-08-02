import type { ReadinessComponents } from '../../../api/contracts'
import type { Availability } from '../chatTypes'

export type ServiceStatusProps = Readonly<{
  availability: Availability
  components: ReadinessComponents | null
  errorMessage: string | null
  onRetry(): void
}>

const COMPONENT_LABELS: readonly Readonly<{
  key: keyof ReadinessComponents
  label: string
}>[] = [
  { key: 'configuration', label: 'Configuration' },
  { key: 'classifier', label: 'Intent classifier' },
  { key: 'pipeline', label: 'Support pipeline' },
  { key: 'vector_store', label: 'Policy search' },
  { key: 'ollama_chat_model', label: 'Local response model' },
  { key: 'ollama_embedding_model', label: 'Local embedding model' },
]

const STATUS_PRESENTATION: Readonly<
  Record<
    Availability,
    Readonly<{
      title: string
      description: string
      dotClass: string
      panelClass: string
    }>
  >
> = {
  checking: {
    title: 'Checking local service',
    description: 'Confirming whether the support service is available.',
    dotClass: 'bg-sky-400',
    panelClass: 'border-sky-300/25 bg-sky-300/10',
  },
  ready: {
    title: 'Service ready',
    description: 'The local support service is available.',
    dotClass: 'bg-emerald-400',
    panelClass: 'border-emerald-300/25 bg-emerald-300/10',
  },
  degraded: {
    title: 'Limited service',
    description:
      'Some local features are unavailable. Safe guidance and fallbacks remain available.',
    dotClass: 'bg-amber-300',
    panelClass: 'border-amber-300/30 bg-amber-300/10',
  },
  unavailable: {
    title: 'Service unavailable',
    description:
      'The local support service is not available. Check the backend, then try again.',
    dotClass: 'bg-rose-400',
    panelClass: 'border-rose-300/30 bg-rose-300/10',
  },
}

export function ServiceStatus({
  availability,
  components,
  errorMessage,
  onRetry,
}: ServiceStatusProps) {
  const presentation = STATUS_PRESENTATION[availability]

  return (
    <section
      className={`rounded-2xl border p-4 ${presentation.panelClass}`}
      aria-labelledby="service-status-title"
    >
      <div className="flex items-start gap-3" role="status" aria-live="polite">
        <span
          className={`mt-1.5 size-2.5 shrink-0 rounded-full ${presentation.dotClass} ${availability === 'checking' ? 'animate-pulse' : ''}`}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <h2
            id="service-status-title"
            className="text-sm font-semibold text-white"
          >
            {presentation.title}
          </h2>
          <p className="mt-1 text-sm leading-6 text-slate-300">
            {availability === 'unavailable' && errorMessage !== null
              ? errorMessage
              : presentation.description}
          </p>
        </div>
      </div>

      {components !== null ? (
        <details className="mt-3 border-t border-white/10 pt-3 text-sm">
          <summary className="cursor-pointer rounded-md font-medium text-slate-200 marker:text-slate-400">
            Service details
          </summary>
          <ul className="mt-3 grid gap-2" aria-label="Service components">
            {COMPONENT_LABELS.map(({ key, label }) => {
              const componentStatus = components[key]
              return (
                <li
                  className="flex items-center justify-between gap-4 text-slate-300"
                  key={key}
                >
                  <span>{label}</span>
                  <span className="font-medium text-slate-100">
                    {componentStatus === 'ready' ? 'Ready' : 'Unavailable'}
                  </span>
                </li>
              )
            })}
          </ul>
        </details>
      ) : null}

      {availability === 'unavailable' ? (
        <button
          className="mt-4 min-h-11 rounded-xl border border-white/20 bg-white/10 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/15 disabled:cursor-wait disabled:opacity-60"
          type="button"
          onClick={onRetry}
        >
          Retry connection
        </button>
      ) : null}
    </section>
  )
}
