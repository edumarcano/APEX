import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useToolPreflight } from './useToolPreflight'

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
            active_profile_name: 'No Tools',
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
        selectedToolNames: [],
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
})
