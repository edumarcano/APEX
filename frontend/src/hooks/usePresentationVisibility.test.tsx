import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const native = vi.hoisted(() => ({
  isNativeDesktop: vi.fn<() => boolean>(),
  getDesktopVisibilityState: vi.fn(),
  subscribeDesktopVisibilityState: vi.fn(),
}))

vi.mock('../platform/services', () => native)

import { usePresentationVisibility } from './usePresentationVisibility'

function setDocumentHidden(hidden: boolean): void {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
}

describe('usePresentationVisibility', () => {
  beforeEach(() => {
    setDocumentHidden(false)
    native.isNativeDesktop.mockReturnValue(false)
    native.getDesktopVisibilityState.mockReset()
    native.subscribeDesktopVisibilityState.mockReset()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('uses document visibility as the browser fallback', () => {
    const { result } = renderHook(() => usePresentationVisibility())
    expect(result.current).toBe(true)

    setDocumentHidden(true)
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(result.current).toBe(false)

    setDocumentHidden(false)
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(result.current).toBe(true)
  })

  it('subscribes before querying and ignores a stale snapshot after a newer event', async () => {
    native.isNativeDesktop.mockReturnValue(true)
    let onChange: ((state: { revision: number; visible: boolean }) => void) | undefined
    let resolveSnapshot!: (state: { revision: number; visible: boolean }) => void
    const snapshot = new Promise<{ revision: number; visible: boolean }>((resolve) => { resolveSnapshot = resolve })
    const order: string[] = []
    native.subscribeDesktopVisibilityState.mockImplementation(async (callback) => {
      order.push('subscribe')
      onChange = callback
      return vi.fn()
    })
    native.getDesktopVisibilityState.mockImplementation(async () => {
      order.push('snapshot')
      return snapshot
    })

    const { result } = renderHook(() => usePresentationVisibility())
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(order).toEqual(['subscribe', 'snapshot'])

    act(() => onChange?.({ revision: 9, visible: false }))
    expect(result.current).toBe(false)
    await act(async () => { resolveSnapshot({ revision: 8, visible: true }); await snapshot })
    expect(result.current).toBe(false)

    setDocumentHidden(true)
    act(() => onChange?.({ revision: 10, visible: true }))
    expect(result.current).toBe(false)
    setDocumentHidden(false)
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(result.current).toBe(true)
  })

  it('unsubscribes a native listener that finishes attaching after unmount', async () => {
    native.isNativeDesktop.mockReturnValue(true)
    let finishSubscribe!: (unsubscribe: () => void) => void
    const pendingSubscribe = new Promise<() => void>((resolve) => { finishSubscribe = resolve })
    const unsubscribe = vi.fn()
    native.subscribeDesktopVisibilityState.mockReturnValue(pendingSubscribe)

    const { unmount } = renderHook(() => usePresentationVisibility())
    await act(async () => { await Promise.resolve() })
    unmount()
    await act(async () => {
      finishSubscribe(unsubscribe)
      await pendingSubscribe
      await Promise.resolve()
    })

    expect(unsubscribe).toHaveBeenCalledOnce()
    expect(native.getDesktopVisibilityState).not.toHaveBeenCalled()
  })

  it('ignores events and snapshots from a detached native attachment after remount', async () => {
    native.isNativeDesktop.mockReturnValue(true)
    const callbacks: Array<(state: { revision: number; visible: boolean }) => void> = []
    const unlisteners = [vi.fn(), vi.fn()]
    native.subscribeDesktopVisibilityState.mockImplementation(async (callback) => {
      callbacks.push(callback)
      return unlisteners[callbacks.length - 1]
    })
    let resolveOldSnapshot!: (state: { revision: number; visible: boolean }) => void
    const oldSnapshot = new Promise<{ revision: number; visible: boolean }>((resolve) => { resolveOldSnapshot = resolve })
    native.getDesktopVisibilityState
      .mockReturnValueOnce(oldSnapshot)
      .mockResolvedValueOnce({ revision: 2, visible: false })

    const first = renderHook(() => usePresentationVisibility())
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(native.getDesktopVisibilityState).toHaveBeenCalledOnce()
    first.unmount()

    const second = renderHook(() => usePresentationVisibility())
    await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() })
    expect(second.result.current).toBe(false)
    expect(native.getDesktopVisibilityState).toHaveBeenCalledTimes(2)

    await act(async () => { resolveOldSnapshot({ revision: 50, visible: true }); await oldSnapshot })
    act(() => callbacks[0]({ revision: 51, visible: true }))
    expect(second.result.current).toBe(false)

    act(() => callbacks[1]({ revision: 3, visible: true }))
    expect(second.result.current).toBe(true)
    second.unmount()
    expect(unlisteners.every((unlisten) => unlisten.mock.calls.length === 1)).toBe(true)
  })

  it('unlistens and falls back to document visibility when the native snapshot fails', async () => {
    native.isNativeDesktop.mockReturnValue(true)
    let onChange: ((state: { revision: number; visible: boolean }) => void) | undefined
    const unsubscribe = vi.fn()
    native.subscribeDesktopVisibilityState.mockImplementation(async (callback) => {
      onChange = callback
      return unsubscribe
    })
    native.getDesktopVisibilityState.mockRejectedValue(new Error('native unavailable'))

    const { result } = renderHook(() => usePresentationVisibility())
    await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() })
    expect(unsubscribe).toHaveBeenCalledOnce()

    setDocumentHidden(true)
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(result.current).toBe(false)
    act(() => onChange?.({ revision: 3, visible: true }))
    expect(result.current).toBe(false)
  })
})
