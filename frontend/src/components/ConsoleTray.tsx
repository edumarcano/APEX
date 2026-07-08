import {
  Check,
  CheckSquare,
  ChevronUp,
  Loader2,
  RotateCcw,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactElement,
} from 'react'

import { type AgentMessage, type ToolTraceItem } from '../hooks/useApexAssistant'
import {
  type ActiveReminder,
  type AgentProfileStatus,
  type AssistantProfile,
} from '../types/telemetry'

import { AssistantToolCards } from './AssistantToolCards'
import { AskApexBar, OPERATION_PROMPT_CHIPS } from './AskApexBar'
import { ReminderListRow } from './ReminderListRow'

const REMINDERS_ENDPOINT = 'http://127.0.0.1:8000/api/v1/reminders'

type ConsoleActivityTone = 'rust' | 'purple'

/**
 * Border-rim activity glow: paints ABOVE panel content, masked to the ring
 * only, so the sweep rides the tray border (not under translucent glass).
 * Two wide arcs sit 180° apart and rotate together.
 * Rust = local model loading; purple = assistant query / tool execution.
 */
function ConsoleActivityGlow({
  tone,
}: {
  tone: ConsoleActivityTone | null
}): ReactElement | null {
  if (!tone) {
    return null
  }

  const accentRgb = tone === 'rust' ? '249, 115, 22' : '168, 85, 247'

  // Dual peaks at opposite ends of the rim (~0° and ~180°).
  const dualSweep = `conic-gradient(from 0deg,
    rgba(${accentRgb}, 0) 0deg,
    rgba(${accentRgb}, 0.15) 15deg,
    rgba(${accentRgb}, 0.95) 45deg,
    rgba(${accentRgb}, 0.15) 75deg,
    rgba(${accentRgb}, 0) 90deg,
    rgba(${accentRgb}, 0) 180deg,
    rgba(${accentRgb}, 0.15) 195deg,
    rgba(${accentRgb}, 0.95) 225deg,
    rgba(${accentRgb}, 0.15) 255deg,
    rgba(${accentRgb}, 0) 270deg,
    rgba(${accentRgb}, 0) 360deg)`

  const ringMask = {
    WebkitMask:
      'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
    WebkitMaskComposite: 'xor',
    mask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
    maskComposite: 'exclude',
  } as const

  return (
    <div
      className="pointer-events-none absolute inset-0 z-[25] rounded-2xl overflow-hidden"
      aria-hidden
      data-slot="console-activity-glow"
      data-tone={tone}
    >
      {/* Steady rim tint on the actual border edge */}
      <div
        className="absolute inset-0 rounded-2xl"
        style={{
          boxShadow: `inset 0 0 0 1px rgba(${accentRgb}, 0.55), 0 0 18px rgba(${accentRgb}, 0.28)`,
        }}
      />

      {/* Soft dual arcs — wider ring, no blur (blur breaks the mask) */}
      <div
        className="absolute inset-0 rounded-2xl overflow-hidden"
        style={{
          padding: '5px',
          ...ringMask,
        }}
      >
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
          <div
            className="animate-border-spin-slow"
            style={{
              width: '200vmax',
              height: '200vmax',
              background: dualSweep,
              opacity: 0.55,
            }}
          />
        </div>
      </div>

      {/* Crisp dual highlights on the border ring */}
      <div
        className="absolute inset-0 rounded-2xl overflow-hidden"
        style={{
          padding: '2px',
          ...ringMask,
        }}
      >
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
          <div
            className="animate-border-spin-slow"
            style={{
              width: '200vmax',
              height: '200vmax',
              background: dualSweep,
              opacity: 1,
            }}
          />
        </div>
      </div>
    </div>
  )
}

interface ConsoleTrayProps {
  placement?: 'bottom' | 'rail'
  isExpanded: boolean
  setExpanded: (open: boolean) => void
  activeTab: 'assistant' | 'reminders'
  setActiveTab: (tab: 'assistant' | 'reminders') => void

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
  activeReminders: ActiveReminder[]
  markReminderAsRead: (id: number) => void
  refreshReminders: () => Promise<void>
  onReminderSaved: () => void
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
  const loadingLocalProfile = profilesStatus.find((profile) => profile.loading)
  const isLocalModelLoading = Boolean(loadingLocalProfile)
  const loadingDisplayName = loadingLocalProfile?.display_name?.trim() || 'model'

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
            className={[
              'size-4 animate-spin',
              isLocalModelLoading ? 'text-[#F97316]' : 'text-[#A855F7]',
            ].join(' ')}
            aria-hidden
          />
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-widest text-zinc-500">
              {isLocalModelLoading
                ? `Loading (${loadingDisplayName})`
                : 'APEX processing'}
            </span>
            <div
              className={[
                'h-2 w-40 animate-pulse rounded-full bg-gradient-to-r',
                isLocalModelLoading
                  ? 'from-[#9A3412]/20 via-[#F97316]/45 to-[#9A3412]/20'
                  : 'from-[#0F4DB8]/20 via-[#A855F7]/40 to-[#0F4DB8]/20',
              ].join(' ')}
            />
          </div>
        </div>
      ) : null}

      <div ref={chatEndRef} />
    </div>
  )
}

