import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useCortex } from './useCortex'

const modelId = 'gemma-4-E2B-Q4_K_M.gguf'
const catalogResponse = {
  key: 'apex', display_name: 'Lynx', canonical_name: 'APEX Agent', description: 'Native assistant.', selected_model: modelId,
  model_catalog: [{ model_id: modelId, display_name: 'Gemma 4 E2B', provider: 'llama_cpp', runtime: 'local', hosted_capabilities: [], status: 'available', active: false, loading: false }],
}

const cloudSelectedWithResidentLocal = {
  ...catalogResponse,
  selected_model: 'z-ai/glm-5.3-flash',
  model_catalog: [
    { model_id: 'z-ai/glm-5.3-flash', display_name: 'GLM 5.3 Flash', provider: 'openrouter', runtime: 'cloud', hosted_capabilities: [], status: 'available', active: false, loading: false },
    { ...catalogResponse.model_catalog[0], active: true, loaded_model: { provider: 'llama_cpp', name: modelId, model: modelId, state: 'loaded', context_window: 16384 }, idle_unload_remaining_seconds: 240 },
  ],
}

describe('useCortex model lifecycle', () => {
  afterEach(() => {
    vi.useRealTimers()
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
    vi.restoreAllMocks()
  })

  it('pauses status polling while dormant without requesting model loads', async () => {
    vi.useFakeTimers()
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
    let statusRequests = 0
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/agent')) {
        statusRequests += 1
        return new Response(JSON.stringify(catalogResponse))
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderHook(() => useCortex(true))
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(statusRequests).toBe(1)

    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    await act(async () => { await vi.advanceTimersByTimeAsync(12_000) })
    expect(statusRequests).toBe(1)

    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(statusRequests).toBe(2)
    expect(fetchSpy.mock.calls.some((call) => String(call[0]).includes('/local-model/load'))).toBe(false)
  })

  it('refreshes the unified catalog and rechecks it after loading the selected local model', async () => {
    let statusRequests = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/agent')) {
        statusRequests += 1
        return new Response(JSON.stringify(catalogResponse))
      }
      if (url.endsWith('/api/v1/cortex/local-model/load')) {
        expect(init?.method).toBe('POST')
        expect(init?.body).toBe(JSON.stringify({ model_id: modelId }))
        return new Response(null, { status: 204 })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const { result } = renderHook(() => useCortex(false))
    await act(async () => { await result.current.refreshAgentsStatus() })
    expect(result.current.cortexAgent?.key).toBe('apex')
    expect(result.current.cortexAgent?.selected_model).toBe(modelId)
    expect(result.current.modelCatalog).toEqual(catalogResponse.model_catalog)
    await act(async () => { await result.current.loadLocalModel(modelId) })
    await waitFor(() => expect(statusRequests).toBe(2))
  })

  it('preserves local residency while a cloud model is selected', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(cloudSelectedWithResidentLocal)),
    )
    const { result } = renderHook(() => useCortex(false))

    await act(async () => { await result.current.refreshAgentsStatus() })

    expect(result.current.cortexAgent?.selected_model).toBe('z-ai/glm-5.3-flash')
    expect(result.current.modelCatalog).toContainEqual(expect.objectContaining({
      model_id: modelId,
      active: true,
      idle_unload_remaining_seconds: 240,
      loaded_model: expect.objectContaining({ model: modelId, state: 'loaded' }),
    }))
  })
})
