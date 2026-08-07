import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AgentKey, ToolCatalog, ToolCatalogTool } from '../types/telemetry'

import { useToolCatalog } from './useToolCatalog'

function catalogFor(
  agent: AgentKey,
  tools: ToolCatalogTool[] = [
    {
      name: 'get_weather_forecast',
      label: 'Weather',
      description: 'Weather',
      origin: 'native' as const,
      source_id: 'apex',
      apex_family: 'weather',
      risk: 'read' as const,
      available: true,
      unavailable_reason: null,
      estimated_schema_tokens: 80,
      allowed_for_agent: true,
    },
  ],
): ToolCatalog {
  const allAllowed = agent === 'panthera'
  return {
    agent,
    groups: [],
    tools,
    profiles: [
      {
        id: 'no_tools',
        name: 'No APEX Tools',
        description: 'No live tools.',
        tool_names: [],
        built_in: true,
        dynamic: false,
      },
      {
        id: 'all_allowed',
        name: 'All APEX Tools',
        description: 'All available tools.',
        tool_names: [],
        built_in: true,
        dynamic: true,
      },
      {
        id: 'saved_weather',
        name: 'Saved Weather',
        description: 'Saved.',
        tool_names: ['get_weather_forecast'],
        built_in: false,
        dynamic: false,
      },
    ],
    default_profile_id: allAllowed ? 'all_allowed' : 'no_tools',
    default_profile_name: allAllowed ? 'All APEX Tools' : 'No APEX Tools',
    default_selected_tool_names: allAllowed ? ['get_weather_forecast'] : [],
    provider_hosted_tools: [],
    context_window: agent === 'panthera' ? null : 4096,
    reserved_response_tokens: agent === 'panthera' ? null : 512,
  }
}

