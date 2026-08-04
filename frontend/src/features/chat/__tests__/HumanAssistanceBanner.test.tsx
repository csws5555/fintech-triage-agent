// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { describe, expect, it } from 'vitest'

import { RISK_LEVEL_VALUES } from '../../../api/contracts'
import { HumanAssistanceBanner } from '../components/HumanAssistanceBanner'

describe('HumanAssistanceBanner', () => {
  it('renders nothing when the backend does not require human help', () => {
    const { container } = render(
      <HumanAssistanceBanner requiresHuman={false} riskLevel="high" />,
    )

    expect(container).toBeEmptyDOMElement()
    expect(
      screen.queryByRole('heading', { name: 'Human assistance required' }),
    ).toBeNull()
  })

  it.each(RISK_LEVEL_VALUES)(
    'renders explicit no-handoff wording for %s risk when human help is required',
    (riskLevel) => {
      render(
        <HumanAssistanceBanner
          requiresHuman
          riskLevel={riskLevel}
        />,
      )

      expect(screen.getByRole('alert')).toHaveAccessibleName(
        'Human assistance required',
      )
      expect(
        screen.getByText(/prototype has not contacted anyone/i),
      ).toBeVisible()
      expect(document.body).not.toHaveTextContent('handoff completed')
      expect(document.body).not.toHaveTextContent('agent has been contacted')
    },
  )

  it('adds urgent official-channel guidance only for critical risk', () => {
    const { rerender } = render(
      <HumanAssistanceBanner requiresHuman riskLevel="high" />,
    )
    expect(screen.queryByText(/official emergency support route/i)).toBeNull()

    rerender(
      <HumanAssistanceBanner requiresHuman riskLevel="critical" />,
    )
    expect(
      screen.getByText(/official emergency support route now/i),
    ).toBeVisible()
  })

  it('has no detectable axe violations', async () => {
    const { container } = render(
      <HumanAssistanceBanner requiresHuman riskLevel="critical" />,
    )

    const results = await axe(container, {
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(results.violations).toEqual([])
  })
})
