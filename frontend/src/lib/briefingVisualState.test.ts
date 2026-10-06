import { describe, expect, it } from 'vitest'

import type { BriefingSessionDetail } from '../types/briefings'
import { resolveActiveBriefingActivity, resolveBriefingLogoActivity, resolveBriefingVisualState } from './briefingVisualState'

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
      status: 'loading', step: 2, activity: 'collecting',
    })
    expect(resolveBriefingVisualState({ ...SESSION, active_stage: { stage: 'investigating', state: 'started' } })).toEqual({
      status: 'loading', step: 3, activity: 'investigating',
    })
    expect(resolveBriefingVisualState({ ...SESSION, active_stage: { stage: 'persisting', state: 'started' } })).toEqual({
      status: 'loading', step: 4, activity: 'persisting',
    })
    expect(resolveBriefingVisualState({ ...SESSION, run_status: 'queued' })).toEqual({ status: 'loading', step: null, activity: 'preparing' })
  })

  it('maps terminal session outcomes and missing sessions to stable visual states', () => {
    expect(resolveBriefingVisualState({ ...SESSION, run_status: 'completed' })).toEqual({ status: 'success', step: null, activity: 'briefing_ready' })
    expect(resolveBriefingVisualState({ ...SESSION, run_status: 'failed' })).toEqual({ status: 'error', step: null, activity: null })
    expect(resolveBriefingVisualState(null)).toEqual({ status: 'idle', step: null, activity: null })
  })
})

describe('resolveBriefingLogoActivity', () => {
  const activeSynthesis = {
    activeRun: true,
    activeActivity: 'synthesizing' as const,
    selectedActivity: 'briefing_ready' as const,
    isPreparingSpeech: false,
    isSpeaking: false,
  }

  it('prioritizes speech preparation and playback over another active briefing, then resumes that stage', () => {
    expect(resolveBriefingLogoActivity({ ...activeSynthesis, isPreparingSpeech: true })).toBe('speech_preparing')
    expect(resolveBriefingLogoActivity({ ...activeSynthesis, isSpeaking: true })).toBe('speech_playing')
    expect(resolveBriefingLogoActivity(activeSynthesis)).toBe('synthesizing')
  })

  it('uses the queued fallback for an active run without detail and selected state when idle', () => {
    expect(resolveBriefingLogoActivity({ ...activeSynthesis, activeActivity: null })).toBe('preparing')
    expect(resolveBriefingLogoActivity({ ...activeSynthesis, activeRun: false })).toBe('briefing_ready')
  })
})

describe('resolveActiveBriefingActivity', () => {
  it('uses the active summary and its model when another session is selected', () => {
    const activeSummary = {
      id: 'active-session',
      profile_id: 'daily',
      model_id: 'gemma-4-E2B-Q4_K_M.gguf',
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
        model_id: 'gemma-4-E2B-Q4_K_M.gguf',
        display_name: 'Gemma 4 E2B',
        provider: 'llama_cpp',
        runtime: 'local',
        stability: 'stable',
        hosted_capabilities: [],
      }],
    })

    expect(result).toEqual({
      session: activeSummary,
      isRunning: true,
      isLocalModelRunning: true,
      modelId: 'gemma-4-E2B-Q4_K_M.gguf',
      displayName: 'Gemma 4 E2B',
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
