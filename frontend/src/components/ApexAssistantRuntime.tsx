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

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { createAssistantStream } from 'assistant-stream'

import { API_ENDPOINTS } from '../lib/api'
import type { AgentKey, CloudEffort } from '../types/telemetry'
import { AgentMark } from './AgentMark'
import { CortexErrorFeedback, CortexQueryRim } from './AgentQueryBar'
import { ToolsSelector, type ToolsSelectorProps } from './ToolsSelector'
import { OPERATION_PROMPT_CHIPS } from '../lib/promptChips'
import { Trash2 } from 'lucide-react'

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
  submitPrompt: (prompt: string) => Promise<boolean>
  patchPreferences: (updates: { agent?: AgentKey; selectedToolNames?: string[] | null; toolProfileId?: string | null }) => Promise<ApexAssistantPatchedPreferences | null>
}

export type ApexAssistantPatchedPreferences = ApexAssistantConversationPreferences & {
  conversationId: string
}

export type ApexAssistantRunConfig = {
  agent: AgentKey
  effort: CloudEffort | null
  selectedToolNames: string[]
  toolProfileId: string | null
  snapshotId: string | null
  briefingId?: number | null
}

export type ApexAssistantComposerProps = {
  activeAgent: AgentKey
  activeAgentName: string
  tools: ToolsSelectorProps
  error?: string | null
  disabled?: boolean
}

type Props = {
  config: ApexAssistantRunConfig
  children: ReactNode
  beforeRun?: (config: ApexAssistantRunConfig) => Promise<boolean>
  onConversationChange?: (conversation: ConversationSummary | null) => void
  onRunningChange?: (running: boolean, agent: AgentKey | null) => void
  onResponseChange?: (response: Record<string, unknown> | null, error: string | null) => void
  runtimeRef?: React.MutableRefObject<ApexAssistantRuntimeHandle | null>
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

function ThreadHistory({ children, getThreadIds, onConversationChangeRef, historyLoadStateRef, forceHistoryReloadRef }: { children?: ReactNode; getThreadIds: (remoteId: string) => Map<string, string>; onConversationChangeRef: React.MutableRefObject<((conversation: ConversationSummary | null) => void) | undefined>; historyLoadStateRef: React.MutableRefObject<HistoryLoadState>; forceHistoryReloadRef: React.MutableRefObject<boolean> }): ReactNode {
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
          // A reload is authoritative: loaded backend UUIDs supersede any opaque
          // assistant-ui IDs that were generated during the previous local run.
          getThreadIds(remoteId).clear()
          historyLoadStateRef.current.failureUntil.delete(remoteId)
          return ExportedMessageRepository.fromBranchableArray(
            detail.messages.map((message) => ({
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
                    content: [{ type: 'text' as const, text: message.content }],
                    createdAt: new Date(message.created_at),
                    status: message.status === 'completed'
                      ? { type: 'complete' as const, reason: 'stop' as const }
                      : message.status === 'pending'
                        ? { type: 'running' as const }
                        : { type: 'incomplete' as const, reason: 'error' as const, error: String(message.response_metadata?.error ?? message.status) },
                    metadata: { custom: { apex: message.response_metadata ?? {} } },
                  },
            })),
            { headId: detail.active_leaf_message_id },
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
  }), [aui, forceHistoryReloadRef, getThreadIds, historyLoadStateRef, onConversationChangeRef])
  return <RuntimeAdapterProvider adapters={{ history }}>{children}</RuntimeAdapterProvider>
}

