import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { ApexDataState, AgentInitialSelection, CloudEffort } from '../types/telemetry'
import { API_ENDPOINTS } from '../lib/api'
import { isAgentKey } from '../lib/agents'

const REMINDERS_ENDPOINT = API_ENDPOINTS.reminders
const REMINDERS_COMPLETE_ENDPOINT = API_ENDPOINTS.remindersComplete
const CONFIG_ENDPOINT = API_ENDPOINTS.config

export type { ApexDataState } from '../types/telemetry'

export type UseApexDataReturn = ApexDataState & {
  refreshReminders: () => Promise<void>
  createReminder: (text: string) => Promise<'synced' | 'pending' | 'unknown'>
  markReminderAsRead: (id: string) => Promise<void>
  getReminderTask: (id: string) => Promise<ReminderTaskDetail>
  listCompletedReminders: () => Promise<CompletedRemindersResult>
  updateReminderTask: (request: ReminderTaskUpdateRequest) => Promise<ReminderTaskMutationResult>
  deleteReminderTask: (request: ReminderTaskTargetRequest) => Promise<ReminderTaskMutationResult>
  reopenReminderTask: (request: ReminderTaskTargetRequest) => Promise<ReminderTaskMutationResult>
  syncReminders: (ids: string[]) => Promise<Array<{ id: string; outcome: string }>>
  dismissUnknownReminder: (id: string) => Promise<void>
  applyBootSettings: (next: {
    agentQueriesEnabled: boolean
    agentInitialSelection: AgentInitialSelection
    marketEnabled: boolean
  }) => void
}

type ReminderRecord = {
  id: string
  note: string
  source: 'todo' | 'local'
  sync_state: 'synced' | 'pending' | 'unknown'
}

type ReminderEnvelope = {
  items: ReminderRecord[]
  source_state: 'live' | 'stale' | 'unavailable'
  cache_timestamp: string | null
  pending_sync_count: number
}

export type ReminderTaskDue = {
  date_time: string
  time_zone: string
}

export type ReminderTaskDetail = {
  id: string
  title: string
  due: ReminderTaskDue | null
  importance: 'low' | 'normal' | 'high'
  is_completed: boolean
  completed_at: ReminderTaskDue | null
  last_modified_at: string
}

export type CompletedRemindersResult = {
  items: ReminderTaskDetail[]
  source_state: 'live' | 'unavailable'
}

export type ReminderTaskUpdateRequest = {
  id: string
  last_modified_at: string
  title?: string
  due?: ReminderTaskDue | null
  importance?: 'low' | 'normal' | 'high'
}

export type ReminderTaskTargetRequest = {
  id: string
  last_modified_at: string
}

export type ReminderTaskMutationResult = {
  id: string
  outcome: 'synced' | 'unknown'
  action_id: string
}

function parseReminderEnvelope(body: unknown): ReminderEnvelope | null {
  if (!body || typeof body !== 'object') {
    return null
  }
  const envelope = body as Record<string, unknown>
  if (!Array.isArray(envelope.items) || !['live', 'stale', 'unavailable'].includes(String(envelope.source_state))) return null
  if (envelope.cache_timestamp !== null && typeof envelope.cache_timestamp !== 'string') return null
  if (typeof envelope.pending_sync_count !== 'number') return null

  const records: ReminderRecord[] = []
  for (const entry of envelope.items) {
    if (!entry || typeof entry !== 'object') continue
    const row = entry as { id?: unknown; note?: unknown; source?: unknown; sync_state?: unknown }
    if (
      typeof row.id !== 'string' || typeof row.note !== 'string' ||
      (row.source !== 'todo' && row.source !== 'local') ||
      !['synced', 'pending', 'unknown'].includes(String(row.sync_state))
    ) continue
    records.push({ id: row.id, note: row.note, source: row.source as ReminderRecord['source'], sync_state: row.sync_state as ReminderRecord['sync_state'] })
  }
  return {
    items: records,
    source_state: envelope.source_state as ReminderEnvelope['source_state'],
    cache_timestamp: envelope.cache_timestamp as string | null,
    pending_sync_count: envelope.pending_sync_count,
  }
}

