import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { BriefingSessionDetail } from '../../types/briefings'
import { formatBriefingTime } from '../../lib/briefingFormat'
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
      comparison: {
        outcome: 'compared', summary: 'Found 1 changed item since the source checkpoints.',
        material_change_count: 1, no_material_changes: false,
        sources: [{
          source: 'calendar', status: 'compared', baseline_session_id: 'prior-session',
          baseline_snapshot_at: '2026-09-24T13:00:00Z', current_snapshot_at: '2026-09-25T13:00:00Z', reason: null,
        }],
      },
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

  it('discloses a limited Deep investigation and its omission reason', () => {
    const session = completedDemoSession()
    session.configuration.profile = { id: 'deep', label: 'Deep', purpose: 'An evidence-backed investigation.', definition_version: 1 }
    session.configuration.execution_kind = 'model'
    session.configuration.model.model_id = 'openrouter/test-model'
    session.artifact!.investigation = {
      status: 'limited', offered_tool_names: ['get_active_reminders'], used_tool_names: ['get_active_reminders'],
      result_count: 1, turns_used: 2, tool_calls_used: 1, time_budget_seconds: 90,
      limitations: ['One read result was truncated before saving.'],
    }
    renderMessage(session)

    expect(screen.getByRole('status')).toHaveTextContent('Deep investigation was limited after 1 untrusted read result.')
    expect(screen.getByRole('status')).toHaveTextContent('One read result was truncated before saving.')
  })

  it('labels completed Deep read results as untrusted', () => {
    const session = completedDemoSession()
    session.configuration.profile = { id: 'deep', label: 'Deep', purpose: 'An evidence-backed investigation.', definition_version: 1 }
    session.configuration.execution_kind = 'model'
    session.artifact!.investigation = {
      status: 'completed', offered_tool_names: ['get_active_reminders'], used_tool_names: ['get_active_reminders'],
      result_count: 1, turns_used: 2, tool_calls_used: 1, time_budget_seconds: 90, limitations: [],
    }
    renderMessage(session)

    expect(screen.getByRole('status')).toHaveTextContent('Deep added 1 untrusted bounded read result.')
  })

  it('shows when Deep decided no additional read was needed', () => {
    const session = completedDemoSession()
    session.configuration.profile = { id: 'deep', label: 'Deep', purpose: 'An evidence-backed investigation.', definition_version: 1 }
    session.configuration.execution_kind = 'model'
    session.artifact!.investigation = {
      status: 'no_read_needed', offered_tool_names: ['get_active_reminders'], used_tool_names: [],
      result_count: 0, turns_used: 1, tool_calls_used: 0, time_budget_seconds: 90, limitations: [],
    }
    renderMessage(session)

    expect(screen.getByRole('status')).toHaveTextContent('Deep used the saved snapshot; no additional read was needed.')
  })

  it('shows the Catch Up comparison period before its sections and source details', async () => {
    const session = completedDemoSession()
    session.configuration.profile = { id: 'catch_up', label: 'Catch Up', purpose: 'Changes since you last checked.', definition_version: 1 }
    renderMessage(session)

    const banner = screen.getByRole('region', { name: 'Catch Up comparison' })
    expect(banner).toHaveTextContent('Found 1 changed item since the source checkpoints.')
    expect(banner.textContent).toMatch(/baseline .*2026/)
    expect(banner.textContent).toMatch(/current .*2026/)
    const disclosure = screen.getByText(/Source coverage and limits/).closest('details')
    expect(disclosure).not.toHaveAttribute('open')
    await userEvent.click(screen.getByText(/Source coverage and limits/))
    const comparison = screen.getByRole('region', { name: 'Source comparison' })
    expect(comparison.textContent).toMatch(/baseline .*2026/)
    expect(comparison.textContent).toMatch(/current .*2026/)
  })

  it('orders the combined period by actual instants when source offsets differ', () => {
    const session = completedDemoSession()
    session.configuration.profile = { id: 'catch_up', label: 'Catch Up', purpose: 'Changes since you last checked.', definition_version: 1 }
    const earliestBaseline = '2026-09-25T02:00:00+02:00'
    const laterBaseline = '2026-09-24T23:30:00-04:00'
    const earlierCurrent = '2026-09-26T05:30:00+02:00'
    const latestCurrent = '2026-09-26T03:00:00-04:00'
    session.artifact!.comparison!.sources = [
      {
        source: 'calendar', status: 'compared', baseline_session_id: 'prior-calendar',
        baseline_snapshot_at: laterBaseline, current_snapshot_at: latestCurrent, reason: null,
      },
      {
        source: 'email', status: 'compared', baseline_session_id: 'prior-email',
        baseline_snapshot_at: earliestBaseline, current_snapshot_at: earlierCurrent, reason: null,
      },
    ]

    const banner = renderMessage(session).getByRole('region', { name: 'Catch Up comparison' })

    expect(banner).toHaveTextContent(`baseline ${formatBriefingTime(earliestBaseline)}`)
    expect(banner).toHaveTextContent(`current ${formatBriefingTime(latestCurrent)}`)
  })

  it('shows the explicit no-change result instead of a generic empty artifact', () => {
    const session = completedDemoSession()
    session.artifact!.sections = []
    session.artifact!.comparison = {
      outcome: 'no_change', summary: 'No material changes were found since the recorded source checkpoints.',
      sources: [{
        source: 'calendar', status: 'compared', baseline_session_id: 'prior-session',
        baseline_snapshot_at: '2026-09-24T13:00:00Z', current_snapshot_at: '2026-09-25T13:00:00Z', reason: null,
      }], material_change_count: 0, no_material_changes: true,
    }
    session.configuration.profile = { id: 'catch_up', label: 'Catch Up', purpose: 'Changes since you last checked.', definition_version: 1 }
    renderMessage(session)

    expect(screen.getByText(/No material changes were found/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Catch Up comparison' })).toHaveTextContent('baseline')
    expect(screen.queryByText('No briefing items were produced.')).not.toBeInTheDocument()
  })

  it.each([
    ['initial', 'This is the first source checkpoint.'],
    ['limited', 'Some source comparisons are limited.'],
  ] as const)('shows the %s comparison result and period by default', (outcome, summary) => {
    const session = completedDemoSession()
    session.configuration.profile = { id: 'catch_up', label: 'Catch Up', purpose: 'Changes since you last checked.', definition_version: 1 }
    session.artifact!.comparison = {
      outcome, summary, material_change_count: 0, no_material_changes: true,
      sources: [{
        source: 'calendar', status: outcome === 'initial' ? 'initial' : 'limited',
        baseline_session_id: null, baseline_snapshot_at: null,
        current_snapshot_at: '2026-09-25T13:00:00Z', reason: outcome === 'limited' ? 'source_unavailable' : null,
      }],
    }
    renderMessage(session)

    const banner = screen.getByRole('region', { name: 'Catch Up comparison' })
    expect(banner).toHaveTextContent(summary)
    expect(banner).toHaveTextContent('current snapshot')
  })

  it('labels synthesis inclusion separately from artifact citation', async () => {
    const session = completedDemoSession()
    session.evidence_ids = ['evidence-1', 'evidence-2']
    const evidence = (sourceId: string, included: boolean) => ({
      id: sourceId, source: 'calendar', source_id: sourceId,
      identity_kind: 'provider' as const, revision: null, revision_kind: 'none' as const,
      observed_at: '2026-09-25T13:00:00Z', effective_at: null, trust: 'observed' as const,
      content: 'Saved source content.', record_reference: null,
      included_in_synthesis: included, available: true, unavailable_reason: null,
    })
    render(<BriefingArtifactMessage
      session={session}
      isLoadingSession={false}
      evidence={{
        evidenceById: { 'evidence-1': evidence('event-1', true), 'evidence-2': evidence('event-2', true) },
        loadingIds: [], errors: {}, onLoadEvidence: vi.fn(async () => {}),
      }}
      onMarkPresented={vi.fn(async () => {})}
    />)

    await userEvent.click(screen.getByText('Evidence (1)'))
    expect(screen.getByText('sent to synthesis · cited in briefing')).toBeInTheDocument()
    await userEvent.click(screen.getByText(/Other captured evidence \(1\)/))
    expect(screen.getByText('sent to synthesis · not cited in briefing')).toBeInTheDocument()
  })

  it('attributes untrusted Deep read evidence without calling it an external report', async () => {
    const session = completedDemoSession()
    session.configuration.profile = { id: 'deep', label: 'Deep', purpose: 'An evidence-backed investigation.', definition_version: 1 }
    session.evidence_ids = ['tool-evidence']
    const toolEvidence = {
      id: 'tool-evidence', source: 'get_active_reminders', source_id: 'read-1',
      identity_kind: 'provider' as const, revision: null, revision_kind: 'none' as const,
      observed_at: '2026-09-25T13:00:00Z', effective_at: null, trust: 'untrusted' as const,
      content: 'A bounded reminder result.', record_reference: null,
      included_in_synthesis: true, available: true, unavailable_reason: null,
    }
    render(<BriefingArtifactMessage
      session={session}
      isLoadingSession={false}
      evidence={{ evidenceById: { 'tool-evidence': toolEvidence }, loadingIds: [], errors: {}, onLoadEvidence: vi.fn(async () => {}) }}
      onMarkPresented={vi.fn(async () => {})}
    />)

    await userEvent.click(screen.getByText('Evidence (1)'))
    expect(screen.getByText('Untrusted read result · get active reminders')).toBeInTheDocument()
    expect(screen.getByText(/Read result from get active reminders is attributed and untrusted/)).toBeInTheDocument()
    expect(screen.queryByText('Untrusted external report')).not.toBeInTheDocument()
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
