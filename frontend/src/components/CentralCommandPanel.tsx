import {
  Check,
  ChevronDown,
  Loader2,
  RotateCcw,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useRef,
  type ReactElement,
} from 'react'

import { type AgentMessage, type ToolTraceItem } from '../hooks/useApexAssistant'
import { type AgentProfileStatus, type AssistantProfile, type SystemState } from '../types/telemetry'

import { ApexLogo } from './ApexLogo'
import { AssistantToolCards } from './AssistantToolCards'
import { AskApexBar, OPERATION_PROMPT_CHIPS } from './AskApexBar'

interface CentralCommandPanelProps {
  isExpanded: boolean
  setExpanded: (open: boolean) => void
  activeTab: 'assistant' | 'briefing'
  setActiveTab: (tab: 'assistant' | 'briefing') => void
  briefingText: string
  insights: string[]
  isBriefingNew: boolean
  setBriefingNew: (val: boolean) => void
  activeStep: number | null
  status: SystemState
  isSpeaking: boolean
  reminderPulseCount: number

  assistantHistory: AgentMessage[]
  isAssistantQuerying: boolean
  assistantLatestTrace: ToolTraceItem[]
  assistantError: string | null
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  queryAssistant: (prompt: string, profile: AssistantProfile) => Promise<void>
  unloadLocalModel: () => Promise<void>
  resetAssistantSession: () => void
  activeProfile: AssistantProfile
  setActiveProfile: (profile: AssistantProfile) => void
  askApexEnabled: boolean
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

function AssistantTabContent({
  history,
  isQuerying,
  latestTrace,
  error,
  profilesStatus,
  onUnloadModel,
  queryAssistant,
  activeProfile,
}: {
  history: AgentMessage[]
  isQuerying: boolean
  latestTrace: ToolTraceItem[]
  error: string | null
  profilesStatus: AgentProfileStatus[]
  onUnloadModel: () => Promise<void>
  queryAssistant: (prompt: string, profile: AssistantProfile) => Promise<void>
  activeProfile: AssistantProfile
}): ReactElement {
  const chatEndRef = useRef<HTMLDivElement>(null)

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
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, isQuerying])

  const chipClassName = [
    'px-2.5 py-1 rounded-full border border-white/5 bg-white/5',
    'hover:border-[#0F4DB8]/40 hover:bg-[#0F4DB8]/10',
    'text-[10px] text-zinc-400 hover:text-white transition-colors',
    'cursor-pointer font-mono uppercase tracking-wider',
    isQuerying ? 'pointer-events-none opacity-50' : '',
  ].join(' ')

  return (
    <div className="space-y-4">
      {activeLocalModel ? (
        <ActiveLocalModelPanel
          activeLocalModel={activeLocalModel}
          isQuerying={isQuerying}
          onUnloadModel={onUnloadModel}
        />
      ) : null}

      {history.length === 0 && !isQuerying ? (
        <div className="flex min-h-[12rem] flex-col items-center justify-center gap-6 py-6">
          <p className="text-center font-mono text-xs uppercase tracking-widest text-zinc-500">
            APEX STANDBY. Submit a query to begin assistant session.
          </p>
          <div className="flex w-full max-w-lg flex-wrap items-center justify-center gap-2">
            {OPERATION_PROMPT_CHIPS.map((chip) => (
              <button
                key={chip.label}
                type="button"
                onClick={() => {
                  void queryAssistant(chip.query, activeProfile)
                }}
                disabled={isQuerying}
                className={chipClassName}
              >
                {chip.label}
              </button>
            ))}
          </div>
        </div>
      ) : (
        history.map((message, index) => {
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
            const toolOutputs = message.tool_outputs ?? []
            return (
              <div key={`model-${index}`} className="flex justify-start">
                <div className="flex w-full min-w-0 max-w-[92%] flex-col">
                  <div className="rounded-2xl rounded-bl-md border border-white/10 bg-zinc-900/80 px-4 py-3">
                    <MarkdownContent content={message.content ?? ''} />
                    {showTrace ? (
                      <ToolTracePanel trace={latestTrace} />
                    ) : null}
                  </div>
                  {toolOutputs.length > 0 ? (
                    <AssistantToolCards toolOutputs={toolOutputs} />
                  ) : null}
                </div>
              </div>
            )
          }

          return null
        })
      )}

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
  )
}

