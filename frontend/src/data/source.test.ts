import { describe, expect, it } from 'vitest'
import { apiUrlForHost } from './source'

describe('apiUrlForHost', () => {
  it('uses loopback for a dashboard opened on the laptop itself', () => {
    expect(apiUrlForHost('localhost', 'auto')).toBe('http://127.0.0.1:8000')
    expect(apiUrlForHost('127.0.0.1', 'auto')).toBe('http://127.0.0.1:8000')
  })

  it('uses the page host for a touchscreen opened through Tailscale', () => {
    expect(apiUrlForHost('100.100.89.19', 'auto')).toBe('http://100.100.89.19:8000')
  })

  it('honours an explicitly configured backend', () => {
    expect(apiUrlForHost('localhost', 'https://api.example.test')).toBe('https://api.example.test')
  })
})
