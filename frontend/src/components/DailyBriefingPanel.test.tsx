import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { BriefingSessionDetail } from '../types/briefings'
import { DailyBriefingPanel } from './DailyBriefingPanel'

const sessionId = '00000000-0000-4000-8000-000000000001'

function completedDemoSession(itemCount: number): BriefingSessionDetail {
  return {
    id: sessionId,
    conversation_id: '00000000-0000-4000-8000-000000000002',
    opening_message_id: '00000000-0000-4000-8000-000000000003',
    run_id: '00000000-0000-4000-8000-000000000004',
    run_status: 'completed',
    run_error_code: null,
    configuration: {
      profile: { id: 'daily', label: 'Daily', purpose: 'A concise view of current information.', definition_version: 2 },
      model: { model_id: 'demo/daily-fixture', provider: 'demo', runtime: 'demo', reasoning: null, context_window: null, local_reasoning_mode: null },
      origin: 'hud',
      execution_kind: 'demo',
    },
    artifact: {
      schema_version: 1,
      session_id: sessionId,
      created_at: '2026-09-25T13:00:00Z',
      sections: [{
        id: 'section-1',
        title: 'Today',
        items: Array.from({ length: itemCount }, (_, index) => ({
          id: `item-${index}`,
          category: 'observation',
          title: `Briefing item ${index}`,
          body: 'A saved briefing item with a short summary.',
          evidence_ids: [],
          record_references: [],
        })),
      }],
      coverage: [],
      limitations: [],
    },
    evidence_count: 0,
    evidence_ids: [],
    created_at: '2026-09-25T13:00:00Z',
    presented_at: null,
    speech_status: 'not_requested',
  }
}

class FakeIntersectionObserver {
  static latest: FakeIntersectionObserver | null = null
  target: Element | null = null
  private readonly callback: IntersectionObserverCallback

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    FakeIntersectionObserver.latest = this
  }

  observe(target: Element): void {
    this.target = target
  }

  disconnect(): void {}
  unobserve(): void {}
  takeRecords(): IntersectionObserverEntry[] { return [] }

  trigger(isIntersecting: boolean, intersectionRatio: number): void {
    if (!this.target) throw new Error('No target was observed.')
    const rect = this.target.getBoundingClientRect()
    this.callback([{
      target: this.target,
      isIntersecting,
      intersectionRatio,
      boundingClientRect: rect,
      intersectionRect: rect,
      rootBounds: null,
      time: 0,
    }], this as unknown as IntersectionObserver)
  }
}

function renderPanel(onMarkPresented: (id: string) => Promise<void>, session = completedDemoSession(32)) {
  return render(
    <DailyBriefingPanel
      sessions={[{
        id: sessionId,
        profile_id: 'daily',
        model_id: 'demo/daily-fixture',
        conversation_id: '00000000-0000-4000-8000-000000000002',
        run_id: '00000000-0000-4000-8000-000000000004',
        run_status: 'completed',
        created_at: '2026-09-25T13:00:00Z',
        presented_at: null,
      }]}
      selectedSessionId={sessionId}
      session={session}
      evidenceById={{}}
      evidenceLoadingIds={[]}
      evidenceErrors={{}}
      isLoadingSessions={false}
      isLoadingSession={false}
      isGenerating={false}
      hasActiveSession={false}
      conversationReady={false}
      canGenerateDaily={true}
      canFollowUp={false}
      error={null}
      onGenerateDaily={vi.fn()}
      onOpenSession={vi.fn()}
      onOpenConversation={vi.fn()}
      onLoadEvidence={vi.fn(async () => {})}
      onCancel={vi.fn()}
      onMarkPresented={onMarkPresented}
      onClose={vi.fn()}
    />,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  FakeIntersectionObserver.latest = null
})

describe('DailyBriefingPanel', () => {
  it('explains a classified model-output failure and how to retry', () => {
    const session = completedDemoSession(0)
    session.run_status = 'failed'
    session.run_error_code = 'invalid_model_output'
    session.artifact = null
    renderPanel(vi.fn(async () => {}), session)

    expect(screen.getByText(/did not pass Daily validation after one repair attempt/)).toBeInTheDocument()
    expect(screen.getByText(/Start a new Daily run to try again/)).toBeInTheDocument()
  })

  it('shows pending and untrusted status before evidence is fetched', () => {
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver as unknown as typeof IntersectionObserver)
    const session = completedDemoSession(2)
    const items = session.artifact?.sections[0]?.items
    if (!items) throw new Error('Missing fixture items')
    items[0].category = 'analysis'
    items[0].record_references = [{ kind: 'external_activity', id: 'report-1' }]
    items[1].category = 'suggestion'
    items[1].record_references = [{ kind: 'context_review', id: 'review-1' }]
    renderPanel(vi.fn(async () => {}), session)

    expect(screen.getByText('Includes an attributed, untrusted external report.')).toBeInTheDocument()
    expect(screen.getByText('Includes a pending review that has not been accepted into personal context.')).toBeInTheDocument()
  })

  it('shows an explicit DEMO fixture marker', () => {
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver as unknown as typeof IntersectionObserver)
    renderPanel(vi.fn(async () => {}))

    expect(screen.getByText('Deterministic demo fixture')).toBeInTheDocument()
    expect(screen.getByText(/DEMO fixture\. No model was run/)).toBeInTheDocument()
  })

  it('acknowledges a visible sentinel even when the full artifact is tall', async () => {
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver as unknown as typeof IntersectionObserver)
    const markPresented = vi.fn(async () => {})
    renderPanel(markPresented)

    await waitFor(() => expect(FakeIntersectionObserver.latest?.target).not.toBeNull())
    const artifact = screen.getByTestId('daily-artifact')
    expect(artifact.querySelector('h4')).toBeInTheDocument()
    expect(FakeIntersectionObserver.latest?.target).not.toBe(artifact)
    FakeIntersectionObserver.latest?.trigger(true, 0.5)

    await waitFor(() => expect(markPresented).toHaveBeenCalledWith(sessionId))
  })

  it('does not acknowledge an artifact sentinel while it is offscreen', async () => {
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver as unknown as typeof IntersectionObserver)
    const markPresented = vi.fn(async () => {})
    renderPanel(markPresented)

    await waitFor(() => expect(FakeIntersectionObserver.latest?.target).not.toBeNull())
    FakeIntersectionObserver.latest?.trigger(false, 0)
    expect(markPresented).not.toHaveBeenCalled()
  })
})
