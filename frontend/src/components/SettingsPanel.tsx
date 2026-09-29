import {
  useCallback,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactElement,
  type RefObject,
} from 'react'
import { createPortal } from 'react-dom'
import { Loader2, RotateCcw, Settings, X } from 'lucide-react'

import DataSourcesView from './settings/DataSourcesView'
import IntelligenceView from './settings/IntelligenceView'
import IntegrationsView from './settings/IntegrationsView'
import VoiceAudioView from './settings/VoiceAudioView'
import SystemStatusView from './settings/SystemStatusView'
import {
  SETTINGS_CATEGORIES,
  getCategoryDirtyMap,
  type SettingsCategoryKey,
} from './settings/settingsCategories'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { useLlamaCppStatus } from '../hooks/useLlamaCppStatus'
import { useMcpStatus, type McpStatusState } from '../hooks/useMcpStatus'
import { useActivityReportFolderStatus } from '../hooks/useActivityReportFolderStatus'
import { useMicrosoftTodoStatus } from '../hooks/useMicrosoftTodoStatus'
import { useSettingsEditor } from '../hooks/useSettingsEditor'
import {
  buildSettingsTimingRuntime,
  resolveEffectiveTiming,
} from '../lib/settings'
import type { ModelCatalogEntry } from '../types/telemetry'
import type { RuntimeSettings, SettingsResponse } from '../types/settings'

interface SettingsPanelProps {
  open: boolean
  onClose: () => void
  restoreFocusRef?: RefObject<HTMLElement | null>
  briefingRunning: boolean
  briefingStep: number | null
  isSpeaking: boolean
  isCortexQuerying: boolean
  modelCatalog: ModelCatalogEntry[]
  cortexAgentHydrated: boolean
  failedConnectors: string[]
  hasTelemetryEvidence: boolean
  onApplied: (response: SettingsResponse, previousSettings: RuntimeSettings) => void
  mcpRuntime?: McpStatusState
}

