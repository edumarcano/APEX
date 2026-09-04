import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { CortexActiveRunStrip } from './CortexActiveRunStrip'
import type { RunRecord } from '../types/runs'

function createMockRun(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: 'run-strip-1',
    conversation_id: 'conv-strip-1',
    partition: 'production',
    user_message_id: 'user-msg-strip-1',
    agent_message_id: 'agent-msg-strip-1',
    status: 'running',
    stop_reason: null,
    requested_model: 'gemma-4-E2B-Q4_K_M.gguf',
    resolved_model: 'gemma-4-E2B-Q4_K_M.gguf',
    provider: 'llama_cpp',
    runtime: 'local',
    turns_count: 1,
    tool_calls_count: 0,
    retries_count: 0,
    total_tokens: 250,
    usage_quality: 'reported',
    elapsed_seconds: 4.2,
    created_at: new Date(Date.now() - 4200).toISOString(),
    started_at: new Date(Date.now() - 4200).toISOString(),
    completed_at: null,
    updated_at: new Date(Date.now() - 4200).toISOString(),
    limit_snapshot: {
      max_elapsed_seconds: 600,
      max_total_tokens: 16384,
      max_retries: 4,
      max_model_turns: 6,
      max_tool_calls: 10,
    },
    evidence: {
      final_message_status: null,
      answer_persisted: false,
      tool_outcome_counts: {},
      action_ids: [],
    },
    runtime_measurements: {
      queue_duration_ms: 10,
      prompt_eval_duration_ms: 50,
      eval_duration_ms: 120,
      total_duration_ms: 170,
      ttft_ms: 45,
      tokens_per_second: 25,
      eval_count: 3,
      prompt_eval_count: 10,
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

  it('renders compact active indicator with agent name, elapsed time, and aria-live region', () => {
    const run = createMockRun({ status: 'running' })
    render(<CortexActiveRunStrip run={run} agentName="Apex" />)

    const indicator = screen.getByTestId('cortex-active-run-strip')
    expect(indicator).toBeInTheDocument()
    expect(indicator).toHaveAttribute('aria-live', 'polite')
    expect(screen.getByText('Apex working')).toBeInTheDocument()
  })

  it('triggers onInspect when inspect button is clicked', async () => {
    const onInspect = vi.fn()
    const run = createMockRun({ status: 'running' })
    const user = userEvent.setup()

    render(<CortexActiveRunStrip run={run} agentName="Apex" onInspect={onInspect} />)

    const inspectBtn = screen.getByRole('button', { name: 'Inspect active run' })
    expect(inspectBtn).toHaveClass('hover:text-[#C084FC]')
    await user.click(inspectBtn)

    expect(onInspect).toHaveBeenCalledTimes(1)
  })

  it('reflects status-specific indicator styling for cancelling and queued states', () => {
    const { rerender } = render(<CortexActiveRunStrip run={createMockRun({ status: 'cancelling' })} />)
    expect(screen.getByTestId('cortex-active-run-strip')).toBeInTheDocument()

    rerender(<CortexActiveRunStrip run={createMockRun({ status: 'queued' })} />)
    expect(screen.getByTestId('cortex-active-run-strip')).toBeInTheDocument()
  })
})