type ApexAssistantComposerContextValue = {
  configRef: React.MutableRefObject<ApexAssistantRunConfig>
  beforeRun?: (config: ApexAssistantRunConfig) => Promise<boolean>
  markPreflightPassed: () => void
  persistActiveLeaf: (messageId: string) => Promise<void>
  clearBranchPersistenceError: () => void
  branchPersistenceError: string | null
  reloadThreads: () => Promise<void>
  threadListError: string | null
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
  submit: () => Promise<boolean>
  isRunning: boolean
} {
  const aui = useAui()
  const context = useContext(ApexAssistantComposerContext)
  const beforeRun = context?.beforeRun
  const configRef = context?.configRef
  const markPreflightPassed = context?.markPreflightPassed
  const isRunning = useAuiState((state) => state.thread.isRunning)
  const isLoading = useAuiState((state) => state.thread.isLoading)
  if (!context) throw new Error('useApexAssistantComposer must be used inside ApexAssistantRuntime.')
  const composer = composerOverride ?? aui.composer
  const submit = useCallback(async (): Promise<boolean> => {
    const text = composer.getState().text.trim()
    if (!text || isRunning || isLoading) return false
    if (beforeRun && configRef && !await beforeRun(configRef.current)) return false
    if (!aui.threadListItem.getState().remoteId) {
      try {
        await aui.threadListItem.initialize()
      } catch {
        return false
      }
    }
    markPreflightPassed?.()
    composer.send()
    return true
  }, [aui, beforeRun, composer, configRef, isLoading, isRunning, markPreflightPassed])
  return { submit, isRunning }
}

function ApexAssistantController({ runtimeRef, branchPersistRef, getActiveRemoteId, getThreadIds, forceHistoryReloadRef, onBranchPersistenceError }: { runtimeRef?: React.MutableRefObject<ApexAssistantRuntimeHandle | null>; branchPersistRef: React.MutableRefObject<(messageId: string) => Promise<void>>; getActiveRemoteId: () => string | undefined; getThreadIds: (remoteId: string) => Map<string, string>; forceHistoryReloadRef: React.MutableRefObject<boolean>; onBranchPersistenceError: (message: string | null) => void }): ReactNode {
  const aui = useAui()
  const { submit } = useApexAssistantComposer()
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
      submitPrompt: async (prompt: string): Promise<boolean> => {
        const text = prompt.trim()
        if (!text) return false
        if (aui.thread().getState().isLoading) return false
        aui.thread.composer().setText(text)
        return submit()
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
    }
    return () => { runtimeRef.current = null; branchPersistRef.current = async () => {} }
  }, [aui, branchPersistRef, getActiveRemoteId, onBranchPersistenceError, persistBranch, runtimeRef, submit])
  return null
}

