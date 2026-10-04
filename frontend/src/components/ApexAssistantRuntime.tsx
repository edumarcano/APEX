/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  RuntimeAdapterProvider,
  MessagePrimitive,
  ThreadPrimitive,
  ThreadListPrimitive,
  ThreadListItemPrimitive,
  useAui,
  useAuiState,
  useLocalRuntime,
  useRemoteThreadListRuntime,
  ExportedMessageRepository,
  type ChatModelAdapter,
  type RemoteThreadListAdapter,
  type ThreadHistoryAdapter,
} from '@assistant-ui/react'

import { createAssistantStream } from 'assistant-stream'

import { API_ENDPOINTS } from '../lib/api'
import { streamRunEvents } from '../lib/cortexStream'
import type { RunRecord } from '../types/runs'
import type { RunActivityStep, RunActivityStepType } from '../types/runs'
import type { AgentKey, CloudEffort, LocalReasoningMode, ModelCatalogEntry } from '../types/telemetry'
import { CortexErrorFeedback, CortexQueryRim } from './AgentQueryBar'
import { ToolsSelector, type ToolsSelectorProps } from './ToolsSelector'
import { CompactModelSelector } from './CompactModelSelector'
import { OPERATION_PROMPT_CHIPS } from '../lib/promptChips'
import { Send, Square, Trash2 } from 'lucide-react'
import { ApexLogo, type ApexLogoProps } from './ApexLogo'
import { DeferredPresentation } from './DeferredPresentation'
import { writeClipboardText } from '../platform/services'

const loadAssistantMarkdown = () => import('./AssistantMarkdown')

type ConversationSummary = {
  id: string
  title: string
  archived_at: string | null
  agent: AgentKey
  selected_tool_names: string[] | null
  tool_profile_id: string | null
  updated_at: string
}

type ConversationMessage = {
  id: string
  parent_message_id: string | null
  role: 'user' | 'agent'
  content: string
  status: 'pending' | 'completed' | 'failed' | 'interrupted'
  created_at: string
  response_metadata: Record<string, unknown> | null
}

type ConversationDetail = ConversationSummary & {
  active_leaf_message_id: string | null
  messages: ConversationMessage[]
}

export type ApexAssistantConversationPreferences = Pick<ConversationSummary, 'agent' | 'selected_tool_names' | 'tool_profile_id'>

export type ApexAssistantRuntimeHandle = {
  submitPrompt: (
    prompt: string,
    overrides?: Partial<Pick<ApexAssistantRunConfig, 'agent' | 'effort' | 'modelId' | 'contextWindow' | 'localReasoningMode' | 'selectedToolNames' | 'toolProfileId'>>,
    options?: { startNewThread?: boolean },
  ) => Promise<boolean>
  patchPreferences: (updates: { agent?: AgentKey; selectedToolNames?: string[] | null; toolProfileId?: string | null }) => Promise<ApexAssistantPatchedPreferences | null>
  openConversation: (conversationId: string) => Promise<boolean>
}

export type ApexAssistantPatchedPreferences = ApexAssistantConversationPreferences & {
  conversationId: string
}

export type ApexAssistantRunConfig = {
  agent: AgentKey
  effort: CloudEffort | null
  modelId?: string | null
  contextWindow?: number | null
  localReasoningMode?: 'none' | 'focused' | null
  selectedToolNames: string[]
  toolProfileId: string | null
  snapshotId: string | null
}

export type ApexAssistantComposerProps = {
  activeAgent: AgentKey
  activeAgentName: string
  tools: ToolsSelectorProps
  selectedModelId?: string
  onModelChange?: (modelId: string) => void
  modelCatalog?: ModelCatalogEntry[]
  cloudEffort?: CloudEffort
  onEffortChange?: (effort: CloudEffort) => void
  localReasoningMode?: LocalReasoningMode
  onLocalReasoningModeChange?: (mode: LocalReasoningMode) => void | Promise<boolean>
  integrated?: boolean
  disabled?: boolean
  error?: string | null
}

type Props = {
  config: ApexAssistantRunConfig
  children: ReactNode
  beforeRun?: (config: ApexAssistantRunConfig) => Promise<boolean>
  onConversationChange?: (conversation: ConversationSummary | null) => void
  onRunningChange?: (running: boolean, agent: AgentKey | null) => void
  onResponseChange?: (response: Record<string, unknown> | null, error: string | null) => void
  onActivityChange?: (label: string | null) => void
  toolLabels?: Array<{ name: string; label: string }>
  runtimeRef?: React.MutableRefObject<ApexAssistantRuntimeHandle | null>
}

type AssistantActivityView = { runId: string | null; status: string | null; steps: RunActivityStep[] }
const AssistantActivityContext = createContext<AssistantActivityView>({ runId: null, status: null, steps: [] })
const AssistantToolLabelsContext = createContext<Array<{ name: string; label: string }>>([])
const EMPTY_TOOL_LABELS: Array<{ name: string; label: string }> = []
export function useApexAssistantActivity(): AssistantActivityView {
  return useContext(AssistantActivityContext)
}

const NATIVE_TOOL_LABELS: Record<string, { active: string; done: string }> = {
  get_upcoming_calendar_events: { active: 'Checking your calendar', done: 'Checked your calendar' },
  get_active_reminders: { active: 'Reading active reminders', done: 'Read active reminders' },
  get_weather_forecast: { active: 'Checking the weather', done: 'Checked the weather' },
  search_gmail: { active: 'Searching email', done: 'Searched email' },
  get_gmail_message: { active: 'Reading email', done: 'Read email' },
  search_apex_docs: { active: 'Searching APEX documentation', done: 'Searched APEX documentation' },
  list_microsoft_todo_tasks: { active: 'Checking To Do tasks', done: 'Checked To Do tasks' },
}

export function activityStepLabel(step: RunActivityStep, toolLabels: Record<string, string> = {}): string {
  const payload = step.payload
  switch (step.type) {
    case 'model.started': return typeof payload.turn === 'number' && payload.turn > 1 ? 'Reviewing results' : 'Thinking'
    case 'model.completed': return 'Model turn completed'
    case 'tool.started': {
      const name = typeof payload.name === 'string' ? payload.name : ''
      if (payload.origin === 'provider') return 'Searching with provider tools'
      return NATIVE_TOOL_LABELS[name]?.active ?? (toolLabels[name] ? `Using ${toolLabels[name]}` : 'Using a tool')
    }
    case 'tool.completed': {
      const name = typeof payload.name === 'string' ? payload.name.toLowerCase() : ''
      if (payload.origin === 'provider' && /google.*search|search.*google/.test(name)) return 'Used Google Search'
      if (payload.origin === 'provider' && /google.*maps|maps.*google/.test(name)) return 'Used Google Maps'
      if (payload.origin === 'provider') return 'Used a provider tool'
      return NATIVE_TOOL_LABELS[name]?.done ?? (toolLabels[name] ? `Used ${toolLabels[name]}` : 'Tool completed')
    }
    case 'action.proposed': return 'Proposed an action for approval'
    case 'retry.updated': return 'Retrying the request'
    case 'response.started': return 'Writing response'
    case 'run.completed': return payload.status === 'completed' ? 'Completed' : payload.status === 'cancelled' ? 'Cancelled' : 'Stopped'
  }
}

function activityStepFromEvent(event: { sequence: number; timestamp: string; type: string; payload: Record<string, unknown> }): RunActivityStep | null {
  const fields: Partial<Record<string, string[]>> = {
    'model.started': ['turn'], 'model.completed': ['turn', 'provider_ms'],
    'tool.started': ['name', 'origin'], 'tool.completed': ['name', 'origin', 'status', 'duration_ms'],
    'action.proposed': ['status', 'risk'], 'usage.updated': ['retries_count'],
  }
  const payload: Record<string, unknown> = {}
  if (event.type === 'usage.updated') {
    if (typeof event.payload.retries_count !== 'number') return null
    payload.retries_count = event.payload.retries_count
    return { sequence: event.sequence, timestamp: event.timestamp, type: 'retry.updated', payload }
  }
  if (!(event.type in fields)) return null
  for (const field of fields[event.type] ?? []) {
    const value = event.payload[field]
    if (typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value))) payload[field] = value
  }
  return { sequence: event.sequence, timestamp: event.timestamp, type: event.type as RunActivityStepType, payload }
}

const ACTIVITY_STEP_TYPES: ReadonlySet<string> = new Set([
  'model.started', 'model.completed', 'tool.started', 'tool.completed',
  'action.proposed', 'retry.updated', 'response.started', 'run.completed',
])

function safeActivitySteps(value: unknown): RunActivityStep[] {
  if (!Array.isArray(value)) return []
  return value.filter((step): step is RunActivityStep => Boolean(
    step && typeof step === 'object' && ACTIVITY_STEP_TYPES.has(step.type) &&
    Number.isInteger(step.sequence) && step.sequence >= 0 && typeof step.timestamp === 'string' &&
    step.payload && typeof step.payload === 'object' && !Array.isArray(step.payload),
  )).slice(-64)
}

