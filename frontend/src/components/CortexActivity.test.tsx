import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { UseCortexRunsResult } from '../hooks/useCortexRuns'
import type { RunRecord } from '../types/runs'
import type { AgentStatus } from '../types/telemetry'
import { CortexActivity } from './CortexActivity'

function createMockRun(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: overrides.id ?? 'run-act-1',
    conversation_id: 'conv-act',
    partition: 'production',
    user_message_id: 'msg-u',
    agent_message_id: 'msg-a',
    requested_model: overrides.requested_model ?? 'gemma-4',
    resolved_model: overrides.resolved_model ?? 'gemma-4',
    provider: overrides.provider ?? 'llama_cpp',
    runtime: overrides.runtime ?? 'local',
    status: overrides.status ?? 'completed',
    stop_reason: overrides.stop_reason ?? 'end_turn',
    created_at: '2026-09-03T14:00:00Z',
    started_at: '2026-09-03T14:00:01Z',
    completed_at: '2026-09-03T14:00:04Z',
    updated_at: '2026-09-03T14:00:04Z',
    limit_snapshot: {
      max_elapsed_seconds: 60,
      max_total_tokens: 4096,
      max_retries: 3,
      max_model_turns: 5,
      max_tool_calls: 10,
    },
    turns_count: 2,
    tool_calls_count: 1,
    retries_count: 0,
    total_tokens: 450,
    elapsed_seconds: 3.5,
    usage_quality: 'reported',
    runtime_measurements: {
      queue_duration_ms: 80,
      prompt_eval_duration_ms: 150,
      eval_duration_ms: 3270,
      total_duration_ms: 3500,
      ttft_ms: 230,
      tokens_per_second: 38.2,
    },
    evidence: {
      answer_persisted: true,
      tool_outcome_counts: { reminders: 1 },
      action_ids: ['action-12345678'],
    },
    trace_id: 'trace-act-1',
    error: null,
    ...overrides,
  }
}

function createMockRunsState(overrides: Partial<UseCortexRunsResult> = {}): UseCortexRunsResult {
  const defaultRun = createMockRun()
  return {
    runs: overrides.runs ?? [defaultRun],
    activeRuns: overrides.activeRuns ?? [],
    selectedRunId: overrides.selectedRunId ?? defaultRun.id,
    selectedRun: overrides.selectedRun ?? defaultRun,
    loading: overrides.loading ?? false,
    error: overrides.error ?? null,
    selectRun: overrides.selectRun ?? vi.fn(),
    activeConversationRun: overrides.activeConversationRun ?? vi.fn(),
    cancelRun: overrides.cancelRun ?? vi.fn(),
    refreshRuns: overrides.refreshRuns ?? vi.fn(),
  }
}

describe('CortexActivity', () => {
  it('renders empty state when no runs recorded', () => {
    const runsState = createMockRunsState({
      runs: [],
      selectedRunId: null,
      selectedRun: null,
    })

    render(<CortexActivity runsState={runsState} />)

    expect(screen.getByText('No Cortex runs recorded yet.')).toBeInTheDocument()
  })

  it('renders recent runs list and detailed execution telemetry', () => {
    const run1 = createMockRun({ id: 'run-1', requested_model: 'gemma-4', resolved_model: 'gemma-4' })
    const run2 = createMockRun({ id: 'run-2', requested_model: 'claude-3-7', resolved_model: 'claude-3-7', status: 'running' })
    const selectRun = vi.fn()

    const runsState = createMockRunsState({
      runs: [run2, run1],
      selectedRunId: 'run-1',
      selectedRun: run1,
      selectRun,
    })

    const agentsStatus: AgentStatus[] = [
      {
        key: 'apex',
        display_name: 'Apex Agent',
        description: 'Native',
        configured_model: 'gemma-4',
        native_tools: {},
        provider: 'llama_cpp',
        sort_order: 0,
        capabilities: [],
        runtime: 'local',
        model_stability: 'stable',
        context_window: 16384,
        context_window_options: null,
        context_window_high_resource_options: null,
        default_context_window: null,
        reasoning_mode: null,
        reasoning_mode_options: null,
        default_reasoning_mode: null,
        status: 'available',
        status_source: 'configuration',
        status_checked_at: null,
        provider_account_tier: null,
        pricing: {
          currency: 'USD',
          pricing_version: 'test',
          billing_basis: 'local',
          input_per_million: 0,
          output_per_million: 0,
          cached_input_per_million: null,
          long_context_threshold_tokens: null,
          long_context_input_per_million: null,
          long_context_output_per_million: null,
          long_context_cached_input_per_million: null,
        },
        active: true,
        loading: false,
        reason: null,
        idle_unload_remaining_seconds: 180,
        loaded_model: null,
        model_catalog: [
          {
            model_id: 'gemma-4',
            display_name: 'Gemma 4',
            provider: 'llama_cpp',
            runtime: 'local',
            stability: 'stable',
            hosted_capabilities: [],
            active: true,
            idle_unload_remaining_seconds: 180,
          },
        ],
      },
    ]

    render(
      <CortexActivity
        runsState={runsState}
        agentsStatus={agentsStatus}
      />,
    )

    // Check header and list
    expect(screen.getByText('Cortex Live Activity')).toBeInTheDocument()
    expect(screen.getByText('2 runs')).toBeInTheDocument()

    // Check gauges and metrics
    expect(screen.getByText('Limit Consumption')).toBeInTheDocument()
    expect(screen.getByText('Runtime Measurements')).toBeInTheDocument()
    expect(screen.getByText('38.2 tok/s')).toBeInTheDocument()

    // Check evidence
    expect(screen.getByText('Execution Evidence')).toBeInTheDocument()
    expect(screen.getByText('reminders')).toBeInTheDocument()
    expect(screen.getByText('action-1…')).toBeInTheDocument()

    // Check resident local model
    expect(screen.getByText('Resident Local Model')).toBeInTheDocument()
    expect(screen.getByText('Idle unload in 180s')).toBeInTheDocument()
  })

  it('allows changing selection via dropdown', async () => {
    const run1 = createMockRun({ id: 'run-1', status: 'running' })
    const run2 = createMockRun({ id: 'run-2', status: 'completed' })
    const selectRun = vi.fn()
    const user = userEvent.setup()

    const runsState = createMockRunsState({
      runs: [run1, run2],
      selectedRunId: 'run-1',
      selectedRun: run1,
      selectRun,
    })

    render(<CortexActivity runsState={runsState} />)

    // Select another run via dropdown
    const select = screen.getByRole('combobox', { name: 'Select run' })
    await user.selectOptions(select, 'run-2')
    expect(selectRun).toHaveBeenCalledWith('run-2')
  })

  it('copies run ID to clipboard when copy button is clicked', async () => {
    const run = createMockRun({ id: '00000000-0000-4000-8000-000000000042' })
    const runsState = createMockRunsState({
      runs: [run],
      selectedRunId: run.id,
      selectedRun: run,
    })
    const writeSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)
    const user = userEvent.setup()

    render(<CortexActivity runsState={runsState} />)

    const copyBtn = screen.getByRole('button', { name: 'Copy run ID' })
    await user.click(copyBtn)
    expect(writeSpy).toHaveBeenCalledWith('00000000-0000-4000-8000-000000000042')
    expect(screen.getByText('Copied')).toBeInTheDocument()
  })
})