export function ApexAssistantRuntime({ config, children, beforeRun, onConversationChange, onRunningChange, onResponseChange, runtimeRef }: Props): ReactNode {
  const configRef = useRef(config)
  const beforeRunRef = useRef(beforeRun)
  const onConversationChangeRef = useRef(onConversationChange)
  const onRunningChangeRef = useRef(onRunningChange)
  const onResponseChangeRef = useRef(onResponseChange)
  // Host callbacks are intentionally read through refs so App polling and
  // diagnostics updates cannot recreate assistant-ui's remote adapter.
  useEffect(() => {
    configRef.current = config
  }, [config])
  useEffect(() => {
    beforeRunRef.current = beforeRun
    onConversationChangeRef.current = onConversationChange
    onRunningChangeRef.current = onRunningChange
    onResponseChangeRef.current = onResponseChange
  }, [beforeRun, onConversationChange, onRunningChange, onResponseChange])
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
  const preflightPassedRef = useRef(false)
  const branchPersistRef = useRef<(messageId: string) => Promise<void>>(async () => {})
  const [threadListError, setThreadListError] = useState<string | null>(null)
  const [branchPersistenceError, setBranchPersistenceError] = useState<string | null>(null)
  const [threadId, setThreadId] = useState<string | undefined>()
  const threadIdRef = useRef(threadId)
  const activeRemoteIdRef = useRef<string | undefined>(threadId)
  const getActiveRemoteId = useCallback(() => activeRemoteIdRef.current, [])
  useEffect(() => {
    threadIdRef.current = threadId
    activeRemoteIdRef.current = threadId
  }, [threadId])
  const forceListReloadRef = useRef(false)
  // The remote runtime treats adapter identity changes as a reload signal.
  // Keep request state outside the adapter closure so transient failures cannot
  // turn host re-renders into a request storm.
  const listRequestRef = useRef<Promise<ApexThreadListResult> | null>(null)
  const listCacheRef = useRef<ApexThreadListResult | null>(null)
  const listFailureRef = useRef<{ error: Error; until: number } | null>(null)
  const historyLoadStateRef = useRef<HistoryLoadState>({ inFlight: new Map(), failureUntil: new Map() })
  const forceHistoryReloadRef = useRef(false)

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
          if (initialRegular[0]) setThreadId((current) => current ?? initialRegular[0].id)
          const result: ApexThreadListResult = { threads: [...initialRegular, ...archived].map((item) => ({
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
      const current = configRef.current
      const item = await requestJson<ConversationSummary>(API_ENDPOINTS.cortexConversations, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ origin: 'hud', agent: current.agent, selected_tool_names: current.selectedToolNames, tool_profile_id: current.toolProfileId }),
      })
      remoteByLocal.current.set(localId, item.id)
      activeRemoteIdRef.current = item.id
      setThreadId(item.id)
      listCacheRef.current = null
      listFailureRef.current = null
      forceListReloadRef.current = true
      onConversationChangeRef.current?.(item)
      return { remoteId: item.id }
    },
    async rename(remoteId, title) {
      await requestJson(API_ENDPOINTS.cortexConversation(remoteId), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) })
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
      listCacheRef.current = null
      forceListReloadRef.current = true
    },
    // assistant-ui may request title generation after a run. APEX titles are
    // operator-controlled, so this intentionally remains a no-op rather than
    // surfacing an unsupported automatic-title failure.
    async generateTitle() { return createAssistantStream(() => {}) },
    async fetch(remoteId) {
      const item = await requestJson<ConversationSummary>(API_ENDPOINTS.cortexConversation(remoteId))
      onConversationChangeRef.current?.(item)
      return { remoteId: item.id, status: item.archived_at ? 'archived' : 'regular', title: item.title, lastMessageAt: new Date(item.updated_at), custom: item }
    },
    unstable_Provider: ({ children }: { children?: ReactNode }) => <ThreadHistory forceHistoryReloadRef={forceHistoryReloadRef} getThreadIds={getThreadIds} historyLoadStateRef={historyLoadStateRef} onConversationChangeRef={onConversationChangeRef}>{children}</ThreadHistory>,
  }), [getThreadIds, onConversationChangeRef])

  const runtimeHook = useCallback(() => {
    const model: ChatModelAdapter = {
      async run(options) {
        const localThreadId = options.unstable_threadId
        const remoteId = (localThreadId ? remoteByLocal.current.get(localThreadId) : undefined) ?? threadIdRef.current ?? activeRemoteIdRef.current
        const user = options.messages.at(-1)
        if (!remoteId || !user || user.role !== 'user' || !options.unstable_assistantMessageId) throw new Error('Conversation is not ready.')
        const current = configRef.current
        if (beforeRunRef.current && !preflightPassedRef.current && !await beforeRunRef.current(current)) throw new Error('This request did not pass APEX preflight.')
        preflightPassedRef.current = false
        onRunningChangeRef.current?.(true, current.agent)
        try {
          const response = await requestJson<Record<string, unknown>>(API_ENDPOINTS.cortexConversationTurns(remoteId), {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              prompt: user.content.filter((part) => part.type === 'text').map((part) => part.text).join('\n'),
              user_message_id: canonicalId(user.id, getThreadIds(remoteId)),
              agent_message_id: canonicalId(options.unstable_assistantMessageId, getThreadIds(remoteId)),
              ...(options.messages.at(-2)?.id
                ? { parent_message_id: canonicalId(options.messages.at(-2)!.id, getThreadIds(remoteId)) }
                : {}),
              agent: current.agent, effort: current.effort, selected_tool_names: current.selectedToolNames,
              tool_profile_id: current.toolProfileId, snapshot_id: current.snapshotId, briefing_id: current.briefingId ?? undefined,
            }),
          })
          const responseError = typeof response.error === 'string' ? response.error : null
          const responseStatus = response.message_status ?? response.status
          const incomplete = responseError !== null || responseStatus === 'failed' || responseStatus === 'interrupted'
          const persistedError = responseError ?? (typeof responseStatus === 'string' ? responseStatus : 'Agent turn did not complete.')
          onResponseChangeRef.current?.(response, incomplete ? persistedError : null)
          return {
            content: [{ type: 'text' as const, text: String(response.answer ?? '') }],
            ...(incomplete ? { status: { type: 'incomplete' as const, reason: 'error' as const, error: persistedError } } : {}),
            metadata: { custom: { apex: response } },
          }
        } catch (error) {
          const message = error instanceof Error ? error.message : 'APEX request failed.'
          onResponseChangeRef.current?.(null, message)
          throw error
        } finally { onRunningChangeRef.current?.(false, null) }
      },
    }
    // assistant-ui invokes this callback as a hook host for each active thread.
    // eslint-disable-next-line react-hooks/rules-of-hooks
    return useLocalRuntime(model, { maxSteps: 1 })
  }, [getThreadIds])

  const handleThreadIdChange = useCallback((nextThreadId: string | undefined): void => {
    setThreadId(nextThreadId)
    activeRemoteIdRef.current = nextThreadId
    setBranchPersistenceError(null)
    if (!nextThreadId) onConversationChangeRef.current?.(null)
  }, [onConversationChangeRef])
  const runtime = useRemoteThreadListRuntime({ runtimeHook, adapter, threadId, onThreadIdChange: handleThreadIdChange })
  const reloadThreads = useCallback(async (): Promise<void> => {
    forceListReloadRef.current = true
    await runtime.threads.reload()
  }, [runtime])
  const markPreflightPassed = useCallback(() => { preflightPassedRef.current = true }, [])
  const runBefore = useCallback(async (runConfig: ApexAssistantRunConfig): Promise<boolean> => {
    return beforeRunRef.current ? beforeRunRef.current(runConfig) : true
  }, [])
  const composerContext = useMemo(() => ({ configRef, beforeRun: runBefore, markPreflightPassed }), [markPreflightPassed, runBefore])
  const runtimeContext = useMemo(() => ({
    ...composerContext,
    persistActiveLeaf: (messageId: string) => branchPersistRef.current(messageId),
    clearBranchPersistenceError: () => setBranchPersistenceError(null),
    branchPersistenceError,
    reloadThreads,
    threadListError,
  }), [branchPersistenceError, composerContext, reloadThreads, threadListError])
  return <AssistantRuntimeProvider runtime={runtime}><ApexAssistantComposerContext.Provider value={runtimeContext}><ApexAssistantController branchPersistRef={branchPersistRef} forceHistoryReloadRef={forceHistoryReloadRef} getActiveRemoteId={getActiveRemoteId} getThreadIds={getThreadIds} onBranchPersistenceError={setBranchPersistenceError} runtimeRef={runtimeRef} />{children}</ApexAssistantComposerContext.Provider></AssistantRuntimeProvider>
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
  const { submit } = useApexAssistantComposer(edit ? aui.composer : undefined)
  const queryActive = useAuiState((state) => state.thread.isRunning)
  const threadLoading = useAuiState((state) => state.thread.isLoading)
  const error = composer?.error ?? null
  const handleSubmit = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    void submit()
  }
  const blocked = disabled || threadLoading
  return <ComposerPrimitive.Root onSubmit={handleSubmit} className="relative border-t border-white/10 bg-black/20 p-3 sm:p-4">
    {!edit && composer && queryActive ? <CortexQueryRim /> : null}
    <div className="flex items-end gap-2">
      <ComposerPrimitive.Input disabled={blocked} placeholder={edit ? 'Edit message…' : 'Ask APEX…'} className="min-h-11 flex-1 resize-none rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45" />
      {!edit && composer ? <ToolsSelector {...composer.tools} compact disabled={blocked || queryActive} /> : null}
      {!edit && composer ? <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 font-mono text-[10px] text-zinc-400" aria-label={`Active agent ${composer.activeAgentName}`}><AgentMark agent={composer.activeAgent} /><span className="hidden sm:inline">{composer.activeAgentName}</span></span> : null}
      {edit ? <ComposerPrimitive.Cancel disabled={blocked} className="rounded-lg border border-white/10 px-3 py-2 font-mono text-xs text-zinc-400 hover:text-white disabled:opacity-45">Cancel</ComposerPrimitive.Cancel> : null}
      <ComposerPrimitive.Send disabled={blocked || queryActive} onClick={(event) => { event.preventDefault(); void submit() }} className="rounded-lg border border-[#7E22CE]/45 bg-[#7E22CE]/15 px-3 py-2 font-mono text-xs uppercase tracking-wider text-[#E9D5FF] hover:bg-[#7E22CE]/25 disabled:cursor-not-allowed disabled:opacity-45">{edit ? 'Save' : 'Send'}</ComposerPrimitive.Send>
    </div>
    {!edit && composer && error ? <CortexErrorFeedback error={error} /> : null}
  </ComposerPrimitive.Root>
}

