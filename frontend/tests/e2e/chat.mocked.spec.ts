import { expect, test, type Page, type Request, type Route } from '@playwright/test'
import axeCore from 'axe-core'

import type { ErrorResponse, ReadinessResponse } from '../../src/api/contracts'
import {
  SERVICE_FREE_ANSWER_SCENARIOS,
  SERVICE_FREE_DEGRADED_RESPONSE,
  SERVICE_FREE_READY_RESPONSE,
  approvedSseSource,
  type ServiceFreeAnswerScenario,
} from '../../src/test/fixtures'

const APP_ORIGIN = 'http://127.0.0.1:5173'
const API_ORIGIN = 'http://127.0.0.1:8000'
const API_PATTERN = `${API_ORIGIN}/**`

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': APP_ORIGIN,
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Accept, Content-Type',
  'Access-Control-Expose-Headers': 'X-Request-ID',
} as const

const STATUS_LABELS = {
  answered: 'Answered',
  clarification_required: 'Needs clarification',
  safety_guidance: 'Safety guidance',
  request_refused: 'Request refused',
  action_not_confirmed: 'Action not confirmed',
  unsupported: 'Unsupported',
  service_fallback: 'Limited service',
} as const

const RISK_LABELS = {
  low: 'Low priority',
  medium: 'Medium priority',
  high: 'High priority',
  critical: 'Critical priority',
} as const

const RESPONSE_MODE_LABELS = {
  static_fallback: 'Safe fallback',
  deterministic_clarification: 'Clarification',
  deterministic_safety: 'Deterministic guidance',
  grounded_generation: 'Generated from approved policy',
} as const

type CapturedChatRequest = Readonly<{
  url: string
  method: string
  headers: Record<string, string>
  body: unknown
}>

type ChatRouteHandler = (
  route: Route,
  request: Request,
  callIndex: number,
) => Promise<void>

type MockApiOptions = Readonly<{
  readiness?: ReadinessResponse
  scenario?: ServiceFreeAnswerScenario
  chatHandler?: ChatRouteHandler
  capturedRequests?: CapturedChatRequest[]
}>

function responseHeaders(requestId: string, contentType: string) {
  return {
    ...CORS_HEADERS,
    'Content-Type': contentType,
    'X-Request-ID': requestId,
  }
}

async function fulfillJson(
  route: Route,
  payload: unknown,
  options: Readonly<{ status?: number; requestId?: string }> = {},
) {
  await route.fulfill({
    status: options.status ?? 200,
    headers: responseHeaders(
      options.requestId ?? 'request-health-check',
      'application/json',
    ),
    body: JSON.stringify(payload),
  })
}

async function fulfillApprovedStream(
  route: Route,
  scenario: ServiceFreeAnswerScenario,
) {
  await route.fulfill({
    status: 200,
    headers: responseHeaders(
      scenario.metadata.request_id,
      'text/event-stream',
    ),
    body: approvedSseSource(scenario),
  })
}

async function installMockApi(page: Page, options: MockApiOptions = {}) {
  const readiness = options.readiness ?? SERVICE_FREE_READY_RESPONSE
  const scenario = options.scenario ?? SERVICE_FREE_ANSWER_SCENARIOS[0]
  let chatCallCount = 0

  await page.route(API_PATTERN, async (route) => {
    const request = route.request()
    const url = new URL(request.url())

    if (request.method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: CORS_HEADERS })
      return
    }

    if (url.pathname === '/health/live') {
      await fulfillJson(route, {
        status: 'alive',
        service: 'fintech-triage-api',
      })
      return
    }

    if (url.pathname === '/health/ready') {
      await fulfillJson(route, readiness, {
        status: readiness.status === 'ready' ? 200 : 503,
      })
      return
    }

    if (url.pathname === '/api/v1/chat/stream') {
      const callIndex = chatCallCount
      chatCallCount += 1
      options.capturedRequests?.push({
        url: request.url(),
        method: request.method(),
        headers: await request.allHeaders(),
        body: request.postDataJSON(),
      })
      if (options.chatHandler !== undefined) {
        await options.chatHandler(route, request, callIndex)
      } else {
        await fulfillApprovedStream(route, scenario)
      }
      return
    }

    await route.fulfill({ status: 404, headers: CORS_HEADERS })
  })
}

async function openReadyApp(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Service ready' })).toBeVisible()
}

async function submitMessage(page: Page, message: string) {
  const composer = page.getByRole('textbox', { name: 'Message' })
  await composer.fill(message)
  await page.getByRole('button', { name: 'Send message' }).click()
}

