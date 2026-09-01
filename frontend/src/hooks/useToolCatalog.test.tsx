import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ToolCatalog, ToolCatalogTool } from '../types/telemetry'

import { useToolCatalog } from './useToolCatalog'

const weatherTool: ToolCatalogTool = {
  name: 'get_weather_forecast', label: 'Weather', description: 'Weather',
  origin: 'native', source_id: 'apex', apex_family: 'weather', risk: 'read',
  available: true, unavailable_reason: null, estimated_schema_tokens: 80, allowed_for_agent: true,
}

function catalogFor(runtime: 'cloud' | 'local', tools = [weatherTool]): ToolCatalog {
  const cloud = runtime === 'cloud'
  return {
    agent: 'apex', groups: [], tools,
    profiles: [{ id: cloud ? 'all_allowed' : 'no_tools', name: cloud ? 'All APEX Tools' : 'No APEX Tools', description: 'Default.', tool_names: [], built_in: true, dynamic: cloud }],
    default_profile_id: cloud ? 'all_allowed' : 'no_tools',
    default_profile_name: cloud ? 'All APEX Tools' : 'No APEX Tools',
    default_selected_tool_names: cloud ? ['get_weather_forecast'] : [],
    provider_hosted_tools: [], context_window: cloud ? null : 16384, reserved_response_tokens: cloud ? null : 512,
  }
}

describe('useToolCatalog model-aware hydration', () => {
  afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks() })

  it('requests the selected model and keeps cloud and local selections separate', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const modelId = new URL(String(input)).searchParams.get('model_id')
      return Promise.resolve({ ok: true, json: async () => catalogFor(modelId?.includes('gemma') ? 'local' : 'cloud') })
    }))
    const hook = renderHook(
      ({ modelId, runtime }: { modelId: string; runtime: 'cloud' | 'local' }) => useToolCatalog('apex', modelId, runtime),
      { initialProps: { modelId: 'deepseek/deepseek-v4-flash-0731', runtime: 'cloud' as 'cloud' | 'local' } },
    )
    await waitFor(() => expect(hook.result.current.selectionReady).toBe(true))
    expect(hook.result.current.selectedToolNames).toEqual(['get_weather_forecast'])
    hook.rerender({ modelId: 'gemma-4-E2B-Q4_K_M.gguf', runtime: 'local' })
    await waitFor(() => expect(hook.result.current.activeToolProfileId).toBe('no_tools'))
    expect(hook.result.current.selectedToolNames).toEqual([])
    expect(sessionStorage.getItem('apex.tool-selection.cloud')).not.toBeNull()
    expect(sessionStorage.getItem('apex.tool-selection.local')).not.toBeNull()
  })

  it('refreshes a dynamic cloud profile after availability changes', async () => {
    const unavailable = { ...weatherTool, available: false }
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => catalogFor('cloud', [unavailable]) })
      .mockResolvedValueOnce({ ok: true, json: async () => catalogFor('cloud') }))
    const hook = renderHook(
      ({ availabilityVersion }: { availabilityVersion: string | null }) => useToolCatalog('apex', 'deepseek/deepseek-v4-flash-0731', 'cloud', availabilityVersion),
      { initialProps: { availabilityVersion: null as string | null } },
    )
    await waitFor(() => expect(hook.result.current.selectionReady).toBe(true))
    expect(hook.result.current.selectedToolNames).toEqual([])
    hook.rerender({ availabilityVersion: 'mcp:connected' })
    await waitFor(() => expect(hook.result.current.selectedToolNames).toEqual(['get_weather_forecast']))
  })

  it('ignores a stale response from the previously selected model', async () => {
    type CatalogResponse = { ok: boolean; json: () => Promise<unknown> }
    const pending: Array<(response: CatalogResponse) => void> = []
    vi.stubGlobal('fetch', vi.fn(() => new Promise<CatalogResponse>((resolve) => { pending.push(resolve) })))
    const hook = renderHook(
      ({ modelId, runtime }: { modelId: string; runtime: 'cloud' | 'local' }) => useToolCatalog('apex', modelId, runtime),
      { initialProps: { modelId: 'deepseek/deepseek-v4-flash-0731', runtime: 'cloud' as 'cloud' | 'local' } },
    )
    await waitFor(() => expect(pending).toHaveLength(1))
    hook.rerender({ modelId: 'gemma-4-E2B-Q4_K_M.gguf', runtime: 'local' })
    await waitFor(() => expect(pending).toHaveLength(2))
    pending[1]({ ok: true, json: async () => catalogFor('local') })
    await waitFor(() => expect(hook.result.current.catalog?.context_window).toBe(16384))
    await act(async () => { pending[0]({ ok: true, json: async () => catalogFor('cloud') }) })
    expect(hook.result.current.catalog?.context_window).toBe(16384)
  })
})
