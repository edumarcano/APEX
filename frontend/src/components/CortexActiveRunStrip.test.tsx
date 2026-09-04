import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { RunRecord } from '../types/runs'
import { CortexActiveRunStrip } from './CortexActiveRunStrip'

function createMockRun(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: overrides.id ?? 'run-strip-1',
    conversation_id: overrides.conversation_id ?? 'conv-strip',
    partition: 'production',
    user_message_id: 'msg-u',
    agent_message_id: 'msg-a',
    requested_model: overrides.requested_model ?? 'gemma-4-E2B-Q4_K_M.gguf',
    resolved_model: overrides.resolved_model ?? 'gemma-4-E2B-Q4_K_M.gguf',
    provider: 'llama_cpp',
    runtime: 'local',
    status: overrides.status ?? 'running',
    stop_reason: overrides.stop_reason ?? null,
    created_at: new Date(Date.now() - 5000).toISOString(),
    started_at: new Date(Date.now() - 4000).toISOString(),
    completed_at: null,
    updated_at: new Date().toISOString(),
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
    total_tokens: overrides.total_tokens ?? 250,
    elapsed_seconds: 4,
    usage_quality: 'reported',
    runtime_measurements: {
      queue_duration_ms: 100,
      prompt_eval_duration_ms: 200,
      eval_duration_ms: 3700,
      total_duration_ms: 4000,
      ttft_ms: 300,
      tokens_per_second: 42.1,
    },
    evidence: {
      answer_persisted: true,
      tool_outcome_counts: {},
      action_ids: [],
    },
    trace_id: 'trace-strip-1',
    error: null,
    ...overrides,
  }
}

describe('CortexActiveRunStrip', () => {
  it('renders nothing when run is null or terminal', () => {
    const { container, rerender } = render(<CortexActiveRunStrip run={null} />)
    expect(container.firstChild).toBeNull()

    rerender(<CortexActiveRunStrip run={createMockRun({ status: 'completed' })} />)
    expect(container.firstChild).toBeNull()

    rerender(<CortexActiveRunStrip run={createMockRun({ status: 'failed' })} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders active run information with polite aria-live region', () => {
    const run = createMockRun({ status: 'running', resolved_model: 'gemma-4-E2B-Q4_K_M.gguf' })
    render(<CortexActiveRunStrip run={run} />)

    const strip = screen.getByTestId('cortex-active-run-strip')
    expect(strip).toBeInTheDocument()
    expect(strip).toHaveAttribute('aria-live', 'polite')
    expect(screen.getByText('running')).toBeInTheDocument()
    expect(screen.getByText('gemma-4-E2B-Q4_K_M.gguf')).toBeInTheDocument()
    expect(screen.getByText('250 tokens')).toBeInTheDocument()
  })

  it('triggers onInspect when inspect button is clicked', async () => {
    const onInspect = vi.fn()
    const run = createMockRun({ status: 'running' })
    const user = userEvent.setup()

    render(<CortexActiveRunStrip run={run} onInspect={onInspect} />)

    const inspectBtn = screen.getByRole('button', { name: 'Inspect run details' })
    await user.click(inspectBtn)

    expect(onInspect).toHaveBeenCalledTimes(1)
  })

  it('triggers onCancel when stop button is clicked, and hides stop button when cancelling', async () => {
    const onCancel = vi.fn()
    const run = createMockRun({ id: 'test-run-id', status: 'running' })
    const user = userEvent.setup()

    const { rerender } = render(<CortexActiveRunStrip run={run} onCancel={onCancel} />)

    const stopBtn = screen.getByRole('button', { name: 'Stop run' })
    await user.click(stopBtn)

    expect(onCancel).toHaveBeenCalledWith('test-run-id')

    rerender(<CortexActiveRunStrip run={{ ...run, status: 'cancelling' }} onCancel={onCancel} />)
    expect(screen.queryByRole('button', { name: 'Stop run' })).not.toBeInTheDocument()
    expect(screen.getByText('cancelling')).toBeInTheDocument()
  })
})