function parseReminderTaskDetail(value: unknown): ReminderTaskDetail | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Record<string, unknown>
  const parseDue = (candidate: unknown): ReminderTaskDue | null | undefined => {
    if (candidate === null) return null
    if (!candidate || typeof candidate !== 'object') return undefined
    const due = candidate as Record<string, unknown>
    return typeof due.date_time === 'string' && typeof due.time_zone === 'string'
      ? { date_time: due.date_time, time_zone: due.time_zone }
      : undefined
  }
  const due = parseDue(row.due)
  const completedAt = parseDue(row.completed_at)
  if (
    typeof row.id !== 'string' || typeof row.title !== 'string' ||
    (row.importance !== 'low' && row.importance !== 'normal' && row.importance !== 'high') ||
    typeof row.is_completed !== 'boolean' || typeof row.last_modified_at !== 'string' ||
    due === undefined || completedAt === undefined
  ) return null
  return {
    id: row.id, title: row.title, due, importance: row.importance,
    is_completed: row.is_completed, completed_at: completedAt,
    last_modified_at: row.last_modified_at,
  }
}

function parseMutationResult(value: unknown): ReminderTaskMutationResult | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Record<string, unknown>
  if (
    typeof row.id !== 'string' || typeof row.action_id !== 'string' ||
    (row.outcome !== 'synced' && row.outcome !== 'unknown')
  ) return null
  return { id: row.id, outcome: row.outcome, action_id: row.action_id }
}

async function responseFailure(response: Response, fallback: string): Promise<Error> {
  try {
    const body: unknown = await response.json()
    const detail = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
    if (detail && typeof detail === 'object' && typeof (detail as { code?: unknown }).code === 'string') {
      const error = new Error((detail as { code: string }).code) as Error & { actionId?: string }
      if (typeof (detail as { action_id?: unknown }).action_id === 'string') {
        error.actionId = (detail as { action_id: string }).action_id
      }
      return error
    }
  } catch {
    // Fall through to a stable local message.
  }
  return new Error(fallback)
}

const VALID_CLOUD_EFFORTS: readonly CloudEffort[] = [
  'none',
  'minimal',
  'low',
  'medium',
  'high',
  'xhigh',
  'max',
]

function parseEnum<T extends string>(value: unknown, values: readonly T[]): T | null {
  return typeof value === 'string' && values.includes(value as T) ? value as T : null
}

function parseAgentInitialSelection(value: unknown): AgentInitialSelection | undefined {
  if (!value || typeof value !== 'object') {
    return undefined
  }
  const record = value as Record<string, unknown>
  const runtime = record.runtime
  const agent = record.agent
  const modelId = record.model_id
  if (runtime !== 'cloud' && runtime !== 'local') {
    return undefined
  }
  if (!isAgentKey(agent) || typeof modelId !== 'string' || modelId.length === 0) {
    return undefined
  }
  const effort =
    record.effort === null || record.effort === undefined
      ? null
      : parseEnum(record.effort, VALID_CLOUD_EFFORTS)
  if (record.effort !== null && record.effort !== undefined && effort === null) {
    return undefined
  }
  return {
    runtime,
    agent,
    modelId,
    effort,
  }
}

async function fetchReminderEnvelope(): Promise<ReminderEnvelope | null> {
  const response = await fetch(REMINDERS_ENDPOINT)
  if (!response.ok) {
    return null
  }

  const body: unknown = await response.json()
  return parseReminderEnvelope(body)
}

