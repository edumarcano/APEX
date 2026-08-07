import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useToolPreflight } from './useToolPreflight'

const noSelectedTools: string[] = []

describe('useToolPreflight', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('sends the current draft prompt and history partition', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({
          agent: 'mus',
          selection: {
            requested_tool_names: [],
            offered_tool_names: [],
            rejected_tool_names: [],
            rejected_tools: [],
            selected_schema_tokens: 0,
            active_profile_id: 'no_tools',
            active_profile_name: 'No APEX Tools',
          },
          breakdown: {
            system_instructions: 10,
            conversation_history: 5,
            hud_context: 0,
            selected_tool_schemas: 0,
            current_prompt: 4,
            total: 19,
            configured_context_window: 4096,
            reserved_response_tokens: 512,
            remaining_estimated_capacity: 3565,
            is_estimate: true,
          },
          warning: null,
          can_proceed: true,
        }),
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    renderHook(() =>
      useToolPreflight({
        agent: 'mus',
        selectedToolNames: noSelectedTools,
        toolProfileId: 'no_tools',
        prompt: '  typed draft  ',
        historyPartition: 'production',
        enabled: true,
      }),
    )

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const calls = fetchMock.mock.calls as unknown as Array<
      [unknown, RequestInit | undefined]
    >
    const request = calls[0]?.[1]
    expect(JSON.parse(String(request?.body))).toMatchObject({
      prompt: '  typed draft  ',
      selected_tool_names: [],
      tool_profile_id: 'no_tools',
      history_partition: 'production',
    })
  })

  it('clears an old estimate on Agent changes and ignores the superseded response', async () => {
    type MockResponse = { ok: boolean; json: () => Promise<unknown> }
    let resolveFirst: ((value: MockResponse) => void) | undefined
    const firstResponse = new Promise<MockResponse>((resolve) => {
      resolveFirst = resolve
    })
    const responseFor = (agent: 'mus' | 'acinonyx'): MockResponse => ({
      ok: true,
      json: async () => ({
        agent,
        selection: {
          requested_tool_names: [],
          offered_tool_names: [],
          rejected_tool_names: [],
          rejected_tools: [],
          selected_schema_tokens: 0,
          active_profile_id: 'no_tools',
          active_profile_name: 'No APEX Tools',
        },
        breakdown: {
          system_instructions: 10,
          conversation_history: 0,
          hud_context: 0,
          selected_tool_schemas: 0,
          current_prompt: 2,
          total: 12,
          configured_context_window: agent === 'mus' ? 4096 : null,
          reserved_response_tokens: agent === 'mus' ? 512 : null,
          remaining_estimated_capacity: agent === 'mus' ? 3572 : null,
          is_estimate: true,
        },
        warning: null,
        can_proceed: true,
      }),
    })
    const fetchMock = vi.fn()
      .mockReturnValueOnce(firstResponse)
      .mockResolvedValueOnce(responseFor('acinonyx'))
    vi.stubGlobal('fetch', fetchMock)

    const hook = renderHook(
      ({ agent }: { agent: 'mus' | 'acinonyx' }) =>
        useToolPreflight({
          agent,
          selectedToolNames: noSelectedTools,
          toolProfileId: 'no_tools',
          enabled: true,
        }),
      { initialProps: { agent: 'mus' } },
    )
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    hook.rerender({ agent: 'acinonyx' })
    await waitFor(() => {
      expect(hook.result.current.estimate).toBeNull()
      expect(hook.result.current.error).toBeNull()
    })

    resolveFirst?.(responseFor('mus'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(hook.result.current.estimate?.agent).toBe('acinonyx'))
    expect(hook.result.current.estimate?.agent).not.toBe('mus')
  })

  it('clears the estimate, error, and loading state when disabled', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        agent: 'mus',
        selection: {
          requested_tool_names: [],
          offered_tool_names: [],
          rejected_tool_names: [],
          rejected_tools: [],
          selected_schema_tokens: 0,
          active_profile_id: 'no_tools',
          active_profile_name: 'No APEX Tools',
        },
        breakdown: {
          system_instructions: 1,
          conversation_history: 0,
          hud_context: 0,
          selected_tool_schemas: 0,
          current_prompt: 1,
          total: 2,
          configured_context_window: 4096,
          reserved_response_tokens: 512,
          remaining_estimated_capacity: 3582,
          is_estimate: true,
        },
        warning: null,
        can_proceed: true,
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const hook = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        useToolPreflight({
          agent: 'mus',
          selectedToolNames: noSelectedTools,
          toolProfileId: 'no_tools',
          enabled,
        }),
      { initialProps: { enabled: true } },
    )
    await waitFor(() => expect(hook.result.current.estimate).not.toBeNull())
    hook.rerender({ enabled: false })
    await waitFor(() => {
      expect(hook.result.current.estimate).toBeNull()
      expect(hook.result.current.error).toBeNull()
      expect(hook.result.current.isLoading).toBe(false)
    })
  })
})