async function expectCompletedScenario(
  page: Page,
  scenario: ServiceFreeAnswerScenario,
) {
  const customerMessage = page.getByRole('article', { name: 'You message' })
  const assistantMessage = page.getByRole('article', {
    name: 'Support guide message',
  })

  await expect(customerMessage).toContainText(scenario.message)
  await expect(assistantMessage).toContainText(scenario.answer)
  await expect(assistantMessage).toContainText('Response complete.')
  await expect(assistantMessage).toContainText(
    STATUS_LABELS[scenario.metadata.status],
  )
  await expect(assistantMessage).toContainText(
    RISK_LABELS[scenario.metadata.risk_level],
  )

  if (scenario.metadata.requires_human) {
    await expect(
      assistantMessage.getByRole('heading', {
        name: 'Human assistance required',
      }),
    ).toBeVisible()
  } else {
    await expect(
      assistantMessage.getByRole('heading', {
        name: 'Human assistance required',
      }),
    ).toHaveCount(0)
  }

  await assistantMessage.getByText('Response details').click()
  await expect(assistantMessage).toContainText(
    RESPONSE_MODE_LABELS[scenario.metadata.response_mode],
  )
  await expect(assistantMessage).toContainText(
    scenario.metadata.request_id,
  )
}

for (const scenario of SERVICE_FREE_ANSWER_SCENARIOS) {
  test(`renders the ${scenario.name} workflow from exact mocked SSE frames`, async ({
    context,
    page,
  }) => {
    const capturedRequests: CapturedChatRequest[] = []
    await context.addCookies([
      {
        name: 'browser_test_credential',
        value: 'must-not-cross-the-api-boundary',
        url: API_ORIGIN,
      },
    ])
    await installMockApi(page, { scenario, capturedRequests })
    await openReadyApp(page)
    await submitMessage(page, scenario.message)
    await expectCompletedScenario(page, scenario)

    expect(capturedRequests).toHaveLength(1)
    expect(capturedRequests[0]).toMatchObject({
      url: `${API_ORIGIN}/api/v1/chat/stream`,
      method: 'POST',
      body: { message: scenario.message },
    })
    expect(Object.keys(capturedRequests[0].body as object)).toEqual(['message'])
    expect(capturedRequests[0].headers.accept).toBe('text/event-stream')
    expect(capturedRequests[0].headers['content-type']).toContain(
      'application/json',
    )
    expect(capturedRequests[0].headers.cookie).toBeUndefined()
    expect(capturedRequests[0].headers.authorization).toBeUndefined()

    if (scenario.metadata.status === 'request_refused') {
      expect(
        await page.evaluate(
          () =>
            (globalThis as typeof globalThis & { privateData?: boolean })
              .privateData,
        ),
      ).toBeUndefined()
      expect(
        await page.locator('script').evaluateAll((scripts) =>
          scripts.some((script) =>
            script.textContent?.includes('window.privateData'),
          ),
        ),
      ).toBe(false)
    }

    expect(
      await page.evaluate(() => ({
        localStorage: localStorage.length,
        sessionStorage: sessionStorage.length,
      })),
    ).toEqual({ localStorage: 0, sessionStorage: 0 })

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Service ready' })).toBeVisible()
    await expect(page.getByRole('article', { name: 'You message' })).toHaveCount(0)
    await expect(
      page.getByRole('article', { name: 'Support guide message' }),
    ).toHaveCount(0)
  })
}

test('keeps chat available with a valid degraded readiness response', async ({
  page,
}) => {
  const scenario = SERVICE_FREE_ANSWER_SCENARIOS[0]
  await installMockApi(page, {
    readiness: SERVICE_FREE_DEGRADED_RESPONSE,
    scenario,
  })
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Limited service' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Message' })).toBeEditable()
  await submitMessage(page, scenario.message)
  await expectCompletedScenario(page, scenario)
})

test('disables chat when mandatory readiness is unavailable', async ({ page }) => {
  const unavailableReadiness = {
    status: 'degraded',
    components: {
      ...SERVICE_FREE_READY_RESPONSE.components,
      classifier: 'unavailable',
    },
  } as const satisfies ReadinessResponse
  await installMockApi(page, { readiness: unavailableReadiness })
  await page.goto('/')

  await expect(
    page.getByRole('heading', { name: 'Service unavailable' }),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry connection' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Message' })).toBeDisabled()
})