function ReminderInput({
  refreshReminders,
  onReminderSaved,
}: {
  refreshReminders: () => Promise<void>
  onReminderSaved: () => void
}): ReactElement {
  const [value, setValue] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>): Promise<void> => {
      event.preventDefault()

      const trimmed = value.trim()
      if (!trimmed || isSubmitting) {
        return
      }

      setIsSubmitting(true)
      setError(null)

      try {
        const response = await fetch(REMINDERS_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: trimmed }),
        })

        if (!response.ok) {
          throw new Error(`Reminder save failed (${response.status})`)
        }

        setValue('')
        onReminderSaved()
        await refreshReminders()
      } catch {
        setError('Reminder save failed. Try again.')
      } finally {
        setIsSubmitting(false)
      }
    },
    [isSubmitting, onReminderSaved, refreshReminders, value],
  )

  return (
    <form
      onSubmit={(event) => {
        void handleSubmit(event)
      }}
      className="hud-command-surface w-full rounded-lg bg-zinc-950/20 shadow-none backdrop-blur-none transition-all duration-300 focus-within:border-[#FBBF24]/40"
      aria-label="Add reminder"
    >
      <div className="flex items-center gap-3 px-3 py-2">
        <CheckSquare
          className="size-4 shrink-0 text-[#FBBF24]"
          strokeWidth={1.75}
          aria-hidden
        />
        <input
          type="text"
          value={value}
          onChange={(event) => {
            setValue(event.target.value)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setValue('')
              event.currentTarget.blur()
            }
          }}
          placeholder="Add a reminder..."
          disabled={isSubmitting}
          className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-zinc-500 outline-none"
          aria-label="Reminder text"
          autoComplete="off"
          spellCheck={false}
        />
        {isSubmitting ? (
          <Loader2 className="size-4 shrink-0 animate-spin text-[#39FF88]" aria-hidden />
        ) : null}
      </div>
      {error ? (
        <p className="border-t border-red-500/20 px-3 py-2 text-xs text-red-300">
          {error}
        </p>
      ) : null}
    </form>
  )
}

