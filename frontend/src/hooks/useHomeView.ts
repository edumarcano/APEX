import { useCallback, useState } from 'react'

import type { BriefingProfileId, BriefingSessionDetail, BriefingSessionSummary } from '../types/briefings'

export type HomeView = 'standby' | 'overview' | 'briefing'
export type HomeActiveView = Exclude<HomeView, 'standby'>
export type BriefingLayoutPhase = 'identity' | 'generating' | 'workspace'

const RUNNING_STATUSES = new Set(['queued', 'running', 'cancelling'])

export function resolveBriefingLayoutPhase({
  session,
  selectedSession,
  isGenerating,
}: {
  session: BriefingSessionDetail | null
  selectedSession: BriefingSessionSummary | null
  isGenerating: boolean
}): BriefingLayoutPhase {
  if (isGenerating) return 'generating'
  if (!session || session.id !== selectedSession?.id) {
    return selectedSession && RUNNING_STATUSES.has(selectedSession.run_status) ? 'generating' : 'identity'
  }
  if (RUNNING_STATUSES.has(session.run_status)) return 'generating'
  if (session.run_status === 'completed' && session.artifact) return 'workspace'
  return 'identity'
}

export type UseHomeViewOptions = {
  activated: boolean
  deactivate: () => void
}

export type UseHomeViewResult = {
  view: HomeView
  /** The view Home returns to once activated. */
  activeView: HomeActiveView
  profileId: BriefingProfileId
  selectView: (view: HomeActiveView) => void
  returnToStandby: () => void
  setProfileId: (profileId: BriefingProfileId) => void
}

/**
 * Owns in-memory Home navigation. Transitions only change presentation: they
 * never generate, speak, or collect, and returning to Standby keeps cached
 * telemetry and briefing sessions.
 */
export function useHomeView({ activated, deactivate }: UseHomeViewOptions): UseHomeViewResult {
  const [activeView, setActiveView] = useState<HomeActiveView>('overview')
  const [profileId, setProfileId] = useState<BriefingProfileId>('daily')
  const selectView = useCallback((view: HomeActiveView): void => setActiveView(view), [])
  const returnToStandby = useCallback((): void => deactivate(), [deactivate])
  return {
    view: activated ? activeView : 'standby',
    activeView,
    profileId,
    selectView,
    returnToStandby,
    setProfileId,
  }
}
