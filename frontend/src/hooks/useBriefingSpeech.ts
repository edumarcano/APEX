import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { BriefingSpeechEngine, BriefingSpeechState, BriefingSpeechStatus } from '../types/briefings'
import type { VoiceMode } from '../types/settings'

export type BriefingSpeechAction = 'prepare' | 'play' | 'stop'

export type UseBriefingSpeechResult = {
  speech: BriefingSpeechState | null
  isLoading: boolean
  pendingAction: BriefingSpeechAction | null
  error: string | null
  playbackCompleted: boolean
  voiceEnabled: boolean
  refresh: () => Promise<void>
  prepare: () => Promise<void>
  recreateAudio: () => Promise<void>
  play: () => Promise<void>
  stop: () => Promise<void>
}

type InFlightSpeechAction = {
  action: BriefingSpeechAction
  sessionId: string
  epoch: number
  controller: AbortController
}

const SPEECH_STATUSES = new Set<BriefingSpeechStatus>([
  'not_requested', 'preparing', 'ready', 'unavailable', 'cancelled', 'playing', 'stopping',
])
const ACTIVE_STATUSES = new Set<BriefingSpeechStatus>(['preparing', 'playing', 'stopping'])
const POLL_INTERVAL_MS = 900
const SPEECH_ENGINES = new Set<BriefingSpeechEngine>(['google', 'kokoro', 'pyttsx3'])

function isBriefingSpeechState(value: unknown, sessionId: string): value is BriefingSpeechState {
  if (!value || typeof value !== 'object') return false
  const body = value as Record<string, unknown>
  return body.session_id === sessionId &&
    typeof body.artifact_sha256 === 'string' &&
    typeof body.status === 'string' && SPEECH_STATUSES.has(body.status as BriefingSpeechStatus) &&
    (body.error_code === null || typeof body.error_code === 'string') &&
    (body.engine === null || (typeof body.engine === 'string' && SPEECH_ENGINES.has(body.engine as BriefingSpeechEngine)))
}

async function readResponse(response: Response, fallback: string): Promise<unknown> {
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body && typeof body === 'object' && 'detail' in body
      ? (body as { detail?: unknown }).detail
      : null
    throw new Error(typeof detail === 'string' ? detail : `${fallback} (${response.status})`)
  }
  return body
}

