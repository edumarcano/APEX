import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AgentKey, ToolCatalog } from '../types/telemetry'

import { useToolCatalog } from './useToolCatalog'

function catalogFor(agent: AgentKey): ToolCatalog {
  const allAllowed = agent === 'panthera'
  const tools = [
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
  ]
  return {
    agent,
    groups: [],
    tools,
    profiles: [
      {
        id: 'no_tools',
        name: 'No Tools',
        description: 'No live tools.',
        tool_names: [],
        built_in: true,
        dynamic: false,
      },
      {
        id: 'all_allowed',
        name: 'All Allowed',
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
    default_profile_name: allAllowed ? 'All Allowed' : 'No Tools',
    default_selected_tool_names: allAllowed ? ['get_weather_forecast'] : [],
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
})
