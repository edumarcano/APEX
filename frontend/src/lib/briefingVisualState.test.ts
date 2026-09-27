import { describe, expect, it } from 'vitest'

import type { BriefingSessionDetail } from '../types/briefings'
import { resolveActiveBriefingActivity, resolveBriefingVisualState } from './briefingVisualState'

const SESSION = {
  id: 'session-1',
  conversation_id: 'conversation-1',
  opening_message_id: 'message-1',
  run_id: 'run-1',
  run_status: 'running',
  run_error_code: null,
  configuration: {
    profile: { id: 'daily', label: 'Daily', purpose: 'Current information', definition_version: 1 },
    model: {
      model_id: 'test/model', provider: 'openrouter', runtime: 'cloud',
      reasoning: null, context_window: null, local_reasoning_mode: null,
    },
    origin: 'hud', execution_kind: 'model',
  },
  artifact: null,
  evidence_count: 0,
  evidence_ids: [],
  created_at: '2026-09-26T10:00:00Z',
  presented_at: null,
  speech_status: 'not_requested',
} satisfies BriefingSessionDetail

describe('resolveBriefingVisualState', () => {
  it('maps active session status and stages to the HUD progress contract', () => {
    expect(resolveBriefingVisualState({ ...SESSION, active_stage: { stage: 'collecting', state: 'started' } })).toEqual({
      status: 'loading', step: 2,
    })
    expect(resolveBriefingVisualState({ ...SESSION, active_stage: { stage: 'investigating', state: 'started' } })).toEqual({
      status: 'loading', step: 3,
    })
    expect(resolveBriefingVisualState({ ...SESSION, active_stage: { stage: 'persisting', state: 'started' } })).toEqual({
      status: 'loading', step: 4,
    })
  })

  it('maps terminal session outcomes and missing sessions to stable visual states', () => {
    expect(resolveBriefingVisualState({ ...SESSION, run_status: 'completed' })).toEqual({ status: 'success', step: null })
    expect(resolveBriefingVisualState({ ...SESSION, run_status: 'failed' })).toEqual({ status: 'error', step: null })
    expect(resolveBriefingVisualState(null)).toEqual({ status: 'idle', step: null })
  })
})

describe('resolveActiveBriefingActivity', () => {
  it('uses the active summary and its model when another session is selected', () => {
    const activeSummary = {
      id: 'active-session',
      profile_id: 'daily',
      model_id: 'qwen3:1.7b',
      conversation_id: 'active-conversation',
      run_id: 'active-run',
      run_status: 'running',
      created_at: '2026-09-26T10:00:00Z',
      presented_at: null,
    } as const
    const selectedOlderSession = { ...SESSION, id: 'older-session', configuration: {
      ...SESSION.configuration,
      model: { ...SESSION.configuration.model, runtime: 'local' as const },
    } }
    const result = resolveActiveBriefingActivity({
      sessions: [activeSummary],
      selectedSessionId: 'older-session',
      selectedSession: selectedOlderSession,
      modelCatalog: [{
        model_id: 'qwen3:1.7b',
        display_name: 'Qwen 3 1.7B',
        provider: 'ollama',
        runtime: 'local',
        stability: 'stable',
        hosted_capabilities: [],
      }],
    })

    expect(result).toEqual({
      session: activeSummary,
      isRunning: true,
      isLocalModelRunning: true,
      modelId: 'qwen3:1.7b',
      displayName: 'Qwen 3 1.7B',
    })
  })

  it('does not take runtime identity from an unrelated selected session', () => {
    const activeSummary = {
      id: 'active-session',
      profile_id: 'daily',
      model_id: 'unknown/model',
      conversation_id: 'active-conversation',
      run_id: 'active-run',
      run_status: 'running',
      created_at: '2026-09-26T10:00:00Z',
      presented_at: null,
    } as const
    const selectedOlderSession = { ...SESSION, id: 'older-session', configuration: {
      ...SESSION.configuration,
      model: { ...SESSION.configuration.model, runtime: 'local' as const },
    } }
    const result = resolveActiveBriefingActivity({
      sessions: [activeSummary],
      selectedSessionId: 'older-session',
      selectedSession: selectedOlderSession,
      modelCatalog: [],
    })

    expect(result.isRunning).toBe(true)
    expect(result.isLocalModelRunning).toBe(false)
    expect(result.modelId).toBeNull()
  })
})
