import {
  Check,
  Loader2,
  RotateCcw,
  Terminal,
  X,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactElement,
} from 'react'

import type { AgentMessage, ToolTraceItem } from '../hooks/useApexAssistant'
import type { AgentProfileStatus, AssistantProfile } from '../types/telemetry'

import { OPERATION_PROMPT_CHIPS } from './AskApexBar'

const PROFILE_LABELS: Record<AssistantProfile, string> = {
  comet: 'Comet',
  nova: 'Nova',
  pulsar: 'Pulsar',
  lynx: 'Lynx',
  acinonyx: 'Acinonyx',
  neofelis: 'Neofelis',
}

interface AssistantDrawerProps {
  isOpen: boolean
  onClose: () => void
  onResetSession: () => void
  history: AgentMessage[]
  isQuerying: boolean
  latestTrace: ToolTraceItem[]
  activeProfile: AssistantProfile
  profilesStatus: AgentProfileStatus[]
  onUnloadModel: () => Promise<void>
  onSubmitFollowUp: (prompt: string) => void
  error: string | null
}

function formatCountdown(seconds: number | null): string {
  if (seconds === null || seconds < 0) {
    return '--:--'
  }

  const total = Math.floor(seconds)
  const minutes = Math.floor(total / 60)
  const remainingSeconds = total % 60
  return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
}

function formatBytes(bytes: number | null): string | null {
  if (bytes === null || !Number.isFinite(bytes) || bytes <= 0) {
    return null
  }

  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unitIndex = 0

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }

  const precision = unitIndex >= 3 ? 1 : 0
  return `${value.toFixed(precision)} ${units[unitIndex]}`
}

function buildLoadedModelDetails(
  loadedModel: AgentProfileStatus['loaded_model'],
): string[] {
  if (!loadedModel) {
    return []
  }

  const details: string[] = []
  if (loadedModel.processor) {
    details.push(loadedModel.processor)
  }
  if (loadedModel.context) {
    details.push(`ctx ${loadedModel.context}`)
  }

  const size = formatBytes(loadedModel.size_bytes)
  if (size) {
    details.push(`size ${size}`)
  }

  const vram = formatBytes(loadedModel.size_vram_bytes)
  if (vram) {
    details.push(`vram ${vram}`)
  }

  return details
}

