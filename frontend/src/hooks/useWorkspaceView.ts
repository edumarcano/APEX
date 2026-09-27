import { useCallback, useState } from 'react'

import type { BriefingProfileId, BriefingSessionDetail, BriefingSessionSummary } from '../types/briefings'

export type WorkspacePresentationView = 'standby' | 'overview' | 'briefing'
export type WorkspaceHudDestination = Exclude<WorkspacePresentationView, 'standby'>
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

export type UseWorkspaceViewOptions = {
  activated: boolean
  deactivate: () => void
  /** Overview or Briefing peer chosen in the header tabs. */
  destination: WorkspaceHudDestination
}

export type UseWorkspaceViewResult = {
  view: WorkspacePresentationView
  profileId: BriefingProfileId
  returnToStandby: () => void
  setProfileId: (profileId: BriefingProfileId) => void
}

/**
 * Resolves Overview/Briefing presentation and owns the selected briefing profile.
 * Standby is Overview-only until activation; Briefing renders without activation.
 */
export function useWorkspaceView({ activated, deactivate, destination }: UseWorkspaceViewOptions): UseWorkspaceViewResult {
  const [profileId, setProfileId] = useState<BriefingProfileId>('daily')
  const returnToStandby = useCallback((): void => deactivate(), [deactivate])
  const view: WorkspacePresentationView =
    !activated && destination === 'overview' ? 'standby' : destination
  return {
    view,
    profileId,
    returnToStandby,
    setProfileId,
  }
}