function responseError(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

/** Loads and manages speech derived from one selected, completed briefing. */
export function useBriefingSpeech(
  sessionId: string | null,
  voiceMode: VoiceMode,
): UseBriefingSpeechResult {
  const [speechState, setSpeechState] = useState<BriefingSpeechState | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [pendingAction, setPendingAction] = useState<BriefingSpeechAction | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [playbackCompletedFor, setPlaybackCompletedFor] = useState<string | null>(null)
  const speechRef = useRef<BriefingSpeechState | null>(null)
  const epochRef = useRef(0)
  const readSequenceRef = useRef(0)
  const actionSequenceRef = useRef(0)
  const pendingActionRef = useRef<BriefingSpeechAction | null>(null)
  const pollControllerRef = useRef<AbortController | null>(null)
  const actionContextRef = useRef<InFlightSpeechAction | null>(null)
  const pollTimerRef = useRef<number | null>(null)
  const readRef = useRef<() => Promise<void>>(async () => undefined)
  const voiceOffStopForRef = useRef<string | null>(null)
  const contextRef = useRef({ sessionId, voiceMode })
  const stopRequestedForRef = useRef<string | null>(null)

  const currentSpeech = sessionId && speechState?.session_id === sessionId ? speechState : null

  useLayoutEffect(() => {
    contextRef.current = { sessionId, voiceMode }
  }, [sessionId, voiceMode])

  const requestSessionStop = useCallback((targetSessionId: string, force = false): void => {
    if (!force && stopRequestedForRef.current === targetSessionId) return
    stopRequestedForRef.current = targetSessionId
    void fetch(API_ENDPOINTS.briefingSessionSpeechStop(targetSessionId), { method: 'POST' })
      .catch(() => {
        if (stopRequestedForRef.current === targetSessionId) stopRequestedForRef.current = null
      })
  }, [])

  useEffect(() => {
    const epoch = ++epochRef.current
    const sessionAtStart = sessionId
    const voiceModeAtStart = voiceMode
    let disposed = false
    const current = (): boolean => !disposed && epochRef.current === epoch
    const clearPoll = (): void => {
      if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
    const schedulePoll = (delay = POLL_INTERVAL_MS): void => {
      clearPoll()
      if (!sessionId) return
      pollTimerRef.current = window.setTimeout(() => { void read() }, delay)
    }
    const applyState = (next: BriefingSpeechState): void => {
      const previous = speechRef.current
      if (previous?.session_id === next.session_id && previous.status === 'playing' && next.status === 'ready') {
        setPlaybackCompletedFor(next.error_code === null ? next.session_id : null)
      } else if (next.status === 'playing' || (next.status === 'ready' && next.error_code !== null)) {
        setPlaybackCompletedFor(null)
      }
      speechRef.current = next
      setSpeechState(next)
    }
  const read = async (): Promise<void> => {
      if (!sessionId || !current()) return
      clearPoll()
      pollControllerRef.current?.abort()
      const controller = new AbortController()
      pollControllerRef.current = controller
      const sequence = ++readSequenceRef.current
      try {
        const response = await fetch(API_ENDPOINTS.briefingSessionSpeech(sessionId), { signal: controller.signal })
        const body = await readResponse(response, 'Spoken highlights could not be loaded')
        if (!isBriefingSpeechState(body, sessionId)) throw new Error('Spoken highlights returned an invalid status.')
        if (!current() || sequence !== readSequenceRef.current) return
        applyState(body)
        setError(null)
        setIsLoading(false)
        if (ACTIVE_STATUSES.has(body.status)) schedulePoll()
      } catch (cause) {
        if (!current() || controller.signal.aborted || sequence !== readSequenceRef.current) return
        setError(responseError(cause, 'Spoken highlights could not be loaded.'))
        setIsLoading(false)
        if (speechRef.current?.session_id === sessionId && ACTIVE_STATUSES.has(speechRef.current.status)) {
          schedulePoll(POLL_INTERVAL_MS * 2)
        }
      } finally {
        if (pollControllerRef.current === controller) pollControllerRef.current = null
      }
    }
    readRef.current = read

    if (!sessionId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- A missing selected session must clear a prior loading state.
      setIsLoading(false)
      setPendingAction(null)
      pendingActionRef.current = null
      setError(null)
      return () => {
        disposed = true
        clearPoll()
        pollControllerRef.current?.abort()
        readSequenceRef.current += 1
        actionSequenceRef.current += 1
      }
    }

    setIsLoading(true)
    setError(null)
    setPendingAction(null)
    pendingActionRef.current = null
    actionSequenceRef.current += 1
    void read()

    return () => {
      const nextContext = contextRef.current
      const previousSpeech = speechRef.current
      const leavingSession = nextContext.sessionId !== sessionAtStart
      const disablingVoice = voiceModeAtStart !== 'off' && nextContext.voiceMode === 'off'
      const action = actionContextRef.current
      const ownsCurrentEpoch = action?.epoch === epoch && action.sessionId === sessionAtStart
      const pendingAdmission = ownsCurrentEpoch && (action.action === 'prepare' || action.action === 'play')
      if (sessionAtStart && (leavingSession || disablingVoice) && previousSpeech?.session_id === sessionAtStart &&
        (previousSpeech.status === 'preparing' || previousSpeech.status === 'playing')) {
        requestSessionStop(sessionAtStart)
      }
      const voiceModeChanged = nextContext.voiceMode !== voiceModeAtStart
      if (sessionAtStart && pendingAdmission && (leavingSession || voiceModeChanged)) requestSessionStop(sessionAtStart)
      if (ownsCurrentEpoch && !pendingAdmission) action.controller.abort()
      disposed = true
      clearPoll()
      pollControllerRef.current?.abort()
      readSequenceRef.current += 1
      actionSequenceRef.current += 1
    }
  }, [requestSessionStop, sessionId, voiceMode])

  const refresh = useCallback(async (): Promise<void> => {
    if (!sessionId) return
    setIsLoading(true)
    setError(null)
    await readRef.current()
  }, [sessionId])

  const runAction = useCallback(async (action: BriefingSpeechAction, forcePrepare = false): Promise<void> => {
    if (!sessionId || !currentSpeech || pendingActionRef.current) return
    if (action !== 'stop' && voiceMode === 'off') return
    if (action === 'prepare' && !['not_requested', 'unavailable', 'cancelled', 'ready'].includes(currentSpeech.status)) return
    if (action === 'play' && currentSpeech.status !== 'ready') return
    if (action === 'stop' && !ACTIVE_STATUSES.has(currentSpeech.status)) return

    if (action === 'prepare' || action === 'play') {
      stopRequestedForRef.current = null
      setPlaybackCompletedFor(null)
    }
    if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current)
    pollTimerRef.current = null
    pollControllerRef.current?.abort()
    readSequenceRef.current += 1
    const epoch = epochRef.current
    const sequence = ++actionSequenceRef.current
    const controller = new AbortController()
    const actionContext: InFlightSpeechAction = { action, sessionId, epoch, controller }
    actionContextRef.current = actionContext
    pendingActionRef.current = action
    setPendingAction(action)
    setError(null)

    const endpoint = action === 'prepare'
      ? API_ENDPOINTS.briefingSessionSpeechPrepare(sessionId, forcePrepare)
      : action === 'play'
        ? API_ENDPOINTS.briefingSessionSpeechPlay(sessionId)
        : API_ENDPOINTS.briefingSessionSpeechStop(sessionId)
    try {
      const response = await fetch(endpoint, { method: 'POST', signal: controller.signal })
      const isStale = (): boolean => epoch !== epochRef.current || sequence !== actionSequenceRef.current || controller.signal.aborted
      const admission = action === 'prepare' || action === 'play'
      const stale = isStale()
      if (stale) {
        if (response.ok && admission) requestSessionStop(sessionId, true)
        return
      }
      const body = await readResponse(response, `Spoken highlights ${action} failed`)
      if (isStale()) {
        if (response.ok && admission) requestSessionStop(sessionId, true)
        return
      }
      if (!isBriefingSpeechState(body, sessionId)) throw new Error('Spoken highlights returned an invalid status.')
      const previous = speechRef.current
      if (previous?.session_id === body.session_id && previous.status === 'playing' && body.status === 'ready') {
        setPlaybackCompletedFor(body.error_code === null ? body.session_id : null)
      } else if (action === 'play' && body.status === 'ready') {
        setPlaybackCompletedFor(body.error_code === null ? body.session_id : null)
      } else if (action === 'play') {
        setPlaybackCompletedFor(null)
      }
      speechRef.current = body
      setSpeechState(body)
      if (!ACTIVE_STATUSES.has(body.status) && stopRequestedForRef.current === sessionId) {
        stopRequestedForRef.current = null
      }
      setError(null)
      if (ACTIVE_STATUSES.has(body.status)) {
        pollTimerRef.current = window.setTimeout(() => { void readRef.current() }, POLL_INTERVAL_MS)
      }
    } catch (cause) {
      if (epoch !== epochRef.current || sequence !== actionSequenceRef.current || controller.signal.aborted) return
      setError(responseError(cause, `Spoken highlights ${action} failed.`))
    } finally {
      if (epoch === epochRef.current && sequence === actionSequenceRef.current) {
        pendingActionRef.current = null
        setPendingAction(null)
      }
      if (actionContextRef.current === actionContext) actionContextRef.current = null
    }
  }, [currentSpeech, requestSessionStop, sessionId, voiceMode])

  useEffect(() => {
    if (voiceMode !== 'off') {
      voiceOffStopForRef.current = null
      stopRequestedForRef.current = null
      return
    }
    if (!sessionId || !currentSpeech || !['preparing', 'playing'].includes(currentSpeech.status)) return
    if (voiceOffStopForRef.current === sessionId) return
    voiceOffStopForRef.current = sessionId
    requestSessionStop(sessionId)
  }, [currentSpeech, requestSessionStop, sessionId, voiceMode])

  return {
    speech: currentSpeech,
    isLoading,
    pendingAction,
    error,
    playbackCompleted: playbackCompletedFor === sessionId,
    voiceEnabled: voiceMode !== 'off',
    refresh,
    prepare: () => runAction('prepare'),
    recreateAudio: () => runAction('prepare', true),
    play: () => runAction('play'),
    stop: () => runAction('stop'),
  }
}