function ActiveLocalModelPanel({
  activeLocalModel,
  isQuerying,
  onUnloadModel,
}: {
  activeLocalModel: AgentProfileStatus
  isQuerying: boolean
  onUnloadModel: () => Promise<void>
}): ReactElement {
  const idleSeconds = activeLocalModel.idle_unload_remaining_seconds
  const countdownText =
    idleSeconds === null ? '--:--' : formatCountdown(idleSeconds)
  const loadedModelDetails = buildLoadedModelDetails(activeLocalModel.loaded_model)

  const handleUnload = useCallback((): void => {
    void onUnloadModel()
  }, [onUnloadModel])

  return (
    <div
      className={[
        'mb-3 flex items-center justify-between rounded-lg border border-amber-500/20',
        'bg-amber-950/10 p-3 text-xs transition-opacity duration-300',
      ].join(' ')}
      data-slot="active-local-model"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center">
          <span
            className="relative mr-2 inline-flex h-2 w-2 shrink-0"
            aria-hidden
          >
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#FBBF24]/60 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[#FBBF24]" />
          </span>
          <span className="truncate font-mono text-[10px] font-bold uppercase tracking-wider text-amber-200">
            {activeLocalModel.display_name} [LOADED]
          </span>
        </div>
        <span className="mt-1 block font-mono text-[10px] text-zinc-500">
          Auto-unload in {countdownText}
        </span>
        {loadedModelDetails.length > 0 ? (
          <span className="mt-1 block truncate font-mono text-[10px] text-zinc-500">
            {loadedModelDetails.join(' | ')}
          </span>
        ) : null}
      </div>

      <button
        type="button"
        onClick={handleUnload}
        disabled={isQuerying}
        className={[
          'ml-3 shrink-0 rounded border border-white/10 px-2 py-1',
          'font-mono text-[10px] uppercase transition-colors',
          'hover:bg-red-950/20 hover:text-red-400',
          isQuerying ? 'cursor-not-allowed opacity-40' : 'text-zinc-300',
        ].join(' ')}
        aria-label={`Unload ${activeLocalModel.display_name}`}
      >
        Unload
      </button>
    </div>
  )
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function parseInlineMarkdown(text: string): string {
  return escapeHtml(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
}

function parseSimpleMarkdown(content: string): string {
  const lines = content.split('\n')
  const htmlParts: string[] = []
  let listItems: string[] = []

  const flushList = (): void => {
    if (listItems.length === 0) {
      return
    }
    htmlParts.push(
      `<ul class="list-disc pl-5 space-y-1">${listItems.join('')}</ul>`,
    )
    listItems = []
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('* ')) {
      const itemText = trimmed.slice(2)
      listItems.push(`<li>${parseInlineMarkdown(itemText)}</li>`)
      continue
    }

    flushList()

    if (trimmed.length === 0) {
      htmlParts.push('<br />')
      continue
    }

    htmlParts.push(`${parseInlineMarkdown(line)}<br />`)
  }

  flushList()
  return htmlParts.join('')
}

function MarkdownContent({ content }: { content: string }): ReactElement {
  return (
    <div
      className="text-sm leading-relaxed text-zinc-200 [&_strong]:font-semibold [&_strong]:text-white"
      dangerouslySetInnerHTML={{ __html: parseSimpleMarkdown(content) }}
    />
  )
}

function TraceStatusIcon({ status }: { status: string }): ReactElement {
  const normalized = status.toLowerCase()
  const Icon: LucideIcon = normalized === 'ok' ? Check : XCircle
  const colorClass = normalized === 'ok' ? 'text-emerald-400' : 'text-red-400'

  return <Icon className={`size-3.5 shrink-0 ${colorClass}`} aria-hidden />
}

function ToolTracePanel({ trace }: { trace: ToolTraceItem[] }): ReactElement | null {
  if (trace.length === 0) {
    return null
  }

  return (
    <div className="mt-3 rounded-lg border border-white/10 bg-zinc-900/70 p-3">
      <p className="mb-2 font-mono text-[10px] uppercase tracking-widest text-zinc-400">
        🔧 Tools Executed
      </p>
      <ul className="space-y-1.5">
        {trace.map((item, index) => (
          <li
            key={`${item.name}-${item.duration_ms}-${index}`}
            className="flex items-center gap-2 font-mono text-[11px] text-zinc-300"
          >
            <TraceStatusIcon status={item.status} />
            <span>
              {item.name} ({item.status}) - {Math.round(item.duration_ms)}ms
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function AssistantDrawer({
  isOpen,
  onClose,
  onResetSession,
  history,
  isQuerying,
  latestTrace,
  activeProfile,
  profilesStatus,
  onUnloadModel,
  onSubmitFollowUp,
  error,
}: AssistantDrawerProps): ReactElement {
  const [followUp, setFollowUp] = useState('')
  const chatEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const activeLocalModel = profilesStatus.find(
    (profile) => profile.provider === 'ollama' && profile.active,
  )

  const lastModelIndex = (() => {
    for (let index = history.length - 1; index >= 0; index -= 1) {
      if (history[index]?.role === 'model') {
        return index
      }
    }
    return -1
  })()

  useEffect(() => {
    if (!isOpen) {
      return
    }

    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, isQuerying, isOpen])

  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus()
    }
  }, [isOpen])

  const handleSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>): void => {
      event.preventDefault()

      const trimmed = followUp.trim()
      if (!trimmed || isQuerying) {
        return
      }

      onSubmitFollowUp(trimmed)
      setFollowUp('')
    },
    [followUp, isQuerying, onSubmitFollowUp],
  )

  const handleInputKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>): void => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        event.currentTarget.form?.requestSubmit()
      }
    },
    [],
  )

  return (
    <aside
      className={[
        'fixed top-0 right-0 z-50 flex h-dvh w-full flex-col border-l border-white/10 bg-zinc-950/95 shadow-2xl backdrop-blur-md transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] sm:w-[460px]',
        isOpen ? 'translate-x-0' : 'translate-x-full',
      ].join(' ')}
      aria-hidden={!isOpen}
      data-slot="assistant-drawer"
    >
      <header className="flex items-center justify-between border-b border-white/10 px-6 py-4">
        <div className="flex items-center gap-3">
          <h2 className="font-mono text-sm font-semibold uppercase tracking-[0.2em] text-white">
            APEX
          </h2>
          <span className="rounded-full border border-[#0F4DB8]/40 bg-[#0F4DB8]/10 px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-[#7EB3FF]">
            {PROFILE_LABELS[activeProfile]}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onResetSession}
            className="rounded-md p-1.5 transition-colors hover:bg-white/5"
            aria-label="Clear session history"
            tabIndex={0}
          >
            <RotateCcw className="size-4 text-zinc-400 hover:text-rose-400 transition-colors" />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-zinc-400 transition-colors hover:bg-white/5 hover:text-white"
            aria-label="Close APEX drawer"
          >
            <X className="size-4" />
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex-1 overflow-y-auto p-6">
          {history.length === 0 && !isQuerying ? (
            <div className="flex h-full min-h-[280px] flex-col items-center justify-center text-center">
              <Terminal
                className="mb-4 size-8 text-[#0F4DB8]/30"
                aria-hidden
              />
              <h3 className="mb-2 font-mono text-xs font-bold uppercase tracking-widest text-white">
                APEX STANDBY
              </h3>
              <p className="mb-6 max-w-sm text-sm text-zinc-500">
                Ask follow-up questions, query long-range schedules, or run
                comparative analytics over past runs.
              </p>
              <div className="grid w-full max-w-md grid-cols-1 gap-2 sm:grid-cols-2">
                {OPERATION_PROMPT_CHIPS.map((chip) => (
                  <button
                    key={chip.label}
                    type="button"
                    onClick={() => {
                      onSubmitFollowUp(chip.query)
                    }}
                    className={[
                      'rounded-lg border border-white/10 bg-zinc-900/60 px-3 py-2.5 text-left',
                      'transition-colors hover:border-[#0F4DB8]/40 hover:bg-[#0F4DB8]/10',
                    ].join(' ')}
                  >
                    <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-400">
                      {chip.label}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {history.map((message, index) => {
                if (message.role === 'user') {
                  return (
                    <div key={`user-${index}`} className="flex justify-end">
                      <div className="max-w-[85%] rounded-2xl rounded-br-md border border-[#0F4DB8]/30 bg-[#0F4DB8]/15 px-4 py-3 text-sm text-white">
                        {message.content}
                      </div>
                    </div>
                  )
                }

                if (message.role === 'model') {
                  const showTrace =
                    index === lastModelIndex && latestTrace.length > 0
                  return (
                    <div key={`model-${index}`} className="flex justify-start">
                      <div className="max-w-[92%] rounded-2xl rounded-bl-md border border-white/10 bg-zinc-900/80 px-4 py-3">
                        <MarkdownContent content={message.content ?? ''} />
                        {showTrace ? (
                          <ToolTracePanel trace={latestTrace} />
                        ) : null}
                      </div>
                    </div>
                  )
                }

                return null
              })}

              {error ? (
                <div className="rounded-lg border border-red-500/30 bg-red-950/30 px-4 py-3 text-sm text-red-300">
                  {error}
                </div>
              ) : null}

              {isQuerying ? (
                <div className="flex items-center gap-3 px-1 py-2">
                  <Loader2
                    className="size-4 animate-spin text-[#39FF88]"
                    aria-hidden
                  />
                  <div className="flex flex-col gap-1.5">
                    <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">
                      APEX processing
                    </span>
                    <div className="h-2 w-40 animate-pulse rounded-full bg-gradient-to-r from-[#0F4DB8]/20 via-[#39FF88]/40 to-[#0F4DB8]/20" />
                  </div>
                </div>
              ) : null}

              <div ref={chatEndRef} />
            </div>
          )}
        </div>

        <footer className="border-t border-white/10 p-4">
          {activeLocalModel ? (
            <ActiveLocalModelPanel
              activeLocalModel={activeLocalModel}
              isQuerying={isQuerying}
              onUnloadModel={onUnloadModel}
            />
          ) : null}

          <form onSubmit={handleSubmit} className="flex items-center gap-2">
            <input
              ref={inputRef}
              type="text"
              value={followUp}
              onChange={(event) => {
                setFollowUp(event.target.value)
              }}
              onKeyDown={handleInputKeyDown}
              placeholder="Send a follow-up query..."
              disabled={isQuerying}
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-zinc-900/80 px-4 py-2.5 text-sm text-white placeholder:text-zinc-500 outline-none transition-colors focus:border-[#0F4DB8]/50 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="Follow-up query"
              autoComplete="off"
              spellCheck={false}
            />
          </form>
        </footer>
      </div>
    </aside>
  )
}
