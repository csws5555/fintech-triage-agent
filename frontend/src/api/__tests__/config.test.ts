import { describe, expect, it } from 'vitest'

import {
  ApiConfigurationError,
  loadApiConfig,
} from '../config'

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000'

describe('loadApiConfig', () => {
  it.each([
    ['an absent value', {}],
    ['an undefined value', { VITE_API_BASE_URL: undefined }],
    ['an empty value', { VITE_API_BASE_URL: '' }],
    ['a whitespace-only value', { VITE_API_BASE_URL: ' \t ' }],
  ])('uses the default origin for %s', (_label, environment) => {
    expect(loadApiConfig(environment).baseUrl).toBe(DEFAULT_BASE_URL)
  })

  it.each([
    ['http://localhost:8000', 'http://localhost:8000'],
    ['https://api.example.test', 'https://api.example.test'],
    [' HTTPS://API.EXAMPLE.TEST:443 ', 'https://api.example.test'],
  ])('accepts and normalizes valid origin %s', (value, expected) => {
    expect(
      loadApiConfig({ VITE_API_BASE_URL: value }).baseUrl,
    ).toBe(expected)
  })

  it('removes one allowed root trailing slash', () => {
    const config = loadApiConfig({
      VITE_API_BASE_URL: 'http://localhost:9000/',
    })

    expect(config.baseUrl).toBe('http://localhost:9000')
    expect(config.chatUrl).toBe(
      'http://localhost:9000/api/v1/chat',
    )
  })

  it.each([
    ['not a URL', 'not-a-url'],
    ['a relative URL', '/api/v1'],
    ['a missing host', 'http://'],
    ['a malformed port', 'http://localhost:99999'],
    ['an unsupported scheme', 'ftp://localhost:8000'],
  ])('rejects %s', (_label, value) => {
    expect(() =>
      loadApiConfig({ VITE_API_BASE_URL: value }),
    ).toThrow(ApiConfigurationError)
  })

  it.each([
    'http://user@localhost:8000',
    'http://user:password@localhost:8000',
  ])('rejects credentialed origin %s', (value) => {
    expect(() =>
      loadApiConfig({ VITE_API_BASE_URL: value }),
    ).toThrow('must not contain credentials')
  })

  it.each([
    'http://localhost:8000?debug=true',
    'http://localhost:8000?',
  ])('rejects query-bearing origin %s', (value) => {
    expect(() =>
      loadApiConfig({ VITE_API_BASE_URL: value }),
    ).toThrow('must not contain a query or fragment')
  })

  it.each([
    'http://localhost:8000#details',
    'http://localhost:8000#',
  ])('rejects fragment-bearing origin %s', (value) => {
    expect(() =>
      loadApiConfig({ VITE_API_BASE_URL: value }),
    ).toThrow('must not contain a query or fragment')
  })

  it.each([
    'http://localhost:8000/api',
    'http://localhost:8000/api/v1',
    'http://localhost:8000/api/..',
    'http://localhost:8000//',
  ])('rejects path-bearing origin %s', (value) => {
    expect(() =>
      loadApiConfig({ VITE_API_BASE_URL: value }),
    ).toThrow('without an embedded path')
  })

  it('rejects a non-string configured value', () => {
    expect(() =>
      loadApiConfig({ VITE_API_BASE_URL: true }),
    ).toThrow('must be a string')
  })

  it('returns only the normalized origin and four fixed endpoint URLs', () => {
    const config = loadApiConfig({
      VITE_API_BASE_URL: 'https://api.example.test/',
    })

    expect(config).toEqual({
      baseUrl: 'https://api.example.test',
      livenessUrl: 'https://api.example.test/health/live',
      readinessUrl: 'https://api.example.test/health/ready',
      chatUrl: 'https://api.example.test/api/v1/chat',
      chatStreamUrl:
        'https://api.example.test/api/v1/chat/stream',
    })
    expect(Object.isFrozen(config)).toBe(true)
  })
})
