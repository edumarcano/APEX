import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { BriefingSessionDetail, BriefingSessionSummary } from '../types/briefings'
import { resolveBriefingLayoutPhase, useHomeView } from './useHomeView'

function summary(run_status: BriefingSessionSummary['run_status']): BriefingSessionSummary {
  return { id: 's1', profile_id: 'daily', model_id: 'm', conversation_id: 'c1', run_id: 'r1', run_status, created_at: '2026-09-25T13:00:00Z', presented_at: null }
}

function detail(run_status: BriefingSessionDetail['run_status'], withArtifact: boolean): BriefingSessionDetail {
  return {
    id: 's1',
    conversation_id: 'c1',
    opening_message_id: 'o1',
    run_id: 'r1',
    run_status,
    run_error_code: null,
    configuration: {
      profile: { id: 'daily', label: 'Daily', purpose: 'p', definition_version: 2 },
      model: { model_id: 'm', provider: 'demo', runtime: 'demo', reasoning: null, context_window: null, local_reasoning_mode: null },
      origin: 'hud',
      execution_kind: 'demo',
    },
    artifact: withArtifact ? { schema_version: 1, session_id: 's1', created_at: '2026-09-25T13:00:00Z', sections: [], coverage: [], limitations: [] } : null,
    evidence_count: 0,
    evidence_ids: [],
    created_at: '2026-09-25T13:00:00Z',
    presented_at: null,
    speech_status: 'not_requested',
  }
}

describe('useHomeView', () => {
  it('is Standby until activated, then shows the chosen destination', () => {
    const deactivate = vi.fn()
    const { result, rerender } = renderHook((props: { activated: boolean; destination: 'overview' | 'briefing' }) => useHomeView({ ...props, deactivate }), { initialProps: { activated: false, destination: 'briefing' } })
    expect(result.current.view).toBe('standby')

    rerender({ activated: true, destination: 'briefing' })
    expect(result.current.view).toBe('briefing')
    rerender({ activated: true, destination: 'overview' })
    expect(result.current.view).toBe('overview')
  })

  it('returns to Standby only through deactivation and keeps the profile', () => {
    const deactivate = vi.fn()
    const { result, rerender } = renderHook((props: { activated: boolean }) => useHomeView({ ...props, destination: 'briefing', deactivate }), { initialProps: { activated: true } })
    act(() => result.current.setProfileId('catch_up'))

    act(() => result.current.returnToStandby())
    expect(deactivate).toHaveBeenCalledTimes(1)
    rerender({ activated: false })
    expect(result.current.view).toBe('standby')

    rerender({ activated: true })
    expect(result.current.view).toBe('briefing')
    expect(result.current.profileId).toBe('catch_up')
  })
})

describe('resolveBriefingLayoutPhase', () => {
  it('uses the identity layout without an open session and after failure', () => {
    expect(resolveBriefingLayoutPhase({ session: null, selectedSession: null, isGenerating: false })).toBe('identity')
    expect(resolveBriefingLayoutPhase({ session: detail('failed', false), selectedSession: summary('failed'), isGenerating: false })).toBe('identity')
    expect(resolveBriefingLayoutPhase({ session: detail('cancelled', false), selectedSession: summary('cancelled'), isGenerating: false })).toBe('identity')
  })

  it('keeps the generating layout while admission or the run is in progress', () => {
    expect(resolveBriefingLayoutPhase({ session: null, selectedSession: null, isGenerating: true })).toBe('generating')
    expect(resolveBriefingLayoutPhase({ session: null, selectedSession: summary('running'), isGenerating: false })).toBe('generating')
    expect(resolveBriefingLayoutPhase({ session: detail('running', false), selectedSession: summary('running'), isGenerating: false })).toBe('generating')
  })

  it('opens the workspace only for a completed session with an artifact', () => {
    expect(resolveBriefingLayoutPhase({ session: detail('completed', true), selectedSession: summary('completed'), isGenerating: false })).toBe('workspace')
    expect(resolveBriefingLayoutPhase({ session: null, selectedSession: summary('completed'), isGenerating: false })).toBe('identity')
  })
})