const ApexAssistantPresentationContext = createContext<{
  renderAgent?: (text: string, metadata: Record<string, unknown>) => ReactNode
  composer?: ApexAssistantComposerProps
}>({})

function ApexAssistantMessage(): ReactNode {
  const aui = useAui()
  const { renderAgent, composer } = useContext(ApexAssistantPresentationContext)
  const context = useContext(ApexAssistantComposerContext)
  const role = useAuiState((state) => state.message.role)
  const content = useAuiState((state) => state.message.content)
  const status = useAuiState((state) => state.message.status)
  const branchCount = useAuiState((state) => state.message.branchCount)
  const branchNumber = useAuiState((state) => state.message.branchNumber)
  const editing = useAuiState((state) => state.composer.isEditing)
  const metadata = useAuiState((state) => state.message.metadata.custom?.apex as Record<string, unknown> | undefined) ?? {}
  const text = content
    .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
    .map((part) => part.text)
    .join('\n')
  const selectBranch = (position: 'previous' | 'next'): void => {
    context?.clearBranchPersistenceError()
    aui.message().switchToBranch({ position })
    queueMicrotask(() => {
      const selectedId = aui.thread().getState().messages.at(-1)?.id
      if (!selectedId || !context) return
      void context.persistActiveLeaf(selectedId).catch(() => undefined)
    })
  }
  if (status?.type === 'running') return null
  return <MessagePrimitive.Root className={role === 'user' ? 'flex justify-end' : 'max-w-5xl'}>
    {editing && role === 'user' ? <GatedComposer edit disabled={composer?.disabled} /> : null}
    {editing && role === 'user' ? null : <>
    <div className={role === 'user'
      ? 'max-w-[85%] rounded-2xl rounded-br-md border border-[#0F4DB8]/35 bg-[#0F4DB8]/15 px-4 py-3 text-sm text-white'
      : 'rounded-2xl rounded-bl-md border border-white/10 bg-zinc-900/80 px-4 py-3 text-sm leading-relaxed text-zinc-200'}>
      {role === 'assistant' ? renderAgent?.(text, metadata) ?? <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown> : text}
      {role === 'assistant' && status?.type === 'incomplete' ? <ApexAssistantError /> : null}
      <div className="mt-2 flex items-center gap-2 font-mono text-[10px] text-zinc-500">
        <button type="button" onClick={() => void navigator.clipboard?.writeText(text)} className="hover:text-white">Copy</button>
        {role === 'user' ? <button type="button" onClick={() => aui.message().composer().beginEdit()} className="hover:text-white">Edit</button> : <button type="button" onClick={() => aui.message().reload()} className="hover:text-white">Retry</button>}
        {branchCount > 1 ? <><button type="button" aria-label="Previous branch" onClick={() => selectBranch('previous')} className="hover:text-white">‹</button><span>{branchNumber + 1}/{branchCount}</span><button type="button" aria-label="Next branch" onClick={() => selectBranch('next')} className="hover:text-white">›</button></> : null}
      </div>
    </div>
    </>}
  </MessagePrimitive.Root>
}

