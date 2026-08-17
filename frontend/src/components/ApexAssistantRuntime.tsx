import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  RuntimeAdapterProvider,
  MessagePrimitive,
  ThreadPrimitive,
  ThreadListPrimitive,
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

import { API_ENDPOINTS } from '../lib/api'
import type { AgentKey, CloudEffort } from '../types/telemetry'

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

export type ApexAssistantRunConfig = {
  agent: AgentKey
  effort: CloudEffort | null
  selectedToolNames: string[]
  toolProfileId: string | null
  snapshotId: string | null
  briefingId?: number | null
}

type Props = {
  config: ApexAssistantRunConfig
  children: ReactNode
  beforeRun?: (config: ApexAssistantRunConfig) => Promise<boolean>
  onConversationChange?: (conversation: ConversationSummary | null) => void
  onRunningChange?: (running: boolean, agent: AgentKey | null) => void
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
  if (!response.ok) throw new Error(`APEX request failed (${response.status})`)
  return response.json() as Promise<T>
}

function ThreadHistory({ children }: { children?: ReactNode }): ReactNode {
  const aui = useAui()
  const history = useMemo<ThreadHistoryAdapter>(() => ({
    async load() {
      const remoteId = aui.threadListItem.getState().remoteId
      if (!remoteId) return ExportedMessageRepository.fromBranchableArray([])
      const detail = await requestJson<ConversationDetail>(API_ENDPOINTS.cortexConversation(remoteId))
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
                  : { type: 'incomplete' as const, reason: 'error' as const, error: String(message.response_metadata?.error ?? message.status) },
                metadata: { custom: { apex: message.response_metadata ?? {} } },
              },
        })),
        { headId: detail.active_leaf_message_id },
      )
    },
    async append() {},
    async update() {},
  }), [aui])
  return <RuntimeAdapterProvider adapters={{ history }}>{children}</RuntimeAdapterProvider>
}

export function ApexAssistantRuntime({ config, children, beforeRun, onConversationChange, onRunningChange }: Props): ReactNode {
  const configRef = useRef(config)
  useEffect(() => {
    configRef.current = config
  }, [config])
  const ids = useRef(new Map<string, string>())
  const remoteByLocal = useRef(new Map<string, string>())
  const [threadId, setThreadId] = useState<string | undefined>()

  const adapter = useMemo<RemoteThreadListAdapter>(() => ({
    async list() {
      const [regular, archived] = await Promise.all([
        requestJson<ConversationSummary[]>(API_ENDPOINTS.cortexConversations),
        requestJson<ConversationSummary[]>(`${API_ENDPOINTS.cortexConversations}?archived=true`),
      ])
      return { threads: [...regular, ...archived].map((item) => ({
        remoteId: item.id, status: item.archived_at ? 'archived' : 'regular', title: item.title,
        lastMessageAt: new Date(item.updated_at), custom: item,
      })) }
    },
    async initialize(localId) {
      const current = configRef.current
      const item = await requestJson<ConversationSummary>(API_ENDPOINTS.cortexConversations, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ origin: 'hud', agent: current.agent, selected_tool_names: current.selectedToolNames, tool_profile_id: current.toolProfileId }),
      })
      remoteByLocal.current.set(localId, item.id)
      onConversationChange?.(item)
      return { remoteId: item.id }
    },
    async rename(remoteId, title) { await requestJson(API_ENDPOINTS.cortexConversation(remoteId), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) }) },
    async archive(remoteId) { await requestJson(API_ENDPOINTS.cortexConversation(remoteId), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ archived: true }) }) },
    async unarchive(remoteId) { await requestJson(API_ENDPOINTS.cortexConversation(remoteId), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ archived: false }) }) },
    async delete() { throw new Error('APEX does not support permanent conversation deletion.') },
    async generateTitle() { throw new Error('APEX does not generate conversation titles.') },
    async fetch(remoteId) {
      const item = await requestJson<ConversationSummary>(API_ENDPOINTS.cortexConversation(remoteId))
      onConversationChange?.(item)
      return { remoteId: item.id, status: item.archived_at ? 'archived' : 'regular', title: item.title, lastMessageAt: new Date(item.updated_at), custom: item }
    },
    unstable_Provider: ThreadHistory,
  }), [onConversationChange])

  const runtimeHook = useCallback(() => {
    const model: ChatModelAdapter = {
      async run(options) {
        const localThreadId = options.unstable_threadId
        const remoteId = (localThreadId ? remoteByLocal.current.get(localThreadId) : undefined) ?? threadId
        const user = options.messages.at(-1)
        if (!remoteId || !user || user.role !== 'user' || !options.unstable_assistantMessageId) throw new Error('Conversation is not ready.')
        const current = configRef.current
        if (beforeRun && !await beforeRun(current)) throw new Error('This request did not pass APEX preflight.')
        onRunningChange?.(true, current.agent)
        try {
          const response = await requestJson<Record<string, unknown>>(API_ENDPOINTS.cortexConversationTurns(remoteId), {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              prompt: user.content.filter((part) => part.type === 'text').map((part) => part.text).join('\n'),
              user_message_id: canonicalId(user.id, ids.current),
              agent_message_id: canonicalId(options.unstable_assistantMessageId, ids.current),
              ...(options.messages.at(-2)?.id
                ? { parent_message_id: canonicalId(options.messages.at(-2)!.id, ids.current) }
                : {}),
              agent: current.agent, effort: current.effort, selected_tool_names: current.selectedToolNames,
              tool_profile_id: current.toolProfileId, snapshot_id: current.snapshotId, briefing_id: current.briefingId ?? undefined,
            }),
          })
          return { content: [{ type: 'text' as const, text: String(response.answer ?? '') }], metadata: { custom: { apex: response } } }
        } finally { onRunningChange?.(false, null) }
      },
    }
    // assistant-ui invokes this callback as a hook host for each active thread.
    // eslint-disable-next-line react-hooks/rules-of-hooks
    return useLocalRuntime(model, { maxSteps: 1 })
  }, [beforeRun, onRunningChange, threadId])

  const runtime = useRemoteThreadListRuntime({ runtimeHook, adapter, threadId, onThreadIdChange: setThreadId })
  return <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>
}

