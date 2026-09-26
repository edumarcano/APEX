import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { BriefingSessionDetail } from '../../types/briefings'
import { BriefingArtifactMessage } from './BriefingArtifactMessage'

function completedDemoSession(): BriefingSessionDetail {
  return {
    id: 'session-1',
    conversation_id: 'conversation-1',
    opening_message_id: 'message-1',
    run_id: 'run-1',
    run_status: 'completed',
    run_error_code: null,
    configuration: {
      profile: { id: 'daily', label: 'Daily', purpose: 'Current information.', definition_version: 2 },
      model: { model_id: 'demo/daily-fixture', provider: 'demo', runtime: 'demo', reasoning: null, context_window: null, local_reasoning_mode: null },
      origin: 'hud',
      execution_kind: 'demo',
    },
    artifact: {
      schema_version: 1,
      session_id: 'session-1',
      created_at: '2026-09-25T13:00:00Z',
      sections: [{
        id: 'section-1',
        title: 'Today',
        items: [
          { id: 'item-1', category: 'analysis', title: 'External item', body: 'Body.', evidence_ids: ['evidence-1'], record_references: [{ kind: 'external_activity', id: 'report-1' }] },
          { id: 'item-2', category: 'suggestion', title: 'Review item', body: 'Body.', evidence_ids: [], record_references: [{ kind: 'context_review', id: 'review-1' }] },
        ],
      }],
      coverage: [{ source: 'calendar', scope: 'today', status: 'partial', observed_at: null, window_start: null, window_end: null, freshness_seconds: null, truncated: true, reason: 'Calendar was slow.' }],
      limitations: ['Email was not read.'],
    },
    evidence_count: 1,
    evidence_ids: ['evidence-1'],
    created_at: '2026-09-25T13:00:00Z',
    presented_at: null,
    speech_status: 'not_requested',
  }
}

function renderMessage(session = completedDemoSession()) {
  return render(<BriefingArtifactMessage
    session={session}
    isLoadingSession={false}
    evidence={{ evidenceById: {}, loadingIds: [], errors: {}, onLoadEvidence: vi.fn(async () => {}) }}
    onMarkPresented={vi.fn(async () => {})}
  />)
}

afterEach(() => vi.unstubAllGlobals())

describe('BriefingArtifactMessage', () => {
  it('labels untrusted reports and pending reviews before evidence is fetched', () => {
    renderMessage()

    expect(screen.getByText('Includes an attributed, untrusted external report.')).toBeInTheDocument()
    expect(screen.getByText('Includes a pending review that has not been accepted into personal context.')).toBeInTheDocument()
    expect(screen.getByText('Inspect source record evidence')).toBeInTheDocument()
  })

  it('shows an explicit DEMO fixture marker instead of a model', () => {
    renderMessage()

    expect(screen.getByText(/Deterministic demo fixture/)).toBeInTheDocument()
    expect(screen.getByText(/DEMO fixture\. No model was run/)).toBeInTheDocument()
  })

  it('includes coverage and limitations with the artifact', () => {
    renderMessage()

    expect(screen.getByText('Calendar was slow.')).toBeInTheDocument()
    expect(screen.getByText('Email was not read.')).toBeInTheDocument()
  })

  it('keeps unreferenced evidence behind a closed disclosure that loads on open', async () => {
    const session = completedDemoSession()
    session.evidence_ids = ['evidence-1', 'evidence-2']
    const onLoadEvidence = vi.fn(async () => {})
    render(<BriefingArtifactMessage
      session={session}
      isLoadingSession={false}
      evidence={{ evidenceById: {}, loadingIds: [], errors: {}, onLoadEvidence }}
      onMarkPresented={vi.fn(async () => {})}
    />)

    const summary = screen.getByText(/Other captured evidence \(1\)/)
    const disclosure = summary.closest('details')
    expect(disclosure).not.toHaveAttribute('open')
    await userEvent.click(summary)
    expect(disclosure).toHaveAttribute('open')
  })
})