export function ActivityTimeline({ steps, toolLabels = [], collapsed = false }: { steps: unknown; toolLabels?: Array<{ name: string; label: string }>; collapsed?: boolean }): ReactNode {
  const [open, setOpen] = useState(!collapsed)
  const safeSteps = safeActivitySteps(steps)
  if (!safeSteps.length) return null
  const labels = Object.fromEntries(toolLabels.map((tool) => [tool.name, tool.label]))
  return <details className="mt-2 rounded-lg border border-white/10 bg-black/10" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer select-none px-3 py-2 font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-500 hover:text-zinc-300">Activity</summary>
    <ol className="space-y-1 border-t border-white/10 px-3 py-2" aria-label="Agent activity steps">{safeSteps.map((step, index) => <li key={`${step.sequence}-${step.type}-${index}`} className="flex items-center justify-between gap-3 text-xs text-zinc-400"><span>{activityStepLabel(step, labels)}</span>{step.payload.origin !== 'provider' && typeof step.payload.duration_ms === 'number' ? <time className="shrink-0 font-mono text-[10px] text-zinc-600">{Math.max(0, step.payload.duration_ms / 1000).toFixed(1)}s</time> : null}</li>)}</ol>
  </details>
}

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function canonicalId(value: string, ids: Map<string, string>): string {
  if (uuidPattern.test(value)) return value
  const existing = ids.get(value)
  if (existing) return existing
  const id = crypto.randomUUID()
  ids.set(value, id)
  return id
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null) as unknown
    const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail?: unknown }).detail : null
    const detailMessage = typeof detail === 'string'
      ? detail
      : detail && typeof detail === 'object' && 'message' in detail && typeof (detail as { message?: unknown }).message === 'string'
        ? (detail as { message: string }).message
        : null
    throw new Error(detailMessage ?? `APEX request failed (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

async function persistActiveLeaf(remoteId: string | undefined, messageId: string): Promise<void> {
  if (!remoteId) return
  await requestJson(API_ENDPOINTS.cortexConversation(remoteId), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active_leaf_message_id: messageId }),
  })
}

const LIST_FAILURE_COOLDOWN_MS = 1_500
const HISTORY_FAILURE_COOLDOWN_MS = 1_500

type HistoryLoadState = {
  inFlight: Map<string, Promise<ExportedMessageRepository>>
  failureUntil: Map<string, number>
}

type PendingAssistantMessage = {
  conversationId: string
  messageId: string
  content: string
}

function topologicalSortMessages(messages: ConversationMessage[]): ConversationMessage[] {
  if (messages.length <= 1) return messages
  const byId = new Map<string, ConversationMessage>()
  const childrenMap = new Map<string | null, ConversationMessage[]>()
  for (const msg of messages) {
    byId.set(msg.id, msg)
    const pid = msg.parent_message_id ?? null
    const list = childrenMap.get(pid)
    if (list) list.push(msg)
    else childrenMap.set(pid, [msg])
  }
  const sorted: ConversationMessage[] = []
  const visited = new Set<string>()
  function visit(msg: ConversationMessage): void {
    if (visited.has(msg.id)) return
    visited.add(msg.id)
    sorted.push(msg)
    const children = childrenMap.get(msg.id)
    if (children) {
      for (const child of children) {
        visit(child)
      }
    }
  }
  for (const msg of messages) {
    if (!msg.parent_message_id || !byId.has(msg.parent_message_id)) {
      visit(msg)
    }
  }
  for (const msg of messages) {
    if (!visited.has(msg.id)) {
      visit(msg)
    }
  }
  return sorted
}

function ThreadHistory({ children, getThreadIds, onConversationChangeRef, onPendingChangeRef, historyLoadStateRef, forceHistoryReloadRef, pendingAssistantRef }: { children?: ReactNode; getThreadIds: (remoteId: string) => Map<string, string>; onConversationChangeRef: React.MutableRefObject<((conversation: ConversationSummary | null) => void) | undefined>; onPendingChangeRef: React.MutableRefObject<((conversationId: string, agent: AgentKey, pending: boolean) => void) | undefined>; historyLoadStateRef: React.MutableRefObject<HistoryLoadState>; forceHistoryReloadRef: React.MutableRefObject<boolean>; pendingAssistantRef: React.MutableRefObject<PendingAssistantMessage | null> }): ReactNode {
  const aui = useAui()
  const history = useMemo<ThreadHistoryAdapter>(() => ({
    async load() {
      const remoteId = aui.threadListItem.getState().remoteId
      if (!remoteId) return ExportedMessageRepository.fromBranchableArray([])
      const existing = historyLoadStateRef.current.inFlight.get(remoteId)
      if (existing) return existing
      const now = Date.now()
      if (!forceHistoryReloadRef.current && (historyLoadStateRef.current.failureUntil.get(remoteId) ?? 0) > now) {
        throw new Error('Conversation history is temporarily unavailable. Retry shortly.')
      }
      forceHistoryReloadRef.current = false
      const loadPromise = (async (): Promise<ExportedMessageRepository> => {
        try {
          const detail = await requestJson<ConversationDetail>(API_ENDPOINTS.cortexConversation(remoteId))
          onConversationChangeRef.current?.(detail)
          onPendingChangeRef.current?.(detail.id, detail.agent, detail.messages.some((message) => message.role === 'agent' && message.status === 'pending'))
          const pendingAssistant = pendingAssistantRef.current
          const pendingMessage = pendingAssistant?.conversationId === detail.id
            ? detail.messages.find((message) => message.id === pendingAssistant.messageId)
            : undefined
          if (pendingAssistant && pendingMessage && pendingMessage.status !== 'pending') {
            pendingAssistantRef.current = null
          }
          const orderedMessages = topologicalSortMessages(detail.messages)
          const idMap = getThreadIds(remoteId)
          idMap.clear()
          for (const msg of orderedMessages) {
            idMap.set(msg.id, msg.id)
          }
          historyLoadStateRef.current.failureUntil.delete(remoteId)
          const headId = detail.active_leaf_message_id || (orderedMessages.at(-1)?.id ?? undefined)
          return ExportedMessageRepository.fromBranchableArray(
            orderedMessages.map((message) => ({
              parentId: message.parent_message_id,
              message: message.role === 'user'
                ? {
                    id: message.id,
                    role: 'user' as const,
                    content: [{ type: 'text' as const, text: message.content }],
                    createdAt: new Date(message.created_at),
                    attachments: [],
                    metadata: { custom: {} },
                  }
                : {
                    id: message.id,
                    role: 'assistant' as const,
                    content: [{
                      type: 'text' as const,
                      text: message.status === 'pending'
                        && pendingAssistant?.conversationId === detail.id
                        && pendingAssistant.messageId === message.id
                        && pendingAssistant.content
                        ? pendingAssistant.content
                        : message.content,
                    }],
                    createdAt: new Date(message.created_at),
                    status: message.status === 'completed'
                      ? { type: 'complete' as const, reason: 'stop' as const }
                      : message.status === 'pending'
                        ? { type: 'running' as const }
                        : { type: 'incomplete' as const, reason: 'error' as const, error: String(message.response_metadata?.error ?? message.status) },
                    metadata: { custom: { apex: message.response_metadata ?? {} } },
                  },
            })),
            { headId },
          )
        } catch (error) {
          historyLoadStateRef.current.failureUntil.set(remoteId, Date.now() + HISTORY_FAILURE_COOLDOWN_MS)
          throw error
        } finally {
          historyLoadStateRef.current.inFlight.delete(remoteId)
        }
      })()
      historyLoadStateRef.current.inFlight.set(remoteId, loadPromise)
      return loadPromise
    },
    async append() {},
    async update() {},
  }), [aui, forceHistoryReloadRef, getThreadIds, historyLoadStateRef, onConversationChangeRef, onPendingChangeRef, pendingAssistantRef])
  return <RuntimeAdapterProvider adapters={{ history }}>{children}</RuntimeAdapterProvider>
}

type ApexAssistantComposerContextValue = {
  configRef: React.MutableRefObject<ApexAssistantRunConfig>
  setPendingPrompt: (text: string) => void
  setTurnOverrides?: (overrides: Partial<ApexAssistantRunConfig> | null) => void
  beforeRun?: (config: ApexAssistantRunConfig) => Promise<boolean>
  markPreflightPassed: () => void
  persistActiveLeaf: (messageId: string) => Promise<void>
  clearBranchPersistenceError: () => void
  branchPersistenceError: string | null
  reloadThreads: () => Promise<void>
  threadListError: string | null
  isTurnLocked: boolean
  beginTurn: (agent: AgentKey) => boolean
  finishTurn: () => void
}

const ApexAssistantComposerContext = createContext<ApexAssistantComposerContextValue | null>(null)

type ApexComposerSubmitRuntime = {
  getState: () => { text: string }
  send: () => void
}

type ApexThreadListResult = {
  threads: Array<{
    remoteId: string
    status: 'regular' | 'archived'
    title: string
    lastMessageAt: Date
    custom: ConversationSummary
  }>
}

export function useApexAssistantComposer(composerOverride?: ApexComposerSubmitRuntime): {
  submit: (overrides?: Partial<ApexAssistantRunConfig>, promptOverride?: string) => Promise<boolean>
  isRunning: boolean
} {
  const aui = useAui()
  const context = useContext(ApexAssistantComposerContext)
  const beforeRun = context?.beforeRun
  const configRef = context?.configRef
  const setPendingPrompt = context?.setPendingPrompt
  const setTurnOverrides = context?.setTurnOverrides
  const markPreflightPassed = context?.markPreflightPassed
  const beginTurn = context?.beginTurn
  const finishTurn = context?.finishTurn
  const isRunning = useAuiState((state) => state.thread.isRunning)
  if (!context) throw new Error('useApexAssistantComposer must be used inside ApexAssistantRuntime.')
  const composer = composerOverride ?? aui.composer
  const submit = useCallback(async (overrides?: Partial<ApexAssistantRunConfig>, promptOverride?: string): Promise<boolean> => {
    const threadState = aui.thread().getState()
    if (threadState.isRunning || threadState.isLoading) return false
    const text = (promptOverride ?? composer.getState().text).trim()
    if (!text || !configRef || !beginTurn || !finishTurn) return false
    const effectiveConfig = { ...configRef.current, ...(overrides ?? {}) }
    if (!beginTurn(effectiveConfig.agent)) return false
    setTurnOverrides?.(overrides ?? null)
    setPendingPrompt?.(text)
    try {
      if (beforeRun && !await beforeRun(effectiveConfig)) {
        setTurnOverrides?.(null)
        finishTurn()
        return false
      }
    } catch {
      setTurnOverrides?.(null)
      finishTurn()
      return false
    }
    if (!aui.threadListItem.getState().remoteId) {
      try {
        await aui.threadListItem.initialize()
      } catch {
        setTurnOverrides?.(null)
        finishTurn()
        return false
      }
    }
    markPreflightPassed?.()
    aui.thread.composer().setText(text)
    composer.send()
    queueMicrotask(() => {
      try {
        void aui.threadListItem.generateTitle()
      } catch {
        // Ignored if thread runtime not yet settled
      }
    })
    return true
  }, [aui, beforeRun, beginTurn, composer, configRef, finishTurn, markPreflightPassed, setPendingPrompt, setTurnOverrides])
  return { submit, isRunning }
}

function ApexAssistantController({ runtimeRef, branchPersistRef, getActiveRemoteId, getThreadIds, forceHistoryReloadRef, onBranchPersistenceError, prepareConversationForOpen }: { runtimeRef?: React.MutableRefObject<ApexAssistantRuntimeHandle | null>; branchPersistRef: React.MutableRefObject<(messageId: string) => Promise<void>>; getActiveRemoteId: () => string | undefined; getThreadIds: (remoteId: string) => Map<string, string>; forceHistoryReloadRef: React.MutableRefObject<boolean>; onBranchPersistenceError: (message: string | null) => void; prepareConversationForOpen: (detail: ConversationDetail) => void }): ReactNode {
  const aui = useAui()
  const { submit } = useApexAssistantComposer()
  const openConversationSequenceRef = useRef(0)
  const openConversationQueueRef = useRef<Promise<void>>(Promise.resolve())
  const persistBranch = useCallback(async (messageId: string): Promise<void> => {
    const remoteId = getActiveRemoteId() ?? aui.threadListItem.getState().remoteId
    if (!remoteId || !messageId) return
    const canonicalMessageId = canonicalId(messageId, getThreadIds(remoteId))
    try {
      await persistActiveLeaf(remoteId, canonicalMessageId)
    } catch (error) {
      // Reconcile the client with the server before surfacing the failure. A
      // branch selection must never remain a client-only state.
      forceHistoryReloadRef.current = true
      try {
        await aui.threads.reloadMainThread()
      } finally {
        onBranchPersistenceError(error instanceof Error ? error.message : 'Unable to persist branch selection.')
      }
      throw error
    }
  }, [aui, forceHistoryReloadRef, getActiveRemoteId, getThreadIds, onBranchPersistenceError])
  useEffect(() => {
    branchPersistRef.current = persistBranch
    if (!runtimeRef) return
    runtimeRef.current = {
      submitPrompt: async (
        prompt: string,
        overrides?: Partial<ApexAssistantRunConfig>,
        options?: { startNewThread?: boolean },
      ): Promise<boolean> => {
        const text = prompt.trim()
        if (!text) return false
        if (options?.startNewThread) {
          try {
            await aui.threads.switchToNewThread()
          } catch {
            // If already on new thread or switching fails gracefully, proceed
          }
        }
        if (aui.thread().getState().isLoading) return false
        return submit(overrides, text)
      },
      patchPreferences: async (updates): Promise<ApexAssistantPatchedPreferences | null> => {
        const remoteId = getActiveRemoteId() ?? aui.threadListItem.getState().remoteId
        if (!remoteId) return null
        try {
          const summary = await requestJson<ConversationSummary>(API_ENDPOINTS.cortexConversation(remoteId), {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              ...(updates.agent !== undefined ? { agent: updates.agent } : {}),
              ...(updates.selectedToolNames !== undefined ? { selected_tool_names: updates.selectedToolNames } : {}),
              ...(updates.toolProfileId !== undefined ? { tool_profile_id: updates.toolProfileId } : {}),
            }),
          })
          return {
            conversationId: summary.id,
            agent: summary.agent,
            selected_tool_names: summary.selected_tool_names,
            tool_profile_id: summary.tool_profile_id,
          }
        } catch {
          return null
        }
      },
      openConversation: async (conversationId: string): Promise<boolean> => {
        const sequence = ++openConversationSequenceRef.current
        try {
          const detail = await requestJson<ConversationDetail>(API_ENDPOINTS.cortexConversation(conversationId))
          if (openConversationSequenceRef.current !== sequence) return false
          const openPromise = openConversationQueueRef.current.then(async () => {
            if (openConversationSequenceRef.current !== sequence) return false
            prepareConversationForOpen(detail)
            forceHistoryReloadRef.current = true
            await aui.threads.reload()
            if (openConversationSequenceRef.current !== sequence) return false
            await aui.threads.switchToThread(detail.id)
            if (openConversationSequenceRef.current !== sequence) return false
            forceHistoryReloadRef.current = true
            await aui.threads.reloadMainThread()
            return openConversationSequenceRef.current === sequence
          })
          openConversationQueueRef.current = openPromise.then(() => undefined, () => undefined)
          return await openPromise
        } catch {
          return false
        }
      },
    }
    return () => { runtimeRef.current = null; branchPersistRef.current = async () => {} }
  }, [aui, branchPersistRef, forceHistoryReloadRef, getActiveRemoteId, onBranchPersistenceError, persistBranch, prepareConversationForOpen, runtimeRef, submit])
  return null
}

export function ApexAssistantRuntime({ config, children, beforeRun, onConversationChange, onRunningChange, onResponseChange, onActivityChange, toolLabels = EMPTY_TOOL_LABELS, runtimeRef }: Props): ReactNode {
  const configRef = useRef(config)
  const pendingPromptRef = useRef<string | null>(null)
  const beforeRunRef = useRef(beforeRun)
  const onConversationChangeRef = useRef(onConversationChange)
  const onRunningChangeRef = useRef(onRunningChange)
  const onResponseChangeRef = useRef(onResponseChange)
  const onActivityChangeRef = useRef(onActivityChange)
  const toolLabelsRef = useRef(toolLabels)
  const [activityView, setActivityView] = useState<AssistantActivityView>({ runId: null, status: null, steps: [] })
  const pendingTurnRef = useRef<{ conversationId: string; agent: AgentKey } | null>(null)
  const [pendingTurnRevision, setPendingTurnRevision] = useState(0)
  const launchTurnRef = useRef(false)
  const modelTurnRef = useRef(false)
  const [isTurnLocked, setIsTurnLocked] = useState(false)
  // Host callbacks are intentionally read through refs so App polling and
  // diagnostics updates cannot recreate assistant-ui's remote adapter.
  useEffect(() => {
    configRef.current = config
  }, [config])
  useEffect(() => {
    toolLabelsRef.current = toolLabels
  }, [toolLabels])
  useEffect(() => {
    beforeRunRef.current = beforeRun
    onConversationChangeRef.current = onConversationChange
    onRunningChangeRef.current = onRunningChange
    onResponseChangeRef.current = onResponseChange
    onActivityChangeRef.current = onActivityChange
  }, [beforeRun, onActivityChange, onConversationChange, onRunningChange, onResponseChange])
  const threadIds = useRef(new Map<string, Map<string, string>>())
  const getThreadIds = useCallback((remoteId: string): Map<string, string> => {
    let map = threadIds.current.get(remoteId)
    if (!map) {
      map = new Map<string, string>()
      threadIds.current.set(remoteId, map)
    }
    return map
  }, [])
  const remoteByLocal = useRef(new Map<string, string>())
  const titleByRemote = useRef(new Map<string, string>())
  const preflightPassedRef = useRef(false)
  const turnOverridesRef = useRef<Partial<ApexAssistantRunConfig> | null>(null)
  const branchPersistRef = useRef<(messageId: string) => Promise<void>>(async () => {})
  const [threadListError, setThreadListError] = useState<string | null>(null)
  const [branchPersistenceError, setBranchPersistenceError] = useState<string | null>(null)
  const setTurnOverrides = useCallback((overrides: Partial<ApexAssistantRunConfig> | null) => {
    turnOverridesRef.current = overrides
  }, [])
  const activeRemoteIdRef = useRef<string | undefined>(undefined)
  const getActiveRemoteId = useCallback(() => activeRemoteIdRef.current, [])
  const forceListReloadRef = useRef(false)
  // The remote runtime treats adapter identity changes as a reload signal.
  // Keep request state outside the adapter closure so transient failures cannot
  // turn host re-renders into a request storm.
  const listRequestRef = useRef<Promise<ApexThreadListResult> | null>(null)
  const listCacheRef = useRef<ApexThreadListResult | null>(null)
  const requiredConversationRef = useRef<ConversationDetail | null>(null)
  const listFailureRef = useRef<{ error: Error; until: number } | null>(null)
  const historyLoadStateRef = useRef<HistoryLoadState>({ inFlight: new Map(), failureUntil: new Map() })
  const forceHistoryReloadRef = useRef(false)
  const pendingAssistantRef = useRef<PendingAssistantMessage | null>(null)
  const prepareConversationForOpen = useCallback((detail: ConversationDetail): void => {
    requiredConversationRef.current = detail
    titleByRemote.current.set(detail.id, detail.title)
    listCacheRef.current = null
    listFailureRef.current = null
    forceListReloadRef.current = true
  }, [])
  const syncTurnLock = useCallback((activeAgent?: AgentKey): void => {
    const pending = pendingTurnRef.current
    const running = launchTurnRef.current || modelTurnRef.current || pending !== null
    setIsTurnLocked(running)
    onRunningChangeRef.current?.(running, running ? (pending?.agent ?? activeAgent ?? configRef.current.agent) : null)
  }, [])
  const beginTurn = useCallback((agent: AgentKey): boolean => {
    if (launchTurnRef.current || modelTurnRef.current || pendingTurnRef.current) return false
    launchTurnRef.current = true
    syncTurnLock(agent)
    return true
  }, [syncTurnLock])
  const finishTurn = useCallback((): void => {
    launchTurnRef.current = false
    modelTurnRef.current = false
    syncTurnLock()
  }, [syncTurnLock])
  const handlePendingChange = useCallback((conversationId: string, agent: AgentKey, pending: boolean): void => {
    const current = pendingTurnRef.current
    if (pending) {
      const changed = current?.conversationId !== conversationId || current?.agent !== agent
      pendingTurnRef.current = { conversationId, agent }
      if (changed) setPendingTurnRevision((revision) => revision + 1)
    } else if (current?.conversationId === conversationId) {
      pendingTurnRef.current = null
      setPendingTurnRevision((revision) => revision + 1)
    }
    syncTurnLock()
  }, [syncTurnLock])
  const onPendingChangeRef = useRef(handlePendingChange)
  useEffect(() => { onPendingChangeRef.current = handlePendingChange }, [handlePendingChange])

  const runtimeRefInternal = useRef<ReturnType<typeof useRemoteThreadListRuntime> | null>(null)
  const initialSelectedRef = useRef(false)
  const adapter = useMemo<RemoteThreadListAdapter>(() => ({
    async list(): Promise<ApexThreadListResult> {
      const existing = listRequestRef.current
      if (existing) return existing
      const failure = listFailureRef.current
      if (!forceListReloadRef.current && failure && failure.until > Date.now()) {
        setThreadListError(failure.error.message)
        if (listCacheRef.current) return listCacheRef.current
        throw failure.error
      }
      forceListReloadRef.current = false
      const listPromise = (async (): Promise<ApexThreadListResult> => {
        try {
          const [initialRegular, archived] = await Promise.all([
            requestJson<ConversationSummary[]>(API_ENDPOINTS.cortexConversations),
            requestJson<ConversationSummary[]>(`${API_ENDPOINTS.cortexConversations}?archived=true`),
          ])
          const regularList = Array.isArray(initialRegular) ? initialRegular : []
          const archivedList = Array.isArray(archived) ? archived : []
          const requiredConversation = requiredConversationRef.current
          if (requiredConversation
            && !regularList.some((item) => item.id === requiredConversation.id)
            && !archivedList.some((item) => item.id === requiredConversation.id)) {
            ;(requiredConversation.archived_at ? archivedList : regularList).unshift(requiredConversation)
          }
          if (!initialSelectedRef.current && regularList[0]) {
            initialSelectedRef.current = true
            const firstId = regularList[0].id
            if (activeRemoteIdRef.current !== firstId) {
              queueMicrotask(() => {
                if (activeRemoteIdRef.current !== firstId) {
                  void runtimeRefInternal.current?.threads.switchToThread(firstId)
                }
              })
            }
          }
          const result: ApexThreadListResult = { threads: [...regularList, ...archivedList].map((item) => ({
            remoteId: item.id, status: item.archived_at ? 'archived' : 'regular', title: item.title,
            lastMessageAt: new Date(item.updated_at), custom: item,
          })) }
          listCacheRef.current = result
          listFailureRef.current = null
          setThreadListError(null)
          return result
        } catch (error) {
          const normalized = error instanceof Error ? error : new Error('Conversation list failed to load.')
          listFailureRef.current = { error: normalized, until: Date.now() + LIST_FAILURE_COOLDOWN_MS }
          setThreadListError(normalized.message)
          throw normalized
        } finally {
          listRequestRef.current = null
        }
      })()
      listRequestRef.current = listPromise
      return listPromise
    },
    async initialize(localId) {
      const overrides = turnOverridesRef.current
      const current = { ...configRef.current, ...(overrides ?? {}) }
      const promptText = pendingPromptRef.current?.split('\n')[0].trim()
      const title = promptText ? (promptText.length > 40 ? `${promptText.slice(0, 37)}…` : promptText) : undefined
      const item = await requestJson<ConversationSummary>(API_ENDPOINTS.cortexConversations, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ origin: 'hud', agent: current.agent, title, selected_tool_names: current.selectedToolNames, tool_profile_id: current.toolProfileId }),
      })
      remoteByLocal.current.set(localId, item.id)
      titleByRemote.current.set(item.id, item.title)
      activeRemoteIdRef.current = item.id
      listCacheRef.current = null
      listFailureRef.current = null
      forceListReloadRef.current = true
      onConversationChangeRef.current?.(item)
      return { remoteId: item.id }
    },
    async rename(remoteId, title) {
      await requestJson(API_ENDPOINTS.cortexConversation(remoteId), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) })
      titleByRemote.current.set(remoteId, title)
      listCacheRef.current = null
      forceListReloadRef.current = true
    },
    async archive(remoteId) {
      await requestJson(API_ENDPOINTS.cortexConversation(remoteId), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ archived: true }) })
      listCacheRef.current = null
      forceListReloadRef.current = true
    },
    async unarchive(remoteId) {
      await requestJson(API_ENDPOINTS.cortexConversation(remoteId), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ archived: false }) })
      listCacheRef.current = null
      forceListReloadRef.current = true
    },
    async delete(remoteId) {
      await requestJson(API_ENDPOINTS.cortexConversation(remoteId), { method: 'DELETE' })
      titleByRemote.current.delete(remoteId)
      listCacheRef.current = null
      forceListReloadRef.current = true
    },
    async generateTitle(remoteId, messages) {
      const cachedTitle = remoteId ? titleByRemote.current.get(remoteId) : undefined
      const firstUserText = messages.find((m) => m.role === 'user')?.content.filter((c) => c.type === 'text').map((c) => c.text).join(' ').trim()
      const promptTitle = firstUserText ? (firstUserText.length > 40 ? `${firstUserText.slice(0, 37)}…` : firstUserText) : undefined
      const title = cachedTitle || promptTitle || 'New conversation'
      return createAssistantStream((controller) => {
        controller.appendText(title)
      })
    },
    async fetch(remoteId) {
      const cached = listCacheRef.current?.threads.find((thread) => thread.remoteId === remoteId)?.custom
      const item = cached ?? await requestJson<ConversationSummary>(API_ENDPOINTS.cortexConversation(remoteId))
      onConversationChangeRef.current?.(item)
      return { remoteId: item.id, status: item.archived_at ? 'archived' : 'regular', title: item.title, lastMessageAt: new Date(item.updated_at), custom: item }
    },
    unstable_Provider: ({ children }: { children?: ReactNode }) => <ThreadHistory forceHistoryReloadRef={forceHistoryReloadRef} getThreadIds={getThreadIds} historyLoadStateRef={historyLoadStateRef} onConversationChangeRef={onConversationChangeRef} onPendingChangeRef={onPendingChangeRef} pendingAssistantRef={pendingAssistantRef}>{children}</ThreadHistory>,
  }), [getThreadIds, onConversationChangeRef])

  const runtimeHook = useCallback(() => {
    const model: ChatModelAdapter = {
      async *run(options) {
        let submittedRunId: string | null = null
        const localThreadId = options.unstable_threadId
        const remoteId = (localThreadId && uuidPattern.test(localThreadId) ? localThreadId : undefined)
          ?? (localThreadId ? remoteByLocal.current.get(localThreadId) : undefined)
          ?? activeRemoteIdRef.current
        const user = options.messages.at(-1)
        if (!remoteId || !user || user.role !== 'user' || !options.unstable_assistantMessageId) throw new Error('Conversation is not ready.')
        const overrides = turnOverridesRef.current
        turnOverridesRef.current = null
        const current = { ...configRef.current, ...(overrides ?? {}) }
        if (beforeRunRef.current && !preflightPassedRef.current) {
          try {
            if (!await beforeRunRef.current(current)) {
              finishTurn()
              throw new Error('This request did not pass APEX preflight.')
            }
          } catch (error) {
            finishTurn()
            throw error
          }
        }
        preflightPassedRef.current = false
        modelTurnRef.current = true
        syncTurnLock()
        try {
          const idMap = getThreadIds(remoteId)
          const userMessageId = canonicalId(user.id, idMap)
          const agentMessageId = canonicalId(options.unstable_assistantMessageId, idMap)
          let parentMessageId: string | undefined = undefined
          const parentMessage = options.messages.at(-2)
          if (parentMessage?.id) {
            parentMessageId = canonicalId(parentMessage.id, idMap)
          }

          const runRecord = await requestJson<RunRecord>(API_ENDPOINTS.cortexConversationRuns(remoteId), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              prompt: user.content.filter((part) => part.type === 'text').map((part) => part.text).join('\n'),
              user_message_id: userMessageId,
              agent_message_id: agentMessageId,
              ...(parentMessageId ? { parent_message_id: parentMessageId } : {}),
              agent: current.agent,
              effort: current.effort,
              ...(current.modelId ? { model_id: current.modelId } : {}),
              ...(current.contextWindow ? { context_window: current.contextWindow } : {}),
              ...(current.localReasoningMode ? { local_reasoning_mode: current.localReasoningMode } : {}),
              selected_tool_names: current.selectedToolNames,
              tool_profile_id: current.toolProfileId,
              snapshot_id: current.snapshotId,
            }),
          })
          submittedRunId = runRecord.id
          const toolLabelsByName = Object.fromEntries(toolLabelsRef.current.map((tool) => [tool.name, tool.label]))
          let liveSteps: RunActivityStep[] = []
          let retryCount = 0
          let writingResponse = false
          const setLiveActivity = (status: string | null, nextSteps = liveSteps): void => {
            liveSteps = nextSteps.slice(-64)
            setActivityView({ runId: runRecord.id, status, steps: liveSteps })
            onActivityChangeRef.current?.(status)
          }
          setLiveActivity('Queued', [])

          const abortHandler = (): void => {
            const isExplicitStop = (options.abortSignal.reason as { detach?: boolean } | undefined)?.detach !== true
            if (isExplicitStop) {
              void requestJson(API_ENDPOINTS.cortexRunCancel(runRecord.id), { method: 'POST' }).catch(() => undefined)
            }
          }

          if (options.abortSignal.aborted) {
            abortHandler()
          } else {
            options.abortSignal.addEventListener('abort', abortHandler, { once: true })
          }

          let cumulativeAnswer = ''
          let lastYieldedAnswer = ''
          let lastYieldTime = 0
          const streamObservation = { error: null as Error | null }
          const STREAM_YIELD_INTERVAL_MS = 32
          const streamingMetadata = { custom: { apex: { agent_used: { key: current.agent } } } }

          try {
            for await (const event of streamRunEvents(runRecord.id, {
              signal: options.abortSignal,
              onExhausted: (error) => { streamObservation.error = error },
            })) {
              if (event.type === 'run.snapshot') {
                liveSteps = safeActivitySteps(event.payload?.activity_steps)
                const last = liveSteps.at(-1)
                const run = event.payload?.run as { status?: string } | undefined
                retryCount = Math.max(0, ...liveSteps.filter((step) => step.type === 'retry.updated').map((step) => Number(step.payload.retries_count) || 0))
                const answer = typeof event.payload?.answer === 'string' ? event.payload.answer : ''
                writingResponse = liveSteps.some((step) => step.type === 'response.started')
                const label = last ? activityStepLabel(last, toolLabelsByName) : run?.status === 'running' ? 'Preparing request' : 'Queued'
                setLiveActivity(label, liveSteps)
                cumulativeAnswer = answer
                if (cumulativeAnswer !== lastYieldedAnswer) {
                  lastYieldedAnswer = cumulativeAnswer
                  lastYieldTime = typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now()
                  yield { content: [{ type: 'text' as const, text: cumulativeAnswer }], metadata: streamingMetadata }
                }
              } else if (event.type === 'response.delta') {
                if (!writingResponse) {
                  writingResponse = true
                  const step: RunActivityStep = { sequence: event.sequence, timestamp: event.timestamp, type: 'response.started', payload: {} }
                  setLiveActivity('Writing response', [...liveSteps, step])
                }
                const text = typeof event.payload?.text === 'string' ? event.payload.text : ''
                cumulativeAnswer += text
                const now = typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now()
                if (now - lastYieldTime >= STREAM_YIELD_INTERVAL_MS) {
                  lastYieldTime = now
                  lastYieldedAnswer = cumulativeAnswer
                  yield {
                    content: [{ type: 'text' as const, text: cumulativeAnswer }],
                    metadata: streamingMetadata,
                  }
                }
              } else if (event.type === 'response.reset') {
                writingResponse = false
                const provisionalIndex = liveSteps.map((step) => step.type).lastIndexOf('response.started')
                if (provisionalIndex >= 0) liveSteps = liveSteps.filter((_, index) => index !== provisionalIndex)
                const previous = liveSteps.at(-1)
                setLiveActivity(previous ? activityStepLabel(previous, toolLabelsByName) : 'Preparing request', liveSteps)
                cumulativeAnswer = ''
                lastYieldedAnswer = ''
                lastYieldTime = 0
                yield {
                  content: [{ type: 'text' as const, text: '' }],
                  metadata: streamingMetadata,
                }
              } else if (event.type === 'response.completed') {
                if (!writingResponse) {
                  writingResponse = true
                  const step: RunActivityStep = { sequence: event.sequence, timestamp: event.timestamp, type: 'response.started', payload: {} }
                  setLiveActivity('Writing response', [...liveSteps, step])
                }
                const answer = typeof event.payload?.answer === 'string' ? event.payload.answer : ''
                cumulativeAnswer = answer
                lastYieldedAnswer = cumulativeAnswer
                lastYieldTime = typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now()
                yield {
                  content: [{ type: 'text' as const, text: cumulativeAnswer }],
                  metadata: streamingMetadata,
                }
              } else {
                const step = activityStepFromEvent(event)
                if (step) {
                  if (step.type === 'retry.updated' && typeof step.payload.retries_count === 'number' && step.payload.retries_count <= retryCount) {
                    // Retry counters are also repeated in routine usage updates.
                  } else {
                    if (step.type === 'retry.updated' && typeof step.payload.retries_count === 'number') retryCount = step.payload.retries_count
                    setLiveActivity(activityStepLabel(step, toolLabelsByName), [...liveSteps, step])
                  }
                }
                if (event.type === 'run.status') {
                  const status = event.payload?.status
                  if (status === 'running' && liveSteps.length === 0) setLiveActivity('Preparing request')
                }
                if (event.type === 'run.completed') {
                  const status = event.payload?.status
                  const terminal = { sequence: event.sequence, timestamp: event.timestamp, type: 'run.completed' as const, payload: { status } }
                  setLiveActivity(status === 'completed' ? 'Completed' : status === 'cancelled' ? 'Cancelled' : 'Stopped', [...liveSteps, terminal])
                }
                if (cumulativeAnswer !== lastYieldedAnswer) {
                  lastYieldedAnswer = cumulativeAnswer
                  lastYieldTime = typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now()
                  yield { content: [{ type: 'text' as const, text: cumulativeAnswer }], metadata: streamingMetadata }
                }
              }
            }
          } finally {
            options.abortSignal.removeEventListener('abort', abortHandler)
          }

          if (cumulativeAnswer !== lastYieldedAnswer) {
            lastYieldedAnswer = cumulativeAnswer
            yield {
              content: [{ type: 'text' as const, text: cumulativeAnswer }],
              metadata: streamingMetadata,
            }
          }

          let durableMessage: ConversationMessage | undefined
          try {
            const detail = await requestJson<ConversationDetail>(API_ENDPOINTS.cortexConversation(remoteId))
            durableMessage = detail.messages.find((m) => m.id === agentMessageId)
          } catch {
            // Fallback to accumulated text if durable conversation fetch is interrupted
          }

          const streamObservationError = streamObservation.error
          const responseStatus = durableMessage?.status ?? (
            options.abortSignal.aborted || streamObservationError ? 'interrupted' : 'completed'
          )
          const finalAnswer = durableMessage
            ? responseStatus === 'pending' ? (cumulativeAnswer || durableMessage.content) : durableMessage.content
            : cumulativeAnswer
          const rawMetadata = (durableMessage?.response_metadata ?? {}) as Record<string, unknown>
          const metadata: Record<string, unknown> = {
            agent_used: { key: current.agent },
            ...rawMetadata,
            ...(streamObservationError ? {
              stream_observation: 'lost',
              stream_error: streamObservationError.message,
            } : {}),
          }
          const responseError = typeof metadata.error === 'string' ? metadata.error : null
          const awaitingDurableCompletion = responseStatus === 'pending'
          if (awaitingDurableCompletion) {
            pendingAssistantRef.current = { conversationId: remoteId, messageId: agentMessageId, content: finalAnswer }
            handlePendingChange(remoteId, current.agent, true)
          } else if (pendingAssistantRef.current?.conversationId === remoteId && pendingAssistantRef.current.messageId === agentMessageId) {
            pendingAssistantRef.current = null
          }
          const incomplete = responseError !== null || responseStatus === 'failed' || responseStatus === 'interrupted'
          const persistedError = responseError ?? (responseStatus !== 'completed' ? responseStatus : 'Agent turn did not complete.')

          const observationError = streamObservationError
            ? `Live run stream disconnected: ${streamObservationError.message}`
            : null
          onResponseChangeRef.current?.(metadata, responseError ?? observationError ?? (incomplete ? persistedError : null))

          yield {
            content: [{ type: 'text' as const, text: finalAnswer }],
            ...(awaitingDurableCompletion ? {} : incomplete ? { status: { type: 'incomplete' as const, reason: 'error' as const, error: persistedError } } : {}),
            metadata: { custom: { apex: metadata } },
          }
          return
        } catch (error) {
          const message = error instanceof Error ? error.message : 'APEX request failed.'
          onResponseChangeRef.current?.(null, message)
          setActivityView({ runId: null, status: null, steps: [] })
          onActivityChangeRef.current?.(null)
          throw error
        } finally {
          finishTurn()
          if (submittedRunId) {
            setActivityView((view) => view.runId === submittedRunId ? { ...view, status: null } : view)
            onActivityChangeRef.current?.(null)
          }
        }
      },
    }
    // assistant-ui invokes this callback as a hook host for each active thread.
    // eslint-disable-next-line react-hooks/rules-of-hooks
    return useLocalRuntime(model, { maxSteps: 1 })
  }, [finishTurn, getThreadIds, handlePendingChange, syncTurnLock])

  const handleThreadIdChange = useCallback((nextThreadId: string | undefined): void => {
    activeRemoteIdRef.current = nextThreadId
    setBranchPersistenceError(null)
    if (!nextThreadId) onConversationChangeRef.current?.(null)
  }, [onConversationChangeRef])
  const runtime = useRemoteThreadListRuntime({ runtimeHook, adapter, onThreadIdChange: handleThreadIdChange })
  useEffect(() => {
    runtimeRefInternal.current = runtime
  }, [runtime])
  useEffect(() => {
    const pending = pendingTurnRef.current
    if (!pending) return
    let cancelled = false
    const poll = async (): Promise<void> => {
      try {
        forceHistoryReloadRef.current = true
        await runtime.threads.reloadMainThread()
      } catch {
        // Retain the lock while an authoritative pending turn cannot be read.
      }
      if (!cancelled && pendingTurnRef.current) window.setTimeout(() => { void poll() }, 1_500)
    }
    const timeout = window.setTimeout(() => { void poll() }, 1_500)
    return () => { cancelled = true; window.clearTimeout(timeout) }
  }, [isTurnLocked, pendingTurnRevision, runtime])
  const reloadThreads = useCallback(async (): Promise<void> => {
    forceListReloadRef.current = true
    await runtime.threads.reload()
  }, [runtime])
  const markPreflightPassed = useCallback(() => { preflightPassedRef.current = true }, [])
  const setPendingPrompt = useCallback((text: string) => {
    pendingPromptRef.current = text
  }, [])
  const runBefore = useCallback(async (runConfig: ApexAssistantRunConfig): Promise<boolean> => {
    return beforeRunRef.current ? beforeRunRef.current(runConfig) : true
  }, [])
  const composerContext = useMemo(() => ({ configRef, setPendingPrompt, setTurnOverrides, beforeRun: runBefore, markPreflightPassed, isTurnLocked, beginTurn, finishTurn }), [beginTurn, finishTurn, isTurnLocked, markPreflightPassed, runBefore, setPendingPrompt, setTurnOverrides])
  const runtimeContext = useMemo(() => ({
    ...composerContext,
    persistActiveLeaf: (messageId: string) => branchPersistRef.current(messageId),
    clearBranchPersistenceError: () => setBranchPersistenceError(null),
    branchPersistenceError,
    reloadThreads,
    threadListError,
  }), [branchPersistenceError, composerContext, reloadThreads, threadListError])
  return <AssistantToolLabelsContext.Provider value={toolLabels}><AssistantActivityContext.Provider value={activityView}><AssistantRuntimeProvider runtime={runtime}><ApexAssistantComposerContext.Provider value={runtimeContext}><ApexAssistantController branchPersistRef={branchPersistRef} forceHistoryReloadRef={forceHistoryReloadRef} getActiveRemoteId={getActiveRemoteId} getThreadIds={getThreadIds} onBranchPersistenceError={setBranchPersistenceError} prepareConversationForOpen={prepareConversationForOpen} runtimeRef={runtimeRef} />{children}</ApexAssistantComposerContext.Provider></AssistantRuntimeProvider></AssistantActivityContext.Provider></AssistantToolLabelsContext.Provider>
}

export function ApexAssistantError(): ReactNode {
  const apex = useAuiState((state) => state.message.metadata.custom?.apex as Record<string, unknown> | undefined)
  return typeof apex?.error === 'string' ? <p className="mt-2 text-xs text-red-300" role="alert">{apex.error}</p> : null
}

function GatedComposer({
  disabled = false,
  edit = false,
  composer,
}: {
  disabled?: boolean
  edit?: boolean
  composer?: ApexAssistantComposerProps
}): ReactNode {
  const aui = useAui()
  const context = useContext(ApexAssistantComposerContext)
  const { submit } = useApexAssistantComposer(edit ? aui.composer : undefined)
  const queryActive = useAuiState((state) => state.thread.isRunning)
  const threadLoading = useAuiState((state) => state.thread.isLoading)
  const error = composer?.error ?? null
  const handleSubmit = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    void submit()
  }
  const blocked = disabled || Boolean(composer?.disabled) || threadLoading || Boolean(context?.isTurnLocked)
  const briefingComposer = !edit && composer?.integrated
  return <ComposerPrimitive.Root onSubmit={handleSubmit} className="relative border-t border-white/10 bg-black/20 p-3 sm:p-4">
    {!edit && composer && queryActive ? <CortexQueryRim /> : null}
    {briefingComposer ? <div className="briefing-composer-container min-w-0">
      <div data-slot="briefing-query-composer" className="briefing-composer-shell min-h-[46px] gap-1.5 rounded-3xl border border-white/15 bg-zinc-900/60 px-2.5 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] transition-colors focus-within:border-[#0F4DB8]/70 focus-within:bg-zinc-900/80">
      <div className="briefing-composer-tools flex items-center"><ToolsSelector {...composer.tools} compact className="size-9 rounded-full" align="left" portal disabled={blocked || queryActive} /></div>
      <ComposerPrimitive.Input disabled={blocked || queryActive} placeholder="Add a follow up" className="briefing-composer-query min-h-9 min-w-0 bg-transparent px-1 py-2 text-sm text-zinc-100 outline-none placeholder:text-zinc-500 focus:ring-0 disabled:cursor-not-allowed disabled:opacity-45" />
      {composer.selectedModelId && composer.onModelChange && composer.modelCatalog ? <div className="briefing-composer-model min-w-0"><CompactModelSelector
        selectedModelId={composer.selectedModelId}
        onModelChange={composer.onModelChange}
        catalog={composer.modelCatalog}
        cloudEffort={composer.cloudEffort}
        onEffortChange={composer.onEffortChange}
        localReasoningMode={composer.localReasoningMode}
        onLocalReasoningModeChange={composer.onLocalReasoningModeChange}
        disabled={blocked || queryActive}
        isQuerying={queryActive || Boolean(context?.isTurnLocked)}
        presentation="composer"
      /></div> : null}
      <div className="briefing-composer-send">{queryActive ? <button type="button" onClick={() => aui.thread.cancelRun()} className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-red-500/10 text-red-200 hover:bg-red-500/20" aria-label="Stop generation"><Square className="size-3.5 fill-current" aria-hidden /></button> : <ComposerPrimitive.Send
        disabled={blocked || queryActive}
        onClick={(event) => { event.preventDefault(); void submit() }}
        className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-[#7E22CE]/20 text-[#D8B4FE] transition-colors hover:bg-[#7E22CE]/35 disabled:cursor-not-allowed disabled:opacity-45"
        aria-label="Send"
      ><Send className="size-4" aria-hidden /></ComposerPrimitive.Send>}</div>
      </div>
    </div> : <div className="flex items-end gap-2">
      {!edit && composer ? (
        <ToolsSelector
          {...composer.tools}
          compact
          className="size-11 rounded-lg"
          align="left"
          disabled={blocked || queryActive}
        />
      ) : null}
      <ComposerPrimitive.Input disabled={blocked} placeholder={edit ? 'Edit message…' : `Ask ${composer?.activeAgentName?.trim() || 'Lynx'}…`} className="min-h-11 flex-1 resize-none rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none placeholder:text-zinc-600 transition-[border-color,box-shadow] duration-300 focus:border-[#0F4DB8]/70 focus:shadow-[0_0_16px_rgba(15,77,184,0.24)] disabled:cursor-not-allowed disabled:opacity-45" />
      {edit ? <ComposerPrimitive.Cancel disabled={blocked} className="h-11 rounded-lg border border-white/10 px-3 py-2 font-mono text-xs text-zinc-400 hover:text-white disabled:opacity-45">Cancel</ComposerPrimitive.Cancel> : null}
      {!edit && queryActive ? (
        <button
          type="button"
          onClick={() => aui.thread.cancelRun()}
          className="inline-flex size-11 shrink-0 items-center justify-center rounded-lg border border-red-500/40 bg-red-950/25 text-red-200 transition-colors hover:bg-red-950/40"
          aria-label="Stop generation"
        >
          <Square className="size-3.5 fill-current" aria-hidden />
        </button>
      ) : (
        <ComposerPrimitive.Send
          disabled={blocked || queryActive}
          onClick={(event) => { event.preventDefault(); void submit() }}
          className={edit
            ? 'h-11 rounded-lg border border-[#7E22CE]/45 bg-[#7E22CE]/15 px-3 py-2 font-mono text-xs uppercase tracking-wider text-[#D8B4FE] hover:bg-[#7E22CE]/25 disabled:cursor-not-allowed disabled:opacity-45'
            : 'inline-flex size-11 shrink-0 items-center justify-center rounded-lg border border-[#7E22CE]/45 bg-[#7E22CE]/15 text-[#D8B4FE] transition-colors hover:bg-[#7E22CE]/25 disabled:cursor-not-allowed disabled:opacity-45'}
          aria-label={edit ? 'Save' : 'Send'}
        >
          {edit ? 'Save' : <Send className="size-4" aria-hidden />}
        </ComposerPrimitive.Send>
      )}
    </div>}
    {!edit && composer && error ? <CortexErrorFeedback error={error} /> : null}
  </ComposerPrimitive.Root>
}

const ApexAssistantPresentationContext = createContext<{
  renderAgent?: (text: string, metadata: Record<string, unknown>) => ReactNode
  composer?: ApexAssistantComposerProps
}>({})

function ApexAssistantMessage(): ReactNode {
  const messageRef = useRef<HTMLDivElement>(null)
  const aui = useAui()
  const { renderAgent, composer } = useContext(ApexAssistantPresentationContext)
  const toolLabels = useContext(AssistantToolLabelsContext)
  const context = useContext(ApexAssistantComposerContext)
  const role = useAuiState((state) => state.message.role)
  const isLast = useAuiState((state) => state.message.isLast)
  const content = useAuiState((state) => state.message.content)
  const status = useAuiState((state) => state.message.status)
  const branchCount = useAuiState((state) => state.message.branchCount)
  const branchNumber = useAuiState((state) => state.message.branchNumber)
  const editing = useAuiState((state) => state.composer.isEditing)
  const metadata = useAuiState((state) => state.message.metadata.custom?.apex as Record<string, unknown> | undefined) ?? {}
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle')
  const [copyError, setCopyError] = useState<string | null>(null)
  const text = content
    .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
    .map((part) => part.text)
    .join('\n')

  const copyMessage = async (): Promise<void> => {
    setCopyState('idle')
    setCopyError(null)
    try {
      await writeClipboardText(text)
      setCopyState('copied')
      setCopyError(null)
    } catch (error) {
      setCopyState('error')
      setCopyError(error instanceof Error ? error.message : 'Clipboard is unavailable.')
    }
  }

  const hasScrolledRef = useRef(false)
  useEffect(() => {
    if (role === 'assistant' && isLast && !hasScrolledRef.current) {
      hasScrolledRef.current = true
      const target = messageRef.current
      const viewport = target?.closest<HTMLElement>('[data-cortex-thread-viewport]')
      if (!target || !viewport || viewport.scrollHeight <= viewport.clientHeight) return
      const targetTop = target.getBoundingClientRect().top - viewport.getBoundingClientRect().top + viewport.scrollTop
      viewport.scrollTo({ behavior: 'smooth', top: targetTop })
    }
  }, [role, isLast])

  const selectBranch = (position: 'previous' | 'next'): void => {
    if (context?.isTurnLocked) return
    context?.clearBranchPersistenceError()
    aui.message().switchToBranch({ position })
    queueMicrotask(() => {
      const selectedId = aui.thread().getState().messages.at(-1)?.id
      if (!selectedId || !context) return
      void context.persistActiveLeaf(selectedId).catch(() => undefined)
    })
  }
  if (status?.type === 'running' && !text) return null
  return <MessagePrimitive.Root ref={messageRef} className={role === 'user' ? 'flex justify-end' : 'max-w-5xl'}>
    {editing && role === 'user' ? <GatedComposer edit disabled={Boolean(composer?.disabled) || Boolean(context?.isTurnLocked)} /> : null}
    {editing && role === 'user' ? null : <>
    <div className={role === 'user'
      ? 'max-w-[85%] rounded-2xl rounded-br-md border border-[#0F4DB8]/35 bg-[#0F4DB8]/15 px-4 py-3 text-sm text-white'
      : 'rounded-2xl rounded-bl-md border border-white/10 bg-zinc-900/80 px-4 py-3 text-sm leading-relaxed text-zinc-200'}>
      {role === 'assistant' ? renderAgent?.(text, metadata) ?? <DeferredPresentation
        load={loadAssistantMarkdown}
        componentProps={{ text }}
        fallback={<div className="whitespace-pre-wrap break-words">{text}</div>}
        renderError={(retry) => <div className="whitespace-pre-wrap break-words">{text}<button type="button" onClick={retry} className="ml-2 font-mono text-[10px] text-[#9AC2FF] underline underline-offset-2 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF]">Retry formatting</button></div>}
      /> : text}
      {role === 'assistant' ? <ActivityTimeline steps={metadata.activity_steps} toolLabels={toolLabels} collapsed /> : null}
      {role === 'assistant' && status?.type === 'incomplete' ? <ApexAssistantError /> : null}
      <div className="mt-2 flex items-center gap-2 font-mono text-[10px] text-zinc-500">
        <button type="button" onClick={() => void copyMessage()} className="hover:text-white">{copyState === 'copied' ? 'Copied' : 'Copy'}</button>
        {copyError ? <span role="alert" className="text-red-300">Copy failed: {copyError}</span> : null}
        {copyState === 'copied' ? <span role="status" className="sr-only">Message copied.</span> : null}
        {role === 'user' ? <button type="button" disabled={context?.isTurnLocked} onClick={() => aui.message().composer().beginEdit()} className="hover:text-white disabled:cursor-not-allowed disabled:opacity-40">Edit</button> : <button type="button" disabled={context?.isTurnLocked} onClick={() => aui.message().reload()} className="hover:text-white disabled:cursor-not-allowed disabled:opacity-40">Retry</button>}
        {branchCount > 1 ? <><button type="button" aria-label="Previous branch" disabled={context?.isTurnLocked} onClick={() => selectBranch('previous')} className="hover:text-white disabled:cursor-not-allowed disabled:opacity-40">‹</button><span>{branchNumber + 1}/{branchCount}</span><button type="button" aria-label="Next branch" disabled={context?.isTurnLocked} onClick={() => selectBranch('next')} className="hover:text-white disabled:cursor-not-allowed disabled:opacity-40">›</button></> : null}
      </div>
    </div>
    </>}
  </MessagePrimitive.Root>
}

/** APEX-owned presentation built from assistant-ui primitives, not its starter kit. */
export function ApexAssistantThread({ disabled = false, renderAgent, composer, logoProps, activeRunSlot }: { disabled?: boolean; renderAgent?: (text: string, metadata: Record<string, unknown>) => ReactNode; composer?: ApexAssistantComposerProps; logoProps?: Omit<ApexLogoProps, 'className'>; activeRunSlot?: ReactNode }): ReactNode {
  const running = useAuiState((state) => state.thread.isRunning)
  const isEmpty = useAuiState((state) => state.thread.isEmpty)
  const context = useContext(ApexAssistantComposerContext)
  const activity = useApexAssistantActivity()
  const toolLabels = useContext(AssistantToolLabelsContext)
  const presentation = useMemo(() => ({ renderAgent, composer }), [composer, renderAgent])
  const messageComponents = useMemo(() => ({ Message: ApexAssistantMessage }), [])
  return <ApexAssistantPresentationContext.Provider value={presentation}><ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
    <ThreadPrimitive.Viewport data-cortex-thread-viewport="" className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 scrollbar-thin" autoScroll={false}>
      <ThreadPrimitive.Empty><div className="flex min-h-56 flex-col items-center justify-center rounded-xl border border-dashed border-white/10 px-6 py-8 text-center"><p className="font-mono text-xs uppercase tracking-widest text-zinc-500">APEX is ready. Start a session with a focused question.</p><div className="mt-4 flex max-w-xl flex-wrap justify-center gap-2">{OPERATION_PROMPT_CHIPS.map((chip) => <ThreadPrimitive.Suggestion key={chip.label} prompt={chip.query} send={false} className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300 transition-colors hover:border-[#0F4DB8]/50 hover:bg-[#0F4DB8]/15 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF]">{chip.label}</ThreadPrimitive.Suggestion>)}</div>{logoProps ? <div data-slot="cortex-chat-logo" className="mt-6 flex items-center justify-center filter drop-shadow-[0_0_24px_rgba(var(--logo-glow-color),0.45)] transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu hover:filter hover:drop-shadow-[0_0_32px_rgba(var(--logo-glow-color),0.6)]"><ApexLogo {...logoProps} className="size-40 sm:size-48" /></div> : null}</div></ThreadPrimitive.Empty>
      <ThreadPrimitive.Messages components={messageComponents} />
      {running ? <div className="space-y-1" data-run-id={activity.runId ?? undefined}><div className="flex items-center gap-2 font-mono text-xs tracking-wider text-[#D8B4FE]" aria-live="polite"><span className="inline-block size-2 animate-pulse rounded-full bg-[#C084FC] motion-reduce:animate-none" aria-hidden />{activity.status ?? 'Preparing request'}</div>{activeRunSlot}{activity.steps.length ? <ActivityTimeline steps={activity.steps} toolLabels={toolLabels} collapsed /> : null}</div> : null}
      {!isEmpty && logoProps ? <div data-slot="cortex-chat-logo" className="my-8 flex items-center justify-center filter drop-shadow-[0_0_24px_rgba(var(--logo-glow-color),0.45)] transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu hover:filter hover:drop-shadow-[0_0_32px_rgba(var(--logo-glow-color),0.6)]"><ApexLogo {...logoProps} className="size-40 sm:size-48" /></div> : null}
    </ThreadPrimitive.Viewport>
    {context?.branchPersistenceError ? <p className="border-t border-red-500/20 bg-red-950/20 px-4 py-2 text-xs text-red-200" role="alert">{context.branchPersistenceError}</p> : null}
    <GatedComposer disabled={disabled} composer={composer} />
  </ThreadPrimitive.Root></ApexAssistantPresentationContext.Provider>
}

function ApexConversationRailItem(): ReactNode {
  const aui = useAui()
  const context = useContext(ApexAssistantComposerContext)
  const disabled = Boolean(context?.isTurnLocked)
  const renameTriggerRef = useRef<HTMLButtonElement>(null)
  const wasRenaming = useRef(false)
  const [renaming, setRenaming] = useState(false)
  const [title, setTitle] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const archived = useAuiState((state) => state.threadListItem.status === 'archived')
  const currentTitle = useAuiState((state) => state.threadListItem.title ?? 'Untitled conversation')
  useEffect(() => {
    if (!renaming && wasRenaming.current) renameTriggerRef.current?.focus()
    wasRenaming.current = renaming
  }, [renaming])
  const archive = async (): Promise<void> => {
    setActionError(null)
    try {
      if (archived) {
        await aui.threadListItem.unarchive()
        return
      }
      await aui.threadListItem.archive()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Conversation update failed.')
    }
  }
  const deleteConversation = async (): Promise<void> => {
    if (!archived || (globalThis.confirm && !globalThis.confirm('Delete this archived conversation permanently? This cannot be undone.'))) return
    setActionError(null)
    try {
      await aui.threadListItem.delete()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Conversation deletion failed.')
    }
  }
  const rename = async (): Promise<void> => {
    if (!title.trim()) return
    setActionError(null)
    try {
      await aui.threadListItem.rename(title.trim())
      setRenaming(false)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Conversation rename failed.')
    }
  }
  return <ThreadListItemPrimitive.Root className="group relative flex items-center gap-1 rounded-md px-2 py-1.5 transition-colors hover:bg-white/5 data-[active=true]:bg-white/10 data-[active=true]:border-l-2 data-[active=true]:border-[#1F6FE5] data-[active=true]:text-white">
    {renaming ? <input autoFocus disabled={disabled} value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setRenaming(false); if (event.key === 'Enter') void rename() }} className="min-w-0 flex-1 bg-transparent text-xs text-white outline-none" /> : <button type="button" disabled={disabled} onClick={() => aui.threadListItem.switchTo({ unarchive: false })} className="min-w-0 flex-1 truncate text-left font-mono text-xs text-zinc-300 group-data-[active=true]:font-medium group-data-[active=true]:text-white disabled:cursor-not-allowed disabled:opacity-40"><ThreadListItemPrimitive.Title /></button>}
    {!renaming ? <button ref={renameTriggerRef} type="button" disabled={disabled} aria-label={`Rename ${currentTitle}`} onClick={() => { setTitle(currentTitle); setRenaming(true) }} className="text-zinc-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-40 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 group-data-[active=true]:opacity-70 group-data-[active=true]:hover:opacity-100 transition-opacity">✎</button> : null}
    <button type="button" disabled={disabled} onClick={() => void archive()} className="text-[10px] text-zinc-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-40 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 group-data-[active=true]:opacity-70 group-data-[active=true]:hover:opacity-100 transition-opacity">{archived ? 'Restore' : 'Archive'}</button>
    {archived ? <button type="button" disabled={disabled} onClick={() => void deleteConversation()} className="rounded p-0.5 text-zinc-500 hover:text-red-200 disabled:cursor-not-allowed disabled:opacity-40 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 group-data-[active=true]:opacity-70 group-data-[active=true]:hover:opacity-100 transition-opacity" aria-label={`Delete ${currentTitle} permanently`} title="Delete permanently"><Trash2 className="size-3" aria-hidden /></button> : null}
    {actionError ? <span role="alert" className="max-w-28 truncate text-[10px] text-red-300" title={actionError}>{actionError}</span> : null}
  </ThreadListItemPrimitive.Root>
}

export function ApexConversationRail({ className = 'hidden xl:flex', disabled = false, compact = false }: { className?: string; disabled?: boolean; compact?: boolean }): ReactNode {
  const aui = useAui()
  const [archived, setArchived] = useState(false)
  const isLoading = useAuiState((state) => state.threads.isLoading)
  const threadCount = useAuiState((state) => (archived ? state.threads.archivedThreadIds.length : state.threads.threadIds.length))
  const mainThreadId = useAuiState((state) => state.threads.mainThreadId)
  const newThreadId = useAuiState((state) => state.threads.newThreadId)
  const isDraftActive = Boolean(newThreadId && mainThreadId === newThreadId)
  const context = useContext(ApexAssistantComposerContext)
  const interactionDisabled = disabled || Boolean(context?.isTurnLocked)
  const threadListError = context?.threadListError ?? null
  const itemComponents = useMemo(() => ({ ThreadListItem: ApexConversationRailItem }), [])
  return <aside className={`${className} flex min-h-0 ${compact ? 'max-h-[min(60vh,32rem)] w-full' : 'h-full w-full xl:w-56'} shrink-0 flex-col overflow-hidden border-r border-white/10 bg-black/15 p-3`} aria-label="Conversations"><div className="mb-3 flex shrink-0 items-center justify-between"><p className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">Conversations</p><ApexAssistantNewConversation disabled={interactionDisabled} /></div><div className="mb-2 flex shrink-0 gap-2"><button type="button" disabled={interactionDisabled} onClick={() => setArchived(false)} aria-pressed={!archived} className="text-[10px] text-zinc-400 hover:text-white disabled:opacity-40">Active</button><button type="button" disabled={interactionDisabled} onClick={() => setArchived(true)} aria-pressed={archived} className="text-[10px] text-zinc-400 hover:text-white disabled:opacity-40">Archived</button></div><div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">{isLoading ? <p className="px-2 py-4 text-xs text-zinc-500" role="status">Loading conversations…</p> : threadListError ? <div className="space-y-2 px-2 py-4"><p className="text-xs text-red-300" role="alert">{threadListError}</p><button type="button" disabled={interactionDisabled} onClick={() => void (context?.reloadThreads() ?? aui.threads.reload())} className="text-[10px] text-[#7EB3FF] hover:text-white disabled:opacity-40">Retry</button></div> : (!archived && isDraftActive) || threadCount > 0 ? <div className="space-y-0.5">{!archived && isDraftActive ? <div data-active="true" className="group relative flex items-center gap-1 rounded-md px-2 py-1.5 transition-colors bg-white/10 border-l-2 border-[#1F6FE5] text-white"><span className="min-w-0 flex-1 truncate text-left font-mono text-xs font-medium text-white">New conversation</span></div> : null}<ThreadListPrimitive.Root><ThreadListPrimitive.Items archived={archived} components={itemComponents} /></ThreadListPrimitive.Root></div> : <div className="space-y-2 px-2 py-4"><p className="text-xs text-zinc-500">No {archived ? 'archived' : 'active'} conversations.</p></div>}</div></aside>
}

export function ApexAssistantNewConversation({ disabled = false }: { disabled?: boolean }): ReactNode {
  const aui = useAui()
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const create = async (): Promise<void> => {
    if (disabled || creating) return
    setCreating(true)
    setCreateError(null)
    try {
      await aui.threads.switchToNewThread()
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : 'Conversation creation failed.')
    } finally {
      setCreating(false)
    }
  }
  return <span className="inline-flex items-center gap-2"><button type="button" disabled={disabled || creating} aria-busy={creating} onClick={() => void create()} className="inline-flex items-center gap-1.5 rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300 hover:border-[#7EB3FF]/50 hover:bg-[#0F4DB8]/15 hover:text-white disabled:opacity-40">
    {creating ? 'Creating…' : 'New conversation'}
  </button>{createError ? <span role="alert" className="max-w-32 truncate text-[10px] text-red-300" title={createError}>{createError}</span> : null}</span>
}
