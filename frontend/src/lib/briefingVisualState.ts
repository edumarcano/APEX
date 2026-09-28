import type { BriefingSessionDetail, BriefingSessionSummary, BriefingStage } from '../types/briefings'
import type { ModelCatalogEntry } from '../types/telemetry'

export type BriefingVisualStatus = 'idle' | 'loading' | 'success' | 'error'
export type BriefingVisualActivity = BriefingStage | 'briefing_ready'

export function resolveBriefingLogoActivity({
  activeRun,
  activeActivity,
  selectedActivity,
  isPreparingSpeech,
  isSpeaking,
}: {
  activeRun: boolean
  activeActivity: BriefingVisualActivity | null
  selectedActivity: BriefingVisualActivity | null
  isPreparingSpeech: boolean
  isSpeaking: boolean
}): BriefingVisualActivity | 'speech_preparing' | 'speech_playing' | null {
  if (isPreparingSpeech) return 'speech_preparing'
  if (isSpeaking) return 'speech_playing'
  if (activeRun) return activeActivity ?? 'preparing'
  return selectedActivity
}

export function resolveBriefingVisualState(session: BriefingSessionDetail | null): {
  status: BriefingVisualStatus
  step: number | null
  activity: BriefingVisualActivity | null
} {
  const status: BriefingVisualStatus =
    session?.run_status === 'queued' || session?.run_status === 'running' || session?.run_status === 'cancelling'
      ? 'loading'
      : session?.run_status === 'completed'
        ? 'success'
        : session?.run_status === 'failed'
          ? 'error'
          : 'idle'
  const stage = session?.active_stage?.stage
  const activity: BriefingVisualActivity | null = status === 'loading'
    ? stage ?? 'preparing'
    : status === 'success'
      ? 'briefing_ready'
      : null
  const step = stage === 'preparing'
    ? 1
    : stage === 'collecting'
      ? 2
      : stage === 'selecting' || stage === 'investigating' || stage === 'synthesizing'
        ? 3
        : stage === 'persisting'
          ? 4
          : null
  return { status, step, activity }
}

export function resolveActiveBriefingActivity({
  sessions,
  selectedSessionId,
  selectedSession,
  modelCatalog,
}: {
  sessions: BriefingSessionSummary[]
  selectedSessionId: string | null
  selectedSession: BriefingSessionDetail | null
  modelCatalog: ModelCatalogEntry[]
}): {
  session: BriefingSessionSummary | null
  isRunning: boolean
  isLocalModelRunning: boolean
  modelId: string | null
  displayName: string | null
} {
  const session = sessions.find((candidate) =>
    candidate.run_status === 'queued' ||
    candidate.run_status === 'running' ||
    candidate.run_status === 'cancelling'
  ) ?? null
  if (!session) {
    return { session: null, isRunning: false, isLocalModelRunning: false, modelId: null, displayName: null }
  }

  const catalogEntry = modelCatalog.find((entry) => entry.model_id === session.model_id)
  const selectedModel =
    selectedSessionId === session.id && selectedSession?.id === session.id
      ? selectedSession.configuration.model
      : null
  const isLocalModelRunning = (catalogEntry?.runtime ?? selectedModel?.runtime) === 'local'
  if (!isLocalModelRunning) {
    return { session, isRunning: true, isLocalModelRunning: false, modelId: null, displayName: null }
  }
  return {
    session,
    isRunning: true,
    isLocalModelRunning: true,
    modelId: session.model_id,
    displayName: catalogEntry?.display_name ?? selectedModel?.model_id ?? session.model_id,
  }
}
