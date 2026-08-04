import type {
  PublicAnswerMetadata,
  PublicStatus,
  ResponseMode,
  RiskLevel,
} from '../../../api/contracts'

export type ResponseMetadataProps = Readonly<{
  metadata: PublicAnswerMetadata
}>

const STATUS_PRESENTATION: Readonly<
  Record<
    PublicStatus,
    Readonly<{
      label: string
      description: string
      className: string
    }>
  >
> = {
  answered: {
    label: 'Answered',
    description: 'The support service returned an approved answer.',
    className: 'border-emerald-300/30 bg-emerald-300/10 text-emerald-100',
  },
  clarification_required: {
    label: 'Needs clarification',
    description: 'More detail is needed before this can be answered safely.',
    className: 'border-sky-300/30 bg-sky-300/10 text-sky-100',
  },
  safety_guidance: {
    label: 'Safety guidance',
    description: 'Review the safety steps in this response.',
    className: 'border-orange-300/30 bg-orange-300/10 text-orange-100',
  },
  request_refused: {
    label: 'Request refused',
    description: 'This request cannot be handled by the prototype.',
    className: 'border-slate-300/30 bg-slate-300/10 text-slate-100',
  },
  action_not_confirmed: {
    label: 'Action not confirmed',
    description: 'The prototype cannot verify whether an account action occurred.',
    className: 'border-amber-300/30 bg-amber-300/10 text-amber-100',
  },
  unsupported: {
    label: 'Unsupported',
    description: 'This topic is outside the approved prototype scope.',
    className: 'border-slate-300/30 bg-slate-300/10 text-slate-100',
  },
  service_fallback: {
    label: 'Limited service',
    description: 'Only limited approved guidance is available.',
    className: 'border-amber-300/30 bg-amber-300/10 text-amber-100',
  },
}

const RISK_PRESENTATION: Readonly<
  Record<
    RiskLevel,
    Readonly<{ label: string; icon: string; className: string }>
  >
> = {
  low: {
    label: 'Low priority',
    icon: '●',
    className: 'border-slate-300/25 bg-slate-300/10 text-slate-100',
  },
  medium: {
    label: 'Medium priority',
    icon: '◆',
    className: 'border-yellow-300/30 bg-yellow-300/10 text-yellow-100',
  },
  high: {
    label: 'High priority',
    icon: '▲',
    className: 'border-orange-300/35 bg-orange-300/15 text-orange-100',
  },
  critical: {
    label: 'Critical priority',
    icon: '!',
    className: 'border-rose-300/40 bg-rose-300/15 text-rose-50',
  },
}

const RESPONSE_MODE_LABELS: Readonly<Record<ResponseMode, string>> = {
  static_fallback: 'Safe fallback',
  deterministic_clarification: 'Clarification',
  deterministic_safety: 'Deterministic guidance',
  grounded_generation: 'Generated from approved policy',
}

export function ResponseMetadata({ metadata }: ResponseMetadataProps) {
  const status = STATUS_PRESENTATION[metadata.status]
  const risk = RISK_PRESENTATION[metadata.risk_level]
  const isCritical = metadata.risk_level === 'critical'
  const announceCritical = isCritical && !metadata.requires_human

  return (
    <div className="mt-4 min-w-0 border-t border-white/10 pt-4">
      <div className="flex flex-wrap gap-2">
        <span
          className={`inline-flex min-h-8 max-w-full items-center break-words rounded-full border px-3 py-1 text-xs font-bold ${status.className}`}
        >
          {status.label}
        </span>
        <span
          className={`inline-flex min-h-8 max-w-full items-center gap-1.5 break-words rounded-full border px-3 py-1 text-xs font-bold ${risk.className}`}
          {...(announceCritical
            ? { role: 'alert', 'aria-live': 'assertive' as const }
            : {})}
        >
          <span aria-hidden="true">{risk.icon}</span>
          {risk.label}
        </span>
      </div>

      <p className="mt-3 text-sm leading-6 text-slate-300">
        {status.description}
      </p>

      <details className="mt-3 min-w-0 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm">
        <summary className="cursor-pointer rounded-md font-semibold text-slate-200 marker:text-slate-400">
          Response details
        </summary>
        <dl className="mt-3 grid gap-3 text-slate-300">
          <div>
            <dt className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">
              Response type
            </dt>
            <dd className="mt-1">
              {RESPONSE_MODE_LABELS[metadata.response_mode]}
            </dd>
          </div>
          <div className="min-w-0">
            <dt className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">
              Request reference
            </dt>
            <dd className="mt-1 select-all break-all font-mono text-xs text-slate-200">
              {metadata.request_id}
            </dd>
          </div>
        </dl>
        <p className="mt-3 border-t border-white/10 pt-3 text-xs leading-5 text-slate-400">
          These details describe the approved response. They do not confirm
          that an account action or support handoff occurred.
        </p>
      </details>
    </div>
  )
}
