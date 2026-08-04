import { defineConfig, devices } from '@playwright/test'

const APP_ORIGIN = 'http://127.0.0.1:5173'
const LIVE_API_TESTS_ENABLED = process.env.RUN_LIVE_API_TESTS === '1'

const managedWebServer = LIVE_API_TESTS_ENABLED
  ? undefined
  : {
      command:
        'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort',
      url: APP_ORIGIN,
      reuseExistingServer: false,
      timeout: 120_000,
    }

export default defineConfig({
  testDir: './tests/e2e',
  outputDir: './node_modules/.cache/playwright-test-results',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'list',
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL: APP_ORIGIN,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // Live runs use the separately started real app on 5173 and never manage
  // an externally owned frontend or backend process.
  webServer: managedWebServer,
})