/** APEX-owned presentation built from assistant-ui primitives, not its starter kit. */
export function ApexAssistantThread({ disabled = false, renderAgent, composer }: { disabled?: boolean; renderAgent?: (text: string, metadata: Record<string, unknown>) => ReactNode; composer?: ApexAssistantComposerProps }): ReactNode {
  const running = useAuiState((state) => state.thread.isRunning)
  const context = useContext(ApexAssistantComposerContext)
  const presentation = useMemo(() => ({ renderAgent, composer }), [composer, renderAgent])
  const messageComponents = useMemo(() => ({ Message: ApexAssistantMessage }), [])
  return <ApexAssistantPresentationContext.Provider value={presentation}><ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
    <ThreadPrimitive.Viewport className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 scrollbar-thin" autoScroll>
      <ThreadPrimitive.Empty><div className="flex min-h-56 flex-col items-center justify-center rounded-xl border border-dashed border-white/10 px-6 text-center"><p className="font-mono text-xs uppercase tracking-widest text-zinc-500">APEX is ready. Start a session with a focused question.</p><div className="mt-4 flex max-w-xl flex-wrap justify-center gap-2">{OPERATION_PROMPT_CHIPS.map((chip) => <ThreadPrimitive.Suggestion key={chip.label} prompt={chip.query} send={false} className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300 transition-colors hover:border-[#0F4DB8]/50 hover:bg-[#0F4DB8]/15 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF]">{chip.label}</ThreadPrimitive.Suggestion>)}</div></div></ThreadPrimitive.Empty>
      <ThreadPrimitive.Messages components={messageComponents} />
      {running ? <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-[#D8B4FE]" aria-live="polite"><span className="inline-block size-2 animate-pulse rounded-full bg-[#C084FC]" aria-hidden />{composer?.activeAgentName ?? 'Agent'} working</div> : null}
    </ThreadPrimitive.Viewport>
    {context?.branchPersistenceError ? <p className="border-t border-red-500/20 bg-red-950/20 px-4 py-2 text-xs text-red-200" role="alert">{context.branchPersistenceError}</p> : null}
    <GatedComposer disabled={disabled} composer={composer} />
  </ThreadPrimitive.Root></ApexAssistantPresentationContext.Provider>
}

function ApexConversationRailItem({ disabled = false }: { disabled?: boolean }): ReactNode {
  const aui = useAui()
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
      await aui.threads.reload()
      const newestRemaining = aui.threads.getState().threadIds[0]
      if (newestRemaining) await aui.threads.switchToThread(newestRemaining)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Conversation update failed.')
    }
  }
  const deleteConversation = async (): Promise<void> => {
    if (!archived || (globalThis.confirm && !globalThis.confirm('Delete this archived conversation permanently? This cannot be undone.'))) return
    setActionError(null)
    try {
      await aui.threadListItem.delete()
      await aui.threads.reload()
      const active = aui.threads.getState().threadIds[0]
      if (active) await aui.threads.switchToThread(active)
      else await aui.threads.switchToNewThread()
      requestAnimationFrame(() => document.querySelector<HTMLElement>('[aria-label="Conversations"] button[aria-pressed="true"]')?.focus())
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
  return <ThreadListItemPrimitive.Root className="group flex items-center gap-1 rounded-md px-2 py-1 hover:bg-white/5">
    {renaming ? <input autoFocus disabled={disabled} value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setRenaming(false); if (event.key === 'Enter') void rename() }} className="min-w-0 flex-1 bg-transparent text-xs text-white outline-none" /> : <ThreadListItemPrimitive.Trigger disabled={disabled} className="min-w-0 flex-1 truncate text-left text-xs text-zinc-300"><ThreadListItemPrimitive.Title /></ThreadListItemPrimitive.Trigger>}
    {!renaming ? <button ref={renameTriggerRef} type="button" disabled={disabled} aria-label={`Rename ${currentTitle}`} onClick={() => { setTitle(currentTitle); setRenaming(true) }} className="text-zinc-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-40">✎</button> : null}
    <button type="button" disabled={disabled} onClick={() => void archive()} className="text-zinc-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-40">{archived ? 'Restore' : 'Archive'}</button>
    {archived ? <button type="button" disabled={disabled} onClick={() => void deleteConversation()} className="rounded p-1 text-zinc-500 hover:text-red-200 disabled:cursor-not-allowed disabled:opacity-40" aria-label={`Delete ${currentTitle} permanently`} title="Delete permanently"><Trash2 className="size-3.5" aria-hidden /></button> : null}
    {actionError ? <span role="alert" className="max-w-28 truncate text-[10px] text-red-300" title={actionError}>{actionError}</span> : null}
  </ThreadListItemPrimitive.Root>
}

export function ApexConversationRail({ className = 'hidden xl:block', disabled = false }: { className?: string; disabled?: boolean }): ReactNode {
  const aui = useAui()
  const [archived, setArchived] = useState(false)
  const threadLoading = useAuiState((state) => state.thread.isLoading)
  const interactionDisabled = disabled || threadLoading
  const isLoading = useAuiState((state) => state.threads.isLoading)
  const threadCount = useAuiState((state) => (archived ? state.threads.archivedThreadIds.length : state.threads.threadIds.length))
  const context = useContext(ApexAssistantComposerContext)
  const threadListError = context?.threadListError ?? null
  return <aside className={`${className} w-56 shrink-0 border-r border-white/10 bg-black/15 p-3`} aria-label="Conversations"><div className="mb-3 flex items-center justify-between"><p className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">Conversations</p><ApexAssistantNewConversation disabled={interactionDisabled} /></div><div className="mb-2 flex gap-2"><button type="button" disabled={interactionDisabled} onClick={() => setArchived(false)} aria-pressed={!archived} className="text-[10px] text-zinc-400 hover:text-white disabled:opacity-40">Active</button><button type="button" disabled={interactionDisabled} onClick={() => setArchived(true)} aria-pressed={archived} className="text-[10px] text-zinc-400 hover:text-white disabled:opacity-40">Archived</button></div>{isLoading ? <p className="px-2 py-4 text-xs text-zinc-500" role="status">Loading conversations…</p> : threadListError ? <div className="space-y-2 px-2 py-4"><p className="text-xs text-red-300" role="alert">{threadListError}</p><button type="button" disabled={interactionDisabled} onClick={() => void (context?.reloadThreads() ?? aui.threads.reload())} className="text-[10px] text-[#7EB3FF] hover:text-white disabled:opacity-40">Retry</button></div> : threadCount === 0 ? <div className="space-y-2 px-2 py-4"><p className="text-xs text-zinc-500">No {archived ? 'archived' : 'active'} conversations.</p></div> : <ThreadListPrimitive.Root><ThreadListPrimitive.Items archived={archived} components={{ ThreadListItem: () => <ApexConversationRailItem disabled={interactionDisabled} /> }} /></ThreadListPrimitive.Root>}</aside>
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
  return <span className="inline-flex items-center gap-2"><button type="button" disabled={disabled || creating} aria-busy={creating} onClick={() => void create()} className="inline-flex items-center gap-1.5 rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300 hover:border-[#7EB3FF]/50 hover:text-white disabled:opacity-40">
    {creating ? 'Creating…' : 'New conversation'}
  </button>{createError ? <span role="alert" className="max-w-32 truncate text-[10px] text-red-300" title={createError}>{createError}</span> : null}</span>
}
