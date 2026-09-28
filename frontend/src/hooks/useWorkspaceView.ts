import { useState } from 'react'

import type { BriefingProfileId, BriefingSessionDetail, BriefingSessionSummary } from '../types/briefings'

export type WorkspacePresentationView = 'overview' | 'briefing'
export type WorkspaceHudDestination = WorkspacePresentationView
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
  /** Overview or Briefing peer chosen in workspace navigation. */
  destination: WorkspaceHudDestination
}

export type UseWorkspaceViewResult = {
  view: WorkspacePresentationView
  profileId: BriefingProfileId
  setProfileId: (profileId: BriefingProfileId) => void
}

/**
 * Resolves the selected Overview/Briefing presentation and owns the briefing profile.
 * Collection admission belongs to the explicit Overview action, not navigation.
 */
export function useWorkspaceView({ destination }: UseWorkspaceViewOptions): UseWorkspaceViewResult {
  const [profileId, setProfileId] = useState<BriefingProfileId>('daily')
  const view: WorkspacePresentationView = destination
  return {
    view,
    profileId,
    setProfileId,
  }
}