function BriefingTabContent({
  briefingText,
  insights,
}: {
  briefingText: string
  insights: string[]
}): ReactElement {
  const trimmed = briefingText.trim()

  if (trimmed.length === 0) {
    return (
      <p className="py-8 text-center font-mono text-xs uppercase tracking-widest text-zinc-500">
        APEX STANDBY. Initiate system synthesis to compile briefing data.
      </p>
    )
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-amber-500/30 bg-zinc-900/40 p-4">
        <MarkdownContent content={trimmed} />
      </div>

      {insights.length > 0 ? (
        <div className="space-y-3 border-t border-white/10 pt-4">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-zinc-500">
            [ SUMMARY INSIGHTS ]
          </p>
          <ul className="space-y-3">
            {insights.map((insight, index) => (
              <li
                key={`${index}-${insight.slice(0, 24)}`}
                className="flex items-start gap-3 text-sm leading-relaxed text-zinc-200"
              >
                <span className="shrink-0 select-none font-mono font-bold text-[#FBBF24]">
                  {`>`}
                </span>
                <span>{insight}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

export function CentralCommandPanel({
  isExpanded,
  setExpanded,
  activeTab,
  setActiveTab,
  briefingText,
  insights,
  isBriefingNew,
  setBriefingNew,
  activeStep,
  status,
  isSpeaking,
  reminderPulseCount,
  assistantHistory,
  isAssistantQuerying,
  assistantLatestTrace,
  assistantError,
  profilesStatus,
  profilesStatusHydrated,
  queryAssistant,
  unloadLocalModel,
  resetAssistantSession,
  activeProfile,
  setActiveProfile,
  askApexEnabled,
}: CentralCommandPanelProps): ReactElement {
  const handleExpandFromFooter = useCallback((): void => {
    setExpanded(true)
  }, [setExpanded])

  const handleExpandIfCollapsed = useCallback((): void => {
    if (!isExpanded) {
      setExpanded(true)
    }
  }, [isExpanded, setExpanded])

  const handleMinimize = useCallback((): void => {
    setExpanded(false)
  }, [setExpanded])

  const handleAgentSubmit = useCallback(
    (query: string, profile: AssistantProfile): void => {
      void queryAssistant(query, profile)
    },
    [queryAssistant],
  )

  const handleChipSelect = useCallback(
    (query: string): void => {
      void queryAssistant(query, activeProfile)
    },
    [activeProfile, queryAssistant],
  )

  const tabBaseClass =
    'font-mono text-[10px] uppercase tracking-[0.2em] transition-colors duration-300 px-3 py-1.5 rounded-md border'

  return (
    <section
      className="flex h-full min-h-0 w-full flex-1 flex-col overflow-hidden rounded-xl border border-white/10 hud-glass transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)]"
      data-slot="central-command-panel"
      aria-label="Central command panel"
    >
      <header className="flex shrink-0 items-center gap-3 border-b border-white/10 px-4 py-3">
        <div
          className={[
            'flex shrink-0 items-center justify-center overflow-hidden transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]',
            isExpanded ? 'w-14 opacity-100 sm:w-16' : 'w-0 opacity-0',
          ].join(' ')}
        >
          {isExpanded ? (
            <ApexLogo
              step={activeStep}
              status={status}
              isSpeaking={isSpeaking}
              reminderPulseCount={reminderPulseCount}
              className="h-14 w-auto sm:h-16"
            />
          ) : null}
        </div>

        <div className="flex flex-1 items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => {
              setActiveTab('assistant')
              handleExpandIfCollapsed()
            }}
            className={[
              tabBaseClass,
              activeTab === 'assistant'
                ? 'border-[#0F4DB8]/50 bg-[#0F4DB8]/15 text-[#7EB3FF] shadow-[0_0_10px_rgba(15,77,184,0.25)]'
                : 'border-white/5 bg-transparent text-zinc-500 hover:border-white/10 hover:text-zinc-300',
            ].join(' ')}
            aria-pressed={activeTab === 'assistant'}
          >
            [ ASSISTANT ]
          </button>

          <button
            type="button"
            onClick={() => {
              setActiveTab('briefing')
              setBriefingNew(false)
              handleExpandIfCollapsed()
            }}
            className={[
              tabBaseClass,
              activeTab === 'briefing'
                ? 'border-[#FBBF24]/50 bg-[#FBBF24]/10 text-[#FBBF24] shadow-[0_0_10px_rgba(251,191,36,0.2)]'
                : 'border-white/5 bg-transparent text-zinc-500 hover:border-white/10 hover:text-zinc-300',
            ].join(' ')}
            aria-pressed={activeTab === 'briefing'}
          >
            <span className="inline-flex items-center gap-1.5">
              [ BRIEFING ]
              {isBriefingNew ? (
                <span className="relative inline-flex h-1.5 w-1.5" aria-label="New briefing available">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#FBBF24]/70 opacity-75" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#FBBF24]" />
                </span>
              ) : null}
            </span>
          </button>
        </div>

        <div
          className={[
            'flex shrink-0 items-center gap-1 overflow-hidden transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]',
            isExpanded ? 'w-auto opacity-100' : 'w-0 opacity-0',
          ].join(' ')}
        >
          {isExpanded ? (
            <>
              <button
                type="button"
                onClick={handleMinimize}
                className="rounded-md p-1.5 transition-colors hover:bg-white/5"
                aria-label="Minimize panel"
              >
                <ChevronDown className="size-4 text-zinc-400 transition-colors hover:text-zinc-200" />
              </button>
              <button
                type="button"
                onClick={resetAssistantSession}
                className="rounded-md p-1.5 transition-colors hover:bg-white/5"
                aria-label="Clear session history"
              >
                <RotateCcw className="size-4 text-zinc-400 transition-colors hover:text-rose-400" />
              </button>
            </>
          ) : null}
        </div>
      </header>

      <div
        className={[
          'flex min-h-0 flex-col overflow-hidden transition-all duration-700 ease-in-out',
          isExpanded
            ? 'flex-1 opacity-100'
            : 'max-h-0 flex-none opacity-0 pointer-events-none',
        ].join(' ')}
        aria-hidden={!isExpanded}
      >
        <div className="min-h-0 flex-1 overflow-y-auto border-b border-white/5 bg-zinc-950/20 p-4 scrollbar-thin">
          {activeTab === 'assistant' ? (
            <AssistantTabContent
              history={assistantHistory}
              isQuerying={isAssistantQuerying}
              latestTrace={assistantLatestTrace}
              error={assistantError}
              profilesStatus={profilesStatus}
              onUnloadModel={unloadLocalModel}
              queryAssistant={queryAssistant}
              activeProfile={activeProfile}
            />
          ) : (
            <BriefingTabContent briefingText={briefingText} insights={insights} />
          )}
        </div>
      </div>

      {askApexEnabled ? (
        <footer
          className="shrink-0 border-t border-white/10 bg-zinc-950/30 p-4"
          onClick={handleExpandFromFooter}
          onFocusCapture={handleExpandFromFooter}
        >
          <AskApexBar
            activeProfile={activeProfile}
            onProfileChange={setActiveProfile}
            onSubmit={handleAgentSubmit}
            profilesStatus={profilesStatus}
            profilesStatusHydrated={profilesStatusHydrated}
            onSelectChip={handleChipSelect}
            isSubmitting={isAssistantQuerying}
            integrated
          />
        </footer>
      ) : null}
    </section>
  )
}