function RemindersTabContent({
  activeReminders,
  markReminderAsRead,
}: {
  activeReminders: ActiveReminder[]
  markReminderAsRead: (id: number) => void
}): ReactElement {
  return (
    <div className="flex min-h-[16rem] flex-col">
      {activeReminders.length === 0 ? (
        <div className="flex min-h-[12rem] flex-1 items-center justify-center rounded-xl border border-white/[0.06] bg-zinc-950/20 px-4 py-6">
          <p className="text-center font-mono text-xs uppercase tracking-widest text-zinc-500">
            No pending reminders.
          </p>
        </div>
      ) : (
        <ul className="list-fade-mask min-h-0 flex-1 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
          {activeReminders.map((reminder, index) => (
            <ReminderListRow
              key={reminder.id}
              reminder={reminder}
              index={index}
              onMarkRead={markReminderAsRead}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * Bottom console tray: a slim always-docked bar (tabs + AskApex input) that
 * expands inline (no overlay/backdrop) via a max-height transition. Because
 * it lives in normal document flow as a flex sibling of the bento body, its
 * growth naturally compresses the body row above it — the wings/digest
 * switch to their compact renderings and the logo (fixed size, unaffected)
 * visually rises as it re-centers within the shorter column.
 */
export function ConsoleTray({
  placement = 'bottom',
  isExpanded,
  setExpanded,
  activeTab,
  setActiveTab,
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
  activeReminders,
  markReminderAsRead,
  refreshReminders,
  onReminderSaved,
}: ConsoleTrayProps): ReactElement {
  const handleExpand = useCallback((): void => {
    setExpanded(true)
  }, [setExpanded])

  const handleToggle = useCallback((): void => {
    setExpanded(!isExpanded)
  }, [isExpanded, setExpanded])

  const handleAgentSubmit = useCallback(
    (query: string, profile: AssistantProfile): void => {
      setActiveTab('assistant')
      setExpanded(true)
      void queryAssistant(query, profile)
    },
    [queryAssistant, setActiveTab, setExpanded],
  )

  const handleChipSelect = useCallback(
    (query: string): void => {
      setActiveTab('assistant')
      setExpanded(true)
      void queryAssistant(query, activeProfile)
    },
    [activeProfile, queryAssistant, setActiveTab, setExpanded],
  )

  const isLocalModelLoading = profilesStatus.some((profile) => profile.loading)
  const activityTone: ConsoleActivityTone | null = isLocalModelLoading
    ? 'rust'
    : isAssistantQuerying
      ? 'purple'
      : null

  const tabBaseClass =
    'hud-command-surface font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] transition-colors duration-300 px-3 py-1.5 rounded-md border shrink-0'

  const tabs = (
    <div className={`flex shrink-0 items-center gap-2 ${placement === 'rail' ? 'min-w-0 flex-wrap' : ''}`}>
      <button
        type="button"
        onClick={() => {
          setActiveTab('assistant')
          handleExpand()
        }}
        className={[
          tabBaseClass,
          activeTab === 'assistant'
            ? 'border-[#0F4DB8]/50 bg-[#0F4DB8]/15 text-[#7EB3FF] shadow-[0_0_10px_rgba(15,77,184,0.25)]'
            : 'border-white/5 bg-transparent text-zinc-500 hover:border-[#0F4DB8]/30 hover:text-zinc-300',
        ].join(' ')}
        aria-pressed={activeTab === 'assistant'}
      >
        [ ASSISTANT ]
      </button>

      <button
        type="button"
        onClick={() => {
          setActiveTab('reminders')
          handleExpand()
        }}
        className={[
          tabBaseClass,
          activeTab === 'reminders'
            ? 'border-[#FBBF24]/50 bg-[#FBBF24]/10 text-[#FBBF24] shadow-[0_0_10px_rgba(251,191,36,0.2)]'
            : 'border-white/5 bg-transparent text-zinc-500 hover:border-[#FBBF24]/30 hover:text-zinc-300',
        ].join(' ')}
        aria-pressed={activeTab === 'reminders'}
      >
        [ REMINDERS ]
      </button>
    </div>
  )

  const activeContent =
    activeTab === 'assistant' ? (
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
      <RemindersTabContent
        activeReminders={activeReminders}
        markReminderAsRead={markReminderAsRead}
      />
    )

  if (placement === 'rail') {
    if (!isExpanded) {
      return (
        <section
          className="hud-corner-brackets hud-interactive-shell hud-glass relative z-[var(--z-bento-hud)] flex w-full shrink-0 flex-col overflow-hidden rounded-2xl border border-white/10"
          data-slot="console-tray-rail"
          aria-label="Assistant console"
        >
          <span className="hud-corner-bl" aria-hidden />
          <span className="hud-corner-br" aria-hidden />
          <ConsoleActivityGlow tone={activityTone} />

          <div className="hud-inner-lift relative z-[2] flex w-full shrink-0 items-center gap-3 px-3 py-3">
            {tabs}

            <div
              className="min-w-0 flex-1"
              onClick={handleExpand}
              onFocusCapture={handleExpand}
            >
              {activeTab === 'assistant' && askApexEnabled ? (
                <button
                  type="button"
                  onClick={handleExpand}
                  className="hud-command-surface flex w-full items-center gap-3 rounded-lg bg-zinc-950/20 px-3 py-2 text-left transition-colors hover:border-[#0F4DB8]/40 hover:bg-[#0F4DB8]/10"
                  aria-label="Ask APEX"
                >
                  <span
                    className="shrink-0 font-mono text-sm font-semibold text-[#0F4DB8]"
                    aria-hidden
                  >
                    &gt;_
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm text-zinc-500">
                    Ask APEX
                  </span>
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleExpand}
                  className="w-full truncate text-left font-mono text-xs uppercase tracking-widest text-zinc-500 hover:text-zinc-300"
                >
                  &gt;_ View console
                </button>
              )}
            </div>

            <button
              type="button"
              onClick={handleToggle}
              className="shrink-0 rounded-md p-1.5 transition-colors hover:bg-white/5"
              aria-label="Expand console"
              aria-expanded={isExpanded}
            >
              <ChevronUp className="size-4 text-zinc-400 transition-colors hover:text-zinc-200" />
            </button>
          </div>
        </section>
      )
    }

    return (
      <section
        className="hud-corner-brackets hud-interactive-shell hud-glass relative z-[var(--z-bento-hud)] flex h-full min-h-0 w-full flex-col overflow-hidden rounded-2xl border border-white/10"
        data-slot="console-tray-rail"
        aria-label="Assistant console"
      >
        <span className="hud-corner-bl" aria-hidden />
        <span className="hud-corner-br" aria-hidden />
        <ConsoleActivityGlow tone={activityTone} />

        <div className="hud-inner-lift relative z-[2] flex w-full shrink-0 items-start justify-between gap-3 px-3 py-3">
          {tabs}

          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={resetAssistantSession}
              className="rounded-md p-1.5 transition-colors hover:bg-white/5"
              aria-label="Clear session history"
            >
              <RotateCcw className="size-4 text-zinc-400 transition-colors hover:text-rose-400" />
            </button>

            <button
              type="button"
              onClick={handleToggle}
              className="rounded-md p-1.5 transition-colors hover:bg-white/5"
              aria-label="Collapse console"
              aria-expanded={isExpanded}
            >
              <ChevronUp className="size-4 rotate-180 text-zinc-400 transition-colors hover:text-zinc-200" />
            </button>
          </div>
        </div>

        <div className="relative z-[2] min-h-0 flex-1 overflow-y-auto border-t border-white/10 bg-zinc-950/30 p-4 scrollbar-thin">
          {activeContent}
        </div>

        {activeTab === 'assistant' && askApexEnabled ? (
          <footer className="relative z-[2] shrink-0 border-t border-white/10 bg-zinc-950/40 p-3">
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
        ) : activeTab === 'reminders' ? (
          <footer className="relative z-[2] shrink-0 border-t border-white/10 bg-zinc-950/40 p-3">
            <ReminderInput
              refreshReminders={refreshReminders}
              onReminderSaved={onReminderSaved}
            />
          </footer>
        ) : null}
      </section>
    )
  }

  return (
    <section
      className="hud-corner-brackets hud-interactive-shell hud-glass relative z-[var(--z-bento-hud)] flex w-full shrink-0 flex-col overflow-visible rounded-2xl border border-white/10"
      data-slot="console-tray"
      aria-label="Assistant console"
    >
      <span className="hud-corner-bl" aria-hidden />
      <span className="hud-corner-br" aria-hidden />
      <ConsoleActivityGlow tone={activityTone} />

      {/* Persistent docked row — always in normal document flow, never displaces the logo/wings above it */}
      <div className="hud-inner-lift relative z-[2] flex w-full shrink-0 items-center gap-3 px-3 py-2.5 sm:px-4">
        {tabs}

        <div
          className={`min-w-0 flex-1 transition-opacity duration-300 ${isExpanded ? 'pointer-events-none opacity-0' : 'opacity-100'}`}
          onClick={handleExpand}
          onFocusCapture={handleExpand}
          aria-hidden={isExpanded}
        >
          {activeTab === 'assistant' && askApexEnabled ? (
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
          ) : (
            <button
              type="button"
              onClick={handleExpand}
              className="w-full truncate text-left font-mono text-xs uppercase tracking-widest text-zinc-500 hover:text-zinc-300"
            >
              &gt;_ View console
            </button>
          )}
        </div>

        {isExpanded ? (
          <button
            type="button"
            onClick={resetAssistantSession}
            className="shrink-0 rounded-md p-1.5 transition-colors hover:bg-white/5"
            aria-label="Clear session history"
          >
            <RotateCcw className="size-4 text-zinc-400 transition-colors hover:text-rose-400" />
          </button>
        ) : null}

        <button
          type="button"
          onClick={handleToggle}
          className="shrink-0 rounded-md p-1.5 transition-colors hover:bg-white/5"
          aria-label={isExpanded ? 'Collapse console' : 'Expand console'}
          aria-expanded={isExpanded}
        >
          <ChevronUp
            className={`size-4 text-zinc-400 transition-transform duration-500 hover:text-zinc-200 ${isExpanded ? 'rotate-180' : ''}`}
          />
        </button>
      </div>

      {/* Inline expandable body — grows via max-height in normal flow, no portal/backdrop */}
      <div
        className={`console-tray-panel relative z-[2] flex min-h-0 flex-col overflow-hidden border-t transition-[max-height,opacity] ${
          isExpanded
            ? 'max-h-[min(48vh,30rem)] border-white/10 opacity-100'
            : 'max-h-0 border-transparent opacity-0'
        }`}
        aria-hidden={!isExpanded}
      >
        <div className="min-h-0 flex-1 overflow-y-auto bg-zinc-950/30 p-4 scrollbar-thin">
          {activeContent}
        </div>

        {activeTab === 'assistant' && askApexEnabled ? (
          <footer className="shrink-0 border-t border-white/10 bg-zinc-950/40 p-4">
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
        ) : activeTab === 'reminders' ? (
          <footer className="shrink-0 border-t border-white/10 bg-zinc-950/40 p-4">
            <ReminderInput
              refreshReminders={refreshReminders}
              onReminderSaved={onReminderSaved}
            />
          </footer>
        ) : null}
      </div>
    </section>
  )
}