export default function SettingsPanel({
  open,
  onClose,
  restoreFocusRef,
  briefingRunning,
  briefingStep,
  isSpeaking,
  isCortexQuerying,
  modelCatalog,
  cortexAgentHydrated,
  failedConnectors,
  hasTelemetryEvidence,
  onApplied,
  mcpRuntime: sharedMcpRuntime,
}: SettingsPanelProps): ReactElement | null {
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const [activeTab, setActiveTab] = useState<SettingsCategoryKey>('data_sources')

  const {
    loadStatus,
    loadError,
    envelope,
    baseline,
    draft,
    isDirty,
    saving,
    saveError,
    setDraft,
    save,
    resetDraft,
  } = useSettingsEditor({ open, onApplied })

  const polledMcpRuntime = useMcpStatus(open && sharedMcpRuntime === undefined)
  const mcpRuntime = sharedMcpRuntime ?? polledMcpRuntime
  const llamaCppRuntime = useLlamaCppStatus(open)
  const activityReportFolderRuntime = useActivityReportFolderStatus(open)
  const refreshActivityReportFolderStatus = activityReportFolderRuntime.refresh
  const reportFolderStatus = activityReportFolderRuntime.status
  const reportFolderAvailability = activityReportFolderRuntime.unavailable

  const microsoftTodoRuntime = useMicrosoftTodoStatus(open)
  useFocusTrap(open, dialogRef, restoreFocusRef)

  const timingRuntime = useMemo(
    () =>
      buildSettingsTimingRuntime({
        briefingRunning,
        briefingStep,
        isSpeaking,
        isCortexQuerying,
      }),
    [briefingRunning, briefingStep, isSpeaking, isCortexQuerying],
  )

  const featuresTiming = resolveEffectiveTiming('features', timingRuntime)
  const marketTiming = resolveEffectiveTiming('market', timingRuntime)
  const calendarTiming = resolveEffectiveTiming('calendar', timingRuntime)
  const modulesTiming = resolveEffectiveTiming('modules', timingRuntime)
  const agentQueriesTiming = resolveEffectiveTiming('agent_queries', timingRuntime)
  const voiceTiming = resolveEffectiveTiming('voice', timingRuntime)
  const mcpTiming = resolveEffectiveTiming('mcp', timingRuntime)
  const llamaCppTiming = resolveEffectiveTiming('llama_cpp', timingRuntime)

  const dirtyMap = useMemo(
    () => getCategoryDirtyMap(baseline, draft),
    [baseline, draft],
  )

  const dirtyCategoryLabels = useMemo(
    () =>
      SETTINGS_CATEGORIES.filter((c) => dirtyMap[c.key]).map((c) => c.label),
    [dirtyMap],
  )

  const dirtyCount = dirtyCategoryLabels.length

  const dirtySummary = useMemo(() => {
    if (dirtyCount === 0) {
      return 'All settings in sync with runtime'
    }
    return `${dirtyCount} unsaved change${dirtyCount === 1 ? '' : 's'} in ${dirtyCategoryLabels.join(', ')}`
  }, [dirtyCount, dirtyCategoryLabels])

  const activeCategoryMeta = useMemo(
    () =>
      SETTINGS_CATEGORIES.find((c) => c.key === activeTab) ??
      SETTINGS_CATEGORIES[0],
    [activeTab],
  )

  const reportFolderStatusMessage = reportFolderAvailability
    ? 'Report folder status is unavailable.'
    : !reportFolderStatus
      ? 'Checking report folder status…'
      : reportFolderStatus.last_error ??
        (reportFolderStatus.state === 'disabled'
          ? 'Disabled. APEX will not read this folder.'
          : reportFolderStatus.state === 'demo_mode'
            ? 'Unavailable in demo mode.'
            : reportFolderStatus.state === 'not_configured'
              ? 'Choose an absolute folder path.'
              : reportFolderStatus.state === 'folder_unavailable'
                ? 'Folder unavailable. APEX will retry when it scans again.'
                : reportFolderStatus.state === 'scan_error'
                  ? 'Some files could not be imported; APEX will retry.'
                  : `Ready. Latest scan imported ${reportFolderStatus.last_imported_count} report${reportFolderStatus.last_imported_count === 1 ? '' : 's'}.`)

  const requestClose = useCallback(() => {
    if (isDirty || saving) {
      const confirmed = window.confirm(
        'You have unsaved settings changes. Discard them and close?',
      )
      if (!confirmed) {
        return
      }
    }
    onClose()
  }, [isDirty, saving, onClose])

  const handleBackdropClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      if (event.target === event.currentTarget) {
        requestClose()
      }
    },
    [requestClose],
  )

  const handleDialogKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        requestClose()
      }
    },
    [requestClose],
  )

  const handleTabListKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      const currentIndex = SETTINGS_CATEGORIES.findIndex((c) => c.key === activeTab)
      if (currentIndex === -1) return

      let nextIndex: number | null = null
      if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
        event.preventDefault()
        nextIndex = (currentIndex + 1) % SETTINGS_CATEGORIES.length
      } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
        event.preventDefault()
        nextIndex = (currentIndex - 1 + SETTINGS_CATEGORIES.length) % SETTINGS_CATEGORIES.length
      } else if (event.key === 'Home') {
        event.preventDefault()
        nextIndex = 0
      } else if (event.key === 'End') {
        event.preventDefault()
        nextIndex = SETTINGS_CATEGORIES.length - 1
      }

      if (nextIndex !== null) {
        const nextKey = SETTINGS_CATEGORIES[nextIndex].key
        setActiveTab(nextKey)
        tabRefs.current[nextKey]?.focus()
      }
    },
    [activeTab],
  )

  const handleSave = useCallback(() => {
    void save().then((saved) => {
      if (saved) {
        void mcpRuntime.refresh()
        void refreshActivityReportFolderStatus()
      }
    })
  }, [save, mcpRuntime, refreshActivityReportFolderStatus])

  const providerRows = useMemo(() => {
    const cloud = modelCatalog.filter((model) => model.runtime === 'cloud')
    const local = modelCatalog.filter((model) => model.runtime === 'local')
    const configuredCloud = cloud.filter((model) => model.status !== 'disabled').length
    const verifiedCloud = cloud.filter((model) => model.status === 'verified').length
    const localAvailable = local.some((model) => model.status === 'available')
    const activeLocal = local.find((model) => model.active && model.loaded_model)

    return {
      cloud: !cortexAgentHydrated
        ? { value: 'Checking…', tone: 'neutral' as const }
        : configuredCloud > 0
          ? {
              value: `${configuredCloud} configured · ${verifiedCloud} verified`,
              tone: verifiedCloud > 0 ? ('ok' as const) : ('neutral' as const),
            }
          : { value: 'Not configured', tone: 'error' as const },
      local: !cortexAgentHydrated
        ? { value: 'Checking…', tone: 'neutral' as const }
        : localAvailable
          ? { value: 'Reachable', tone: 'ok' as const }
          : {
              value: local.some(
                (model) =>
                  model.status === 'ollama_unreachable' ||
                  model.status === 'provider_unreachable',
              )
                ? 'Unreachable'
                : 'Unavailable',
              tone: 'error' as const,
            },
      activeModel:
        activeLocal?.loaded_model?.model ??
        activeLocal?.loaded_model?.name ??
        'None',
    }
  }, [cortexAgentHydrated, modelCatalog])

  if (!open) {
    return null
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-3 sm:p-6 backdrop-blur-md transition-opacity duration-300 motion-reduce:transition-none"
      onClick={handleBackdropClick}
      role="presentation"
    >
      <div
        ref={dialogRef}
        className="hud-corner-brackets hud-glass relative flex h-[82vh] max-h-[820px] min-h-[480px] w-full max-w-5xl flex-col rounded-2xl border border-white/10 p-4 sm:p-6 shadow-2xl outline-none transition-all duration-300 motion-reduce:transition-none"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={handleDialogKeyDown}
      >
        <span className="hud-corner-bl" aria-hidden />
        <span className="hud-corner-br" aria-hidden />

        {/* Modal Header */}
        <header className="mb-4 flex shrink-0 items-center justify-between gap-4 border-b border-white/10 pb-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="hud-icon-badge size-8 text-[color:var(--hud-accent)]">
              <Settings className="size-4" strokeWidth={2} aria-hidden="true" />
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <h2
                id={titleId}
                className="font-orbitron text-sm font-semibold tracking-[0.14em] text-[color:var(--hud-text)] uppercase"
              >
                Runtime Settings
              </h2>
              <span className="font-mono text-xs text-zinc-500" aria-hidden="true">
                //
              </span>
              <span className="font-orbitron text-xs tracking-[0.12em] text-[color:var(--hud-accent)] uppercase">
                {activeCategoryMeta.label}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={requestClose}
            className="inline-flex items-center justify-center rounded-lg border border-white/10 bg-white/5 p-1.5 text-[color:var(--hud-text)] transition-colors hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            aria-label="Close settings"
          >
            <X className="size-4" strokeWidth={2} />
          </button>
        </header>

        {/* Two-Pane Body Container */}
        <div className="flex flex-1 min-h-0 flex-col lg:flex-row gap-4 lg:gap-6 overflow-hidden">
          {/* Category Navigation Rail (horizontal scroll strip on <lg, vertical rail on >=lg) */}
          <nav
            role="tablist"
            aria-label="Settings categories"
            onKeyDown={handleTabListKeyDown}
            className="flex shrink-0 flex-row lg:flex-col gap-1.5 overflow-x-auto lg:overflow-x-visible border-b lg:border-b-0 lg:border-r border-white/10 pb-2.5 lg:pb-0 lg:pr-4 w-full lg:w-60 scrollbar-thin"
          >
            <div className="hidden lg:block mb-1 px-2 font-mono text-[9px] uppercase tracking-[0.2em] text-zinc-500">
              Categories
            </div>
            {SETTINGS_CATEGORIES.map((cat) => {
              const isSelected = activeTab === cat.key
              const isCategoryDirty = dirtyMap[cat.key]
              const Icon = cat.icon
              return (
                <button
                  key={cat.key}
                  ref={(el) => {
                    tabRefs.current[cat.key] = el
                  }}
                  id={`settings-tab-${cat.key}`}
                  role="tab"
                  aria-selected={isSelected}
                  aria-controls={`settings-tabpanel-${cat.key}`}
                  tabIndex={isSelected ? 0 : -1}
                  onClick={() => setActiveTab(cat.key)}
                  className={`group relative flex shrink-0 items-center justify-between rounded-lg lg:rounded-xl border px-3 py-1.5 lg:p-2.5 text-left transition-all duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] ${
                    isSelected
                      ? 'border-[color:var(--hud-accent)]/50 bg-[color:var(--hud-accent)]/15 text-white shadow-[0_0_16px_rgba(15,77,184,0.2)]'
                      : 'border-white/5 bg-white/[0.02] text-zinc-400 hover:border-white/15 hover:bg-white/[0.05] hover:text-zinc-200'
                  }`}
                >
                  <div className="flex min-w-0 items-center gap-2 lg:gap-3">
                    <span
                      className={`hud-icon-badge size-6 lg:size-8 shrink-0 transition-colors ${
                        isSelected
                          ? 'border-[color:var(--hud-accent)]/40 bg-[color:var(--hud-accent)]/20 text-white'
                          : 'text-zinc-400 group-hover:text-zinc-200'
                      }`}
                    >
                      <Icon className="size-3 lg:size-4" aria-hidden="true" />
                    </span>
                    <div className="min-w-0">
                      <div className="font-orbitron text-xs font-semibold uppercase tracking-[0.12em] whitespace-nowrap lg:whitespace-normal truncate">
                        {cat.label}
                      </div>
                      <div className="hidden lg:block font-mono text-[10px] text-zinc-500 truncate group-hover:text-zinc-400">
                        {cat.description}
                      </div>
                    </div>
                  </div>

                  {isCategoryDirty ? (
                    <span
                      className="size-2 rounded-full bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.9)] animate-pulse shrink-0 ml-2"
                      aria-label="Unsaved changes in category"
                      title="Unsaved changes in this category"
                    />
                  ) : null}
                </button>
              )
            })}
          </nav>

          {/* Right Content Canvas */}
          <div
            id={`settings-tabpanel-${activeTab}`}
            role="tabpanel"
            aria-labelledby={`settings-tab-${activeTab}`}
            tabIndex={0}
            className="flex-1 min-h-0 overflow-y-auto pr-1 sm:pr-2 scrollbar-thin focus-visible:outline-none"
          >
            {loadStatus === 'loading' || loadStatus === 'idle' ? (
              <div className="space-y-3 py-6" aria-busy="true" aria-live="polite">
                <div className="h-4 w-full animate-pulse rounded bg-white/5" />
                <div className="h-4 w-5/6 animate-pulse rounded bg-white/5" />
                <div className="h-4 w-4/5 animate-pulse rounded bg-white/5" />
              </div>
            ) : null}

            {loadStatus === 'error' ? (
              <p
                className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200"
                role="alert"
              >
                {loadError ?? 'Failed to load settings.'}
              </p>
            ) : null}

            {loadStatus === 'ready' && draft ? (
              <>
                {activeTab === 'data_sources' ? (
                  <DataSourcesView
                    titleId={titleId}
                    draft={draft}
                    setDraft={setDraft}
                    featuresTiming={featuresTiming}
                    marketTiming={marketTiming}
                    calendarTiming={calendarTiming}
                    modulesTiming={modulesTiming}
                  />
                ) : null}

                {activeTab === 'intelligence' ? (
                  <IntelligenceView
                    titleId={titleId}
                    draft={draft}
                    setDraft={setDraft}
                    agentQueriesTiming={agentQueriesTiming}
                    llamaCppTiming={llamaCppTiming}
                    llamaCppRuntime={llamaCppRuntime}
                  />
                ) : null}

                {activeTab === 'integrations' ? (
                  <IntegrationsView
                    titleId={titleId}
                    baseline={baseline}
                    draft={draft}
                    setDraft={setDraft}
                    mcpTiming={mcpTiming}
                    mcpRuntime={mcpRuntime}
                    microsoftTodoRuntime={microsoftTodoRuntime}
                    reportFolderStatusMessage={reportFolderStatusMessage}
                    reportFolderStatus={reportFolderStatus}
                  />
                ) : null}

                {activeTab === 'voice_audio' ? (
                  <VoiceAudioView
                    titleId={titleId}
                    draft={draft}
                    setDraft={setDraft}
                    voiceTiming={voiceTiming}
                  />
                ) : null}

                {activeTab === 'system_status' ? (
                  <SystemStatusView
                    titleId={titleId}
                    envelope={envelope}
                    baseline={baseline}
                    providerRows={providerRows}
                    failedConnectors={failedConnectors}
                    hasTelemetryEvidence={hasTelemetryEvidence}
                  />
                ) : null}
              </>
            ) : null}
          </div>
        </div>

        {/* Modal Footer */}
        <footer className="mt-4 flex shrink-0 flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-t border-white/10 pt-4">
          {/* Status / Error Summary */}
          <div className="flex flex-col gap-1 min-w-0">
            {saveError ? (
              <p
                className="rounded border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-xs text-red-200"
                role="alert"
              >
                {saveError}
              </p>
            ) : null}
            <div className="flex items-center gap-2">
              {isDirty ? (
                <>
                  <span
                    className="size-2 rounded-full bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.9)] animate-pulse shrink-0"
                    aria-hidden="true"
                  />
                  <span className="font-mono text-xs text-amber-200/90 truncate">
                    {dirtySummary}
                  </span>
                </>
              ) : (
                <>
                  <span
                    className="size-1.5 rounded-full bg-emerald-400/80 shrink-0"
                    aria-hidden="true"
                  />
                  <span className="font-mono text-xs text-zinc-500">
                    All settings in sync with runtime
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-2 self-end sm:self-auto shrink-0">
            <button
              type="button"
              onClick={resetDraft}
              disabled={!isDirty || saving || loadStatus !== 'ready'}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] text-[color:var(--hud-text)] uppercase transition-colors hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RotateCcw className="size-3" aria-hidden="true" />
              <span>Reset Draft</span>
            </button>
            <button
              type="button"
              onClick={requestClose}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] text-[color:var(--hud-text)] uppercase transition-colors hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            >
              Close
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!isDirty || saving || loadStatus !== 'ready'}
              aria-label="Save changes"
              className="inline-flex items-center gap-1.5 rounded-lg border border-[color:var(--hud-accent)]/40 bg-[color:var(--hud-accent)]/20 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] text-[color:var(--hud-text)] uppercase transition-colors hover:bg-[color:var(--hud-accent)]/30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {saving ? (
                <>
                  <Loader2 className="size-3 animate-spin" aria-hidden="true" />
                  <span>Saving…</span>
                </>
              ) : (
                <span>Save Changes</span>
              )}
            </button>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  )
}