export function ApexAssistantError(): ReactNode {
  const apex = useAuiState((state) => state.message.metadata.custom?.apex as Record<string, unknown> | undefined)
  return typeof apex?.error === 'string' ? <p className="mt-2 text-xs text-red-300" role="alert">{apex.error}</p> : null
}

function ApexAssistantMessage(): ReactNode {
  const role = useAuiState((state) => state.message.role)
  const content = useAuiState((state) => state.message.content)
  const status = useAuiState((state) => state.message.status)
  const text = content
    .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
    .map((part) => part.text)
    .join('\n')
  return <MessagePrimitive.Root className={role === 'user' ? 'flex justify-end' : 'max-w-5xl'}>
    <div className={role === 'user'
      ? 'max-w-[85%] rounded-2xl rounded-br-md border border-[#0F4DB8]/35 bg-[#0F4DB8]/15 px-4 py-3 text-sm text-white'
      : 'rounded-2xl rounded-bl-md border border-white/10 bg-zinc-900/80 px-4 py-3 text-sm leading-relaxed text-zinc-200'}>
      {role === 'assistant' ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown> : text}
      {role === 'assistant' && status?.type === 'incomplete' ? <ApexAssistantError /> : null}
    </div>
  </MessagePrimitive.Root>
}

/** APEX-owned presentation built from assistant-ui primitives, not its starter kit. */
export function ApexAssistantThread({ disabled = false }: { disabled?: boolean }): ReactNode {
  return <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
    <ThreadPrimitive.Viewport className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 scrollbar-thin" autoScroll>
      <ThreadPrimitive.Messages components={{ Message: ApexAssistantMessage }} />
    </ThreadPrimitive.Viewport>
    <ComposerPrimitive.Root className="border-t border-white/10 bg-black/20 p-3 sm:p-4">
      <div className="flex items-end gap-2">
        <ComposerPrimitive.Input
          disabled={disabled}
          placeholder="Ask APEX…"
          className="min-h-11 flex-1 resize-none rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45"
        />
        <ComposerPrimitive.Send disabled={disabled} className="rounded-lg border border-[#0F4DB8]/60 bg-[#0F4DB8]/20 px-3 py-2 font-mono text-xs uppercase tracking-wider text-white hover:bg-[#0F4DB8]/35 disabled:cursor-not-allowed disabled:opacity-45">
          Send
        </ComposerPrimitive.Send>
      </div>
    </ComposerPrimitive.Root>
  </ThreadPrimitive.Root>
}

export function ApexAssistantNewConversation({ disabled = false }: { disabled?: boolean }): ReactNode {
  return <ThreadListPrimitive.New disabled={disabled} className="inline-flex items-center gap-1.5 rounded-md border border-white/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-300 hover:border-[#7EB3FF]/50 hover:text-white disabled:opacity-40">
    New conversation
  </ThreadListPrimitive.New>
}
