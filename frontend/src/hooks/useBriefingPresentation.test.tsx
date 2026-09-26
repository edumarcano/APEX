import { render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { BriefingSessionDetail } from '../types/briefings'
import { useBriefingPresentation } from './useBriefingPresentation'

const sessionId = '00000000-0000-4000-8000-000000000001'

function completedSession(overrides: Partial<BriefingSessionDetail> = {}): BriefingSessionDetail {
  return {
    id: sessionId,
    conversation_id: '00000000-0000-4000-8000-000000000002',
    opening_message_id: '00000000-0000-4000-8000-000000000003',
    run_id: '00000000-0000-4000-8000-000000000004',
    run_status: 'completed',
    run_error_code: null,
    configuration: {
      profile: { id: 'daily', label: 'Daily', purpose: 'Current information.', definition_version: 2 },
      model: { model_id: 'demo/daily-fixture', provider: 'demo', runtime: 'demo', reasoning: null, context_window: null, local_reasoning_mode: null },
      origin: 'hud',
      execution_kind: 'demo',
    },
    artifact: { schema_version: 1, session_id: sessionId, created_at: '2026-09-25T13:00:00Z', sections: [], coverage: [], limitations: [] },
    evidence_count: 0,
    evidence_ids: [],
    created_at: '2026-09-25T13:00:00Z',
    presented_at: null,
    speech_status: 'not_requested',
    ...overrides,
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

function Sentinel({ session, onMarkPresented }: { session: BriefingSessionDetail; onMarkPresented: (id: string) => Promise<void> }) {
  const ref = useBriefingPresentation({ session, isLoadingSession: false, onMarkPresented })
  return <div ref={ref}>Sentinel</div>
}

function setVisibility(state: DocumentVisibilityState): void {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
}

afterEach(() => {
  vi.unstubAllGlobals()
  FakeIntersectionObserver.latest = null
  setVisibility('visible')
})

describe('useBriefingPresentation', () => {
  it('marks a visible completed session once', async () => {
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver as unknown as typeof IntersectionObserver)
    const markPresented = vi.fn(async () => {})
    render(<Sentinel session={completedSession()} onMarkPresented={markPresented} />)

    await waitFor(() => expect(FakeIntersectionObserver.latest?.target).not.toBeNull())
    FakeIntersectionObserver.latest?.trigger(true, 0.5)
    FakeIntersectionObserver.latest?.trigger(true, 1)

    await waitFor(() => expect(markPresented).toHaveBeenCalledWith(sessionId))
    expect(markPresented).toHaveBeenCalledTimes(1)
  })

  it('does not mark while the sentinel is offscreen or under half visible', async () => {
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver as unknown as typeof IntersectionObserver)
    const markPresented = vi.fn(async () => {})
    render(<Sentinel session={completedSession()} onMarkPresented={markPresented} />)

    await waitFor(() => expect(FakeIntersectionObserver.latest?.target).not.toBeNull())
    FakeIntersectionObserver.latest?.trigger(false, 0)
    FakeIntersectionObserver.latest?.trigger(true, 0.4)
    expect(markPresented).not.toHaveBeenCalled()
  })

  it('waits for a hidden tab to become visible', async () => {
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver as unknown as typeof IntersectionObserver)
    const markPresented = vi.fn(async () => {})
    setVisibility('hidden')
    render(<Sentinel session={completedSession()} onMarkPresented={markPresented} />)

    await waitFor(() => expect(FakeIntersectionObserver.latest?.target).not.toBeNull())
    FakeIntersectionObserver.latest?.trigger(true, 1)
    expect(markPresented).not.toHaveBeenCalled()

    setVisibility('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await waitFor(() => expect(markPresented).toHaveBeenCalledTimes(1))
  })

  it('retries after a failed presentation write', async () => {
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver as unknown as typeof IntersectionObserver)
    const markPresented = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue(undefined)
    render(<Sentinel session={completedSession()} onMarkPresented={markPresented} />)

    await waitFor(() => expect(FakeIntersectionObserver.latest?.target).not.toBeNull())
    FakeIntersectionObserver.latest?.trigger(true, 1)
    await waitFor(() => expect(markPresented).toHaveBeenCalledTimes(1))
    await Promise.resolve()
    FakeIntersectionObserver.latest?.trigger(true, 1)
    await waitFor(() => expect(markPresented).toHaveBeenCalledTimes(2))
  })

  it('ignores sessions that are already presented or not completed', async () => {
    vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver as unknown as typeof IntersectionObserver)
    const markPresented = vi.fn(async () => {})
    const { rerender } = render(<Sentinel session={completedSession({ presented_at: '2026-09-25T13:02:00Z' })} onMarkPresented={markPresented} />)
    expect(FakeIntersectionObserver.latest).toBeNull()

    rerender(<Sentinel session={completedSession({ run_status: 'running', artifact: null })} onMarkPresented={markPresented} />)
    expect(FakeIntersectionObserver.latest).toBeNull()
    expect(markPresented).not.toHaveBeenCalled()
  })
})
