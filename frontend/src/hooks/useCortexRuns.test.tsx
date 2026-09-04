import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { RunRecord } from '../types/runs'
import { useCortexRuns } from './useCortexRuns'

function createMockRun(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: overrides.id ?? 'run-1',
    conversation_id: overrides.conversation_id ?? 'conv-1',
    partition: overrides.partition ?? 'production',
    user_message_id: overrides.user_message_id ?? 'msg-u-1',
    agent_message_id: overrides.agent_message_id ?? 'msg-a-1',
    requested_model: overrides.requested_model ?? 'test-model',
    resolved_model: overrides.resolved_model ?? 'test-model',
    provider: overrides.provider ?? 'llama_cpp',
    runtime: overrides.runtime ?? 'local',
    status: overrides.status ?? 'completed',
    stop_reason: overrides.stop_reason ?? 'end_turn',
    created_at: overrides.created_at ?? '2026-09-03T12:00:00Z',
    started_at: overrides.started_at ?? '2026-09-03T12:00:01Z',
    completed_at: overrides.completed_at ?? '2026-09-03T12:00:05Z',
    updated_at: overrides.updated_at ?? '2026-09-03T12:00:05Z',
    limit_snapshot: {
      max_elapsed_seconds: 60,
      max_total_tokens: 4096,
      max_retries: 3,
      max_model_turns: 5,
      max_tool_calls: 10,
    },
    turns_count: 1,
    tool_calls_count: 0,
    retries_count: 0,
    total_tokens: 150,
    elapsed_seconds: 4,
    usage_quality: 'reported',
    runtime_measurements: {
      queue_duration_ms: 50,
      prompt_eval_duration_ms: 120,
      eval_duration_ms: 3800,
      total_duration_ms: 4000,
      ttft_ms: 180,
      tokens_per_second: 35.5,
    },
    evidence: {
      answer_persisted: true,
      tool_outcome_counts: {},
      action_ids: [],
    },
    trace_id: 'trace-1',
    error: null,
    ...overrides,
  }
}

describe('useCortexRuns', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches runs on mount and classifies active runs', async () => {
    const mockRuns = [
      createMockRun({ id: 'run-active', status: 'running' }),
      createMockRun({ id: 'run-done', status: 'completed' }),
    ]

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/v1/cortex/runs')) {
        return new Response(JSON.stringify(mockRuns), { status: 200 })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const { result } = renderHook(() => useCortexRuns({ pollingEnabled: false }))

    await waitFor(() => expect(result.current.runs).toHaveLength(2))
    expect(result.current.activeRuns).toHaveLength(1)
    expect(result.current.activeRuns[0].id).toBe('run-active')
    expect(result.current.selectedRun?.id).toBe('run-active')
  })

  it('resolves active conversation run and supports manual selection', async () => {
    const mockRuns = [
      createMockRun({ id: 'run-c1', conversation_id: 'conv-1', status: 'completed' }),
      createMockRun({ id: 'run-c2', conversation_id: 'conv-2', status: 'running' }),
    ]

    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(mockRuns), { status: 200 }),
    )

    const { result } = renderHook(() => useCortexRuns({ conversationId: 'conv-2', pollingEnabled: false }))

    await waitFor(() => expect(result.current.runs).toHaveLength(2))

    // Defaults to active run of current conversation
    expect(result.current.selectedRun?.id).toBe('run-c2')
    expect(result.current.activeConversationRun('conv-2')?.id).toBe('run-c2')
    expect(result.current.activeConversationRun('conv-1')).toBeNull()

    // Explicit selection
    act(() => {
      result.current.selectRun('run-c1')
    })

    expect(result.current.selectedRun?.id).toBe('run-c1')
  })

  it('cancels run through API and refreshes run list', async () => {
    let cancelCalled = false
    const activeRun = createMockRun({ id: 'run-cancel-test', status: 'running' })
    const cancelledRun = createMockRun({ id: 'run-cancel-test', status: 'cancelling' })

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.includes('/api/v1/cortex/runs/run-cancel-test/cancel') && init?.method === 'POST') {
        cancelCalled = true
        return new Response(JSON.stringify(cancelledRun), { status: 200 })
      }
      if (url.includes('/api/v1/cortex/runs')) {
        return new Response(JSON.stringify(cancelCalled ? [cancelledRun] : [activeRun]), { status: 200 })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const { result } = renderHook(() => useCortexRuns({ pollingEnabled: false }))
    await waitFor(() => expect(result.current.runs).toHaveLength(1))

    let success = false
    await act(async () => {
      success = await result.current.cancelRun('run-cancel-test')
    })

    expect(success).toBe(true)
    expect(cancelCalled).toBe(true)
    expect(result.current.runs[0].status).toBe('cancelling')
  })

  it('triggers refresh on window focus', async () => {
    let fetchCount = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      fetchCount += 1
      return new Response(JSON.stringify([]), { status: 200 })
    })

    renderHook(() => useCortexRuns({ pollingEnabled: true }))
    await waitFor(() => expect(fetchCount).toBe(1))

    act(() => {
      window.dispatchEvent(new Event('focus'))
    })

    await waitFor(() => expect(fetchCount).toBe(2))
  })
})