test('shows a safe retryable error and retries without duplicating the customer turn', async ({
  page,
}) => {
  const scenario = SERVICE_FREE_ANSWER_SCENARIOS[0]
  const errorPayload = {
    request_id: 'request-timeout',
    error: {
      code: 'request_timeout',
      message: 'The support request timed out.',
      retryable: true,
    },
  } as const satisfies ErrorResponse
  let chatCalls = 0

  await installMockApi(page, {
    scenario,
    chatHandler: async (route) => {
      chatCalls += 1
      if (chatCalls === 1) {
        await fulfillJson(route, errorPayload, {
          status: 504,
          requestId: errorPayload.request_id,
        })
        return
      }
      await fulfillApprovedStream(route, scenario)
    },
  })
  await openReadyApp(page)
  await submitMessage(page, scenario.message)

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('Request timed out')
  await expect(alert).toContainText(errorPayload.error.message)
  await expect(alert).toBeFocused()
  await alert.getByRole('button', { name: 'Retry request' }).click()

  await expectCompletedScenario(page, scenario)
  await expect(page.getByRole('article', { name: 'You message' })).toHaveCount(1)
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(chatCalls).toBe(2)
})

test('cancels a pending request and ignores its stale fulfilled response', async ({
  page,
}) => {
  const scenario = SERVICE_FREE_ANSWER_SCENARIOS[1]
  let releaseResponse: (() => void) | undefined
  const responseGate = new Promise<void>((resolve) => {
    releaseResponse = resolve
  })

  await installMockApi(page, {
    scenario,
    chatHandler: async (route) => {
      await responseGate
      await fulfillApprovedStream(route, scenario).catch(() => undefined)
    },
  })
  await openReadyApp(page)
  await submitMessage(page, scenario.message)
  await expect(page.getByRole('button', { name: 'Cancel request' })).toBeVisible()
  await page.getByRole('button', { name: 'Cancel request' }).click()

  const assistantMessage = page.getByRole('article', {
    name: 'Support guide message',
  })
  await expect(assistantMessage).toContainText('Response cancelled.')
  await expect(
    assistantMessage.getByRole('button', { name: 'Retry cancelled request' }),
  ).toBeVisible()
  releaseResponse?.()
  await page.waitForTimeout(150)
  await expect(assistantMessage).not.toContainText(scenario.answer)
  await expect(assistantMessage).toContainText('Response cancelled.')
})

test('supports keyboard submission, preserves focus, and has no detectable axe violations', async ({
  page,
}) => {
  const scenario = SERVICE_FREE_ANSWER_SCENARIOS[2]
  await installMockApi(page, { scenario })
  await openReadyApp(page)

  const composer = page.getByRole('textbox', { name: 'Message' })
  await composer.focus()
  await composer.fill(scenario.message)
  await composer.press('Enter')
  await expect(
    page.getByRole('article', { name: 'Support guide message' }),
  ).toContainText('Response complete.')
  await expect(composer).toBeFocused()
  await expectCompletedScenario(page, scenario)

  await page.addScriptTag({ content: axeCore.source })
  const violations = await page.evaluate(async () => {
    const axe = (
      globalThis as typeof globalThis & {
        axe: {
          run(): Promise<{
            violations: Array<{ id: string; help: string }>
          }>
        }
      }
    ).axe
    const result = await axe.run()
    return result.violations.map(({ id, help }) => ({ id, help }))
  })
  expect(violations).toEqual([])
})

test('keeps long content and controls inside mobile and desktop viewports', async ({
  page,
}) => {
  const scenario = {
    name: 'responsive long-content guidance',
    message: `Card help ${'M'.repeat(180)}`,
    answer: `Use the official support route: https://support.example.test/${'a'.repeat(220)}`,
    metadata: {
      ...SERVICE_FREE_ANSWER_SCENARIOS[2].metadata,
      request_id: 'request-responsive-content',
    },
  } as const satisfies ServiceFreeAnswerScenario

  await page.setViewportSize({ width: 320, height: 720 })
  await installMockApi(page, { scenario })
  await openReadyApp(page)
  await submitMessage(page, scenario.message)
  await expectCompletedScenario(page, scenario)

  const assertNoHorizontalOverflow = async (viewportWidth: number) => {
    const layout = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }))
    expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth)

    for (const control of [
      page.getByRole('textbox', { name: 'Message' }),
      page.getByRole('button', { name: 'Send message' }),
      page.getByRole('button', { name: 'Clear conversation' }),
    ]) {
      const box = await control.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewportWidth)
    }
  }

  await assertNoHorizontalOverflow(320)
  await page.setViewportSize({ width: 1440, height: 900 })
  await assertNoHorizontalOverflow(1440)
})