describe('useToolCatalog per-Agent hydration', () => {
  afterEach(() => {
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('applies each Agent default independently and restores that Agent session', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const agent = new URL(String(input)).searchParams.get('agent') as AgentKey
        return Promise.resolve({
          ok: true,
          json: async () => catalogFor(agent),
        })
      }),
    )

    const hook = renderHook(
      ({ agent }: { agent: AgentKey }) => useToolCatalog(agent),
      { initialProps: { agent: 'panthera' as AgentKey } },
    )
    await waitFor(() => expect(hook.result.current.selectionReady).toBe(true))
    expect(hook.result.current.selectedToolNames).toEqual(['get_weather_forecast'])
    expect(hook.result.current.activeToolProfileId).toBe('all_allowed')

    hook.rerender({ agent: 'mus' })
    await waitFor(() => expect(hook.result.current.selectionReady).toBe(true))
    expect(hook.result.current.selectedToolNames).toEqual([])
    expect(hook.result.current.activeToolProfileId).toBe('no_tools')

    hook.rerender({ agent: 'panthera' })
    await waitFor(() => expect(hook.result.current.selectionReady).toBe(true))
    expect(hook.result.current.selectedToolNames).toEqual(['get_weather_forecast'])
    expect(hook.result.current.activeToolProfileId).toBe('all_allowed')
  })

  it('does not retain a stored profile identity when names no longer match it', async () => {
    sessionStorage.setItem(
      'apex.tool-selection.mus',
      JSON.stringify({
        names: ['unknown_tool'],
        profileId: 'saved_weather',
      }),
    )
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          json: async () => catalogFor('mus'),
        }),
      ),
    )

    const hook = renderHook(() => useToolCatalog('mus'))
    await waitFor(() => expect(hook.result.current.selectionReady).toBe(true))

    expect(hook.result.current.selectedToolNames).toEqual(['unknown_tool'])
    expect(hook.result.current.activeToolProfileId).toBeNull()
  })

  it('re-resolves a stored dynamic profile after availability, discovery, and policy changes', async () => {
    const weather = catalogFor('panthera').tools[0]
    const newMcpTool = {
      ...weather,
      name: 'brave_brave_web_search',
      label: 'Web search',
      origin: 'mcp' as const,
      source_id: 'brave',
      apex_family: 'web_search',
    }
    const disconnectedWeather = {
      ...weather,
      available: false,
      unavailable_reason: 'Weather is disconnected.',
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => catalogFor('panthera', [disconnectedWeather, newMcpTool]),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => catalogFor('panthera', [
          disconnectedWeather,
          { ...newMcpTool, allowed_for_agent: false },
        ]),
      })
    vi.stubGlobal('fetch', fetchMock)
    sessionStorage.setItem(
      'apex.tool-selection.panthera',
      JSON.stringify({
        names: ['get_weather_forecast'],
        profileId: 'all_allowed',
      }),
    )

    const hook = renderHook(() => useToolCatalog('panthera'))
    await waitFor(() => expect(hook.result.current.selectionReady).toBe(true))
    expect(hook.result.current.selectedToolNames).toEqual(['brave_brave_web_search'])
    expect(hook.result.current.activeToolProfileId).toBe('all_allowed')

    await act(async () => {
      await hook.result.current.refreshCatalog()
    })
    await waitFor(() => expect(hook.result.current.selectedToolNames).toEqual([]))
    expect(hook.result.current.activeToolProfileId).toBe('all_allowed')
  })

  it('never copies the previous Agent selection into a new Agent session', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const agent = new URL(String(input)).searchParams.get('agent') as AgentKey
        return Promise.resolve({
          ok: true,
          json: async () => catalogFor(agent),
        })
      }),
    )
    const hook = renderHook(
      ({ agent }: { agent: AgentKey }) => useToolCatalog(agent),
      { initialProps: { agent: 'panthera' as AgentKey } },
    )
    await waitFor(() => expect(hook.result.current.selectionReady).toBe(true))
    hook.result.current.setSelectedToolNames(['get_weather_forecast'])

    hook.rerender({ agent: 'mus' })
    await waitFor(() => expect(hook.result.current.selectionReady).toBe(true))
    expect(hook.result.current.selectedToolNames).toEqual([])
    expect(hook.result.current.activeToolProfileId).toBe('no_tools')
  })

  it('ignores a stale Agent refresh while hydrating the newly selected Agent', async () => {
    type CatalogResponse = { ok: boolean; json: () => Promise<unknown> }
    const pendingResponses: Array<{
      agent: AgentKey
      resolve: (response: CatalogResponse) => void
    }> = []
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const agent = new URL(String(input)).searchParams.get('agent') as AgentKey
      return new Promise<CatalogResponse>((resolve) => {
        pendingResponses.push({ agent, resolve })
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const hook = renderHook(
      ({ agent }: { agent: AgentKey }) => useToolCatalog(agent),
      { initialProps: { agent: 'panthera' as AgentKey } },
    )
    await waitFor(() => expect(pendingResponses).toHaveLength(1))
    pendingResponses[0].resolve({
      ok: true,
      json: async () => catalogFor('panthera'),
    })
    await waitFor(() => expect(hook.result.current.selectionReady).toBe(true))

    const stalePantheraRefresh = hook.result.current.refreshCatalog
    act(() => {
      void stalePantheraRefresh()
    })
    await waitFor(() => expect(pendingResponses).toHaveLength(2))

    hook.rerender({ agent: 'mus' })
    await waitFor(() => {
      expect(pendingResponses).toHaveLength(3)
      expect(hook.result.current.catalog).toBeNull()
      expect(hook.result.current.selectionReady).toBe(false)
    })

    act(() => {
      void stalePantheraRefresh()
    })
    expect(fetchMock).toHaveBeenCalledTimes(3)

    const musResponse = pendingResponses.find((request) => request.agent === 'mus')
    const oldPantheraResponse = pendingResponses[1]
    musResponse?.resolve({
      ok: true,
      json: async () => catalogFor('mus'),
    })
    await waitFor(() => {
      expect(hook.result.current.catalog?.agent).toBe('mus')
      expect(hook.result.current.selectionReady).toBe(true)
    })

    oldPantheraResponse.resolve({
      ok: true,
      json: async () => catalogFor('panthera'),
    })
    await act(async () => {
      await Promise.resolve()
    })

    expect(hook.result.current.catalog?.agent).toBe('mus')
    expect(hook.result.current.selectionReady).toBe(true)
  })
})
