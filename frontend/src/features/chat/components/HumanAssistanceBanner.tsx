import { useId } from 'react'

import type { RiskLevel } from '../../../api/contracts'

export type HumanAssistanceBannerProps = Readonly<{
  requiresHuman: boolean
  riskLevel: RiskLevel
}>

export function HumanAssistanceBanner({
  requiresHuman,
  riskLevel,
}: HumanAssistanceBannerProps) {
  const titleId = useId()

  if (!requiresHuman) {
    return null
  }

  const critical = riskLevel === 'critical'

  return (
    <div
      className={`mt-4 min-w-0 rounded-2xl border p-4 [overflow-wrap:anywhere] ${
        critical
          ? 'border-rose-300/40 bg-rose-300/15 text-rose-50'
          : 'border-amber-300/35 bg-amber-300/10 text-amber-50'
      }`}
      aria-labelledby={titleId}
      role="alert"
      aria-live="assertive"
      aria-atomic="true"
    >
      <h3 id={titleId} className="font-bold">
        Human assistance required
      </h3>
      <p className="mt-1 text-sm leading-6">
        Use an official support channel for account-specific help. This
        prototype has not contacted anyone and cannot perform or confirm
        account actions.
      </p>
      {critical ? (
        <p className="mt-2 text-sm font-semibold leading-6">
          For urgent safety or access concerns, contact the official emergency
          support route now.
        </p>
      ) : null}
    </div>
  )
}
