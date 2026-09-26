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
  /** The Home peer workspace chosen in the header menu. */
  destination: HomeActiveView
}

export type UseHomeViewResult = {
  view: HomeView
  profileId: BriefingProfileId
  returnToStandby: () => void
  setProfileId: (profileId: BriefingProfileId) => void
}

/**
 * Resolves the Home presentation and owns the selected briefing profile.
 * Standby covers the chosen Home destination until activation; transitions
 * never generate, speak, or collect, and returning to Standby keeps cached
 * telemetry and briefing sessions.
 */
export function useHomeView({ activated, deactivate, destination }: UseHomeViewOptions): UseHomeViewResult {
  const [profileId, setProfileId] = useState<BriefingProfileId>('daily')
  const returnToStandby = useCallback((): void => deactivate(), [deactivate])
  return {
    view: activated ? destination : 'standby',
    profileId,
    returnToStandby,
    setProfileId,
  }
}
