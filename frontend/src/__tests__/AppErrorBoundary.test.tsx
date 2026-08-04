// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AppErrorBoundary } from '../AppErrorBoundary'

function BrokenApplication(): never {
  throw new Error('private path C:\\private and internal diagnostics')
}

describe('AppErrorBoundary', () => {
  it('shows a safe accessible fallback without exception details', () => {
    const consoleError = vi
      .spyOn(console, 'error')
      .mockImplementation(() => undefined)

    try {
      render(
        <AppErrorBoundary>
          <BrokenApplication />
        </AppErrorBoundary>,
      )

      expect(screen.getByRole('alert')).toBeVisible()
      expect(
        screen.getByRole('heading', {
          name: 'The interface could not start',
        }),
      ).toBeVisible()
      expect(
        screen.getByRole('button', { name: 'Reload page' }),
      ).toHaveClass('w-full', 'sm:w-auto')
      expect(screen.getByRole('main')).toHaveClass('min-h-dvh', 'min-w-0')
      expect(document.body).not.toHaveTextContent('C:\\private')
      expect(document.body).not.toHaveTextContent('internal diagnostics')
    } finally {
      consoleError.mockRestore()
    }
  })
})