export function useApexData(): UseApexDataReturn {
  const [state, setState] = useState<ApexDataState>({
    activeReminders: [],
    demoModeActive: false,
    devModeActive: false,
    marketEnabled: true,
  })

  const stateRef = useRef(state)
  useLayoutEffect(() => {
    stateRef.current = state
  }, [state])

  const reminderRefreshSequenceRef = useRef(0)

  const applyReminderRecords = useCallback((records: ReminderRecord[], sourceState?: ApexDataState['reminderSourceState']): void => {
    setState((prev) => ({
      ...prev,
      activeReminders: records.map((record) => ({ ...record })),
      ...(sourceState ? { reminderSourceState: sourceState } : {}),
    }))
  }, [])

  const applyBootSettings = useCallback(
    (next: {
      agentQueriesEnabled: boolean
      agentInitialSelection: AgentInitialSelection
      marketEnabled: boolean
    }): void => {
      setState((prev) => ({
        ...prev,
        agentQueriesEnabled: next.agentQueriesEnabled,
        defaultAgent: next.agentInitialSelection.agent,
        agentInitialSelection: next.agentInitialSelection,
        marketEnabled: next.marketEnabled,
      }))
    },
    [],
  )

  const refreshReminders = useCallback(async (): Promise<void> => {
    const requestSequence = ++reminderRefreshSequenceRef.current
    try {
      const envelope = await fetchReminderEnvelope()
      if (requestSequence !== reminderRefreshSequenceRef.current) return
      if (envelope) applyReminderRecords(envelope.items, envelope.source_state)
    } catch {
      // Reminder refresh is best-effort; preserve existing HUD state on failure.
    }
  }, [applyReminderRecords])

  const createReminder = useCallback(
    async (text: string): Promise<'synced' | 'pending' | 'unknown'> => {
      const response = await fetch(REMINDERS_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })

      if (!response.ok) {
        throw new Error(`Create reminder failed with status ${response.status}`)
      }
      const body: unknown = await response.json()
      const outcome = body && typeof body === 'object'
        ? (body as { outcome?: unknown }).outcome
        : null
      await refreshReminders()
      return outcome === 'synced' || outcome === 'pending' || outcome === 'unknown'
        ? outcome
        : 'pending'
    },
    [refreshReminders],
  )

  const markReminderAsRead = useCallback(async (id: string): Promise<void> => {
    const removedReminder = stateRef.current.activeReminders.find((reminder) => reminder.id === id)
    if (!removedReminder) {
      return
    }

    // Invalidate an older list read before starting the mutation. Otherwise an
    // in-flight response captured before completion could restore the task.
    ++reminderRefreshSequenceRef.current

    setState((prev) => {
      const nextActiveReminders = prev.activeReminders.filter(
        (reminder) => reminder.id !== id,
      )

      return {
        ...prev,
        activeReminders: nextActiveReminders,
      }
    })

    try {
      const response = await fetch(REMINDERS_COMPLETE_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      })

      if (!response.ok) {
        throw await responseFailure(response, 'Could not complete reminder.')
      }
      await refreshReminders()
    } catch (error) {
      console.warn('Failed to mark reminder as read; restoring local state.', error)

      setState((prev) => {
        if (prev.activeReminders.some((reminder) => reminder.id === id)) {
          return prev
        }

        const restored = [...prev.activeReminders, removedReminder].sort((a, b) => a.id.localeCompare(b.id))

        return {
          ...prev,
          activeReminders: restored,
        }
      })
      throw error
    }
  }, [refreshReminders])

  const getReminderTask = useCallback(async (id: string): Promise<ReminderTaskDetail> => {
    const response = await fetch(API_ENDPOINTS.reminderTask(id))
    if (!response.ok) throw await responseFailure(response, 'Could not load reminder task.')
    const parsed = parseReminderTaskDetail(await response.json())
    if (!parsed) throw new Error('Reminder task response is invalid.')
    return parsed
  }, [])

  const listCompletedReminders = useCallback(async (): Promise<CompletedRemindersResult> => {
    const response = await fetch(API_ENDPOINTS.remindersCompleted)
    if (!response.ok) throw await responseFailure(response, 'Could not load completed reminders.')
    const body: unknown = await response.json()
    if (!body || typeof body !== 'object') throw new Error('Completed reminders response is invalid.')
    const envelope = body as { items?: unknown; source_state?: unknown }
    if (!Array.isArray(envelope.items) || (envelope.source_state !== 'live' && envelope.source_state !== 'unavailable')) {
      throw new Error('Completed reminders response is invalid.')
    }
    const items = envelope.items.flatMap((item) => {
      const parsed = parseReminderTaskDetail(item)
      return parsed ? [parsed] : []
    })
    return { items, source_state: envelope.source_state }
  }, [])

  const mutateReminderTask = useCallback(async (
    endpoint: string,
    request: ReminderTaskUpdateRequest | ReminderTaskTargetRequest,
  ): Promise<ReminderTaskMutationResult> => {
    const response = await fetch(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
    if (!response.ok && response.status !== 202) {
      throw await responseFailure(response, 'Could not update reminder task.')
    }
    const result = parseMutationResult(await response.json())
    if (!result) throw new Error('Reminder task response is invalid.')
    if (result.outcome === 'synced') await refreshReminders()
    return result
  }, [refreshReminders])

  const updateReminderTask = useCallback(
    (request: ReminderTaskUpdateRequest) => mutateReminderTask(API_ENDPOINTS.remindersUpdate, request),
    [mutateReminderTask],
  )

  const deleteReminderTask = useCallback(
    (request: ReminderTaskTargetRequest) => mutateReminderTask(API_ENDPOINTS.remindersDelete, request),
    [mutateReminderTask],
  )

  const reopenReminderTask = useCallback(
    (request: ReminderTaskTargetRequest) => mutateReminderTask(API_ENDPOINTS.remindersReopen, request),
    [mutateReminderTask],
  )

  const syncReminders = useCallback(async (ids: string[]): Promise<Array<{ id: string; outcome: string }>> => {
    const response = await fetch(API_ENDPOINTS.remindersSync, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    })
    if (!response.ok) throw new Error(`Reminder sync failed with status ${response.status}`)
    const body: unknown = await response.json()
    await refreshReminders()
    if (!body || typeof body !== 'object' || !Array.isArray((body as { items?: unknown }).items)) return []
    return (body as { items: unknown[] }).items.flatMap((item) => {
      if (!item || typeof item !== 'object') return []
      const row = item as { id?: unknown; outcome?: unknown }
      return typeof row.id === 'string' && typeof row.outcome === 'string'
        ? [{ id: row.id, outcome: row.outcome }]
        : []
    })
  }, [refreshReminders])

  const dismissUnknownReminder = useCallback(async (id: string): Promise<void> => {
    const response = await fetch(API_ENDPOINTS.remindersDismiss, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    })
    if (!response.ok) throw new Error(`Reminder dismissal failed with status ${response.status}`)
    await refreshReminders()
  }, [refreshReminders])

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller

    void (async (): Promise<void> => {
      try {
        const [remindersResponse, configResponse] = await Promise.all([
          fetch(REMINDERS_ENDPOINT, { signal }),
          fetch(CONFIG_ENDPOINT, { signal }),
        ])
        if (signal.aborted) return

        let bootPatch: Partial<ApexDataState> = {}
        if (configResponse.ok) {
          try {
            const raw: unknown = await configResponse.json()
            if (raw && typeof raw === 'object') {
              const body = raw as Record<string, unknown>
              const agentInitialSelection = parseAgentInitialSelection(body.cortex_initial_selection)
              bootPatch = {
                ...(agentInitialSelection ? {
                  agentInitialSelection,
                  defaultAgent: agentInitialSelection.agent,
                } : {}),
                ...(typeof body.ask_apex_enabled === 'boolean' ? { agentQueriesEnabled: body.ask_apex_enabled } : {}),
                ...(typeof body.market_enabled === 'boolean' ? { marketEnabled: body.market_enabled } : {}),
                ...(typeof body.demo_mode_active === 'boolean' ? { demoModeActive: body.demo_mode_active } : {}),
                ...(typeof body.dev_mode_active === 'boolean' ? { devModeActive: body.dev_mode_active } : {}),
                ...(parseEnum(body.voice_mode, ['off', 'manual', 'automatic'] as const)
                  ? { voiceMode: parseEnum(body.voice_mode, ['off', 'manual', 'automatic'] as const) ?? undefined }
                  : {}),
              }
            }
          } catch {
            // Boot configuration is best-effort; local controls retain safe defaults.
          }
        }

        let envelope: ReminderEnvelope | null = null
        if (remindersResponse.ok) {
          try {
            envelope = parseReminderEnvelope(await remindersResponse.json())
          } catch {
            envelope = null
          }
        }
        if (signal.aborted) return

        setState((previous) => ({
          ...previous,
          ...bootPatch,
          ...(envelope ? {
            activeReminders: envelope.items.map((record) => ({ ...record })),
            reminderSourceState: envelope.source_state,
          } : {}),
        }))
      } catch (error) {
        if (!signal.aborted && !(error instanceof DOMException && error.name === 'AbortError')) {
          // Launch boot requests are best-effort; subsequent refresh actions can retry.
        }
      }
    })()

    return () => controller.abort()
  }, [])

  return {
    ...state,
    refreshReminders,
    createReminder,
    markReminderAsRead,
    getReminderTask,
    listCompletedReminders,
    updateReminderTask,
    deleteReminderTask,
    reopenReminderTask,
    syncReminders,
    dismissUnknownReminder,
    applyBootSettings,
  }
}
