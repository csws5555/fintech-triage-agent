// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import type {
  PublicStatus,
  ReadinessResponse,
  ResponseMode,
  RiskLevel,
} from '../api/contracts'
import {
  SERVICE_FREE_ANSWER_SCENARIOS,
  SERVICE_FREE_DEGRADED_RESPONSE,
  SERVICE_FREE_PAYLOAD_TOO_LARGE_RESPONSE,
  SERVICE_FREE_READY_RESPONSE,
  approvedSseResponse,
  jsonApiResponse,
  streamApiResponse,
  type ServiceFreeAnswerScenario,
} from '../test/fixtures'

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

type FetchMock = ReturnType<typeof vi.fn<typeof fetch>>

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') {
    return input
  }
  if (input instanceof URL) {
    return input.href
  }
  return input.url
}

function fetchForScenario(
  scenario: ServiceFreeAnswerScenario,
  readiness: ReadinessResponse = SERVICE_FREE_READY_RESPONSE,
): FetchMock {
  return vi.fn<typeof fetch>(async (input) => {
    const url = requestUrl(input)
    if (url.endsWith('/health/ready')) {
      return jsonApiResponse(readiness, {
        status: readiness.status === 'ready' ? 200 : 503,
      })
    }
    if (url.endsWith('/api/v1/chat/stream')) {
      return approvedSseResponse(scenario)
    }
    throw new Error('Unexpected service-free endpoint.')
  })
}

function chatCall(fetchMock: FetchMock) {
  const call = fetchMock.mock.calls.find(([input]) =>
    requestUrl(input).endsWith('/api/v1/chat/stream'),
  )
  if (call === undefined) {
    throw new Error('The service-free chat request was not made.')
  }
  return call
}

async function submitMessage(message: string): Promise<void> {
  const user = userEvent.setup()
  const composer = await screen.findByRole('textbox', { name: 'Message' })
  await screen.findByText(/Service ready|Limited service/)
  fireEvent.change(composer, { target: { value: message } })
  await user.click(screen.getByRole('button', { name: 'Send message' }))
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
  sessionStorage.clear()
})

