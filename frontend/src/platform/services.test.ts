import { afterEach, describe, expect, it, vi } from 'vitest'

import { openExternal } from './services'

describe('openExternal browser adapter', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('opens validated URLs in a separate browser context', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue({} as Window)
    await openExternal('https://example.com/source')
    expect(open).toHaveBeenCalledWith('https://example.com/source', '_blank')
  })

  it('rejects unsafe destinations without calling the browser', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue({} as Window)
    await expect(openExternal('//example.com/remote')).rejects.toThrow(/valid HTTP\(S\) URL/)
    expect(open).not.toHaveBeenCalled()
  })

  it('reports when the browser blocks opening a new context', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    await expect(openExternal('https://example.com')).rejects.toThrow(/popup settings/)
  })
})
