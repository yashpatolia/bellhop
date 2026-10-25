import { beforeEach, describe, expect, it } from 'vitest'
import { readMode, saveMode } from './mode'

const store = new Map<string, string>()
beforeEach(() => {
  store.clear()
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: { localStorage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) } },
  })
})

describe('mode', () => {
  it('defaults to the real home', () => {
    expect(readMode()).toBe('live')
  })
  it('remembers the demo choice', () => {
    saveMode('demo')
    expect(readMode()).toBe('demo')
    saveMode('live')
    expect(readMode()).toBe('live')
  })
  it('falls back to live when storage throws', () => {
    Object.defineProperty(globalThis, 'window', { configurable: true, value: { localStorage: { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } } } })
    expect(readMode()).toBe('live')
    expect(() => saveMode('demo')).not.toThrow()
  })
})