describe('service-free production application integration', () => {
  it.each(SERVICE_FREE_ANSWER_SCENARIOS)(
    'renders $name through the exact fetch and SSE boundary',
    async (scenario) => {
      const fetchMock = fetchForScenario(scenario)
      vi.stubGlobal('fetch', fetchMock)
      render(<App />)

      await submitMessage(scenario.message)

      const assistant = await screen.findByLabelText('Support guide message')
      expect(assistant).toHaveTextContent(scenario.answer)
      expect(within(assistant).getAllByText(
        STATUS_LABELS[scenario.metadata.status],
      )[0]).toBeVisible()
      expect(within(assistant).getByText(
        RISK_LABELS[scenario.metadata.risk_level],
      )).toBeVisible()
      expect(within(assistant).getByText('Response complete.')).toBeVisible()
      expect(within(assistant).queryByText(/Response unavailable/i)).toBeNull()

      await userEvent.click(within(assistant).getByText('Response details'))
      expect(within(assistant).getByText(
        RESPONSE_MODE_LABELS[scenario.metadata.response_mode],
      )).toBeVisible()
      expect(within(assistant).getByText(
        scenario.metadata.request_id,
      )).toBeVisible()

      if (scenario.metadata.requires_human) {
        expect(within(assistant).getByRole('heading', {
          name: 'Human assistance required',
        })).toBeVisible()
      } else {
        expect(within(assistant).queryByRole('heading', {
          name: 'Human assistance required',
        })).toBeNull()
      }

      const [input, options] = chatCall(fetchMock)
      expect(requestUrl(input)).toBe(
        'http://127.0.0.1:8000/api/v1/chat/stream',
      )
      expect(options).toMatchObject({
        method: 'POST',
        credentials: 'omit',
      })
      expect(options?.body).toBe(JSON.stringify({ message: scenario.message }))
      expect(Object.keys(JSON.parse(String(options?.body)))).toEqual([
        'message',
      ])
      const headers = new Headers(options?.headers)
      expect(headers.get('Accept')).toBe('text/event-stream')
      expect(headers.get('Content-Type')).toBe('application/json')
      expect(headers.has('X-Request-ID')).toBe(false)

      const customer = screen.getByLabelText('You message')
      if (scenario.metadata.status === 'request_refused') {
        expect(customer).toHaveTextContent('<script>window.privateData = true</script>')
        expect(document.querySelector('script')).toBeNull()
        expect(assistant).not.toHaveTextContent('window.privateData')
      }
      if (scenario.metadata.status === 'action_not_confirmed') {
        expect(assistant).toHaveTextContent('cannot confirm')
        expect(assistant).not.toHaveTextContent('I froze your card')
      }
      if (scenario.metadata.status === 'safety_guidance') {
        expect(assistant).not.toHaveTextContent('I froze your card')
        expect(assistant).not.toHaveTextContent('human handoff completed')
      }

      expect(localStorage).toHaveLength(0)
      expect(sessionStorage).toHaveLength(0)
      expect(document.body).not.toHaveTextContent('reason_code')
      expect(document.body).not.toHaveTextContent('retrieved_policy_ids')
      expect(document.body).not.toHaveTextContent('classifier confidence')
    },
  )

  it('keeps optional-only degraded readiness usable through the fetch boundary', async () => {
    const scenario = SERVICE_FREE_ANSWER_SCENARIOS[0]
    const fetchMock = fetchForScenario(
      scenario,
      SERVICE_FREE_DEGRADED_RESPONSE,
    )
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    await submitMessage(scenario.message)

    expect(screen.getByText('Limited service')).toBeVisible()
    expect(await screen.findByText(scenario.answer)).toBeVisible()
    expect(screen.getByText('Response complete.')).toBeVisible()
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeEnabled()
  })

  it('fails safely when both health checks are unreachable', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValue(
        new TypeError('private network route C:\\customer\\secret'),
      )
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    expect(await screen.findByText('Service unavailable')).toBeVisible()
    expect(
      screen.getByText('The local support service could not be reached.'),
    ).toBeVisible()
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(document.body).not.toHaveTextContent('private network route')
    expect(document.body).not.toHaveTextContent('customer\\secret')
  })

  it('presents an exact pre-header 413 error without exposing raw data', async () => {
    const scenario = SERVICE_FREE_ANSWER_SCENARIOS[0]
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = requestUrl(input)
      if (url.endsWith('/health/ready')) {
        return jsonApiResponse(SERVICE_FREE_READY_RESPONSE)
      }
      if (url.endsWith('/api/v1/chat/stream')) {
        return jsonApiResponse(SERVICE_FREE_PAYLOAD_TOO_LARGE_RESPONSE, {
          status: 413,
          requestId: SERVICE_FREE_PAYLOAD_TOO_LARGE_RESPONSE.request_id,
        })
      }
      throw new Error('Unexpected service-free endpoint.')
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    await submitMessage(scenario.message)

    const alert = await screen.findByRole('alert', {
      name: 'Message could not be sent',
    })
    expect(alert).toHaveTextContent('The request body is too large.')
    expect(alert).toHaveTextContent('Use a shorter message')
    expect(alert).toHaveTextContent('payload_too_large')
    expect(alert).toHaveTextContent('request-payload-too-large')
    expect(screen.getByText('Response unavailable.')).toBeVisible()
    expect(screen.queryByText('Response complete.')).toBeNull()
    expect(
      screen.getByRole('button', { name: 'Edit and resend' }),
    ).toBeVisible()
    expect(document.body).not.toHaveTextContent('traceback')
  })

  it('retains approved partial text as incomplete when SSE ends without done', async () => {
    const scenario = SERVICE_FREE_ANSWER_SCENARIOS[1]
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = requestUrl(input)
      if (url.endsWith('/health/ready')) {
        return jsonApiResponse(SERVICE_FREE_READY_RESPONSE)
      }
      if (url.endsWith('/api/v1/chat/stream')) {
        return approvedSseResponse(scenario, { includeDone: false })
      }
      throw new Error('Unexpected service-free endpoint.')
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    await submitMessage(scenario.message)

    expect(await screen.findByText(scenario.answer)).toBeVisible()
    expect(screen.getByText(
      'Incomplete response - delivery was interrupted.',
    )).toBeVisible()
    expect(screen.queryByText('Response complete.')).toBeNull()
    expect(screen.getByRole('alert', {
      name: 'Connection interrupted',
    })).toHaveTextContent('The response stream was interrupted.')
    expect(screen.getByRole('button', { name: 'Retry request' })).toBeVisible()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
  })

  it('cancels an open fetch-backed stream without allowing completion', async () => {
    const user = userEvent.setup()
    const scenario = SERVICE_FREE_ANSWER_SCENARIOS[1]
    const cancel = vi.fn()
    const encoder = new TextEncoder()
    const partialSource =
      `event: metadata\ndata: ${JSON.stringify(scenario.metadata)}\n\n` +
      `event: chunk\ndata: ${JSON.stringify({
        request_id: scenario.metadata.request_id,
        sequence: 0,
        text: 'Approved partial safety guidance.',
      })}\n\n`
    const openBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(Uint8Array.from(encoder.encode(partialSource)))
      },
      cancel,
    })
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = requestUrl(input)
      if (url.endsWith('/health/ready')) {
        return jsonApiResponse(SERVICE_FREE_READY_RESPONSE)
      }
      if (url.endsWith('/api/v1/chat/stream')) {
        return streamApiResponse(openBody, scenario.metadata.request_id)
      }
      throw new Error('Unexpected service-free endpoint.')
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    await submitMessage(scenario.message)
    expect(
      await screen.findByText('Approved partial safety guidance.'),
    ).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Cancel request' }))

    expect(screen.getByText('Response cancelled.')).toBeVisible()
    expect(screen.queryByText('Response complete.')).toBeNull()
    expect(screen.getByRole('button', {
      name: 'Retry cancelled request',
    })).toBeVisible()
    await waitFor(() => expect(cancel).toHaveBeenCalledTimes(1))
  })
})
