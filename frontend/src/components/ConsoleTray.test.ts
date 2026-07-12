import { describe, expect, it } from 'vitest'

import { resolveConsoleActivityTone } from '../lib/consoleActivity'

describe('resolveConsoleActivityTone', () => {
  it('ignores briefing-owned local model loading', () => {
    expect(resolveConsoleActivityTone(false, true)).toBeNull()
  })

  it('uses rust for assistant-owned local model loading', () => {
    expect(resolveConsoleActivityTone(true, true)).toBe('rust')
  })

  it('uses purple for cloud assistant work', () => {
    expect(resolveConsoleActivityTone(true, false)).toBe('purple')
  })
})
