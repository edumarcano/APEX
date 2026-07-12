import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSettingsEditor } from './useSettingsEditor'
import {
  BASE_SETTINGS,
  buildSettingsResponse,
  jsonResponse,
} from '../test/settingsFixtures'

describe('useSettingsEditor', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads a fresh editable snapshot when opened', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))

    const { result } = renderHook(() => useSettingsEditor({ open: true }))

    await waitFor(() => expect(result.current.loadStatus).toBe('ready'))
    expect(result.current.baseline).toEqual(BASE_SETTINGS)
    expect(result.current.draft).toEqual(BASE_SETTINGS)
    expect(result.current.draft).not.toBe(result.current.baseline)
  })

  it('aborts an in-progress load when closed', async () => {
    let requestSignal: AbortSignal | undefined
    vi.mocked(fetch).mockImplementationOnce((_input, init) => {
      requestSignal = init?.signal ?? undefined
      return new Promise<Response>(() => undefined)
    })

    const { rerender } = renderHook(
      ({ open }: { open: boolean }) => useSettingsEditor({ open }),
      { initialProps: { open: true } },
    )

    await waitFor(() => expect(requestSignal).toBeDefined())
    rerender({ open: false })

    expect(requestSignal?.aborted).toBe(true)
  })

  it('submits only dirty fields and replaces the baseline after success', async () => {
    const savedSettings = structuredClone(BASE_SETTINGS)
    savedSettings.features.weather = false
    const applied = vi.fn()
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
      .mockResolvedValueOnce(jsonResponse(buildSettingsResponse(savedSettings)))

    const { result } = renderHook(() =>
      useSettingsEditor({ open: true, onApplied: applied }),
    )
    await waitFor(() => expect(result.current.loadStatus).toBe('ready'))

    act(() => {
      result.current.setDraft((previous) => ({
        ...previous,
        features: { ...previous.features, weather: false },
      }))
    })
    await act(async () => {
      expect(await result.current.save()).toBe(true)
    })

    expect(fetch).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining('/api/v1/settings'),
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ features: { weather: false } }),
      }),
    )
    expect(result.current.baseline).toEqual(savedSettings)
    expect(result.current.draft).toEqual(savedSettings)
    expect(result.current.isDirty).toBe(false)
    expect(applied).toHaveBeenCalledWith(buildSettingsResponse(savedSettings))
  })

  it('preserves the dirty draft and reports an API failure', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Unable to persist settings.' }, { status: 503 }),
      )

    const { result } = renderHook(() => useSettingsEditor({ open: true }))
    await waitFor(() => expect(result.current.loadStatus).toBe('ready'))

    act(() => {
      result.current.setDraft((previous) => ({
        ...previous,
        assistant: { ...previous.assistant, enabled: false },
      }))
    })
    await act(async () => {
      expect(await result.current.save()).toBe(false)
    })

    expect(result.current.draft?.assistant.enabled).toBe(false)
    expect(result.current.baseline?.assistant.enabled).toBe(true)
    expect(result.current.isDirty).toBe(true)
    expect(result.current.saveError).toBe('Unable to persist settings.')
  })
})
