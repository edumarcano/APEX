import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useCortex } from './useCortex'

const modelId = 'gemma-4-E2B-Q4_K_M.gguf'
const catalogResponse = {
  key: 'apex', display_name: 'Apex Agent', description: 'Native assistant.', selected_model: modelId,
  model_catalog: [{ model_id: modelId, display_name: 'Gemma 4 E2B', provider: 'llama_cpp', runtime: 'local', stability: 'stable', hosted_capabilities: [], status: 'available', active: false, loading: false }],
}

describe('useCortex model lifecycle', () => {
  afterEach(() => vi.restoreAllMocks())

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
    expect(result.current.agentsStatus[0]?.key).toBe('apex')
    expect(result.current.agentsStatus[0]?.configured_model).toBe(modelId)
    await act(async () => { await result.current.loadLocalModel(modelId) })
    await waitFor(() => expect(statusRequests).toBe(2))
  })
})
