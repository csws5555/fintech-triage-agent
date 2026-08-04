// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { describe, expect, it } from 'vitest'

import {
  PUBLIC_STATUS_VALUES,
  RESPONSE_MODE_VALUES,
  RISK_LEVEL_VALUES,
  type PublicAnswerMetadata,
  type PublicStatus,
  type ResponseMode,
  type RiskLevel,
} from '../../../api/contracts'
import { ResponseMetadata } from '../components/ResponseMetadata'

const STATUS_LABELS: Readonly<Record<PublicStatus, string>> = {
  answered: 'Answered',
  clarification_required: 'Needs clarification',
  safety_guidance: 'Safety guidance',
  request_refused: 'Request refused',
  action_not_confirmed: 'Action not confirmed',
  unsupported: 'Unsupported',
  service_fallback: 'Limited service',
}

const RISK_LABELS: Readonly<Record<RiskLevel, string>> = {
  low: 'Low priority',
  medium: 'Medium priority',
  high: 'High priority',
  critical: 'Critical priority',
}

const RESPONSE_MODE_LABELS: Readonly<Record<ResponseMode, string>> = {
  static_fallback: 'Safe fallback',
  deterministic_clarification: 'Clarification',
  deterministic_safety: 'Deterministic guidance',
  grounded_generation: 'Generated from approved policy',
}

function metadata(
  overrides: Partial<PublicAnswerMetadata> = {},
): PublicAnswerMetadata {
  return {
    request_id: 'request-reference-123',
    status: 'answered',
    response_mode: 'grounded_generation',
    risk_level: 'low',
    requires_human: false,
    ...overrides,
  }
}

describe('ResponseMetadata', () => {
  it.each(PUBLIC_STATUS_VALUES)(
    'maps the %s status to reviewed customer-facing text',
    (status) => {
      render(<ResponseMetadata metadata={metadata({ status })} />)

      expect(screen.getByText(STATUS_LABELS[status])).toBeVisible()
    },
  )

  it.each(RISK_LEVEL_VALUES)(
    'maps the %s risk to visible text and an icon',
    (riskLevel) => {
      render(
        <ResponseMetadata
          metadata={metadata({ risk_level: riskLevel })}
        />,
      )

      expect(screen.getByText(RISK_LABELS[riskLevel])).toBeVisible()
      if (riskLevel === 'critical') {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Critical priority',
        )
      }
    },
  )

  it.each(RESPONSE_MODE_VALUES)(
    'maps the %s response mode descriptively',
    async (responseMode) => {
      const user = userEvent.setup()
      render(
        <ResponseMetadata
          metadata={metadata({ response_mode: responseMode })}
        />,
      )

      await user.click(screen.getByText('Response details'))
      expect(screen.getByText(RESPONSE_MODE_LABELS[responseMode])).toBeVisible()
    },
  )

  it('shows a safe selectable request reference and action limitation', async () => {
    const user = userEvent.setup()
    render(<ResponseMetadata metadata={metadata()} />)

    await user.click(screen.getByText('Response details'))
    expect(screen.getByText('request-reference-123')).toHaveClass(
      'select-all',
      'break-all',
    )
    expect(
      screen.getByText(/do not confirm that an account action/i),
    ).toBeVisible()
    expect(document.body).not.toHaveTextContent('reason_code')
    expect(document.body).not.toHaveTextContent('policy_id')
    expect(document.body).not.toHaveTextContent('confidence')
  })

  it('has no detectable axe violations', async () => {
    const { container } = render(
      <ResponseMetadata
        metadata={metadata({
          status: 'safety_guidance',
          response_mode: 'deterministic_safety',
          risk_level: 'critical',
          requires_human: true,
        })}
      />,
    )

    const results = await axe(container, {
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(results.violations).toEqual([])
  })

  it('does not create duplicate landmarks across multiple responses', async () => {
    const { container } = render(
      <>
        <ResponseMetadata metadata={metadata({ request_id: 'request-one' })} />
        <ResponseMetadata
          metadata={metadata({
            request_id: 'request-two',
            status: 'unsupported',
            response_mode: 'static_fallback',
            requires_human: true,
          })}
        />
      </>,
    )

    const results = await axe(container, {
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(results.violations).toEqual([])
    expect(screen.queryByRole('region')).toBeNull()
  })
})
